"""Skill-invocation failure-path tests for BringupOrchestrator.invoke_skill.

Focus: a skill whose INPUT fails validation must surface as
OrchestratorError(code="SKILL_INPUT_INVALID") and must NOT be masked by a
StateMachineError from an illegal lifecycle transition (regression test for the
READY->FAILED transition the driver records on input-validation failure).

Also re-covers the already-working SKILL_OUTPUT_INVALID path and a normal
success, so a future FSM change can't silently regress either.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_skill_invocation_failures
(or: python3 audio_bu_skill/tests/test_skill_invocation_failures.py)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from orchestrator.driver import BringupOrchestrator, OrchestratorError
from orchestrator.skill_state_machine import StateMachineError

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _fresh_orchestrator(tmp_root: Path, run_id: str) -> BringupOrchestrator:
    o = BringupOrchestrator(workspace_root=tmp_root, skills_root=SKILLS_ROOT, run_id=run_id)
    o.start_run(target_soc="TEST1", nearest_target="x")
    return o


def _good_input(tmp_root: Path) -> dict:
    """A source_intake input_envelope that passes schema validation."""
    return {
        "workspace_context": {"workspace_root": str(tmp_root)},
        "target_soc": "TEST1",
        "run_id": "test-run",
        "decision": {"evidence_source": "offline_documents", "power_model_source": "n/a (test)"},
        "evidence_roots": {},
    }


def _good_output() -> dict:
    """A source_intake output the validator accepts."""
    return {
        "resolved_evidence_sources": {
            "run_id": "test-run",
            "evidence_source": "offline_documents",
            "power_model_source": "n/a (test)",
            "available_inputs": [],
            "ambiguities": [],
            "provenance": {"policy": "offline_documents", "primary_source": "offline_documents",
                           "fell_back": False, "fallback_reason": None, "mcp": None},
        },
        "evidence": {"evidence_refs": ["x"]},
        "human_review_needed": False,
        "ambiguities": [],
    }


def test_input_invalid_not_masked() -> None:
    """Malformed input -> SKILL_INPUT_INVALID, not StateMachineError."""
    with tempfile.TemporaryDirectory() as tmp:
        o = _fresh_orchestrator(Path(tmp), "input-invalid-run")
        o.register_runner("source_intake", lambda env: _good_output())
        try:
            # Missing required top-level keys -> input schema validation fails.
            o.invoke_skill("source_intake", {"not": "a valid envelope"})
        except StateMachineError as exc:  # the exact masking bug being guarded against
            raise AssertionError(
                f"SKILL_INPUT_INVALID was masked by StateMachineError: {exc.details}"
            ) from exc
        except OrchestratorError as exc:
            assert exc.code == "SKILL_INPUT_INVALID", f"expected SKILL_INPUT_INVALID, got {exc.code}"
        else:
            raise AssertionError("expected OrchestratorError(SKILL_INPUT_INVALID), nothing raised")
    print("PASS: input-invalid surfaces SKILL_INPUT_INVALID, not masked")


def test_output_invalid_still_raises() -> None:
    """Bad runner output -> SKILL_OUTPUT_INVALID (preserved behavior)."""
    with tempfile.TemporaryDirectory() as tmp:
        o = _fresh_orchestrator(Path(tmp), "output-invalid-run")
        # valid input passes; output is structurally wrong (bad evidence_source enum)
        bad = {"resolved_evidence_sources": {"evidence_source": "BOGUS"},
               "evidence": {"evidence_refs": ["x"]}, "human_review_needed": False, "ambiguities": []}
        o.register_runner("source_intake", lambda env: bad)
        try:
            o.invoke_skill("source_intake", _good_input(Path(tmp)))
        except OrchestratorError as exc:
            assert exc.code == "SKILL_OUTPUT_INVALID", f"expected SKILL_OUTPUT_INVALID, got {exc.code}"
        else:
            raise AssertionError("expected OrchestratorError(SKILL_OUTPUT_INVALID), nothing raised")
    print("PASS: output-invalid still raises SKILL_OUTPUT_INVALID")


def test_normal_success() -> None:
    """Valid input + valid output -> SUCCESS, output returned + captured."""
    with tempfile.TemporaryDirectory() as tmp:
        o = _fresh_orchestrator(Path(tmp), "success-run")
        o.register_runner("source_intake", lambda env: _good_output())
        out = o.invoke_skill("source_intake", _good_input(Path(tmp)))
        assert out["resolved_evidence_sources"]["evidence_source"] == "offline_documents"
        assert o.last_outputs.get("source_intake") is out
    print("PASS: normal success returns + captures output")


def main() -> None:
    test_input_invalid_not_masked()
    test_output_invalid_still_raises()
    test_normal_success()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
