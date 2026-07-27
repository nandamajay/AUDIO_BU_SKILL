"""H-2 reviewer loader — parse H-1 JSON output into a :class:`TargetView`.

This module is the *only* place H-2 touches the filesystem in Phase 1,
and it is strictly READ-ONLY: it opens ``audio_hardware_template.json``
and ``gap_manifest.json`` for a target, parses them, and projects them
into the frozen view objects declared in
:mod:`orchestrator.reviewer.model`. It writes nothing, mutates nothing,
and imports no H-1 / reasoning / generation / codegen Python module
(invariant I-2) — it consumes JSON, not objects.

The loader is idempotent: calling it twice on the same inputs yields
equal :class:`TargetView` values and produces no side effects.

**What the loader deliberately does NOT do:**

  * It does not promote candidate values, re-run cross-verification, or
    recompute authority. H-1 already decided those; the loader copies
    them verbatim (invariant I-1 / I-4).
  * It does not assign severity or workflow state (Phase 2).
  * It does not read or trust ``gc["cross_verification"]["rows"]`` or
    ``TrustedFacts`` — those are H-1's inputs, not H-2's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.reviewer.model import (
    EntityView,
    FactView,
    GapView,
    ReviewerContext,
    TargetView,
)

# Ordered entity families as they appear in an AudioHardwareTemplate.
# board_metadata is the singleton group (projected first); the rest are
# lists projected in this fixed order so the resulting TargetView.entities
# tuple is deterministic.
_LIST_FAMILIES: tuple[tuple[str, str], ...] = (
    ("codecs", "codec"),
    ("amplifiers", "amplifier"),
    ("buses", "bus"),
    ("clocks", "clock"),
    ("audio_links", "audio_link"),
)

# A parsed field is a FactRecord iff it is a dict carrying the ``authority``
# envelope key. board_metadata also carries a bare ``target_name`` string
# (non-FactRecord) which must be skipped, so we test structurally rather
# than by field name.
def _is_fact_record(value: Any) -> bool:
    return isinstance(value, dict) and "authority" in value


def _load_json(path: str | Path) -> dict[str, Any]:
    """Read and parse a JSON object file, raising a clear error on trouble."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(f"reviewer loader: cannot read {p}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reviewer loader: {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"reviewer loader: {p} must contain a JSON object, "
            f"got {type(data).__name__}"
        )
    return data


def _project_entity(kind: str, index: int, raw: dict[str, Any]) -> EntityView:
    """Project one entity dict into an EntityView of FactViews.

    Only FactRecord-shaped fields become FactViews; bare scalars (e.g.
    board_metadata's ``target_name`` string) are skipped — they are not
    provenance-carrying facts and H-2 has nothing to review about them.
    """
    fields: dict[str, FactView] = {}
    for field_name, field_value in raw.items():
        if _is_fact_record(field_value):
            fields[field_name] = FactView.from_record(field_value, path=field_name)
    return EntityView(kind=kind, index=index, fields=fields)


def _project_gaps(manifest: dict[str, Any]) -> tuple[GapView, ...]:
    """Project the manifest's flat gap list into GapViews, in order."""
    gaps: list[GapView] = []
    for raw_gap in manifest.get("gaps") or ():
        if not isinstance(raw_gap, dict):
            raise ValueError(
                f"reviewer loader: gap entry must be a dict, "
                f"got {type(raw_gap).__name__}"
            )
        path = raw_gap.get("path")
        reason = raw_gap.get("reason")
        if not isinstance(path, str):
            raise ValueError(f"reviewer loader: gap missing string 'path': {raw_gap!r}")
        if not isinstance(reason, str):
            raise ValueError(f"reviewer loader: gap missing string 'reason': {raw_gap!r}")
        fact = FactView.from_record(raw_gap, path=path)
        # severity / state / comment are Phase-2 concerns: always None here.
        gaps.append(GapView(path=path, reason=reason, fact=fact))
    return tuple(gaps)


