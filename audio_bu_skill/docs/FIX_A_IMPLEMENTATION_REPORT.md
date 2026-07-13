# Fix A — Implementation Report: ANALYSIS_SCHEMA 1.3.0 `element_counts`

**Status:** Implemented, validated, green. Not committed, not pushed.
**Design of record:** `docs/FIX_A_ELEMENT_COUNTS_SCHEMA_DESIGN.md` (approved).
**Scope guard honored:** WP-C, `cardinality.py`, cardinality rendering, `catalog_count`, and SWI work were **not** implemented. This change is purely the additive schema + prompt + threading that WP-C's pre-flight identified as its prerequisite.

---

## 1. What Fix A does (one paragraph)

QGenie already knew the true instance counts and said them in prose (`"8x DMIC"`, `"2x … Speaker 0/1"`), but the only machine-readable signal downstream had was `len(codecs[])` / `len(amplifiers[])` — a **part-number count**, not an **instance count**. On Eliza that made `len(amplifiers)==1` (one WSA8845 part) hide that there are **2** physical amplifiers, and `len(mics)==2` hide that there are **8** DMIC lines. Fix A adds an optional, typed `element_counts` array to ANALYSIS_SCHEMA so the model reports physical-instance counts per independent enumeration lane (`dt` / `evidence` / `proposal` / `catalog`), giving a future Cardinality Authority a countable input instead of a lie derived from list length. The change is additive-only: a 1.2.0-shaped response with no `element_counts` still validates unchanged.

---

## 2. Files modified

### Production code
| File | Change |
|---|---|
| `orchestrator/reasoning/schemas.py` | `ANALYSIS_SCHEMA_VERSION` `1.2.0`→`1.3.0`; new `_ELEMENT_COUNT_ITEM` item schema; new optional `element_counts` property on `ANALYSIS_SCHEMA`. `required` list unchanged. |
| `orchestrator/reasoning/client.py` | `build_prompt()`: added one paragraph instructing QGenie to populate `element_counts` as **physical-instance** counts per lane, with the instance-count≠part-count rule, null-vs-0 semantics, `dt_applied`, `ambiguous`/`ambiguity_note`, `catalog`-stays-null, and cite-every-count. |
| `orchestrator/runners/target_onboarding_runner.py` | `_build_audio_topology()`: threads `analysis["element_counts"]` into `audio_topology["element_counts"]` verbatim (same pattern as `ipcat_findings`), only when truthy. |
| `orchestrator/reasoning/ledger.py` | `FIELD_DOMAIN_EXCLUDED`: added `"element_counts"` so the schema-coverage drift-guard stays exhaustive. **No status/band logic touched** — the ledger reads none of it (it is WP-C input, not a trust domain). |

### Tests
| File | Change |
|---|---|
| `tests/test_analysis_schema_v1_1.py` | Version assertion → `1.3.0`; `_V1_3_STYLE_ANALYSIS` fixture; validation + rejection tests for `element_counts` (empty-list ok, missing `element_class` rejected, negative lane rejected, non-integer lane rejected, null lane ok, 1.2.0-without-element_counts still validates); real-artifact backward-compat via frozen fixtures. |
| `tests/test_target_onboarding_wiring.py` | `test_build_audio_topology_threads_element_counts_when_present` and `..._omits_element_counts_when_absent` (empty list treated as absent). |
| `tests/test_confidence_ledger.py` | `test_element_counts_does_not_perturb_ledger` — `build_ledger` byte-identical with/without `element_counts`. |

### New fixtures
| File | Purpose |
|---|---|
| `tests/fixtures/schema_1_2_0/nord-iq10_qgenie_analysis.json` | Frozen real 1.2.0 Nord analysis (no `element_counts`), captured **before** the Fix A re-run. |
| `tests/fixtures/schema_1_2_0/eliza_qgenie_analysis.json` | Frozen real 1.2.0 Eliza analysis (no `element_counts`), captured **before** the Fix A re-run. |

