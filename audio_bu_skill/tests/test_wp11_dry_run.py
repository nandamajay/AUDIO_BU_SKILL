"""Phase-2B WP11.3 — --dry-run must render the report but write nothing.

This is the RED anchor of WP11.3. It fails against the WP11.2 tree (which has
no ``--dry-run`` flag: ``do_onboard`` has no ``dry_run`` parameter, so the call
below raises ``TypeError``) and is made green by the WP11.3 wiring (a single
``if not dry_run:`` gate around the ``write_artifact_bytes`` call in the
do_onboard write loop).

What WP11.3 adds, and what this test pins
-----------------------------------------
WP11.2 wired ``write_artifact_bytes`` into ``do_onboard`` so that ``--generate``
materializes artifact bytes under ``generated/<run_id>/``. WP11.3 adds a
``--dry-run`` flag that keeps the *report* (the ``## Generation`` section, which
renders each artifact's ``path_hint``) but suppresses the *disk write*.

Two design constraints define the flag:

  * **Q4 — report still renders.** ``## Generation`` is assembled from the
    original ``path_hint`` populated by ``_run_generation`` (main.py:527),
    BEFORE the write loop and never mutated by it. So the report is
    byte-identical with or without writes. ``--dry-run`` must NOT gate
    ``_write_onboarding_artifacts`` (main.py:577). This test asserts the
    promised path_hint is present in the report.

  * **C4 — truly side-effect-free.** No file, no partial write, no lock file,
    no ``run_dir`` creation under ``generated/<run_id>/``. The ONLY writer of
    that tree is ``write_artifact_bytes`` (whose internal
    ``dest.parent.mkdir`` at runner.py:104 is what would create the dir), so
    gating that one call is sufficient. We assert the constraint at the
    strongest observable granularity: the ``generated/<run_id>/`` **directory
    does not exist** (G4 — directory-absence, not merely file-absence-inside).

Test seam
---------
Identical honest seam to ``tests/test_wp11_disk_writes.py``: the
``local-test`` engine offline harness with ``m.WORKSPACE_ROOT`` /
``m.TARGETS_ROOT`` monkeypatched, plus ``m._run_crossverify`` monkeypatched to
inject the two open T3 rows (``lpass_macro_instance``, ``dsp_subsystem_instance``)
that open the ``audioreach_topology`` gate offline. With the gate open the
generator emits a real ``GeneratedArtifact`` whose bytes ``--generate`` WOULD
write; ``--dry-run`` is the ONLY reason those bytes are absent. This keeps the
disk-absence assertion honest — it is not a false negative from a closed gate.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_wp11_dry_run
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Same artifact this test pins on as test_wp11_disk_writes — audioreach_topology
# emits path_hint = "generated/audioreach_topology/nord_audioreach.dtsi".
_ARTIFACT_CLASS = "audioreach_topology"
_ARTIFACT_FILE = "nord_audioreach.dtsi"


def _fake_workspace_yaml(root: Path) -> None:
    """Minimal workspace.yaml (mirrors test_wp11_disk_writes)."""
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
    """Minimal kernel tree with a resolvable codec (mirrors test_wp11_disk_writes)."""
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
    """Seed one activated target so the similarity ranker has a candidate
    (mirrors test_wp11_disk_writes._existing_target)."""
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
    """The two open T3 rows that open the audioreach_topology gate
    (identical to test_wp11_disk_writes._open_t3_rows)."""
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


def test_dry_run_renders_report_but_writes_nothing() -> None:
    """--generate --dry-run renders ## Generation (Q4) but touches no disk (C4/G4).

    RED against the WP11.2 tree: ``do_onboard`` has no ``dry_run`` parameter, so
    the keyword call below raises ``TypeError``. GREEN after WP11.3 adds the
    ``dry_run`` parameter and the ``if not dry_run:`` write gate.
    """
    import orchestrator.main as m

    target = "nord-iq10"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)

        targets_root = root / "audio_bu_skill" / "targets"
        _existing_target(targets_root, "lemans-like")
        target_dir = targets_root / target
        ev_offline = target_dir / "evidence" / "offline"
        ev_offline.mkdir(parents=True, exist_ok=True)
        (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")

        def _fake_crossverify(tgt: str, tdir: Path, output: dict) -> None:
            gc = output.get("generated_case")
            if not isinstance(gc, dict):
                return
            gc["cross_verification"] = {
                "rows": _open_t3_rows(),
                "snapshot_provenance": {"chip": "nordschleife_2.0"},
            }

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        original_crossverify = m._run_crossverify
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        m._run_crossverify = _fake_crossverify
        try:
            run_id, _attempt, _is_new = m._resolve_onboarding_run_id(target)

            m.do_onboard(
                target,
                str(kernel),
                analysis_engine="local-test",
                test_mode=True,
                generate=True,
                dry_run=True,
            )

            # Q4 — the report still MADE the promise. The ## Generation section
            # renders the original path_hint (main.py:527/1307), which the write
            # loop never mutates; --dry-run must not suppress it.
            report = (target_dir / "onboarding_report.md").read_text(encoding="utf-8")
            promised_hint = f"generated/{_ARTIFACT_CLASS}/{_ARTIFACT_FILE}"
            assert promised_hint in report, (
                "Q4 regression: --dry-run suppressed the ## Generation render. "
                f"The report does not carry the promised path_hint {promised_hint!r}. "
                "Report:\n" + report
            )

            # C4/G4 — side-effect-free at directory granularity. The write path's
            # ONLY dir-creator is write_artifact_bytes' internal dest.parent.mkdir
            # (runner.py:104); gating that call means generated/<run_id>/ is never
            # created. Assert the DIRECTORY is absent, not just a file inside it —
            # a lock file / partial write / bare mkdir would still fail this.
            generated_run_dir = root / "generated" / run_id
            assert not generated_run_dir.exists(), (
                "C4 breach: --dry-run created "
                f"{generated_run_dir} — dry-run must be truly side-effect-free "
                "(no file, no partial write, no lock file, no run_dir). Contents: "
                + repr(sorted(p.name for p in generated_run_dir.rglob("*")))
            )
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify

    print(
        "PASS: --generate --dry-run rendered ## Generation (path_hint promised) "
        "but created nothing under generated/<run_id>/ (side-effect-free)"
    )


def test_dry_run_requires_generate_exits_two() -> None:
    """--dry-run without --generate is a usage error (argparse exit code 2).

    The check lives in parse_args (parser.error → exit 2), not in do_onboard, so
    it is a pure CLI-contract test. We invoke the module as a subprocess to
    exercise the real argparse path and capture the exit code + stderr. RED
    against the WP11.2 tree (no --dry-run flag → argparse rejects the unknown
    option, also exit 2 but with a DIFFERENT message); GREEN after WP11.3 with
    the explicit 'requires --generate' message.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.main", "--onboard", "nord-iq10", "--dry-run"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (
        f"--dry-run without --generate must exit 2 (argparse usage error), got "
        f"{proc.returncode}. stderr:\n{proc.stderr}"
    )
    assert "--dry-run" in proc.stderr and "--generate" in proc.stderr, (
        "usage error must name both --dry-run and --generate so the operator "
        f"knows the constraint. stderr:\n{proc.stderr}"
    )
    print(
        "PASS: --dry-run without --generate exits 2 with a message naming both flags"
    )


def main() -> None:
    test_dry_run_renders_report_but_writes_nothing()
    test_dry_run_requires_generate_exits_two()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
