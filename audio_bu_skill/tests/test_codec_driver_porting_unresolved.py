"""Unit tests for Benchmark Readiness Fix #1: codec_driver_porting accepts
"unresolved" codec_verdicts status from target_onboarding.

Confirms:
  - the input schema's verdicts.status enum now includes "unresolved" (and
    verdicts.driver_path accepts null, matching target_onboarding's
    _derive_codec_verdicts() shape of {"driver_path": None, "status": "unresolved"}),
  - a verdicts dict shaped exactly like target_onboarding's output (eliza's
    WCD9378 / nord-iq10's ADAU1979 case) now validates instead of raising
    CODEC_DRIVER_PORTING_INPUT_INVALID,
  - run_codec_driver_porting() still treats "unresolved" as blocking DT
    generation (blocks_dt_generation=True), same as needs_port/needs_write,
  - "unresolved" is NOT silently mapped/upgraded to upstream_present/needs_port/
    needs_write -- the runner and validator both still pass it through verbatim.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_codec_driver_porting_unresolved
(or: python3 audio_bu_skill/tests/test_codec_driver_porting_unresolved.py)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from orchestrator.runners.codec_driver_porting_runner import run_codec_driver_porting

_VALIDATOR_PATH = Path(__file__).resolve().parents[1] / "skills" / "codec_driver_porting" / "validator.py"
_spec = importlib.util.spec_from_file_location("codec_driver_porting_validator", _VALIDATOR_PATH)
_validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validator)
validate_input = _validator.validate_input
validate_output = _validator.validate_output


def _base_input(verdicts: dict) -> dict:
    return {
        "workspace_context": {"workspace_root": "/local/mnt/workspace/NORD_BU"},
        "codec_part_numbers": sorted(verdicts.keys()),
        "kernel_source_path": "linux-fake",
        "run_id": "test-onboarding",
        "verdicts": verdicts,
    }


def test_unresolved_verdict_with_null_driver_path_validates() -> None:
    """Exact shape produced by target_onboarding_runner._derive_codec_verdicts()
    for eliza's WCD9378 and nord-iq10's ADAU1979: {"driver_path": None, "status": "unresolved"}."""
    input_envelope = _base_input({
        "WCD9378": {"driver_path": None, "status": "unresolved"},
    })
    validate_input(input_envelope)  # must not raise
    print("PASS: verdicts.status='unresolved' with driver_path=null validates against input schema")


def test_upstream_present_verdict_still_requires_nonempty_driver_path() -> None:
    """Regression: the pre-existing three statuses still require a real driver_path string."""
    bad_input = _base_input({
        "PCM1681": {"driver_path": None, "status": "upstream_present"},
    })
    try:
        validate_input(bad_input)
        raise AssertionError("expected validation to reject upstream_present with driver_path=null")
    except _validator.SchemaValidationError as exc:
        assert exc.code == "CODEC_DRIVER_PORTING_INPUT_INVALID", exc.code
    print("PASS: upstream_present/needs_port/needs_write still require a non-null driver_path (unchanged)")


def test_unresolved_still_blocks_dt_generation() -> None:
    with_root = Path(__file__).resolve().parents[2]  # repo root, just needs to exist as a Path
    input_envelope = _base_input({
        "WCD9378": {"driver_path": None, "status": "unresolved"},
    })
    input_envelope["kernel_source_path"] = str(with_root)  # any real dir; driver won't exist on disk

    output = run_codec_driver_porting(input_envelope)
    availability = output["codec_driver_availability"]

    assert availability["per_codec"]["WCD9378"]["status"] == "unresolved"
    assert availability["per_codec"]["WCD9378"]["driver_path"] is None
    assert availability["blocks_dt_generation"] is True

    validate_output(output)  # must not raise -- output schema already allowed "unresolved"
    print("PASS: run_codec_driver_porting() treats 'unresolved' as blocking DT generation, "
          "same as needs_port/needs_write, and never crashes on driver_path=None")


def test_unresolved_not_fabricated_into_upstream_present() -> None:
    """codec_driver_porting must never guess a concrete status for an
    unresolved codec -- it passes the caller's verdict through verbatim."""
    root = Path(__file__).resolve().parents[2]
    input_envelope = _base_input({"ADAU1979": {"driver_path": None, "status": "unresolved"}})
    input_envelope["kernel_source_path"] = str(root)

    output = run_codec_driver_porting(input_envelope)
    status = output["codec_driver_availability"]["per_codec"]["ADAU1979"]["status"]
    assert status == "unresolved", status
    assert status not in ("upstream_present", "needs_port", "needs_write")
    print("PASS: 'unresolved' is passed through verbatim -- never fabricated into a concrete status")


def test_mixed_verdicts_upstream_present_and_unresolved() -> None:
    """nord-iq10-shaped input: one resolved codec (PCM1681, real driver on disk),
    one unresolved (ADAU1979) -- both must coexist and validate."""
    root = Path(__file__).resolve().parents[1] / "orchestrator"  # a real dir that exists
    input_envelope = _base_input({
        "PCM1681": {"driver_path": "reasoning/schemas.py", "status": "upstream_present"},
        "ADAU1979": {"driver_path": None, "status": "unresolved"},
    })
    input_envelope["kernel_source_path"] = str(root)
    validate_input(input_envelope)  # must not raise

    output = run_codec_driver_porting(input_envelope)
    per_codec = output["codec_driver_availability"]["per_codec"]
    assert per_codec["PCM1681"]["status"] == "upstream_present"
    assert per_codec["PCM1681"]["exists_on_disk"] is True
    assert per_codec["ADAU1979"]["status"] == "unresolved"
    assert output["codec_driver_availability"]["blocks_dt_generation"] is True
    validate_output(output)
    print("PASS: mixed upstream_present + unresolved verdicts (nord-iq10 shape) validate end-to-end")


def main() -> None:
    test_unresolved_verdict_with_null_driver_path_validates()
    test_upstream_present_verdict_still_requires_nonempty_driver_path()
    test_unresolved_still_blocks_dt_generation()
    test_unresolved_not_fabricated_into_upstream_present()
    test_mixed_verdicts_upstream_present_and_unresolved()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
