# WP G-3B-beta — CodecPreviewEngine (Pipeline 2, preview-only)

**Status:** DRAFT (draft-before-code per standing directive).
**Depends on:** G-3A.9 (committed at `389f00e`), G-3B-alpha (task #60, deleted — direction changed to C).
**Blocks:** none. Landing WP: `codegen` disk-write gate (#3), CLI wire-in (`--generate-codegen`), OEM-doc reader (WP-SRC-C).
**Direction ruling (this session):** user approved **G-3B-beta (C)**. Pipeline 2 codec lane, preview-only, no CLI wire-in, no disk write. Contributes_rows stay reviewer-attached disclosures — NOT auto-promoted to T5. **Fresh authoritative evidence is required** before any new cross-verification PASS is recorded.

Confidence tags apply per-claim: [Certain] = grep-proven or executed; [Likely] = design projection; [Guessing] = not yet grounded.

---

## 0. Provenance guard (non-negotiable, inherited from prior session)

The candidate patch `5267b2e1` is codec-source *material*, NOT verification authority. Any CodecPreviewEngine output MUST inherit provenance labels from the envelope:

- If `input_envelope["codec_source_path"]` is populated → the emitted preview carries `provenance.candidate_derived = True` and `provenance.independently_verified = False`.
- If T4a MATCH is same-source per [[wp-b-wp-a-implemented]] / G-3A.11 → the preview labels T4a-derived facts as `same-source presence signal, NOT cross-verified`.
- The preview MUST NOT emit any row-shaped payload that could be indexed by cross-verification as a new PASS/MATCH.

Violation of this guard = WP failure. Regression test asserts labels are present.

---

## 1. Scope (what lands, what does NOT)

**Lands:**
1. `orchestrator/codegen/codec_preview_engine.py` — a new `CodecPreviewEngine(CodegenEngine)` class registered in `_ENGINES` alongside `NullEngine`.
2. Engine `generate(task_spec) → ChangeSet` that returns:
   - Exactly one `Change(path="sound/soc/codecs/<target>-preview.c", change_type="create", ...)` per codec identified in `target_profile["codecs"]`.
   - `unified_diff = ""` (Phase-2 foundation contract, see `models.py:36`) — the *body preview* rides in `rationale` OR a new sibling field (§3 decides).
   - `needs_review` populated with provenance-tagged disclosure lines (from the T4b advisory-open pattern).
3. `codec_generation_runner.py` unchanged in signature but now accepts `engine_id="codec_preview"` explicitly.
4. Tests: `tests/test_codec_preview_engine.py` — 8+ tests covering guard, disclosure-only, envelope-driven codec list, provenance labels, empty-envelope skip.

**Does NOT land in this WP:**
- No CLI wire-in. `--generate` continues to invoke Pipeline 1 only (`main.py:555-571`). No new flag.
- No disk write. `ChangeSet` stays in-memory; consumer is the test suite + a follow-up WP.
- No feedback into `cross_verification.rows`.
- No mutation of `is_open()` at `model.py:213-237`, `_GATING_OPEN_VERDICTS` at `model.py:46`, or `_rows_with_prefix` at `codec_stub.py:383-393`.
- No cross-pipeline coupling. Pipeline 1's `codec_stub.py` is not imported, referenced, or diffed.

---

## 2. Envelope contract [Certain, grep-verified against real Nord profile.json]

Grep of `audio_bu_skill/targets/nord-iq10/profile.json` (produced by real Nord run 36):

| Key | Type | Sample value (Nord IQ-10) |
|-----|------|---------------------------|
| `target_name` | str | `"nord-iq10"` |
| `codec_source` | str \| null | `"/tmp/g3a9-candidate/iq10-evk.dts"` |
| `codecs` | list[str] | `["adi,adau1979", "ti,pcm1681"]` |
| `soc` | (nested) | present |
| `soundwire`, `audio_stack`, `power_model`, `amplifiers` | (nested) | present |
| `cites` | dict | keys: `soc`, `power_model`, `soundwire` |
| `qgenie_analysis` | dict | present |

**No `_reasoning` top-level key on this profile.** The `_reasoning.codec_source` anchor documented in G-3A.9 is a *test-harness* anchor, not a runtime profile anchor. Runtime profile uses `target_profile["codec_source"]` (top-level). [Certain — grep-verified, retracts any prior claim that `_reasoning.codec_source` is runtime state.]

**Task_spec contract** (input to `CodecPreviewEngine.generate`), extending the shape already assembled at `codec_generation_runner.py:31-36`:

```python
task_spec = {
    "skill_id": "codec_generation",
    "target": target_name,
    "run_id": run_id,
    "target_profile": target_profile,   # existing
    # NEW (this WP):
    "provenance": {
        "codec_source_path": target_profile.get("codec_source"),
        "candidate_derived": bool(target_profile.get("codec_source")),
        "independently_verified": False,   # always False in this WP
        "same_source_t4a": True,            # G-3A.11 caveat, always True until authority integration
    },
}
```

The runner wires `provenance` from `target_profile["codec_source"]` — no new envelope key required, no case.py schema change.

---

## 3. Engine contract [Likely — depends on §3 field choice]

`CodecPreviewEngine.generate(task_spec: dict) → ChangeSet`:

1. Read `target_profile["codecs"]` (list of `"vendor,part"` compatible strings). Empty → return `ChangeSet(changes=[], summary="no codecs in profile — preview skipped")`.
2. For each codec compatible string:
   - Parse `vendor,part` → `("adi", "adau1979")`.
   - Emit `Change(path=f"sound/soc/codecs/{part}-preview.c", change_type="create", skill_id="codec_generation", unified_diff="", rationale=<preview body>, needs_review=[<disclosure lines>])`.
3. **Preview body location — DECISION POINT:**
   - **Option R (Rationale):** Preview text goes in `Change.rationale`. Pros: fits existing model, no schema change. Cons: `rationale` is single-line-ish semantically; multi-line preview text is awkward.
   - **Option F (New field):** Add `preview_bytes: str = ""` to `Change`. Pros: clean separation. Cons: schema change touches `models.py`, `to_dict()`, tests.
   - **[Recommendation, Likely]**: Option R for this WP. `rationale` already stores multi-line text in practice (nothing enforces single-line). Defer new field to a follow-up.
4. `needs_review` MUST include (deterministic sort order):
   - `"PROVENANCE: codec source is candidate-derived from {codec_source_path}, NOT independently verified"`
   - `"PROVENANCE: T4a QUP MATCH is same-source (IPCAT-vs-IPCAT); NOT cross-verified per G-3A.11"`
   - `"REVIEWER: confirm reset-gpios pin against schematic"`
   - `"REVIEWER: confirm MCLK feed (LPASS vs. crystal) against schematic"`
   - `"REVIEWER: confirm codec-domain output-enable line against schematic"`
5. `ChangeSet.summary`: `"codec preview: {N} codec(s), provenance-labeled, disclosure-only"`.

---

## 4. Disclosure-only invariant [Certain, this WP's core contract]

**Rule:** `Change.needs_review` entries and `Change.rationale` preview body are REVIEWER DISCLOSURES. They are NOT to be:
- Written to `cross_verification.rows`.
- Fed into `is_open()` decisions.
- Consumed by `contributes_rows` in Pipeline 1 artifacts.
- Elevated to any verdict tier stronger than `NOT_CROSS_CHECKABLE`.

**Enforcement:**
1. Engine returns a `ChangeSet` — a purely additive dataclass with NO cross-verification API surface. There is no code path from `ChangeSet` to `cross_verification.rows` in the current tree — this WP does not add one.
2. Test: `test_codec_preview_disclosures_are_not_rows` — grep the returned `ChangeSet.to_dict()` for any key resembling `verdict`, `is_open`, `track`, `subject`, `MATCH`, `PARTIAL_MATCH`. All MUST be absent.
3. Test: `test_codec_preview_does_not_touch_pipeline_1` — assert that after running `CodecPreviewEngine.generate(...)`, `_rows_with_prefix`, `is_open`, and `_GATING_OPEN_VERDICTS` are byte-identical to their pre-run state (import-and-hash check).
4. Test: `test_codec_preview_requires_fresh_evidence_for_pass` — attempt to construct a scenario where the engine would emit a MATCH-shaped payload. Assert the engine refuses / does not have that code path.

---

## 5. Test plan [Certain]

New file: `audio_bu_skill/tests/test_codec_preview_engine.py`. Tests recorded as files under `tests/` per standing preference.

1. `test_null_engine_still_default` — `resolve_engine()` with no args still returns `NullEngine`; `resolve_engine("codec_preview")` returns `CodecPreviewEngine`.
2. `test_empty_codecs_returns_empty_changeset` — profile with `codecs=[]` → `ChangeSet.is_empty() is True`, summary names the skip reason.
3. `test_two_codec_profile_emits_two_changes` — real-Nord profile shape → 2 `Change` entries, paths sorted deterministically.
4. `test_change_path_shape` — path is `sound/soc/codecs/{part}-preview.c`, `change_type == "create"`, `skill_id == "codec_generation"`.
5. `test_provenance_labels_present` — both provenance lines appear in every `Change.needs_review`, verbatim.
6. `test_reviewer_disclosures_deterministic_order` — same input → byte-identical `to_dict()`. Two calls compared.
7. `test_provenance_absent_when_no_codec_source` — profile with `codec_source=None` → provenance line for candidate-derived is REPLACED with `"PROVENANCE: no codec source path provided"` (not silently dropped).
8. `test_disclosures_are_not_rows` — assert `ChangeSet.to_dict()` contains no key matching `{verdict, is_open, track, subject, MATCH, PARTIAL_MATCH, NCC, cross_verify}`.
9. `test_pipeline_1_untouched` — hash `codec_stub.py`, `model.py`, run engine, re-hash. Byte-identical. (regression against accidental import-side-effect mutation.)
10. `test_engine_never_writes_disk` — patch `open`/`Path.write_text`/`Path.write_bytes` → engine call → no write attempts.

**Regression suite:** the existing 188 test count under Phase 2 foundation ([[phase2-foundation-uncommitted]]) must remain green. Target: 198+ tests, 0 failures. Full sweep required before proposing commit.

---

## 6. Files touched [Certain, minimal footprint]

| File | Action | Delta |
|------|--------|-------|
| `orchestrator/codegen/codec_preview_engine.py` | NEW | ~150 lines |
| `orchestrator/codegen/engine.py` | MODIFY | `_ENGINES` gets `codec_preview` entry; ~3 lines |
| `orchestrator/runners/codec_generation_runner.py` | MODIFY | inject `provenance` dict into task_spec; ~10 lines |
| `tests/test_codec_preview_engine.py` | NEW | ~300 lines, 10 tests |
| `docs/WP_G-3B-beta_DESIGN.md` | NEW (this file) | ~200 lines |

**NOT touched:**
- `orchestrator/generation/*.py` (Pipeline 1) — untouched.
- `orchestrator/main.py` — no CLI change.
- `orchestrator/codegen/models.py` — no schema change (Option R).
- `case.py` files — no case-schema change.

Commit target: 5 files (4 source/test + 1 doc), single commit, signoff line per standing directive.

---

## 7. Explicit non-goals (guard against scope-creep) [Certain]

1. No CLI mode. `--generate-codegen` is a future WP, not this one.
2. No disk write. `write_change_set(...)` is a future WP (Phase-2 gate #3).
3. No CLI-driven engine selection. Runner still defaults to `"null"`; `codec_preview` is only reachable via test or explicit envelope override.
4. No `machine_driver_preview`, `dt_scaffolding_preview`, `audioreach_preview`. This WP is codec-only (one lane, per G-3A.9 acceptance criteria).
5. No absorption of `_NORD_CODECS` (Pipeline 1's hard-coded lookup at `codec_stub.py:161-164`) into the preview engine — Pipeline 1 stays authoritative for the Nord path; Pipeline 2 reads the profile.
6. No OEM-doc reader integration (WP-SRC-C is a separate future WP, task #50).

---

## 8. Rollback [Certain]

Single commit → single revert. No schema migration. No case.py touch. `resolve_engine("null")` continues to work.

---

## 9. Acceptance criteria [Certain]

Before proposing commit:

- [ ] All 10 new tests pass.
- [ ] Full test sweep green (198+ tests, 0 failures).
- [ ] `grep -n "codec_preview" audio_bu_skill/orchestrator/main.py` returns nothing (no CLI wire-in leaked).
- [ ] `grep -rn "cross_verification" audio_bu_skill/orchestrator/codegen/codec_preview_engine.py` returns nothing.
- [ ] `grep -rn "is_open\|_rows_with_prefix\|_GATING_OPEN_VERDICTS" audio_bu_skill/orchestrator/codegen/codec_preview_engine.py` returns nothing.
- [ ] Real-Nord scorecard from run 36 unchanged when run without `codec_preview` engine (Pipeline 1 unaffected, byte-identical `skill_outputs.json`).
- [ ] Provenance labels present in every Change's `needs_review` (grep-verifiable).
- [ ] WP doc reviewed and approved before code lands.

---

## 10. Open questions for user before implementation

**Q1.** Preview body location — Option R (`rationale` string) or Option F (new `preview_bytes` field on `Change`)? **[Recommendation: R]**

**Q2.** Should `Change.path` mirror the upstream kernel layout (`sound/soc/codecs/adau1979-preview.c`) even though nothing writes there yet? **[Recommendation: Yes — future disk-write WP inherits the convention.]**

**Q3.** Is `"codec_preview"` the right engine_id, or `"codec_preview_v1"`/`"codec_generation.preview"`? **[Recommendation: `"codec_preview"` — flat, matches existing `"null"`/`"claude_code"`/`"qgenie"` style.]**

**Q4.** Should this WP add a `Change.provenance: dict` field for structured (not string) provenance, or keep provenance as strings in `needs_review`? Structured is more testable but is a schema change. **[Recommendation: strings this WP; structured is a follow-up.]**

---

**End of draft.** No code changes yet. Awaiting user ruling on Q1–Q4 (or blanket approval of recommendations) before implementing.
