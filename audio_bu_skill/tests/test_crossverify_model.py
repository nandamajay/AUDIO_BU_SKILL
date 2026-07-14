"""Unit tests for Phase-2A WP2 — VerificationRow model.

Pure-value-object tests over orchestrator.reasoning.crossverify_model — no
orchestrator run, no network, no fixtures. Covers:
  * valid rows for MATCH, DISAGREE_WITH_AUTHORITY, and NOT_CROSS_CHECKABLE
    (authority_out_of_scope);
  * enum validation: illegal track / verdict / authority.strength / confidence
    each raise ValueError;
  * the coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE invariant (both directions);
  * warning defaults derived from the verdict, and explicit overrides;
  * deterministic to_dict() — repeated calls equal, stable key order, and
    json.dumps(..., sort_keys=True) succeeds.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_model
"""

from __future__ import annotations

import json

from orchestrator.reasoning.crossverify_model import (
    AUTHORITY_STRENGTHS,
    CONFIDENCE_LEVELS,
    COVERAGE_GAP_REASONS,
    TRACKS,
    VERDICTS,
    VerificationRow,
)


def _expect_value_error(fn, label: str) -> None:
    try:
        fn()
    except ValueError:
        print(f"PASS: {label} raises ValueError")
        return
    raise AssertionError(f"FAIL: {label} did not raise ValueError")


# ── valid rows ───────────────────────────────────────────────────────────────

def test_valid_match_row() -> None:
    row = VerificationRow(
        track="T1",
        subject="aud_intfc0_clk (GPIO 57)",
        verdict="MATCH",
        source={"pin": 57, "function": 1},
        authority={"strength": "IPCAT_DIRECT", "origin": "ipcat.gpio_list_tlmm_gpios"},
        confidence="high",
    )
    d = row.to_dict()
    assert d["verdict"] == "MATCH"
    assert d["warning"] is False, "MATCH warning must default False"
    assert d["coverage_gap_reason"] is None
    assert d["authority"]["strength"] == "IPCAT_DIRECT"
    print("PASS: valid MATCH row (warning defaults False, no coverage gap)")


def test_valid_disagree_row() -> None:
    row = VerificationRow(
        track="T5",
        subject="adsp compatible namespace",
        verdict="DISAGREE_WITH_AUTHORITY",
        source="qcom,sa8775p-adsp-pas",
        authority={"strength": "KB_RULE", "origin": "kb.dts_namespace"},
        confidence="high",
        review_actions=["correct compatible to the SA8797P namespace"],
    )
    d = row.to_dict()
    assert d["warning"] is True, "DISAGREE_WITH_AUTHORITY warning must default True"
    assert d["coverage_gap_reason"] is None
    print("PASS: valid DISAGREE_WITH_AUTHORITY row (warning defaults True)")


def test_valid_not_cross_checkable_out_of_scope_row() -> None:
    row = VerificationRow(
        track="T4b",
        subject="PCM1681 ↔ controller binding",
        verdict="NOT_CROSS_CHECKABLE",
        coverage_gap_reason="authority_out_of_scope",
        authority={"strength": "UNAVAILABLE", "origin": "none"},
        confidence="none",
        review_actions=["validate codec↔controller binding against schematic/DTS"],
    )
    d = row.to_dict()
    assert d["coverage_gap_reason"] == "authority_out_of_scope"
    assert d["warning"] is False, "NOT_CROSS_CHECKABLE warning must default False"
    assert d["authority"]["strength"] == "UNAVAILABLE"
    print("PASS: valid NOT_CROSS_CHECKABLE row with authority_out_of_scope")


# ── enum validation ──────────────────────────────────────────────────────────

def test_invalid_track_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(track="T4", subject="x", verdict="MATCH"),
        "illegal track 'T4'",
    )


def test_invalid_verdict_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(track="T1", subject="x", verdict="AGREE"),
        "illegal verdict 'AGREE'",
    )


def test_invalid_authority_strength_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(
            track="T1",
            subject="x",
            verdict="MATCH",
            authority={"strength": "GUESS"},
        ),
        "illegal authority.strength 'GUESS'",
    )


def test_invalid_confidence_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(
            track="T1", subject="x", verdict="MATCH", confidence="low"
        ),
        "illegal confidence 'low'",
    )


# ── coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE ────────────────────────────────

def test_not_cross_checkable_without_reason_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(
            track="T2", subject="soundwire masters", verdict="NOT_CROSS_CHECKABLE"
        ),
        "NOT_CROSS_CHECKABLE without coverage_gap_reason",
    )


def test_match_with_coverage_gap_reason_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(
            track="T1",
            subject="x",
            verdict="MATCH",
            coverage_gap_reason="authority_out_of_scope",
        ),
        "MATCH with coverage_gap_reason",
    )


