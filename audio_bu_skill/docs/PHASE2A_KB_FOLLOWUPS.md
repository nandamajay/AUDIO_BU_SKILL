# Phase-2A KB Follow-ups

Non-blocking KB coverage gaps observed during live production runs.
None of these are defects; each is a KB-coverage improvement that
requires research rather than a code fix.

## SM7750 (Eliza) missing from T5_TARGET_IDENTITY

**Observed:** Eliza's onboarding report renders
`T5 silicon_identity NOT_CROSS_CHECKABLE (authority_unavailable)`
while Nord renders `T5 dts.revision_anchor NOT_CROSS_CHECKABLE
(revision_not_pinned)`.

**Root cause:** `crossverify_config.py::T5_TARGET_IDENTITY` has a
canonical family entry for `sa8797p` (Nord) but not `sm7750` (Eliza).
The T5 family-mapper `_t5_normalize_family` cannot resolve
`SM7750 (Eliza)` to a known family, so T5 falls through to the
authority-unavailable branch and skips donor-rule evaluation.

**Not a defect:** the engine is honestly reporting a KB coverage gap.
Fabricating a family assignment would violate the "no fabricated
values" invariant.

**Fix (research task):** add an `sm7750` block to `T5_TARGET_IDENTITY`
with citations to upstream Qualcomm bindings for:
- expected compatible prefixes (qcom,sm7750-*)
- expected firmware prefixes (qcom/sm7750/*.mbn)
- expected power-domain style (rpmhpd vs scmi, verify with SM7750 docs)

Once landed, Eliza T5 will emit the same row shape as Nord and donor-
rule evaluation becomes active for Eliza too.

**Impact on Phase-2B:** WP3 (DT scaffolding generator) currently sees
`T5 silicon_identity NCC(authority_unavailable)` for Eliza and will
emit `GeneratorSkipped(reason=authority_not_in_snapshot)` per gating
rules. That's the fail-closed default working as designed — no wrong
artifacts will be generated for Eliza until this KB gap closes.

**Priority:** deferred; not blocking any Phase-2B WP.
