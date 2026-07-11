"""Reasoning fingerprints + replay/rerun tests (Task #32, v1.2).

Covers the reproducibility contract for QGenie-backed onboarding:
  - reasoning_fingerprints() is deterministic (same inputs -> same digests).
  - diff_fingerprints() surfaces task_spec changes and QGenie-profile changes
    (qgenie_cli_home / config_root / data_root) as drift, not just evidence.
  - _ipcat_provenance_id() prefers the PLAYBOOK.md provenance.json shape
    (doc_ids, then query) over a raw digest.
  - --replay never re-invokes reasoning (reads manifest.json only).
  - --rerun (do_rerun) detects both evidence/task_spec drift and QGenie
    profile drift for onboarding runs, which have no case.py (the do_rerun
    gap this task closes via _do_rerun_onboarding).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_reasoning_fingerprints
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from orchestrator import run_manifest
from orchestrator.reasoning.result import _ipcat_provenance_id, reasoning_fingerprints

_TASK_SPEC_A = {"skill_id": "target_onboarding", "target": "t", "kernel": {"path": "/tmp/k"}, "evidence": {}}
_TASK_SPEC_B = {"skill_id": "target_onboarding", "target": "t2", "kernel": {"path": "/tmp/k"}, "evidence": {}}


# --------------------------------------------------------------------------- #
# fingerprint stability + drift (unit-level, no subprocess)
# --------------------------------------------------------------------------- #
def test_fingerprints_stable_for_same_inputs() -> None:
    kwargs = dict(
        task_spec=_TASK_SPEC_A, engine_id="qgenie", model_id="2.1.198", cli_version="1.1.13",
        schema_version="1.0", ipcat_provenance={"doc_ids": ["a", "b"]},
        qgenie_cli_home="/profiles/prod", config_root="/profiles/prod/config",
        data_root="/profiles/prod/data", kernel_commit="deadbeef",
        evidence_sha256={"evidence/x.pdf": "abc123"},
    )
    fp1 = reasoning_fingerprints(**kwargs)
    fp2 = reasoning_fingerprints(**kwargs)
    assert fp1 == fp2, "same inputs must yield identical fingerprints"
    assert not run_manifest.diff_fingerprints(fp1, fp2), "identical fingerprints must show no drift"
    print("PASS: reasoning_fingerprints is deterministic for identical inputs")


def test_drift_detects_task_spec_change() -> None:
    common = dict(
        engine_id="qgenie", model_id="2.1.198", cli_version="1.1.13", schema_version="1.0",
        ipcat_provenance=None, qgenie_cli_home="/profiles/prod", config_root="/c", data_root="/d",
        kernel_commit="deadbeef", evidence_sha256={"evidence/x.pdf": "abc123"},
    )
    recorded = reasoning_fingerprints(task_spec=_TASK_SPEC_A, **common)
    current = reasoning_fingerprints(task_spec=_TASK_SPEC_B, **common)
    drift = run_manifest.diff_fingerprints(recorded, current)
    assert any("task_spec_sha256" in line for line in drift), drift
    print("PASS: a changed task_spec is surfaced as task_spec_sha256 drift")


def test_drift_detects_profile_change() -> None:
    common = dict(
        task_spec=_TASK_SPEC_A, engine_id="qgenie", model_id="2.1.198", cli_version="1.1.13",
        schema_version="1.0", ipcat_provenance=None, kernel_commit="deadbeef",
        evidence_sha256={"evidence/x.pdf": "abc123"},
    )
    recorded = reasoning_fingerprints(qgenie_cli_home="/profiles/prod", config_root="/c1", data_root="/d1", **common)
    current = reasoning_fingerprints(qgenie_cli_home="/profiles/staging", config_root="/c2", data_root="/d2", **common)
    drift = run_manifest.diff_fingerprints(recorded, current)
    drift_keys = {line.split(":", 1)[0] for line in drift}
    assert "qgenie_cli_home" in drift_keys, drift
    assert "config_root" in drift_keys, drift
    assert "data_root" in drift_keys, drift
    print("PASS: a changed QGenie profile (CLI_HOME/config_root/data_root) is surfaced as drift")


def test_drift_detects_kernel_commit_change() -> None:
    common = dict(
        task_spec=_TASK_SPEC_A, engine_id="qgenie", model_id="2.1.198", cli_version="1.1.13",
        schema_version="1.0", ipcat_provenance=None, qgenie_cli_home="/p", config_root="/c", data_root="/d",
        evidence_sha256={"evidence/x.pdf": "abc123"},
    )
    recorded = reasoning_fingerprints(kernel_commit="deadbeef", **common)
    current = reasoning_fingerprints(kernel_commit="cafef00d", **common)
    drift = run_manifest.diff_fingerprints(recorded, current)
    assert any(line.startswith("kernel_commit:") for line in drift), drift
    print("PASS: a changed kernel_commit is surfaced as drift")


def test_ipcat_provenance_id_prefers_doc_ids_then_query_then_digest() -> None:
    doc_ids_id = _ipcat_provenance_id({"doc_ids": ["d1", "d2"], "query": "q"})
    assert doc_ids_id and doc_ids_id.startswith("doc_ids:"), doc_ids_id

    query_id = _ipcat_provenance_id({"query": "q"})
    assert query_id and query_id.startswith("query:"), query_id

    digest_id = _ipcat_provenance_id({"other": "field"})
    assert digest_id and digest_id.startswith("digest:"), digest_id

    assert _ipcat_provenance_id(None) is None
    assert _ipcat_provenance_id({}) is None

    # stable for the same doc_ids regardless of input order
    assert _ipcat_provenance_id({"doc_ids": ["d1", "d2"]}) == _ipcat_provenance_id({"doc_ids": ["d2", "d1"]})
    print("PASS: _ipcat_provenance_id prefers doc_ids > query > digest, and is order-independent for doc_ids")


# --------------------------------------------------------------------------- #
# end-to-end helpers (local-test engine — no live QGenie)
# --------------------------------------------------------------------------- #
def _fake_workspace_yaml(root: Path) -> None:
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


def _fake_kernel(root: Path, head_ref: str = "ref: refs/heads/main\n") -> Path:
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    (kernel / ".git").mkdir(exist_ok=True)
    (kernel / ".git" / "HEAD").write_text(head_ref, encoding="utf-8")
    codecs = kernel / "sound" / "soc" / "codecs"
    codecs.mkdir(parents=True, exist_ok=True)
    (codecs / "pcm1681.c").write_text("// PCM1681 ASoC driver\n", encoding="utf-8")
    return kernel


def _existing_target(targets_root: Path, name: str) -> None:
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


def _seed_target(root: Path, name: str) -> tuple[Path, Path]:
    targets_root = root / "audio_bu_skill" / "targets"
    _existing_target(targets_root, "lemans-like")
    new_dir = targets_root / name
    ev_offline = new_dir / "evidence" / "offline"
    ev_offline.mkdir(parents=True, exist_ok=True)
    (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")
    return targets_root, ev_offline


# --------------------------------------------------------------------------- #
# replay never re-invokes reasoning
# --------------------------------------------------------------------------- #
def test_replay_never_recalls_reasoning() -> None:
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)
        target = "replayboard"
        targets_root, _ = _seed_target(root, target)

        original_targets_root, original_workspace_root = m.TARGETS_ROOT, m.WORKSPACE_ROOT
        m.TARGETS_ROOT, m.WORKSPACE_ROOT = targets_root, root
        try:
            m.do_onboard(target, str(kernel), analysis_engine="local-test", test_mode=True)

            # get_reasoning_client must NEVER be called during --replay: patch it to
            # blow up if touched, then replay and confirm no exception surfaces.
            with mock.patch("orchestrator.main.get_reasoning_client",
                             side_effect=AssertionError("do_replay must not call reasoning")):
                m.do_replay(f"{target}-onboarding")
        finally:
            m.TARGETS_ROOT, m.WORKSPACE_ROOT = original_targets_root, original_workspace_root

    print("PASS: --replay reconstructs an onboarding run from artifacts without re-invoking reasoning")


# --------------------------------------------------------------------------- #
# rerun detects task_spec (evidence/kernel) and profile drift
# --------------------------------------------------------------------------- #
def test_rerun_repeatable_then_detects_evidence_drift() -> None:
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)
        target = "rerunboard"
        targets_root, ev_offline = _seed_target(root, target)

        original_targets_root, original_workspace_root = m.TARGETS_ROOT, m.WORKSPACE_ROOT
        m.TARGETS_ROOT, m.WORKSPACE_ROOT = targets_root, root
        try:
            m.do_onboard(target, str(kernel), analysis_engine="local-test", test_mode=True)

            rc_clean = m.do_rerun(f"{target}-onboarding", str(kernel))
            assert rc_clean == 0, f"expected REPEATABLE, got exit {rc_clean}"

            (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet REV2\n", encoding="utf-8")
            rc_drift = m.do_rerun(f"{target}-onboarding", str(kernel))
            assert rc_drift == 2, f"expected DRIFT DETECTED, got exit {rc_drift}"
        finally:
            m.TARGETS_ROOT, m.WORKSPACE_ROOT = original_targets_root, original_workspace_root

    print("PASS: --rerun on an onboarding run_id is REPEATABLE when unchanged, "
          "then DRIFT DETECTED after an evidence file changes")


def test_rerun_detects_kernel_commit_drift() -> None:
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)
        target = "kernelboard"
        targets_root, _ = _seed_target(root, target)

        original_targets_root, original_workspace_root = m.TARGETS_ROOT, m.WORKSPACE_ROOT
        m.TARGETS_ROOT, m.WORKSPACE_ROOT = targets_root, root
        try:
            m.do_onboard(target, str(kernel), analysis_engine="local-test", test_mode=True)

            rc_clean = m.do_rerun(f"{target}-onboarding", str(kernel))
            assert rc_clean == 0, f"expected REPEATABLE, got exit {rc_clean}"

            # simulate the kernel tree moving to a new commit (fallback path: hash of .git/HEAD)
            (kernel / ".git" / "HEAD").write_text("ref: refs/heads/feature-branch\n", encoding="utf-8")
            rc_drift = m.do_rerun(f"{target}-onboarding", str(kernel))
            assert rc_drift == 2, f"expected DRIFT DETECTED, got exit {rc_drift}"
        finally:
            m.TARGETS_ROOT, m.WORKSPACE_ROOT = original_targets_root, original_workspace_root

    print("PASS: --rerun on an onboarding run_id detects kernel_commit drift")


def test_rerun_detects_profile_drift() -> None:
    """A changed QGENIE_CLI_HOME between the recorded run and --rerun must show
    up as reasoning-profile drift, even though the local-test engine itself
    always reports qgenie_cli_home=None (it's not a real QGenie profile) —
    so this drives the drift via the recorded fingerprint directly, exactly
    as do_rerun's diff_fingerprints call would see it against a real QGenie
    profile change in production."""
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)
        target = "profileboard"
        targets_root, _ = _seed_target(root, target)

        original_targets_root, original_workspace_root = m.TARGETS_ROOT, m.WORKSPACE_ROOT
        m.TARGETS_ROOT, m.WORKSPACE_ROOT = targets_root, root
        try:
            m.do_onboard(target, str(kernel), analysis_engine="local-test", test_mode=True)

            manifest_path = run_manifest.artifacts_dir(root, f"{target}-onboarding") / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["fingerprints"]["reasoning"]["qgenie_cli_home"] = "/profiles/prod"
            manifest["fingerprints"]["reasoning"]["config_root"] = "/profiles/prod/config"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            rc_drift = m.do_rerun(f"{target}-onboarding", str(kernel))
            assert rc_drift == 2, f"expected DRIFT DETECTED, got exit {rc_drift}"
        finally:
            m.TARGETS_ROOT, m.WORKSPACE_ROOT = original_targets_root, original_workspace_root

    print("PASS: --rerun detects reasoning-profile drift (qgenie_cli_home/config_root changed)")


def main() -> None:
    test_fingerprints_stable_for_same_inputs()
    test_drift_detects_task_spec_change()
    test_drift_detects_profile_change()
    test_drift_detects_kernel_commit_change()
    test_ipcat_provenance_id_prefers_doc_ids_then_query_then_digest()
    test_replay_never_recalls_reasoning()
    test_rerun_repeatable_then_detects_evidence_drift()
    test_rerun_detects_kernel_commit_drift()
    test_rerun_detects_profile_drift()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
