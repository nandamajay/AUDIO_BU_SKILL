"""Unit tests for the additive ANALYSIS_SCHEMA / target_onboarding schema.json
extension (slice 5 of the Onboarding Accuracy Upgrade).

Confirms: schema version bumped, a 1.0.0-shaped analysis (no schematic_nets,
no q6apm/q6prm) still validates, a 1.1.0-shaped analysis (with them) also
validates, and the skill's schema.json still accepts the exact same
generated_case shape produced before this slice (no new required fields).

Also covers the 1.4.0 nearest_targets citation contract: every scored
nearest_targets entry must carry a non-empty citations list (schema-level
enforcement, mirrors the FINDING_MISSING_CITATION validator rule).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_analysis_schema_v1_1
(or: python3 audio_bu_skill/tests/test_analysis_schema_v1_1.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from orchestrator.reasoning.schemas import ANALYSIS_SCHEMA, ANALYSIS_SCHEMA_VERSION

SKILL_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "skills" / "target_onboarding" / "schema.json"
# Frozen real 1.2.0 analysis artifacts (Nord + Eliza), captured BEFORE the Fix A
# re-run added element_counts. Kept as immutable fixtures so this backward-compat
# proof is stable even after the live targets/ artifacts are regenerated at 1.3.0.
_FIXTURES_1_2_0 = Path(__file__).resolve().parent / "fixtures" / "schema_1_2_0"

_V1_0_STYLE_ANALYSIS = {
    "soc": {"value": "SA8797P", "confidence": 0.9, "citations": ["kernel/fakesoc.dtsi"]},
    "codecs": [{"part": "WSA8845", "confidence": 0.8, "citations": ["evidence/WSA8845.pdf"]}],
    "power_model": {"kind": "rpmhpd", "confidence": 0.6, "citations": [], "needs_review": True},
    "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP",
                          "citations": ["kernel/fakesoc.dtsi"]}],
    "missing_evidence": [], "overall_confidence": 0.7, "human_review_needed": True,
}

_V1_1_STYLE_ANALYSIS = {
    **_V1_0_STYLE_ANALYSIS,
    "audio_stack": {"lpass": True, "adsp": True, "audioreach": True, "gpr": True, "apm": True,
                     "q6apm": True, "q6prm": True, "citations": []},
    "schematic_nets": [{"net_name": "WSA1_EN", "gpio": 59, "sheet_ref": "CQ7790_GPIO1", "citations": []}],
}

_V1_2_STYLE_ANALYSIS = {
    **_V1_1_STYLE_ANALYSIS,
    "ipcat_findings": {
        "queried": True, "returned_target_specific": False, "returned_generic_only": True,
        "notes": "only generic multi-SoC HPG chapters returned", "citations": [],
    },
}

# 1.3.0 (Fix A): adds optional element_counts — per-element-class instance
# counts as typed integers per enumeration lane. Modeled on real Eliza data
# (dmic_line 8, amplifier 2, soundwire_master ambiguous 1-or-2).
_V1_3_STYLE_ANALYSIS = {
    **_V1_2_STYLE_ANALYSIS,
    "element_counts": [
        {
            "element_class": "dmic_line",
            "dt": 0, "evidence": 8, "proposal": 8, "catalog": None,
            "ambiguous": False, "dt_applied": False,
            "citations": ["board-block-diagram p4 (DMIC01/23/45/67 = 8)"],
        },
        {
            "element_class": "soundwire_master",
            "dt": 0, "evidence": None, "proposal": 1, "catalog": None,
            "ambiguous": True, "dt_applied": False,
            "ambiguity_note": "could be 1 or 2 physical masters; not resolved pre-SWI",
            "citations": ["soundwire.master_count=1 (low confidence)"],
        },
    ],
}


def test_schema_version_bumped() -> None:
    assert ANALYSIS_SCHEMA_VERSION == "1.5.0", ANALYSIS_SCHEMA_VERSION
    print("PASS: ANALYSIS_SCHEMA_VERSION bumped to 1.5.0")


def test_v1_0_style_analysis_still_validates() -> None:
    jsonschema.validate(instance=_V1_0_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.0.0-shaped analysis (no schematic_nets/q6apm/q6prm) still validates against 1.1.0 schema")


def test_v1_1_style_analysis_validates() -> None:
    jsonschema.validate(instance=_V1_1_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.1.0-shaped analysis (with schematic_nets/q6apm/q6prm) validates")


def test_v1_2_style_analysis_validates() -> None:
    jsonschema.validate(instance=_V1_2_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.2.0-shaped analysis (with ipcat_findings) validates")


def test_v1_3_style_analysis_validates() -> None:
    jsonschema.validate(instance=_V1_3_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.3.0-shaped analysis (with element_counts) validates")


def test_v1_2_style_analysis_still_validates_without_element_counts() -> None:
    # The core backward-compat guarantee: a full 1.2.0 response (no
    # element_counts key at all) still validates under the 1.3.0 schema.
    assert "element_counts" not in _V1_2_STYLE_ANALYSIS
    jsonschema.validate(instance=_V1_2_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.2.0-shaped analysis (no element_counts at all) still validates against 1.3.0 schema")


def test_empty_element_counts_validates() -> None:
    # [] is valid — "reported, nothing enumerated", distinct from absent.
    doc = {**_V1_0_STYLE_ANALYSIS, "element_counts": []}
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: element_counts: [] validates (reported-but-empty)")


def test_element_count_missing_element_class_rejected() -> None:
    bad = {**_V1_0_STYLE_ANALYSIS,
           "element_counts": [{"proposal": 2, "citations": []}]}  # missing required element_class
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected rejection of an element_count missing 'element_class'")
    except jsonschema.ValidationError:
        pass
    print("PASS: an element_count item missing required 'element_class' is rejected")


def test_element_count_negative_lane_rejected() -> None:
    bad = {**_V1_0_STYLE_ANALYSIS,
           "element_counts": [{"element_class": "dmic_line", "proposal": -1, "citations": []}]}
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected rejection of a negative lane count")
    except jsonschema.ValidationError:
        pass
    print("PASS: a negative element_count lane (proposal: -1) is rejected")


def test_element_count_null_lane_validates() -> None:
    # null is a first-class value (lane not consulted), distinct from 0.
    doc = {**_V1_0_STYLE_ANALYSIS,
           "element_counts": [{"element_class": "soundwire_master", "dt": 0,
                               "evidence": None, "proposal": 1, "catalog": None,
                               "ambiguous": True, "dt_applied": False, "citations": []}]}
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: null lane values validate (null = lane-not-consulted, distinct from 0)")


def test_element_count_non_integer_lane_rejected() -> None:
    bad = {**_V1_0_STYLE_ANALYSIS,
           "element_counts": [{"element_class": "dmic_line", "proposal": "8", "citations": []}]}
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected rejection of a string lane count")
    except jsonschema.ValidationError:
        pass
    print("PASS: a non-integer element_count lane (proposal: '8') is rejected")


def test_v1_1_style_analysis_still_validates_without_ipcat_findings() -> None:
    assert "ipcat_findings" not in _V1_1_STYLE_ANALYSIS
    jsonschema.validate(instance=_V1_1_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.1.0-shaped analysis (no ipcat_findings at all) still validates against 1.2.0 schema")


def test_schematic_nets_missing_gpio_rejected() -> None:
    bad = {**_V1_0_STYLE_ANALYSIS, "schematic_nets": [{"net_name": "WSA1_EN"}]}  # missing required "gpio"
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected schema validation to reject a schematic_net missing 'gpio'")
    except jsonschema.ValidationError:
        pass
    print("PASS: a schematic_net item missing required 'gpio' is rejected")


def test_stored_1_2_0_target_artifacts_still_validate() -> None:
    # Real-data backward-compat proof: the actual Nord + Eliza qgenie_analysis.json
    # as produced under schema 1.2.0 (frozen fixtures, neither carrying
    # element_counts) must still validate unchanged under the 1.3.0 schema.
    # Uses frozen copies rather than the live targets/ artifacts, which are
    # regenerated at 1.3.0 (with element_counts) by the Fix A re-run.
    checked = 0
    for target in ("nord-iq10", "eliza"):
        path = _FIXTURES_1_2_0 / f"{target}_qgenie_analysis.json"
        if not path.exists():
            continue
        analysis = json.loads(path.read_text(encoding="utf-8"))
        assert "element_counts" not in analysis, f"{target} fixture unexpectedly has element_counts"
        jsonschema.validate(instance=analysis, schema=ANALYSIS_SCHEMA)  # must not raise
        checked += 1
    assert checked == 2, f"expected 2 frozen 1.2.0 fixtures, validated {checked}"
    print(f"PASS: {checked} frozen real 1.2.0 analysis artifact(s) still validate under 1.3.0 "
          "(no element_counts, unchanged)")


def test_skill_schema_json_still_valid_json_and_backward_compatible() -> None:
    schema = json.loads(SKILL_SCHEMA_PATH.read_text(encoding="utf-8"))
    generated_case_schema = schema["output_envelope"]["properties"]["generated_case"]

    # required list unchanged from before this slice (no new required fields).
    assert generated_case_schema["required"] == ["target_soc", "nearest_target", "run_id", "needs_review"], \
        generated_case_schema["required"]

    # new optional properties present
    assert "audio_topology" in generated_case_schema["properties"]
    assert "candidate_patch_series" in generated_case_schema["properties"]

    # the exact generated_case shape produced before this slice (no audio_topology
    # key at all) must still satisfy the schema's `required` list.
    pre_slice5_generated_case = {
        "target_soc": "SA8797P", "nearest_target": "nord-iq10", "run_id": "eliza-onboarding",
        "needs_review": ["power_model_source: never auto-finalized"],
    }
    for key in generated_case_schema["required"]:
        assert key in pre_slice5_generated_case, key
    print("PASS: target_onboarding schema.json's generated_case required-list unchanged; "
          "pre-slice-5 output shape still satisfies it")


def test_nearest_target_without_citations_rejected() -> None:
    # 1.4.0: citations is now required with minItems=1 on nearest_targets items.
    # A scored entry with citations absent must be rejected by the schema.
    bad = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP"}]}
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected rejection of nearest_targets entry missing citations")
    except jsonschema.ValidationError:
        pass
    print("PASS: nearest_targets entry missing citations field is rejected (1.4.0 contract)")


def test_nearest_target_with_empty_citations_rejected() -> None:
    # An empty citations list is as unauditable as an absent one — also rejected.
    bad = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP",
                                 "citations": []}]}
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected rejection of nearest_targets entry with citations: []")
    except jsonschema.ValidationError:
        pass
    print("PASS: nearest_targets entry with citations: [] is rejected (minItems=1)")


def test_nearest_target_with_citations_validates() -> None:
    # The positive case: a non-empty citations list satisfies both schema and validator.
    doc = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP",
                                 "citations": ["kernel/fakesoc.dtsi"]}]}
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: nearest_targets entry with non-empty citations validates")


# ---------------------------------------------------------------------------
# 1.5.0 (Phase A): nearest_targets role field — optional donor decomposition
# ---------------------------------------------------------------------------

def test_nearest_target_with_role_validates() -> None:
    # A role-tagged nearest_targets entry must pass schema validation.
    doc = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [{"name": "sa8775p-ref", "score": 0.72, "rationale": "ADSP match",
                                 "citations": ["kernel/sa8775p.dtsi"], "role": "adsp_stack"}]}
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: nearest_targets entry with optional role field validates (1.5.0)")


def test_nearest_target_without_role_still_validates() -> None:
    # role is NOT in required[]: omitting it must not break validation.
    doc = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP",
                                 "citations": ["kernel/fakesoc.dtsi"]}]}
    # no "role" key present
    assert "role" not in doc["nearest_targets"][0]
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: nearest_targets entry without role still validates (role is optional)")


def test_nearest_target_multiple_roles_in_list_validates() -> None:
    # Mixed list: one entry with role, one without — both must validate.
    doc = {**_V1_0_STYLE_ANALYSIS,
           "nearest_targets": [
               {"name": "sa8775p-ref", "score": 0.72, "rationale": "ADSP match",
                "citations": ["kernel/sa8775p.dtsi"], "role": "adsp_stack"},
               {"name": "qcs9100-ride", "score": 0.71, "rationale": "codec match",
                "citations": ["kernel/qcs9100-ride.dtsi"], "role": "sound_card"},
               {"name": "other-board", "score": 0.50, "rationale": "partial match",
                "citations": ["kernel/other.dtsi"]},  # no role
           ]}
    jsonschema.validate(instance=doc, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: mixed nearest_targets list (role present/absent) validates")


def test_runner_donor_targets_populated_from_roles() -> None:
    # Exercise the runner's actual donor_targets ingest (via _normalize_role),
    # not an inlined copy, so this test tracks the real code path. Legacy Phase A
    # role tags ("adsp_donor"/"soundcard_donor") must be folded to the canonical
    # vocabulary ("adsp_stack"/"sound_card") at ingest.
    from orchestrator.runners.target_onboarding_runner import _normalize_role
    nearest = [
        {"name": "sa8775p-ref", "score": 0.72, "rationale": "ADSP", "citations": ["k.dtsi"],
         "role": "adsp_donor"},
        {"name": "qcs9100-ride", "score": 0.71, "rationale": "codecs", "citations": ["k.dtsi"],
         "role": "soundcard_donor"},
        {"name": "other-board", "score": 0.50, "rationale": "partial", "citations": ["k.dtsi"]},
    ]
    donor_targets: dict[str, str] = {}
    for nt in nearest:
        role = _normalize_role(nt.get("role", ""))
        if role:
            donor_targets[role] = nt.get("name", "")

    # Legacy input, canonical output — the derivation keys off adsp_stack/sound_card.
    assert donor_targets == {"adsp_stack": "sa8775p-ref", "sound_card": "qcs9100-ride"}, donor_targets
    assert "other-board" not in donor_targets.values(), "no-role entry must not appear in donor_targets"
    print("PASS: donor_targets populated + legacy roles folded to canonical vocabulary")


def test_runner_donor_targets_empty_when_no_roles() -> None:
    # When no nearest_targets entries carry a role field, donor_targets stays {}.
    nearest = [
        {"name": "sa8775p-ref", "score": 0.72, "rationale": "ADSP", "citations": ["k.dtsi"]},
        {"name": "qcs9100-ride", "score": 0.71, "rationale": "codecs", "citations": ["k.dtsi"]},
    ]
    donor_targets: dict[str, str] = {}
    for nt in nearest:
        role = nt.get("role", "")
        if role:
            donor_targets[role] = nt.get("name", "")

    assert donor_targets == {}, f"expected empty donor_targets, got {donor_targets}"
    print("PASS: donor_targets stays {{}} when no role tags present (safe no-op for existing artifacts)")


# ---------------------------------------------------------------------------
# Phase B: role-specific confidence in the QGenie-backed runner path
# ---------------------------------------------------------------------------

def test_runner_role_confidence_empty_when_no_roles() -> None:
    # The core backward-compat guarantee for Phase B: on any analysis whose
    # nearest_targets carry no role (all real Nord/Eliza data today), the runner's
    # _qgenie_role_confidence returns {} — a pure no-op, exactly like donor_targets.
    from orchestrator.runners.target_onboarding_runner import _qgenie_role_confidence
    nearest = [
        {"name": "sa8775p", "score": 0.85, "role": None},
        {"name": "qcs9100-ride", "score": 0.80, "role": None},
    ]
    assert _qgenie_role_confidence(nearest, {}) == {}
    print("PASS: _qgenie_role_confidence is {{}} when no roles tagged (Phase B no-op on real data)")


def test_runner_role_confidence_split_donor() -> None:
    # Split-donor case: ADSP donor sa8775p (0.85), sound-card donor qcs9100-ride
    # (0.80). Each role graded independently against the best OTHER candidate.
    from orchestrator.runners.target_onboarding_runner import _qgenie_role_confidence
    nearest = [
        {"name": "sa8775p", "score": 0.85, "role": "adsp_stack"},
        {"name": "qcs9100-ride", "score": 0.80, "role": "sound_card"},
        {"name": "sc7280", "score": 0.30},
    ]
    donor_targets = {"adsp_stack": "sa8775p", "sound_card": "qcs9100-ride"}
    rc = _qgenie_role_confidence(nearest, donor_targets)
    assert set(rc) == {"adsp_stack", "sound_card"}, rc
    # adsp_stack: top 0.85, best-other = 0.80 -> margin 0.05
    assert rc["adsp_stack"]["top"] == "sa8775p"
    assert rc["adsp_stack"]["score"] == 0.85
    assert abs(rc["adsp_stack"]["margin"] - 0.05) < 1e-6, rc["adsp_stack"]
    # sound_card: top 0.80, best-other = 0.85 (the adsp donor) -> margin -0.05
    assert rc["sound_card"]["top"] == "qcs9100-ride"
    assert abs(rc["sound_card"]["margin"] - (-0.05)) < 1e-6, rc["sound_card"]
    # both below threshold -> low_confidence, and the formula is the shared one
    for role, block in rc.items():
        assert block["low_confidence"] is True, (role, block)
        expected = max(0.0, min(1.0, block["score"] * (block["margin"] + 0.10)))
        assert abs(block["confidence"] - round(expected, 4)) < 1e-6, (role, block)
        assert block["source"] == "qgenie"
        for key in ("top", "score", "margin", "confidence", "low_confidence", "min_score", "min_margin"):
            assert key in block, (role, key)
    print("PASS: _qgenie_role_confidence grades adsp_stack/sound_card donors independently")


def test_runner_nearest_target_derivation() -> None:
    # Phase B derivation: donor_targets.get("adsp_stack") or .get("sound_card") or top_name.
    def derive(donor_targets: dict[str, str], top_name: str) -> str:
        return (donor_targets.get("adsp_stack") or donor_targets.get("sound_card") or top_name)

    # 1. no roles -> falls back to blended top_name (pre-Phase-B behavior, unchanged)
    assert derive({}, "sa8775p") == "sa8775p"
    # 2. adsp_stack present -> wins
    assert derive({"adsp_stack": "sa8775p", "sound_card": "qcs9100-ride"}, "other") == "sa8775p"
    # 3. only sound_card present -> sound_card wins
    assert derive({"sound_card": "qcs9100-ride"}, "other") == "qcs9100-ride"
    # 4. no roles AND no top_name -> empty (runner marks UNKNOWN downstream)
    assert derive({}, "") == ""
    print("PASS: nearest_target derivation prefers adsp_stack, then sound_card, then top_name")


def test_runner_normalize_role_folds_legacy_aliases() -> None:
    # The runner mirrors engine.normalize_role locally (production path is decoupled
    # from the demoted local engine). Both must agree on the canonical folding.
    from orchestrator.runners.target_onboarding_runner import _normalize_role
    assert _normalize_role("adsp_donor") == "adsp_stack"
    assert _normalize_role("soundcard_donor") == "sound_card"
    assert _normalize_role("adsp_stack") == "adsp_stack"
    assert _normalize_role("sound_card") == "sound_card"
    assert _normalize_role("unknown") == "unknown"
    assert _normalize_role("") == ""
    # cross-check the runner's local map against the engine's canonical map
    from orchestrator.similarity import normalize_role as engine_normalize
    for legacy in ("adsp_donor", "soundcard_donor", "adsp_stack", "sound_card", "x", ""):
        assert _normalize_role(legacy) == engine_normalize(legacy), legacy
    print("PASS: runner _normalize_role folds legacy aliases and agrees with engine.normalize_role")


def test_runner_legacy_roles_flow_through_derivation() -> None:
    # End-to-end: QGenie emits LEGACY role tags -> normalization folds them ->
    # donor_targets is keyed canonically -> the nearest_target derivation (which
    # keys off adsp_stack/sound_card) picks the ADSP donor. Without folding this
    # would silently miss and collapse to the blended top_name — the exact latent
    # bug this review closes.
    from orchestrator.runners.target_onboarding_runner import (
        _normalize_role, _qgenie_role_confidence,
    )
    nearest = [
        {"name": "sc7280", "score": 0.90, "role": None},              # blended top, no role
        {"name": "sa8775p", "score": 0.85, "role": "adsp_donor"},     # legacy ADSP donor
        {"name": "qcs9100-ride", "score": 0.80, "role": "soundcard_donor"},  # legacy sndcard donor
    ]
    donor_targets: dict[str, str] = {}
    for nt in nearest:
        role = _normalize_role(nt.get("role", ""))
        if role:
            donor_targets[role] = nt.get("name", "")
    assert donor_targets == {"adsp_stack": "sa8775p", "sound_card": "qcs9100-ride"}, donor_targets

    top_name = nearest[0]["name"]  # "sc7280" — highest blended score
    derived = donor_targets.get("adsp_stack") or donor_targets.get("sound_card") or top_name
    assert derived == "sa8775p", f"legacy adsp donor must win derivation, got {derived}"

    # role_confidence is keyed canonically too, from the folded donor_targets
    rc = _qgenie_role_confidence(nearest, donor_targets)
    assert set(rc) == {"adsp_stack", "sound_card"}, rc
    assert rc["adsp_stack"]["top"] == "sa8775p"
    assert rc["sound_card"]["top"] == "qcs9100-ride"
    print("PASS: legacy role tags fold through to canonical derivation + role_confidence")


def main() -> None:
    test_schema_version_bumped()
    test_v1_0_style_analysis_still_validates()
    test_v1_1_style_analysis_validates()
    test_v1_2_style_analysis_validates()
    test_v1_3_style_analysis_validates()
    test_v1_2_style_analysis_still_validates_without_element_counts()
    test_empty_element_counts_validates()
    test_element_count_missing_element_class_rejected()
    test_element_count_negative_lane_rejected()
    test_element_count_null_lane_validates()
    test_element_count_non_integer_lane_rejected()
    test_v1_1_style_analysis_still_validates_without_ipcat_findings()
    test_schematic_nets_missing_gpio_rejected()
    test_stored_1_2_0_target_artifacts_still_validate()
    test_skill_schema_json_still_valid_json_and_backward_compatible()
    test_nearest_target_without_citations_rejected()
    test_nearest_target_with_empty_citations_rejected()
    test_nearest_target_with_citations_validates()
    # 1.5.0 Phase A tests
    test_nearest_target_with_role_validates()
    test_nearest_target_without_role_still_validates()
    test_nearest_target_multiple_roles_in_list_validates()
    test_runner_donor_targets_populated_from_roles()
    test_runner_donor_targets_empty_when_no_roles()
    test_runner_normalize_role_folds_legacy_aliases()
    test_runner_legacy_roles_flow_through_derivation()
    test_runner_role_confidence_empty_when_no_roles()
    test_runner_role_confidence_split_donor()
    test_runner_nearest_target_derivation()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
