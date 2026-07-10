"""Skill manifest loader/validator for audio_bu_skill/skills/*/skill.yaml.

Re-implements the validation rules from laei/schemas/skill_manifest_schema.py
(read in full during the AURA/laei review): required-field set, snake_case
skill_id matching its directory name, semver version, enum-constrained
sdlc_phase/status.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = (
    "manifest_version", "skill_id", "version", "owner", "description",
    "dependencies", "mandatory_inputs", "optional_inputs", "outputs",
    "confidence", "validation_rules", "execution_timeout", "sdlc_phase",
    "status", "writes_knowledge", "requires_human_review", "evidence_required",
)
SDLC_PHASES = {
    "requirements", "architecture", "hardware_understanding", "driver_understanding",
    "planning", "implementation", "validation", "debug", "learning", "maintenance",
}
STATUSES = {"prototype", "validated", "production", "reusable", "cross_platform", "deprecated"}
SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class SkillLoaderError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def load_skill_registry(skills_root: str | Path) -> dict[str, Any]:
    root = Path(skills_root).expanduser().resolve()
    if not root.is_dir():
        raise SkillLoaderError(code="INVALID_SKILLS_ROOT", message="skills root must exist and be a directory",
                                details={"skills_root": str(root)})

    manifests: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "skill.yaml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = _load_and_validate_manifest(manifest_path, expected_dir_name=entry.name)
            manifests[manifest["skill_id"]] = manifest
        except SkillLoaderError as exc:
            errors.append({"skill_directory": entry.name, "error": exc.to_dict()})

    dependency_graph = {
        skill_id: manifest["dependencies"] for skill_id, manifest in manifests.items()
    }

    return {
        "skills_root": str(root),
        "skills": manifests,
        "dependency_graph": dependency_graph,
        "validation_status": "valid" if not errors else "invalid",
        "errors": errors,
    }


def _load_and_validate_manifest(manifest_path: Path, *, expected_dir_name: str) -> dict[str, Any]:
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SkillLoaderError(code="INVALID_MANIFEST", message="skill.yaml must be a mapping",
                                details={"manifest_path": str(manifest_path)})

    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise SkillLoaderError(code="MISSING_FIELDS", message="skill.yaml missing required fields",
                                details={"missing_fields": missing, "manifest_path": str(manifest_path)})

    skill_id = raw["skill_id"]
    if not isinstance(skill_id, str) or not SNAKE_CASE_PATTERN.fullmatch(skill_id):
        raise SkillLoaderError(code="INVALID_SKILL_ID", message="skill_id must be snake_case",
                                details={"skill_id": skill_id})
    if skill_id != expected_dir_name:
        raise SkillLoaderError(code="SKILL_ID_DIRECTORY_MISMATCH", message="skill_id must match its directory name",
                                details={"skill_id": skill_id, "directory": expected_dir_name})

    version = raw["version"]
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise SkillLoaderError(code="INVALID_VERSION", message="version must be semver (x.y.z)",
                                details={"version": version})

    if raw["sdlc_phase"] not in SDLC_PHASES:
        raise SkillLoaderError(code="INVALID_SDLC_PHASE", message="sdlc_phase must be one of the approved values",
                                details={"sdlc_phase": raw["sdlc_phase"], "allowed": sorted(SDLC_PHASES)})

    if raw["status"] not in STATUSES:
        raise SkillLoaderError(code="INVALID_STATUS", message="status must be one of the approved values",
                                details={"status": raw["status"], "allowed": sorted(STATUSES)})

    raw["skill_directory"] = expected_dir_name
    raw["manifest_path"] = str(manifest_path)
    return raw
