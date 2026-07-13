# Fix A — ANALYSIS_SCHEMA 1.3.0 `element_counts` Extension (Design & Validation)

**Status:** Architecture/design only. **No code modified. No schema file changed. Nothing implemented, staged, or committed.** This document designs the additive `element_counts` extension identified in `docs/WP_C_PREFLIGHT_GAP_ANALYSIS.md` as the prerequisite that must exist before WP-C (Cardinality Authority) can be built on trustworthy integer counts. **WP-C is NOT implemented and NOT designed here** — this is strictly the upstream data-contract fix.

**Standing constraints honored:** additive-only, backward compatible, target-agnostic, no gating, no promotion/onboarding-decision change, no IPCAT/catalog_count/Track D/learn-loop work.

---

## Part A — Schema Proposal

### A.1 The problem this closes (one paragraph)

Track C (spec C.2) needs, per element class, integer counts from up to four independent lanes (`dt` / `evidence` / `proposal` / `catalog`). The analyzer today emits **per-part findings with prose roles** (`mics[].role = "8x DMIC …"`) and exactly one typed count integer (`soundwire.master_count`). The instance counts *exist in the model's output* but as English, not integers — so `collect_counts()` cannot read a trustworthy count for any class except a self-contradicted `soundwire_master`. `element_counts` gives those numbers a **typed, cited, ambiguity-aware home** without disturbing any existing field.

### A.2 Version bump

`ANALYSIS_SCHEMA_VERSION`: **`1.2.0` → `1.3.0`**. Minor bump = additive-only, consistent with the two prior additive bumps (`1.1.0` added `schematic_nets`; `1.2.0` added `ipcat_findings`). The version is recorded in the reasoning fingerprints, so the bump surfaces as expected drift on `--rerun` (not a silent change).

### A.3 New optional envelope key: `element_counts`

Proposed addition to `ANALYSIS_SCHEMA["properties"]` (NOT added to `required`):

```python
# New in 1.3.0, optional: per-element-class instance counts from each
# independent enumeration lane, as typed integers (Track C / WP-C input).
# Absent means "not reported" (a pre-1.3.0 response), NOT "count is zero".
# Each lane value is: an integer >= 0, OR null when that lane was not
# consulted / cannot produce a count. `ambiguous` marks a count the model
# itself could not resolve to a single integer (e.g. Eliza "1 or 2 masters").
_ELEMENT_COUNT_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "element_class": {"type": "string"},   # must be a known C.1 class key
        "dt":       {"type": ["integer", "null"], "minimum": 0},
        "evidence": {"type": ["integer", "null"], "minimum": 0},
        "proposal": {"type": ["integer", "null"], "minimum": 0},
        # catalog is DECLARED but always null pre-SWI. Present in the schema so
        # the post-SWI upgrade (Track D) is itself additive — no future bump.
        "catalog":  {"type": ["integer", "null"], "minimum": 0},
        "ambiguous":     {"type": "boolean"},   # true => at least one lane is a range, not a point
        "ambiguity_note": {"type": "string"},   # free text, e.g. "1 or 2 masters; 'dedicated' SWR0 unresolved"
        "dt_applied":    {"type": "boolean"},   # false => dt=0 means "scaffolding unapplied at HEAD", not "absent from silicon"
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["element_class", "citations"],
    "additionalProperties": True,
}
```

```python
# in ANALYSIS_SCHEMA["properties"]:
"element_counts": {"type": "array", "items": _ELEMENT_COUNT_ITEM},
```

### A.4 Design decisions and why

