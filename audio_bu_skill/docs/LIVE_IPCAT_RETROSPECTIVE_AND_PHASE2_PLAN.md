# Live IPCAT Retrospective & Phase-2 Plan

**Type:** Retrospective + roadmap planning. **No code, no implementation, no commits. Lessons learned and forward plan only.**
**Inputs read:** `docs/PHASE1B_LIVE_EVIDENCE.md`, `docs/PHASE1C_LIVE_EVIDENCE.md`, `docs/NORD_TARGET_IDENTIFICATION.md`.
**Scope:** Phases 1A/1B/1C are now demonstrated against **live** IPCAT data. This document (a) closes the loop on what the first live run taught us and (b) frames the proposed **Schematic ↔ IPCAT Cross-Verification Engine** as Phase-2A, against the alternative of jumping straight to DTS generation.
**Date:** 2026-07-14

---

## Part I — Retrospective on the First Live IPCAT Execution

### 1. Assumptions VALIDATED by live execution

| # | Assumption (pre-live) | How live execution confirmed it |
|---|---|---|
| V1 | The `ip_catalog` MCP server is reachable and returns real, structured catalog data (not a stub). | `chips_list_chips` returned **733 real chips**; both targets resolved with full field sets. |
| V2 | Nord target = **SA8797P (NordAU)**, family resolvable; NordDC/AIC200 are a different product line. | Live catalog confirmed `SA8797P (NordAU) v2` (id 781, `nordschleife_2.0`, family Wildcat/23) exactly as `NORD_TARGET_IDENTIFICATION.md` predicted. |
| V3 | Eliza is a single unambiguous sibling target. | One `SM7750 (Eliza)` row (id 693, `eliza_1.0`, family Wildcat/23). |
| V4 | Resolution can be re-confirmed on ≥2 named fields (the frozen 1B contract). | Both targets matched on **4** fields (id + name + alias + family). |
| V5 | The three audio element classes are countable from live catalog surfaces. | All three counted **DIRECT** for both targets; none required UNAVAILABLE. |
| V6 | Nord is I²S-only (no SoundWire, no LPASS macros) per `profile.json`. | Live catalog **independently corroborated** `soundwire_master=0`, `lpass_macro_instance=0`. Two independent sources now agree. |
| V7 | The committed WP-C cardinality lane (`28f2f07`) can consume a live `catalog` authority lane and emit verdicts without modification. | Ran unchanged; emitted a verdict for all 6 rows (3 classes × 2 targets). |
| V8 | The "gateway-brokered auth" (G-L1) prediction — credentials live at the gateway, not in the config file. | Confirmed: the registration carries only `url`; identity is brokered at connect time. |
| V9 | Security boundaries hold under a real run. | `auth.json`/`.credentials.json` never read; TLS `verify=True` throughout; read-only allow-list respected; token handled by reference. |

### 2. Assumptions PROVEN WRONG

