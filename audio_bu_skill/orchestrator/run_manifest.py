"""Run manifest, fingerprints, and audit artifacts for one bring-up run.

This module turns a completed (or resumed) run into a durable, reproducible
record. It is the Section-12 "Replayability and Repeatability" layer:

  * compute_fingerprints() hashes every input whose change should be visible as
    drift — the kernel commit, each evidence file, the target's case.py, each
    skill's declared version, and the framework files (workspace.yaml + every
    skill.yaml / schema.json / validator.py).
  * build_manifest() assembles run_manifest.json from the persisted state record
    plus those fingerprints plus a lightweight per-run analytics block (NOT a
    fleet aggregator — just the fields a future dashboard would roll up).
  * write_artifacts() materializes artifacts/<run_id>/ (manifest.json, state.json,
    evidence_refs.json, skill_outputs.json, timeline.md, timeline.json, and a
    blocker_report.md when the run halted at BLOCKED).

Everything is derived from on-disk state + on-disk inputs, so it works the same
on a fresh run and on a resumed one, and --rerun can recompute fingerprints
without invoking any skill.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from orchestrator.runners.source_intake_runner import discover_evidence


class RunManifestError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def artifacts_dir(workspace_root: str | Path, run_id: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    if ".." in run_id or "/" in run_id or "\\" in run_id:
        raise RunManifestError(code="PATH_TRAVERSAL", message="run_id contains path traversal or separators",
                               details={"run_id": run_id})
    return root / "artifacts" / run_id


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# fingerprints
# --------------------------------------------------------------------------- #
def _kernel_commit(kernel_source: str | None) -> str | None:
    if not kernel_source:
        return None
    ks = Path(kernel_source)
    try:
        result = subprocess.run(
            ["git", "-C", str(ks), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    # Fallback: hash .git/HEAD (records ref movement even when git is unavailable).
    head = ks / ".git" / "HEAD"
    if head.is_file():
        return "head:" + _sha256_text(head.read_text(encoding="utf-8"))
    return None


def _framework_fingerprints(workspace_root: Path, skills_root: Path) -> dict[str, str]:
    """Hash workspace.yaml + each skill's skill.yaml / schema.json / validator.py.

    Keyed by path relative to workspace_root so drift output is readable.
    """
    out: dict[str, str] = {}
    ws_manifest = workspace_root / "workspace.yaml"
    if ws_manifest.is_file():
        out["workspace.yaml"] = _sha256_file(ws_manifest)
    if skills_root.is_dir():
        for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
            for fname in ("skill.yaml", "schema.json", "validator.py"):
                f = skill_dir / fname
                if f.is_file():
                    rel = f.relative_to(workspace_root) if _is_relative_to(f, workspace_root) else f
                    out[str(rel)] = _sha256_file(f)
    return out


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def compute_fingerprints(
    *,
    workspace_context: dict[str, Any],
    case: Any,
    target: str,
    targets_root: str | Path,
    skills_root: str | Path,
    skill_registry: dict[str, Any],
) -> dict[str, Any]:
    """Fingerprint every input whose change should surface in --rerun drift."""
    workspace_root = Path(workspace_context["workspace_root"])
    kernel_source = workspace_context.get("kernel_source") or getattr(case, "kernel_source_path", "")

    # evidence: hash the exact files the case's policy resolves to (pure, reused
    # from the runner so a fresh run and a --rerun agree).
    discovery = discover_evidence(workspace_root, getattr(case, "evidence_roots", {}) or {}, case.evidence_source)
    evidence: dict[str, str] = {}
    for p in discovery["paths"]:
        fp = Path(p)
        if fp.is_file():
            key = str(fp.relative_to(workspace_root)) if _is_relative_to(fp, workspace_root) else str(fp)
            evidence[key] = _sha256_file(fp)

    case_path = Path(targets_root) / target / "case.py"
    case_sha = _sha256_file(case_path) if case_path.is_file() else None

    skill_versions = {sid: manifest.get("version") for sid, manifest in sorted(skill_registry.items())}

    return {
        "kernel_source": str(kernel_source) if kernel_source else None,
        "kernel_commit": _kernel_commit(str(kernel_source) if kernel_source else None),
        "evidence": evidence,
        "case_sha256": case_sha,
        "skill_versions": skill_versions,
        "framework": _framework_fingerprints(workspace_root, Path(skills_root)),
    }


def diff_fingerprints(recorded: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return a flat list of human-readable 'key: old -> new' drift lines."""
    drift: list[str] = []

    def _cmp(prefix: str, old: Any, new: Any) -> None:
        if isinstance(old, dict) or isinstance(new, dict):
            old = old if isinstance(old, dict) else {}
            new = new if isinstance(new, dict) else {}
            for key in sorted(set(old) | set(new)):
                _cmp(f"{prefix}[{key}]", old.get(key), new.get(key))
        elif old != new:
            drift.append(f"{prefix}: {old} -> {new}")

    for top in sorted(set(recorded) | set(current)):
        _cmp(top, recorded.get(top), current.get(top))
    return drift


