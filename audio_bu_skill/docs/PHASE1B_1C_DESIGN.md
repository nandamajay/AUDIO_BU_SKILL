# Phase-1B / Phase-1C Design Freeze

**Type:** Design only. **No code, no `probe.py` changes, no implementation, no commits.**
**Context:** Phase-1A committed at `91de143`; no provisioning exists; no live IPCAT run possible yet. This document makes Phase-1B and Phase-1C **execution-ready the moment provisioning arrives.**
**Sources:** `docs/PHASE1_NEXT_STEPS.md`, `docs/PHASE1_IMPLEMENTATION_PLAN.md`; consumes the already-committed WP-C cardinality lane (`28f2f07`) and `element_counts` schema 1.3.0 (`b151e26`) unchanged.

> **Standing constraints carried forward:** read-only only; TLS `verify=True`; `auth.json` never opened (presence-check only); probe stays outside the production import path; the three deferred SHOULD-FIX items (live error handling, timeout, named-field matching) are **pre-first-live-run gates** and must be closed before any live run below. No fabricated values — unknown is recorded as unknown, never guessed.

---

## 1. Phase-1B Design — Eliza Resolution + Nord Re-Confirmation

### 1.1 Objective
From a proven-working structured lookup (Phase-1A exit 0), resolve `<ELIZA-SOC>` to a **definitive** catalog identity or a **definitive absent**, and independently re-confirm Nord — producing an auditable resolution record. No counts, no cardinality yet.

### 1.2 Eliza resolution contract
A resolution attempt returns exactly one of three terminal states (never a bare boolean):

```
ResolutionResult:
  target_label:   str        # "<ELIZA-SOC>" | "<NORD-ALIAS>"
  status:         RESOLVED | ABSENT | AMBIGUOUS
  chip_id:        str | null # populated iff RESOLVED
  matched_field:  str | null # the field that produced the match (not substring)
  candidates:     [ChipRef]  # >1 iff AMBIGUOUS; the evidence for the verdict
  query:          QueryRecord# tool + args that produced this (reproducible)
  evidence_ts:    <injected> # stamped by operator/runbook, not by probe logic
```

- **RESOLVED** requires a match on a **named identifier field** (chip id / canonical name / alias field) — not the Phase-1A substring heuristic. Exactly one candidate.
- Resolution proceeds mechanism-agnostically over a structured enumeration (`get_chips` / `swi_search_swi`) already on the read-only allow-list.

### 1.3 Definitive-absent contract
`ABSENT` may be asserted **only** when both hold:
1. The enumeration/query **succeeded** (structured response, not an error/empty-due-to-failure), and
2. No candidate matches the target on any identifier field.

An empty result caused by a query error, timeout, or unstructured (prose) response is **NOT** absent — it is a Phase-1A-class failure and must be surfaced as such (exit 3 semantics), never silently downgraded to "Eliza absent." The `query` record must prove the enumeration was authoritative (e.g. returned N>0 other chips), so absence is distinguishable from "catalog didn't answer."

### 1.4 Identifier schema
`ChipRef` is the minimal typed identity used throughout 1B/1C:

```
ChipRef:
  chip_id:        str        # authoritative catalog id (primary key)
  canonical_name: str | null
  aliases:        [str]      # includes Nord alias / Eliza alias when known
  source_tool:    str        # which read-only tool surfaced it
```

Nord re-confirmation must match on a **second field** (id + name/alias), not name alone, to defeat the substring false-positive risk flagged in review.

### 1.5 Ambiguity handling
`AMBIGUOUS` (>1 candidate on identifier fields) is a **first-class terminal state**, not an error and not a guess:
- record **all** candidates in `candidates[]`;
- do **not** pick one;
- mark the target UNVERIFIED and stop the target's progression to Phase-1C;
- an ambiguous Eliza does **not** block Nord (targets resolve independently).

This mirrors the anti-fallback discipline already encoded in WP-C (`ambiguous:true → not_cross_checkable`, evaluated first).

### 1.6 Evidence recording format
One JSON record per target, written to the non-tracked experiments artifact path (never a production run dir):

