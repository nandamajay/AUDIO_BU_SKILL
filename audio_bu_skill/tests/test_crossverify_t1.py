"""Unit tests for Phase-2A WP4 — Track T1 (GPIO / pinmux validation).

Pure tests over ``orchestrator.reasoning.crossverify.track_t1``. No IPCAT,
no collector, no network — snapshots are built inline as plain dicts.

Covers the five verdict shapes the Phase-2A V2 spec (§2/T1, §3.1) requires:

  1. MATCH                     — pin exists, exact (pin, function) match
                                 with agreeing name, DIRECT parameterized
                                 authority → confidence=high;
  2. PARTIAL_MATCH             — pin exists, (pin, function) match, but the
                                 authority's name for that alternate is a
                                 different signal (the "wrong fn number"
                                 shape: GPIO 61 aud_intfc0_data2 fn1 vs
                                 aud_intfc10_clk fn2 — schematic claims fn2
                                 with name aud_intfc0_data2);
  3. DISAGREE_WITH_AUTHORITY   — pin exists but cannot mux the claimed
                                 function under any alternate (name doesn't
                                 land on any alternate either);
  4. REVIEW_REQUIRED           — pin number absent from the authority's
                                 pinmux (silicon does not expose the pin);
  5. NOT_CROSS_CHECKABLE       — neither DIRECT nor fallback authority tool
                                 answered → coverage_gap_reason=authority_unavailable,
                                 confidence=none.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t1``
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.crossverify import track_t1
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Snapshot builders (pure helpers, no I/O) ────────────────────────────────

GPIO_MAP_RELEASE = "nordau_io v1.2 ECO F03 Release"


def _tool_ok(payload: Any) -> dict[str, Any]:
    """Minimal ``status=ok`` tool entry. ``result_digest`` isn't consulted by T1."""
    return {"status": "ok", "payload": payload, "result_digest": "deadbeef"}


def _tool_unavailable(error_class: str = "TimeoutError") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "payload": None,
        "result_digest": None,
        "error_class": error_class,
    }


def _snap(
    *,
    direct_rows: list[dict[str, Any]] | None,
    fallback_rows: list[dict[str, Any]] | None,
    release: str | None = GPIO_MAP_RELEASE,
    gpio_map_id: int | None = 8240,
) -> dict[str, Any]:
    """Build a minimal collector-shape snapshot with just the GPIO surface.

    ``direct_rows=None`` → gpio_get_gpio_map + gpio_list_gpios_from_map are
    both ``unavailable``; ``fallback_rows=None`` → gpio_list_tlmm_gpios is
    ``unavailable``. Any other tool entries the T1 track never consults are
    omitted — the track only reads the three GPIO surface tools.
    """
    tools: dict[str, dict[str, Any]] = {}
    if direct_rows is None:
        tools["gpio_get_gpio_map"] = _tool_unavailable("RuntimeError")
        tools["gpio_list_gpios_from_map"] = _tool_unavailable("missing_gpio_map_id")
    else:
        tools["gpio_get_gpio_map"] = _tool_ok(
            {
                "id": gpio_map_id,
                "group": {"name": "TLMM"},
                "chipio_release": {"name": release} if release else {},
            }
        )
        tools["gpio_list_gpios_from_map"] = _tool_ok(direct_rows)

    if fallback_rows is None:
        tools["gpio_list_tlmm_gpios"] = _tool_unavailable("RuntimeError")
    else:
        tools["gpio_list_tlmm_gpios"] = _tool_ok(fallback_rows)

    return {
        "chip": "nordschleife_2.0",
        "provenance": {
            "tls": {"verify": True, "ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt"},
            "readonly_tools": [
                "gpio_get_gpio_map",
                "gpio_list_gpios_from_map",
                "gpio_list_tlmm_gpios",
            ],
            "gpio_map": {"id": gpio_map_id, "release": release},
        },
        "tools": tools,
    }


