"""triage runner: root-causes a failed bring-up gate from its evidence.

Interactive/judgment skill. The actual root-cause diagnosis is supplied
by the caller via input_envelope["diagnosis"] (a human or an LLM
reasoning over gate_evidence) — this runner validates that the diagnosis
cites the evidence it claims, classifies the failure category against
the known gate taxonomy, and marks the run unresolved (rather than
silently guessing) when no root cause is supplied.
"""

from __future__ import annotations

from typing import Any

KNOWN_FAILURE_CATEGORIES = {
    "dt_generation", "compile", "boot_pas", "audio_path", "binding_review",
}


def run_triage(input_envelope: dict[str, Any]) -> dict[str, Any]:
    run_id = input_envelope["run_id"]
    failed_gate = input_envelope["failed_gate"]
    gate_evidence = input_envelope["gate_evidence"]
    diagnosis = input_envelope.get("diagnosis") or {}

    root_cause = diagnosis.get("root_cause")
    cited_evidence = diagnosis.get("cited_evidence") or []
    proposed_fix = diagnosis.get("proposed_fix")
    failure_category = diagnosis.get("failure_category")
    needs_external_input = diagnosis.get("needs_external_input")

    unresolved = not root_cause or not cited_evidence or failure_category not in KNOWN_FAILURE_CATEGORIES

    # A diagnosis can be fully resolved (root cause understood, fix known in
    # shape) while still being blocked on a concrete external value the fix
    # needs to apply (e.g. an unconfirmed register/index) — that is NOT the
    # same as "unresolved" (no root cause found at all).
    blocked_on_external_input = bool(needs_external_input) and not unresolved

    triage_diagnosis = {
        "run_id": run_id,
        "failed_gate": failed_gate,
        "failure_category": failure_category,
        "root_cause": root_cause,
        "proposed_fix": proposed_fix,
        "unresolved": unresolved,
        "blocked_on_external_input": blocked_on_external_input,
        "needs_external_input": needs_external_input,
        "gate_evidence_summary": gate_evidence if isinstance(gate_evidence, str) else str(gate_evidence)[:500],
    }

    return {
        "triage_diagnosis": triage_diagnosis,
        "evidence": {"evidence_refs": list(cited_evidence)},
        "unresolved": unresolved,
        "blocked_on_external_input": blocked_on_external_input,
    }
