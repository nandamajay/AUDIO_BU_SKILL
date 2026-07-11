"""Unit tests for the additive ANALYSIS_SCHEMA / target_onboarding schema.json
extension (slice 5 of the Onboarding Accuracy Upgrade).

Confirms: schema version bumped, a 1.0.0-shaped analysis (no schematic_nets,
no q6apm/q6prm) still validates, a 1.1.0-shaped analysis (with them) also
validates, and the skill's schema.json still accepts the exact same
generated_case shape produced before this slice (no new required fields).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_analysis_schema_v1_1
(or: python3 audio_bu_skill/tests/test_analysis_schema_v1_1.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from orchestrator.reasoning.schemas import ANALYSIS_SCHEMA, ANALYSIS_SCHEMA_VERSION

SKILL_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "skills" / "target_onboarding" / "schema.json"

_V1_0_STYLE_ANALYSIS = {
    "soc": {"value": "SA8797P", "confidence": 0.9, "citations": ["kernel/fakesoc.dtsi"]},
    "codecs": [{"part": "WSA8845", "confidence": 0.8, "citations": ["evidence/WSA8845.pdf"]}],
    "power_model": {"kind": "rpmhpd", "confidence": 0.6, "citations": [], "needs_review": True},
    "nearest_targets": [{"name": "nord-iq10", "score": 0.4, "rationale": "shared ADSP", "citations": []}],
    "missing_evidence": [], "overall_confidence": 0.7, "human_review_needed": True,
}

_V1_1_STYLE_ANALYSIS = {
    **_V1_0_STYLE_ANALYSIS,
    "audio_stack": {"lpass": True, "adsp": True, "audioreach": True, "gpr": True, "apm": True,
                     "q6apm": True, "q6prm": True, "citations": []},
    "schematic_nets": [{"net_name": "WSA1_EN", "gpio": 59, "sheet_ref": "CQ7790_GPIO1", "citations": []}],
}


def test_schema_version_bumped() -> None:
    assert ANALYSIS_SCHEMA_VERSION == "1.1.0", ANALYSIS_SCHEMA_VERSION
    print("PASS: ANALYSIS_SCHEMA_VERSION bumped to 1.1.0")


def test_v1_0_style_analysis_still_validates() -> None:
    jsonschema.validate(instance=_V1_0_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.0.0-shaped analysis (no schematic_nets/q6apm/q6prm) still validates against 1.1.0 schema")


def test_v1_1_style_analysis_validates() -> None:
    jsonschema.validate(instance=_V1_1_STYLE_ANALYSIS, schema=ANALYSIS_SCHEMA)  # must not raise
    print("PASS: a 1.1.0-shaped analysis (with schematic_nets/q6apm/q6prm) validates")


def test_schematic_nets_missing_gpio_rejected() -> None:
    bad = {**_V1_0_STYLE_ANALYSIS, "schematic_nets": [{"net_name": "WSA1_EN"}]}  # missing required "gpio"
    try:
        jsonschema.validate(instance=bad, schema=ANALYSIS_SCHEMA)
        raise AssertionError("expected schema validation to reject a schematic_net missing 'gpio'")
    except jsonschema.ValidationError:
        pass
    print("PASS: a schematic_net item missing required 'gpio' is rejected")


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


def main() -> None:
    test_schema_version_bumped()
    test_v1_0_style_analysis_still_validates()
    test_v1_1_style_analysis_validates()
    test_schematic_nets_missing_gpio_rejected()
    test_skill_schema_json_still_valid_json_and_backward_compatible()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
