"""Mocked-QGenie tests for the reasoning client (v1.2 strict no-fallback).

All subprocess calls to `qgenie` are mocked; no real QGenie/Claude invocation
happens here. Covers each ReasoningUnavailableError code the client can raise,
the success path (mocked doctor + mocked analyze -> parsed ReasoningResult),
and the local-test engine's test-mode gate.

Run: PYTHONPATH=audio_bu_skill python3 tests/test_reasoning_client.py
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest import mock

from orchestrator.reasoning import ANALYSIS_SCHEMA
from orchestrator.reasoning.client import QGenieReasoningClient, ReasoningUnavailableError, get_reasoning_client

_DOCTOR_OK = (
    "CLI\n"
    "  qgenie_version: 1.1.13\n"
    "  auth: configured, file, redacted\n"
    "Harnesses\n"
    "  claude:   installed, config_ready, launch_ready, version=2.1.198\n"
    "Connectivity\n"
    "  all services reachable\n"
)

_VALID_ANALYSIS: dict[str, Any] = {
    "soc": {"value": "SA8797P", "confidence": 0.9, "citations": ["kernel/arch/arm64/boot/dts/qcom/fakesoc.dtsi"]},
    "codecs": [{"part": "WSA8845", "role": "amp", "confidence": 0.8, "citations": ["evidence/WSA8845.pdf"]}],
    "amplifiers": [], "mics": [], "speakers": [], "buses": [],
    "soundwire": {"present": True, "master_count": 1, "confidence": 0.7, "citations": ["evidence/WSA8845.pdf"]},
    "audio_stack": {"audioreach": True, "citations": []},
    "power_model": {"kind": "unknown", "confidence": 0.0, "citations": [], "needs_review": True},
    "nearest_targets": [{"name": "lemans-like", "score": 0.8, "rationale": "matching codecs", "citations": ["kernel/..."]}],
    "missing_evidence": ["no schematic PDF found"],
    "overall_confidence": 0.8,
    "human_review_needed": True,
}

_TASK_SPEC = {"skill_id": "target_onboarding", "target": "t", "kernel": {"path": "/tmp/k"}, "evidence": {}}


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> mock.Mock:
    m = mock.Mock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_cli_not_found() -> None:
    client = QGenieReasoningClient(qgenie_bin=None)
    with mock.patch("shutil.which", return_value=None):
        try:
            client.preflight()
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.CLI_NOT_FOUND, exc.code
    print("PASS: missing qgenie binary -> QGENIE_CLI_NOT_FOUND")


def test_auth_not_configured() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie")
    bad_doctor = _DOCTOR_OK.replace("auth: configured, file, redacted", "auth: not_configured")
    with mock.patch("subprocess.run", return_value=_proc(0, stdout=bad_doctor)):
        try:
            client.preflight()
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.AUTH_FAILED, exc.code
    print("PASS: auth not configured -> QGENIE_AUTH_FAILED")


def test_doctor_nonzero_exit() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie")
    with mock.patch("subprocess.run", return_value=_proc(1, stderr="boom")):
        try:
            client.preflight()
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.ENV_INVALID, exc.code
    print("PASS: `qgenie doctor` nonzero exit -> QGENIE_ENV_INVALID")


def test_analysis_timeout() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="qgenie", timeout=900)):
        try:
            client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.ANALYSIS_TIMEOUT, exc.code
    print("PASS: analysis subprocess timeout -> QGENIE_ANALYSIS_TIMEOUT")


def test_analysis_nonzero_exit() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    with mock.patch("subprocess.run", return_value=_proc(1, stderr="claude crashed")):
        try:
            client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.ANALYSIS_FAILED, exc.code
    print("PASS: analysis subprocess nonzero exit -> QGENIE_ANALYSIS_FAILED")


def test_output_unparseable() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    with mock.patch("subprocess.run", return_value=_proc(0, stdout="not json at all")):
        try:
            client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.OUTPUT_UNPARSEABLE, exc.code
    print("PASS: non-JSON stdout -> QGENIE_OUTPUT_UNPARSEABLE")


def test_output_schema_invalid() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    bad_analysis = {"soc": {"value": "X"}}  # missing required keys (codecs, power_model, ...)
    with mock.patch("subprocess.run", return_value=_proc(0, stdout=json.dumps(bad_analysis))):
        try:
            client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
            raise AssertionError("expected ReasoningUnavailableError")
        except ReasoningUnavailableError as exc:
            assert exc.code == ReasoningUnavailableError.OUTPUT_SCHEMA_INVALID, exc.code
    print("PASS: schema-invalid JSON -> QGENIE_OUTPUT_SCHEMA_INVALID")


def test_mocked_success_direct_object() -> None:
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    with mock.patch("subprocess.run", return_value=_proc(0, stdout=json.dumps(_VALID_ANALYSIS))):
        result = client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
    assert result.parsed["soc"]["value"] == "SA8797P"
    assert result.engine_id == "qgenie"
    assert result.parsed["nearest_targets"][0]["name"] == "lemans-like"
    print("PASS: mocked success (direct JSON object) -> parsed ReasoningResult")


def test_mocked_success_claude_envelope_string_result() -> None:
    """`claude --output-format json` wraps the result as {"type":..., "result": "<json-string>"}."""
    client = QGenieReasoningClient(qgenie_bin="/fake/qgenie", ipcat_mcp_config=None)
    client.cli_version, client.model_id, client._preflighted = "1.1.13", "2.1.198", True
    envelope = {"type": "result", "result": json.dumps(_VALID_ANALYSIS)}
    with mock.patch("subprocess.run", return_value=_proc(0, stdout=json.dumps(envelope))):
        result = client.analyze(_TASK_SPEC, json_schema=ANALYSIS_SCHEMA, timeout=900)
    assert result.parsed["codecs"][0]["part"] == "WSA8845"
    print("PASS: mocked success (claude envelope, string result) -> parsed ReasoningResult")


def test_local_engine_blocked_without_test_mode() -> None:
    try:
        get_reasoning_client("local-test", test_mode=False)
        raise AssertionError("expected ReasoningUnavailableError")
    except ReasoningUnavailableError as exc:
        assert exc.code == ReasoningUnavailableError.LOCAL_ENGINE_BLOCKED, exc.code
    print("PASS: local-test engine rejected without --test-mode")


def test_local_engine_allowed_with_test_mode() -> None:
    client = get_reasoning_client("local-test", test_mode=True)
    assert client.engine_id == "local-test"
    print("PASS: local-test engine allowed with --test-mode (stamped engine_id=local-test)")


def test_unknown_engine_rejected() -> None:
    try:
        get_reasoning_client("gpt-5-turbo")
        raise AssertionError("expected ReasoningUnavailableError")
    except ReasoningUnavailableError as exc:
        assert exc.code == ReasoningUnavailableError.ENV_INVALID, exc.code
    print("PASS: unknown engine id rejected, not silently substituted")


def main() -> None:
    test_cli_not_found()
    test_auth_not_configured()
    test_doctor_nonzero_exit()
    test_analysis_timeout()
    test_analysis_nonzero_exit()
    test_output_unparseable()
    test_output_schema_invalid()
    test_mocked_success_direct_object()
    test_mocked_success_claude_envelope_string_result()
    test_local_engine_blocked_without_test_mode()
    test_local_engine_allowed_with_test_mode()
    test_unknown_engine_rejected()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
