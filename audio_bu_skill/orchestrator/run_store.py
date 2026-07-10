"""Resumable per-run state store.

Persists, under <workspace_root>/state/<run_id>.json, the current
BringupState plus the full transition history and every skill-invocation
lifecycle for that run. This is what makes BLOCKED durable across days:
the orchestrator can be re-invoked in a fresh session and resume exactly
where a run left off, rather than re-deriving state from scratch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RunStoreError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _state_path(workspace_root: str | Path, run_id: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    if ".." in run_id or "/" in run_id or "\\" in run_id:
        raise RunStoreError(code="PATH_TRAVERSAL", message="run_id contains path traversal or separators",
                             details={"run_id": run_id})
    return root / "audio_bu_skill" / "state" / f"{run_id}.json"


def load_run(workspace_root: str | Path, run_id: str) -> dict[str, Any] | None:
    path = _state_path(workspace_root, run_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def init_run(workspace_root: str | Path, run_id: str, *, target_soc: str, nearest_target: str) -> dict[str, Any]:
    path = _state_path(workspace_root, run_id)
    if path.is_file():
        raise RunStoreError(code="RUN_ALREADY_EXISTS", message="a run with this run_id already exists",
                             details={"run_id": run_id, "path": str(path)})

    record = {
        "run_id": run_id,
        "target_soc": target_soc,
        "nearest_target": nearest_target,
        "bringup_state": "INIT",
        "bringup_history": [],
        "skill_invocations": {},
    }
    _save(path, record)
    return record


def save_bringup_transition(workspace_root: str | Path, run_id: str, transition_record: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(workspace_root, run_id)
    record = load_run(workspace_root, run_id)
    if record is None:
        raise RunStoreError(code="RUN_NOT_FOUND", message="run_id has no persisted state; call init_run first",
                             details={"run_id": run_id})

    if record["bringup_state"] != transition_record["from_state"]:
        raise RunStoreError(
            code="STALE_BRINGUP_STATE",
            message="persisted bringup_state does not match the transition's from_state",
            details={"persisted": record["bringup_state"], "from_state": transition_record["from_state"]},
        )

    record["bringup_state"] = transition_record["to_state"]
    record["bringup_history"].append(transition_record)
    _save(path, record)
    return record


def save_skill_transition(workspace_root: str | Path, run_id: str, skill_id: str, transition_record: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(workspace_root, run_id)
    record = load_run(workspace_root, run_id)
    if record is None:
        raise RunStoreError(code="RUN_NOT_FOUND", message="run_id has no persisted state; call init_run first",
                             details={"run_id": run_id})

    invocation = record["skill_invocations"].setdefault(skill_id, {"skill_state": "PENDING", "history": []})
    if invocation["skill_state"] != transition_record["from_state"]:
        raise RunStoreError(
            code="STALE_SKILL_STATE",
            message="persisted skill_state does not match the transition's from_state",
            details={"skill_id": skill_id, "persisted": invocation["skill_state"], "from_state": transition_record["from_state"]},
        )

    invocation["skill_state"] = transition_record["to_state"]
    invocation["history"].append(transition_record)
    _save(path, record)
    return record


def _save(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
