"""audio_bu_orchestrator schema + validation_rules enforcement.

Unlike the other three skills, audio_bu_orchestrator has no separate
plain-function runner registered via BringupOrchestrator.register_runner
— it IS the orchestrator (BringupOrchestrator itself drives it). What
this validator checks is the *output* of a run: the persisted
bringup_run_state (i.e. a run_store record, or the envelope shape a
caller wraps around one) against this skill's own validation_rules.
Intended to be called against orchestrator.run_store.load_run(...)'s
record after wrapping it as {"bringup_run_state": record, "evidence": ...}.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.bringup_state import BringupState, GATE_FOR_FAILURE_SOURCE
from orchestrator.schema_validation import SchemaValidationError, load_schema, validate_against

SCHEMA_PATH = Path(__file__).with_name("schema.json")

SKILL_FIT_GATE_STATES = {BringupState.SCAFFOLD.value}


class AudioBuOrchestratorValidationError(SchemaValidationError):
    pass


def validate_input(input_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(input_envelope, schema, schema_key="input_envelope", error_code="AUDIO_BU_ORCHESTRATOR_INPUT_INVALID")


def validate_output(output_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(output_envelope, schema, schema_key="output_envelope", error_code="AUDIO_BU_ORCHESTRATOR_OUTPUT_INVALID")

    run_state = output_envelope["bringup_run_state"]
    history = run_state["bringup_history"]

    # must_enforce_skill_fit_gate_before_scaffold: the run must have gone
    # through INIT before ever reaching SCAFFOLD (i.e. no run starts pre-seeded at SCAFFOLD+).
    reached_scaffold_or_later = any(
        entry["to_state"] in SKILL_FIT_GATE_STATES or entry["from_state"] in SKILL_FIT_GATE_STATES
        for entry in history
    )
    if reached_scaffold_or_later:
        first_entry = history[0]
        if first_entry["from_state"] != BringupState.INIT.value:
            raise AudioBuOrchestratorValidationError(
                code="SKILL_FIT_GATE_SKIPPED",
                message="must_enforce_skill_fit_gate_before_scaffold: run history does not begin at INIT",
                details={"first_transition": first_entry},
            )

    # must_record_state_transition_evidence / must_not_skip_gates_without_evidence
    for entry in history:
        if not entry.get("reason"):
            raise AudioBuOrchestratorValidationError(
                code="TRANSITION_MISSING_REASON",
                message="must_record_state_transition_evidence: a bring-up transition has no recorded reason",
                details={"transition": entry},
            )
        if entry["to_state"] == BringupState.TRIAGE.value:
            expected_gate = GATE_FOR_FAILURE_SOURCE.get(entry["from_state"])
            if entry.get("failed_gate") != expected_gate:
                raise AudioBuOrchestratorValidationError(
                    code="GATE_SKIPPED_WITHOUT_EVIDENCE",
                    message="must_not_skip_gates_without_evidence: TRIAGE transition's failed_gate does not match its from_state's known gate",
                    details={"transition": entry, "expected_failed_gate": expected_gate},
                )

    # must_halt_in_blocked_state_pending_external_input
    if run_state["bringup_state"] == BringupState.BLOCKED.value:
        last_entry = history[-1] if history else None
        if last_entry is None or last_entry["to_state"] != BringupState.BLOCKED.value:
            raise AudioBuOrchestratorValidationError(
                code="BLOCKED_STATE_UNEXPLAINED",
                message="must_halt_in_blocked_state_pending_external_input: run is BLOCKED but history's last entry does not transition into BLOCKED",
                details={},
            )