```
experiments/ipcat_probe/artifacts/phase1b_<target>.json
{
  "phase": "1B",
  "mechanism": "A|B",
  "results": [ ResolutionResult, ... ],   # one per target
  "boundary": {"auth_json_read": false, "tls_verify": true},
  "verdict": "PASS|PARTIAL|FAIL"           # per §4 success criteria
}
```
No secrets, no token, no `auth.json` content. Record is discardable (rollback = delete).

### 1.7 Phase-1B success mapping (from plan §4)
- **PASS:** Eliza RESOLVED (or authoritative ABSENT) **and** Nord RESOLVED on ≥2 fields.
- **PARTIAL:** one target resolves; the other genuinely AMBIGUOUS (recorded).
- **FAIL:** neither resolves, or the catalog cannot answer identity queries.

---

## 2. Phase-1C Design — Count Acquisition

Runs only for a **RESOLVED** target from 1B. The three counts, each with a direct / derived / unavailable path. Every count carries its classification and the reproducible query that produced it. No fabrication.

Common count record:
```
CountResult:
  chip_id:        str
  element_class:  str        # soundwire_master | dsp_subsystem_instance | lpass_macro_instance
  value:          int | null
  classification: DIRECT | DERIVED | UNAVAILABLE
  method:         str        # tool+extract (DIRECT) | formula (DERIVED) | reason (UNAVAILABLE)
  query:          [QueryRecord]
  ambiguous:      bool       # true → route to not_cross_checkable downstream
```

### 2.1 `soundwire_master`
- **Direct path:** a read-only enumeration of SoundWire master instances for the chip returns a countable list → `value = len(instances)`, `DIRECT`. (Requires the relevant enumerate tool to be added to the read-only allow-list for 1C.)
- **Derived path:** if masters are not directly enumerable but a deterministic mapping exists (e.g. per-subsystem master presence), compute via a documented formula → `DERIVED`, `method` records the formula.
- **Unavailable path:** if neither a countable list nor a deterministic formula exists → `value=null`, `UNAVAILABLE`, `method` records why. Never inferred from prose.
- **WP-C note:** `soundwire_master` excludes dt in cross-check (SWR-P1); count-vs-routing mismatch downgrades to `benign_divergence` (SWR-D1) — handled by the committed lane, not here.

### 2.2 `dsp_subsystem_instance`
- **Direct path:** enumerate DSP subsystem instances (read-only) → `len(...)`, `DIRECT`.
- **Derived path:** derive from a subsystem/topology descriptor if instances aren't directly listed but are unambiguously implied → `DERIVED`.
- **Unavailable path:** not listable and not unambiguously derivable → `UNAVAILABLE`.

### 2.3 `lpass_macro_instance`
- **Direct path:** enumerate LPASS macro instances (read-only) → `len(...)`, `DIRECT`.
- **Derived path:** derive from LPASS macro configuration/registers if a deterministic rule exists → `DERIVED`, formula recorded.
- **Unavailable path:** ambiguous or absent → `UNAVAILABLE` (or `ambiguous:true` → routed to `not_cross_checkable`).

### 2.4 Classification discipline
- `DIRECT` only when a real enumeration is counted (never `len()` of a mislabeled field — the Eliza `len()`-bug class fixed in WP-C).
- `DERIVED` requires a **documented, deterministic** formula in `method`; a derivable-but-ambiguous count sets `ambiguous:true` and is classified per the downstream verdict, not asserted as a number.
- `UNAVAILABLE` is a legitimate, recorded outcome — partial success, not failure.

---

## 3. Cardinality Integration (WP-C lane, unchanged)

Uses the committed WP-C lane (`compare_element_counts`) and `element_counts` schema 1.3.0 **as-is** — no schema change, no lane change. 1C only *produces the input* and *observes the output*.

- **Inputs:** an `element_counts` structure (schema 1.3.0) populated from §2 `CountResult`s — per element class: the machine/analysis count and, where present, the catalog (authority) count, plus `ambiguous` and applicable-source flags. dt=0 under `dt_applied=false` is dropped (not a false disagree), per the committed rule.
- **Authority checks:** the lane compares per-class counts against applicable sources using each class's `divergence_rule`; `ambiguous:true` is evaluated first → `not_cross_checkable`.
- **Outputs / verdict vocabulary (existing):** `agree` / `disagree` / `not_cross_checkable` / `benign_divergence` / `disagree_with_authority`. The catalog lane (`disagree_with_authority`) becomes live for the first time once real catalog counts are supplied — today it is inert.
- **Where it runs:** exercised on the **experiments artifact only** (probe-produced counts), never inside a shipped production run. This is the *expected* and only sanctioned crossing of the "probe touches WP-C" line, consistent with `PHASE1A_REVIEW.md` §3.
- **Expected first observation:** for a resolved target with direct counts, `agree`; the first live `disagree_with_authority`/`benign_divergence` verdicts replace today's "no count obtained" state (plan §4.4).

