"""WP-MCP-BANNER: T-MCP-1..4 (red before implementation).

Written test-first per PHASE3A_IMPLEMENTATION_PLAN.md §5a. These tests MUST
be red on the clean d8edec2/f3be3db checkout because the banner section,
the collector `reason` field, and the terminal-summary emitter don't exist
yet. WP-MCP-BANNER closes G-3A.6 (silent cross-verify / MCP degradation).

Contract these tests pin down for the implementation:

1. `snapshot_provenance` gains an `mcp_state` field ∈ {"ok","degraded","empty"}.
   Consumed by the banner renderer alongside the existing `chip` key that
   `main.py:1175` already writes.
2. `_render_onboarding_report()` emits a section titled
   `## MCP / Authority Status` with one of `OK` / `DEGRADED` / `EMPTY`.
3. `crossverify_collector._call()` returns a dict carrying a named
   human-readable `reason` string in the unavailable branch (in ADDITION to
   the existing `error_class` sentinel), so a debugger sees "why" not just
   "which exception class".
4. A new emitter `_render_terminal_summary(output) -> str` in
   `orchestrator.main` gates the "wrote proposal artifacts to …" line on
   `mcp_state != "degraded"`. Degraded runs still exit 0 (advisory), but
   the terminal line no longer lies about success.

Failure discipline: each test guards its import in a try/except so the
red-state output names the specific missing surface. This mirrors §5a's
"first turn red; each assertion carries its own reason" rule.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_mcp_banner``
"""

from __future__ import annotations

from typing import Any


# ── Fixture builders (pure, no I/O) ──────────────────────────────────────────


def _output_with_mcp_state(state: str) -> dict[str, Any]:
    """Minimal `output` dict shaped like `do_onboard`'s in-memory result, with
    just enough scaffolding for `_render_onboarding_report` to run.

    Only the crossverify.snapshot_provenance carries the WP-MCP-BANNER signal.
    Every other field is the smallest legal shape the renderer will accept.
    """
    return {
        "target_profile": {
            "target_name": "mcp-banner-fixture",
            "soc": "sa8775p",
            "cites": {},
        },
        "similarity_report": {
            "confidence": {
                "top": "eliza",
                "score": 0.5,
                "confidence": "MEDIUM",
                "margin": 0.1,
                "min_score": 0.4,
                "min_margin": 0.05,
                "low_confidence": False,
            },
            "ranked": [],
            "weights": {},
        },
        "evidence_inventory": {"kernel_source_path": "", "files": []},
        "generated_case": {
            "target_soc": "sa8775p",
            "nearest_target": "eliza",
            "run_id": "fixture",
            "inherit_from": None,
            "evidence_source": "fixture",
            "kernel_source_path": "",
            "power_model_source": None,
            "codec_part_numbers": [],
            "needs_review": [],
            "cross_verification": {
                "rows": [],
                "snapshot_provenance": {
                    "chip": "sa8775p",
                    "mcp_state": state,
                },
            },
        },
    }


# ── T-MCP-1: degraded snapshot → banner=DEGRADED, no clean success line ──────


