# Phase-2A Specification — Schematic ↔ IPCAT Cross-Verification Engine

**Type:** Executable specification. **No implementation, no code changes, no commits.** This document is implementation-ready: a developer should be able to build the engine from it without further design decisions, and a reviewer should be able to accept/reject the build against it.
**Inputs read:** `docs/LIVE_IPCAT_RETROSPECTIVE_AND_PHASE2_PLAN.md`, `docs/PHASE1B_LIVE_EVIDENCE.md`, `docs/PHASE1C_LIVE_EVIDENCE.md`.
**Reuses (unchanged):** WP-C Cardinality Authority — `orchestrator/reasoning/cardinality.py`, `orchestrator/reasoning/cardinality_config.py` (committed `28f2f07`).
**Date:** 2026-07-14

---

## 0. Scope, invariants, and non-goals

**What this engine is.** A pure, deterministic, **diagnostic-only** cross-verification pass that reads a target's schematic/board view and the live IPCAT silicon view, compares them along five tracks, and emits per-check verdict rows, a reviewer worklist, and a confidence report. It renders as an **additive report section**, exactly like the Confidence Ledger and the Cardinality Authority.

**Hard invariants (inherited from WP-C / Phase-1, non-negotiable):**
1. **No gating.** The engine never blocks, promotes, or mutates a pipeline decision. A warning costs a reviewer one glance (C.9 asymmetry). It never hard-fails onboarding.
2. **No DTS mutation.** T5 reads and diagnoses the DTS; it never rewrites it.
3. **Pure + deterministic.** Identical `(schematic snapshot, IPCAT snapshot)` → byte-identical rows. All I/O (the live IPCAT calls) happens in a **collector** stage that produces a frozen snapshot; the **comparison core** is pure and unit-testable against fixtures — the same split WP-C already uses (`compare_element_counts` is pure; the live call was done separately in Phase-1C).
4. **No fabricated values.** Unknown is recorded as `UNAVAILABLE`/`NOT_CROSS_CHECKABLE`, never guessed. The `swi_search_swi` exhaustiveness caveat (W4) is a first-class, recorded attribute — not an assumption.
5. **Security envelope.** Read-only IPCAT allow-list; TLS `verify=True`; `auth.json`/`.credentials.json` never read; token by reference only.

**Non-goals:** DTS generation (Phase-2B, explicitly sequenced after 2A); schematic parsing from raw PDFs/CAD (the engine consumes already-extracted `profile.json` facts, not raw schematics); any new onboarding gate.

---

## 1. Engine architecture

### 1.1 Three-stage pipeline

```
                 ┌──────────────────────────────────────────────────────────┐
                 │  STAGE 1 — COLLECTOR (impure; the only stage doing I/O)    │
                 │                                                            │
 profile.json ──▶│  • load schematic-derived facts (SchematicFactSet)        │
 board layer  ──▶│  • load DTS facts (DtsFactSet)                             │
 draft DTS    ──▶│  • query live IPCAT read-only  ──▶ IpcatAuthoritySnapshot  │
 resolved tgt ──▶│      (chips_list_chips, cores_list_core_instances,         │
 (Phase-1B)      │       swi_search_swi + per-track authorities)              │
                 │  • freeze everything into a VerificationInput bundle       │
                 └──────────────────────────────────────────────────────────┘
                                          │  (frozen snapshot — no live handles cross this line)
                                          ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │  STAGE 2 — COMPARISON CORE (pure; deterministic)           │
                 │                                                            │
                 │  for each track T1..T5:                                    │
                 │     rows += track.compare(schematic, dts, ipcat, kb)       │
                 │  T3 delegates counts to WP-C compare_element_counts(gc)    │
                 │     (called UNCHANGED)                                     │
                 └──────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │  STAGE 3 — RENDERER / EMITTER (pure)                        │
                 │  • VerificationRow[]  → phase2a_verification.json          │
                 │  • ReviewerWorklist   (REVIEW_REQUIRED rows only)          │
                 │  • ConfidenceReport   (per-track rollup)                   │
                 │  • additive report section (like Ledger / Cardinality)     │
                 └──────────────────────────────────────────────────────────┘
```

**Why the collector/core split is mandatory:** it is what makes replay (§5) and unit testing possible. The live IPCAT snapshot is captured once, frozen (with `evidence_ts`, tool names, and query args recorded), and the pure core can then be re-run offline against that snapshot forever. This is the exact discipline that let Phase-1C run WP-C's pure `compare_element_counts` against a captured live `catalog` lane.