def test_illegal_coverage_gap_reason_raises() -> None:
    _expect_value_error(
        lambda: VerificationRow(
            track="T2",
            subject="x",
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="mystery",
        ),
        "illegal coverage_gap_reason 'mystery'",
    )


# ── warning defaults / overrides ─────────────────────────────────────────────

def test_review_required_warning_defaults_true() -> None:
    row = VerificationRow(track="T1", subject="pin 9999", verdict="REVIEW_REQUIRED")
    assert row.to_dict()["warning"] is True
    print("PASS: REVIEW_REQUIRED warning defaults True")


def test_partial_match_warning_defaults_false() -> None:
    row = VerificationRow(track="T4a", subject="QUP se_number", verdict="PARTIAL_MATCH")
    assert row.to_dict()["warning"] is False
    print("PASS: PARTIAL_MATCH warning defaults False")


def test_explicit_warning_override_wins() -> None:
    quiet = VerificationRow(
        track="T5", subject="x", verdict="DISAGREE_WITH_AUTHORITY", warning=False
    )
    loud = VerificationRow(track="T1", subject="x", verdict="MATCH", warning=True)
    assert quiet.to_dict()["warning"] is False, "explicit False must override default True"
    assert loud.to_dict()["warning"] is True, "explicit True must override default False"
    print("PASS: explicit warning override wins over verdict default")


# ── deterministic serialization ──────────────────────────────────────────────

def test_to_dict_deterministic_across_calls() -> None:
    row = VerificationRow(
        track="T3",
        subject="lpass_macro_instance",
        verdict="DISAGREE_WITH_AUTHORITY",
        source={"proposal": 2},
        authority={"strength": "IPCAT_DIRECT", "origin": "ipcat.swi_search_swi", "value": 4},
        confidence="high",
        citations=["swi:LPASS_RX_RX_MACRO", "swi:LPASS_TX_TX_MACRO"],
        notes=["proposal=2 vs catalog=4"],
    )
    first = row.to_dict()
    second = row.to_dict()
    assert first == second, "to_dict must be equal across repeated calls"
    assert list(first.keys()) == list(second.keys()), "key order must be stable"
    # mutating the returned dict must not affect the row.
    first["citations"].append("tampered")
    assert row.to_dict()["citations"] == [
        "swi:LPASS_RX_RX_MACRO",
        "swi:LPASS_TX_TX_MACRO",
    ], "returned lists must be copies, not shared references"
    print("PASS: to_dict() is deterministic and returns independent copies")


def test_json_dumps_sort_keys_succeeds() -> None:
    rows = [
        VerificationRow(track="T1", subject="pin", verdict="MATCH", confidence="high"),
        VerificationRow(
            track="T4b",
            subject="binding",
            verdict="NOT_CROSS_CHECKABLE",
            coverage_gap_reason="authority_out_of_scope",
        ),
    ]
    blob = json.dumps([r.to_dict() for r in rows], sort_keys=True)
    assert isinstance(blob, str) and blob, "json.dumps(sort_keys=True) must succeed"
    # round-trips cleanly.
    assert json.loads(blob)[1]["coverage_gap_reason"] == "authority_out_of_scope"
    print("PASS: json.dumps(to_dict(), sort_keys=True) succeeds and round-trips")


# ── enum-set sanity (guards against silent enum drift) ───────────────────────

def test_enum_sets_match_spec() -> None:
    assert TRACKS == {"T1", "T2", "T3", "T4a", "T4b", "T5"}
    assert VERDICTS == {
        "MATCH",
        "PARTIAL_MATCH",
        "DISAGREE_WITH_AUTHORITY",
        "NOT_CROSS_CHECKABLE",
        "REVIEW_REQUIRED",
    }
    assert AUTHORITY_STRENGTHS == {
        "IPCAT_DIRECT",
        "IPCAT_DERIVED",
        "KB_RULE",
        "UNAVAILABLE",
    }
    assert COVERAGE_GAP_REASONS == {
        "source_ambiguous",
        "authority_unavailable",
        "authority_out_of_scope",
        "insufficient_lanes",
        "revision_not_pinned",
    }
    assert CONFIDENCE_LEVELS == {"high", "medium", "provisional", "none"}
    print("PASS: enum sets match PHASE2A_SPECIFICATION_V2")


def main() -> None:
    test_valid_match_row()
    test_valid_disagree_row()
    test_valid_not_cross_checkable_out_of_scope_row()
    test_invalid_track_raises()
    test_invalid_verdict_raises()
    test_invalid_authority_strength_raises()
    test_invalid_confidence_raises()
    test_not_cross_checkable_without_reason_raises()
    test_match_with_coverage_gap_reason_raises()
    test_illegal_coverage_gap_reason_raises()
    test_review_required_warning_defaults_true()
    test_partial_match_warning_defaults_false()
    test_explicit_warning_override_wins()
    test_to_dict_deterministic_across_calls()
    test_json_dumps_sort_keys_succeeds()
    test_enum_sets_match_spec()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