### Regenerated target artifacts (live QGenie re-run)
- `targets/nord-iq10/{qgenie_analysis.json, case.generated.py, onboarding_report.md}` — run `nord-iq10-onboarding-4`.
- `targets/eliza/{qgenie_analysis.json, case.generated.py, onboarding_report.md}` — run `eliza-onboarding-11`.

---

## 3. Schema diff

```diff
-ANALYSIS_SCHEMA_VERSION = "1.2.0"
+# 1.3.0 (Fix A — element_counts): additive only — adds optional `element_counts`,
+# per-element-class instance counts as typed integers from each independent
+# enumeration lane (dt / evidence / proposal / catalog). Gives the counts QGenie
+# already surfaces in prose a machine-countable home. `catalog` declared but
+# always null pre-SWI so the post-SWI upgrade stays additive. A 1.2.0-shaped
+# response (no element_counts) still validates.
+ANALYSIS_SCHEMA_VERSION = "1.3.0"

+_ELEMENT_COUNT_ITEM = {
+    "type": "object",
+    "properties": {
+        "element_class": {"type": "string"},
+        "dt":       {"type": ["integer", "null"], "minimum": 0},
+        "evidence": {"type": ["integer", "null"], "minimum": 0},
+        "proposal": {"type": ["integer", "null"], "minimum": 0},
+        "catalog":  {"type": ["integer", "null"], "minimum": 0},   # always null pre-SWI
+        "ambiguous": {"type": "boolean"},
+        "ambiguity_note": {"type": "string"},
+        "dt_applied": {"type": "boolean"},
+        "citations": {"type": "array", "items": {"type": "string"}},
+    },
+    "required": ["element_class", "citations"],
+    "additionalProperties": True,
+}

 ANALYSIS_SCHEMA["properties"] = {
     ...
     "ipcat_findings": _IPCAT_FINDINGS_ITEM,
+    "element_counts": {"type": "array", "items": _ELEMENT_COUNT_ITEM},
 }
 # ANALYSIS_SCHEMA["required"] UNCHANGED
```

**Type semantics that matter downstream:**
- Each lane is `["integer","null"], minimum:0`. **`null` = lane not consulted / cannot produce a count**; **`0` = affirmatively none**. These are distinct and both preserved.
- `dt_applied: false` with `dt: 0` = "audio scaffolding unapplied at pinned HEAD," not "absent from silicon."
- `element_class` is a free string in the schema; the known-class vocabulary is validated *downstream*, so adding a class is a config change, not a schema bump.
- `catalog` is declared but always emitted `null` pre-SWI, so the eventual Track-D upgrade that fills it is itself additive.

---

## 4. Nord before / after (real, run `nord-iq10-onboarding-4`)

Everything except `element_counts` is unchanged by Fix A:

| Field | Before (1.2.0) | After (1.3.0) |
|---|---|---|
| soc | SA8775P-class | same |
| codecs (list len) | 2 | 2 |
| amplifiers (list len) | 0 | 0 |
| soundwire.present | false | false |
| power_model.kind | unknown | unknown |
| overall_confidence | 0.45 | 0.45 |
| human_review_needed | true | true |
| **element_counts** | **absent** | **6 rows (below)** |

**Populated `element_counts` (6 rows):**

| element_class | dt | dt_applied | evidence | proposal | ambiguous | note |
|---|---|---|---|---|---|---|
| dsp_subsystem_instance | 0 | false | null | 1 | — | ADSP PAS in patch 0003, **0 applied at HEAD** |
| dai_link | 0 | false | null | 2 | — | playback (I2S8→pcm1681) + capture (I2S8→adau1979) |
| audioreach_port | 0 | false | null | 2 | **true** | QUATERNARY_TDM_RX_0/TX_0 are **explicit placeholders**; I2S8 macro unconfirmed; 1-bidir-vs-2-unidir unresolved |
| amplifier | 0 | false | **0** | **0** | — | DAC+ADC only, no WSA/discrete amp in any evidence |
| soundwire_master | 0 | false | **0** | **0** | — | no SWR node; codecs are I2S/TDM-attached |
| lpass_macro_instance | 0 | false | **0** | **0** | — | no lpass wsa/va macro wired |

