"""workspace.yaml loader: declared evidence-artifact inventory with sha256 hashes.

Re-implements laei's runtime/workspace_loader.py contract (read in full):
require workspace.yaml at the workspace root, validate its artifact list,
hash whatever exists, raise structured errors for missing required
artifacts or path traversal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

WORKSPACE_MANIFEST_FILENAME = "workspace.yaml"
REQUIRED_TOP_LEVEL_FIELDS = ("manifest_version", "workspace_id", "artifacts")
REQUIRED_ARTIFACT_FIELDS = ("id", "type", "path")


class WorkspaceLoaderError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def load_workspace_context(workspace_root: str | Path) -> dict[str, Any]:
    root_path = Path(workspace_root).expanduser()
    if not root_path.exists() or not root_path.is_dir():
        raise WorkspaceLoaderError(code="INVALID_WORKSPACE_ROOT", message="workspace root must exist and be a directory",
                                    details={"workspace_root": str(root_path)})

    resolved_root = root_path.resolve()
    manifest_path = resolved_root / WORKSPACE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise WorkspaceLoaderError(code="MISSING_MANIFEST", message="workspace.yaml is required at workspace root",
                                    details={"manifest_path": str(manifest_path)})

    raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    normalized = _normalize_manifest(raw_manifest)

    inventory: list[dict[str, Any]] = []
    for artifact in normalized["artifacts"]:
        relative_path = artifact["path"]
        artifact_path = _resolve_relative(resolved_root, relative_path)
        exists = artifact_path.is_file()

        if artifact["required"] and not exists:
            raise WorkspaceLoaderError(code="MISSING_REQUIRED_ARTIFACT", message="required artifact is missing",
                                        details={"artifact_id": artifact["id"], "relative_path": relative_path})

        record: dict[str, Any] = {
            "artifact_id": artifact["id"],
            "artifact_type": artifact["type"],
            "relative_path": relative_path,
            "required": artifact["required"],
            "exists": exists,
            "hash_sha256": _sha256_file(artifact_path) if exists else None,
            "size_bytes": artifact_path.stat().st_size if exists else None,
        }
        inventory.append(record)

    return {
        "workspace_root": str(resolved_root),
        "workspace_id": normalized["workspace_id"],
        "manifest_version": normalized["manifest_version"],
        "metadata": normalized["metadata"],
        "artifact_inventory": inventory,
        "validation_status": "valid",
    }


def _normalize_manifest(raw_manifest: Any) -> dict[str, Any]:
    if not isinstance(raw_manifest, dict):
        raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="workspace manifest must be a mapping", details={})

    missing = [f for f in REQUIRED_TOP_LEVEL_FIELDS if f not in raw_manifest]
    if missing:
        raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="workspace manifest is missing required top-level fields",
                                    details={"missing_fields": missing})

    artifacts = raw_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="artifacts must be a non-empty list", details={})

    normalized_artifacts = []
    seen_ids: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="artifact entries must be mappings",
                                        details={"artifact_index": index})
        missing_fields = [f for f in REQUIRED_ARTIFACT_FIELDS if f not in artifact]
        if missing_fields:
            raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="artifact entry missing required fields",
                                        details={"artifact_index": index, "missing_fields": missing_fields})
        artifact_id = artifact["id"]
        if artifact_id in seen_ids:
            raise WorkspaceLoaderError(code="INVALID_MANIFEST", message="artifact ids must be unique",
                                        details={"artifact_id": artifact_id})
        seen_ids.add(artifact_id)
        normalized_artifacts.append({
            "id": artifact_id,
            "type": artifact["type"],
            "path": artifact["path"],
            "required": artifact.get("required", True),
        })

    return {
        "manifest_version": raw_manifest["manifest_version"],
        "workspace_id": raw_manifest["workspace_id"],
        "metadata": raw_manifest.get("metadata") or {},
        "artifacts": normalized_artifacts,
    }


def _resolve_relative(workspace_root: Path, relative_path: str) -> Path:
    candidate = (workspace_root / relative_path).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise WorkspaceLoaderError(code="PATH_TRAVERSAL", message="artifact path escapes workspace root",
                                    details={"relative_path": relative_path}) from exc
    return candidate


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
