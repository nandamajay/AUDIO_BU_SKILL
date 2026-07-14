"""Unit tests for Phase-2A WP5 — Track T2 (Bus / SoundWire-Master validation).

Pure tests over ``orchestrator.reasoning.crossverify.track_t2``. No IPCAT, no
collector, no network — snapshots are built inline as plain dicts matching the
WP1 collector's wire shape:

    snapshot["tools"]["swi_search_swi"] = {
        "status": "ok" | "unavailable",
        "payload": {
            "SOUNDWIRE_MASTER": {"status": "ok", "payload": {"results": [...]}},
            "SWR_MSTR":         {"status": "ok" | "unavailable", ...},
            "SWR":              {"status": "ok" | "unavailable", ...},
            "LPASS_MACRO":      {...},  # not consumed by T2 (still recorded)
            "LPASS":            {...},  # not consumed by T2 (still recorded)
        },
        "result_digest": <sha256|None>,
        "queries":       ["SOUNDWIRE_MASTER", "SWR_MSTR", "SWR", "LPASS_MACRO", "LPASS"],
        # status == "unavailable" also carries "error_class": "all_swi_queries_failed"
    }

Covers the six required verdict shapes plus determinism (WP5 requirement 5, a-g):

  a. Nord — soundwire.present=False AND catalog union count = 0 → MATCH
  b. Eliza — source master_count = 4 AND catalog union count = 4 → MATCH
  c. counts differ (source=2, catalog=4) → DISAGREE_WITH_AUTHORITY
  d. source flagged ambiguous:true → NOT_CROSS_CHECKABLE (source_ambiguous)
  e. one healthy SWI term at result cap → provisional confidence
  f. swi_search_swi unavailable → NOT_CROSS_CHECKABLE (authority_unavailable)
  g. deterministic across repeated calls

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t2``
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.crossverify import (
    _T2_SOUNDWIRE_TERMS,
    _T2_SWI_RESULT_CAP,
    track_t2,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Snapshot builders (pure helpers, no I/O) ────────────────────────────────


def _term_ok(results: list[dict[str, Any]]) -> dict[str, Any]:
    """One SWI per-term entry, status='ok', with a results payload."""
    return {"status": "ok", "payload": {"results": results}, "result_digest": "deadbeef"}


def _term_unavailable(error_class: str = "TimeoutError") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "payload": None,
        "result_digest": None,
        "error_class": error_class,
    }


def _swi_snap(
    per_term: dict[str, dict[str, Any]] | None,
    *,
    status: str = "ok",
    error_class: str | None = None,
) -> dict[str, Any]:
    """Build a minimal snapshot with only the swi_search_swi tool populated.

    ``per_term`` is a ``{term: per_term_entry}`` dict; missing terms default to
    an empty ``results:[]`` OK entry (mirrors the collector's default). When
    ``status="unavailable"`` the tool-level status is set accordingly and the
    ``error_class`` is recorded (collector convention: ``all_swi_queries_failed``).
    """
    payload: dict[str, dict[str, Any]] = {}
    default_terms = ("SOUNDWIRE_MASTER", "SWR_MSTR", "SWR", "LPASS_MACRO", "LPASS")
    for term in default_terms:
        if per_term and term in per_term:
            payload[term] = per_term[term]
        else:
            payload[term] = _term_ok([])
    tool_entry: dict[str, Any] = {
        "status": status,
        "payload": payload,
        "result_digest": "cafebabe" if status == "ok" else None,
        "queries": list(default_terms),
    }
    if status == "unavailable":
        tool_entry["error_class"] = error_class or "all_swi_queries_failed"
    return {
        "chip": "nordschleife_2.0",
        "provenance": {
            "tls": {"verify": True, "ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt"},
            "readonly_tools": ["swi_search_swi"],
        },
        "tools": {"swi_search_swi": tool_entry},
    }


def _rows_by_subject(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    return {r.subject: r for r in rows}


# ── (a) Nord — I2S-only, both sides = 0 → MATCH ─────────────────────────────


def test_nord_i2s_only_zero_equals_zero_is_match() -> None:
    """Design says present=False, catalog union count is 0 → MATCH high."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok([]),
            "SWR_MSTR": _term_ok([]),
            "SWR": _term_ok([]),
        }
    )
    source = {"present": False, "master_count": 0, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.track == "T2"
    assert row.subject == "soundwire_master"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == "ipcat.swi_search_swi"
    assert row.authority["value"] == {"soundwire_master_count": 0}
    assert row.source == {"present": False, "master_count": 0, "ambiguous": False}
    # provenance citation lists the three soundwire terms actually consulted
    assert row.citations, "citations must not be empty"
    assert row.citations[0].startswith("swi_search_swi:")
    for term in _T2_SOUNDWIRE_TERMS:
        assert term in row.citations[0]
    print("PASS: Nord I2S-only — soundwire.present=False and catalog=0 → MATCH high")


# ── (b) Eliza — source master_count = 4 AND catalog union count = 4 → MATCH ─


def test_eliza_four_equals_four_is_match() -> None:
    """Source master_count=4 AND catalog union count=4 → MATCH high."""
    # Four distinct named blocks scattered across the three terms; the union
    # must dedup so that a block appearing in two terms doesn't inflate the count.
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok(
                [
                    {"name": "SWR_MSTR_WSA0"},
                    {"name": "SWR_MSTR_WSA1"},
                ]
            ),
            "SWR_MSTR": _term_ok(
                [
                    {"name": "SWR_MSTR_WSA0"},  # dup — must not double-count
                    {"name": "SWR_MSTR_RX"},
                    {"name": "SWR_MSTR_TX"},
                ]
            ),
            "SWR": _term_ok(
                [
                    {"name": "SWR_MSTR_RX"},  # dup
                    {"name": "SWR_MSTR_TX"},  # dup
                ]
            ),
        }
    )
    source = {"present": True, "master_count": 4, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "MATCH"
    assert row.confidence == "high"
    assert row.warning is False
    assert row.coverage_gap_reason is None
    assert row.authority["value"] == {"soundwire_master_count": 4}
    assert row.source == {"present": True, "master_count": 4, "ambiguous": False}
    print("PASS: Eliza — source master_count=4 and catalog union=4 (deduped) → MATCH high")


# ── (c) Counts differ (source=2, catalog=4) → DISAGREE_WITH_AUTHORITY ────────


def test_counts_differ_is_disagree_with_authority() -> None:
    """Source claims 2 masters; catalog says 4 → DISAGREE_WITH_AUTHORITY."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok(
                [
                    {"name": "SWR_MSTR_WSA0"},
                    {"name": "SWR_MSTR_WSA1"},
                    {"name": "SWR_MSTR_RX"},
                    {"name": "SWR_MSTR_TX"},
                ]
            ),
        }
    )
    source = {"present": True, "master_count": 2, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True  # DISAGREE_WITH_AUTHORITY warns by default
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"
    assert row.authority["value"] == {"soundwire_master_count": 4}
    assert row.source == {"present": True, "master_count": 2, "ambiguous": False}
    assert row.review_actions, "DISAGREE must record a review action"
    assert "source=2" in row.review_actions[0] and "catalog=4" in row.review_actions[0]
    print("PASS: source=2 vs catalog=4 → DISAGREE_WITH_AUTHORITY (warning=True)")


# ── (d) Source ambiguous:true → NOT_CROSS_CHECKABLE (source_ambiguous) ──────


def test_source_ambiguous_is_not_cross_checkable() -> None:
    """Source self-flagged ambiguous:true → NOT_CROSS_CHECKABLE / source_ambiguous."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok(
                [
                    {"name": "SWR_MSTR_WSA0"},
                    {"name": "SWR_MSTR_WSA1"},
                    {"name": "SWR_MSTR_RX"},
                    {"name": "SWR_MSTR_TX"},
                ]
            ),
        }
    )
    source = {
        "present": True,
        "master_count": 4,
        "ambiguous": True,
        "ambiguity_note": "schematic shows SoundWire block but master count unclear",
    }
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "source_ambiguous"
    assert row.warning is False  # NOT_CROSS_CHECKABLE warning defaults False
    assert row.confidence == "none"
    # authority payload is still populated (catalog *is* readable — the gap is on source side)
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["value"] == {"soundwire_master_count": 4}
    assert row.review_actions and "resolve source ambiguity" in row.review_actions[0]
    print("PASS: source ambiguous:true → NOT_CROSS_CHECKABLE (source_ambiguous)")


