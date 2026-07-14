"""Unit tests for Phase-2A WP3 — Track T3 (regression anchor).

Pure tests over ``orchestrator.reasoning.crossverify.track_t3`` and its
delegation to the unchanged WP-C lane (``compare_element_counts``, commit
``28f2f07``). No IPCAT, no collector, no network.

The **regression anchor**: rebuild the frozen Phase-1C evidence (see
``docs/PHASE1C_LIVE_EVIDENCE.md`` §3) by loading each target's committed
``element_counts`` and injecting the live catalog counts Phase-1C observed —
Nord ``{sw=0, dsp=1, lpass=0}``, Eliza ``{sw=4, dsp=1, lpass=4}`` — then
assert T3 emits exactly the six known verdicts:

  Nord:
    soundwire_master       = MATCH
    dsp_subsystem_instance = MATCH
    lpass_macro_instance   = MATCH

  Eliza:
    soundwire_master       = NOT_CROSS_CHECKABLE (source_ambiguous)
    dsp_subsystem_instance = MATCH
    lpass_macro_instance   = DISAGREE_WITH_AUTHORITY

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t3``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.reasoning.crossverify import _VERDICT_MAP, track_t3
from orchestrator.reasoning.crossverify_model import VerificationRow


REPO_ROOT = Path(__file__).resolve().parents[1]  # audio_bu_skill/
TARGETS = REPO_ROOT / "targets"

# The three element classes T3 covers today (V2 §2/T3, matches Phase-1C).
T3_CLASSES = ("soundwire_master", "dsp_subsystem_instance", "lpass_macro_instance")

# Live catalog counts observed in Phase-1C (docs/PHASE1C_LIVE_EVIDENCE.md §2).
NORD_CATALOG = {"soundwire_master": 0, "dsp_subsystem_instance": 1, "lpass_macro_instance": 0}
ELIZA_CATALOG = {"soundwire_master": 4, "dsp_subsystem_instance": 1, "lpass_macro_instance": 4}


def _load_element_counts(target_dir: str) -> list[dict[str, Any]]:
    """Return the frozen ``element_counts`` from a target's qgenie_analysis.json.

    The counts live at the JSON top level (not under ``audio_topology``); this
    is the same shape Phase-1C read via its ``src_ec`` fallback.
    """
    path = TARGETS / target_dir / "qgenie_analysis.json"
    data = json.loads(path.read_text())
    at = (data.get("audio_topology") or {}).get("element_counts")
    return at or data.get("element_counts") or []


def _build_gc(target_dir: str, catalog: dict[str, int]) -> dict[str, Any]:
    """Rebuild the Phase-1C gc: frozen element_counts + injected catalog lane.

    Filters to the three T3 classes and copies each row verbatim, adding the
    ``catalog`` field from the live-observed counts. This is exactly what
    Phase-1C did before calling the WP-C lane.
    """
    items = _load_element_counts(target_dir)
    picked: list[dict[str, Any]] = []
    for item in items:
        cls = item.get("element_class")
        if cls in catalog:
            enriched = dict(item)
            enriched["catalog"] = catalog[cls]
            picked.append(enriched)
    # sanity: we found all three
    assert {p["element_class"] for p in picked} == set(catalog), (
        f"missing T3 rows in {target_dir}: "
        f"{set(catalog) - {p['element_class'] for p in picked}}"
    )
    return {"audio_topology": {"element_counts": picked}}


def _rows_by_class(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    return {r.subject: r for r in rows}


# ── Frozen Phase-1C reproduction — the six verdicts ─────────────────────────


def test_nord_all_three_are_match() -> None:
    gc = _build_gc("nord-iq10", NORD_CATALOG)
    rows = track_t3(snapshot={}, gc=gc, kb=None)
    by = _rows_by_class(rows)
    for cls in T3_CLASSES:
        assert cls in by, f"missing T3 row for {cls}"
        assert by[cls].verdict == "MATCH", f"{cls}: got {by[cls].verdict}"
        assert by[cls].track == "T3"
        assert by[cls].warning is False
        assert by[cls].coverage_gap_reason is None
        assert by[cls].authority["strength"] == "IPCAT_DIRECT"
        assert by[cls].authority["value"] == NORD_CATALOG[cls]
        assert by[cls].confidence == "high"
    print("PASS: Nord — soundwire_master / dsp_subsystem_instance / lpass_macro_instance all MATCH")


def test_eliza_soundwire_is_not_cross_checkable_ambiguous() -> None:
    gc = _build_gc("eliza", ELIZA_CATALOG)
    row = _rows_by_class(track_t3(snapshot={}, gc=gc, kb=None))["soundwire_master"]
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "source_ambiguous"
    assert row.warning is False
    assert row.confidence == "none"
    assert row.review_actions and "resolve source ambiguity" in row.review_actions[0]
    print("PASS: Eliza soundwire_master = NOT_CROSS_CHECKABLE (source_ambiguous)")


def test_eliza_dsp_is_match() -> None:
    gc = _build_gc("eliza", ELIZA_CATALOG)
    row = _rows_by_class(track_t3(snapshot={}, gc=gc, kb=None))["dsp_subsystem_instance"]
    assert row.verdict == "MATCH"
    assert row.confidence == "high"
    assert row.authority["value"] == 1
    print("PASS: Eliza dsp_subsystem_instance = MATCH")


def test_eliza_lpass_is_disagree_with_authority() -> None:
    gc = _build_gc("eliza", ELIZA_CATALOG)
    row = _rows_by_class(track_t3(snapshot={}, gc=gc, kb=None))["lpass_macro_instance"]
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True, "DISAGREE_WITH_AUTHORITY must warn"
    assert row.confidence == "high"
    assert row.coverage_gap_reason is None
    assert row.authority["value"] == 4
    # source side: proposal=2 was the divergent lane
    assert (row.source or {}).get("lanes", {}).get("proposal") == 2
    assert row.review_actions and "catalog=4" in row.review_actions[0]
    print("PASS: Eliza lpass_macro_instance = DISAGREE_WITH_AUTHORITY (proposal=2 vs catalog=4)")


def test_six_verdicts_exactly() -> None:
    """The complete Phase-1C truth table in one shot."""
    combined = _rows_by_class(
        track_t3(snapshot={}, gc=_build_gc("nord-iq10", NORD_CATALOG), kb=None)
    )
    nord = {cls: combined[cls].verdict for cls in T3_CLASSES}

    combined = _rows_by_class(
        track_t3(snapshot={}, gc=_build_gc("eliza", ELIZA_CATALOG), kb=None)
    )
    eliza = {cls: combined[cls].verdict for cls in T3_CLASSES}

    assert nord == {
        "soundwire_master": "MATCH",
        "dsp_subsystem_instance": "MATCH",
        "lpass_macro_instance": "MATCH",
    }
    assert eliza == {
        "soundwire_master": "NOT_CROSS_CHECKABLE",
        "dsp_subsystem_instance": "MATCH",
        "lpass_macro_instance": "DISAGREE_WITH_AUTHORITY",
    }
    print("PASS: all six Phase-1C verdicts reproduced exactly")


# ── Contract: mapping table is total; delegation is unchanged ──────────────


def test_verdict_map_covers_every_wp_c_verdict() -> None:
    """Guard against silent WP-C drift — every WP-C verdict must map."""
    from orchestrator.reasoning import cardinality as WPC

    wpc_verdicts = {
        WPC.VERDICT_AGREE,
        WPC.VERDICT_DISAGREE,
        WPC.VERDICT_NOT_CROSS_CHECKABLE,
        WPC.VERDICT_BENIGN_DIVERGENCE,
        WPC.VERDICT_DISAGREE_WITH_AUTHORITY,
    }
    unmapped = wpc_verdicts - set(_VERDICT_MAP)
    assert not unmapped, f"WP-C verdicts with no Phase-2A mapping: {unmapped}"
    # every mapped Phase-2A verdict is a legal VerificationRow verdict
    from orchestrator.reasoning.crossverify_model import VERDICTS
    assert set(_VERDICT_MAP.values()) <= VERDICTS
    print("PASS: verdict map is total over WP-C output and lands in legal verdicts")


def test_empty_element_counts_yields_empty_row_list() -> None:
    """No element_counts → no rows (matches WP-C's null-guarded return)."""
    assert track_t3(snapshot={}, gc={}, kb=None) == []
    assert track_t3(snapshot={}, gc={"audio_topology": {}}, kb=None) == []
    print("PASS: empty gc yields [] (additive-only contract preserved)")


def test_deterministic_across_calls() -> None:
    gc = _build_gc("eliza", ELIZA_CATALOG)
    a = [r.to_dict() for r in track_t3(snapshot={}, gc=gc, kb=None)]
    b = [r.to_dict() for r in track_t3(snapshot={}, gc=gc, kb=None)]
    assert a == b, "T3 must be deterministic across repeated calls"
    print("PASS: T3 is deterministic across repeated calls")


def main() -> None:
    test_nord_all_three_are_match()
    test_eliza_soundwire_is_not_cross_checkable_ambiguous()
    test_eliza_dsp_is_match()
    test_eliza_lpass_is_disagree_with_authority()
    test_six_verdicts_exactly()
    test_verdict_map_covers_every_wp_c_verdict()
    test_empty_element_counts_yields_empty_row_list()
    test_deterministic_across_calls()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