def test_mcp_1_degraded_snapshot_renders_degraded_banner() -> None:
    """MCP-down (mcp_state='degraded') → onboarding_report contains a
    `## MCP / Authority Status` section labeled DEGRADED. Also asserts the
    unconditional `wrote proposal artifacts to` string is NOT emitted by
    the (to-be-added) terminal-summary emitter for a degraded run.

    Fails on baseline: neither the banner section nor
    `_render_terminal_summary` exists.
    """
    try:
        from orchestrator.main import _render_onboarding_report
    except ImportError as exc:  # pragma: no cover — sanity
        raise AssertionError(f"T-MCP-1: cannot import renderer: {exc}") from exc

    output = _output_with_mcp_state("degraded")
    md = _render_onboarding_report(output)
    assert "## MCP / Authority Status" in md, (
        "T-MCP-1: report must include a `## MCP / Authority Status` section "
        "when snapshot_provenance carries mcp_state. Baseline "
        "d8edec2/f3be3db does not emit this section — this is the "
        "WP-MCP-BANNER surface to add."
    )
    assert "DEGRADED" in md, (
        "T-MCP-1: banner must render the DEGRADED label when "
        "mcp_state='degraded'."
    )

    # Terminal-summary emitter must exist and must NOT print the false
    # success line on a degraded run.
    try:
        from orchestrator.main import _render_terminal_summary
    except ImportError as exc:
        raise AssertionError(
            "T-MCP-1: expected `_render_terminal_summary(output) -> str` in "
            "orchestrator.main to replace the unconditional print block at "
            f"main.py:686-694. Not present on baseline. ImportError: {exc}"
        ) from exc

    summary = _render_terminal_summary(output)
    assert "wrote proposal artifacts to" not in summary, (
        "T-MCP-1: degraded terminal summary must NOT contain the "
        "unconditional success line `wrote proposal artifacts to …`. Found: "
        f"{summary!r}"
    )
    assert "DEGRADED" in summary, (
        "T-MCP-1: degraded terminal summary must carry a visible DEGRADED "
        f"label so the run is unmistakably labeled. Got: {summary!r}"
    )
    print("PASS: T-MCP-1 degraded → banner=DEGRADED, terminal summary suppressed")


# ── T-MCP-2: healthy snapshot → banner=OK ────────────────────────────────────


def test_mcp_2_healthy_snapshot_renders_ok_banner() -> None:
    """MCP-up (mcp_state='ok') → banner renders OK.

    Fails on baseline: banner section is not emitted at all.
    """
    try:
        from orchestrator.main import _render_onboarding_report
    except ImportError as exc:  # pragma: no cover
        raise AssertionError(f"T-MCP-2: cannot import renderer: {exc}") from exc

    md = _render_onboarding_report(_output_with_mcp_state("ok"))
    assert "## MCP / Authority Status" in md, (
        "T-MCP-2: banner section must render for healthy runs too "
        "(banner is always present; only its label varies)."
    )
    # 'OK' is short — anchor to the section by requiring both together.
    banner_idx = md.find("## MCP / Authority Status")
    banner_slice = md[banner_idx : banner_idx + 400]
    assert "OK" in banner_slice, (
        "T-MCP-2: healthy banner section must render the OK label near the "
        f"section header. Section slice: {banner_slice!r}"
    )
    print("PASS: T-MCP-2 healthy → banner=OK")


# ── T-MCP-3: collector `_call` surfaces a named reason, not just a sentinel ──


def test_mcp_3_call_surfaces_named_reason_on_failure() -> None:
    """`crossverify_collector._call` currently returns
    `{"status":"unavailable","error_class": <ClassName>}` and discards the
    exception message (redacted for header-echo safety, see
    crossverify_collector.py:148). WP-MCP-BANNER requires a NAMED,
    human-readable `reason` field alongside `error_class` so operators see
    *why* the tool was unavailable, not just *which* exception class.

    Fails on baseline: the returned dict has no `reason` key.
    """
    try:
        from orchestrator.runners import crossverify_collector
    except ImportError as exc:  # pragma: no cover
        raise AssertionError(f"T-MCP-3: cannot import collector: {exc}") from exc

    class _RaisingTransport:
        def call_tool(self, name: str, params: dict) -> Any:
            raise RuntimeError("connection refused: mcp gateway down")

    result = crossverify_collector._call(
        _RaisingTransport(),
        "chips_list_chips",  # allow-listed read-only tool
        {},
    )
    assert isinstance(result, dict), (
        f"T-MCP-3: _call must return a dict; got {type(result).__name__}"
    )
    assert result.get("status") == "unavailable", (
        "T-MCP-3: raising transport must still land in the unavailable "
        f"branch; got status={result.get('status')!r}"
    )
    assert "reason" in result, (
        "T-MCP-3: the unavailable branch must add a `reason` key carrying a "
        "human-readable string. Baseline returns only `error_class`. Got "
        f"keys: {sorted(result.keys())!r}"
    )
    reason = result["reason"]
    assert isinstance(reason, str) and reason.strip(), (
        f"T-MCP-3: `reason` must be a non-empty string; got {reason!r}"
    )
    assert reason.strip().lower() != "unavailable", (
        "T-MCP-3: `reason` must be MORE informative than the literal "
        f"'unavailable' sentinel; got {reason!r}"
    )
    print(f"PASS: T-MCP-3 unavailable branch carries named reason={reason!r}")