# ── (e) SWI term at cap → provisional confidence ────────────────────────────


def test_swi_term_at_cap_downgrades_to_provisional() -> None:
    """A healthy term returns exactly ``_T2_SWI_RESULT_CAP`` rows → provisional confidence."""
    # Build a full page of distinct named blocks under SOUNDWIRE_MASTER, and
    # leave SWR_MSTR + SWR empty. The union count equals the cap. The source
    # matches that count so we still land in MATCH — but confidence must be
    # downgraded to 'provisional' because the response *could* be truncated.
    capped_rows = [{"name": f"SWR_MSTR_BLK{i:02d}"} for i in range(_T2_SWI_RESULT_CAP)]
    snap = _swi_snap({"SOUNDWIRE_MASTER": _term_ok(capped_rows)})
    source = {"present": True, "master_count": _T2_SWI_RESULT_CAP, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "MATCH"
    assert row.confidence == "provisional", (
        f"expected provisional under result cap, got {row.confidence!r}"
    )
    # caveat recorded in notes and appended to review_actions
    assert any("result cap" in n for n in row.notes), "notes must record the cap caveat"
    assert row.review_actions and any(
        "higher page size" in a for a in row.review_actions
    ), "review_actions must ask for a re-run at higher page size"
    print("PASS: SWI term at result cap → confidence downgraded to provisional")


# ── (f) swi_search_swi unavailable → NOT_CROSS_CHECKABLE (authority_unavailable) ─


def test_swi_unavailable_is_not_cross_checkable() -> None:
    """swi_search_swi.status='unavailable' → NOT_CROSS_CHECKABLE / authority_unavailable."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_unavailable("TimeoutError"),
            "SWR_MSTR": _term_unavailable("TimeoutError"),
            "SWR": _term_unavailable("TimeoutError"),
            "LPASS_MACRO": _term_unavailable("TimeoutError"),
            "LPASS": _term_unavailable("TimeoutError"),
        },
        status="unavailable",
        error_class="all_swi_queries_failed",
    )
    source = {"present": True, "master_count": 4, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "authority_unavailable"
    assert row.warning is False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # citation still recorded so provenance is never silently empty
    assert row.citations, "citations must not be empty even when authority unavailable"
    assert row.review_actions and "re-run collector" in row.review_actions[0]
    print("PASS: swi_search_swi unavailable → NOT_CROSS_CHECKABLE (authority_unavailable)")


# ── (g) Determinism ─────────────────────────────────────────────────────────


def test_deterministic_across_calls() -> None:
    """T2 is a pure function: identical input → identical output (byte-equal to_dict)."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok(
                [{"name": "SWR_MSTR_WSA0"}, {"name": "SWR_MSTR_WSA1"}]
            ),
            "SWR_MSTR": _term_ok([{"name": "SWR_MSTR_RX"}, {"name": "SWR_MSTR_TX"}]),
            "SWR": _term_ok([{"name": "SWR_MSTR_WSA0"}]),  # dup
        }
    )
    source = {"present": True, "master_count": 4, "ambiguous": False}
    a = [r.to_dict() for r in track_t2(snapshot=snap, source=source, kb=None)]
    b = [r.to_dict() for r in track_t2(snapshot=snap, source=source, kb=None)]
    assert a == b, "T2 must be deterministic across repeated calls"
    # also assert the count landed at 4 (dedup across terms) so we're not
    # asserting determinism on an accidentally-trivial output
    assert a[0]["authority"]["value"] == {"soundwire_master_count": 4}
    assert a[0]["verdict"] == "MATCH"
    print("PASS: T2 is deterministic across repeated calls (4 = 4 with dedup)")


