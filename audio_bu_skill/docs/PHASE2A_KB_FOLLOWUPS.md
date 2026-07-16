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

## WP2 Nord fixture provenance — seeded, not projected from live Phase-2A

**Observed:** The Nord fixture at `tests/fixtures/phase2b/nord_trusted_facts.json`
has been refreshed twice by WP-gate discipline:

- WP5 renamed `T2.swr.mstr.tx` -> `T2.soundwire_master` to match what
  `track_t2` actually emits (SHA update: `f9b69759...`)
- WP6 added `T3.lpass_macro_instance` (MATCH, count=0) and
  `T3.dsp_subsystem_instance` (MATCH, count=1) rows because the fixture
  had only `T3.clocks.count` — missing the two subjects the WP6 gate
  reads (SHA update: `55f1ca8f...`)

**Root cause:** The Nord fixture was seeded during WP2 authoring rather
than projected from a live Phase-2A run against Nord. As downstream
generators (WP5, WP6) declared their gate subjects, the drift between
fixture and live-projection surfaced one WP at a time.

**Not a defect:** Each drift was caught by the corresponding WP's gate,
recorded in the WP's commit message, and corrected at fixture-refresh
time. The `test_regression_anchor_byte_hash` in `test_generation_facts.py`
prevents silent drift within the fixture itself. Rehydrator symmetry
in `test_generation_facts.py::_rehydrate_phase2a_rows()` documents each
correction.

**Fix (Phase-2A follow-up):** Full WP2 fixture regeneration against a
live Nord Phase-2A run once bespoke tooling exists. Two prerequisites:

1. Nord's Phase-2A pipeline must reach a stable point where all
   generators' expected gate subjects are emitted by `track_*` functions
   (verified as of WP6: T1, T2, T3, T4a, T4b, T5 all emit their
   respective subjects).
2. A regeneration script at `tests/regenerate/regenerate_phase2b_fixtures.py`
   (per spec §8.3) that:
   - Runs the live Phase-2A pipeline against a canonical Nord input
   - Freezes the resulting rows to `nord_trusted_facts.json`
   - Recomputes SHA256 for the fixture
   - Emits a diff summary of what changed vs the seeded fixture
   - Refuses to run under CI (per §8.4 guardrail)

Once landed, the rehydrator's `_NORD_T4B_CODEC_SUBJECTS`, `_NORD_T2_SUBJECT`,
and `_NORD_T3_ROWS` constants become redundant (fixture reflects live
projection directly). Rehydrator's Phase-2A correction (T4b REVIEW_REQUIRED
-> NCC per `VerificationRow.__post_init__` invariant) still stands.

**Impact on downstream WPs:** None. WP7/8/9/10 don't touch the WP2 fixture.

**Priority:** Deferred. Not blocking any Phase-2B WP. Should land before
Phase-2B declares end-to-end complete (i.e. before Nord's `--onboard`
+ `--generate` produces onboarding_report.md sections against real
Phase-2A output).

**Cross-references:**
- `WP5 commit 0076536` (T2 rename)
- `WP6 commit 8196ff3` (T3 rows added)
- `test_generation_facts.py::_rehydrate_phase2a_rows`
- `crossverify_config.py::T5_TARGET_IDENTITY` (analogous
  seeded-vs-projected pattern)
