"""Phase-2B WP11.1 — failing end-to-end anchor: --generate must write bytes to disk.

This is the RED test of the WP11 test-first sequence. It fails against the
current tree and is made green by WP11.2 (wiring ``write_artifact_bytes`` into
``do_onboard``). It is deliberately NOT a unit test.

Why this is not a duplicate of test_generation_runner.py:234-244
----------------------------------------------------------------
``tests/test_generation_runner.py::test_path_guard_rejects_outside_root`` case
(c) (lines 234-245) already asserts that ``write_artifact_bytes`` — called in
isolation with a valid guard-root path — writes bytes and returns a Path. That
proves the *function* works.

The WP11 gap (PHASE2B_KNOWN_GAPS.md) is a *pipeline-wiring* defect, not a
function defect: ``write_artifact_bytes`` has zero production call sites.
``do_onboard`` (main.py:514-525) runs ``_run_generation`` — which populates
``gc["generation"]["artifacts"]`` with a ``GeneratedArtifact`` carrying a
``path_hint`` — then renders that ``path_hint`` into the report's ``## Generation``
section (main.py:1254-1255) WITHOUT ever calling ``write_artifact_bytes``. The
report promises a file the orchestrator never writes.

This test drives the *whole* ``do_onboard`` path (not the function in
isolation) and asserts bytes land on disk under
``generated/<run_id>/<artifact_class>/<file>``. It therefore covers the exact
contract the unit test cannot: that the pipeline keeps the promise its report
makes. It MUST fail today.

Test seam (honest, no smoke-and-mirrors)
----------------------------------------
The offline harness is the one proven by
``tests/test_onboarding_attempt_model.py``: ``do_onboard(...,
analysis_engine="local-test", test_mode=True)`` with ``m.WORKSPACE_ROOT`` /
``m.TARGETS_ROOT`` monkeypatched to a tmp workspace — the full pipeline, no live
QGenie.

``audioreach_topology`` gates on two open T3 rows
(``T3.lpass_macro_instance``, ``T3.dsp_subsystem_instance`` —
audioreach_topology.py:131-134). ``_run_crossverify`` (main.py:982) cannot
produce those offline: it needs a live, TLS-verified IPCAT transport and
fails closed without one, which would yield an all-``GeneratorSkipped`` run and
make this test fail for the WRONG reason ("nothing generated" rather than
"write not wired"). So we monkeypatch ``m._run_crossverify`` to inject exactly
those two MATCH rows into ``output["generated_case"]["cross_verification"]`` —
semantically "as if crossverify resolved them." With the gate open,
``audioreach_topology`` returns a real ``GeneratedArtifact`` and the ONLY reason
its bytes are absent from disk is the missing WP11.2 wiring.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_wp11_disk_writes
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# The one GeneratedArtifact this test pins on. audioreach_topology.py:388 emits
# path_hint = "generated/audioreach_topology/nord_audioreach.dtsi"; the run_id-
# aware dest (Q2 Option B) re-roots that under generated/<run_id>/.
_ARTIFACT_CLASS = "audioreach_topology"
_ARTIFACT_FILE = "nord_audioreach.dtsi"


def _fake_workspace_yaml(root: Path) -> None:
    """do_onboard -> load_workspace_context(WORKSPACE_ROOT) requires a
    workspace.yaml at the workspace root. Minimal valid one (mirrors
    test_onboarding_attempt_model._fake_workspace_yaml)."""
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
    """Minimal kernel tree with a codec the local-test engine can resolve."""
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
    """Seed one activated target so the local-test similarity ranker has a
    candidate to rank against (mirrors test_onboarding_attempt_model.
    _existing_target). Without >=1 candidate the target_onboarding validator
    fails must_rank_at_least_one_candidate before the generate block is reached."""
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
    """The two open T3 rows that open the audioreach_topology gate.

    MATCH + warning=False -> is_open True (model.py:_GATING_OPEN_VERDICTS,
    model.py:is_open). Serialized to dicts because
    output["generated_case"]["cross_verification"]["rows"] carries dicts, not
    VerificationRow objects (facts._row_from_maybe_dict rehydrates them)."""
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


def test_generate_writes_audioreach_bytes_to_disk() -> None:
    """--generate must materialize audioreach_topology bytes under generated/<run_id>/.

    RED today (no production call site for write_artifact_bytes); GREEN after
    WP11.2. Drives the whole do_onboard pipeline — NOT write_artifact_bytes in
    isolation.
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

        # Inject the two open T3 rows in place of the live-IPCAT crossverify pass
        # (see module docstring — honest seam, keeps the gate open offline).
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
            )

            # Precondition: the report MADE the promise. If this fails, the seam
            # broke (gate closed / artifact skipped) and the disk assertion below
            # would be a false RED. Assert the promise exists before asserting the
            # disk gap.
            report = (target_dir / "onboarding_report.md").read_text(encoding="utf-8")
            promised_hint = f"generated/{_ARTIFACT_CLASS}/{_ARTIFACT_FILE}"
            assert promised_hint in report, (
                "seam precondition failed: the report does not carry the "
                f"audioreach path_hint {promised_hint!r} — the gate did not open "
                "or the artifact was skipped, so the disk assertion would be a "
                "false negative. Report:\n" + report
            )

            # The WP11 contract: bytes on disk under generated/<run_id>/<class>/<file>.
            expected = root / "generated" / run_id / _ARTIFACT_CLASS / _ARTIFACT_FILE
            assert expected.is_file(), (
                "WP11 gap: --generate rendered the path_hint into the report but "
                f"wrote no bytes to disk (run_id={run_id}). Expected file missing: "
                f"{expected}\n"
                "The report's ## Generation section is a false attestation until "
                "WP11.2 wires write_artifact_bytes into do_onboard."
            )
            assert expected.read_bytes(), "written artifact must be non-empty"
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root
            m._run_crossverify = original_crossverify

    print(
        "PASS: --generate materialized audioreach_topology bytes under "
        "generated/<run_id>/audioreach_topology/nord_audioreach.dtsi"
    )


def main() -> None:
    test_generate_writes_audioreach_bytes_to_disk()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
