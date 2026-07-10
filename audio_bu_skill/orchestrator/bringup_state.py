"""Domain-level bring-up state machine for one audio bring-up run.

This is the run-level state diagram already documented and presented to
the user in Audio_BU_Skill.html Sec.06:

    INIT -> SCAFFOLD -> PATCH_APPLIED -> ON_TARGET -> VERIFY -> VERIFIED (terminal)

Any of SCAFFOLD / PATCH_APPLIED / ON_TARGET / VERIFY may fail into TRIAGE,
which either resumes at PATCH_APPLIED with a fix, or escalates to BLOCKED
when the fix needs external input (e.g. an SCMI power-domain index).
BLOCKED resumes at PATCH_APPLIED once the input arrives.

This machine tracks the WHOLE RUN, not one skill invocation — see
orchestrator.skill_state_machine.SkillState for the per-invocation FSM
that audio_bu_orchestrator drives each time it calls source_intake,
triage or codec_driver_porting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BringupState(str, Enum):
    INIT = "INIT"
    SCAFFOLD = "SCAFFOLD"
    PATCH_APPLIED = "PATCH_APPLIED"
    ON_TARGET = "ON_TARGET"
    VERIFY = "VERIFY"
    VERIFIED = "VERIFIED"
    TRIAGE = "TRIAGE"
    BLOCKED = "BLOCKED"


APPROVED_STATES: tuple[str, ...] = tuple(s.value for s in BringupState)
TERMINAL_STATES: set[str] = {BringupState.VERIFIED.value}

# (from, to): entry condition satisfied on success / on the failure branch.
APPROVED_TRANSITIONS: tuple[tuple[str, str], ...] = (
    (BringupState.INIT.value, BringupState.SCAFFOLD.value),           # sources gathered
    (BringupState.INIT.value, BringupState.BLOCKED.value),            # missing source
    (BringupState.SCAFFOLD.value, BringupState.PATCH_APPLIED.value),  # DT generated
    (BringupState.SCAFFOLD.value, BringupState.TRIAGE.value),         # gen error
    (BringupState.PATCH_APPLIED.value, BringupState.ON_TARGET.value), # compiles, flashed
    (BringupState.PATCH_APPLIED.value, BringupState.TRIAGE.value),    # compile fail
    (BringupState.ON_TARGET.value, BringupState.VERIFY.value),        # boots
    (BringupState.ON_TARGET.value, BringupState.TRIAGE.value),        # boot/PAS fail
    (BringupState.VERIFY.value, BringupState.VERIFIED.value),         # aplay/arecord pass
    (BringupState.VERIFY.value, BringupState.TRIAGE.value),           # aplay/arecord fail
    (BringupState.TRIAGE.value, BringupState.PATCH_APPLIED.value),    # fix looped back in
    (BringupState.TRIAGE.value, BringupState.BLOCKED.value),          # needs external input
    (BringupState.BLOCKED.value, BringupState.PATCH_APPLIED.value),   # input arrived, resume
)
APPROVED_TRANSITION_SET: set[tuple[str, str]] = set(APPROVED_TRANSITIONS)

GATE_FOR_FAILURE_SOURCE: dict[str, str] = {
    BringupState.SCAFFOLD.value: "dt_generation",
    BringupState.PATCH_APPLIED.value: "compile",
    BringupState.ON_TARGET.value: "boot_pas",
    BringupState.VERIFY.value: "audio_path",
}


class BringupStateError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class BringupTransitionRecord:
    run_id: str
    from_state: str
    to_state: str
    transition: str
    reason: str
    failed_gate: str | None
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "transition": self.transition,
            "reason": self.reason,
            "failed_gate": self.failed_gate,
            "timestamp": self.timestamp,
        }


def evaluate_bringup_transition(
    *, run_id: str, from_state: str, to_state: str, reason: str,
) -> BringupTransitionRecord:
    from_norm = _normalize_state(from_state)
    to_norm = _normalize_state(to_state)
    pair = (from_norm, to_norm)

    if pair not in APPROVED_TRANSITION_SET:
        raise BringupStateError(
            code="ILLEGAL_BRINGUP_TRANSITION",
            message="requested bring-up transition is not allowed",
            details={
                "transition": f"{from_norm}->{to_norm}",
                "allowed_transitions": [f"{a}->{b}" for a, b in APPROVED_TRANSITIONS],
            },
        )

    failed_gate = GATE_FOR_FAILURE_SOURCE.get(from_norm) if to_norm == BringupState.TRIAGE.value else None

    return BringupTransitionRecord(
        run_id=run_id,
        from_state=from_norm,
        to_state=to_norm,
        transition=f"{from_norm}->{to_norm}",
        reason=reason,
        failed_gate=failed_gate,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def _normalize_state(value: Any) -> str:
    if isinstance(value, BringupState):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise BringupStateError(code="UNKNOWN_BRINGUP_STATE", message="state must be a non-empty string", details={"value": value})
    normalized = value.strip().upper()
    if normalized not in APPROVED_STATES:
        raise BringupStateError(code="UNKNOWN_BRINGUP_STATE", message="unknown bring-up state", details={"value": value})
    return normalized
