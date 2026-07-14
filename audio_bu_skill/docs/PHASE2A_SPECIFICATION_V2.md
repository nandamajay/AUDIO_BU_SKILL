# Phase-2A Specification V2 — Schematic ↔ IPCAT Cross-Verification Engine

**Type:** Executable specification (revision 2). **No implementation, no code changes, no commits.**
**Supersedes:** `docs/PHASE2A_SPECIFICATION.md` (V1). This revision folds in the live authority-discovery evidence.
**Inputs read:** `docs/PHASE2A_SPECIFICATION.md`, `docs/PHASE2A_AUTHORITY_DISCOVERY.md`.
**Reuses (unchanged):** WP-C Cardinality Authority — `orchestrator/reasoning/cardinality.py`, `orchestrator/reasoning/cardinality_config.py` (committed `28f2f07`).
**Date:** 2026-07-14

---

## 0. What changed from V1 (changelog)

| # | V1 statement | V2 revision | Evidence |
|---|---|---|---|
| C1 | T1 (GPIO/pinmux) authority **unverified**; emits `NOT_CROSS_CHECKABLE (authority_tool_unverified)`. | **T1 authority is live-verified DIRECT.** Emits real verdicts. | `PHASE2A_AUTHORITY_DISCOVERY.md §2` — `gpio_list_tlmm_gpios` returned 1280 pins incl. `aud_intfc0_*` with function-mux alternates. |
| C2 | T4 (connectivity) treated as a single track, gated by A1 discovery. | **T4 split into T4a (SoC endpoint — implementable now) and T4b (codec binding — structurally out of scope).** | Discovery: SoC endpoints exist via QUP/cores/buses; **no** codec/DAI/I²S tool or field exists in the 95-tool catalog. |
| C3 | Single coverage-gap reason for both: `authority_tool_unverified`. | **New reason `authority_out_of_scope`** distinguishes "IPCAT structurally cannot hold this" from "tool not yet found." | Codec↔controller binding is board/schematic data, permanently absent from IPCAT. |
| C4 | A1 prerequisite blocks T1 **and** T4. | **A1 resolved for T1 and T4a**; only T4b remains uncheckable — and that is permanent (scope), not a pending spike. | dito |
| C5 | Build order: T3 → T2 → T5 → (T1/T4 gated). | **Build order: T3 → T1 → T2 → T5 → T4a; T4b diagnostic-only.** | Task 4 of the revision request; reflects newly unblocked tracks. |

Everything in V1 §0 (invariants), §1.1 (three-stage architecture), §3 (verdict model core), §5 (replayability) stands unchanged unless noted below.

---

## 1. Engine architecture (unchanged from V1 §1, authorities updated)

Three-stage pipeline: **Collector** (impure; all live IPCAT I/O, freezes a snapshot) → **pure Comparison Core** → **Renderer/Emitter**. Inputs, outputs, and the collector/core split are as V1 §1.1–1.4.

### 1.3 (REVISED) IPCAT authority snapshot — verified tool inventory

**Live-verified authorities (all safe to depend on now):**

| Tool | Required params | Returns | Serves |
|---|---|---|---|
| `chips_list_chips` | — | full chip catalog (733 rows) | target re-confirm, **T5** silicon identity |
| `cores_list_core_instances` | `chip` | audio DSP subsystem + audio core enumeration | **T3** (dsp_subsystem_instance), **T4a** (endpoint existence) |
| `swi_search_swi` | `chip`, term | named register-block search (**capped, relevance-ranked** — union+stability method, W4) | **T2**, **T3** (soundwire_master, lpass_macro_instance) |
| `gpio_list_tlmm_gpios` | `chip` | 1280 pin rows `{name, pad, function, number, direction, …}` | **T1** (DIRECT) |
| `gpio_get_gpio_map` | `chip` | GPIO map id + TLMM group + ChipIO release provenance | **T1** (map resolver + replay provenance) |
| `gpio_list_gpios_from_map` | `gpio_map_id` (opt `function`, `name`, `number`) | parameterized pin query, same row shape | **T1** (preferred parameterized path) |
| `chipio_get_qups` | `chip` | 27 QUP serial engines `{i2c, uart, spi, i3c, …}` | **T4a** (codec control-bus endpoints) |
| `buses_list_buses` / `buses_list_bus_gateways` / `buses_list_bidpidmids` | `chip` (buses: opt) | NoC fabric buses/gateways/master-IDs | **T4a** (audio subsystem fabric attachment, indirect) |

