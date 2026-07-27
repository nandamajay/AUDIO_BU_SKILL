# WP G-3B-gamma — dt_scaffolding lane: T5 positive attestation

**Status:** DRAFT (draft-before-code per standing directive).
**Depends on:** G-3B-beta (CodecPreviewEngine), phase-A-E audit (task #66).
**Blocks:** dt_scaffolding real-Nord PASS artifact; downstream dt_scaffolding runner integration.
**Approval:** user approved Option 2 (task #67) with six explicit constraints — recorded below verbatim in §0.

Confidence tags per-claim: [Certain] = grep-proven or executed; [Likely] = design projection; [Guessing] = not yet grounded.

---

## 0. User-approved constraints (verbatim, non-negotiable)

> 1. Preserve trust-chain behavior exactly as-is.
> 2. Do not weaken provenance requirements.
> 3. Do not introduce candidate-derived PASS conditions.
> 4. Do not modify AudioReach gating logic.
> 5. Fix only the dt_scaffolding registration/producer mismatch identified in the audit.
> 6. Add regression tests proving:
>    - expected rows exist
>    - generator opens when rows are emitted
>    - existing codec_stub behavior unchanged
>    - existing machine_driver behavior unchanged
>    - audioreach behavior unchanged

Additional standing invariants that apply here [Certain]:
- Provenance guard: authority for MATCH/PARTIAL_MATCH must be INDEPENDENT of candidate commit `5267b2e1`.
- Disclosure-only rule: EMIT `contributes_rows` are reviewer disclosures, not feedable to `cross_verification.rows`.
- `is_open()` at `generation/model.py:213-237`, `_GATING_OPEN_VERDICTS`, `_rows_with_prefix` at `codec_stub.py:383-393` — all NO-TOUCH.

---

## 1. Root cause (from Phase A-E audit) [Certain — grep-proven]

`orchestrator/generation/dt_scaffolding.py` gates on `T5.dts.firmware` and `T5.dts.compatible` (declared at line 150-165) expecting a POSITIVE attestation row. `track_t5()` at `crossverify.py:1314` emits these subjects **only** as `DISAGREE_WITH_AUTHORITY` when a donor rule matches (line 1378-1396, Path 1). On the clean real-Nord DTS (no donor leak) those subjects are absent from `cross_verification.rows`. `is_open()` returns False → generator skips with `authority_not_in_snapshot` → post-verify `skip_validity` FAIL.

Category mismatch: dt_scaffolding treats `T5.dts.firmware` as "authority attests firmware is well-formed"; track_t5 treats it as "donor leak on the firmware kind." The generator's expectation was never wired to a producer.

---

## 2. Fix — Option 2 (approved) [Certain]

Extend `track_t5` Path 1 (authority available) to emit a `MATCH` row per kind ∈ `{compatible, firmware}` when ALL of the following hold:

1. `chips_list_chips` yielded a canonical family token (Path 1 already gates on this) — the IPCAT-side authority anchor. [independent of `5267b2e1`]
2. No donor rule of that kind fired for the target family (mutually-exclusive per kind — if a donor `compatible` rule fired, no positive `compatible` MATCH).
3. `T5_TARGET_IDENTITY[target]` has the corresponding `expected_<kind>_prefix` entry.
4. The DTS text contains that expected prefix as a substring.

The MATCH row carries:
- `authority = {"strength": "IPCAT_DIRECT", "origin": "ipcat.chips_list_chips", "value": {"canonical_family": target, "chip_name": chip_name}}` — same authority object as the sibling DISAGREE branch.
- `confidence = "high"` — authority-backed on both sides (IPCAT attests family; DTS text attests kind prefix).
- `citations = ["chips_list_chips:<chip_name>", "kb.rule:<meta_id>"]` — new meta-rule ids added to `T5_META_RULES` (§4).
- `warning = False` — default for MATCH per `_WARNING_DEFAULT_TRUE` at `crossverify_model.py:81`.

**Why this satisfies constraint (1) (preserve trust-chain):**
- Existing DISAGREE_WITH_AUTHORITY rows on donor leak are UNCHANGED — same branch, same fields.
- Existing NCC(revision_not_pinned) is UNCHANGED — still emitted alongside.
- Existing case-(e) test at `test_crossverify_t5.py:240-253` `assert rows == []` NO LONGER HOLDS by design — the input to that test now legitimately emits 2 MATCH rows because it satisfies all four conditions. The test must be updated to assert the two MATCH rows AND absence of DISAGREE/NCC rows. That is the deliberate behavior change of this WP. [Certain — grep of test body]

**Why this satisfies constraint (3) (no candidate-derived PASS):**
- Condition (1) is IPCAT authority — not `5267b2e1`.
- Condition (4) is DTS text; on real Nord run 36 the DTS *text* comes from the profile's DTS-fragment field, which is CANDIDATE-DERIVED. **But the MATCH requires BOTH (1) AND (4).** The candidate DTS alone cannot open the gate — authority must also confirm the family. This is the same trust-chain contract as the existing DISAGREE branch (which also requires both authority-attested family AND DTS text pattern match). [Likely — mirror-argument with DISAGREE branch; needs verify test]

**Why this satisfies constraint (4) (no AudioReach change):**
- AudioReach gates are `T2.*` / `T4a.*`, not `T5.*`. `track_t5` output does not reach AudioReach gating logic. [Certain — grep-verifiable]

---

## 3. Files touched [Certain, minimal footprint]

| File | Action | Delta |
|------|--------|-------|
| `orchestrator/reasoning/crossverify.py` | MODIFY | insert positive-attestation branch in `track_t5` Path 1, after donor sweep, before revision-anchor emission; ~50 lines |
| `orchestrator/reasoning/crossverify_config.py` | MODIFY | add 2 new keys to `T5_META_RULES`; 2 lines |
| `tests/test_crossverify_t5_positive_attestation.py` | NEW | ~250 lines, 8 tests |
| `tests/test_dt_scaffolding_positive_gate.py` | NEW | ~120 lines, 3 tests |
| `tests/test_crossverify_t5.py` | MODIFY | update case-(e) test body to assert MATCH rows (deliberate behavior change) |
| `docs/WP_G-3B-gamma_DT_SCAFFOLDING_DESIGN.md` | NEW (this file) | ~200 lines |

**NOT touched:**
- `orchestrator/generation/dt_scaffolding.py` — the generator is CORRECT; the producer was wrong. [Certain]
- `orchestrator/generation/model.py`, `codec_stub.py`, `machine_driver.py`, `audioreach_topology.py`, `post_verify.py` — no-touch guarantees. Byte-identity asserted in test §6.
- `orchestrator/reasoning/crossverify_model.py` — no schema change.

---

## 4. `T5_META_RULES` additions [Certain]

```python
T5_META_RULES: dict[str, str] = {
    "silicon_identity":     "t5.meta.silicon.identity",
    "revision_not_pinned":  "t5.meta.revision.pin_required",
    # New in G-3B-gamma:
    "target_compatible_match": "t5.target.compatible.match",
    "target_firmware_match":   "t5.target.firmware.match",
}
```

Each MATCH row cites `kb.rule:t5.target.<kind>.match` alongside the `chips_list_chips:<chip_name>` IPCAT anchor.

---

## 5. Positive-attestation branch — pseudocode [Likely — draft implementation]

Inserted in `track_t5` after donor sweep (`crossverify.py:1396`), before revision-anchor block (`:1401`):

```python
# ── Positive SoC-family attestation ───────────────────────────────────
# One MATCH row per kind whose donor did NOT fire and whose target-identity
# prefix is present in the DTS.
# Requires BOTH: (a) IPCAT authority confirms target family (Path 1
# invariant), (b) DTS text contains the expected prefix for this kind.
# Trust chain: candidate DTS alone cannot open; authority anchor is IPCAT,
# not the candidate patch.
#
# SCOPE — non-negotiable:
#   * `dts.compatible` MATCH is a SoC-family attestation ONLY. It does NOT
#     authorize any board-level compatible (qcom,iq10-rrd, qcom,iq10-evk,
#     or any downstream board variant). Board-variant reconciliation is a
#     separate track (task #69).
#   * `dts.firmware` MATCH is a SoC-family firmware-path prefix attestation
#     ONLY. It does not authorize any specific firmware binary or a
#     board-specific firmware variant.
donor_kinds_fired = {rule["kind"] for rule, _ in _t5_matching_donor_rules(dts_text, target)}
target_identity = T5_TARGET_IDENTITY.get(target, {})
for kind, prefix_key, meta_key in (
    ("compatible", "expected_compatible_prefix", "target_compatible_match"),
    ("firmware",   "expected_firmware_prefix",   "target_firmware_match"),
):
    if kind in donor_kinds_fired:
        continue  # donor leak already emitted DISAGREE for this kind
    expected_prefix = target_identity.get(prefix_key)
    if not expected_prefix:
        continue  # no KB entry for this target/kind — remain silent
    if expected_prefix not in dts_text:
        continue  # DTS does not attest the kind — remain silent
    if kind == "compatible":
        notes = [
            f"target-family compatible prefix {expected_prefix!r} present "
            f"in DTS; IPCAT authority confirms family={target}",
            "SCOPE: SoC-family attestation only",
            "NOT_ATTESTED: board_variant",
            "MATCH does NOT authorize qcom,iq10-rrd, qcom,iq10-evk, or any "
            "board-level compatible string; board-variant reconciliation "
            "is a separate track",
        ]
    else:  # firmware
        notes = [
            f"target-family firmware prefix {expected_prefix!r} present "
            f"in DTS; IPCAT authority confirms family={target}",
            "SCOPE: SoC-family firmware-path prefix only",
            "MATCH does NOT authorize any specific firmware binary or "
            "board-specific firmware variant",
        ]
    rows.append(
        _t5_row(
            subject=f"dts.{kind}",
            verdict="MATCH",
            source={"dts_prefix_found": expected_prefix},
            authority=dict(authority_value),
            confidence="high",
            citations=_t5_citations(chip_name, _T5_META_RULES[meta_key]),
            review_actions=[],
            notes=notes,
        )
    )
```

**Note on citation key access:** `_T5_META_RULES` is the module-local import of `T5_META_RULES` — already imported at `crossverify.py:1073-1075`. [Certain — grep-verifiable]

**Row `notes` are load-bearing (Turn 3 tightened contract):**
Reviewers reading a MATCH row must see explicitly:
- `SCOPE:` — what the attestation covers (SoC-family only).
- `NOT_ATTESTED: board_variant` (compatible only) — the disclosure that this MATCH does not extend to board identity.
- Enumeration of board-level compatibles that a MATCH does NOT authorize.

Tests in §6 assert the presence of each line.

---

## 6. Test plan [Certain]

### 6.1. New file `tests/test_crossverify_t5_positive_attestation.py` (8 tests)

1. `test_positive_compatible_match_when_authority_and_prefix` — clean Nord DTS with `qcom,sa8797p-adsp-pas` + authority OK → `dts.compatible` MATCH row emitted.
2. `test_positive_firmware_match_when_authority_and_prefix` — clean Nord DTS with `sa8797p/adsp.mbn` + authority OK → `dts.firmware` MATCH row emitted.
3. `test_both_kinds_match_together` — real-Nord case (e) DTS text → both MATCH rows emitted.
4. `test_no_positive_match_when_donor_kind_fired` — DTS with BOTH sa8775p compatible AND sa8797p compatible → only DISAGREE emitted for `compatible`, no MATCH (mutual exclusivity per kind).
5. `test_no_positive_match_when_dts_missing_prefix` — DTS has neither `qcom,sa8797p-` nor `sa8797p/` → no MATCH rows (neither kind emitted).
6. `test_no_positive_match_when_authority_unavailable` — chips_list_chips unavailable, source-declared family sa8797p, DTS has sa8797p prefix → still no MATCH (Path 2 skips positive branch; authority strength is KB_RULE, not IPCAT_DIRECT, which is insufficient).
7. `test_match_row_citations_contain_ipcat_and_kb_rule` — cite check: MATCH row citations include `chips_list_chips:<chip_name>` AND `kb.rule:t5.target.<kind>.match`.
8. `test_match_row_warning_false_default` — MATCH row's `warning` flag is False (opens the gate per `is_open()` invariant).

### 6.2. New file `tests/test_dt_scaffolding_positive_gate.py` (3 tests)

1. `test_dt_scaffolding_opens_when_positive_rows_present` — build a `Facts` bundle with `T5.dts.firmware`=MATCH and `T5.dts.compatible`=MATCH → `is_open` returns True for both → generator emits non-skip artifact.
2. `test_dt_scaffolding_still_skips_when_rows_absent` — Facts bundle with no T5 rows → generator still skips `authority_not_in_snapshot` (regression: no accidental default-open).
3. `test_dt_scaffolding_still_skips_when_disagree_row_present` — Facts bundle with `T5.dts.firmware`=DISAGREE_WITH_AUTHORITY (warning=True) → gate closed → generator skips (regression: warning gate still functions).

### 6.3. Existing test update `tests/test_crossverify_t5.py`

Case (e) `test_valid_revision_pin_and_no_donor_is_empty` at line 240-253:
- Current: `assert rows == []`.
- Updated: `assert len(rows) == 2` and both are `MATCH`, subjects are `dts.compatible` and `dts.firmware`. Rename test to `test_valid_revision_pin_and_no_donor_emits_positive_matches`.
- Docstring updated to reflect the new expected behavior.

**Rationale:** case (e) was a snapshot of the OLD contract. Under the new contract, "fully cross-checkable" means the two positive attestation rows now exist. This is the deliberate behavior change of this WP; the test update is part of it, not a regression.

### 6.4. Regression checks — all MUST remain green [Certain]

- `test_crossverify_t5.py`: cases (a)/(b)/(c) DISAGREE tests unchanged, (f)/(g)/(h)/(i) unchanged. Cases (d) and (e) are both **deliberate behavior changes** — see §6.4.1.
- `test_generation_codec.py`, `test_generation_machine.py`, `test_generation_audioreach.py`, `test_generation_post_verify.py`, `test_generation_registry.py`, `test_generation_render.py`, `test_generation_runner.py`, `test_generation_dt.py` — full 188+ test sweep expected green.

#### 6.4.1. Case (d) is ALSO a deliberate behavior change [Certain]

Pre-G-3B-gamma, case (d) `test_no_donor_no_revision_pin_is_not_cross_checkable` asserted `len(rows) == 1` — a single NCC(revision_not_pinned) row. Its DTS input carries BOTH `qcom,sa8797p-adsp-pas` AND `sa8797p/adsp.mbn`, so under the new positive-attestation branch the same four conditions that fire for case (e) ALSO fire here — the two kinds have the target prefix, no donor fires, IPCAT authority is present.

The new revision-pin branch and the new positive-attestation branch are **orthogonal and additive**: absence of `qcom,board-id`/`qcom,msm-id` still emits NCC(revision_not_pinned), and presence of target-family prefixes still emits per-kind MATCH. Both fire on this input → 3 rows.

Rename to `test_no_donor_no_revision_pin_emits_positives_plus_ncc`; new assertion is `len(rows) == 3` with the same NCC invariants as before **plus** the compat/firmware MATCH invariants (IPCAT_DIRECT, warning=False, confidence=high, SCOPE line, compat carries `NOT_ATTESTED: board_variant`, firmware does not).

### 6.5. Byte-identity checks — no-touch guarantees

`tests/test_dt_scaffolding_positive_gate.py` includes a hash-check subtest asserting `orchestrator/generation/{dt_scaffolding.py, model.py, codec_stub.py, machine_driver.py, audioreach_topology.py, post_verify.py}` are byte-identical before and after running the new generator test (import-side-effect regression guard).

---

## 7. Acceptance criteria [Certain]

Before proposing commit:

- [ ] All 11 new tests pass (8 T5 + 3 dt_scaffolding).
- [ ] Updated case-(e) test passes with new assertion.
- [ ] Full test sweep green (no regressions in 188+ existing tests).
- [ ] `grep -n "5267b2e1\|candidate_derived" audio_bu_skill/orchestrator/reasoning/crossverify.py` returns no new hits (guard against candidate-derived PASS injection).
- [ ] Byte-identity of `orchestrator/generation/*.py` confirmed pre/post.
- [ ] Real-Nord run-N projection (below §8) reviewed.
- [ ] All 6 constraints from §0 have a mapped acceptance check.
- [ ] WP doc reviewed and approved before code lands (this file).
- [ ] **Turn-3 disclosure contract:** every `dts.compatible` MATCH row's `notes` includes each of: `SCOPE: SoC-family attestation only`, `NOT_ATTESTED: board_variant`, and the explicit non-authorization enumeration (`qcom,iq10-rrd`, `qcom,iq10-evk`, board-level compatibles). Every `dts.firmware` MATCH row's `notes` includes `SCOPE: SoC-family firmware-path prefix only` and the "does NOT authorize any specific firmware binary" disclosure. Asserted by `test_match_row_notes_carry_not_attested_disclosure` in `tests/test_crossverify_t5_positive_attestation.py`.

---

## 8. Run-36 → Run-N projected behavior change [Likely — projection, not yet executed]

**Run 36 (current, pre-fix):**
- `track_t5` on real Nord DTS → 0 rows (no donor leak, valid revision pin).
- `dt_scaffolding` gate check → `is_open("T5", "dts.firmware")` = False → skip with reason `authority_not_in_snapshot`.
- `post_verify.skip_validity` → FAIL for dt_scaffolding lane.
- Scorecard: dt_scaffolding = SKIP-INVALID.

**Run N (post-fix), same input:**
- `track_t5` on real Nord DTS → 2 rows: `T5.dts.compatible`=MATCH (high, IPCAT_DIRECT) + `T5.dts.firmware`=MATCH (high, IPCAT_DIRECT).
- `dt_scaffolding` gate check → `is_open("T5", "dts.firmware")` = True → generator runs.
- Artifact emitted with proper DT scaffolding.
- `post_verify.skip_validity` → N/A (not a skip).
- Scorecard: dt_scaffolding = EMITTED with T5 positive attestation citations.

**Lane scorecard delta (projected):**

| Lane | Run 36 | Run N |
|------|--------|-------|
| codec_stub | EMIT (unchanged) | EMIT (unchanged, byte-identical) |
| machine_driver | EMIT (unchanged) | EMIT (unchanged, byte-identical) |
| audioreach_topology | EMIT (unchanged) | EMIT (unchanged, byte-identical) |
| dt_scaffolding | **SKIP-INVALID** | **EMIT** |

Zero change to other three lanes. dt_scaffolding transitions from SKIP-INVALID → EMIT. This is the single observable behavior change.

**What does NOT change [Certain]:**
- Provenance labels on codec_stub outputs (still candidate-derived, T4a same-source).
- `is_open()` predicate logic.
- Any Pipeline 2 (`orchestrator/codegen/`) output.
- Any AudioReach or machine_driver gate.

---

## 9. Rollback [Certain]

Single commit → single revert. No schema migration. No file split. `T5_META_RULES` additions are additive; removing them removes the two new citation ids only. The positive branch is a pure addition to `track_t5` — revert takes the branch out; the DISAGREE/NCC branches are untouched.

---

## 10. Open questions

None. Constraints §0 answer the design questions; §5 pseudocode is the implementation. Proceeding with code after user reviews this design.

---

**End of draft.** Await approval, then implement in order: (1) config additions, (2) failing tests, (3) `track_t5` branch, (4) verify pass, (5) full sweep, (6) STOP for user review before commit.
