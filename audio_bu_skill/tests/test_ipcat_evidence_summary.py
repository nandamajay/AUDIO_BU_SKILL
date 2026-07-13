"""Unit tests for Fix #4 (Benchmark Readiness): IPCAT coverage clarity.

Confirms _ipcat_evidence_summary() combines the two signals it has access to --
QGenie's self-reported analysis["ipcat_findings"] (schema 1.2.0, optional) and
the orchestrator's own deterministic evidence_files/ipcat_mcp_requested facts
-- into one of a small set of clear statuses, and never raises on a missing
self-report (older/non-compliant QGenie responses).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_evidence_summary
(or: python3 audio_bu_skill/tests/test_ipcat_evidence_summary.py)
"""

from __future__ import annotations

from orchestrator.runners.target_onboarding_runner import _ipcat_evidence_summary


def test_mcp_returned_target_specific() -> None:
    analysis = {"ipcat_findings": {"queried": True, "returned_target_specific": True}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "target_specific", out
    assert out["mcp_returned_target_specific"] is True
    print("PASS: MCP self-report of target-specific results -> status=target_specific")


def test_offline_files_present_counts_as_target_specific_even_without_self_report() -> None:
    analysis = {}  # no self-report at all (older/non-compliant QGenie response)
    files = ["audio_bu_skill/targets/eliza-like/evidence/ipcat/HPG_eliza_specific.pdf"]
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=files, ipcat_mcp_requested=False)
    assert out["status"] == "target_specific", out
    assert out["offline_files_present"] is True
    assert out["offline_file_count"] == 1
    print("PASS: offline-cached evidence/ipcat/ files alone -> status=target_specific, "
          "no self-report required, never raises on missing analysis['ipcat_findings']")


def test_mcp_generic_only() -> None:
    analysis = {"ipcat_findings": {"queried": True, "returned_generic_only": True,
                                    "notes": "only generic HPG chapters"}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "generic_only", out
    assert out["self_report_notes"] == "only generic HPG chapters"
    print("PASS: MCP self-report of generic-only results -> status=generic_only")


def test_mcp_queried_but_no_explicit_generic_or_specific_flag() -> None:
    """Self-report says queried=True but leaves both target_specific and
    generic_only false/absent -- still a soft 'unhelpful' signal, not fabricated
    as confirmed-good."""
    analysis = {"ipcat_findings": {"queried": True}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "generic_only", out
    print("PASS: MCP queried with no target-specific/generic-only signal -> treated as generic_only, "
          "never silently upgraded to target_specific")


def test_queried_no_result() -> None:
    analysis = {}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "queried_no_result", out
    print("PASS: ipcat_mcp requested but no offline files and no self-report -> status=queried_no_result")


def test_unavailable() -> None:
    analysis = {}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=False)
    assert out["status"] == "unavailable", out
    print("PASS: no offline files, no MCP request, no self-report -> status=unavailable")


def test_never_raises_on_malformed_self_report() -> None:
    analysis = {"ipcat_findings": None}  # self-report key present but null
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=False)
    assert out["status"] == "unavailable", out
    print("PASS: analysis['ipcat_findings'] = None degrades gracefully, never raises")


def main() -> None:
    test_mcp_returned_target_specific()
    test_offline_files_present_counts_as_target_specific_even_without_self_report()
    test_mcp_generic_only()
    test_mcp_queried_but_no_explicit_generic_or_specific_flag()
    test_queried_no_result()
    test_unavailable()
    test_never_raises_on_malformed_self_report()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