| Decision | Rationale |
|---|---|
| **Array of typed rows**, not a nested dict keyed by class | Mirrors `codecs`/`schematic_nets`/`nearest_targets` (all arrays of typed items) — consistent house style, and `additionalProperties: True` lets a row carry extra fields without a bump. |
| **`element_class` is a free string**, validated against C.1 keys **in `cardinality_config.py`**, not in the schema | Keeps the schema target-agnostic and class-list-agnostic. Adding a new element class (spec C.8) stays a config change, never a schema change. The schema enforces *shape*; the config enforces *vocabulary*. |
| **Every lane nullable, `minimum: 0`** | Distinguishes "0 instances" (integer 0) from "lane not consulted" (`null`). This is the exact distinction the pre-flight showed was missing — without it, `dt: 0` is unreadable. |
| **`dt_applied` sibling flag** | The pre-flight's sharpest finding: on both real targets `dt=0` because the audio scaffolding is *unapplied at HEAD*, not because the silicon lacks it. `dt_applied: false` lets `compare()` treat that 0 as "not yet in tree" (→ `not_cross_checkable`) rather than a real disagreement (→ false `disagree`). |
| **`ambiguous` + `ambiguity_note`** | Eliza's `soundwire_master` is genuinely "1 or 2". A single integer would fabricate certainty. `ambiguous: true` lets WP-C emit an honest `not_cross_checkable` with the reason, never a false point-count. |
| **`catalog` declared now, always `null` pre-SWI** | Makes the post-SWI Track D upgrade purely additive (C.7) — no second schema bump when `catalog_count` arrives. Renders as "Unavailable (pre-SWI)" exactly as the approved WP-C scope requires. |
| **Not in `required`** | A pre-1.3.0 (or a run where the model omits it) still validates — the core backward-compat guarantee. |

### A.5 Relationship to existing fields (no overlap, no duplication)

`element_counts` **does not replace or restate** `codecs[]`/`amplifiers[]`/`mics[]`/`speakers[]` (which stay the authoritative *identity/role* records) or `soundwire.master_count` (which stays as-is). It is a **separate, count-only projection** — the same way `schematic_nets` is a separate projection of pin data that also appears in prose. `soundwire.master_count` and `element_counts[soundwire_master].proposal` may coexist; if they ever disagree, that is itself a signal WP-C can surface. No existing consumer reads `element_counts`, so nothing downstream changes.

---

## Part B — Backward Compatibility Analysis

**Claim: fully additive and backward compatible. A 1.2.0-shaped response validates unchanged under 1.3.0, and every current consumer is unaffected.**