# --------------------------------------------------------------------------- #
# manifest + analytics
# --------------------------------------------------------------------------- #
def build_manifest(
    *,
    run_id: str,
    target: str,
    case: Any,
    workspace_context: dict[str, Any],
    state_record: dict[str, Any],
    fingerprints: dict[str, Any],
    evidence_refs: list[str],
    generated_artifact_count: int,
) -> dict[str, Any]:
    history = state_record.get("bringup_history", [])
    final_state = state_record.get("bringup_state")
    started_at = history[0]["timestamp"] if history else None
    ended_at = history[-1]["timestamp"] if history else None

    skill_invocations = state_record.get("skill_invocations", {})
    executed_skills = sorted(skill_invocations.keys())
    skill_states = {sid: inv.get("skill_state") for sid, inv in skill_invocations.items()}

    transitions = [
        {"from": t["from_state"], "to": t["to_state"], "reason": t.get("reason"),
         "failed_gate": t.get("failed_gate"), "timestamp": t.get("timestamp")}
        for t in history
    ]

    blocker_count = 1 if final_state == "BLOCKED" else 0
    analytics = {
        "evidence_count": len(evidence_refs),
        "skill_count": len(executed_skills),
        "blocker_count": blocker_count,
        "final_state": final_state,
        "blocked_category": getattr(case, "blocked_category", "") if blocker_count else "",
        "blocked_owner": getattr(case, "blocked_owner", "") if blocker_count else "",
        "generated_artifact_count": generated_artifact_count,
    }

    return {
        "run_id": run_id,
        "target": target,
        "target_soc": case.target_soc,
        "nearest_target": case.nearest_target,
        "kernel_source": workspace_context.get("kernel_source") or getattr(case, "kernel_source_path", ""),
        "evidence_source": case.evidence_source,
        "case_version": getattr(case, "case_version", ""),
        "inherit_from": getattr(case, "inherit_from", ""),
        "started_at": started_at,
        "ended_at": ended_at,
        "final_state": final_state,
        "executed_skills": executed_skills,
        "skill_states": skill_states,
        "state_transitions": transitions,
        "fingerprints": fingerprints,
        "analytics": analytics,
    }


# --------------------------------------------------------------------------- #
# artifact writers
# --------------------------------------------------------------------------- #
def _render_timeline_md(manifest: dict[str, Any]) -> str:
    lines = [
        f"# Timeline — {manifest['run_id']}",
        "",
        f"- **target:** {manifest['target']} ({manifest['target_soc']})",
        f"- **final state:** {manifest['final_state']}",
        f"- **started:** {manifest['started_at']}   **ended:** {manifest['ended_at']}",
        f"- **evidence source:** {manifest['evidence_source']}",
        "",
        "## Transitions",
        "",
        "| # | from | to | gate | reason | timestamp |",
        "|---|------|----|------|--------|-----------|",
    ]
    for i, t in enumerate(manifest["state_transitions"], 1):
        reason = (t.get("reason") or "").replace("|", "\\|")
        lines.append(
            f"| {i} | {t['from']} | {t['to']} | {t.get('failed_gate') or ''} | {reason} | {t.get('timestamp') or ''} |"
        )
    return "\n".join(lines) + "\n"