Nord demonstrates the **`0` vs `null` distinction on real data**: `amplifier`/`soundwire_master`/`lpass_macro_instance` are affirmative `0` (determined none), while `dt` is `0`+`dt_applied:false` (unapplied), and `evidence` on the proposal-only rows is `null` (not consulted). Every row is `dt_applied:false` — Nord's audio scaffolding is entirely unapplied at the pinned HEAD, and the flag says so precisely.

---

## 5. Eliza before / after (real, run `eliza-onboarding-11`)

| Field | Before (1.2.0) | After (1.3.0) |
|---|---|---|
| codecs (list len) | 1 | 1 |
| amplifiers (list len) | **1** | **1** |
| soundwire.present | true | true |
| soundwire master_count | 1 | 1 |
| overall_confidence | 0.62 | 0.72 |
| human_review_needed | true | true |
| **element_counts** | **absent** | **8 rows (below)** |

**Populated `element_counts` (8 rows) — this is where Fix A pays off:**

| element_class | dt | dt_applied | evidence | proposal | ambiguous | note |
|---|---|---|---|---|---|---|
| dsp_subsystem_instance | **1** | **true** | null | 1 | — | **eliza.dtsi:1971 — ADSP is applied in Eliza's tree** |
| soundwire_master | 0 | false | **3** | 1 | **true** | schematic shows SWR0/SWR_RX/SWR_TX=3, applied candidate wires only swr0=1 — **evidence and proposal disagree** |
| dmic_line | 0 | false | **8** | **8** | — | 8 DMIC lines from LD20-93542-1 |
| amplifier | 0 | false | **2** | **2** | — | **2 WSA8845 instances** (one part number) |
| speaker | 0 | false | **2** | **2** | — | Speaker 0/1 |
| lpass_macro_instance | 0 | false | null | 2 | — | WSA macro + VA macro |
| dai_link | 0 | false | null | 2 | — | va-dai-link + wsa-dai-link |
| audioreach_port | 0 | false | null | 2 | — | VA_CODEC_DMA_TX_0 + WSA_CODEC_DMA_RX_0 |

**The bug Fix A fixes, shown on real data:**
- `amplifier evidence/proposal = 2` while `len(amplifiers[]) == 1`. The list length was a **part-number** count (one WSA8845); the true **instance** count is 2. Before Fix A this was unrecoverable downstream.
- `dmic_line evidence = 8` — there is no `mics` list length that would have surfaced 8 DMIC lines as a machine number.
- `dsp_subsystem_instance dt=1 / dt_applied=true` — Eliza's ADSP **is** applied at HEAD, so the same flag that reads `false` on all six Nord rows reads `true` here. This validates that `dt_applied` discriminates "unapplied" from "present in silicon," on real, contrasting targets.
- `soundwire_master` `evidence=3, proposal=1, ambiguous=true` — the schematic (3 buses) and the applied candidate (1 bus, WCD9378 not wired) genuinely disagree, and the model reported the disagreement as structured data + an `ambiguity_note` rather than collapsing it to a single wrong integer.

---

## 6. Backward-compatibility proof

