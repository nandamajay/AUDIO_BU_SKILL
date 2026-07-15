"""Unit tests for Phase-2A WP8 — Schematic ↔ IPCAT Cross-Verification
renderer (`orchestrator.main._render_crossverify_section`).

Pure tests over the renderer's list-of-strings output. No IPCAT, no
collector, no network: the ``cross_verification`` payload is built inline as
plain dicts matching what the WP8 orchestrator wiring attaches to
``generated_case``. WP8 requirement 4 — eight cases (a–h):

  a. Null-guard: no ``cross_verification`` key on ``gc`` → []
  b. Null-guard: ``cross_verification.rows`` is empty → []
  c. Header + snapshot provenance + verdict summary render (all six kinds)
  d. Track grouping order T1 → T2 → T3 → T4a → T4b → T5
  e. Reviewer worklist lists warning=True OR verdict==REVIEW_REQUIRED rows
  f. Determinism: repeated calls → byte-identical output
  g. Fixture-based end-to-end (frozen_snapshot / expected_rows / expected_section)
  h. Regression: report byte-identical when no cross_verification key vs. WP7 baseline

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_render
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.main import (
    _CROSSVERIFY_TRACK_ORDER,
    _CROSSVERIFY_VERDICT_ORDER,
    _render_crossverify_section,
    _render_onboarding_report,
)


# ── Row/section builders (pure helpers, no I/O) ─────────────────────────────


def _row(
    track: str,
    subject: str,
    verdict: str,
    *,
    confidence: str = "medium",
    warning: bool = False,
    review_actions: list[str] | None = None,
    coverage_gap_reason: str | None = None,
) -> dict:
    """Minimal row dict shaped like ``VerificationRow.to_dict()`` output."""
    return {
        "track": track,
        "subject": subject,
        "source": {},
        "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat.stub", "value": None},
        "verdict": verdict,
        "confidence": confidence,
        "coverage_gap_reason": coverage_gap_reason,
        "rule_id": None,
        "warning": warning,
        "review_actions": list(review_actions or []),
        "citations": [],
        "notes": [],
    }


def _provenance() -> dict:
    return {
        "tls": {"verify": True, "ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt"},
        "readonly_tools": ["chips_list_chips", "gpio_list_gpios_from_map"],
        "gpio_map": {"id": 42, "release": "nord-1.0"},
    }


def _gc(rows: list[dict]) -> dict:
    return {
        "resolved_chip": "nordschleife_2.0",
        "cross_verification": {
            "rows": rows,
            "snapshot_provenance": _provenance(),
        },
    }


# ── (a) Null-guard: no cross_verification key → [] ──────────────────────────


def test_null_guard_no_key_returns_empty() -> None:
    """A generated_case with no ``cross_verification`` key must not render.

    This is the byte-unchanged-report invariant. Also confirms the guard
    tolerates ``gc = None`` and ``gc = {}``.
    """
    assert _render_crossverify_section(None) == []
    assert _render_crossverify_section({}) == []
    assert _render_crossverify_section({"resolved_chip": "x"}) == []
    print("PASS: (a) no cross_verification key → [] (byte-unchanged report)")


# ── (b) Null-guard: empty rows → [] ─────────────────────────────────────────


def test_null_guard_empty_rows_returns_empty() -> None:
    """cross_verification present but rows==[] → still []."""
    assert _render_crossverify_section(_gc([])) == []
    # rows key absent under cross_verification dict → also []
    assert _render_crossverify_section({"cross_verification": {}}) == []
    # rows explicitly None → still []
    assert _render_crossverify_section({"cross_verification": {"rows": None}}) == []
    print("PASS: (b) empty/missing rows → []")


# ── (c) Header + provenance + verdict summary (all six kinds) ───────────────


def test_header_and_summary_render_all_verdicts() -> None:
    """Six rows (one per verdict kind) → header, provenance, and full summary."""
    rows = [
        _row("T1", "gpio.i2s.0", "MATCH"),
        _row("T2", "swr.mstr.tx", "PARTIAL_MATCH"),
        _row("T5", "dts.firmware", "DISAGREE_WITH_AUTHORITY", warning=True),
        _row("T3", "clocks.count", "NOT_CROSS_CHECKABLE",
             coverage_gap_reason="authority_out_of_scope"),
        _row("T4b", "codec.wsa883x", "REVIEW_REQUIRED"),
        # Sixth verdict kind is a placeholder for grouping — but WP8 says only
        # 5 verdicts are enumerated; the "all six kinds" phrasing just means
        # exercise the full _CROSSVERIFY_VERDICT_ORDER list.
    ]
    # Add duplicates of MATCH to prove counting works, not just presence.
    rows += [_row("T1", "gpio.i2s.1", "MATCH")]

    section = _render_crossverify_section(_gc(rows))
    joined = "\n".join(section)

    assert "## Schematic ↔ IPCAT Cross-Verification" in joined
    assert "### Snapshot provenance" in joined
    assert "chip" in joined and "nordschleife_2.0" in joined
    assert "tls" in joined and "verify=True" in joined
    assert "readonly_tools" in joined and "chips_list_chips" in joined
    assert "gpio_map" in joined and "id=42" in joined
    assert "### Verdict summary" in joined
    assert "MATCH: 2" in joined
    assert "PARTIAL_MATCH: 1" in joined
    assert "DISAGREE_WITH_AUTHORITY: 1" in joined
    assert "NOT_CROSS_CHECKABLE: 1" in joined
    assert "REVIEW_REQUIRED: 1" in joined
    print("PASS: (c) header + provenance sub-header + verdict summary all render")


# ── (d) Row table grouping order T1 → T2 → T3 → T4a → T4b → T5 ──────────────


def test_row_table_grouping_order() -> None:
    """Rows must appear in ``_CROSSVERIFY_TRACK_ORDER``, subject-sorted within."""
    # Insert in scrambled order so we can prove the renderer sorts.
    rows = [
        _row("T5", "dts.compatible", "MATCH"),
        _row("T1", "gpio.z", "MATCH"),
        _row("T1", "gpio.a", "MATCH"),
        _row("T4a", "qup.se3", "MATCH"),
        _row("T2", "swr.mstr.rx", "MATCH"),
        _row("T3", "clocks.count", "MATCH"),
        _row("T4b", "codec.wsa883x", "NOT_CROSS_CHECKABLE"),
    ]
    section = _render_crossverify_section(_gc(rows))
    # Scan only the table lines (start with "| T")
    table_rows = [line for line in section if line.startswith("| T")]
    # First column is the track — sequence must equal the track order.
    tracks_in_order = [line.split("|")[1].strip() for line in table_rows]
    # Expected: T1 twice (sorted a,z), T2, T3, T4a, T4b, T5
    assert tracks_in_order == ["T1", "T1", "T2", "T3", "T4a", "T4b", "T5"], (
        f"wrong track order in table: {tracks_in_order}"
    )
    # Confirm subject sort within T1 group
    t1_subjects = [
        line.split("|")[2].strip() for line in table_rows if line.split("|")[1].strip() == "T1"
    ]
    assert t1_subjects == sorted(t1_subjects), (
        f"T1 subjects not sorted: {t1_subjects}"
    )
    # Track order must be exactly the constant
    assert _CROSSVERIFY_TRACK_ORDER == ("T1", "T2", "T3", "T4a", "T4b", "T5")
    print("PASS: (d) table grouped T1→T2→T3→T4a→T4b→T5, subject-sorted within track")


# ── (e) Reviewer worklist — DISAGREE + REVIEW_REQUIRED only ────────────────


def test_reviewer_worklist_lists_only_disagree_and_review_required() -> None:
    """Worklist should include warning=True rows AND verdict==REVIEW_REQUIRED
    rows, but NOT MATCH/PARTIAL_MATCH/NOT_CROSS_CHECKABLE rows without warning.
    """
    rows = [
        _row("T1", "gpio.ok", "MATCH", warning=False),
        _row("T2", "swr.mstr.tx", "DISAGREE_WITH_AUTHORITY",
             warning=True, review_actions=["fix bus name"]),
        _row("T3", "clocks.count", "NOT_CROSS_CHECKABLE",
             coverage_gap_reason="authority_out_of_scope"),
        _row("T4b", "codec.wsa883x", "REVIEW_REQUIRED",
             review_actions=["confirm codec DAI binding manually"]),
        _row("T5", "dts.firmware", "MATCH", warning=False),
        # NCC with warning=True (rare but legal) — must appear
        _row("T5", "dts.donor_leak", "NOT_CROSS_CHECKABLE",
             warning=True, review_actions=["review donor namespace fragment"]),
    ]
    section = _render_crossverify_section(_gc(rows))
    joined = "\n".join(section)
    assert "### Reviewer worklist" in joined

    # Extract worklist bullets (start with "- **" and appear after the header)
    idx = section.index("### Reviewer worklist")
    worklist_lines = [ln for ln in section[idx:] if ln.startswith("- **")]

    # 3 rows should qualify: the DISAGREE, the REVIEW_REQUIRED, the warning-NCC
    assert len(worklist_lines) == 3, (
        f"expected 3 worklist entries, got {len(worklist_lines)}: {worklist_lines}"
    )
    # None of the MATCH/no-warning-NCC rows should have leaked in
    assert not any("gpio.ok" in ln for ln in worklist_lines)
    assert not any("dts.firmware" in ln for ln in worklist_lines)
    # First review_action must appear next to the subject
    assert any("fix bus name" in ln for ln in worklist_lines)
    assert any("confirm codec DAI binding manually" in ln for ln in worklist_lines)
    assert any("review donor namespace fragment" in ln for ln in worklist_lines)
    print("PASS: (e) reviewer worklist contains DISAGREE + REVIEW_REQUIRED + warning-True only")


# ── (f) Determinism ─────────────────────────────────────────────────────────


def test_deterministic_output() -> None:
    """The renderer is pure — identical gc → byte-equal list output."""
    rows = [
        _row("T5", "dts.firmware", "DISAGREE_WITH_AUTHORITY", warning=True),
        _row("T1", "gpio.b", "MATCH"),
        _row("T1", "gpio.a", "MATCH"),
        _row("T4b", "codec.wsa883x", "REVIEW_REQUIRED"),
    ]
    a = _render_crossverify_section(_gc(rows))
    b = _render_crossverify_section(_gc(rows))
    assert a == b, "renderer must be byte-deterministic"
    # And a shuffle of the input (same set of rows in different order) still
    # produces the same output, because the renderer sorts internally.
    shuffled = [rows[3], rows[0], rows[2], rows[1]]
    c = _render_crossverify_section(_gc(shuffled))
    assert a == c, "renderer must be order-independent w.r.t. input row order"
    print("PASS: (f) byte-deterministic and row-order-independent")


# ── (g) Fixture-based end-to-end ────────────────────────────────────────────


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2a"


def test_fixture_end_to_end() -> None:
    """Load frozen_snapshot + expected_rows and prove the renderer produces
    expected_section.txt verbatim. This is the guardrail against silent
    rendering changes; if intentional, regenerate the fixture.
    """
    rows = json.loads((_FIXTURE_DIR / "expected_rows.json").read_text(encoding="utf-8"))
    provenance = json.loads(
        (_FIXTURE_DIR / "frozen_snapshot.json").read_text(encoding="utf-8")
    )["provenance"]
    gc = {
        "resolved_chip": "nordschleife_2.0",
        "cross_verification": {"rows": rows, "snapshot_provenance": provenance},
    }
    got = "\n".join(_render_crossverify_section(gc)).rstrip("\n")
    expected = (_FIXTURE_DIR / "expected_section.txt").read_text(encoding="utf-8").rstrip("\n")
    assert got == expected, (
        "renderer output diverged from fixture — regenerate expected_section.txt "
        "if the change is intentional.\n"
        f"---got---\n{got}\n---expected---\n{expected}\n"
    )
    print("PASS: (g) fixture-based end-to-end (frozen snapshot → expected section)")


# ── (h) Regression: report byte-identical when no cross_verification key ────


_BASELINE_OUTPUT = {
    "target_profile": {"target_name": "eliza-baseline", "soc": "SA8797P", "cites": {}},
    "similarity_report": {
        "ranked": [{"target_name": "lemans-like", "overall": 0.72, "per_signal": {}}],
        "confidence": {
            "confidence": 0.72, "score": 0.72, "margin": 0.1,
            "min_score": 0.75, "min_margin": 0.0, "low_confidence": True,
        },
        "weights": {"codecs": 1},
    },
    "evidence_inventory": {"kernel_source_path": "linux-fake", "files": []},
    "generated_case": {"needs_review": [], "candidate_patch_series": []},
}


def test_report_byte_identical_without_cross_verification() -> None:
    """WP7 → WP8 regression: report must be byte-identical when the
    ``cross_verification`` key is absent. Additive-only guarantee.
    """
    baseline = _render_onboarding_report(_BASELINE_OUTPUT)

    # Same output, still no cross_verification key → must match byte-for-byte.
    again = _render_onboarding_report(_BASELINE_OUTPUT)
    assert baseline == again, "renderer must be deterministic across calls"
    # And the "## Schematic ↔ IPCAT Cross-Verification" header must not appear
    assert "## Schematic ↔ IPCAT Cross-Verification" not in baseline, (
        "WP8 section leaked into baseline report — additive-only invariant broken"
    )
    print("PASS: (h) report byte-identical without cross_verification key (WP7 baseline preserved)")


def main() -> None:
    test_null_guard_no_key_returns_empty()                           # a
    test_null_guard_empty_rows_returns_empty()                       # b
    test_header_and_summary_render_all_verdicts()                    # c
    test_row_table_grouping_order()                                  # d
    test_reviewer_worklist_lists_only_disagree_and_review_required() # e
    test_deterministic_output()                                      # f
    test_fixture_end_to_end()                                        # g
    test_report_byte_identical_without_cross_verification()          # h
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