### 1.2 Inputs (VerificationInput bundle)

| Input | Source | Contents used | Notes |
|---|---|---|---|
| **Resolved target** | Phase-1B artifact (`phase1b_live.json`) | `chip_id`, `canonical_name`, `alias`, `family` | The key for every IPCAT lookup. Engine **requires** a RESOLVED target; ABSENT/AMBIGUOUS → engine refuses to run (records why). |
| **Schematic-derived facts** | `targets/<t>/profile.json` + board layer | codecs, bus declaration (`soundwire.present`, `master_count`), GPIO/pinmux (I²S8), power domains | The "design intent" side of every comparison. |
| **DTS inputs** | `targets/<t>/…/*.dtsi`, `*.dts` (e.g. `nord-sa8797p.dtsi`) | compatible strings, firmware paths, power-domain refs, `qcom,board-id`/`msm-id` if present | Read-only. T5's subject. |
| **Prior element_counts** | `targets/<t>/qgenie_analysis.json` (top-level `element_counts`) | dt / evidence / proposal lanes per class | Feeds T3 → WP-C directly, same shape Phase-1C used. |
| **IPCAT authority snapshot** | Live read-only IPCAT | see §1.3 | The authority side. Captured once, frozen. |
| **KB divergence rules** | existing WP-C KB mechanism + new per-track rules | benign-divergence rule ids per track/class | Reused, not reinvented. |

### 1.3 IPCAT authority snapshot — verified vs. unverified tools

**Live-verified in Phase-1 (safe to depend on now):**

| Tool | Returns | Used by |
|---|---|---|
| `chips_list_chips` | full chip catalog (733 rows) | target re-confirm, T5 silicon identity |
| `cores_list_core_instances(chip)` | audio DSP subsystem enumeration | T3 (`dsp_subsystem_instance`) |
| `swi_search_swi(chip, term)` | named register-block search (**capped, relevance-ranked**) | T2, T3 (`soundwire_master`, `lpass_macro_instance`) — **always via the union+stability method (W4)** |

**Required but NOT yet verified (MUST-FIX discovery spike — see §6):** GPIO/pinmux function tables (T1), codec/DAI connectivity authority (T4). The retrospective names these as *examples*; **no live tool was confirmed for them.** Per invariant #4 the spec does **not** invent tool names. Until a discovery spike confirms an authority, **T1 and T4 emit `NOT_CROSS_CHECKABLE` with reason `authority_tool_unverified`** — they are architecturally present and fully specified, but honestly report that their authority is not yet mapped. This is a legitimate recorded outcome, not a stub.

### 1.4 Outputs

1. **`phase2a_verification.json`** — the full row set + snapshot provenance (schema in §4).
2. **Reviewer worklist** — the subset of rows with `verdict == REVIEW_REQUIRED` (and the `DISAGREE_WITH_AUTHORITY` rows that map to it), each with a concrete `review_actions[]`.
3. **Confidence report** — per-track rollup: counts of each verdict, aggregate confidence, and any propagation discounts applied.
4. **Additive report section** — human-rendered, same treatment as Confidence Ledger / Cardinality Authority.

---

## 2. Validation tracks

Every track implements the same interface:

```
Track.compare(schematic, dts, ipcat_snapshot, kb) -> list[VerificationRow]
```

and every row carries `{track, subject, source, authority, source_value, authority_value, verdict, confidence, rule_id, review_actions, citations, notes}` (§4). Tracks are independent and may run in any order; the **confidence-propagation** step (§3.4) runs after all tracks and only *annotates* confidence — it never changes a verdict.

---

### Track T1 — GPIO Validation

- **Purpose:** every audio pin the design assigns (I²S8 pinmux, GPIO number, drive strength) is a pin the resolved silicon actually exposes and can mux to the claimed audio function.
- **Inputs (source):** `profile.json` pinmux/GPIO block + board layer — pin id, requested function, drive strength.
- **IPCAT authorities:** per-chip GPIO/pinmux function map. **UNVERIFIED** — requires the §6 discovery spike. Until then T1 rows are `NOT_CROSS_CHECKABLE (authority_tool_unverified)`.
- **Verdict rules (once authority is mapped):**
  - Pin exists AND function is muxable on it → `MATCH`.
  - Pin exists, function muxable, but a secondary attribute (drive strength/bias) differs → `PARTIAL_MATCH`.
  - Pin exists but silicon cannot mux the claimed audio function to it → `DISAGREE_WITH_AUTHORITY`.
  - Pin does not exist on silicon → `DISAGREE_WITH_AUTHORITY` (hard mismatch).
  - Authority tool unmapped/unavailable → `NOT_CROSS_CHECKABLE`.
