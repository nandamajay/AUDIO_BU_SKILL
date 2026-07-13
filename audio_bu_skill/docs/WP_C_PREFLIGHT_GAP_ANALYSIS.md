# WP-C Pre-Flight Gap Analysis — STOP

**Verdict: the mandatory pre-flight FAILS. WP-C is NOT implemented in this pass.**

The architecture review's single pre-flight check was: *verify on real Nord and Eliza data that machine-countable `dt_count` / `evidence_count` / `proposal_count` exist, show exactly where they come from, and determine whether `collect_counts()` can be built without schema changes.* Per the approved instruction — "If counts are missing, incomplete, ambiguous, or only available in prose: STOP. Do not implement WP-C. Produce a gap analysis and recommended fix." — this document is that gap analysis. **No `cardinality*.py` files were created. Nothing was modified, staged, or committed.**

This is exactly the outcome the review flagged as the plan-invalidating risk (§7 under-engineering): *"Verify [dt/evidence/proposal counts are countable] before writing `collect_counts` — if the runner doesn't currently emit a machine-countable proposal_count (vs prose), WP-C's first stage has no input and silently produces all-`not_cross_checkable`."* On real data, that risk is realized.

---

## 1. Method — what I actually read (no assumptions)

Real stored artifacts for both onboarded targets, this session:

| Artifact | Nord | Eliza | Role |
|---|---|---|---|
| `case.generated.py` (`audio_topology`) | ✓ read in full | ✓ read in full | what reaches the renderer as `gc` |
| `qgenie_analysis.json` (raw envelope) | ✓ read in full | ✓ read in full | the pre-map analysis, incl. `buses`/`schematic_nets` |
| `profile.json` | ✓ inspected keys | ✓ inspected keys | no count fields |
| `qgenie_task_spec.json` | ✓ inspected | ✓ inspected | `candidate_patch_series` lives here (input only) |
| `evidence_inventory.json` | ✓ | ✓ | file list only, no per-element counts |
| `orchestrator/reasoning/schemas.py` (ANALYSIS_SCHEMA v1.2.0) | ✓ read in full | — | the typed contract |
| `orchestrator/main.py` render path (`_render_confidence_ledger`, `_render_onboarding_report`) | ✓ read | — | confirms only `gc` (not the raw envelope) reaches the renderer |
| `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` Track C (C.1–C.9) | ✓ read | — | the count-source definitions |

---

## 2. Where each count would have to come from (mapped against real data)

Per spec C.2, the three pre-SWI sources are `dt_count` (instances in the applied kernel DT), `evidence_count` (from offline/schematic extraction), `proposal_count` (what the case proposes). Mapping each to a real, machine-readable field:

### 2a. `proposal_count` — **PARTIALLY available, mostly as list-length, semantically wrong for the flagship class**

`audio_topology` carries typed arrays (`schemas.py:114-117`, `_CODEC_ITEM`): `codecs[]`, `amplifiers[]`, `mics[]`, `speakers[]`, and a typed `soundwire.master_count` integer (`schemas.py:123`). So *a* proposal number is machine-readable via `len(list)` / the int. **But the list length is not the instance count** for the element classes WP-C is defined over (C.1: `soundwire_master`, `lpass_macro_instance`, `dai_link`, `dmic_line`, `audioreach_port`, `dsp_subsystem_instance`). Real Eliza data:

| Element | `audio_topology` machine value | True instance count | Where the true count lives |
|---|---|---|---|
| DMIC lines | `mics[]` len = **2** | **8** | inside the prose `part` string `"8x DMIC (digital PDM mics)"` and `role` |
| WSA amps | `amplifiers[]` len = **1** | **2** | prose: `"2x stereo… (Speaker 0 / Speaker 1)"` |
| speakers | `speakers[]` len = **2** | 2 | matches by luck (one row per speaker) |
| soundwire_master | `soundwire.master_count` = **1** | **1 or 2 (unresolved)** | `master_count`=1 but `missing_evidence` says "could be 1 or 2" |

The one element WP-C most exists to serve — `soundwire_master` on Eliza — has a typed integer (`master_count=1`) that **the case's own `missing_evidence` explicitly contradicts** ("could be 1 or 2 physical master instances; not resolved"). The honest count is *ambiguous*, and the ambiguity is only in prose. None of C.1's other five element classes (`lpass_macro_instance`, `dai_link`, `audioreach_port`, `dsp_subsystem_instance`, `dmic_line`) has a dedicated typed count field at all.

### 2b. `dt_count` — **NOT available (structurally zero on both targets, and not because the tool counted zero)**

