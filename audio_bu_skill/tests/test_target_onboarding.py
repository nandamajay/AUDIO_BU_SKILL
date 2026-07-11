"""Smoke test for target_onboarding (v1.1 Phase 1).

Builds a tmp workspace with a minimal fake kernel tree + an existing target +
a new target's evidence folder, runs run_target_onboarding directly, and asserts:
  - similarity_report ranks >= 1 candidate,
  - the generated case renders as valid Python and builds a BringupCase,
  - the runner's output validates against the skill's validator,
  - the kernel tree is NOT mutated (sentinel hash unchanged),
  - no patch files are produced, and case.py is NOT created.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_target_onboarding
(or: python3 audio_bu_skill/tests/test_target_onboarding.py)
"""

from __future__ import annotations

import hashlib
import tempfile
import types
from pathlib import Path

from orchestrator.runners.target_onboarding_runner import run_target_onboarding

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_kernel(root: Path) -> Path:
    """A minimal kernel tree with the 4 required subdirs + audio codecs + a qcom dtsi."""
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    (kernel / ".git").mkdir(exist_ok=True)

    codecs = kernel / "sound" / "soc" / "codecs"
    codecs.mkdir(parents=True, exist_ok=True)
    (codecs / "pcm1681.c").write_text("// PCM1681 ASoC driver\n", encoding="utf-8")
    (codecs / "adau1977.c").write_text("// ADAU1977 family driver\n", encoding="utf-8")

    dts = kernel / "arch" / "arm64" / "boot" / "dts" / "qcom"
    dts.mkdir(parents=True, exist_ok=True)
    (dts / "fakesoc-audio.dtsi").write_text(
        'model = "fakesoc";\n'
        'compatible = "qcom,sa8797p";\n'
        'soc_audio: sound {\n'
        '    compatible = "qcom,q6apm-sound";\n'
        '    pcm1681_codec { compatible = "ti,pcm1681"; };\n'
        '    adsp { compatible = "qcom,sa8797p-adsp-pas"; power-domains = <&rpmhpd 0>; };\n'
        '};\n',
        encoding="utf-8",
    )
    return kernel


def _existing_target(targets_root: Path, name: str) -> None:
    """A DB target whose case.py names the same codecs (so it ranks as nearest)."""
    tdir = targets_root / name
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "case.py").write_text(
        "from orchestrator.bringup_walk import BringupCase\n"
        "CASE = BringupCase(\n"
        f"    target_soc='SA8797P',\n"
        f"    nearest_target='x',\n"
        f"    run_id='{name}-audio-bringup-2026-07',\n"
        "    kernel_source_path='linux-fake',\n"
        "    codec_part_numbers=['PCM1681', 'ADAU1977'],\n"
        "    codec_verdicts={'PCM1681': {'driver_path': 'sound/soc/codecs/pcm1681.c', 'status': 'upstream_present'}},\n"
        "    power_model_source='confirmed',\n"
        ")\n",
        encoding="utf-8",
    )


def _validate_output(output: dict) -> None:
    import importlib.util
    vpath = SKILLS_ROOT / "target_onboarding" / "validator.py"
    spec = importlib.util.spec_from_file_location("to_validator", vpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.validate_output(output)


def _render_and_exec(generated_case: dict) -> object:
    """Render case.generated.py via main's renderer, exec it, return CASE."""
    from orchestrator.main import _render_case_generated
    from orchestrator.bringup_walk import BringupCase

    src = _render_case_generated(generated_case)
    module = types.ModuleType("case_generated_under_test")
    # BringupCase is imported by the generated file's `from orchestrator...` line.
    exec(compile(src, "case.generated.py", "exec"), module.__dict__)
    case = getattr(module, "CASE", None)
    assert isinstance(case, BringupCase), "rendered case.generated.py did not build a BringupCase"
    return src, case


def test_onboard_smoke() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kernel = _fake_kernel(root)
        targets_root = root / "audio_bu_skill" / "targets"
        _existing_target(targets_root, "lemans-like")

        new_target = "newboard"
        new_dir = targets_root / new_target
        ev_offline = new_dir / "evidence" / "offline"
        ev_offline.mkdir(parents=True, exist_ok=True)
        # a datasheet whose filename carries a codec part number
        (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")

        sentinel = kernel / "sound" / "soc" / "codecs" / "pcm1681.c"
        before = _sha256(sentinel)
        kernel_files_before = sorted(str(p) for p in kernel.rglob("*"))

        envelope = {
            "workspace_context": {"workspace_root": str(root)},
            "target_name": new_target,
            "kernel_source_path": "linux-fake",
            "run_id": f"{new_target}-onboarding",
            "evidence_roots": {
                "ipcat": f"audio_bu_skill/targets/{new_target}/evidence/ipcat",
                "offline_documents": f"audio_bu_skill/targets/{new_target}/evidence/offline",
            },
        }

        # NOTE: run the runner with cwd-independent absolute workspace_root; the
        # runner imports main.load_case which resolves targets under the *real*
        # repo TARGETS_ROOT, so point target_db_root at our tmp DB explicitly.
        envelope["target_db_root"] = f"audio_bu_skill/targets"

        output = _run_with_tmp_targets(envelope, targets_root)

        # --- assertions ---
        ranked = output["similarity_report"]["ranked"]
        assert len(ranked) >= 1, "expected >=1 ranked candidate"
        assert ranked[0]["target_name"] == "lemans-like", ranked

        _validate_output(output)  # skill validator accepts the output

        src, case = _render_and_exec(output["generated_case"])
        assert "AUTO-GENERATED" in src and "NEEDS_REVIEW" in src
        assert case.run_id == f"{new_target}-onboarding"

        # kernel tree unmutated
        assert _sha256(sentinel) == before, "kernel sentinel file was modified"
        assert sorted(str(p) for p in kernel.rglob("*")) == kernel_files_before, "kernel tree gained/lost files"

        # no patches anywhere, and case.py not created by the runner
        assert not list(root.rglob("*.patch")), "onboarding produced patch files"
        assert not (new_dir / "case.py").exists(), "case.py must NOT be created"

    print("PASS: onboarding smoke — ranks candidate, renders valid case.generated.py, "
          "no kernel mutation, no patches, no case.py")


def _run_with_tmp_targets(envelope: dict, tmp_targets_root: Path) -> dict:
    """Run the runner while pointing load_case at the tmp target DB.

    The runner imports orchestrator.main.load_case (which uses the module-level
    TARGETS_ROOT). Temporarily patch that constant to the tmp DB so the smoke
    test is hermetic and never touches the real nord-iq10 case.
    """
    import orchestrator.main as m
    original = m.TARGETS_ROOT
    m.TARGETS_ROOT = tmp_targets_root
    try:
        return run_target_onboarding(envelope)
    finally:
        m.TARGETS_ROOT = original


def main() -> None:
    test_onboard_smoke()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
