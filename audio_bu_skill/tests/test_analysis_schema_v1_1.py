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
    assert ANALYSIS_SCHEMA_VERSION == "1.4.0", ANALYSIS_SCHEMA_VERSION
    print("PASS: ANALYSIS_SCHEMA_VERSION bumped to 1.4.0")


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
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