**Structurally absent from IPCAT (permanent — not a discovery gap):** codec parts (PCM1681/ADAU1979), I²S/TDM/PCM **DAI-link** endpoints, codec↔controller **binding**. No tool and no field in the 95-tool catalog exposes these. → drives **T4b** and the `authority_out_of_scope` reason (§3.6).

---

## 2. Validation tracks (revised)

Track interface unchanged: `Track.compare(schematic, dts, ipcat_snapshot, kb) -> list[VerificationRow]`.

---

### Track T1 — GPIO Validation  *(V2: UNBLOCKED — live-verified DIRECT authority)*

- **Purpose:** every audio pin the design assigns (I²S/`aud_intfc` pinmux, GPIO number, drive strength/direction) is a pin the resolved silicon exposes and can mux to the claimed audio function.
- **Inputs (source):** `profile.json` pinmux/GPIO block + board layer — pin id/number, requested function, drive strength.
- **IPCAT authorities (VERIFIED, replacing `authority_tool_unverified`):**
  - **`gpio_get_gpio_map(chip)`** → resolves the `gpio_map_id` (Nord = 8240) and records ChipIO **release provenance** (`nordau_io v1.2 ECO F03`) into the snapshot for replay/freshness.
  - **`gpio_list_gpios_from_map(gpio_map_id, function=…, name=…)`** → **preferred parameterized path**; queries a specific audio pin/function directly.
  - **`gpio_list_tlmm_gpios(chip)`** → full 1280-pin enumeration fallback / audit path. Row = `{name, pad:{id,name,wakeup}, function, number, direction, special_condition, clock}`.
  - **Audio evidence (live, Nord):** `aud_intfc0_clk`(57), `aud_intfc0_ws`(58), `aud_intfc0_data0..5`(59–64), all function 1; **function-mux alternates on shared pads** — GPIO 61 = `aud_intfc0_data2`(fn1) *or* `aud_intfc10_clk`(fn2); GPIO 63 = `aud_intfc0_data4`(fn1) *or* `aud_intfc7_clk`(fn2). The `function` index **is** the pinmux authority.
- **Verdict rules:**
  - Pin exists AND design's claimed audio function is a valid mux alternate on that pad → `MATCH`.
  - Pin exists, function muxable, secondary attribute (direction/drive/bias) differs → `PARTIAL_MATCH`.
  - Pin exists but silicon cannot mux the claimed audio function to it → `DISAGREE_WITH_AUTHORITY` (+ worklist).
  - Pin number not present on silicon → `DISAGREE_WITH_AUTHORITY` (hard mismatch → `REVIEW_REQUIRED`).
  - GPIO map/tool genuinely unavailable at run time → `NOT_CROSS_CHECKABLE (authority_unavailable)` (a live/transport failure, **not** the old `_tool_unverified`).
- **Confidence rules:** `MATCH` from a DIRECT `function`-field lookup = **high**. A verdict resting on client-side name-heuristics rather than the `function` filter = *medium*. Provenance (`gpio_map` release id) recorded for replay.
- **Reviewer actions:** on disagreement — "verify pin `<n>`/`aud_intfc<x>` function assignment against silicon pinmux (map `<id>`); correct board/DTS pinmux if the pad cannot carry the function."

---

### Track T2 — Bus Validation  *(unchanged from V1)*

