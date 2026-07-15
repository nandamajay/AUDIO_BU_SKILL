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

## T5 donor rule needs target-family carve-out for lemans-family parts

**Observed:** Phase-2A KB rule t5.donor.firmware.sa8775p in
crossverify_config.py catches any DTS reference to sa8775p firmware
(qcom/sa8775p/*.mbn) as donor residue.

**Correct on Eliza:** Eliza is not a lemans-family part; qcom/sa8775p/adsp.mbn
there is genuine donor residue and should route to
GeneratorSkipped(reason=gating_row_partial_match_donor_residue).

**Incorrect on Nord:** Nord IQ-10 (SA8797P) is a lemans-family part that
legitimately shares the SA8775P ADSP firmware image
(qcom/sa8775p/adsp.mbn). Nord's compatible is qcom,sa8775p-adsp-pas
because the ADSP PAS driver only supports that string. Verified against:
- linux-nord/0003-patch:74 (Nord's own remoteproc node uses this)
- Phase-1C phase1c_live.json (citation confirms sa8775p usage on Nord)
- pinctrl-nord.c mux table

**Root cause:** The KB rule uses a family-agnostic substring match. It
needs a target-family exemption list to distinguish "donor residue on a
non-lemans-family target" (Eliza case) from "legitimate lemans-family
firmware sharing" (Nord case).

**Detected by:** WP3.1 fixture-refresh session, when the reviewer's
initial prompt conflated the two cases and specified sa8797p firmware
values that don't actually exist on Nord.

**Fix (Phase-2A follow-up):** Extend T5_DONOR_RULES entries with an
optional exempt_families field. The rule dict would grow a new key
exempt_families set to a tuple like ("sa8775p", "sa8797p") naming the
lemans-family SoCs that legitimately share the SA8775P ADSP image. The
T5 evaluator then skips the rule when the resolved chip family is in
the exemption list. For Eliza (sm7750), rule still fires; for Nord
(sa8797p), rule silently passes.

**Impact on WP3.1:** WP3.1 lands with ground-truth Nord values (which
carry sa8775p references). WP3's test_wp2_fixture_hits_donor_residue
test still passes because that test uses the WP2 fixture, which is
projected from Phase-2A expected_rows.json and doesn't have
target-family context. Once the exemption lands, Nord's real Phase-2A
row for T5.dts.firmware becomes MATCH (not PARTIAL_MATCH), and the WP2
fixture would need regeneration to reflect the corrected verdict.

**Priority:** Should-fix before Phase-2B ships end-to-end. Not blocking
WP3.1 (which uses synthetic clean-Nord facts), WP4 (independent lane),
or WP5-WP6 (also independent).

**Cross-references:**
- PHASE2A_KB_FOLLOWUPS.md — this file
- WP3.1 commit 7c13809 (references this follow-up in trailer)
- crossverify_config.py::T5_DONOR_RULES