`dt_count` means "instances present in the applied kernel DT." On **both** targets the entire audio scaffolding is *unapplied* at the pinned kernel HEAD:
- Nord `missing_evidence[0]`: *"The entire audio DT/config scaffolding … exists ONLY as loose root-level .patch files (0002-0005) … None of it is applied or committed at that HEAD."*
- Eliza `missing_evidence[1]`: *"all audio DT wiring is still pending as unapplied FROMLIST patches … not yet present in the kernel tree."*

So a true `dt_count` is legitimately **0 for every audio element class on both targets** — but there is **no structured field that records this as a count.** It's derivable only by parsing the prose `missing_evidence` and the citation strings (e.g. Nord `soundwire.citations`: *"grep at HEAD … no soundwire-controller/SWR node"*). There is no DT-node enumeration artifact anywhere in the stored outputs. `collect_counts` cannot read a `dt_count` it can trust; it can only read "0" and would have to *know* that 0 means "unapplied," not "absent from silicon" — a distinction that lives only in prose.

### 2c. `evidence_count` — **NOT available as a count; only as prose + un-parsed binary evidence**

`evidence_count` means "from offline/schematic evidence extraction." The schematic-derived structured field is `schematic_nets[]` (Eliza: 4 entries; Nord: **0**). But those entries are **net-name groups, not element instances** — Eliza's single `schematic_nets` row `"DMIC01_CLK/DATA, DMIC23_CLK/DATA, DMIC45_CLK/DATA, DMIC67_CLK/DATA"` encodes 8 DMICs in one string. The real per-element evidence counts (8 DMICs, 2 AMICs, 2 WSA amps) are asserted in prose inside `mics[].role` / `buses[]` (`"DMIC PDM bus … 4 stereo pairs = 8 DMICs"`), never as integers. Nord has **no** `schematic_nets` at all in its envelope, and its offline evidence (`IQ10_RRD_IO_Mapping.xlsx`, PPTM, PDFs) was *"not re-opened this session"* per its own `missing_evidence`. So `evidence_count` is prose on Eliza and absent on Nord.

---

## 3. The three-source cross-check collapses on real data

WP-C's value (spec C.3–C.6) is *comparing independent counts*. On the only two real targets:

| Element class | dt_count | evidence_count | proposal_count | Independent sources available | Verdict WP-C could emit |
|---|---|---|---|---|---|
| **Eliza soundwire_master** | 0 (prose: unapplied) | prose ("1 or 2") | 1 (typed, but self-contradicted) | **0 machine-comparable** | `not_cross_checkable` |
| Eliza dmic_line | 0 (unapplied) | prose (8) | list-len 2 ≠ true 8 | 0 reliable | `not_cross_checkable` or **false `disagree`** |
| Eliza wsa amp | 0 | prose (2) | list-len 1 ≠ true 2 | 0 reliable | false `disagree` |
| Nord (all audio) | 0 (unapplied) | 0 (not opened) | list-len (codecs=2) | 1 at most | `not_cross_checkable` |

**Every row is either `not_cross_checkable` or a *false* `disagree` driven by list-length ≠ true-count.** There is no row on either real target where two trustworthy independent integers can actually be compared. The cross-check — the entire point of Track C — has no real input today.

Worse than "no value": using `len(list)` as `proposal_count` would emit **false `disagree` warnings** (Eliza DMIC 2-vs-8, amp 1-vs-2) into the `## NEEDS_REVIEW` channel — actively misleading, the exact trust-inversion class WP-B was just refined to eliminate. Shipping it would regress the credibility gain from WP-B.

---

## 4. Can `collect_counts()` be implemented without schema changes?

**No — not in a form that produces trustworthy counts.**

- A `collect_counts` that reads only existing typed fields (`len(codecs)`, `soundwire.master_count`, …) **compiles without schema changes** but is *semantically wrong*: list-length ≠ instance-count for 3 of 4 Eliza element classes, and the classes WP-C names (C.1) mostly have no typed field at all.
- A `collect_counts` that produces *correct* counts must extract integers from prose (`"8x DMIC"`, `"2x … Speaker 0 / Speaker 1"`, `"could be 1 or 2"`) or re-derive `dt_count` by parsing citation strings and `missing_evidence`. That is prose-scraping, not counting — brittle, and precisely the "only available in prose" STOP trigger.
- `dt_count` and `evidence_count` have **no structured home at all** in ANALYSIS_SCHEMA v1.2.0. Producing them reliably requires the runner/analyzer to *emit* them — a schema addition — which is explicitly forbidden this pass ("No schema version changes").

So the honest answer to pre-flight Q3 is: `collect_counts()` can be *written* without schema changes, but it cannot be *correct* without them. That fails the "incomplete / ambiguous / only in prose" bar.

---

## 5. Root cause