# ── T-MCP-4: degraded run stays exit-0 but is labeled ────────────────────────


def test_mcp_4_degraded_run_is_labeled_but_still_advisory() -> None:
    """Two-part contract: (a) `_render_terminal_summary` MUST be
    non-fatal — invoking it on a degraded output does not raise; (b) the
    onboarding report MUST carry a visible DEGRADED label.

    Codifies §4's "keep exit 0 (advisory), but label the degradation loudly"
    without requiring a subprocess boot. Fails on baseline because
    `_render_terminal_summary` does not exist.
    """
    try:
        from orchestrator.main import (
            _render_onboarding_report,
            _render_terminal_summary,
        )
    except ImportError as exc:
        raise AssertionError(
            "T-MCP-4: expected _render_terminal_summary in orchestrator.main. "
            f"Baseline lacks it. ImportError: {exc}"
        ) from exc

    output = _output_with_mcp_state("degraded")

    # (a) non-fatal: must not raise
    try:
        summary = _render_terminal_summary(output)
    except SystemExit as exc:
        raise AssertionError(
            f"T-MCP-4: _render_terminal_summary raised SystemExit({exc.code}) "
            "on a degraded run — WP-MCP-BANNER must stay advisory (exit 0)."
        ) from exc
    except BaseException as exc:  # noqa: BLE001 — this is the whole point
        raise AssertionError(
            f"T-MCP-4: _render_terminal_summary must not raise on degraded "
            f"input; got {type(exc).__name__}: {exc}"
        ) from exc

    assert isinstance(summary, str), (
        f"T-MCP-4: _render_terminal_summary must return a string; got "
        f"{type(summary).__name__}"
    )

    # (b) the DEGRADED label is visible in both the report and the summary
    md = _render_onboarding_report(output)
    assert "DEGRADED" in md, (
        "T-MCP-4: onboarding report must carry a DEGRADED label so a "
        "degraded run is not indistinguishable from a healthy one."
    )
    assert "DEGRADED" in summary, (
        "T-MCP-4: terminal summary must carry a DEGRADED label. "
        f"Got: {summary!r}"
    )
    print("PASS: T-MCP-4 degraded run is advisory (non-fatal) but labeled")


# ── Runner ───────────────────────────────────────────────────────────────────


def main() -> None:
    """Run each T-MCP-* independently so the red state of every test is
    visible in a single invocation. Aggregates AssertionError per test and
    exits non-zero if any failed. Non-assertion errors (import failures)
    also feed the aggregator via each test's own guard-clauses."""
    import sys

    tests = [
        ("T-MCP-1", test_mcp_1_degraded_snapshot_renders_degraded_banner),
        ("T-MCP-2", test_mcp_2_healthy_snapshot_renders_ok_banner),
        ("T-MCP-3", test_mcp_3_call_surfaces_named_reason_on_failure),
        ("T-MCP-4", test_mcp_4_degraded_run_is_labeled_but_still_advisory),
    ]
    failures: list[tuple[str, AssertionError]] = []
    for label, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((label, exc))
            print(f"FAIL: {label}: {exc}")

    if failures:
        print(f"\n{len(failures)}/{len(tests)} tests FAILED — see per-test FAIL lines above.")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
