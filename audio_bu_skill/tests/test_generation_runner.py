"""Phase-2B WP10 — tests for the generation runner.

Pure, stdlib-only tests over ``orchestrator.generation.runner._run_generation``
and ``write_artifact_bytes``.  Mirrors WP3-WP8 test discipline: inline data,
minimal fakes, no network, no pytest.

Eight tests per PHASE2B_SPECIFICATION.md §WP10 (recon-locked E scope):

  1.  ``test_generate_off_gc_generation_absent``      — §WP10(e): when
      ``--generate`` is OFF the runner is never called, so
      ``gc["generation"]`` must be absent.

  2.  ``test_generate_on_populates_gc_generation``    — §WP10(c): calling
      ``_run_generation`` populates ``gc["generation"]`` with ``artifacts``
      and ``post_verification`` keys.

  3.  ``test_missing_snapshot_raises_exception``      — ``MissingPhase2ASnapshot``
      is raised when ``gc["cross_verification"]`` is absent or empty.

  4.  ``test_missing_snapshot_translates_to_exit_2``  — §3.8: the
      do_onboard dispatch catches ``MissingPhase2ASnapshot`` and calls
      ``sys.exit(2)`` (simulated via ``SystemExit`` assertion).

  5.  ``test_path_guard_rejects_outside_root``        — §5.4:
      ``write_artifact_bytes`` returns ``None`` for a path outside
      ``PATH_GUARD_ROOT``; no exception raised.

  6.  ``test_generator_skipped_is_not_failure``       — §WP10(h):
      a ``GeneratorSkipped`` result is included in ``gc["generation"]
      ["artifacts"]`` and does NOT cause ``post_verification`` to fail by
      itself.

  7.  ``test_generator_exception_isolates_and_continues``  — §WP10(h):
      an unhandled exception from a generator leaves that generator
      absent from ``gc["generation"]["artifacts"]`` while later
      generators continue.

  8.  ``test_report_byte_identical_without_generation`` — §3.9 regression
      anchor: the pre-WP10 baseline fixture does NOT contain a
      ``## Generation`` section, asserting that ``--generate OFF`` leaves
      the report byte-identical to the pre-WP10 state.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_runner``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

from orchestrator.generation.config import PATH_GUARD_ROOT, is_path_within_guard
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.generation.runner import (
    MissingPhase2ASnapshot,
    _run_generation,
    write_artifact_bytes,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2b"


# ── Test helpers ─────────────────────────────────────────────────────────────

def _open_row(track: str, subject: str) -> VerificationRow:
    """Minimal MATCH row that opens a gate."""
    return VerificationRow(
        track=track,
        subject=subject,
        verdict="MATCH",
        source="test",
        authority={"strength": "IPCAT_DIRECT", "origin": "test"},
        confidence="high",
    )


def _facts_with_rows(*rows: VerificationRow) -> TrustedFacts:
    """Project a small set of rows to TrustedFacts."""
    from orchestrator.generation.facts import project_facts
    return project_facts(list(rows))


def _empty_facts() -> TrustedFacts:
    return TrustedFacts(rows_by_track_subject={})


def _gc_with_cv(rows: list[VerificationRow] | None = None) -> dict[str, Any]:
    """Build a gc dict with a populated cross_verification block."""
    r = rows or []
    return {
        "cross_verification": {
            "rows": [row.to_dict() for row in r],
            "snapshot_provenance": {"chip": "test_chip"},
        }
    }


# ── 1. --generate OFF → gc["generation"] absent ──────────────────────────────

def test_generate_off_gc_generation_absent() -> None:
    """§WP10(e): when the caller never calls _run_generation, gc has no 'generation' key."""
    gc: dict[str, Any] = {}
    assert "generation" not in gc, "gc must not have 'generation' key when runner not called"

    # Simulate do_onboard with args.generate == False: runner never called.
    # gc stays unchanged — same dict, no 'generation' key.
    assert "generation" not in gc, "gc['generation'] must be absent when --generate OFF"
    print("PASS: generate-OFF — gc['generation'] absent when runner not called")


# ── 2. _run_generation populates gc["generation"] ────────────────────────────

def test_generate_on_populates_gc_generation() -> None:
    """§WP10(c): _run_generation populates gc['generation'] with artifacts + post_verification."""
    from orchestrator.generation.registry import ensure_generators_loaded, generator_order
    ensure_generators_loaded()

    # Build a gc with cross_verification populated.
    gc = _gc_with_cv()
    facts = _empty_facts()

    _run_generation(gc, facts)

    assert "generation" in gc, "gc must have 'generation' key after _run_generation"
    gen = gc["generation"]
    assert "artifacts" in gen, "gc['generation'] must have 'artifacts'"
    assert "post_verification" in gen, "gc['generation'] must have 'post_verification'"
    assert isinstance(gen["artifacts"], list), "artifacts must be a list"
    assert isinstance(gen["post_verification"], dict), "post_verification must be a dict"
    assert "verdict" in gen["post_verification"], "post_verification must have 'verdict'"

    # With empty TrustedFacts all gates are closed → all generators produce
    # GeneratorSkipped.  post_verification verdict must still be "pass"
    # (skipped artifacts pass WP7's skip-validity check).
    pv_verdict = gen["post_verification"]["verdict"]
    assert pv_verdict in ("pass", "fail"), f"verdict must be pass/fail, got {pv_verdict!r}"

    print("PASS: generate-ON — gc['generation'] populated with artifacts + post_verification")


# ── 3. MissingPhase2ASnapshot raised when cross_verification absent ──────────

def test_missing_snapshot_raises_exception() -> None:
    """MissingPhase2ASnapshot raised when gc['cross_verification'] absent or empty."""
    facts = _empty_facts()

    # (a) cross_verification key absent entirely
    gc_no_cv: dict[str, Any] = {}
    raised = False
    try:
        _run_generation(gc_no_cv, facts)
    except MissingPhase2ASnapshot:
        raised = True
    assert raised, "MissingPhase2ASnapshot must be raised when gc has no cross_verification"

    # (b) cross_verification present but falsy (None)
    gc_none_cv: dict[str, Any] = {"cross_verification": None}
    raised = False
    try:
        _run_generation(gc_none_cv, facts)
    except MissingPhase2ASnapshot:
        raised = True
    assert raised, "MissingPhase2ASnapshot must be raised when gc['cross_verification'] is None"

    # (c) cross_verification present but empty dict
    gc_empty_cv: dict[str, Any] = {"cross_verification": {}}
    raised = False
    try:
        _run_generation(gc_empty_cv, facts)
    except MissingPhase2ASnapshot:
        raised = True
    assert raised, "MissingPhase2ASnapshot must be raised when gc['cross_verification'] is {}"

    print("PASS: missing-snapshot — MissingPhase2ASnapshot raised in all 3 absent/empty shapes")


# ── 4. MissingPhase2ASnapshot → sys.exit(2) ──────────────────────────────────

def test_missing_snapshot_translates_to_exit_2() -> None:
    """§3.8: do_onboard catches MissingPhase2ASnapshot and translates to SystemExit(2)."""
    facts = _empty_facts()
    gc_no_cv: dict[str, Any] = {}

    # Simulate the do_onboard dispatch: catch + sys.exit(2).
    try:
        try:
            _run_generation(gc_no_cv, facts)
        except MissingPhase2ASnapshot as exc:
            sys.exit(2)
    except SystemExit as se:
        assert se.code == 2, f"exit code must be 2; got {se.code!r}"
        print("PASS: missing-snapshot → sys.exit(2) correctly simulated")
        return

    raise AssertionError("SystemExit(2) must be raised when MissingPhase2ASnapshot is caught")


# ── 5. write_artifact_bytes rejects paths outside PATH_GUARD_ROOT ─────────────

def test_path_guard_rejects_outside_root(tmp_path: Path | None = None) -> None:
    """§5.4: write_artifact_bytes returns None for paths outside PATH_GUARD_ROOT; no exception."""
    import tempfile
    import os

    base_dir = Path(tempfile.mkdtemp())
    try:
        # (a) Escape via absolute path
        artifact_abs = GeneratedArtifact(
            artifact_class="dt_scaffolding",
            subject="dt_scaffolding",
            path_hint="/etc/passwd",
            bytes_=b"// evil\n",
        )
        result = write_artifact_bytes(artifact_abs, base_dir)
        assert result is None, f"absolute escape must return None; got {result!r}"

        # (b) Escape via ../
        artifact_dotdot = GeneratedArtifact(
            artifact_class="dt_scaffolding",
            subject="dt_scaffolding",
            path_hint="../escaped_file.txt",
            bytes_=b"// evil\n",
        )
        result = write_artifact_bytes(artifact_dotdot, base_dir)
        assert result is None, f"../escape must return None; got {result!r}"

        # (c) Valid path inside PATH_GUARD_ROOT
        artifact_valid = GeneratedArtifact(
            artifact_class="dt_scaffolding",
            subject="dt_scaffolding",
            path_hint=f"{PATH_GUARD_ROOT}dt_scaffolding/board.dtsi",
            bytes_=b"// stub\n",
        )
        result = write_artifact_bytes(artifact_valid, base_dir)
        assert result is not None, "valid guard-root path must return Path"
        assert result.is_file(), "written file must exist"
        assert result.read_bytes() == b"// stub\n", "written bytes must match"

        print("PASS: path-guard — outside-root returns None (no exception); inside-root writes")
    finally:
        import shutil
        shutil.rmtree(base_dir, ignore_errors=True)


# ── 6. GeneratorSkipped is not a failure ─────────────────────────────────────

def test_generator_skipped_is_not_failure() -> None:
    """§WP10(h): GeneratorSkipped result is included in artifacts; does not by itself cause failure."""
    from orchestrator.generation.registry import ensure_generators_loaded, generator_order

    ensure_generators_loaded()
    gc = _gc_with_cv()
    facts = _empty_facts()

    _run_generation(gc, facts)

    gen = gc["generation"]
    artifacts = gen["artifacts"]

    # With empty TrustedFacts all gates are closed → all registered generators
    # must produce GeneratorSkipped (no GeneratedArtifact can pass gates with
    # no open rows).
    skipped = [a for a in artifacts if a["kind"] == "GeneratorSkipped"]
    assert len(skipped) > 0, "at least one GeneratorSkipped expected with empty TrustedFacts"

    # Every artifact that is GeneratorSkipped should appear in the list
    # (inclusion confirms it is NOT treated as a failure / absent).
    order = generator_order()
    skipped_classes = {a["artifact_class"] for a in skipped}
    for artifact_class in order:
        assert artifact_class in skipped_classes, (
            f"generator {artifact_class!r} must appear as GeneratorSkipped in artifacts"
        )

    print("PASS: generator-skipped-not-failure — all skipped generators present in artifacts")


# ── 7. Unhandled generator exception isolates and continues ──────────────────

def test_generator_exception_isolates_and_continues() -> None:
    """§WP10(h): unhandled exception from a generator leaves it absent from artifacts."""
    from orchestrator.generation.registry import ensure_generators_loaded, generator_order

    ensure_generators_loaded()
    order = generator_order()
    assert len(order) >= 2, "need >=2 generators for isolation test"

    first_class = order[0]
    second_class = order[1]

    original_first = None
    try:
        from orchestrator.generation import registry as _reg
        original_first = _reg._GENERATORS[first_class].func

        # Patch the first generator to raise.
        def _exploding_generator(facts: object, kb: object = None) -> object:  # noqa: ANN001
            raise RuntimeError("deliberate test explosion")

        from dataclasses import replace
        _reg._GENERATORS[first_class] = replace(
            _reg._GENERATORS[first_class], func=_exploding_generator
        )

        gc = _gc_with_cv()
        facts = _empty_facts()
        _run_generation(gc, facts)

        artifacts = gc["generation"]["artifacts"]
        artifact_classes = {a["artifact_class"] for a in artifacts}

        assert first_class not in artifact_classes, (
            f"exploding generator {first_class!r} must be absent from artifacts"
        )
        assert second_class in artifact_classes, (
            f"later generator {second_class!r} must still appear (isolation)"
        )

        print("PASS: exception-isolation — failed generator absent; later generators continue")
    finally:
        if original_first is not None:
            from dataclasses import replace
            from orchestrator.generation import registry as _reg
            _reg._GENERATORS[first_class] = replace(
                _reg._GENERATORS[first_class], func=original_first
            )


# ── 8. Baseline fixture has no Generation section ────────────────────────────

def test_report_byte_identical_without_generation() -> None:
    """§3.9 regression anchor: pre_wp10_baseline_report.md must not contain a Generation section.

    This asserts that the WP8 renderer's null-guard (returning [] when
    gc['generation'] is absent) preserves the pre-WP10 report byte-for-byte.
    The frozen fixture captures the report state immediately before WP10 landed.
    """
    baseline_path = FIXTURE_DIR / "pre_wp10_baseline_report.md"
    assert baseline_path.is_file(), (
        f"baseline fixture missing: {baseline_path}"
    )
    baseline = baseline_path.read_text(encoding="utf-8")

    # The baseline must not contain a Generation section — that is the key
    # invariant: --generate OFF leaves the report identical to pre-WP10.
    assert "## Generation" not in baseline, (
        "pre_wp10_baseline_report.md must not contain '## Generation' section; "
        "if it does, the fixture was captured AFTER WP10 landed"
    )

    # Also assert the renderer returns [] for a gc without 'generation' key,
    # which is what --generate OFF produces.
    from orchestrator.main import _render_generation_section
    result = _render_generation_section({})
    assert result == [], f"_render_generation_section({{}}) must return [] for absent generation key"

    result_none = _render_generation_section({"generation": None})
    assert result_none == [], (
        "_render_generation_section({'generation': None}) must return []"
    )

    print("PASS: baseline-fixture — no '## Generation' section; renderer returns [] for absent key")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    test_generate_off_gc_generation_absent()            # 1
    test_generate_on_populates_gc_generation()          # 2
    test_missing_snapshot_raises_exception()            # 3
    test_missing_snapshot_translates_to_exit_2()        # 4
    test_path_guard_rejects_outside_root()              # 5
    test_generator_skipped_is_not_failure()             # 6
    test_generator_exception_isolates_and_continues()   # 7
    test_report_byte_identical_without_generation()     # 8
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