1. **Schema `required` unchanged.** `ANALYSIS_SCHEMA["required"]` and the skill's `schema.json` `generated_case.required` are byte-identical to 1.2.0. A pre-slice output shape still satisfies them (asserted in `test_skill_schema_json_still_valid_json_and_backward_compatible`).
2. **1.2.0-shaped analyses validate under 1.3.0.** `_V1_0/_V1_1/_V1_2_STYLE_ANALYSIS` (none carrying `element_counts`) validate unchanged (`test_v1_2_style_analysis_still_validates_without_element_counts`).
3. **Real frozen artifacts validate.** The actual Nord + Eliza `qgenie_analysis.json` as produced under 1.2.0 (frozen in `tests/fixtures/schema_1_2_0/`, asserted to contain **no** `element_counts`) both validate under the 1.3.0 schema (`test_stored_1_2_0_target_artifacts_still_validate`, checked==2).
4. **Absent ≠ empty ≠ zero, all handled.** absent key = "not reported" (validates); `[]` = "reported, nothing enumerated" (validates); lane `null` = "not consulted"; lane `0` = "affirmatively none" — all four tested.
5. **Ledger untouched.** `build_ledger()` is byte-identical with and without `element_counts` (`test_element_counts_does_not_perturb_ledger`); it produces the same 9 rows on both regenerated cases. `element_counts` is in `FIELD_DOMAIN_EXCLUDED`, keeping the schema-coverage drift-guard exhaustive without giving it trust semantics.
6. **No promotion.** `targets/eliza/case.py` does not exist; `targets/nord-iq10/case.py` is untouched (dated Jul 13 00:30, pre-existing). Only `case.generated.py` was written.

---

## 7. Validation results

| Check | Result |
|---|---|
| Full test suite | **21/21 modules green** |
| Schema version | `1.3.0` |
| `build_prompt` determinism | identical across 5 runs; `element_counts` instruction present |
| 1.3.0 validation | deterministic; typed-integer / null / rejection cases all pass |
| Ledger byte-stability | 9 rows, identical with/without `element_counts`, on both regenerated cases |
| Nord re-run | `nord-iq10-onboarding-4`, 6 element_counts rows, validates |
| Eliza re-run | `eliza-onboarding-11`, 8 element_counts rows, validates |
| No kernel-tree mutation | confirmed (wiring test re-verifies sha256 + file list) |
| No promotion | confirmed (no `case.py` created/modified) |

---

## 8. Remaining risks

1. **Emission is model-governed, not deterministic.** The lane counts come from QGenie per-run. The schema *enforces shape* (types, `minimum:0`, required keys) but cannot enforce *correctness* of a count or that a given class is emitted. Mitigation in place: cite-every-count is required by the prompt; ambiguity must be reported, not guessed. A future WP-C should treat these as evidence to reconcile, not as ground truth.
2. **`element_class` vocabulary is unvalidated in-schema by design.** A typo'd or novel class name will validate. This is intentional (target/class-agnostic), but means the downstream consumer (WP-C) owns vocabulary validation — that consumer does not exist yet.
3. **`catalog` is structurally present but always null.** No catalog/SWI source is wired this session (out of scope). The lane exists only so the eventual fill is additive; until then it carries no signal.
4. **Two-target evidence base.** The instance-count win is demonstrated on Nord and Eliza only. Other targets may surface element classes or lane-disagreement shapes not yet seen; the additive schema accommodates them, but they are unproven.
5. **Prompt-length pressure.** `build_prompt` grew by one paragraph. No truncation observed, but the analysis instruction is now longer; if further additive fields are added, prompt budget should be watched.

---

## 9. Recommendation for WP-C readiness

**Fix A closes the gap that failed WP-C's pre-flight.** The pre-flight blocked because there was no machine-countable `dt` / `evidence` / `proposal` count on real data — only list-lengths that conflate part-numbers with instances. The Fix A re-run produced exactly those counts on both real targets, including the discriminating cases WP-C needs:

- true instance counts that **contradict** list-length (`amplifier=2` vs `len==1`, `dmic_line=8`);
- a real cross-lane **disagreement** captured as structured data (`soundwire_master evidence=3 / proposal=1 / ambiguous`);
- the applied-vs-unapplied discriminator working in both directions (`dt_applied=true` on Eliza's ADSP, `false` across all of Nord).

**Recommendation:** WP-C now has a trustworthy, machine-countable input and can be scoped against real element_counts shapes. **WP-C implementation still requires separate explicit approval** and remains out of scope here — Fix A delivered only the additive prerequisite, per the approved plan. When WP-C is approved, it should consume `audio_topology.element_counts` as reconciliation evidence (comparing lanes, honoring `null`≠`0` and `ambiguous`), not as authoritative truth, per risks 1–2 above.

---

*Not committed. Not pushed. Implementation, validation, and report complete.*
