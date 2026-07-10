"""source_intake runner: resolves where bring-up evidence comes from.

Interactive/judgment skill — see orchestrator.runners module docstring.
The judgment (IPCAT vs. offline docs, power-model source) is supplied by
the caller via input_envelope["decision"]; this runner's job is to check
that decision is actually grounded in the paths/evidence it claims,
shape the resolved_evidence_sources output, and flag ambiguity for human
review when the caller's decision is missing or unsupported.

Evidence can be supplied two ways, which compose:
  1. `evidence_roots`: {"ipcat": "<dir>", "offline_documents": "<dir>"} —
     locked per-source folders. `decision.evidence_source` selects which
     root(s) to glob; every existing file found becomes an evidence_ref.
     This is the multi-target convention (targets/<name>/evidence/<src>/).
  2. explicit `*_path` fields (ipcat_export_path, schematic_path, ...) —
     the original hand-listed paths, kept as an override/fallback.
Both are resolved relative to workspace_root (or accepted as absolute).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Which evidence_roots keys each evidence_source choice pulls from.
#   ipcat_first: ipcat is the primary source; offline_documents is a fallback used
#   only when the ipcat root is missing/empty (IPCAT server busy or nobody fetched).
_SOURCE_TO_ROOT_KEYS: dict[str, tuple[str, ...]] = {
    "ipcat": ("ipcat",),
    "offline_documents": ("offline_documents",),
    "both": ("ipcat", "offline_documents"),
    "ipcat_first": ("ipcat",),  # fallback to offline handled explicitly below
}
_VALID_SOURCES = tuple(_SOURCE_TO_ROOT_KEYS.keys())


def _resolve(workspace_root: Path, rel_or_abs: str) -> Path:
    candidate = Path(rel_or_abs)
    return candidate if candidate.is_absolute() else (workspace_root / candidate)


def discover_evidence(
    workspace_root: Path,
    evidence_roots: dict[str, str],
    source_choice: str | None,
) -> dict[str, Any]:
    """Resolve which evidence files a source policy selects (pure; no side effects).

    Returns {"paths": [abs str, ...], "discovered_inputs": [...],
    "provenance": {...}, "ambiguities": [...]}. Shared by the runner and by
    run_manifest so --rerun can recompute evidence fingerprints without
    invoking the skill. Implements the ipcat_first fallback semantics.
    """
    ambiguities: list[str] = []
    discovered_inputs: list[str] = []
    paths: list[str] = []
    provenance: dict[str, Any] = {
        "policy": source_choice,
        "primary_source": None,
        "fell_back": False,
        "fallback_reason": None,
        "mcp": None,
    }

    def _glob_root(root_key: str) -> int:
        root_rel = evidence_roots.get(root_key)
        if not root_rel:
            return -1
        root_path = _resolve(workspace_root, root_rel)
        if not root_path.is_dir():
            ambiguities.append(f"evidence_roots[{root_key}] is not an existing directory: {root_path}")
            return 0
        count = 0
        for file_path in sorted(root_path.rglob("*")):
            if file_path.is_file():
                count += 1
                paths.append(str(file_path))
        discovered_inputs.append(f"evidence_roots.{root_key}")
        if count == 0:
            ambiguities.append(f"evidence_roots[{root_key}] directory is empty: {root_path}")
        return count

    if source_choice == "ipcat_first":
        provenance["primary_source"] = "ipcat"
        provenance["mcp"] = _read_ipcat_provenance(workspace_root, evidence_roots.get("ipcat"))
        found = _glob_root("ipcat")
        if found <= 0:  # ipcat root absent (-1) or empty (0) -> fall back to offline
            provenance["fell_back"] = True
            provenance["primary_source"] = "offline_documents"
            provenance["fallback_reason"] = (
                "ipcat evidence root missing" if found < 0 else "ipcat evidence root empty"
            )
            ambiguities.append(f"ipcat_first: {provenance['fallback_reason']}; falling back to offline_documents")
            _glob_root("offline_documents")
    else:
        if _SOURCE_TO_ROOT_KEYS.get(source_choice):
            provenance["primary_source"] = _SOURCE_TO_ROOT_KEYS[source_choice][0]
        for root_key in _SOURCE_TO_ROOT_KEYS.get(source_choice, ()):
            _glob_root(root_key)

    return {
        "paths": _dedup(paths),
        "discovered_inputs": discovered_inputs,
        "provenance": provenance,
        "ambiguities": ambiguities,
    }


def run_source_intake(input_envelope: dict[str, Any]) -> dict[str, Any]:
    workspace_context = input_envelope["workspace_context"]
    run_id = input_envelope["run_id"]
    decision = input_envelope.get("decision") or {}
    evidence_roots = input_envelope.get("evidence_roots") or {}

    source_choice = decision.get("evidence_source")
    power_model_source = decision.get("power_model_source")
    ambiguities: list[str] = []

    if source_choice not in _VALID_SOURCES:
        ambiguities.append("evidence_source not resolved by caller decision")
    if not power_model_source:
        ambiguities.append("power_model_source not resolved by caller decision")

    workspace_root = Path(workspace_context["workspace_root"])

    # (1) explicit per-artifact paths (override/fallback, back-compatible).
    candidate_paths = {
        "ipcat_export_path": input_envelope.get("ipcat_export_path"),
        "schematic_path": input_envelope.get("schematic_path"),
        "io_mapping_path": input_envelope.get("io_mapping_path"),
        "downstream_reference_path": input_envelope.get("downstream_reference_path"),
    }
    available = {key: value for key, value in candidate_paths.items() if value}

    evidence_refs: list[dict[str, Any]] = []
    for key, rel_path in available.items():
        full_path = _resolve(workspace_root, rel_path)
        evidence_refs.append({"artifact": key, "path": str(full_path), "exists": full_path.exists()})

    # (2) locked-folder auto-discovery, gated on the evidence_source choice.
    discovery = discover_evidence(workspace_root, evidence_roots, source_choice)
    ambiguities.extend(discovery["ambiguities"])
    for path in discovery["paths"]:
        evidence_refs.append({"artifact": "evidence_roots", "path": path, "exists": True})

    resolved_evidence_sources = {
        "run_id": run_id,
        "evidence_source": source_choice,
        "power_model_source": power_model_source,
        "available_inputs": sorted(set(available.keys()) | set(discovery["discovered_inputs"])),
        "ambiguities": ambiguities,
        "provenance": discovery["provenance"],
    }

    return {
        "resolved_evidence_sources": resolved_evidence_sources,
        "evidence": {"evidence_refs": _dedup([ref["path"] for ref in evidence_refs if ref["exists"]])},
        "human_review_needed": bool(ambiguities),
        "ambiguities": ambiguities,
    }


def _read_ipcat_provenance(workspace_root: Path, ipcat_root_rel: str | None) -> dict[str, Any] | None:
    """Return the parsed evidence/ipcat/provenance.json if present, else None.

    The MCP fetch (agent-mediated, outside this subprocess) writes this file when
    it materializes IPCAT results into the ipcat cache. We only read it here so the
    run manifest can record where the evidence came from.
    """
    if not ipcat_root_rel:
        return None
    candidate = _resolve(workspace_root, ipcat_root_rel) / "provenance.json"
    if not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _dedup(items: list[str]) -> list[str]:
    """Preserve order, drop duplicates (evidence roots can overlap on disk)."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
