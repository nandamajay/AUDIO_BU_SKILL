"""audio_bu_orchestrator's own logic: the domain state machine driver.

This module is deliberately NOT laei's pipeline_vertical_slice.py fixture
executor. It is our own thin orchestrator loop, as decided when reviewing
AURA/laei: load/validate the 4 skill manifests, drive our own bringup
state machine, and call plain-function runners (interactive/judgment
based) for source_intake / triage / codec_driver_porting rather than a
run_fixture(input_envelope) contract.

Deterministic steps (DT generation, dtbs_check, flashing, aplay/arecord)
are NOT modeled as skills here — the orchestrator runs them directly (or,
in this repo, treats their already-observed outcome as an input) per the
skill-decomposition principle: skills exist only where judgment or
interactive decision-making is needed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from orchestrator import bringup_state, run_store, skill_state_machine
from orchestrator.logger_json import append_log_event
from orchestrator.loader_skill_manifest import load_skill_registry
from orchestrator.schema_validation import SchemaValidationError

SkillRunner = Callable[[dict[str, Any]], dict[str, Any]]


def _load_skill_validator(manifest: dict[str, Any]) -> ModuleType | None:
    """Dynamically import <skill_directory>/validator.py, keyed off the manifest path.

    skills/ is deliberately not a Python package (each skill directory is a
    self-contained unit, not an importable submodule tree), so this loads
    validator.py by file path instead of via a normal import statement.
    """
    validator_path = Path(manifest["manifest_path"]).with_name("validator.py")
    if not validator_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"skill_validator_{manifest['skill_id']}", validator_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class BringupOrchestrator:
    """Drives one bring-up run's domain state machine, delegating to skill runners on demand."""

    def __init__(self, *, workspace_root: str | Path, skills_root: str | Path, run_id: str):
        self.workspace_root = str(Path(workspace_root).expanduser().resolve())
        self.run_id = run_id
        registry = load_skill_registry(skills_root)
        if registry["validation_status"] != "valid":
            raise OrchestratorError(code="INVALID_SKILL_REGISTRY", message="skill manifests failed validation",
                                     details={"errors": registry["errors"]})
        self.skill_registry = registry["skills"]
        self._runners: dict[str, SkillRunner] = {}
        # Last validated output per skill this session — consumed by run_manifest
        # to write artifacts/<run_id>/skill_outputs.json without re-invoking.
        self.last_outputs: dict[str, Any] = {}
        self._validators: dict[str, ModuleType | None] = {
            skill_id: _load_skill_validator(manifest) for skill_id, manifest in self.skill_registry.items()
        }

    def register_runner(self, skill_id: str, runner: SkillRunner) -> None:
        if skill_id not in self.skill_registry:
            raise OrchestratorError(code="UNKNOWN_SKILL", message="no manifest for this skill_id",
                                     details={"skill_id": skill_id})
        self._runners[skill_id] = runner

    def start_run(self, *, target_soc: str, nearest_target: str) -> dict[str, Any]:
        record = run_store.init_run(self.workspace_root, self.run_id, target_soc=target_soc, nearest_target=nearest_target)
        self._log(event_type="run_started", status="running",
                   message=f"bring-up run started for {target_soc} (nearest_target={nearest_target})")
        return record

    def resume_run(self) -> dict[str, Any]:
        record = run_store.load_run(self.workspace_root, self.run_id)
        if record is None:
            raise OrchestratorError(code="RUN_NOT_FOUND", message="no persisted state for this run_id",
                                     details={"run_id": self.run_id})
        return record

    def current_bringup_state(self) -> str:
        record = run_store.load_run(self.workspace_root, self.run_id)
        if record is None:
            raise OrchestratorError(code="RUN_NOT_FOUND", message="no persisted state for this run_id",
                                     details={"run_id": self.run_id})
        return record["bringup_state"]

    def transition_bringup(self, *, to_state: str, reason: str) -> dict[str, Any]:
        """Advance the domain state machine and persist + log the transition."""
        from_state = self.current_bringup_state()
        transition = bringup_state.evaluate_bringup_transition(
            run_id=self.run_id, from_state=from_state, to_state=to_state, reason=reason,
        )
        record = run_store.save_bringup_transition(self.workspace_root, self.run_id, transition.to_dict())
        self._log(event_type="bringup_transition",
                   status="halted" if transition.to_dict()["to_state"] in ("TRIAGE", "BLOCKED") else "info",
                   message=f"{transition.transition}: {reason}",
                   context={"failed_gate": transition.failed_gate} if transition.failed_gate else {})
        return record

    def invoke_skill(self, skill_id: str, input_envelope: dict[str, Any]) -> dict[str, Any]:
        """Drive skill_id through its per-invocation lifecycle, calling its registered runner."""
        if skill_id not in self._runners:
            raise OrchestratorError(code="NO_RUNNER_REGISTERED", message="no runner registered for this skill_id",
                                     details={"skill_id": skill_id})

        record = run_store.load_run(self.workspace_root, self.run_id)
        invocation = record["skill_invocations"].get(skill_id, {"skill_state": "PENDING"})
        state = invocation["skill_state"]

        def step(to_state: str, reason: str, metadata: dict[str, Any] | None = None):
            nonlocal state
            transition = skill_state_machine.evaluate_state_transition(
                skill_id=skill_id, run_id=self.run_id, from_state=state, to_state=to_state,
                reason=reason, metadata=metadata,
            )
            run_store.save_skill_transition(self.workspace_root, self.run_id, skill_id, transition.to_dict())
            self._log(event_type="skill_transition", status="running", skill_id=skill_id,
                      message=f"{transition.transition}: {reason}")
            state = to_state

        if state in ("RUNNING", "VALIDATING"):
            # invoke_skill() always starts by stepping to READY, but only
            # PENDING->READY and RETRY->READY are legal transitions. A process
            # killed/interrupted while this skill was RUNNING or VALIDATING
            # leaves the persisted skill_state stuck there with no legal path
            # forward on resume. Self-heal via the state machine's own approved
            # ...->FAILED->RETRY->READY chain (no FSM changes) so the
            # interruption is recorded in history, not silently erased or
            # permanently stranding the run.
            step(
                "FAILED", f"resumed run found skill_state={state}; prior attempt was interrupted",
                metadata={"failure": {
                    "code": "INTERRUPTED_RESUME",
                    "message": f"prior attempt left skill_state={state}; process likely killed/interrupted mid-run",
                }},
            )
            step("RETRY", "retrying after interrupted-resume self-heal",
                 metadata={"retry": {"reason": "resumed after interruption"}})

        step("READY", "mandatory inputs satisfied")

        validator = self._validators.get(skill_id)
        if validator is not None:
            try:
                validator.validate_input(input_envelope)
            except SchemaValidationError as exc:
                step("FAILED", "input_envelope failed schema validation", metadata={"failure": exc.to_dict()})
                raise OrchestratorError(code="SKILL_INPUT_INVALID", message=exc.message, details={"skill_id": skill_id, **exc.details}) from exc

        step("RUNNING", "invoking runner")

        try:
            output = self._runners[skill_id](input_envelope)
        except Exception as exc:  # runner-level failure -> FAILED, not a Python traceback bubbling up
            step("FAILED", "runner raised an exception", metadata={"failure": {"code": "RUNNER_EXCEPTION", "message": str(exc)}})
            raise OrchestratorError(code="SKILL_RUNNER_FAILED", message=str(exc), details={"skill_id": skill_id}) from exc

        step("VALIDATING", "runner returned output")

        if validator is not None:
            try:
                validator.validate_output(output)
            except SchemaValidationError as exc:
                step("FAILED", "output failed schema or validation_rules check", metadata={"failure": exc.to_dict()})
                raise OrchestratorError(code="SKILL_OUTPUT_INVALID", message=exc.message, details={"skill_id": skill_id, **exc.details}) from exc

        evidence_refs = output.get("evidence", {}).get("evidence_refs", []) if isinstance(output.get("evidence"), dict) else []
        if self.skill_registry[skill_id]["evidence_required"] and not evidence_refs:
            step("FAILED", "evidence_required but output carries no evidence_refs",
                 metadata={"failure": {"code": "EVIDENCE_REFERENCE_MISSING", "message": "skill output missing evidence_refs"}})
            raise OrchestratorError(code="EVIDENCE_REFERENCE_MISSING", message="skill output missing required evidence",
                                     details={"skill_id": skill_id})

        step("SUCCESS", "output validated", metadata={"validation": {"passed": True, "evidence_refs": evidence_refs}})

        if self.skill_registry[skill_id]["requires_human_review"]:
            self._log(event_type="human_review_pending", status="warning", skill_id=skill_id,
                       message="output awaits human review before APPROVED")
        else:
            step("APPROVED", "no human review required", metadata={"persisted_artifacts": [f"{skill_id}:{self.run_id}"]})

        self.last_outputs[skill_id] = output
        return output

    def _log(self, *, event_type: str, status: str, message: str, skill_id: str | None = None, context: dict[str, Any] | None = None) -> None:
        event: dict[str, Any] = {
            "run_id": self.run_id, "event_type": event_type, "status": status, "message": message,
            "context": context or {},
        }
        if skill_id is not None:
            event["skill_id"] = skill_id
        append_log_event(workspace_root=self.workspace_root, event=event)
