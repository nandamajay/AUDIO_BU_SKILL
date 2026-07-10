"""Structured JSONL append-only logger with secret/raw-content redaction.

Re-implements the sanitization discipline of laei's runtime/logger_json.py
(read in full during the AURA/laei review): forbid raw document content,
redact secret-shaped keys/values, whitelist event keys, guard against log
path traversal outside the workspace root.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
ALLOWED_STATUS = {"pending", "running", "passed", "failed", "halted", "warning", "info"}
ALLOWED_KEYS = {
    "timestamp", "level", "run_id", "skill_id", "event_type",
    "status", "message", "context", "evidence_refs", "error",
}

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_SECRET_KEY_TOKEN_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
)
_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b"),
]
_RAW_TEXT_KEY_PATTERN = re.compile(r"(?i)(raw_document|raw_text|document_text|document_content|datasheet_text)")


class LoggerError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def append_log_event(*, workspace_root: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise LoggerError(code="INVALID_WORKSPACE_ROOT", message="workspace root must exist and be a directory",
                           details={"workspace_root": str(root)})

    normalized = _normalize_event(event)
    sanitized = _sanitize_event(normalized)
    log_path = _resolve_log_path(root, sanitized["run_id"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)

    return {
        "log_path": str(log_path),
        "event_hash_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
        "event": sanitized,
    }


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise LoggerError(code="INVALID_EVENT_RECORD", message="event must be a mapping", details={})

    unknown = sorted(set(event.keys()) - ALLOWED_KEYS)
    if unknown:
        raise LoggerError(code="INVALID_EVENT_RECORD", message="event contains unsupported keys",
                           details={"unsupported_keys": unknown})

    run_id = _require_identifier(event.get("run_id"), "run_id")

    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise LoggerError(code="INVALID_EVENT_RECORD", message="event_type must be a non-empty string", details={})

    status = event.get("status")
    if status not in ALLOWED_STATUS:
        raise LoggerError(code="INVALID_EVENT_RECORD", message="status must be one of approved values",
                           details={"allowed": sorted(ALLOWED_STATUS)})

    level = event.get("level", "INFO")
    if level not in ALLOWED_LEVELS:
        raise LoggerError(code="INVALID_EVENT_RECORD", message="level must be one of approved values",
                           details={"allowed": sorted(ALLOWED_LEVELS)})

    timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    skill_id = event.get("skill_id")
    if skill_id is not None:
        skill_id = _require_identifier(skill_id, "skill_id")

    normalized: dict[str, Any] = {
        "timestamp": timestamp,
        "level": level,
        "run_id": run_id,
        "event_type": event_type,
        "status": status,
        "message": event.get("message"),
        "context": event.get("context", {}),
        "evidence_refs": event.get("evidence_refs", []),
        "error": event.get("error"),
    }
    if skill_id is not None:
        normalized["skill_id"] = skill_id
    return normalized


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: _sanitize_value(value, key) for key, value in event.items()}


def _sanitize_value(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key in sorted(value):
            if _RAW_TEXT_KEY_PATTERN.search(key):
                raise LoggerError(code="RAW_CONTENT_FORBIDDEN", message="raw document content fields are not allowed in logs",
                                   details={"field": key})
            if _SECRET_KEY_TOKEN_PATTERN.search(key):
                sanitized[key] = "[REDACTED]"
                continue
            sanitized[key] = _sanitize_value(value[key], key)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, field_name) for item in value]
    if isinstance(value, str):
        if _looks_like_raw_document(value):
            raise LoggerError(code="RAW_CONTENT_FORBIDDEN", message="raw document-like text is not allowed in logs",
                               details={"field": field_name})
        if _looks_like_secret_value(value):
            return "[REDACTED]"
        return value
    return value


def _resolve_log_path(workspace_root: Path, run_id: str) -> Path:
    candidate = (workspace_root / "logs" / f"{run_id}.jsonl").resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise LoggerError(code="PATH_TRAVERSAL", message="log path escapes workspace root", details={}) from exc
    return candidate


def _require_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LoggerError(code="INVALID_EVENT_RECORD", message=f"{field_name} must be a non-empty string", details={})
    normalized = value.strip()
    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise LoggerError(code="PATH_TRAVERSAL", message=f"{field_name} contains path traversal or separators", details={})
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise LoggerError(code="INVALID_EVENT_RECORD", message=f"{field_name} contains unsupported characters", details={})
    return normalized


def _looks_like_secret_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def _looks_like_raw_document(value: str) -> bool:
    return len(value) > 4096 and value.count("\n") > 40
