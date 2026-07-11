"""Onboarding attempt model (v1.2): repeated --onboard runs get distinct attempts.

Regression coverage for the bug where a second --onboard against the same
target hit ``StateMachineError`` at step("READY") because the deterministic
run_id ``f"{target}-onboarding"`` collided with a SUCCESS-terminal invocation
persisted from a prior attempt, and (SUCCESS, READY) is not (and per explicit
instruction, must never become) a legal skill_state_machine transition.

Asserts, driving orchestrator.main.do_onboard directly against a tmp workspace
with the local-test engine (test_mode=True, no live QGenie):
  - a first onboarding attempt succeeds and gets run_id "<target>-onboarding"
    (attempt 1, unsuffixed — so a pre-existing unsuffixed state file from
    before this model shipped is recognized as attempt 1),
  - a second onboarding attempt against the SAME target does NOT raise
    StateMachineError; it allocates a new attempt run_id
    "<target>-onboarding-2" instead of re-entering the terminal attempt 1,
  - each attempt gets its own artifacts/<run_id>/manifest.json recording the
    5 mandated reproducibility fields (qgenie/model id, task_spec hash,
    evidence hash, kernel commit) via the "reasoning"/"evidence"/
    "kernel_commit" fingerprint keys,
  - skill_state_machine.py's APPROVED_TRANSITIONS is untouched (no
    (SUCCESS, READY) transition exists).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_onboarding_attempt_model
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from orchestrator import run_manifest, run_store
from orchestrator.skill_state_machine import APPROVED_TRANSITION_SET, SkillState

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _fake_workspace_yaml(root: Path) -> None:
    """do_onboard calls load_workspace_context(WORKSPACE_ROOT), which requires
    workspace.yaml at the workspace root — write a minimal valid one."""
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
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    (kernel / ".git").mkdir(exist_ok=True)
    # _kernel_commit falls back to hashing .git/HEAD when `git rev-parse` fails
    # (no real git repo here) — give it a HEAD file so kernel_commit is non-None.
    (kernel / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
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


def test_no_illegal_transition_between_attempts() -> None:
    assert (SkillState.SUCCESS.value, SkillState.READY.value) not in APPROVED_TRANSITION_SET, (
        "(SUCCESS, READY) must never be added to APPROVED_TRANSITIONS — the "
        "attempt model fixes re-onboarding via a new run_id, not FSM re-entry"
    )
    print("PASS: (SUCCESS, READY) is not, and must not be, a legal transition")


def test_two_attempts_get_distinct_run_ids() -> None:
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_workspace_yaml(root)
        kernel = _fake_kernel(root)
        targets_root = root / "audio_bu_skill" / "targets"
        _existing_target(targets_root, "lemans-like")

        new_target = "newboard"
        new_dir = targets_root / new_target
        ev_offline = new_dir / "evidence" / "offline"
        ev_offline.mkdir(parents=True, exist_ok=True)
        (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")

        original_targets_root = m.TARGETS_ROOT
        original_workspace_root = m.WORKSPACE_ROOT
        m.TARGETS_ROOT = targets_root
        m.WORKSPACE_ROOT = root
        try:
            # --- attempt 1: fresh target, no prior state ---
            m.do_onboard(new_target, str(kernel), analysis_engine="local-test", test_mode=True)
            run_id_1, attempt_1, is_new_1 = m._resolve_onboarding_run_id(new_target)
            # _resolve_onboarding_run_id called AFTER attempt 1 completed (SUCCESS)
            # reports the NEXT attempt to allocate, i.e. attempt 2.
            assert attempt_1 == 2 and is_new_1, (run_id_1, attempt_1, is_new_1)

            state_1 = run_store.load_run(root, f"{new_target}-onboarding")
            assert state_1 is not None, "attempt 1 must persist under the unsuffixed run_id"
            assert state_1["skill_invocations"]["target_onboarding"]["skill_state"] == "SUCCESS"

            manifest_1 = run_manifest.load_manifest(root, f"{new_target}-onboarding")
            assert manifest_1["attempt"] == 1
            fp1 = manifest_1["fingerprints"]
            assert fp1["kernel_commit"], "attempt 1 manifest must record kernel_commit"
            assert fp1["reasoning"]["cli_version"], "attempt 1 manifest must record qgenie/cli version"
            assert fp1["reasoning"]["model_id"], "attempt 1 manifest must record model id"
            assert fp1["reasoning"]["task_spec_sha256"], "attempt 1 manifest must record task_spec hash"
            assert fp1["evidence"], "attempt 1 manifest must record evidence file hashes"

            # --- attempt 2: same target, second --onboard invocation ---
            # This is the exact scenario that used to raise StateMachineError
            # (SUCCESS -> READY on the same run_id). It must now succeed cleanly.
            m.do_onboard(new_target, str(kernel), analysis_engine="local-test", test_mode=True)

            state_2 = run_store.load_run(root, f"{new_target}-onboarding-2")
            assert state_2 is not None, "attempt 2 must persist under a NEW, distinct run_id"
            assert state_2["skill_invocations"]["target_onboarding"]["skill_state"] == "SUCCESS"

            manifest_2 = run_manifest.load_manifest(root, f"{new_target}-onboarding-2")
            assert manifest_2["attempt"] == 2
            assert manifest_2["run_id"] == f"{new_target}-onboarding-2"

            # attempt 1's own record is untouched by attempt 2.
            state_1_again = run_store.load_run(root, f"{new_target}-onboarding")
            assert state_1_again == state_1, "attempt 1's persisted state must not be mutated by attempt 2"
        finally:
            m.TARGETS_ROOT = original_targets_root
            m.WORKSPACE_ROOT = original_workspace_root

    print("PASS: two --onboard runs against the same target get distinct attempt "
          "run_ids, no StateMachineError, each with its own manifest + fingerprints")


def test_preexisting_unsuffixed_state_treated_as_attempt_one() -> None:
    """A state/<target>-onboarding.json from before the attempt model shipped
    (no attempt suffix) must be recognized as attempt 1, not orphaned."""
    import orchestrator.main as m

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state_dir = root / "audio_bu_skill" / "state"
        state_dir.mkdir(parents=True)
        legacy_record = {
            "run_id": "legacyboard-onboarding",
            "target_soc": "legacyboard",
            "nearest_target": "(pending onboarding)",
            "bringup_state": "INIT",
            "bringup_history": [],
            "skill_invocations": {
                "target_onboarding": {"skill_state": "SUCCESS", "history": []}
            },
        }
        (state_dir / "legacyboard-onboarding.json").write_text(json.dumps(legacy_record), encoding="utf-8")

        original_workspace_root = m.WORKSPACE_ROOT
        m.WORKSPACE_ROOT = root
        try:
            run_id, attempt, is_new = m._resolve_onboarding_run_id("legacyboard")
            assert attempt == 2 and is_new, (run_id, attempt, is_new)
            assert run_id == "legacyboard-onboarding-2"
        finally:
            m.WORKSPACE_ROOT = original_workspace_root

    print("PASS: pre-existing unsuffixed state file is recognized as attempt 1, "
          "and a terminal SUCCESS there allocates attempt 2 next")


def main() -> None:
    test_no_illegal_transition_between_attempts()
    test_two_attempts_get_distinct_run_ids()
    test_preexisting_unsuffixed_state_treated_as_attempt_one()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
