"""Phase-2B WP11.4 — idempotency short-circuit for artifact writes.

These tests pin the C3 contract from PHASE2B_KNOWN_GAPS.md: "Re-running
--generate on the same run_id must either short-circuit (bytes already on
disk, hashes match) or overwrite deterministically. Undefined behavior on
re-run is rejected."

WP11.4 wires an idempotency check into do_onboard's write loop, immediately
after the dest_hint rebuild and BEFORE the WP11.3 --dry-run gate:

  dest absent                     → write via write_artifact_bytes (D3 line-3)
                                    art_dict["generation_status"] = "created"
  dest present, hashes match      → continue (D3 line-1, SHORT-CIRCUIT)
                                    art_dict["generation_status"] = "unchanged"
  dest present, hashes differ     → temp-write + Path.replace() (D3 line-2)
                                    art_dict["generation_status"] = "updated"

Hash is sha256(artifact.bytes_) on the in-memory generator bytes ONLY (D1,
G6) — never from a re-read of a written file. There is no on-disk manifest
(D2, G7); the hash is recomputed each run.

Test seam
---------
Identical honest seam to tests/test_wp11_dry_run.py and
tests/test_wp11_disk_writes.py: the ``local-test`` engine offline harness
with ``m.WORKSPACE_ROOT`` / ``m.TARGETS_ROOT`` monkeypatched, plus
``m._run_crossverify`` monkeypatched to inject the two open T3 rows
(``lpass_macro_instance``, ``dsp_subsystem_instance``) that open the
``audioreach_topology`` gate offline. With the gate open the generator
emits a real ``GeneratedArtifact`` whose bytes are hashed and materialized
by the idempotency block being tested.

Why nanosecond mtime (``st_mtime_ns``)? Some filesystems have 1-second
mtime granularity; a millisecond-scale test could see two "different"
mtimes collapse to the same integer second and the "no-touch" assertion
would be a false GREEN. ``st_mtime_ns`` (nanosecond precision) survives
any filesystem that stores sub-second mtime, and returns 0 on those that
don't (still comparable, still distinct across a real rewrite).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_wp11_idempotency
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

# Same artifact this test pins on as test_wp11_disk_writes / test_wp11_dry_run —
# audioreach_topology emits path_hint = "generated/audioreach_topology/nord_audioreach.dtsi".
_ARTIFACT_CLASS = "audioreach_topology"
_ARTIFACT_FILE = "nord_audioreach.dtsi"


def _fake_workspace_yaml(root: Path) -> None:
    """Minimal workspace.yaml (mirrors test_wp11_disk_writes / test_wp11_dry_run)."""
    (root / "workspace.yaml").write_text(
        "manifest_version: '1.0'\n"
        "workspace_id: 'test-workspace'\n"
        "artifacts:\n"
        "  - id: 'placeholder'\n"
        "    type: 'input.txt'\n"
        "    path: 'placeholder.txt'\n"
        "    required: false\n",
        encoding="utf-8",
    )


def _fake_kernel(root: Path) -> Path:
    """Minimal kernel tree with a resolvable codec."""
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    (kernel / ".git").mkdir(exist_ok=True)
    (kernel / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    codecs = kernel / "sound" / "soc" / "codecs"
    codecs.mkdir(parents=True, exist_ok=True)
    (codecs / "pcm1681.c").write_text("// PCM1681 ASoC driver\n", encoding="utf-8")
    return kernel


def _existing_target(targets_root: Path, name: str) -> None:
    """Seed one activated target so the similarity ranker has a candidate."""
    tdir = targets_root / name
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "case.py").write_text(
        "from orchestrator.bringup_walk import BringupCase\n"
        "CASE = BringupCase(\n"
        "    target_soc='SA8797P',\n"
        "    nearest_target='x',\n"
        f"    run_id='{name}-audio-bringup-2026-07',\n"
        "    kernel_source_path='linux-fake',\n"
        "    codec_part_numbers=['PCM1681'],\n"
        "    codec_verdicts={'PCM1681': {'driver_path': 'sound/soc/codecs/pcm1681.c', 'status': 'upstream_present'}},\n"
        "    power_model_source='confirmed',\n"
        ")\n",
        encoding="utf-8",
    )


def _open_t3_rows() -> list[dict]:
    """The two open T3 rows that open the audioreach_topology gate."""
    from orchestrator.reasoning.crossverify_model import VerificationRow

    rows = [
        VerificationRow(
            track="T3",
            subject="lpass_macro_instance",
            verdict="MATCH",
            source="test",
            authority={"strength": "IPCAT_DIRECT", "origin": "test"},
            confidence="high",
        ),
        VerificationRow(
            track="T3",
            subject="dsp_subsystem_instance",
            verdict="MATCH",
            source="test",
            authority={"strength": "IPCAT_DIRECT", "origin": "test"},
            confidence="high",
        ),
    ]
    return [r.to_dict() for r in rows]


def _prepare_workspace(tmp: str, target: str):
    """Build the fake workspace + kernel tree; return (root, kernel, target_dir).

    Every test uses the same seam. Extracted so each test can focus on its
    own arrange/act/assert. Caller is responsible for monkeypatching
    ``m.TARGETS_ROOT`` / ``m.WORKSPACE_ROOT`` / ``m._run_crossverify`` and
    restoring them in a ``try/finally``.
    """
    root = Path(tmp)
    _fake_workspace_yaml(root)
    kernel = _fake_kernel(root)
    targets_root = root / "audio_bu_skill" / "targets"
    _existing_target(targets_root, "lemans-like")
    target_dir = targets_root / target
    ev_offline = target_dir / "evidence" / "offline"
    ev_offline.mkdir(parents=True, exist_ok=True)
    (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")
    return root, kernel, targets_root, target_dir


def _fake_crossverify_factory():
    """Return a _run_crossverify replacement that injects open T3 rows."""

    def _fake_crossverify(tgt: str, tdir: Path, output: dict) -> None:
        gc = output.get("generated_case")
        if not isinstance(gc, dict):
            return
        gc["cross_verification"] = {
            "rows": _open_t3_rows(),
            "snapshot_provenance": {"chip": "nordschleife_2.0"},
        }

    return _fake_crossverify


def _do_onboard_once(m, target: str, kernel: Path, *, generate: bool = True,
                     dry_run: bool = False) -> str:
    """Resolve a run_id and call do_onboard once.

    Returns the run_id so the caller can address the destination directly.
    NOTE: The C3 idempotency contract is defined on the SAME run_id across
    invocations. The natural resolver ``_resolve_onboarding_run_id``
    (main.py:377) allocates a NEW attempt number after each terminal
    SUCCESS (main.py:396-398), so a naive "call do_onboard twice" would
    write to two different run_dirs and never exercise the short-circuit.
    Callers MUST monkeypatch ``m._resolve_onboarding_run_id`` to pin the
    run_id before the second call — see the tests below.
    """
    run_id, _attempt, _is_new = m._resolve_onboarding_run_id(target)
    m.do_onboard(
        target,
        str(kernel),
        analysis_engine="local-test",
        test_mode=True,
        generate=generate,
        dry_run=dry_run,
    )
    return run_id


def _pin_run_id(m, target: str) -> str:
    """Freeze the resolver on attempt-1 for the duration of the test.

    Returns the pinned run_id. After calling this, every ``do_onboard``
    invocation writes to ``generated/<pinned_run_id>/`` regardless of how
    many terminal completions have occurred — which is exactly the C3
    scenario ("re-running --generate on the same run_id"). Every call
    reports ``is_new=True`` because ``_reset_persisted_state`` deletes
    the state record between invocations, mimicking the real-world
    scenario where an operator re-runs --generate against a run_id
    whose bytes are already on disk but whose persisted skill_state
    would otherwise block a fresh cycle. The C3 contract lives at the
    disk layer (dest hash match / mismatch), not at the FSM layer.
    """
    pinned_run_id = f"{target}-onboarding"
    m._resolve_onboarding_run_id = lambda _t: (pinned_run_id, 1, True)
    return pinned_run_id


def _reset_persisted_state(m, run_id: str) -> None:
    """Delete the persisted FSM state for run_id so a second do_onboard
    call can cleanly start a fresh PENDING->READY->...->APPROVED cycle
    against the SAME on-disk generation tree (generated/<run_id>/...).

    Rationale: WP11.4's C3 contract is defined at the artifact-bytes
    layer ("dest exists, hashes match → short-circuit"), independently
    of the FSM's skill_state. In production, an operator can re-run
    --generate against a run_id whose generated/ tree already exists;
    the FSM either resumes or self-heals. In this offline test we
    simulate that "second cycle" by resetting the FSM state file (a
    small JSON under audio_bu_skill/state/) while leaving the
    generated/<run_id>/ tree completely intact — the idempotency
    check inspects that tree, and it is the sole subject of the
    C3 contract.
    """
    from orchestrator import run_store

    path = run_store._state_path(m.WORKSPACE_ROOT, run_id)
    if path.is_file():
        path.unlink()


def test_second_run_short_circuits_and_preserves_mtime() -> None:
    """E6 — Second --generate on same run_id: dest is not rewritten, mtime frozen.

    The SHORT-CIRCUIT contract (D3 line-1). Two identical --generate runs;
    the second must observe dest.is_file() == True, hashes matching, and
    ``continue`` before any write. Nanosecond-precision mtime is the proof:
    a rewrite of the same bytes would still bump st_mtime_ns, so equal
    mtime_ns across runs = no write happened.
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root, kernel, targets_root, target_dir = _prepare_workspace(tmp, target)

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        original_resolver = m._resolve_onboarding_run_id
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify_factory()
        run_id = _pin_run_id(m, target)
        try:
            _do_onboard_once(m, target, kernel)

            dest = root / "generated" / run_id / _ARTIFACT_CLASS / _ARTIFACT_FILE
            assert dest.is_file(), (
                f"first --generate must create {dest} (WP11.2 regression check)"
            )
            first_bytes = dest.read_bytes()
            first_mtime_ns = dest.stat().st_mtime_ns

            # Small sleep so that IF the second run rewrote dest, its mtime
            # would advance past first_mtime_ns even on a coarse-grained
            # filesystem clock. Correct behavior: mtime does NOT change.
            time.sleep(0.02)

            _reset_persisted_state(m, run_id)
            _do_onboard_once(m, target, kernel)

            second_bytes = dest.read_bytes()
            second_mtime_ns = dest.stat().st_mtime_ns

            assert second_bytes == first_bytes, (
                "C3 breach: second --generate mutated dest bytes even though "
                "the generator produced identical content. Idempotency check "
                "at main.py:598-611 must short-circuit on hash match."
            )
            assert second_mtime_ns == first_mtime_ns, (
                "C3 breach: second --generate rewrote dest with identical bytes. "
                f"first_mtime_ns={first_mtime_ns} second_mtime_ns={second_mtime_ns} "
                "— hash-match branch must `continue` (main.py:611) without a write."
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify
            m._resolve_onboarding_run_id = original_resolver

    print(
        "PASS: second --generate on same run_id short-circuited (bytes identical, "
        "st_mtime_ns frozen — no write occurred)"
    )


def test_second_run_with_mutated_bytes_overwrites_deterministically() -> None:
    """E7 — Second run reasserts generator bytes when dest was tampered.

    D3 line-2: dest exists, hashes differ → atomic-rename overwrite via
    temp file + Path.replace() (main.py:649). We simulate drift by writing
    garbage bytes to dest between runs; the second --generate must
    overwrite them with the generator's canonical bytes and advance mtime.
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root, kernel, targets_root, target_dir = _prepare_workspace(tmp, target)

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        original_resolver = m._resolve_onboarding_run_id
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify_factory()
        run_id = _pin_run_id(m, target)
        try:
            _do_onboard_once(m, target, kernel)

            dest = root / "generated" / run_id / _ARTIFACT_CLASS / _ARTIFACT_FILE
            canonical = dest.read_bytes()
            first_mtime_ns = dest.stat().st_mtime_ns

            # Simulate corruption / stale bytes. Any mutation is sufficient
            # so long as sha256(mutated) != sha256(canonical).
            mutated = canonical + b"\n// tampered\n"
            dest.write_bytes(mutated)
            assert dest.read_bytes() != canonical, "test setup: mutation failed"

            time.sleep(0.02)

            _reset_persisted_state(m, run_id)
            _do_onboard_once(m, target, kernel)

            reasserted = dest.read_bytes()
            second_mtime_ns = dest.stat().st_mtime_ns

            assert reasserted == canonical, (
                "C3 breach: second --generate did NOT overwrite mutated bytes "
                "with the generator's canonical output. Overwrite path at "
                "main.py:637-649 (temp-write + Path.replace) must reassert."
            )
            assert second_mtime_ns > first_mtime_ns, (
                "C3 breach: overwrite path did not advance dest mtime. "
                f"first_mtime_ns={first_mtime_ns} second_mtime_ns={second_mtime_ns}"
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify
            m._resolve_onboarding_run_id = original_resolver

    print(
        "PASS: second --generate over mutated dest reasserted canonical bytes "
        "via atomic-rename overwrite (mtime advanced)"
    )


def test_atomic_rename_leaves_no_temp_file_on_success() -> None:
    """E8-a — On successful overwrite, no ``*.tmp.<pid>`` sibling remains.

    D4 atomicity has two invariants: (1) the rename replaces dest in one
    step, and (2) the temp file is CONSUMED by the rename, not leaked. We
    check invariant 2 here: after an overwrite run completes, glob the run
    directory for any ``*.tmp.*`` entries. Zero.
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root, kernel, targets_root, target_dir = _prepare_workspace(tmp, target)

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        original_resolver = m._resolve_onboarding_run_id
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify_factory()
        run_id = _pin_run_id(m, target)
        try:
            _do_onboard_once(m, target, kernel)

            dest = root / "generated" / run_id / _ARTIFACT_CLASS / _ARTIFACT_FILE
            canonical = dest.read_bytes()
            dest.write_bytes(canonical + b"// drift\n")  # force overwrite path

            _reset_persisted_state(m, run_id)
            _do_onboard_once(m, target, kernel)

            run_dir = root / "generated" / run_id
            leftovers = sorted(p for p in run_dir.rglob("*.tmp.*"))
            assert leftovers == [], (
                "D4 breach: atomic-rename left temp sibling(s) behind: "
                f"{[str(p) for p in leftovers]} — Path.replace() must consume "
                "the temp file. See main.py:648-649."
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify
            m._resolve_onboarding_run_id = original_resolver

    print(
        "PASS: overwrite path left no *.tmp.<pid> siblings (atomic rename consumed the temp)"
    )


def test_first_run_creates_status_created_second_run_unchanged() -> None:
    """E8-b — Report addendum: first run → "created", second run → "unchanged".

    Pins the render channel. The write loop assigns
    ``art_dict["generation_status"]`` (main.py:610/651/670); the render
    reads via ``art.get("generation_status", "—")`` (main.py:1412). Both
    passes are asserted by parsing the ## Generation section's Per-artifact
    table.
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root, kernel, targets_root, target_dir = _prepare_workspace(tmp, target)

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        original_resolver = m._resolve_onboarding_run_id
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify_factory()
        _pin_run_id(m, target)
        pinned_run_id = f"{target}-onboarding"
        try:
            _do_onboard_once(m, target, kernel)
            report_1 = (target_dir / "onboarding_report.md").read_text(encoding="utf-8")

            _reset_persisted_state(m, pinned_run_id)
            _do_onboard_once(m, target, kernel)
            report_2 = (target_dir / "onboarding_report.md").read_text(encoding="utf-8")

            # Assert the audioreach_topology row exists with status="created" in
            # run 1 and status="unchanged" in run 2. The row is a single markdown
            # table line: substring match on the artifact class + explicit status
            # cell is sufficient — the render is machine-generated so column
            # spacing is stable within a single run.
            def _row_contains(report: str, artifact_class: str, status: str) -> bool:
                for line in report.splitlines():
                    if line.startswith("| ") and artifact_class in line and f"| {status} |" in line:
                        return True
                return False

            assert _row_contains(report_1, _ARTIFACT_CLASS, "created"), (
                "report from first --generate must show status='created' for "
                f"{_ARTIFACT_CLASS}. Full report:\n{report_1}"
            )
            assert _row_contains(report_2, _ARTIFACT_CLASS, "unchanged"), (
                "report from second --generate must show status='unchanged' for "
                f"{_ARTIFACT_CLASS} (idempotent short-circuit). Full report:\n{report_2}"
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify
            m._resolve_onboarding_run_id = original_resolver

    print(
        "PASS: first --generate rendered status='created'; second --generate "
        "rendered status='unchanged' (report addendum)"
    )


def test_dry_run_reports_unchanged_when_dest_matches() -> None:
    """E9 — WP11.3 × WP11.4 intersection: --dry-run over matching dest = "unchanged".

    Refinement 2 (from the WP11.4 authorization): the honest-reporting-in-
    dry-run contract. Idempotency probe runs BEFORE the WP11.3 gate
    (main.py:598-611 vs main.py:629), so a pre-existing dest with matching
    bytes MUST report status='unchanged' even under --dry-run, and MUST
    NOT write (no mtime change, no temp siblings).
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root, kernel, targets_root, target_dir = _prepare_workspace(tmp, target)

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        original_resolver = m._resolve_onboarding_run_id
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify_factory()
        run_id = _pin_run_id(m, target)
        try:
            # First run (wet) creates dest with canonical bytes.
            _do_onboard_once(m, target, kernel)
            dest = root / "generated" / run_id / _ARTIFACT_CLASS / _ARTIFACT_FILE
            assert dest.is_file(), "test setup: first --generate must create dest"
            baseline_mtime_ns = dest.stat().st_mtime_ns
            baseline_bytes = dest.read_bytes()

            time.sleep(0.02)

            # Second run: --generate --dry-run over the already-matching dest.
            # Should hit the hash-match short-circuit (main.py:605-611) which
            # runs BEFORE the --dry-run gate — so status='unchanged' is
            # assigned even in dry-run mode. No temp files, no mtime bump.
            _reset_persisted_state(m, run_id)
            _do_onboard_once(m, target, kernel, dry_run=True)

            report = (target_dir / "onboarding_report.md").read_text(encoding="utf-8")

            unchanged_row_present = False
            for line in report.splitlines():
                if (
                    line.startswith("| ")
                    and _ARTIFACT_CLASS in line
                    and "| unchanged |" in line
                ):
                    unchanged_row_present = True
                    break
            assert unchanged_row_present, (
                "E9 breach: --generate --dry-run over matching dest must render "
                f"status='unchanged' for {_ARTIFACT_CLASS} (idempotency probe "
                "runs BEFORE the dry-run gate). Full report:\n" + report
            )

            assert dest.read_bytes() == baseline_bytes, (
                "E9 breach: --dry-run over matching dest mutated bytes"
            )
            assert dest.stat().st_mtime_ns == baseline_mtime_ns, (
                "E9 breach: --dry-run over matching dest bumped mtime "
                f"(baseline={baseline_mtime_ns}, now={dest.stat().st_mtime_ns}). "
                "Short-circuit must not touch dest."
            )

            run_dir = root / "generated" / run_id
            leftovers = sorted(p for p in run_dir.rglob("*.tmp.*"))
            assert leftovers == [], (
                "E9 breach: --dry-run over matching dest left temp siblings: "
                f"{[str(p) for p in leftovers]}"
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify
            m._resolve_onboarding_run_id = original_resolver

    print(
        "PASS: --generate --dry-run over matching dest rendered status='unchanged' "
        "(mtime frozen, no temp siblings)"
    )


def main() -> None:
    test_second_run_short_circuits_and_preserves_mtime()
    test_second_run_with_mutated_bytes_overwrites_deterministically()
    test_atomic_rename_leaves_no_temp_file_on_success()
    test_first_run_creates_status_created_second_run_unchanged()
    test_dry_run_reports_unchanged_when_dest_matches()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