| # | Assumption (pre-live) | Reality discovered live | Consequence |
|---|---|---|---|
| W1 | The probe's enumerate tool name `get_chips` is correct. | **No such tool.** The real enumerator is `chips_list_chips` (one of 95 tools). | The probe **binary** still exits 3; live evidence was collected via the ad-hoc session helper. Probe is a known, separately-tracked fix (not patched, per constraint). |
| W2 | The MCPHub gateway API key (Bearer) is sufficient to reach catalog **data**. | The key authenticates to the gateway (enough for `initialize` + `tools/list`), but the **ip_catalog backend requires a secondary interactive header-submission** (`…/auth?flow=<id>&kind=headers`) before `tools/call` returns data. | Two-layer auth is now a documented prerequisite for any live run; automation cannot self-serve it. |
| W3 | Default TLS trust (httpx → `certifi`) will validate the corporate endpoint. | `certifi` lacks the Qualcomm corporate CA → `CERTIFICATE_VERIFY_FAILED`. | Fixed **without weakening TLS**: `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (system CA store has the corporate root). `verify=True` preserved. |
| W4 | A text search tool (`swi_search_swi`) can be trusted as an exhaustive enumerator, and `total_hits` reflects the count. | It is a **capped, relevance-ranked** search; `total_hits` returned **0 even when results existed**. A single-term query under-counted (1 macro vs the true 4). | Counting method hardened: **union multiple query terms + verify set-stability + confirm below-cap**, never trust `total_hits` or a single term. This is the exact "mislabeled `len()`" anti-pattern the design warns against. |
| W5 | Prior onboarding proposal counts would broadly match the live authority. | Mostly true — but **Eliza `lpass_macro_instance`: proposal=2 vs live catalog=4** (`disagree_with_authority`). | WP-C surfaced a genuine review item; the prior proposal appears to have under-counted LPASS macros. |
| W6 | `swi_get_submodules` / `swi_get_module_details` could enumerate per-chip blocks. | Returned FETCH_ERROR/INVALID_INPUT for chip-only input (need module IDs not in hand). | Abandoned in favor of the `swi_search_swi` named-block union + `cores_list_core_instances`. |

### 3. Discrepancy register (every discrepancy discovered)

| ID | Discrepancy | Category | Root cause | Current status | Residual risk / follow-up |
|---|---|---|---|---|---|
| **D1** | `get_chips` (probe) vs `chips_list_chips` (real) | Tool-contract mismatch | Probe hardcoded a tool name that does not exist on the server. | Evidence collected via helper; probe **unmodified** per constraint. | Probe binary exits 3 until the tool name is corrected. Tracked fix, not yet applied. |
| **D2** | TLS / corporate CA handling | Environment / trust anchor | httpx defaults to `certifi`, which omits the Qualcomm corporate root CA. | Resolved via `SSL_CERT_FILE` → system CA store; `verify=True` kept. | Any new runner/host must set the same env or re-hit `CERTIFICATE_VERIFY_FAILED`. Should be codified in the runner, not left ambient. |
| **D3** | Secondary auth flow (gateway key ≠ backend data access) | Auth architecture | ip_catalog backend requires interactive `kind=headers` submission beyond the gateway Bearer. | Completed manually for this run. | Non-interactive/CI execution is **blocked** until a headless path (or dedicated read-only token — see `BRIDGE_PROVISIONING_FEASIBILITY.md`) exists. |
| **D4** | Eliza `lpass_macro_instance`: proposal 2 vs live catalog 4 | Data divergence | Prior onboarding proposal under-counted LPASS macros (or counted a different scope). | WP-C verdict = `disagree_with_authority` (NEEDS_REVIEW, never hard-fail). | Reviewer must reconcile: is the live catalog 4 the true instance count, or a naming-scope artifact? Feeds directly into Phase-2A audio-resource validation. |
| **D5** (context) | Eliza `soundwire_master` prior pass self-flagged `ambiguous:true` ("1 or 2"); live = 4 | Ambiguity carried from onboarding | Reasoning pass could not resolve to a single integer. | WP-C correctly returned `not_cross_checkable` (refuses to manufacture a verdict from a disowned number). | Live catalog now gives a firm 4 — the ambiguity is *resolvable* but the lane will not auto-promote it. A future step could re-run the count and clear the ambiguity flag. |

---

## Part II — Phase-2 Roadmap

### 4. Phase-2A — Schematic ↔ IPCAT Cross-Verification Engine

**Premise.** Phase-1 proved we can pull an **authoritative silicon view** (the IPCAT catalog: chips, cores, register blocks, buses) for a resolved target. Phase-0/onboarding already produces a **board/design view** (schematic-derived: codecs, GPIO/pinmux assignments, I²S/SoundWire wiring, DTS scaffolding). These two views have never been mechanically cross-checked. Every real defect in Nord/Eliza bring-up so far (donor `sa8775p` compatible reused for `sa8797p`, LCX/LMX power domains copied structurally, the LPASS macro count divergence D4) is a **schematic-vs-silicon mismatch** that a human caught late or not at all.

**Objective.** A pure, diagnostic-only engine that consumes the schematic/board view and the live IPCAT silicon view, cross-checks them along well-defined tracks, and emits per-check verdicts using the **same asymmetry discipline as WP-C** — a false positive costs a reviewer one glance, never a blocked pipeline. It **introduces no new onboarding decision, promotion, or gating path**; it renders as an additive report section, exactly like the Confidence Ledger and the Cardinality Authority.

**Why 2A (not 2-anything-else):** it is the natural extension of WP-C. WP-C cross-checks *counts* across lanes; 2A cross-checks *structured facts* (pins, buses, resources, connectivity, DTS) across the schematic and the silicon authority. Same shape, wider surface.

### 5. Validation tracks

Each track has the same skeleton: **schematic claim → IPCAT authority lookup → verdict**. Verdicts reuse the WP-C vocabulary (`agree` / `disagree_with_authority` / `not_cross_checkable` / `benign_divergence`), extended per track where noted.

| Track | What it cross-checks | Schematic side (input) | IPCAT side (authority) | Example defect it would have caught |
|---|---|---|---|---|
| **T1 — GPIO validation** | Pin/pinmux assignments are legal and audio-function-capable for the resolved silicon. | I²S8 pinmux, GPIO numbers, drive-strength from `profile.json` / board layer. | Per-chip GPIO/pinmux tables and function maps from IPCAT. | An I²S pin assigned to a GPIO the silicon does not expose, or a wrong function mux. |
| **T2 — Bus validation** | The declared audio bus topology (I²S vs SoundWire, master/slave, instance) matches silicon. | Board declares I²S-only (Nord) or SoundWire (Eliza), master_count. | `soundwire_master` / I²S controller blocks from IPCAT SWI surface. | Nord accidentally wired for SoundWire when silicon/board is I²S-only (or vice-versa). |
| **T3 — Audio resource validation** | LPASS macros, DSP subsystems, ports match between design intent and silicon. | Onboarding proposal counts (LPASS macros, DSP subsystem, AudioReach ports). | Live `lpass_macro_instance`, `dsp_subsystem_instance`, register blocks. | **Exactly D4** — Eliza proposal=2 vs catalog=4 LPASS macros. |
| **T4 — Connectivity validation** | Codec ↔ SoC data paths are consistent end-to-end. | Codec parts (PCM1681 DAC, ADAU1979 ADC), which controller they hang off. | Controller/port existence + capability from IPCAT. | A codec wired to a DAI/port the silicon can't drive; orphaned codec. |
| **T5 — DTS consistency validation** | The generated/draft DTS is internally consistent and consistent with silicon identity. | `nord-sa8797p.dtsi`, compatible strings, firmware paths, power domains. | Silicon identity (SA8797P), correct compatible/firmware namespace. | **The donor bug**: `qcom,sa8775p-adsp-pas` + `sa8775p/adsp.mbn` + LCX/LMX copied from LeMans into an SA8797P DTS (the repo's own `FIXME(sa8797p-audio)`). |

**Track dependency ordering (suggested):** T1/T2 are foundational (nothing downstream is trustworthy if pins/buses are wrong) → T3/T4 build on a validated bus → T5 is the integration check that consumes all of the above. This ordering also determines a sensible confidence-propagation chain (a failed T2 discounts T3/T4 confidence).

### 6. Engine contract — Inputs, Outputs, Confidence model, WP-C integration

#### 6.1 Inputs
- **Resolved target** (Phase-1B output): `chip_id`, family, alias — the key for all IPCAT lookups.
- **Schematic/board view:** the existing `targets/<t>/profile.json` and board layer (pinmux, codecs, bus declaration, GPIO), plus the draft DTS (`nord-sa8797p.dtsi` etc.).
- **Live IPCAT view (read-only):** `chips_list_chips`, `cores_list_core_instances`, `swi_search_swi` (with the hardened union+stability method from W4), and per-track lookups (GPIO/pinmux tables, controller blocks). All via the **corrected** tool names and TLS/auth handling from Part I.
- **KB divergence rules** (as WP-C already uses): registered benign-divergence rules per track/class.

#### 6.2 Expected outputs
- **One verdict row per check**, shape mirroring WP-C:
  `{track, subject, schematic_value, ipcat_value, verdict, rule_id, confidence, warning, notes, citations}`.
- **A rolled-up per-track summary** (agree / needs-review / not-cross-checkable counts).
- **A reviewer work list** — only `disagree_with_authority` and track-specific hard mismatches map to NEEDS_REVIEW; everything else is informational.
- **An additive report section**, rendered like the Confidence Ledger / Cardinality Authority. **No gating, no promotion, no auto-mutation of the DTS.**
- **Deterministic + pure:** identical (schematic, IPCAT snapshot) → identical rows, so it is unit-testable in isolation against frozen fixtures.

#### 6.3 Confidence model
Extends the existing DIRECT/DERIVED/UNAVAILABLE classification and WP-C asymmetry:
- **Authority strength:** IPCAT-DIRECT (a real enumeration answered) > IPCAT-DERIVED (deterministic formula, documented in `method`) > UNAVAILABLE (tool cannot answer — legitimate, recorded, never guessed).
- **Verdict confidence:** `agree` backed by two IPCAT-DIRECT lanes is high; a verdict resting on a capped `swi_search_swi` result carries the recorded exhaustiveness caveat and is marked *provisional* until set-stability is confirmed (the W4 discipline becomes a first-class confidence attribute).
- **Propagation:** a failed foundational track (T1/T2) **discounts** the confidence of dependent tracks (T3/T4/T5) rather than hard-failing them — mirroring WP-C's "diagnostic, not gating" stance.
- **Asymmetry (C.9):** a false positive = one reviewer glance; a false negative (missed real mismatch) is the expensive error. The model is therefore tuned to **surface, not suppress** — ambiguity resolves to `not_cross_checkable` + NEEDS_REVIEW, never silent agreement.

#### 6.4 How WP-C integrates
- **Reuse, don't fork.** WP-C's `compare_element_counts` **is** Track T3's count engine — Phase-1C already proved it runs against a live `catalog` authority lane unchanged. 2A wraps it, not replaces it.
- **Shared vocabulary + rendering.** 2A adopts WP-C's verdict enums, `warning`→NEEDS_REVIEW mapping, KB divergence-rule mechanism, and additive-section rendering — one consistent reviewer experience.
- **Shared correctness rules.** The `dt=0 under dt_applied=false → unapplied-at-HEAD` rule and the `ambiguous:true → not_cross_checkable` rule apply verbatim to any count-bearing track.
- **Boundary inheritance.** Same security envelope: read-only IPCAT, TLS `verify=True`, no credential-store reads, no fabricated values, corrected tool names + `SSL_CERT_FILE` codified in the runner (fixes D1/D2 as a *precondition* for 2A rather than a side quest).

---

## Part III — Prioritization: Phase-2A Cross-Verification vs. Direct DTS Generation

### 7. The decision

| Dimension | **Phase-2A — Cross-Verification Engine** | **Direct DTS Generation** |
|---|---|---|
| Primary value | Catches schematic↔silicon mismatches *before* they ship (donor bug, D4-class divergences, wrong pinmux). | Produces the actual DTS artifact — the visible deliverable. |
| Risk profile | Low: diagnostic-only, no gating, false positives cheap. Builds directly on proven WP-C + Phase-1 access. | High: generates code that, on current evidence, would **inherit** the donor `sa8775p` compatible/firmware/LCX-LMX bug and the LPASS under-count. Generation without verification *automates the known defects*. |
| Dependency readiness | Ready: live IPCAT access proven (1A/1B/1C), WP-C committed and live-validated, tool/TLS/auth discrepancies now understood. | Depends on trustworthy inputs — which cross-verification is what establishes. Generating first means validating after the fact (or not at all). |
| Reversibility | Fully additive; can be removed with zero pipeline impact. | Generated DTS becomes a maintained artifact; mistakes propagate downstream and are expensive to unwind. |
| Evidence from this session | The first live run **already surfaced a real divergence (D4)** and confirmed a latent donor bug is live. The need is demonstrated, not hypothetical. | No new evidence that generation is safe yet — the opposite. |

### 8. Recommendation

**Prioritize Phase-2A (Schematic ↔ IPCAT Cross-Verification Engine) before Direct DTS Generation.**

**Justification:**
1. **Generation without verification automates known defects.** The repo already carries a self-flagged donor bug (`FIXME(sa8797p-audio)`: `sa8775p` compatible/firmware/LCX-LMX reused for SA8797P). A DTS generator run today would faithfully reproduce it. Cross-verification (T5) is precisely the check that catches it.
2. **The first live run proved the need empirically, not theoretically.** WP-C already found one genuine divergence (D4: Eliza LPASS 2 vs 4). That is a concrete, this-week example of a mismatch generation would have baked in.
3. **2A is low-risk and high-readiness.** It is diagnostic-only, reuses the committed WP-C lane (proven live in 1C), and its main prerequisites (D1 tool name, D2 TLS, D3 auth) are now *understood* and cheap to codify. Generation is higher-risk and, critically, *depends on the very input trust that 2A establishes*.
4. **Sequencing compounds value.** Cross-verification produces a validated, confidence-scored view of the design — which becomes the **trusted input** to a later DTS generator. Doing 2A first makes eventual generation *safer and faster*; doing generation first forces expensive rework.
5. **Asymmetry favors verify-first.** A missed schematic↔silicon mismatch that ships in generated DTS is the expensive failure mode; a cross-verification false positive is one reviewer glance. The economics point the same direction as the engineering.

**Recommended sequence:** land the D1/D2/D3 preconditions (correct probe tool name, codify `SSL_CERT_FILE`, define the headless/read-only auth path) → build Phase-2A on top of the unchanged WP-C lane, tracks in dependency order T1/T2 → T3/T4 → T5 → **only then** scope Direct DTS Generation, consuming 2A's validated view as its trusted input and 2A itself as its post-generation acceptance check.

**Not recommended:** starting Direct DTS Generation now. It would inherit the donor bug and the LPASS divergence with no mechanism to catch them, and would need the cross-verification work built afterward anyway — as rework rather than foundation.

---

*Planning and lessons-learned only. No code, no implementation, no probe changes, WP-C lane untouched, nothing committed. All live values cited trace to the Phase-1B/1C evidence artifacts; no value fabricated.*
