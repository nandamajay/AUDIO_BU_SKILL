"""Phase-2A — Schematic ↔ IPCAT Cross-Verification Engine (pure Comparison Core).

Pure, deterministic. Zero I/O. Consumes a frozen snapshot produced by
``orchestrator/runners/crossverify_collector.py`` and a case dict ``gc``
carrying (a) ``audio_topology.element_counts`` for T3, and (b) the
schematic/design view for the remaining tracks (built in later WPs). Emits
:class:`~orchestrator.reasoning.crossverify_model.VerificationRow` values only.

WP3 in this file is the **regression anchor**: T3 delegates to the committed
WP-C lane (:func:`~orchestrator.reasoning.cardinality.compare_element_counts`,
pinned at commit ``28f2f07``) UNCHANGED, then translates each WP-C row into a
``VerificationRow`` via a total mapping (see :data:`_VERDICT_MAP`). No other
track is implemented here — tracks T1/T2/T4a/T4b/T5 are separate WPs and stay
un-imported until then. Only WP-C's public ``compare_element_counts`` is
touched; ``cardinality.py`` / ``cardinality_config.py`` are not modified.

Track_t3 accepts the WP1 signature ``(snapshot, gc, kb)`` for API parity with
the other tracks even though it consumes only ``gc``. The catalog lane is
already present in ``gc["audio_topology"]["element_counts"]`` at call time —
exactly the shape Phase-1C committed — so this track re-runs Phase-1C's
verdicts byte-for-byte and is the pipeline's regression anchor.
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.cardinality import compare_element_counts
from orchestrator.reasoning.crossverify_model import VerificationRow

# WP-C ``compare_element_counts`` returns ``counts`` keyed by
# :data:`orchestrator.reasoning.cardinality_config.SOURCE_NAME` values
# (``dt_count`` / ``evidence_count`` / ``proposal_count`` / ``catalog_count``),
# not by the raw lane keys. The catalog lane in that mapping is:
_WPC_CATALOG_SOURCE: str = "catalog_count"


def _strip_count(source_name: str) -> str:
    """``proposal_count`` → ``proposal``, ``dt_count`` → ``dt``, ... for reader-facing lane names."""
    return source_name[:-len("_count")] if source_name.endswith("_count") else source_name


# ── WP-C verdict → Phase-2A verdict mapping (total over WP-C's output) ──────
#
# WP-C can emit five verdict strings. The four the WP3 spec lists map 1-1;
# ``disagree`` (pre-SWI pairwise mismatch, no KB rule) is also mapped so the
# translation is total — an unmapped WP-C verdict would silently drop a row.
_VERDICT_MAP: dict[str, str] = {
    "agree": "MATCH",
    "disagree_with_authority": "DISAGREE_WITH_AUTHORITY",
    "not_cross_checkable": "NOT_CROSS_CHECKABLE",
    "benign_divergence": "PARTIAL_MATCH",
    "disagree": "DISAGREE_WITH_AUTHORITY",
}


def _authority(row: dict[str, Any]) -> dict[str, Any]:
    """Build the authority object for a WP-C row.

    When the ``catalog`` lane is present in ``row["counts"]`` the authority
    is the post-SWI IPCAT catalog (``IPCAT_DIRECT``, origin = the WP-C lane
    that surfaced it); otherwise no authority spoke this run and the row
    carries ``UNAVAILABLE``. The catalog value, when present, is copied
    verbatim so the reviewer can see what the authority actually said.
    """
    counts = row.get("counts") or {}
    if _WPC_CATALOG_SOURCE in counts:
        return {
            "strength": "IPCAT_DIRECT",
            "origin": "wp_c.cardinality_catalog",
            "value": counts[_WPC_CATALOG_SOURCE],
        }
    return {"strength": "UNAVAILABLE", "origin": "none"}


def _coverage_gap_reason(row: dict[str, Any]) -> str:
    """Only called when the mapped verdict is NOT_CROSS_CHECKABLE.

    WP-C emits ``not_cross_checkable`` from two precedence branches:
      1. ``ambiguous:true`` on the source → ``source_ambiguous``;
      2. ``< 2 usable lanes`` (nothing to compare) → ``insufficient_lanes``.
    """
    if row.get("ambiguous"):
        return "source_ambiguous"
    return "insufficient_lanes"


def _confidence(mapped_verdict: str, row: dict[str, Any]) -> str:
    """Confidence policy for T3 (V2 §2/T3, §2/T2 & WP-C asymmetry).

    * post-SWI (catalog lane present) MATCH / DISAGREE_WITH_AUTHORITY = ``high``;
    * pre-SWI pairwise MATCH (no catalog authority) = ``medium``;
    * PARTIAL_MATCH via a KB divergence rule = ``medium`` (rule downgrades it
      from a hard defect to informational, but not to certainty);
    * NOT_CROSS_CHECKABLE has no verdict-bearing signal → ``none``.
    """
    if mapped_verdict == "NOT_CROSS_CHECKABLE":
        return "none"
    counts = row.get("counts") or {}
    catalog_spoke = _WPC_CATALOG_SOURCE in counts
    if mapped_verdict in ("MATCH", "DISAGREE_WITH_AUTHORITY"):
        return "high" if catalog_spoke else "medium"
    # PARTIAL_MATCH
    return "medium"


def _review_actions(mapped_verdict: str, row: dict[str, Any]) -> list[str]:
    """One-line reviewer prompts, tuned to the verdict. Empty for MATCH."""
    cls = row.get("element_class", "?")
    counts = row.get("counts") or {}
    if mapped_verdict == "DISAGREE_WITH_AUTHORITY":
        catalog = counts.get(_WPC_CATALOG_SOURCE)
        others = {_strip_count(s): n for s, n in counts.items() if s != _WPC_CATALOG_SOURCE}
        others_str = ", ".join(f"{s}={n}" for s, n in others.items()) or "no other lanes"
        return [
            f"reconcile {cls}: catalog={catalog} vs {others_str}"
        ]
    if mapped_verdict == "NOT_CROSS_CHECKABLE":
        if row.get("ambiguous"):
            note = row.get("ambiguity_note") or "source flagged ambiguous"
            return [f"resolve source ambiguity on {cls}: {note}"]
        return [
            f"insufficient lanes to cross-check {cls}; add an independent count"
        ]
    if mapped_verdict == "PARTIAL_MATCH":
        rule = row.get("rule_id") or "KB rule"
        return [f"{cls} lane disagreement covered by {rule} (informational)"]
    # MATCH → no action
    return []


def _translate(row: dict[str, Any]) -> VerificationRow:
    """One WP-C row → one VerificationRow.

    ``track`` is always ``T3``. ``subject`` = element_class. ``source``
    carries every non-catalog lane the WP-C row surfaced (dt/evidence/proposal),
    so the reviewer sees exactly what the design side reported. ``authority``
    carries the catalog lane when present.
    """
    wpc_verdict = row.get("verdict")
    mapped = _VERDICT_MAP.get(wpc_verdict)
    if mapped is None:
        raise ValueError(f"unmapped WP-C verdict {wpc_verdict!r}")

    counts = row.get("counts") or {}
    source_lanes = {
        _strip_count(s): n for s, n in counts.items() if s != _WPC_CATALOG_SOURCE
    }

    notes = list(row.get("notes") or [])
    if row.get("ambiguous") and row.get("ambiguity_note"):
        notes.insert(0, f"ambiguous: {row['ambiguity_note']}")

    coverage_gap = _coverage_gap_reason(row) if mapped == "NOT_CROSS_CHECKABLE" else None

    return VerificationRow(
        track="T3",
        subject=row.get("element_class", "?"),
        verdict=mapped,
        source={"lanes": source_lanes} if source_lanes else None,
        authority=_authority(row),
        confidence=_confidence(mapped, row),
        coverage_gap_reason=coverage_gap,
        rule_id=row.get("rule_id"),
        review_actions=_review_actions(mapped, row),
        citations=list(row.get("citations") or []),
        notes=notes,
    )


def track_t3(
    snapshot: dict[str, Any],
    gc: dict[str, Any],
    kb: dict[str, Any] | None = None,
) -> list[VerificationRow]:
    """T3 — Audio Resource Validation via the unchanged WP-C lane.

    Pure delegation: hands ``gc`` to
    :func:`~orchestrator.reasoning.cardinality.compare_element_counts`
    (committed ``28f2f07``, not modified) and maps every emitted row to a
    :class:`VerificationRow`. Consumes only ``gc``; ``snapshot`` and ``kb``
    are accepted for API parity with the other tracks and are unused today
    (a future revision may pull the catalog lane out of the snapshot here).

    Ordering is preserved from WP-C's config-driven order — the anchor is
    a byte-for-byte reproduction of Phase-1C's verdicts.
    """
    del snapshot, kb  # explicitly unused in WP3
    return [_translate(row) for row in compare_element_counts(gc)]
