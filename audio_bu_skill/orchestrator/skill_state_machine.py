"""Per-skill-invocation lifecycle state machine.

This models ONE skill invocation's lifecycle (did source_intake's single
run succeed / fail / get approved). It is intentionally the same shape as
the laei "Sprint-1 skill lifecycle" this project reviewed and decided to
reuse: PENDING -> READY -> RUNNING -> VALIDATING -> SUCCESS -> APPROVED,
with FAILED/RETRY/SKIPPED branches. It is NOT the domain-level bring-up
state machine (see orchestrator.bringup_state for that) — the two must
not be conflated. An orchestrator run drives one bringup_state machine
across many skill invocations, each of which is tracked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SkillState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    SKIPPED = "SKIPPED"
    APPROVED = "APPROVED"


APPROVED_STATES: tuple[str, ...] = tuple(state.value for state in SkillState)

APPROVED_TRANSITIONS: tuple[tuple[str, str], ...] = (
    (SkillState.PENDING.value, SkillState.READY.value),
    (SkillState.PENDING.value, SkillState.SKIPPED.value),
    (SkillState.READY.value, SkillState.RUNNING.value),
    (SkillState.READY.value, SkillState.FAILED.value),
    (SkillState.RUNNING.value, SkillState.VALIDATING.value),
    (SkillState.RUNNING.value, SkillState.FAILED.value),
    (SkillState.VALIDATING.value, SkillState.SUCCESS.value),
    (SkillState.VALIDATING.value, SkillState.FAILED.value),
    (SkillState.SUCCESS.value, SkillState.APPROVED.value),
    (SkillState.SUCCESS.value, SkillState.FAILED.value),
    (SkillState.FAILED.value, SkillState.RETRY.value),
    (SkillState.RETRY.value, SkillState.READY.value),
)

APPROVED_TRANSITION_SET: set[tuple[str, str]] = set(APPROVED_TRANSITIONS)
TERMINAL_STATES: set[str] = {SkillState.FAILED.value, SkillState.SKIPPED.value, SkillState.APPROVED.value}


class StateMachineError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class StateTransitionRecord:
    skill_id: str
    run_id: str
    from_state: str
    to_state: str
    transition: str
    reason: str
    failure: dict[str, Any] | None
    timestamp: str
    requires_validated_output: bool = False
    requires_persisted_artifacts: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "run_id": self.run_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "transition": self.transition,
            "reason": self.reason,
            "failure": self.failure,
            "requires_validated_output": self.requires_validated_output,
            "requires_persisted_artifacts": self.requires_persisted_artifacts,
            "timestamp": self.timestamp,
        }


def evaluate_state_transition(
    *,
    skill_id: str,
    run_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> StateTransitionRecord:
    """Evaluate one transition request; raises StateMachineError if illegal or preconditions unmet."""
    from_norm = _normalize_state(from_state)
    to_norm = _normalize_state(to_state)
    pair = (from_norm, to_norm)

    if pair not in APPROVED_TRANSITION_SET:
        raise StateMachineError(
            code="ILLEGAL_TRANSITION",
            message="requested transition is not allowed",
            details={
                "transition": f"{from_norm}->{to_norm}",
                "allowed_transitions": [f"{a}->{b}" for a, b in APPROVED_TRANSITIONS],
            },
        )

    meta = dict(metadata or {})
    failure_payload = _evaluate_preconditions(from_norm, to_norm, meta)

    return StateTransitionRecord(
        skill_id=skill_id,
        run_id=run_id,
        from_state=from_norm,
        to_state=to_norm,
        transition=f"{from_norm}->{to_norm}",
        reason=reason,
        failure=failure_payload,
        requires_validated_output=pair
        in {(SkillState.VALIDATING.value, SkillState.SUCCESS.value), (SkillState.SUCCESS.value, SkillState.APPROVED.value)},
        requires_persisted_artifacts=pair == (SkillState.SUCCESS.value, SkillState.APPROVED.value),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def _normalize_state(value: Any) -> str:
    if isinstance(value, SkillState):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise StateMachineError(code="UNKNOWN_STATE", message="state must be a non-empty string", details={"value": value})
    normalized = value.strip().upper()
    if normalized not in APPROVED_STATES:
        raise StateMachineError(code="UNKNOWN_STATE", message="unknown state value", details={"value": value})
    return normalized


def _evaluate_preconditions(from_state: str, to_state: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
    pair = (from_state, to_state)

    if pair == (SkillState.VALIDATING.value, SkillState.SUCCESS.value):
        validation = metadata.get("validation")
        if not isinstance(validation, dict) or validation.get("passed") is not True:
            raise StateMachineError(
                code="VALIDATION_NOT_PASSED",
                message="VALIDATING->SUCCESS requires validation.passed=true",
                details={"validation": validation},
            )
        evidence_refs = validation.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise StateMachineError(
                code="MISSING_VALIDATION_EVIDENCE",
                message="VALIDATING->SUCCESS requires non-empty validation.evidence_refs",
                details={"validation": validation},
            )
        return None

    if pair == (SkillState.SUCCESS.value, SkillState.APPROVED.value):
        artifacts = metadata.get("persisted_artifacts")
        valid = isinstance(artifacts, list) and any(isinstance(a, str) and a.strip() for a in artifacts)
        if not valid and not _approval_bypass_enabled(metadata):
            raise StateMachineError(
                code="APPROVAL_PRECONDITION_FAILED",
                message="SUCCESS->APPROVED requires persisted_artifacts or explicit policy bypass",
                details={},
            )
        return None

    if pair == (SkillState.SUCCESS.value, SkillState.FAILED.value):
        human_review = metadata.get("human_review")
        if not isinstance(human_review, dict) or human_review.get("rejected") is not True or not human_review.get("reason"):
            raise StateMachineError(
                code="MISSING_HUMAN_REVIEW_REJECTION",
                message="SUCCESS->FAILED requires human_review={rejected: true, reason: ...}",
                details={"human_review": human_review},
            )
        return {"code": "HUMAN_REVIEW_REJECTED", "message": human_review["reason"], "details": {}}

    if pair == (SkillState.FAILED.value, SkillState.RETRY.value):
        retry = metadata.get("retry")
        if not isinstance(retry, dict):
            raise StateMachineError(code="RETRY_NOT_ALLOWED", message="FAILED->RETRY requires retry metadata", details={})
        return None

    if to_state == SkillState.FAILED.value:
        failure = metadata.get("failure")
        if not isinstance(failure, dict) or not failure.get("code") or not failure.get("message"):
            raise StateMachineError(
                code="MISSING_FAILURE_REASON",
                message="transition to FAILED requires failure={code, message}",
                details={},
            )
        return {"code": failure["code"], "message": failure["message"], "details": failure.get("details", {})}

    return None


def _approval_bypass_enabled(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("policy")
    return isinstance(policy, dict) and policy.get("review_required") is False and policy.get("output_accepted_by_policy") is True