# ── Extra contract sanity ───────────────────────────────────────────────────


def test_missing_swi_tool_entry_is_authority_unavailable() -> None:
    """No swi_search_swi tool entry at all → treated as unavailable."""
    snap = {
        "chip": "nord",
        "provenance": {"tls": {"verify": True, "ssl_cert_file": "/x"}, "readonly_tools": []},
        "tools": {},
    }
    source = {"present": True, "master_count": 4, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    assert rows[0].verdict == "NOT_CROSS_CHECKABLE"
    assert rows[0].coverage_gap_reason == "authority_unavailable"
    print("PASS: missing swi_search_swi tool entry → authority_unavailable")


def test_source_wrapper_key_soundwire_is_unwrapped() -> None:
    """Source may wrap the soundwire dict under a 'soundwire' key."""
    snap = _swi_snap(None)  # all terms empty → catalog count = 0
    source = {"soundwire": {"present": False, "master_count": 0, "ambiguous": False}}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    assert rows[0].verdict == "MATCH"
    assert rows[0].confidence == "high"
    print("PASS: source wrapped under 'soundwire' key is unwrapped correctly")


def test_partial_term_failure_still_counts_healthy_terms() -> None:
    """One term fails, other terms healthy → count over the healthy terms only."""
    snap = _swi_snap(
        {
            "SOUNDWIRE_MASTER": _term_ok(
                [{"name": "SWR_MSTR_WSA0"}, {"name": "SWR_MSTR_WSA1"}]
            ),
            "SWR_MSTR": _term_unavailable("TimeoutError"),  # this one dropped
            "SWR": _term_ok([{"name": "SWR_MSTR_WSA0"}]),  # dup
        }
    )
    source = {"present": True, "master_count": 2, "ambiguous": False}
    rows = track_t2(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "MATCH"
    assert row.authority["value"] == {"soundwire_master_count": 2}
    # SWR_MSTR should NOT appear in the citation (it wasn't healthy)
    assert "SWR_MSTR" not in row.citations[0]
    assert "SOUNDWIRE_MASTER" in row.citations[0] and "SWR" in row.citations[0]
    print("PASS: partial term failure — count uses only healthy terms (2 = 2)")


def main() -> None:
    # WP5 requirement 5, tests a–g
    test_nord_i2s_only_zero_equals_zero_is_match()               # a
    test_eliza_four_equals_four_is_match()                       # b
    test_counts_differ_is_disagree_with_authority()              # c
    test_source_ambiguous_is_not_cross_checkable()               # d
    test_swi_term_at_cap_downgrades_to_provisional()             # e
    test_swi_unavailable_is_not_cross_checkable()                # f
    test_deterministic_across_calls()                            # g
    # extra contract sanity (not required by WP5 but pattern-parity with T1)
    test_missing_swi_tool_entry_is_authority_unavailable()
    test_source_wrapper_key_soundwire_is_unwrapped()
    test_partial_term_failure_still_counts_healthy_terms()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