def _render_blocker_report_md(manifest: dict[str, Any], case: Any, skill_outputs: dict[str, Any]) -> str:
    triage_out = (skill_outputs.get("triage") or {}).get("triage_diagnosis", {})
    diagnosis = (case.triage_input or {}).get("diagnosis", {}) if case.triage_input else {}
    cited = diagnosis.get("cited_evidence", []) or []
    lines = [
        f"# Blocker Report — {manifest['run_id']}",
        "",
        f"- **target:** {manifest['target']} ({manifest['target_soc']})",
        f"- **category:** {getattr(case, 'blocked_category', '') or 'unspecified'}",
        f"- **owner:** {getattr(case, 'blocked_owner', '') or 'unspecified'}",
        f"- **expected unblock signal:** {getattr(case, 'expected_unblock_signal', '') or 'unspecified'}",
        "",
        "## Root cause",
        "",
        diagnosis.get("root_cause") or triage_out.get("root_cause") or "(none recorded)",
        "",
        "## Proposed fix",
        "",
        diagnosis.get("proposed_fix") or triage_out.get("proposed_fix") or "(none recorded)",
        "",
        "## Needs external input",
        "",
        str(diagnosis.get("needs_external_input") or triage_out.get("needs_external_input") or "(none recorded)"),
        "",
        "## Cited evidence",
        "",
    ]
    lines.extend(f"- {c}" for c in cited) if cited else lines.append("- (none cited)")
    return "\n".join(lines) + "\n"


def write_artifacts(
    *,
    workspace_root: str | Path,
    run_id: str,
    manifest: dict[str, Any],
    state_record: dict[str, Any],
    evidence_refs: list[str],
    evidence_provenance: dict[str, Any] | None,
    skill_outputs: dict[str, Any],
    case: Any,
) -> dict[str, Any]:
    """Write artifacts/<run_id>/ and return {"dir": str, "files": [...]}.

    Idempotent: overwrites each file so a resumed run refreshes its record.
    """
    out_dir = artifacts_dir(workspace_root, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def _write(name: str, text: str) -> None:
        (out_dir / name).write_text(text, encoding="utf-8")
        written.append(name)

    _write("state.json", json.dumps(state_record, indent=2, sort_keys=True) + "\n")
    _write("evidence_refs.json", json.dumps(
        {"evidence_refs": evidence_refs,
         "provenance": evidence_provenance,
         "fingerprints": manifest["fingerprints"]["evidence"]},
        indent=2, sort_keys=True) + "\n")
    _write("skill_outputs.json", json.dumps(skill_outputs, indent=2, sort_keys=True) + "\n")
    _write("timeline.md", _render_timeline_md(manifest))
    _write("timeline.json", json.dumps(
        {"run_id": run_id, "final_state": manifest["final_state"],
         "started_at": manifest["started_at"], "ended_at": manifest["ended_at"],
         "transitions": manifest["state_transitions"]},
        indent=2, sort_keys=True) + "\n")
    if manifest["final_state"] == "BLOCKED":
        _write("blocker_report.md", _render_blocker_report_md(manifest, case, skill_outputs))

    # manifest last, so generated_artifact_count reflects everything else written
    # (+1 for manifest.json itself).
    manifest["analytics"]["generated_artifact_count"] = len(written) + 1
    _write("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {"dir": str(out_dir), "files": written}


def load_manifest(workspace_root: str | Path, run_id: str) -> dict[str, Any]:
    path = artifacts_dir(workspace_root, run_id) / "manifest.json"
    if not path.is_file():
        raise RunManifestError(code="ARTIFACTS_NOT_FOUND",
                               message="no manifest.json for this run_id; run it first",
                               details={"run_id": run_id, "path": str(path)})
    return json.loads(path.read_text(encoding="utf-8"))


def load_skill_outputs(workspace_root: str | Path, run_id: str) -> dict[str, Any]:
    """Return a prior run's recorded skill_outputs.json, or {} if none exists.

    Lets a resume layer this session's fresh invocations over the previously
    recorded ones, instead of clobbering them with an empty set when the walk
    was a no-op (already-settled run → no skills re-ran).
    """
    path = artifacts_dir(workspace_root, run_id) / "skill_outputs.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