WP-C's design (spec C.2) assumes the onboarding analyzer emits **per-element-class integer counts from three independent extraction lanes.** The analyzer as built emits **per-part findings with prose roles and a single typed `soundwire.master_count`.** The instance-count information exists in the data — QGenie clearly knows there are 8 DMICs and 2 amps — but it is expressed as English inside `role`/`buses`/`missing_evidence`, not as machine integers. Track C was specified for a data shape the analyzer does not (yet) produce. This is a genuine upstream gap, not a rendering nuance.

---

## 6. Recommended fix (smallest correct change, for a future authorized pass)

The fix belongs **upstream of WP-C**, in the analysis contract — and it is an *additive, version-bumped* schema change, so it is out of scope for this instruction and must be separately approved.

**Fix A (required, enables WP-C correctly): additive schema field `element_counts` (ANALYSIS_SCHEMA → 1.3.0).**
Add an optional, additive envelope key that captures what QGenie already knows in prose as structured integers per C.1 element class and per source lane:
```
"element_counts": {                      # optional; absent → pre-1.3.0 behavior
  "soundwire_master": {"proposal": 1, "evidence": null, "dt": 0,
                       "ambiguous": true, "citations": [...]},
  "dmic_line":        {"proposal": 8, "evidence": 8, "dt": 0, "citations": [...]},
  "wsa_amp":          {"proposal": 2, "evidence": 2, "dt": 0, "citations": [...]}
}
```
- Additive and optional (a 1.2.0 response still validates), mirroring how `schematic_nets` (1.1.0) and `ipcat_findings` (1.2.0) were added — the established additive-bump pattern.
- Carries an explicit `ambiguous` flag so Eliza's "1 or 2 masters" becomes a *typed* `not_cross_checkable`, not a fabricated integer.
- `dt: 0` + a `dt_applied: false` sibling (or reuse `missing_evidence`) so `collect_counts` can distinguish "0 because unapplied" from "0 because absent."
- The onboarding prompt must ask QGenie to fill it (it already surfaces these numbers in prose, so this is a formatting ask, not new reasoning).

**Fix B (cheap, ship regardless): the element-class *config* is dependency-free.**
`orchestrator/reasoning/cardinality_config.py` (the C.1 element-class list + matcher specs) has no data dependency and can be written now — it's just labels + matcher patterns, unit-testable against fixtures. But `cardinality.py`'s `collect_counts`/`compare` should **not** ship until Fix A gives it real integers, else it emits false `disagree`s.

**Sequencing recommendation:** do **not** proceed to WP-C on the current data shape. Either (1) authorize the additive `element_counts` schema bump (Fix A) + re-run onboarding for Nord/Eliza so real counts populate, *then* implement WP-C against real integers; or (2) if the immediate goal is the SoundWire master-count question specifically, that number is fundamentally unresolvable pre-SWI on Eliza (the review and SWI spike both conclude the catalog is the only authority) — so the SWI read-only probe would deliver more than a cardinality section that can only say "can't tell."

---

## 7. What this pre-flight did NOT find (fairness check)

To be clear about scope so this isn't over-read:
- The **element-class enum/labels** are implementable now (Fix B) — no blocker there.
- The **render integration point** is clean and available (adjacent to `_render_confidence_ledger`, before `## Promotion`) — no blocker there.
- The **verdict vocabulary** (agree/disagree/not_cross_checkable/benign_divergence/disagree_with_authority) is sound — no blocker there.
- The blocker is **exclusively** the input data: no trustworthy machine-countable `dt_count`/`evidence_count`, and a `proposal_count` that is either list-length (wrong) or a self-contradicted typed int. That is the one thing WP-C's first stage cannot run without.

---

## 8. Bottom line

- **Pre-flight result: FAIL (STOP).** dt_count: absent (structurally 0, prose-only, no field). evidence_count: prose-only on Eliza, absent on Nord. proposal_count: list-length (semantically wrong for 3/4 element classes) or a self-contradicted `master_count`.
- **`collect_counts()` cannot be correct without an additive schema change** — forbidden this pass.
- **Implementing WP-C now would emit false `disagree` warnings** (list-length ≠ true count) into the review channel, regressing the trust gain WP-B just delivered.
- **No WP-C files created. Nothing modified, staged, or committed.** WP-B remains closed and green.
- **Recommended next step:** authorize the additive `element_counts` schema bump (1.3.0) + Nord/Eliza re-run, *or* pivot to the read-only SWI probe (the SoundWire master-count that motivates WP-C is unresolvable pre-SWI anyway). I'll await your decision before writing any code.

---

**Evidence:** live inspection of `targets/{nord-iq10,eliza}/case.generated.py`, `qgenie_analysis.json`, `profile.json`, `qgenie_task_spec.json`, `evidence_inventory.json`; `orchestrator/reasoning/schemas.py` (ANALYSIS_SCHEMA v1.2.0); `orchestrator/main.py` render path; `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` Track C (C.1–C.9). Nord/Eliza used strictly as validation examples; no target-specific logic proposed.