| Compatibility axis | Analysis | Result |
|---|---|---|
| **JSON-schema validation** (`client.py:582` `jsonschema.validate`) | `element_counts` is optional (not in `required`); `additionalProperties: True` already tolerates unknown keys. A response with **no** `element_counts` validates exactly as before. | ✅ pass |
| **Stored real data** (Nord + Eliza `qgenie_analysis.json`, both 1.2.0) | Neither has `element_counts`; both continue to validate under 1.3.0 unchanged. | ✅ pass |
| **Runner mapping** (`_build_audio_topology`, runner:496-505) | Builds `audio_topology` from an explicit key allow-list. Absent a new line, `element_counts` is simply not copied — zero behavior change until we *choose* to thread it (one additive line, Part C). | ✅ inert until wired |
| **Confidence Ledger** (`ledger.py`, WP-B) | `build_ledger` reads only the keys in `FIELD_DOMAIN_MAP`; `element_counts` is not among them. `FIELD_DOMAIN_EXCLUDED` would gain `element_counts` (a one-line drift-guard update) so the coverage test stays exhaustive. **No ledger status/band logic changes.** | ✅ pass (1-line test-guard update) |
| **Report renderer** (`main.py`) | Renders fixed sections; no section reads `element_counts`. No new section is added by Fix A (that's WP-C). | ✅ no change |
| **`local_test.py` engine** | Emits the `ANALYSIS_SCHEMA` shape and stamps `ANALYSIS_SCHEMA_VERSION`. It may omit `element_counts` (optional) and still validate; the version string updates to 1.3.0 automatically. | ✅ pass |
| **Reasoning fingerprints / `--rerun`** | The version bump changes the fingerprint → surfaces as *expected* drift, the intended signal that the contract evolved. Not a silent change. | ✅ by design |
| **Promotion / onboarding decisions / gating** | None read the schema counts. Untouched. | ✅ no change |

**Failure modes considered:** (a) model emits `element_counts` with an unknown `element_class` → still schema-valid (free string); `cardinality_config` ignores unknown classes → no crash, logged as unmatched. (b) model emits a negative or non-integer count → `minimum: 0` + type union rejects it at validation, same defense-in-depth as every other numeric field. (c) model emits `element_counts: []` → valid, treated as "reported, nothing enumerated" — distinct from absent.

---

## Part C — Migration Strategy

**Principle: three independent, individually-shippable steps, each additive and reversible. Fix A is only steps 1–2; step 3 is WP-C and stays unbuilt.**

### Step 1 — Schema (this design, when approved)
- Add `_ELEMENT_COUNT_ITEM` + the `element_counts` property to `schemas.py`; bump `ANALYSIS_SCHEMA_VERSION` to `1.3.0`.
- Add `"element_counts"` to `ledger.py`'s `FIELD_DOMAIN_EXCLUDED` (drift-guard only).
- **Reversible:** delete the property + revert the version string.

### Step 2 — Prompt + producers (Part F)
- Extend `build_prompt` to instruct the model to fill `element_counts` (Part F gives exact wording).
- Optionally thread it into `audio_topology` for inspectability by adding one line to `_build_audio_topology`:
  ```python
  if analysis.get("element_counts"):
      topology["element_counts"] = analysis["element_counts"]
  ```
  (Exactly the pattern used for `ipcat_findings`/`pin_crosschecks`.) This is optional for Fix A — WP-C's `collect_counts` can read the raw `analysis` envelope directly at runner time, where `element_counts` already lives.
- **Re-run** onboarding for Nord + Eliza so real counts populate. *(Re-running is a normal onboarding operation; it regenerates `case.generated.py`/`qgenie_analysis.json` — it does NOT promote anything.)*
- **Reversible:** revert the prompt string; old runs remain valid.

### Step 3 — WP-C (OUT OF SCOPE; do not build now)
- `cardinality_config.py` + `cardinality.py` consume `element_counts`. Gated on step 2 producing real integers on both targets. Not part of Fix A.

**Migration ordering guarantee:** steps 1 and 2 change *what the model may return* and *what we ask for* — they never change what any existing code *does* with a response. An un-migrated stored run (no `element_counts`) and a migrated run (with it) both flow through the current pipeline identically until WP-C exists to read the new field.

---

## Part D — Nord Examples (from real `targets/nord-iq10` data)

Nord is a **discrete-I2S, no-SoundWire** target; entire audio stack unapplied at HEAD `66b80186`. Reconstructing what the model *should* emit from the facts already in its prose output:

```jsonc
"element_counts": [
  {
    "element_class": "soundwire_master",
    "dt": 0, "evidence": 0, "proposal": 0, "catalog": null,
    "ambiguous": false,
    "dt_applied": false,
    "citations": [
      "nord-iq10.dtsi (grep at HEAD 66b80186: no soundwire-controller/SWR node)",
      "0004-...enable-audio-codecs...patch (codecs via I2S/TDM, not SoundWire)"
    ]
  },
  {
    "element_class": "dai_link",
    "dt": 0, "evidence": 1, "proposal": 1, "catalog": null,
    "ambiguous": false, "dt_applied": false,
    "ambiguity_note": "single I2S8/QUATERNARY_TDM dai-link drafted; port macro is a placeholder",
    "citations": [
      "0004-...patch (sound{} card, dai-link via q6apmbedai QUATERNARY_TDM_RX_0/TX_0)",
      "missing_evidence: I2S8 logical-port macro is an explicit placeholder"
    ]
  },
  {
    "element_class": "audioreach_port",
    "dt": 0, "evidence": null, "proposal": 1, "catalog": null,
    "ambiguous": true, "dt_applied": false,
    "ambiguity_note": "q6dsp-lpass-ports.h defines only PRIMARY..QUINARY; no literal I2S8 macro — mapping unconfirmed",
    "citations": ["missing_evidence[5]", "0004-...patch"]
  },
  {
    "element_class": "dsp_subsystem_instance",
    "dt": 0, "evidence": 1, "proposal": 1, "catalog": null,
    "ambiguous": false, "dt_applied": false,
    "citations": [
      "0003-...add-ADSP-remoteproc...patch (remoteproc_adsp, unapplied)",
      "CAVEAT: none of this exists at HEAD 66b80186 (verified via grep)"
    ]
  }
]
```
- **`dmic_line`, `amplifier`, `speaker`, `lpass_macro_instance`:** correctly **omitted** (Nord has no DMIC array, no amps/speakers — `amplifiers/mics/speakers` are all `[]`; no LPASS macro nodes). Omission = "no such element on this target," distinct from a zero count.
- **What WP-C would later say:** every Nord row is `dt_applied:false` + single-lane → `not_cross_checkable` (honest: "proposed but not yet in tree"). **No false `disagree`.** This is the correct, non-misleading outcome the pre-flight demanded.

---

## Part E — Eliza Examples (from real `targets/eliza` data)

Eliza is the **SoundWire** target — the case WP-C most exists for, and the one where list-length lied (mics list=2 but 8 DMICs; amps list=1 but 2 WSA). `element_counts` fixes exactly that:

```jsonc
"element_counts": [
  {
    "element_class": "soundwire_master",
    "dt": 0, "evidence": null, "proposal": 1, "catalog": null,
    "ambiguous": true,
    "dt_applied": false,
    "ambiguity_note": "could be 1 or 2 physical masters: one SWR_RX/TX to WCD9378 + a 'dedicated' SWR0 to WSA amps; not resolved without catalog enumeration",
    "citations": [
      "soundwire.master_count=1 (typed, low-confidence 0.55)",
      "missing_evidence: 'could be 1 or 2 physical master instances; not resolved'",
      "eliza.dtsi (no qcom,soundwire-vX.Y.Z node present — cannot confirm from DT)"
    ]
  },
  {
    "element_class": "dmic_line",
    "dt": 0, "evidence": 8, "proposal": 8, "catalog": null,
    "ambiguous": false, "dt_applied": false,
    "citations": [
      "LD20-93542-1 p3 ('DMIC X 8' block); p4 (DMIC01/23/45/67_CLK,DATA = 4 pairs = 8)",
      "ipcat LPASS_13.3.x_HPG ('up to 8 DMICs')",
      "buses[]: 'DMIC PDM bus — 4 stereo pairs = 8 DMICs'"
    ]
  },
  {
    "element_class": "amplifier",
    "dt": 0, "evidence": 2, "proposal": 2, "catalog": null,
    "ambiguous": false, "dt_applied": false,
    "ambiguity_note": "one amplifiers[] row of part WSA8845, but two physical instances (Speaker 0 / Speaker 1)",
    "citations": [
      "LD20-93542-1 p3 (two amp instances labeled WSA8845 driving Speaker 0 / Speaker 1)",
      "wsa884x.c:2165 (driver present)"
    ]
  },
  {
    "element_class": "speaker",
    "dt": 0, "evidence": 2, "proposal": 2, "catalog": null,
    "ambiguous": false, "dt_applied": false,
    "citations": ["speakers[] = Speaker 0 (WSA8845 #1), Speaker 1 (WSA8845 #2)"]
  }
]
```
- **Key win #1 (`amplifier` 2, not 1):** `evidence`/`proposal` both = **2**, capturing the true instance count that `len(amplifiers[]) == 1` hid. WP-C compares 2-vs-2 → honest **`agree`** (not a false `disagree`).
- **Key win #2 (`dmic_line` 8, not 2):** both lanes = **8**, not the misleading `len(mics[]) == 2`. → `agree`.
- **Key win #3 (`soundwire_master` ambiguous):** `ambiguous:true` + note → WP-C emits **`not_cross_checkable`** with the "1 or 2" reason, never a fabricated `1`. This is precisely the SoundWire ambiguity the SWI catalog (post-Track D) is meant to resolve; pre-SWI, `element_counts` makes the *uncertainty itself* machine-readable.

**Future element classes (spec C.8, demonstrated):** a new class — e.g. `slimbus_device` (Eliza's `buses[]` mentions WCN675x/Moselle BT via SLIMbus) — needs **only a new `cardinality_config.py` row** (matcher + which lanes apply). The model emits another `element_counts` entry with `element_class: "slimbus_device"`; **no schema change, no code change in `cardinality.py` core** (C.8 guarantee). Same for `lpass_macro_instance` once Eliza's WSA/VA/RX/TX macro nodes are applied.

---

## Part F — Prompt Changes Required for QGenie

The counts already exist in the model's prose output; this is a **formatting instruction**, not new analysis. Add one paragraph to `build_prompt` (`client.py:369`), styled like the existing `ipcat_findings` self-report instruction:

> "Also populate `element_counts`: for each enumerable audio element class you can identify (SoundWire masters, DMIC lines, amplifiers, speakers, DAI links, AudioReach ports, DSP subsystem instances, LPASS macro instances), report the **number of physical instances** as typed integers per source lane — `dt` (instances actually present in the applied kernel DT at the pinned HEAD), `evidence` (from schematic/offline evidence), `proposal` (what your proposed case wires). Report the true instance count, not the number of distinct part numbers — e.g. two WSA8845 amplifiers driving two speakers is `amplifier: {proposal: 2}` even though it is one part number, and eight DMICs is `dmic_line: {evidence: 8}`. Set a lane to `null` if you did not consult it; set `0` only when you affirmatively determined there are none. If the audio scaffolding is not yet applied to the kernel tree, set `dt: 0` **and** `dt_applied: false`. If a count cannot be resolved to a single integer, set `ambiguous: true` and explain in `ambiguity_note` rather than guessing. Leave `catalog` null (it comes from a source not available this session). Cite every count."

**Notes:**
- Emphasize **instance count ≠ part-number count** — this is the single behavior that fixes the list-length bug; without it the model may echo `len(list)`.
- Emphasize the `dt_applied` flag — the model already reports "unapplied at HEAD" in prose, so this just asks it to also set the boolean.
- The instruction is target-agnostic (names element *classes*, never Nord/Eliza specifics).
- No change to `_add_dirs`, the MCP guidance, or any other prompt machinery.

---

## Part G — Testing Strategy

All tests are pure-function / fixture-based, matching the existing `tests/test_*` harness. **No live QGenie call needed.**

1. **Schema backward-compat test** (extend `tests/test_reasoning_*` or a new `test_element_counts_schema.py`):
   - A stored 1.2.0 response (no `element_counts`) validates under 1.3.0. ✅ core guarantee.
   - A response with a well-formed `element_counts` validates.
   - Negative count / non-integer lane / missing `element_class` → validation *fails* (defense-in-depth).
   - `element_counts: []` and lane `null` both validate.
2. **Real-data fixture test:** load the *actual* Nord + Eliza `qgenie_analysis.json`, confirm they still validate under 1.3.0 unchanged (regression against the migration).
3. **Ledger non-interference test** (extend `test_confidence_ledger.py`): a `gc` carrying `element_counts` produces byte-identical ledger rows to one without it (proves WP-B untouched) + `FIELD_DOMAIN_EXCLUDED` coverage test still exhaustive.
4. **Version-drift test:** `ANALYSIS_SCHEMA_VERSION == "1.3.0"`; fingerprint changes vs 1.2.0 (expected drift, asserted).
5. **Producer-shape test (`local_test.py`):** the local engine's output still validates (it may omit `element_counts`).
6. **Determinism:** schema validation is deterministic; assert repeated validation is stable (trivial but keeps the suite's determinism discipline).
7. **Full suite:** all existing modules remain green (the whole point of additive).

**Explicitly deferred to WP-C (not tested here):** `collect_counts`/`compare` logic, verdict truth tables, the rendered cardinality section — none exist yet.

---

## Part H — Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Model still echoes `len(list)` instead of true instance count** despite the prompt | **High** (defeats the whole fix) | Prompt explicitly contrasts part-count vs instance-count with the WSA8845 (2 instances, 1 part) example; step-2 re-run is *validated* against Part D/E expected values before declaring success — if Eliza `amplifier.proposal != 2`, the prompt is iterated, not WP-C started. |
| 2 | **Model fabricates a point count for a genuinely ambiguous class** (Eliza masters) | Medium | `ambiguous`/`ambiguity_note` give it a sanctioned "I can't tell" channel; prompt says "rather than guessing." WP-C treats `ambiguous:true` as `not_cross_checkable` regardless of the integer, so a bad guess can't become a false verdict. |
| 3 | **`dt=0` misread as real disagreement** (unapplied ≠ absent) | Medium | `dt_applied:false` sibling flag; WP-C's `compare()` (later) must gate on it. Documented as a hard requirement for step 3. |
| 4 | **Element-class vocabulary drift** — model invents class names not in C.1 | Low | Free-string in schema, validated in `cardinality_config`; unknown classes ignored + logged, never crash. Config is the single source of the class list (C.8). |
| 5 | **`soundwire.master_count` vs `element_counts[soundwire_master].proposal` divergence** | Low | Intentional: both allowed to coexist; a divergence is itself a WP-C signal, not a bug. No consumer requires them equal. |
| 6 | **Re-running onboarding changes other fields** (analysis is model-driven, not fully deterministic) | Medium | Re-run is already a supported operation; diff the new `case.generated.py` against the stored one and confirm only additive/expected changes (same discipline as prior re-runs #16/#17). Nothing is promoted. |
| 7 | **Scope creep toward WP-C** | Low (process) | This document + approval gate explicitly stop at steps 1–2; `cardinality.py` is not written until real counts are validated on both targets. |
| 8 | **`catalog` field invites premature Track D work** | Low | Declared null-only with a comment; no producer fills it; renders "Unavailable (pre-SWI)". Purely a future-additivity hook. |

---

## Summary & Recommendation

- `element_counts` is a **minimal, additive, backward-compatible, target-agnostic** extension (1.2.0 → 1.3.0) that gives the instance counts — which the model already knows and states in prose — a **typed, cited, ambiguity-aware** home, with an explicit `dt_applied` flag that resolves the pre-flight's sharpest failure (unapplied ≠ absent).
- Demonstrated on **real** Nord (discrete/no-SWR → clean omissions + honest `not_cross_checkable`) and **real** Eliza (`amplifier:2` and `dmic_line:8` fix the list-length lie; `soundwire_master` ambiguous stays honest).
- **Recommended sequence:** approve schema step 1 → apply prompt step 2 → **re-run Nord+Eliza and validate the counts against Part D/E** → only then authorize WP-C (step 3). The re-run validation is the gate: if the model doesn't emit true instance counts, iterate the prompt before any WP-C code.
- **Not implemented. No code/schema modified. Nothing committed.** Awaiting approval to proceed to implementation of steps 1–2 (still a separate, explicitly-authorized action).

---

**Evidence:** `orchestrator/reasoning/schemas.py` (ANALYSIS_SCHEMA v1.2.0, additive-bump precedent); `orchestrator/reasoning/client.py:369` `build_prompt`; `orchestrator/runners/target_onboarding_runner.py:487` `_build_audio_topology`; live `targets/{nord-iq10,eliza}/qgenie_analysis.json` + `case.generated.py`; `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` C.1–C.9; `docs/WP_C_PREFLIGHT_GAP_ANALYSIS.md`. Nord/Eliza used strictly as validation examples; no target-specific logic introduced into the schema.