Cardinality output record:
```
experiments/ipcat_probe/artifacts/phase1c_<chip_id>.json
{
  "phase": "1C",
  "chip_id": ...,
  "counts": [ CountResult, ... ],
  "element_counts_input": { ...schema-1.3.0... },
  "cardinality_verdicts": [ {element_class, verdict, detail}, ... ],
  "verdict": "PASS|PARTIAL|FAIL"
}
```

---

## 4. Execution Sequence

### 4.1 Phase-1B Runbook (first real IPCAT execution)
**Preconditions:** Gate-1 closed (mechanism provisioned, creds present); pre-first-live-run remediation applied (live error handling, timeout, named-field matching); Phase-1A live run returns **exit 0**.

1. `python probe.py --check` → confirm the provisioned mechanism shows present; `auth.json` untouched, TLS-on noted.
2. `python probe.py --mechanism <A|B> --chip <NORD_ALIAS>` → **exit 0** required (the 1A live gate). If 2/3 → stop, investigate.
3. Run Eliza resolution against `<ELIZA-SOC>` over the structured enumeration → produce `ResolutionResult` (RESOLVED / ABSENT / AMBIGUOUS per §1.2–1.5).
4. Re-confirm Nord on ≥2 identifier fields → `ResolutionResult`.
5. Write `phase1b_<target>.json` (§1.6); assign PASS/PARTIAL/FAIL (§1.7).
6. **Gate to 1C:** proceed only for targets with status RESOLVED. AMBIGUOUS/ABSENT-Eliza does not block a RESOLVED Nord.
**Rollback:** delete the 1B artifact; nothing production-facing touched.

### 4.2 Phase-1C Runbook
**Preconditions:** Phase-1B produced ≥1 RESOLVED target; the specific read-only count/enumerate tools added to the allow-list (still read-only).

1. For the resolved `chip_id`, acquire each of the three counts via its direct → derived → unavailable cascade (§2); record `CountResult` with classification + query.
2. Assemble the `element_counts` schema-1.3.0 input from the `CountResult`s (§3 inputs); apply the dt=0/`dt_applied=false` drop and `ambiguous` flags.
3. Invoke the committed WP-C `compare_element_counts` on the experiments input; capture per-class verdicts.
4. Write `phase1c_<chip_id>.json` (§3); assign PASS/PARTIAL/FAIL (plan §4: all three counted+classified & lane emits a verdict = PASS; some UNAVAILABLE but correctly classified = PARTIAL; none obtainable/derivable or lane errors = FAIL).
5. Report first live cardinality verdicts.
**Rollback:** delete the 1C artifact; the production WP-C lane is untouched (exercised on probe data only).

---

## 5. Readiness Checklist (what "execution-ready" means here)

| Item | State at freeze |
|---|---|
| Eliza resolution / absent / ambiguity contracts | **Designed (§1)** |
| Identifier schema (`ChipRef`, `ResolutionResult`, `CountResult`) | **Designed** |
| Three-count acquisition cascades | **Designed (§2)** |
| WP-C integration (inputs/outputs/authority/verdicts) | **Designed against committed lane (§3)** — no schema/lane change |
| 1B / 1C runbooks | **Written (§4)** |
| Read-only allow-list extension for count tools | **Deferred to execution** (add when tool names known; still read-only) |
| Pre-first-live-run remediation | **Prerequisite gate** (not done here — code untouched) |
| Live run | **Blocked by provisioning** |

Everything is design; nothing here executes, changes `probe.py`, or commits. The only work still gating a live run is operator provisioning + the pre-first-live-run remediation.

---

*Phase-1B / 1C design freeze. Design only — no code, no probe changes, no commits. Consumes the committed WP-C lane and schema 1.3.0 unchanged. Phase-0 frozen; execution blocked on operator provisioning.*