- **Confidence rules:** `MATCH` on a DIRECT pin-map lookup = high. A verdict resting on a name-heuristic (not a structured pin table) is *provisional*. UNAVAILABLE contributes no confidence.
- **Reviewer actions:** on `DISAGREE_WITH_AUTHORITY` — "verify pin `<n>` audio-function assignment against silicon pinmux; correct board/DTS pinmux if the pin cannot carry the function." On `NOT_CROSS_CHECKABLE (authority_tool_unverified)` — "run the T1 authority discovery spike (§6)."

---

### Track T2 — Bus Validation

- **Purpose:** the declared audio bus topology (I²S-only vs SoundWire; master count) matches the silicon SWI surface. This is the track that would catch "Nord accidentally wired for SoundWire" or the inverse.
- **Inputs (source):** `profile.json` — `soundwire.present`, `soundwire.master_count`, I²S controller declaration.
- **IPCAT authorities:** `swi_search_swi` **union+stability** over `{SOUNDWIRE_MASTER, SWR_MSTR, SWR}` (verified in Phase-1C) → count of named SoundWire master blocks; I²S controller blocks analogously. **Verified tool.**
- **Verdict rules:**
  - Design `soundwire.present=false, master_count=0` AND silicon shows 0 master blocks → `MATCH` (Nord's live-corroborated case).
  - Design master_count == silicon master-block count (both > 0) → `MATCH`.
  - Counts differ → `DISAGREE_WITH_AUTHORITY`.
  - The design side self-flagged `ambiguous` (cf. D5 Eliza "1 or 2") → `NOT_CROSS_CHECKABLE` regardless of the silicon integer (WP-C correctness rule 2 — never manufacture a verdict from a disowned number).
  - `swi_search_swi` result at/above cap (possible truncation) → verdict marked *provisional*, confidence downgraded, `notes` records the caveat.
- **Confidence rules:** high when the union set is stable and below cap; *provisional* when at cap; `NOT_CROSS_CHECKABLE` when the source is ambiguous.
- **Reviewer actions:** on disagreement — "reconcile declared bus topology with silicon SWI blocks; confirm board is I²S vs SoundWire." On provisional — "re-run union with additional query terms to confirm below-cap."

---

### Track T3 — Audio Resource Validation  *(delegates to WP-C, unchanged)*

- **Purpose:** LPASS macros, DSP subsystems, and (where present) AudioReach ports match between design intent and silicon. **This track already ran live in Phase-1C** and surfaced D4.
- **Inputs (source):** prior `element_counts` (dt/evidence/proposal) from `qgenie_analysis.json`.
- **IPCAT authorities:** live `lpass_macro_instance` (swi union), `dsp_subsystem_instance` (`cores_list_core_instances`) — injected as the `catalog` lane, exactly as Phase-1C did.
- **Mechanism (MANDATORY reuse):** T3 **constructs the `gc["audio_topology"]["element_counts"]` bundle and calls `compare_element_counts(gc)` UNCHANGED**, then maps each WP-C row into a `VerificationRow` (mapping table in §3.5). T3 adds **no** new counting logic — the anti-`len()` discipline lives in the collector's use of the union+stability method.
- **Verdict rules:** inherited verbatim from WP-C `_verdict` (see §3.5 mapping). D4 (`disagree_with_authority`) and D5 (`not_cross_checkable` via `ambiguous:true`) reproduce exactly.
- **Confidence rules:** WP-C's `warning` flag + count of usable lanes; ≥2 DIRECT lanes agreeing = high; capped-swi authority = provisional.
- **Reviewer actions:** on `DISAGREE_WITH_AUTHORITY` (D4) — "reconcile proposal LPASS macro count (2) vs live catalog (4): is 4 the true instance count or a naming-scope artifact?"

---

### Track T4 — Connectivity Validation

- **Purpose:** codec ↔ SoC data paths are consistent end-to-end — each codec (Nord: TI PCM1681 DAC, ADI ADAU1979 ADC) hangs off a controller/port the silicon can actually drive; no orphaned codec, no path to a non-existent DAI.
- **Inputs (source):** `profile.json` codec list + which I²S/controller each is wired to; DTS DAI-link references.
- **IPCAT authorities:** controller/port existence + capability. **UNVERIFIED** — requires §6 discovery spike (same status as T1). Until then `NOT_CROSS_CHECKABLE (authority_tool_unverified)`.
- **Verdict rules (once authority mapped):**
  - Codec's controller exists on silicon AND port is capable → `MATCH`.
  - Controller exists but a capability attribute (channel count/format) differs → `PARTIAL_MATCH`.
  - Codec wired to a controller/port the silicon does not expose → `DISAGREE_WITH_AUTHORITY`.
  - Codec present in design but no path found → `DISAGREE_WITH_AUTHORITY` (orphaned codec).
- **Confidence rules:** high on a DIRECT controller/port lookup; provisional on name-heuristic matching.
- **Reviewer actions:** on disagreement — "verify codec `<part>` → controller `<id>` path against silicon; fix DAI-link or codec assignment." Unmapped authority → "run T4 discovery spike."

---

### Track T5 — DTS Consistency Validation

- **Purpose:** the draft/generated DTS is internally consistent and consistent with the resolved **silicon identity**. This is the track that catches the **donor bug**: `qcom,sa8775p-adsp-pas` + `sa8775p/adsp.mbn` + LCX/LMX power domains copied from LeMans into an SA8797P DTS (the repo's own `FIXME(sa8797p-audio)`).
- **Inputs (source):** DTS compatible strings, firmware paths, power-domain refs, `qcom,board-id`/`msm-id`.
- **IPCAT authorities:** `chips_list_chips` (silicon identity = SA8797P) + expected compatible/firmware namespace for the resolved family. **Verified for identity**; the *expected-namespace* rule is a KB rule (deterministic, documented), not a live lookup.
- **Verdict rules:**
  - DTS compatible/firmware namespace matches resolved silicon family → `MATCH`.
  - DTS uses a **donor** namespace (`sa8775p*`) while silicon is SA8797P → `DISAGREE_WITH_AUTHORITY` (the donor bug — high-severity, but still diagnostic, never hard-fail).
  - Power-domain refs copied from a donor and flagged by an in-DTS `FIXME` → `DISAGREE_WITH_AUTHORITY` with `notes` citing the FIXME.
  - `qcom,board-id`/`msm-id` absent (cannot pin revision) → that sub-check is `NOT_CROSS_CHECKABLE` (this is the exact revision-pin gap noted in `NORD_TARGET_IDENTIFICATION.md`).
  - A donor reuse that a KB rule marks as an accepted interim bring-up shortcut → `PARTIAL_MATCH` + `benign_divergence` rule id (only if such a rule is registered; otherwise it is a full disagreement).
- **Confidence rules:** identity match against `chips_list_chips` = high (DIRECT); namespace-expectation is a KB rule (documented deterministic). Revision sub-checks are `NOT_CROSS_CHECKABLE` where the repo does not pin a revision.
- **Reviewer actions:** on the donor-bug disagreement — "replace `qcom,sa8775p-adsp-pas`/`sa8775p/adsp.mbn`/LCX-LMX with the SA8797P-correct compatible, firmware, and power domains; resolve `FIXME(sa8797p-audio)`."

---

## 3. Common verdict model

### 3.1 The five verdicts

| Verdict | Meaning | Warning? | Maps to reviewer worklist? |
|---|---|---|---|
| **MATCH** | Source and authority agree on a DIRECT/DERIVED basis. | No | No |
| **PARTIAL_MATCH** | Primary fact agrees; a secondary attribute differs, OR a KB rule downgrades a mismatch to accepted divergence. | No (informational) | No (unless the KB rule requests it) |
| **DISAGREE_WITH_AUTHORITY** | Source contradicts the IPCAT authority on a DIRECT basis. The real-defect signal (donor bug, D4). | Yes | Yes (as REVIEW_REQUIRED) |
| **NOT_CROSS_CHECKABLE** | Cannot compare: authority unavailable/unverified, or source self-flagged ambiguous, or <2 usable lanes. Legitimate recorded outcome. | No | No (but listed as "coverage gap") |
| **REVIEW_REQUIRED** | Explicit reviewer-action verdict. Every `DISAGREE_WITH_AUTHORITY` produces a `REVIEW_REQUIRED` worklist entry; a track may also raise `REVIEW_REQUIRED` directly for a hard mismatch that isn't a clean authority disagreement (e.g. T1 pin-does-not-exist). | Yes | Yes |

**Relationship:** `DISAGREE_WITH_AUTHORITY` is the *verdict on the row*; `REVIEW_REQUIRED` is the *actionable projection* of every warning verdict into the worklist. They are not mutually exclusive — a row's `verdict` is one of the first four; if it is a warning verdict it additionally generates a `REVIEW_REQUIRED` worklist item. (Implementations may represent `REVIEW_REQUIRED` as a derived worklist entry rather than a sixth row-level enum; the spec treats it as a first-class member of the vocabulary for clarity.)

### 3.2 Mapping to existing WP-C semantics

The WP-C lane (`cardinality.py`) uses: `agree`, `disagree`, `not_cross_checkable`, `benign_divergence`, `disagree_with_authority`. Phase-2A is a **strict superset** with a 1:1 core mapping — T3 rows are produced by WP-C and translated:

| WP-C verdict (`cardinality.py`) | Phase-2A verdict | Notes |
|---|---|---|
| `agree` | `MATCH` | direct rename |
| `disagree_with_authority` | `DISAGREE_WITH_AUTHORITY` | identical semantics; + generates `REVIEW_REQUIRED` |
| `not_cross_checkable` | `NOT_CROSS_CHECKABLE` | identical (ambiguous / <2 lanes / no authority) |
| `benign_divergence` | `PARTIAL_MATCH` (with `rule_id`) | KB-registered accepted divergence |
| `disagree` (pre-SWI, no authority) | `DISAGREE_WITH_AUTHORITY` if an authority lane is present; else `PARTIAL_MATCH`/`REVIEW_REQUIRED` per KB | In 2A the IPCAT `catalog` lane is (almost) always the authority, so pre-SWI `disagree` rarely arises |
| WP-C `warning == true` | 2A row `warning == true` → worklist | mapping preserved verbatim |

**Correctness rules carried over verbatim (do not re-derive):**
- `dt == 0` under `dt_applied == false` → lane dropped as "unapplied-at-HEAD," reported as a note (not an instance count).
- `ambiguous == true` → `NOT_CROSS_CHECKABLE` regardless of integers.

### 3.3 Verdict precedence (per row)
1. Source self-flagged ambiguous → `NOT_CROSS_CHECKABLE`.
2. Authority unavailable/unverified → `NOT_CROSS_CHECKABLE`.
3. <2 usable lanes (count tracks) / no authority lookup possible → `NOT_CROSS_CHECKABLE`.
4. Authority present, all usable lanes equal it → `MATCH`.
5. Authority present, secondary-attribute-only difference → `PARTIAL_MATCH`.
6. Authority present, KB benign-divergence rule applies → `PARTIAL_MATCH` (+ `rule_id`).
7. Authority present, primary fact differs → `DISAGREE_WITH_AUTHORITY` (+ worklist `REVIEW_REQUIRED`).

### 3.4 Confidence model
- **Authority strength:** `IPCAT_DIRECT` > `IPCAT_DERIVED` (documented formula) > `KB_RULE` (deterministic expectation) > `UNAVAILABLE`.
- **Provisional flag:** any verdict resting on a capped `swi_search_swi` result (at/above cap, or single-term) is `provisional=true` with confidence downgraded and the W4 caveat in `notes`.
- **Propagation (annotate-only):** a foundational-track warning (T1/T2) discounts dependent-track confidence (T3/T4/T5) by a fixed documented factor; it **never changes a dependent verdict**.
- **Asymmetry (C.9):** ambiguity → surface (`NOT_CROSS_CHECKABLE` + coverage-gap note), never silent `MATCH`.

### 3.5 T3 row translation (concrete)
For each row from `compare_element_counts(gc)`:
```
VerificationRow(
  track="T3",
  subject=row["element_class"],
  source="proposal|evidence|dt (usable lanes)",
  authority="ipcat.catalog",
  source_value=row["counts"] minus catalog_count,
  authority_value=row["counts"]["catalog_count"],
  verdict=MAP[row["verdict"]],              # table §3.2
  confidence=high if not provisional else provisional,
  rule_id=row["rule_id"],
  review_actions=[...] if row["warning"] else [],
  citations=row["citations"],
  notes=row["notes"] + ambiguity_note,
)
```

---

## 4. Evidence schema — `phase2a_verification.json`

JSON Schema (draft-07 style) proposal. Path: `experiments/ipcat_probe/artifacts/phase2a_verification_<chip_id>.json` (per-target) + a combined `phase2a_verification.json`.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Phase2A Schematic-IPCAT Cross-Verification",
  "type": "object",
  "required": ["phase", "chip_id", "evidence_ts", "boundary", "provenance", "rows", "reviewer_worklist", "confidence_report", "verdict"],
  "properties": {
    "phase": { "const": "2A" },
    "chip_id": { "type": "integer" },
    "target_label": { "type": "string" },
    "evidence_ts": { "type": "string", "format": "date-time" },

    "boundary": {
      "type": "object",
      "required": ["auth_json_read", "credentials_json_read", "tls_verify", "readonly_only", "wp_c_lane_modified"],
      "properties": {
        "auth_json_read": { "const": false },
        "credentials_json_read": { "const": false },
        "tls_verify": { "const": true },
        "readonly_only": { "const": true },
        "wp_c_lane_modified": { "const": false }
      }
    },

    "provenance": {
      "type": "object",
      "description": "Frozen snapshot metadata enabling replay (see §5).",
      "required": ["ipcat_tools", "schematic_sources", "dts_sources", "wp_c_commit"],
      "properties": {
        "ipcat_tools": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["tool", "args", "capped", "result_digest"],
            "properties": {
              "tool": { "type": "string", "enum": ["chips_list_chips", "cores_list_core_instances", "swi_search_swi"] },
              "args": { "type": "object" },
              "capped": { "type": "boolean", "description": "true if a swi_search_swi result was at/above cap (provisional)" },
              "union_terms": { "type": "array", "items": { "type": "string" } },
              "stability_confirmed": { "type": "boolean" },
              "result_digest": { "type": "string", "description": "hash of the frozen result set for replay verification" }
            }
          }
        },
        "schematic_sources": { "type": "array", "items": { "type": "string" }, "description": "file:line citations, e.g. targets/nord-iq10/profile.json:72" },
        "dts_sources": { "type": "array", "items": { "type": "string" } },
        "wp_c_commit": { "type": "string", "description": "commit of the unchanged WP-C lane, e.g. 28f2f07" }
      }
    },

    "rows": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["track", "subject", "source", "authority", "verdict", "confidence", "citations"],
        "properties": {
          "track": { "type": "string", "enum": ["T1", "T2", "T3", "T4", "T5"] },
          "subject": { "type": "string", "description": "e.g. soundwire_master, GPIO I2S8, codec:PCM1681, compatible:adsp-pas" },

          "source": {
            "type": "object",
            "required": ["origin", "value"],
            "properties": {
              "origin": { "type": "string", "enum": ["profile_json", "board_layer", "dts", "element_counts_proposal", "element_counts_evidence", "element_counts_dt"] },
              "value": {},
              "citation": { "type": "string" }
            }
          },

          "authority": {
            "type": "object",
            "required": ["origin", "value", "strength"],
            "properties": {
              "origin": { "type": "string", "enum": ["ipcat.chips_list_chips", "ipcat.cores_list_core_instances", "ipcat.swi_search_swi", "kb_rule", "unverified"] },
              "value": {},
              "strength": { "type": "string", "enum": ["IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"] },
              "provisional": { "type": "boolean", "description": "true if resting on a capped swi_search_swi result" },
              "caveat": { "type": "string" }
            }
          },

          "verdict": { "type": "string", "enum": ["MATCH", "PARTIAL_MATCH", "DISAGREE_WITH_AUTHORITY", "NOT_CROSS_CHECKABLE", "REVIEW_REQUIRED"] },

          "confidence": {
            "type": "object",
            "required": ["level"],
            "properties": {
              "level": { "type": "string", "enum": ["high", "medium", "provisional", "none"] },
              "propagation_discount": { "type": "number", "description": "factor applied from an upstream T1/T2 warning; 1.0 = none" },
              "basis": { "type": "string" }
            }
          },

          "rule_id": { "type": ["string", "null"], "description": "KB divergence rule id (WP-C-compatible), e.g. SWR-D1" },
          "warning": { "type": "boolean" },

          "review_actions": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["action", "severity"],
              "properties": {
                "action": { "type": "string" },
                "severity": { "type": "string", "enum": ["info", "review", "high"] },
                "wp_c_ref": { "type": "string", "description": "e.g. D4 for the Eliza LPASS divergence" }
              }
            }
          },

          "citations": { "type": "array", "items": { "type": "string" } },
          "notes": { "type": "array", "items": { "type": "string" } }
        }
      }
    },

    "reviewer_worklist": {
      "type": "array",
      "description": "Projection of all warning rows (DISAGREE_WITH_AUTHORITY / REVIEW_REQUIRED).",
      "items": {
        "type": "object",
        "required": ["track", "subject", "verdict", "actions"],
        "properties": {
          "track": { "type": "string" },
          "subject": { "type": "string" },
          "verdict": { "type": "string" },
          "actions": { "type": "array", "items": { "type": "string" } },
          "wp_c_ref": { "type": "string" }
        }
      }
    },

    "confidence_report": {
      "type": "object",
      "required": ["per_track", "coverage_gaps"],
      "properties": {
        "per_track": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "properties": {
              "match": { "type": "integer" },
              "partial_match": { "type": "integer" },
              "disagree_with_authority": { "type": "integer" },
              "not_cross_checkable": { "type": "integer" },
              "review_required": { "type": "integer" },
              "aggregate_confidence": { "type": "string", "enum": ["high", "medium", "provisional", "none"] }
            }
          }
        },
        "coverage_gaps": {
          "type": "array",
          "description": "NOT_CROSS_CHECKABLE rows with reason — the honest 'what we could not check' list.",
          "items": {
            "type": "object",
            "properties": {
              "track": { "type": "string" },
              "subject": { "type": "string" },
              "reason": { "type": "string", "enum": ["authority_tool_unverified", "source_ambiguous", "insufficient_lanes", "revision_not_pinned"] }
            }
          }
        }
      }
    },

    "verdict": { "type": "string", "enum": ["PASS", "PASS_WITH_REVIEW", "PARTIAL", "FAIL"] },
    "verdict_basis": { "type": "string" }
  }
}
```

**Top-level verdict mapping:**
- `PASS` — every applicable row `MATCH`/`PARTIAL_MATCH`; no warnings; no coverage gaps beyond documented revision-pin.
- `PASS_WITH_REVIEW` — all comparable rows resolved, but ≥1 `DISAGREE_WITH_AUTHORITY`/`REVIEW_REQUIRED` (the expected steady state today — D4 lives here).
- `PARTIAL` — some tracks `NOT_CROSS_CHECKABLE` due to unverified authorities (T1/T4 before the §6 spike), rest resolved.
- `FAIL` — engine could not run (target not RESOLVED, IPCAT unreachable, or WP-C lane errored). Note: content disagreements are **never** `FAIL` — they are `PASS_WITH_REVIEW` (C.9 asymmetry).

---

## 5. Replayability

The engine is reproducible because Stage 1 (collector) **freezes** the live snapshot and Stage 2 (core) is pure. A future skill run reproduces results as follows:

1. **Snapshot capture (once, online).** The collector records, in `provenance.ipcat_tools[]`: every tool name, exact args, `union_terms`, `stability_confirmed`, `capped`, and a `result_digest` (hash of the frozen result set). The raw frozen results are stored alongside the artifact (e.g. `phase2a_snapshot_<chip_id>.json`).
2. **Deterministic replay (offline, no IPCAT).** Re-running the pure core against the frozen snapshot yields byte-identical `rows` — the same guarantee Phase-1C relied on when running `compare_element_counts` against a captured live `catalog` lane. No credentials, no network.
3. **Freshness check (online, optional).** To confirm the snapshot is still current, re-capture and compare `result_digest` per tool. A changed digest flags "silicon catalog moved since last run" → re-run the core; unchanged digest → the prior artifact is still authoritative.
4. **WP-C pinning.** `provenance.wp_c_commit` records the exact commit of the unchanged lane (`28f2f07`); replay asserts the lane is byte-identical before trusting T3 rows.
5. **Determinism guards:** no wall-clock or RNG in the core; `evidence_ts` is captured once at snapshot time and passed in, never read inside the pure core (same rule the workflow/runners already follow).

**Replay contract:** `same snapshot + same WP-C commit + same schematic/DTS inputs ⇒ identical rows, worklist, and confidence_report`. Any difference is a real input change, not engine nondeterminism.

---

## 6. MUST-FIX prerequisites (from D1/D2/D3 — specified, NOT implemented here)

These are lessons from the retrospective's discrepancy register. This section **specifies what must be true** before the engine can run headlessly; it does **not** implement any fix.

| ID | Prerequisite | What "fixed" means for Phase-2A | Blocks which tracks | Status |
|---|---|---|---|---|
| **D1** | Correct IPCAT enumerate tool name (`chips_list_chips`, not `get_chips`). | The collector must call the **verified** tool names (§1.3). The engine's collector is written against `chips_list_chips`/`cores_list_core_instances`/`swi_search_swi` from day one; the *probe binary* fix is separate and out of scope here. | All (collector cannot enumerate silicon otherwise). | Understood; probe unmodified per constraint. |
| **D2** | TLS / corporate CA handling codified. | The collector/runner must set `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (or equivalent system CA store) **in the runner config**, not rely on ambient env. `verify=True` always. | All (no live call succeeds otherwise). | Understood; must be codified in the 2A runner, not left ambient. |
| **D3** | Non-interactive IPCAT data access. | The ip_catalog backend's secondary `kind=headers` auth must have a **headless path** (dedicated read-only token per `BRIDGE_PROVISIONING_FEASIBILITY.md`) before 2A can run in CI/unattended. Until then 2A runs **operator-attended** (auth completed manually, as in Phase-1C). | All live tracks; the pure core + replay (§5) work offline regardless. | **Open operator question** — mint a dedicated read-only hub token, or accept attended-only runs. |
| **(A1)** | *New for 2A:* verify GPIO/pinmux (T1) and codec-connectivity (T4) authority tools exist. | A **discovery spike** must confirm a real IPCAT tool for per-chip GPIO/pinmux function maps and for controller/DAI capability. Until confirmed, T1/T4 correctly emit `NOT_CROSS_CHECKABLE (authority_tool_unverified)`. | T1, T4 only (T2/T3/T5 use verified tools). | **Open** — not attempted in Phase-1; must not be assumed. |

