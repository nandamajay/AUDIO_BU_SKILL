"""Unit tests for IPCAT tri-state coverage status.

Confirms `_ipcat_evidence_summary()` maps its inputs (QGenie self-report +
orchestrator-observed offline_ipcat_files + ipcat_mcp_requested) to exactly
one of three trust states:

  LIVE_IPCAT_VERIFIED  — MCP self-reported target-specific evidence.
  CACHED_IPCAT_ONLY    — offline files present but MCP not verified live.
  NO_IPCAT_EVIDENCE    — neither.

Evidence-first mode: the caller MUST distinguish these. The prior 4-way
enum collapsed CACHED_IPCAT_ONLY into `target_specific`, silently
downgrading trust — that regression is guarded here.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_evidence_summary
"""

from __future__ import annotations

from orchestrator.runners.target_onboarding_runner import _ipcat_evidence_summary


# ── LIVE_IPCAT_VERIFIED ─────────────────────────────────────────────────────

def test_mcp_returned_target_specific_is_live_verified() -> None:
    analysis = {"ipcat_findings": {"queried": True, "returned_target_specific": True}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "LIVE_IPCAT_VERIFIED", out
    assert out["mcp_returned_target_specific"] is True
    print("PASS: MCP self-report of target-specific results -> status=LIVE_IPCAT_VERIFIED")


def test_mcp_target_specific_takes_precedence_over_cached() -> None:
    """Even with cached files, MCP live-verified is the higher-trust state."""
    analysis = {"ipcat_findings": {"queried": True, "returned_target_specific": True}}
    files = ["audio_bu_skill/targets/x/evidence/ipcat/HPG.pdf"]
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=files, ipcat_mcp_requested=True)
    assert out["status"] == "LIVE_IPCAT_VERIFIED", out
    print("PASS: MCP live-verified overrides cached — status=LIVE_IPCAT_VERIFIED")


# ── CACHED_IPCAT_ONLY ───────────────────────────────────────────────────────

def test_offline_files_without_live_mcp_is_cached_only() -> None:
    """The core silent-downgrade regression guard: cached files WITHOUT live
    MCP verification MUST NOT be reported as LIVE_IPCAT_VERIFIED."""
    analysis = {}
    files = ["audio_bu_skill/targets/eliza-like/evidence/ipcat/HPG_eliza_specific.pdf"]
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=files, ipcat_mcp_requested=False)
    assert out["status"] == "CACHED_IPCAT_ONLY", out
    assert out["offline_files_present"] is True
    assert out["offline_file_count"] == 1
    print("PASS: offline files without live MCP -> status=CACHED_IPCAT_ONLY "
          "(no silent downgrade to LIVE_IPCAT_VERIFIED)")


def test_offline_files_with_mcp_requested_but_no_target_specific() -> None:
    """MCP was requested but did NOT self-report target_specific; cached
    files still exist → CACHED_IPCAT_ONLY."""
    analysis = {"ipcat_findings": {"queried": True, "returned_generic_only": True}}
    files = ["audio_bu_skill/targets/x/evidence/ipcat/generic_hpg.pdf"]
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=files, ipcat_mcp_requested=True)
    assert out["status"] == "CACHED_IPCAT_ONLY", out
    print("PASS: MCP queried but generic + cached files present -> CACHED_IPCAT_ONLY")


# ── NO_IPCAT_EVIDENCE ───────────────────────────────────────────────────────

def test_mcp_generic_only_no_cache_is_no_evidence() -> None:
    analysis = {"ipcat_findings": {"queried": True, "returned_generic_only": True,
                                    "notes": "only generic HPG chapters"}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "NO_IPCAT_EVIDENCE", out
    assert out["self_report_notes"] == "only generic HPG chapters"
    print("PASS: MCP generic-only with no cache -> status=NO_IPCAT_EVIDENCE")


def test_mcp_queried_but_no_signal_no_cache_is_no_evidence() -> None:
    analysis = {"ipcat_findings": {"queried": True}}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "NO_IPCAT_EVIDENCE", out
    print("PASS: MCP queried, no target_specific/generic_only, no cache -> NO_IPCAT_EVIDENCE")


def test_ipcat_mcp_requested_but_nothing_returned_or_cached() -> None:
    analysis = {}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=True)
    assert out["status"] == "NO_IPCAT_EVIDENCE", out
    print("PASS: MCP requested but no self-report and no cache -> NO_IPCAT_EVIDENCE")


def test_nothing_at_all_is_no_evidence() -> None:
    analysis = {}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=False)
    assert out["status"] == "NO_IPCAT_EVIDENCE", out
    print("PASS: no MCP request, no self-report, no cache -> NO_IPCAT_EVIDENCE")


# ── Graceful degradation ────────────────────────────────────────────────────

def test_never_raises_on_malformed_self_report() -> None:
    analysis = {"ipcat_findings": None}
    out = _ipcat_evidence_summary(analysis=analysis, evidence_files=[], ipcat_mcp_requested=False)
    assert out["status"] == "NO_IPCAT_EVIDENCE", out
    print("PASS: analysis['ipcat_findings'] = None degrades gracefully, never raises")


def main() -> None:
    test_mcp_returned_target_specific_is_live_verified()
    test_mcp_target_specific_takes_precedence_over_cached()
    test_offline_files_without_live_mcp_is_cached_only()
    test_offline_files_with_mcp_requested_but_no_target_specific()
    test_mcp_generic_only_no_cache_is_no_evidence()
    test_mcp_queried_but_no_signal_no_cache_is_no_evidence()
    test_ipcat_mcp_requested_but_nothing_returned_or_cached()
    test_nothing_at_all_is_no_evidence()
    test_never_raises_on_malformed_self_report()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