def _by_subject(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    return {r.subject: r for r in rows}


# ── (1) MATCH — GPIO 57 aud_intfc0_clk fn=1, DIRECT authority ──────────────


def test_match_aud_intfc0_clk_gpio57_fn1() -> None:
    """DIRECT parameterized path answered — MATCH at high confidence."""
    snap = _snap(
        direct_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
        ],
        # Fallback present but the DIRECT path should win.
        fallback_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
        ],
    )
    source = [{"pin": 57, "function": 1, "name": "aud_intfc0_clk"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.track == "T1"
    assert row.subject == "aud_intfc0_clk (GPIO 57)"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # DIRECT authority
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == "ipcat.gpio_list_gpios_from_map"
    assert row.authority["value"] == {
        "pin": 57,
        "function": 1,
        "name": "aud_intfc0_clk",
    }
    # provenance recorded
    assert f"gpio_map:{GPIO_MAP_RELEASE}" in row.citations
    print("PASS: MATCH — aud_intfc0_clk GPIO 57 fn=1 via DIRECT authority, confidence=high")


def test_match_fallback_only_confidence_medium() -> None:
    """Only the name-heuristic fallback answered — MATCH at medium confidence."""
    snap = _snap(
        direct_rows=None,  # gpio_list_gpios_from_map unavailable
        fallback_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
        ],
    )
    source = [{"pin": 57, "function": 1, "name": "aud_intfc0_clk"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "MATCH"
    assert row.confidence == "medium"  # fallback lookup → medium
    assert row.authority["origin"] == "ipcat.gpio_list_tlmm_gpios"
    print("PASS: MATCH via fallback authority → confidence=medium")


# ── (2) PARTIAL_MATCH — GPIO 61 aud_intfc0_data2 fn1 vs aud_intfc10_clk fn2 ─


def test_partial_match_gpio61_mux_alt_wrong_function_index() -> None:
    """Schematic says fn=2 name=aud_intfc0_data2; authority has fn=1=aud_intfc0_data2, fn=2=aud_intfc10_clk.

    An alternate for (pin, function) exists, but the authority's name for
    that alternate is a different signal → PARTIAL_MATCH (wrong fn number,
    right identity).
    """
    snap = _snap(
        direct_rows=[
            {"name": "aud_intfc0_data2", "number": 61, "function": 1},
            {"name": "aud_intfc10_clk",  "number": 61, "function": 2},
        ],
        fallback_rows=[
            {"name": "aud_intfc0_data2", "number": 61, "function": 1},
            {"name": "aud_intfc10_clk",  "number": 61, "function": 2},
        ],
    )
    # Schematic uses fn=2 (wrong) with claimed name aud_intfc0_data2.
    source = [{"pin": 61, "function": 2, "name": "aud_intfc0_data2"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "PARTIAL_MATCH"
    assert row.warning is False  # PARTIAL_MATCH warning defaults False
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # DIRECT lookup answered
    assert row.authority["origin"] == "ipcat.gpio_list_gpios_from_map"
    # authority.value.function is the fn the schematic claimed (fn=2); its
    # authority-recorded name is aud_intfc10_clk (not the schematic's name).
    assert row.authority["value"]["function"] == 2
    assert row.authority["value"]["name"] == "aud_intfc10_clk"
    assert row.review_actions and "aud_intfc10_clk" in row.review_actions[0]
    print("PASS: PARTIAL_MATCH — GPIO 61 fn=2 muxes aud_intfc10_clk, not aud_intfc0_data2")


# ── (3) DISAGREE_WITH_AUTHORITY — function not muxable, name absent ────────


def test_disagree_function_not_muxable_and_name_not_in_alternates() -> None:
    """Pin exists but the claimed function and name are both absent from every alternate."""
    snap = _snap(
        direct_rows=[
            {"name": "some_other_signal_a", "number": 42, "function": 1},
            {"name": "some_other_signal_b", "number": 42, "function": 2},
            {"name": "some_other_signal_c", "number": 42, "function": 3},
        ],
        fallback_rows=None,
    )
    source = [{"pin": 42, "function": 5, "name": "totally_bogus_audio_sig"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True  # DISAGREE_WITH_AUTHORITY warns by default
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # DIRECT authority answered
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == "ipcat.gpio_list_gpios_from_map"
    # authority.value.alternates surfaces exactly what the silicon does support.
    alts = row.authority["value"]["alternates"]
    assert {a["name"] for a in alts} == {
        "some_other_signal_a",
        "some_other_signal_b",
        "some_other_signal_c",
    }
    assert row.review_actions and "cannot mux function 5" in row.review_actions[0]
    print("PASS: DISAGREE_WITH_AUTHORITY — pin 42 cannot mux fn=5 for 'totally_bogus_audio_sig'")


# ── (4) REVIEW_REQUIRED — pin number not exposed by silicon ────────────────


def test_review_required_pin_absent_from_authority() -> None:
    """Schematic cites pin 9999 which the authority does not list at all."""
    snap = _snap(
        direct_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
        ],
        fallback_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
        ],
    )
    source = [{"pin": 9999, "function": 1, "name": "phantom_signal"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "REVIEW_REQUIRED"
    assert row.warning is True  # REVIEW_REQUIRED warns by default
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"  # DIRECT authority spoke (about a different pin)
    assert row.review_actions and "not exposed by TLMM authority" in row.review_actions[0]
    assert row.notes and "no rows for pin 9999" in row.notes[0]
    print("PASS: REVIEW_REQUIRED — pin 9999 absent from TLMM authority")


# ── (5) NOT_CROSS_CHECKABLE — authority_unavailable ────────────────────────


def test_not_cross_checkable_authority_unavailable() -> None:
    """Both DIRECT and fallback authorities are unavailable → coverage_gap_reason=authority_unavailable."""
    snap = _snap(
        direct_rows=None,      # gpio_list_gpios_from_map unavailable
        fallback_rows=None,    # gpio_list_tlmm_gpios also unavailable
        release=None,          # missing release → placeholder citation
        gpio_map_id=None,
    )
    source = [{"pin": 57, "function": 1, "name": "aud_intfc0_clk"}]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "authority_unavailable"
    assert row.warning is False  # NOT_CROSS_CHECKABLE warning defaults False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # placeholder citation still recorded so provenance is never silently empty
    assert row.citations == ["gpio_map:<release_unknown>"]
    print("PASS: NOT_CROSS_CHECKABLE — both authorities unavailable, coverage_gap_reason=authority_unavailable")


# ── contract sanity ────────────────────────────────────────────────────────


def test_empty_source_yields_no_rows() -> None:
    """No pin claims → no rows, no crash."""
    snap = _snap(direct_rows=[], fallback_rows=[])
    assert track_t1(snapshot=snap, source=[], kb=None) == []
    assert track_t1(snapshot=snap, source=None, kb=None) == []
    assert track_t1(snapshot=snap, source={"audio_pins": []}, kb=None) == []
    print("PASS: empty/None source yields [] (no rows, no crash)")


def test_source_dict_shape_accepted() -> None:
    """Source may be a dict wrapping the list under ``audio_pins``/``gpios``/``pins``."""
    snap = _snap(
        direct_rows=[{"name": "aud_intfc0_clk", "number": 57, "function": 1}],
        fallback_rows=None,
    )
    rows = track_t1(
        snapshot=snap,
        source={"audio_pins": [{"pin": 57, "function": 1, "name": "aud_intfc0_clk"}]},
        kb=None,
    )
    assert len(rows) == 1 and rows[0].verdict == "MATCH"
    print("PASS: source dict with 'audio_pins' key is unwrapped correctly")


def test_provenance_citation_on_every_row() -> None:
    """Every T1 row must carry the ``gpio_map:<release>`` citation (V2 requirement 6)."""
    snap = _snap(
        direct_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
            {"name": "aud_intfc0_data2", "number": 61, "function": 1},
            {"name": "aud_intfc10_clk",  "number": 61, "function": 2},
            {"name": "some_other_signal_a", "number": 42, "function": 1},
        ],
        fallback_rows=None,
    )
    source = [
        {"pin": 57, "function": 1, "name": "aud_intfc0_clk"},      # MATCH
        {"pin": 61, "function": 2, "name": "aud_intfc0_data2"},   # PARTIAL_MATCH
        {"pin": 42, "function": 5, "name": "bogus"},               # DISAGREE
        {"pin": 9999, "function": 1, "name": "phantom"},           # REVIEW_REQUIRED
    ]
    rows = track_t1(snapshot=snap, source=source, kb=None)
    assert len(rows) == 4
    expected = f"gpio_map:{GPIO_MAP_RELEASE}"
    for r in rows:
        assert expected in r.citations, f"{r.subject} missing provenance citation"
    print("PASS: every T1 row carries the gpio_map:<release> citation")


def test_deterministic_across_calls() -> None:
    """T1 is a pure function: identical input → identical output."""
    snap = _snap(
        direct_rows=[
            {"name": "aud_intfc0_clk", "number": 57, "function": 1},
            {"name": "aud_intfc0_data2", "number": 61, "function": 1},
            {"name": "aud_intfc10_clk",  "number": 61, "function": 2},
        ],
        fallback_rows=None,
    )
    source = [
        {"pin": 57, "function": 1, "name": "aud_intfc0_clk"},
        {"pin": 61, "function": 2, "name": "aud_intfc0_data2"},
    ]
    a = [r.to_dict() for r in track_t1(snapshot=snap, source=source, kb=None)]
    b = [r.to_dict() for r in track_t1(snapshot=snap, source=source, kb=None)]
    assert a == b, "T1 must be deterministic across repeated calls"
    print("PASS: T1 is deterministic across repeated calls")


def main() -> None:
    test_match_aud_intfc0_clk_gpio57_fn1()
    test_match_fallback_only_confidence_medium()
    test_partial_match_gpio61_mux_alt_wrong_function_index()
    test_disagree_function_not_muxable_and_name_not_in_alternates()
    test_review_required_pin_absent_from_authority()
    test_not_cross_checkable_authority_unavailable()
    test_empty_source_yields_no_rows()
    test_source_dict_shape_accepted()
    test_provenance_citation_on_every_row()
    test_deterministic_across_calls()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
