"""Generic, outcome-driven bring-up walk shared by every audio target.

This is the target-agnostic half of what used to be hand-typed into
main.py. It hardcodes the *canonical* audio bring-up trajectory —

    INIT -> SCAFFOLD -> PATCH_APPLIED -> ON_TARGET -> VERIFY -> VERIFIED

with the failure branch into TRIAGE and (when a fix needs external input)
BLOCKED — and drives it by branching on **runner output + what the target
case reports as observed**, never on the target's identity. Every string
of judgment (root-cause prose, cited evidence, proposed fix, per-gate
reasons) lives in the per-target BringupCase, not here.

The walk is idempotent and resumable: it reads current_bringup_state()
and only advances from there, so re-running a BLOCKED or VERIFIED run is a
no-op. It stops at a terminal state (VERIFIED) or at BLOCKED (which needs
external input to resume, not something the walk can supply).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Any, Callable

from orchestrator import run_store
from orchestrator.bringup_state import BringupState, TERMINAL_STATES
from orchestrator.driver import BringupOrchestrator, OrchestratorError

# The evidence-source policies source_intake understands. ipcat_first tries the
# ipcat root and silently falls back to offline_documents when it is empty/absent.
EVIDENCE_SOURCES: tuple[str, ...] = ("ipcat", "offline_documents", "both", "ipcat_first")


@dataclass
class BringupCase:
    """All per-target, human-authored content for one bring-up run.

    The engine (this walk + the orchestrator) is generic; this object is
    where a specific SoC's facts and analyst judgment are declared. Fields
    that describe a phase that a given target never reaches are left at
    their defaults.
    """

    # identity
    target_soc: str
    nearest_target: str
    run_id: str

    # provenance / lineage
    case_version: str = "0.1.0"
    inherit_from: str = ""                              # parent target name, resolved by main.load_case
    donor_targets: dict[str, str] = field(default_factory=dict)  # role -> target_name from QGenie nearest_targets

    # source_intake (INIT -> SCAFFOLD)
    power_model_source: str = ""
    evidence_source: str = "ipcat_first"               # default; CLI may override
    evidence_roots: dict[str, str] = field(default_factory=dict)
    source_intake_paths: dict[str, str] = field(default_factory=dict)  # optional explicit *_path overrides
    scaffold_reason: str = "evidence sources resolved"

    # codec_driver_porting (SCAFFOLD -> PATCH_APPLIED, or -> TRIAGE if it blocks)
    kernel_source_path: str = ""
    codec_part_numbers: list[str] = field(default_factory=list)
    codec_verdicts: dict[str, Any] = field(default_factory=dict)
    patch_reason: str = "DT scaffolding landed and builds clean"

    # audio_topology (optional; populated by target_onboarding's QGenie analysis
    # via the Onboarding Accuracy Upgrade collectors). Preserves the richer
    # topology (amplifiers, speakers, mics, SoundWire, LPASS/ADSP/AudioReach/
    # GPR/APM, graded power-model status, candidate FROMLIST patch series, pin
    # cross-check verdicts) that codec_part_numbers/codec_verdicts alone cannot
    # express. Additive and optional: defaults to {} so every existing target
    # (e.g. nord-iq10) that never sets it is unaffected; merge_cases's generic
    # dict-field merge already handles it key-wise like codec_verdicts.
    audio_topology: dict[str, Any] = field(default_factory=dict)

    # PATCH_APPLIED -> ON_TARGET when there is no compile/DT blocker
    compile_reason: str = "compiles clean, flashed to target"

    # TRIAGE: present iff this target hit a compile/DT blocker worth diagnosing.
    #   {"failed_gate": str, "gate_evidence": str, "diagnosis": {...}}
    triage_input: dict[str, Any] | None = None
    blocked_reason: str = "fix needs external input; halting with reasoning on record"
    triage_resolved_reason: str = "fix applied, looping back to PATCH_APPLIED"

    # blocker taxonomy (structured; used by run_manifest for reporting when BLOCKED)
    blocked_category: str = ""      # e.g. external_team_input | missing_firmware | missing_driver | ...
    blocked_owner: str = ""         # e.g. power-team | audio-fw | self
    expected_unblock_signal: str = ""

    # ON_TARGET -> VERIFY : {"passed": bool, "reason": str}
    boot_outcome: dict[str, Any] | None = None
    # VERIFY -> VERIFIED : {"passed": bool, "reason": str}
    audio_outcome: dict[str, Any] | None = None


def merge_cases(parent: BringupCase, child: BringupCase) -> BringupCase:
    """Deep-merge ``child`` over ``parent`` into a new BringupCase.

    Child wins on every field it sets to a non-default value; dict fields are
    merged key-wise (child keys override parent keys) so a child can override
    one codec verdict / one evidence root without restating the rest. Neither
    input is mutated. ``inherit_from`` is cleared on the result (already resolved).
    """
    defaults = BringupCase(target_soc="_", nearest_target="_", run_id="_")
    merged: dict[str, Any] = {}
    for f in dataclass_fields(BringupCase):
        name = f.name
        parent_val = getattr(parent, name)
        child_val = getattr(child, name)
        default_val = getattr(defaults, name)
        if isinstance(parent_val, dict) and isinstance(child_val, dict):
            merged[name] = {**parent_val, **child_val}
        elif child_val != default_val and child_val not in ("", None, [], {}):
            merged[name] = child_val          # child explicitly set a meaningful value
        else:
            merged[name] = parent_val         # child left it default/empty -> inherit parent
    merged["inherit_from"] = ""
    return BringupCase(**merged)


def validate_case(case: BringupCase, *, target: str) -> None:
    """Fail fast on a resolved case before any run touches the state store.

    Raises OrchestratorError(code="CASE_INVALID") on the first problem found.
    """
    problems: list[str] = []
    for name in ("target_soc", "nearest_target", "run_id"):
        if not str(getattr(case, name) or "").strip():
            problems.append(f"{name} must be a non-empty string")

    if case.evidence_source not in EVIDENCE_SOURCES:
        problems.append(f"evidence_source {case.evidence_source!r} not in {list(EVIDENCE_SOURCES)}")

    # run_id must encode the SoC or target name so two targets can't collide on
    # state/<run_id>.json (this replaces the old inline guard in main.py).
    rid = case.run_id.lower()
    if case.target_soc and target and case.target_soc.lower() not in rid and target.lower() not in rid:
        problems.append(
            f"run_id {case.run_id!r} does not encode target_soc {case.target_soc!r} or target {target!r} "
            "(needed so state/<run_id>.json cannot collide between targets)"
        )

    if case.triage_input is not None:
        if not case.triage_input.get("failed_gate"):
            problems.append("triage_input present but missing 'failed_gate'")
        if not case.triage_input.get("diagnosis"):
            problems.append("triage_input present but missing 'diagnosis'")

    if problems:
        raise OrchestratorError(
            code="CASE_INVALID",
            message="target case failed validation",
            details={"target": target, "run_id": case.run_id, "problems": problems},
        )


def run_bringup(
    orchestrator: BringupOrchestrator,
    workspace_context: dict[str, Any],
    case: BringupCase,
    *,
    on_event: Callable[[str], None] | None = None,
) -> str:
    """Advance ``case``'s run as far as its observed outcomes allow.

    Returns the bring-up state the run settles at (VERIFIED, BLOCKED, or
    wherever a missing/ambiguous case outcome halts it).
    """
    emit = on_event or (lambda _msg: None)

    while True:
        state = orchestrator.current_bringup_state()
        if state in TERMINAL_STATES or state == BringupState.BLOCKED.value:
            return state
        advanced = _advance_one(orchestrator, workspace_context, case, state, emit)
        if not advanced:
            return orchestrator.current_bringup_state()


def _advance_one(
    orchestrator: BringupOrchestrator,
    workspace_context: dict[str, Any],
    case: BringupCase,
    state: str,
    emit: Callable[[str], None],
) -> bool:
    if state == BringupState.INIT.value:
        orchestrator.invoke_skill("source_intake", _source_intake_envelope(workspace_context, case))
        orchestrator.transition_bringup(to_state=BringupState.SCAFFOLD.value, reason=case.scaffold_reason)
        emit("source_intake resolved -> SCAFFOLD")
        return True

    if state == BringupState.SCAFFOLD.value:
        codec_output = orchestrator.invoke_skill("codec_driver_porting", _codec_envelope(workspace_context, case))
        if codec_output["codec_driver_availability"]["blocks_dt_generation"]:
            if case.triage_input is None:
                raise OrchestratorError(
                    code="CASE_INCOMPLETE",
                    message="codec_driver_porting blocks DT generation but case supplies no triage_input",
                    details={"run_id": case.run_id},
                )
            orchestrator.transition_bringup(
                to_state=BringupState.TRIAGE.value,
                reason="codec driver unavailable/needs port; DT generation blocked",
            )
            emit("codec drivers block DT generation -> TRIAGE")
        else:
            orchestrator.transition_bringup(to_state=BringupState.PATCH_APPLIED.value, reason=case.patch_reason)
            emit("codec drivers present -> PATCH_APPLIED")
        return True

    if state == BringupState.PATCH_APPLIED.value:
        if case.triage_input is not None and not _triage_already_ran(orchestrator):
            orchestrator.transition_bringup(
                to_state=BringupState.TRIAGE.value,
                reason=case.triage_input.get("transition_reason", "gate failed; entering triage"),
            )
            emit("blocker at PATCH_APPLIED gate -> TRIAGE")
        else:
            orchestrator.transition_bringup(to_state=BringupState.ON_TARGET.value, reason=case.compile_reason)
            emit("no blocker -> ON_TARGET")
        return True

    if state == BringupState.TRIAGE.value:
        triage_output = orchestrator.invoke_skill("triage", _triage_envelope(workspace_context, case))
        if triage_output["unresolved"] or triage_output["blocked_on_external_input"]:
            orchestrator.transition_bringup(to_state=BringupState.BLOCKED.value, reason=case.blocked_reason)
            emit("triage needs external input -> BLOCKED")
        else:
            orchestrator.transition_bringup(to_state=BringupState.PATCH_APPLIED.value, reason=case.triage_resolved_reason)
            emit("triage resolved -> PATCH_APPLIED")
        return True

    if state == BringupState.ON_TARGET.value:
        outcome = _require_outcome(case.boot_outcome, "boot_outcome", case.run_id)
        if outcome["passed"]:
            orchestrator.transition_bringup(to_state=BringupState.VERIFY.value, reason=outcome["reason"])
            emit("boot/PAS passed -> VERIFY")
        else:
            orchestrator.transition_bringup(to_state=BringupState.TRIAGE.value, reason=outcome["reason"])
            emit("boot/PAS failed -> TRIAGE")
        return True

    if state == BringupState.VERIFY.value:
        outcome = _require_outcome(case.audio_outcome, "audio_outcome", case.run_id)
        if outcome["passed"]:
            orchestrator.transition_bringup(to_state=BringupState.VERIFIED.value, reason=outcome["reason"])
            emit("aplay/arecord passed -> VERIFIED")
        else:
            orchestrator.transition_bringup(to_state=BringupState.TRIAGE.value, reason=outcome["reason"])
            emit("aplay/arecord failed -> TRIAGE")
        return True

    return False


def _triage_already_ran(orchestrator: BringupOrchestrator) -> bool:
    record = run_store.load_run(orchestrator.workspace_root, orchestrator.run_id)
    return bool(record) and "triage" in record.get("skill_invocations", {})


def _require_outcome(outcome: dict[str, Any] | None, field_name: str, run_id: str) -> dict[str, Any]:
    if not isinstance(outcome, dict) or "passed" not in outcome or "reason" not in outcome:
        raise OrchestratorError(
            code="CASE_INCOMPLETE",
            message=f"case reached a gate needing {field_name} but it is missing/malformed "
                    f"(expected {{'passed': bool, 'reason': str}})",
            details={"run_id": run_id, "field": field_name},
        )
    return outcome


def _source_intake_envelope(workspace_context: dict[str, Any], case: BringupCase) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "workspace_context": workspace_context,
        "target_soc": case.target_soc,
        "run_id": case.run_id,
        "evidence_roots": case.evidence_roots,
        "decision": {
            "evidence_source": case.evidence_source,
            "power_model_source": case.power_model_source,
        },
    }
    envelope.update(case.source_intake_paths)  # optional explicit *_path overrides
    return envelope


def _codec_envelope(workspace_context: dict[str, Any], case: BringupCase) -> dict[str, Any]:
    # kernel_source resolution: workspace_context (from --kernel-source, set by
    # main.py) wins; otherwise the case's own kernel_source_path.
    kernel_source_path = workspace_context.get("kernel_source") or case.kernel_source_path
    return {
        "workspace_context": workspace_context,
        "run_id": case.run_id,
        "codec_part_numbers": case.codec_part_numbers,
        "kernel_source_path": kernel_source_path,
        "verdicts": case.codec_verdicts,
    }


def _triage_envelope(workspace_context: dict[str, Any], case: BringupCase) -> dict[str, Any]:
    triage_input = case.triage_input or {}
    return {
        "workspace_context": workspace_context,
        "run_id": case.run_id,
        "failed_gate": triage_input.get("failed_gate"),
        "gate_evidence": triage_input.get("gate_evidence"),
        "diagnosis": triage_input.get("diagnosis"),
    }