def _summarize(
    entities: tuple[EntityView, ...], gaps: tuple[GapView, ...]
) -> dict[str, Any]:
    """Small descriptive counts dict — NOT an authority signal."""
    entity_counts: dict[str, int] = {}
    for e in entities:
        entity_counts[e.kind] = entity_counts.get(e.kind, 0) + 1
    gap_counts: dict[str, int] = {}
    for g in gaps:
        gap_counts[g.reason] = gap_counts.get(g.reason, 0) + 1
    return {
        "entity_counts": entity_counts,
        "gap_count": len(gaps),
        "gap_count_by_reason": gap_counts,
    }


def load(context: ReviewerContext) -> TargetView:
    """Load one target's H-1 output into a frozen :class:`TargetView`.

    Read-only and idempotent. Parses ``template_path`` and
    ``gap_manifest_path`` from ``context`` and projects them. The optional
    ``attested_findings_path`` / ``gap_states_path`` are NOT read in
    Phase 1 (they belong to the attested-findings and workflow-state
    subsystems, which do not exist yet).
    """
    template = _load_json(context.template_path)
    manifest = _load_json(context.gap_manifest_path)

    entities: list[EntityView] = []

    # board_metadata — singleton group, projected first at index 0.
    board = template.get("board_metadata")
    if isinstance(board, dict):
        entities.append(_project_entity("board_metadata", 0, board))

    # list families, in fixed order.
    for key, kind in _LIST_FAMILIES:
        family = template.get(key) or []
        if not isinstance(family, list):
            raise ValueError(
                f"reviewer loader: template['{key}'] must be a list, "
                f"got {type(family).__name__}"
            )
        for index, raw in enumerate(family):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"reviewer loader: {key}[{index}] must be a dict, "
                    f"got {type(raw).__name__}"
                )
            entities.append(_project_entity(kind, index, raw))

    entities_tuple = tuple(entities)
    gaps_tuple = _project_gaps(manifest)

    # Provenance / identity copied verbatim from the template. The schema
    # version key is written by H-1 as ``$schema_version``.
    return TargetView(
        target_name=template.get("target_name", context.target_name),
        run_id=template.get("run_id", ""),
        schema_version=template.get("$schema_version", TargetView.schema_version),
        generated_from=dict(template.get("generated_from") or {}),
        entities=entities_tuple,
        gaps=gaps_tuple,
        summary=_summarize(entities_tuple, gaps_tuple),
    )


# ── path helpers for locating H-1 output ────────────────────────────────────
#
# H-1 writes into ``targets/<name>/h1_validation/`` under the validation
# harness, and would write into ``targets/<name>/`` in a production run.
# The loader accepts an explicit ReviewerContext, but this helper builds a
# context by locating whichever directory actually holds the pair of H-1
# artefacts, so tests and the (later) CLI don't have to hard-code the
# harness subdirectory.

_TEMPLATE_NAME = "audio_hardware_template.json"
_MANIFEST_NAME = "gap_manifest.json"


def context_for_target(target_dir: str | Path, target_name: str | None = None) -> ReviewerContext:
    """Build a :class:`ReviewerContext` by finding H-1 output under a target dir.

    Searches ``target_dir`` and its immediate subdirectories for a pair of
    ``audio_hardware_template.json`` + ``gap_manifest.json`` files. Raises
    :class:`FileNotFoundError` if no such pair exists.
    """
    root = Path(target_dir)
    name = target_name or root.name

    candidates = [root, *(p for p in sorted(root.iterdir()) if p.is_dir())] if root.is_dir() else []
    for d in candidates:
        template = d / _TEMPLATE_NAME
        manifest = d / _MANIFEST_NAME
        if template.is_file() and manifest.is_file():
            attested = d / "attested_findings.md"
            gap_states = d / "gap_states.json"
            return ReviewerContext(
                target_name=name,
                template_path=str(template),
                gap_manifest_path=str(manifest),
                attested_findings_path=str(attested) if attested.is_file() else None,
                gap_states_path=str(gap_states) if gap_states.is_file() else None,
            )
    raise FileNotFoundError(
        f"reviewer loader: no {_TEMPLATE_NAME} + {_MANIFEST_NAME} pair found "
        f"under {root}"
    )