- **Purpose / inputs / authority:** as V1 §2/T2. Declared audio bus topology (I²S-only vs SoundWire; master count) vs the silicon SWI surface via `swi_search_swi` **union+stability** over `{SOUNDWIRE_MASTER, SWR_MSTR, SWR}`.
- **Verdict rules:** as V1 — 0=0 → `MATCH` (Nord's live-corroborated I²S-only); equal counts → `MATCH`; differ → `DISAGREE_WITH_AUTHORITY`; source self-flagged `ambiguous` (D5) → `NOT_CROSS_CHECKABLE`; result at/above cap → *provisional*.
- **Confidence / reviewer actions:** as V1 §2/T2.

---

### Track T3 — Audio Resource Validation  *(unchanged — delegates to WP-C)*

- **Purpose / mechanism:** as V1 §2/T3. **Constructs `gc["audio_topology"]["element_counts"]` and calls `compare_element_counts(gc)` UNCHANGED**, mapping each WP-C row to a `VerificationRow` (§3.5). Live in Phase-1C; reproduces D4 (`disagree_with_authority`) and D5 (`not_cross_checkable`).
- **Authorities:** `lpass_macro_instance` (swi union), `dsp_subsystem_instance` (`cores_list_core_instances`) → `catalog` lane.
- **Verdict/confidence/reviewer actions:** inherited verbatim from WP-C. **This is the engine's regression anchor.**

---

### Track T4a — SoC Endpoint Validation  *(V2: NEW — split from T4; implementable now)*

- **Purpose:** the SoC-side audio endpoints the design names actually **exist and are capable** on silicon — the controller/serial-engine and audio cores a codec is *supposed* to attach to.
- **Inputs (source):** `profile.json` — which controller/serial engine each codec is wired to (e.g. codec control on an I²C QUP; audio-data on an I²S/`aud_intfc` controller); DTS controller nodes.
- **IPCAT authorities (POSSIBLE_AUTHORITY — verified live):**
  - **`chipio_get_qups(chip)`** → 27 QUP serial engines; **all 27 I²C-capable** — the codec **control-bus** endpoints. (Note: **no `i2s`/`audio` flag** — QUPs are the control path only.)
  - **`cores_list_core_instances(chip)`** → 175 audio cores under `u_hpass_wrapper` (e.g. `Audio - QAIF`, `qdsp6ss` DSP wrappers) — proves audio controller/core existence.
  - **`buses_list_buses` / `bus_gateways` / `bidpidmids`** → `audio_core_noc`, `hpass_audio` fabric attachment (indirect corroboration).
- **Verdict rules:**
  - Design-named control engine (I²C QUP) exists on silicon → `MATCH`.
  - Named audio controller/core exists (`cores_list_core_instances`) → `MATCH`.
  - Design names a controller/engine that does **not** exist on silicon → `DISAGREE_WITH_AUTHORITY` (+ worklist).
  - Capability attribute differs (e.g. engine present but not I²C-capable) → `PARTIAL_MATCH`.
- **Confidence rules:** high on DIRECT QUP/core lookup; the NoC-fabric corroboration is *supporting* evidence (medium) not a primary verdict source.
- **Reviewer actions:** on disagreement — "verify the SoC endpoint (`QUP se_number`/audio core) the design assigns actually exists on `<chip>`; correct the controller assignment if not."

---

### Track T4b — Codec Binding Validation  *(V2: NEW — diagnostic-only, OUT OF SCOPE for IPCAT)*

- **Purpose:** the **codec ↔ controller binding** is correct end-to-end — does codec X (PCM1681 DAC, ADAU1979 ADC) actually hang off the specific DAI/port the design claims; is any codec orphaned.
- **Inputs (source):** `profile.json` codec list + claimed codec→controller wiring; DTS DAI-link nodes.
- **IPCAT authority:** **NONE.** Discovery confirmed **no tool and no field** in the 95-tool catalog exposes codec parts, I²S/TDM/PCM DAI-link endpoints, or the codec↔controller binding. Codecs are board parts; the binding is a **schematic fact IPCAT structurally does not hold.**
- **Verdict rule:** **always `NOT_CROSS_CHECKABLE` with reason `authority_out_of_scope`** (§3.6). This is a *permanent, deterministic* outcome — not a pending spike, not a transport failure.
- **Confidence:** `none` (no authority). The row still renders — it is an honest, first-class "coverage gap," making explicit *what IPCAT cannot check* so a reviewer knows to validate the binding from the schematic/DTS instead.
- **Reviewer actions:** "codec↔controller binding is not IPCAT-checkable (board/schematic fact); validate `<codec>`→`<controller>` against the schematic/DTS DAI-links directly." *(Future: a schematic/DTS-internal consistency track — not an IPCAT authority — could close this. Out of Phase-2A scope.)*

---

### Track T5 — DTS Consistency Validation  *(unchanged from V1)*

- **Purpose / authority / rules:** as V1 §2/T5. Catches the **donor bug** (`qcom,sa8775p-adsp-pas` + `sa8775p/adsp.mbn` + LCX/LMX on an SA8797P DTS) via `chips_list_chips` silicon identity + a KB namespace rule. Donor namespace on SA8797P silicon → `DISAGREE_WITH_AUTHORITY`; absent `qcom,board-id`/`msm-id` → revision sub-check `NOT_CROSS_CHECKABLE (revision_not_pinned)`.

---

## 3. Common verdict model

### 3.1–3.5 (unchanged from V1)

Five verdicts (`MATCH`, `PARTIAL_MATCH`, `DISAGREE_WITH_AUTHORITY`, `NOT_CROSS_CHECKABLE`, `REVIEW_REQUIRED`); WP-C mapping table; carried-over correctness rules (dt-unapplied, ambiguous→not_cross_checkable); per-row precedence; T3 row-translation — all as V1 §3.1–3.5.

### 3.6 (NEW) Coverage-gap reasons — `authority_out_of_scope`

Every `NOT_CROSS_CHECKABLE` row carries a machine-readable `reason`. V2 adds a third:

| Reason | Meaning | Nature | Example | Reviewer implication |
|---|---|---|---|---|
| `source_ambiguous` | The design/source self-flagged the value it cannot resolve to a single answer. | Data | Eliza soundwire_master `ambiguous:true` (D5). | Resolve the source ambiguity, then re-check. |
| `authority_unavailable` | The IPCAT authority tool **exists** but did not answer at run time (transport error, auth wall, empty release). | Transient / operational | `gpio_get_gpio_map` timed out. | Re-run; check access (D2/D3). |
| **`authority_out_of_scope`** *(NEW)* | The IPCAT catalog **structurally does not model** the fact. No tool or field exists, and none is expected — the authority lives in a different source (schematic/board). | **Permanent / architectural** | **T4b codec↔controller binding**; codec parts; DAI-link endpoints. | Do **not** wait for a tool. Validate from the schematic/DTS; treat as a known, permanent IPCAT boundary. |

**When `authority_out_of_scope` applies (decision rule):** use it **only** when discovery has confirmed *both* (a) no tool name matches the entity, **and** (b) no field inside a returned entity carries it, **and** (c) the fact is definitionally board/schematic data (not silicon-catalog data). If a tool merely *hasn't been checked yet*, the correct reason is a pending discovery item, not `authority_out_of_scope`. If a tool exists but failed, it is `authority_unavailable`. This distinction matters because `authority_out_of_scope` tells the reader **to stop looking in IPCAT** — a false application would hide a checkable fact.

*(V1's `authority_tool_unverified` is retired: T1's authority is now verified, and T4b's gap is correctly `authority_out_of_scope`, not "unverified.")*

---

## 4. Evidence schema — `phase2a_verification.json` (V2 delta)

Schema as V1 §4, with these additive changes:

1. **`rows[].track` enum** extends to `["T1", "T2", "T3", "T4a", "T4b", "T5"]` (was `T4`).
2. **`rows[].authority.origin` enum** adds the newly verified sources:
   `"ipcat.gpio_list_tlmm_gpios"`, `"ipcat.gpio_get_gpio_map"`, `"ipcat.gpio_list_gpios_from_map"`, `"ipcat.chipio_get_qups"`, `"ipcat.buses"` — and `"none"` for T4b.
3. **`confidence_report.coverage_gaps[].reason` enum** becomes:
   `["source_ambiguous", "authority_unavailable", "authority_out_of_scope", "insufficient_lanes", "revision_not_pinned"]`
   (**adds `authority_out_of_scope`; removes `authority_tool_unverified`**).
4. **`rows[].authority.strength`** unchanged enum `["IPCAT_DIRECT","IPCAT_DERIVED","KB_RULE","UNAVAILABLE"]`; T1 rows use `IPCAT_DIRECT`, T4a `IPCAT_DIRECT`/supporting, T4b `UNAVAILABLE`.

All boundary constants, `provenance`, worklist, and top-level verdict enum (`PASS`/`PASS_WITH_REVIEW`/`PARTIAL`/`FAIL`) are unchanged. Note: a run whose only gaps are T4b `authority_out_of_scope` rows is **not** `PARTIAL` on that account alone — `authority_out_of_scope` is an expected, permanent boundary and does not degrade the top-level verdict below `PASS`/`PASS_WITH_REVIEW`. (Contrast `authority_unavailable`, which does indicate an incomplete run → `PARTIAL`.)

---

## 5. Replayability (unchanged from V1 §5)

Collector freezes the snapshot (now including the GPIO map release id and QUP/bus results, each with a `result_digest`); the pure core replays byte-identically offline; `provenance.wp_c_commit` pins the unchanged lane. T4b rows are trivially replayable — they are deterministic `authority_out_of_scope` outcomes independent of any snapshot.

---

## 6. Prerequisites (revised from V1 §6)

| ID | Prerequisite | V2 status |
|---|---|---|
| **D1** | Correct IPCAT tool names in the collector. | Understood; collector written against verified names (§1.3). Probe binary fix separate/out of scope. |
| **D2** | TLS / corporate CA codified (`SSL_CERT_FILE` → system CA store; `verify=True`). | Required for any live run; must be codified in the 2A runner. |
| **D3** | Non-interactive (headless) IPCAT data access. | Required for **CI/unattended** runs; attended runs proceed (as Phase-1C/discovery did). Open operator item. |
| **~~A1~~** | *(V1)* Verify GPIO (T1) and connectivity (T4) authorities. | **RESOLVED by discovery.** T1 = DIRECT (verified). T4a = POSSIBLE (verified). **T4b is not a discovery item** — it is a structural IPCAT boundary → permanent `authority_out_of_scope`. A1 is closed. |

**No open discovery prerequisites remain.** D1/D2 gate any live run; D3 gates headless runs; A1 is closed.

---

## 7. Build order (REVISED per Task 4)

Priority sequence: **T3 → T1 → T2 → T5 → T4a**, with T4b implemented as a deterministic diagnostic-only stub.

| Order | Track | Why here |
|---|---|---|
| 1 | **T3** | Pure delegation to the already-live WP-C lane; validates row-translation against known Phase-1C output. **Regression anchor** — nothing else is trusted until T3 reproduces the six known verdicts. |
| 2 | **T1** | Newly unblocked DIRECT authority; highest new value (pinmux is foundational and now fully verifiable). Anchor against Nord `aud_intfc0_*` pins. |
| 3 | **T2** | Verified `swi_search_swi` union+stability; anchor against Nord `MATCH` (0=0) and Eliza counts. |
| 4 | **T5** | DTS identity + donor-bug KB rule; anchor against the known `FIXME(sa8797p-audio)` case → `DISAGREE_WITH_AUTHORITY`. |
| 5 | **T4a** | SoC-endpoint existence via QUP/cores/buses (POSSIBLE_AUTHORITY); lower priority — corroborative rather than defect-catching, and its verdict space is narrower. |
| 6 | **T4b** | **Diagnostic-only, always `NOT_CROSS_CHECKABLE (authority_out_of_scope)`.** No authority to build against — implement as the honest coverage-gap row + reviewer pointer to schematic/DTS. |
| 7 | — | Renderer + worklist + confidence_report + additive section. |

**Acceptance:** given the frozen Phase-1C snapshot, the engine reproduces the six T3 verdicts exactly; T1 emits real `MATCH`/mismatch rows for Nord audio pins; T5 flags the donor bug; T4b emits deterministic `authority_out_of_scope` rows; Nord's comparable rows → `PASS`/`PASS_WITH_REVIEW` (Eliza D4 in the worklist); all boundary flags are the required constants; replay is byte-identical.

---

## 8. Final readiness assessment

| Track | Readiness | Authority basis | Notes |
|---|---|---|---|
| **T1 — GPIO Validation** | **IMPLEMENTATION_READY** | DIRECT — `gpio_list_tlmm_gpios`, `gpio_get_gpio_map`, `gpio_list_gpios_from_map` (live-verified) | Audio pins + function-mux alternates confirmed on Nord. |
| **T2 — Bus Validation** | **IMPLEMENTATION_READY** | `swi_search_swi` union+stability (verified Phase-1C) | Provisional flag when at cap. |
| **T3 — Audio Resource Validation** | **IMPLEMENTATION_READY** | WP-C lane over `cores_list_core_instances` + `swi_search_swi` (live Phase-1C) | Regression anchor; reproduces D4/D5. |
| **T4a — SoC Endpoint Validation** | **PARTIALLY_READY** | POSSIBLE_AUTHORITY — `chipio_get_qups` + `cores_list_core_instances` + `buses_*` | Validates endpoint **existence/capability**, not codec binding. Narrow but real verdict space. |
| **T4b — Codec Binding Validation** | **OUT_OF_SCOPE** | NONE (structural IPCAT boundary) | Always `authority_out_of_scope`; defer to schematic/DTS-internal check (future track). |
| **T5 — DTS Consistency Validation** | **IMPLEMENTATION_READY** | `chips_list_chips` identity + KB namespace rule (verified) | Catches donor bug; revision sub-check `NOT_CROSS_CHECKABLE (revision_not_pinned)`. |

**Launch summary:** **4 tracks IMPLEMENTATION_READY** (T1, T2, T3, T5), **1 PARTIALLY_READY** (T4a), **1 OUT_OF_SCOPE** (T4b). Phase-2A launches with five contributing tracks (T1/T2/T3/T5 + T4a) — well beyond V1's T2/T3/T5-only fallback — with T4b rendered honestly as a permanent, documented IPCAT coverage boundary rather than a stub or a pending spike.

---

*Specification update only. No implementation, no code changes, no probe changes, WP-C lane referenced as unchanged (`28f2f07`), nothing committed. All authority classifications trace to live evidence in `PHASE2A_AUTHORITY_DISCOVERY.md`; the T4b boundary is recorded as structural, not assumed.*