**Interlock:** D1 + D2 are required for **any** live run; D3 is required for **headless/CI** runs (attended runs proceed without it, as Phase-1C did); A1 is required to lift T1/T4 out of `NOT_CROSS_CHECKABLE`. **None are implemented in this spec.** T2, T3, and T5 are fully buildable and runnable (attended) on the strength of the three verified tools today; T1 and T4 are architecturally complete but honestly gated on A1.

---

## 7. Build order & acceptance (implementation-ready checklist)

1. **Collector + snapshot freeze** (Stage 1) with `provenance` + `result_digest` — enables replay before any track exists.
2. **Comparison core skeleton** (Stage 2) + `VerificationRow` model + verdict enum + precedence (§3.3).
3. **T3 first** — it is pure delegation to the already-live WP-C lane; validates the row-translation (§3.5) against the known Phase-1C output (Nord all `MATCH`; Eliza LPASS `DISAGREE_WITH_AUTHORITY`, soundwire `NOT_CROSS_CHECKABLE`). This is the engine's regression anchor.
4. **T2** — verified `swi_search_swi` union+stability; anchor against Nord `MATCH` (0=0) and Eliza's counts.
5. **T5** — DTS identity + donor-bug KB rule; anchor against the known `FIXME(sa8797p-audio)` donor case → `DISAGREE_WITH_AUTHORITY`.
6. **T1 / T4** — implement the comparison logic + emit `NOT_CROSS_CHECKABLE (authority_tool_unverified)` until the A1 discovery spike lands.
7. **Renderer + worklist + confidence_report** (Stage 3) + additive report section.
8. **Acceptance:** given the frozen Phase-1C snapshot, the engine reproduces the six T3 verdicts exactly; produces `PASS_WITH_REVIEW` for Eliza (D4 in the worklist) and `PASS` for Nord's comparable rows; all boundary flags in the artifact are the required constants; replay is byte-identical.

---

*Executable specification only. No implementation, no code changes, no probe changes, WP-C lane referenced as unchanged (`28f2f07`), nothing committed. Only the three Phase-1-verified IPCAT tools are treated as available; unverified authorities (T1/T4) are specified but honestly gated behind a discovery spike per the no-fabrication invariant.*
