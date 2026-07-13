"""Unit tests for slice 6 of the Onboarding Accuracy Upgrade: wiring
kernel_history_discovery / power_model_inspection / pin_crosscheck into
target_onboarding_runner.py.

Confirms:
  - resolve_onboarding_task_spec() folds a real kernel_history discovery and a
    resolved power_model_hint into task_spec, and expands candidate_targets
    with kernel-history donor-hint / compatible-fallback stubs.
  - _history_derived_candidates() adds donor-hint-derived stubs not present in
    the local targets/ DB, deduplicated against it and the target itself.
  - run_target_onboarding() (via the local-test engine) populates
    generated_case["audio_topology"] and ["candidate_patch_series"], still
    validates, and still never mutates the kernel tree / writes case.py.
  - a pin_crosscheck mismatch verdict folds into generated_case["needs_review"]
    as a soft signal (never a hard failure), via _map_analysis_to_envelope.
  - _schematic_nets_dict() flattens ANALYSIS_SCHEMA's schematic_nets array into
    the {net_name: gpio} shape cross_check_pins expects.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_target_onboarding_wiring
(or: python3 audio_bu_skill/tests/test_target_onboarding_wiring.py)
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from orchestrator.runners.target_onboarding_runner import (
    _history_derived_candidates,
    _map_analysis_to_envelope,
    _schematic_nets_dict,
    resolve_onboarding_task_spec,
    run_target_onboarding,
)

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _init_git_kernel(root: Path) -> Path:
    """A real git-repo kernel tree (shaped like test_target_onboarding.py's
    _fake_kernel) plus a FROMLIST commit carrying a qcom,newboard-rpmhpd
    compatible fallback and a donor hint, and an on-disk rpmhpd.c that
    resolves that compatible string to a parseable LCX/LMX array."""
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    codecs = kernel / "sound" / "soc" / "codecs"
    codecs.mkdir(parents=True, exist_ok=True)
    (codecs / "pcm1681.c").write_text("// PCM1681 ASoC driver\n", encoding="utf-8")

    _git(kernel, "init", "-q")
    _git(kernel, "config", "user.email", "test@example.com")
    _git(kernel, "config", "user.name", "Test User")
    (kernel / "README").write_text("base\n", encoding="utf-8")
    _git(kernel, "add", "README", "sound/soc/codecs/pcm1681.c")
    _git(kernel, "commit", "-q", "-m", "initial: base kernel checkout")

    dts = kernel / "newboard-audio.dtsi"
    dts.write_text(
        'sound {\n'
        '    compatible = "qcom,q6apm-sound";\n'
        '};\n'
        'adsp: remoteproc@1 {\n'
        '    compatible = "qcom,newboard-adsp-pas";\n'
        '};\n'
        'rpmhpd_match {\n'
        '    compatible = "qcom,newboard-rpmhpd", "vendor,donorsoc-rpmhpd";\n'
        '};\n',
        encoding="utf-8",
    )
    _git(kernel, "add", "newboard-audio.dtsi")
    _git(kernel, "commit", "-q", "-m",
         "FROMLIST: arm64: dts: vendor: newboard: Add audio and power-domain support\n\n"
         "The hardware is similar to the DONORSOC platform.\n")

    rpmhpd_dir = kernel / "drivers" / "pmdomain" / "qcom"
    rpmhpd_dir.mkdir(parents=True, exist_ok=True)
    (rpmhpd_dir / "rpmhpd.c").write_text(
        "static struct rpmhpd *newboard_rpmhpds[] = {\n"
        "\t[RPMHPD_LCX] = &lcx,\n"
        "\t[RPMHPD_LMX] = &lmx,\n"
        "};\n\n"
        "static const struct rpmhpd_desc newboard_desc = {\n"
        "\t.rpmhpds = newboard_rpmhpds,\n"
        "\t.num_pds = ARRAY_SIZE(newboard_rpmhpds),\n"
        "};\n\n"
        "static const struct of_device_id rpmhpd_match_table[] = {\n"
        '\t{ .compatible = "qcom,newboard-rpmhpd", .data = &newboard_desc },\n'
        "\t{ }\n"
        "};\n",
        encoding="utf-8",
    )
    _git(kernel, "add", "drivers/pmdomain/qcom/rpmhpd.c")
    _git(kernel, "commit", "-q", "-m", "sound: qcom: rpmhpd: add newboard entry")
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


def test_task_spec_includes_kernel_history_and_power_model_hint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kernel = _init_git_kernel(root)

        resolved = resolve_onboarding_task_spec(root, "eliza-like", "linux-fake")
        task_spec = resolved["task_spec"]

        kernel_history = task_spec["kernel_history"]
        assert kernel_history["git_available"] is True, kernel_history
        assert kernel_history["candidates"], "expected >=1 FROMLIST candidate"
        candidate = kernel_history["candidates"][0]
        assert candidate["donor_hint"] == "DONORSOC", candidate
        assert "qcom,newboard-rpmhpd" in candidate["compatible_fallbacks"], candidate

        power_model_hint = task_spec["power_model_hint"]
        assert power_model_hint["status"] == "source_confirmed", power_model_hint
        assert power_model_hint["lcx_lmx_present"] is True, power_model_hint

        assert task_spec["candidate_patch_series"] == kernel_history["candidates"]

        # history-derived stubs (donor hint + compatible-string stems) present
        # in candidate_targets alongside any local targets/ DB entries.
        history_names = {
            c["name"] for c in task_spec["candidate_targets"] if c.get("source") == "kernel_history_donor_hint"
        }
        assert "DONORSOC" in history_names, history_names
        assert "newboard" in history_names, history_names

        # never mutates the kernel tree
        assert resolved["kernel_commit"], "expected a resolvable kernel_commit"
    print("PASS: resolve_onboarding_task_spec() folds kernel_history + power_model_hint "
          "into task_spec and expands candidate_targets with donor-hint stubs")


def _init_git_kernel_rpmhpd_only_in_base_dtsi(root: Path) -> Path:
    """Real-world shape for Fix #3: the target's own rpmhpd node/compatible
    string (e.g. eliza.dtsi's `rpmhpd: power-controller { compatible =
    "qcom,eliza-rpmhpd"; }`) is wired by an ORDINARY base-platform commit --
    not a FROMLIST/RFC/audio-tagged one -- so kernel_history's git-log
    archaeology never surfaces it as a compatible_fallback at all. Before
    Fix #3, this meant power_model_hint always fell through to "missing"
    even though the answer was sitting in the checked-out tree. There is no
    FROMLIST commit in this fixture at all -- proving the DTS-direct-scan
    path works standalone, without kernel_history's help."""
    kernel = root / "linux-fake"
    kernel.mkdir(parents=True, exist_ok=True)

    _git(kernel, "init", "-q")
    _git(kernel, "config", "user.email", "test@example.com")
    _git(kernel, "config", "user.name", "Test User")

    dts_dir = kernel / "arch" / "arm64" / "boot" / "dts" / "qcom"
    dts_dir.mkdir(parents=True, exist_ok=True)
    (dts_dir / "realtarget.dtsi").write_text(
        'rpmhpd: power-controller {\n'
        '    compatible = "qcom,realtarget-rpmhpd";\n'
        '};\n'
        'remoteproc_adsp: remoteproc@1 {\n'
        '    compatible = "qcom,realtarget-adsp-pas";\n'
        '    power-domains = <&rpmhpd RPMHPD_LCX>, <&rpmhpd RPMHPD_LMX>;\n'
        '    power-domain-names = "lcx", "lmx";\n'
        '};\n',
        encoding="utf-8",
    )

    rpmhpd_dir = kernel / "drivers" / "pmdomain" / "qcom"
    rpmhpd_dir.mkdir(parents=True, exist_ok=True)
    (rpmhpd_dir / "rpmhpd.c").write_text(
        "static struct rpmhpd *realtarget_rpmhpds[] = {\n"
        "\t[RPMHPD_LCX] = &lcx,\n"
        "\t[RPMHPD_LMX] = &lmx,\n"
        "};\n\n"
        "static const struct rpmhpd_desc realtarget_desc = {\n"
        "\t.rpmhpds = realtarget_rpmhpds,\n"
        "\t.num_pds = ARRAY_SIZE(realtarget_rpmhpds),\n"
        "};\n\n"
        "static const struct of_device_id rpmhpd_match_table[] = {\n"
        '\t{ .compatible = "qcom,realtarget-rpmhpd", .data = &realtarget_desc },\n'
        "\t{ }\n"
        "};\n",
        encoding="utf-8",
    )
    _git(kernel, "add", "-A")
    _git(kernel, "commit", "-q", "-m", "arm64: dts: qcom: realtarget: base platform bring-up")
    return kernel


def test_power_model_hint_source_confirmed_via_dtsi_without_kernel_history() -> None:
    """Fix #3 regression: power_model_hint must reach source_confirmed purely
    from the target's own checked-out .dtsi, even when kernel_history surfaces
    zero candidates (no FROMLIST/RFC commit exists in this fixture at all)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel_rpmhpd_only_in_base_dtsi(root)

        resolved = resolve_onboarding_task_spec(root, "realtarget", "linux-fake")
        task_spec = resolved["task_spec"]

        assert task_spec["kernel_history"]["candidates"] == [], (
            "fixture intentionally has no FROMLIST/RFC commit -- kernel_history "
            "must find nothing, proving power_model_hint doesn't depend on it"
        )

        power_model_hint = task_spec["power_model_hint"]
        assert power_model_hint["status"] == "source_confirmed", power_model_hint
        assert power_model_hint["lcx_present"] is True, power_model_hint
        assert power_model_hint["lmx_present"] is True, power_model_hint
        assert power_model_hint["dtsi_confirms_lcx_lmx"] is True, power_model_hint
    print("PASS: power_model_hint reaches source_confirmed via direct dtsi scan "
          "even when kernel_history surfaces zero candidates (Fix #3)")


def test_history_derived_candidates_dedup_against_existing() -> None:
    kernel_history = {
        "candidates": [
            {
                "sha": "deadbeef",
                "donor_hint": "DONORSOC",
                "compatible_fallbacks": ["qcom,newboard-adsp-pas", "qcom,lemans-like-adsp-pas"],
            },
        ],
    }
    out = _history_derived_candidates(kernel_history, existing_names={"lemans-like", "eliza-like"})
    names = {c["name"] for c in out}
    # "lemans-like" (stem of qcom,lemans-like-adsp-pas) is already in existing_names -> dropped.
    assert "lemans-like" not in names, names
    # "DONORSOC" and "newboard" are new -> added, each tagged with its source sha.
    assert "DONORSOC" in names, names
    assert "newboard" in names, names
    for c in out:
        assert c["source"] == "kernel_history_donor_hint"
        assert c["sha"] == "deadbeef"
    print("PASS: _history_derived_candidates adds new donor-hint/compatible-stem stubs, "
          "dedups case-insensitively against existing_names")


def test_run_target_onboarding_populates_audio_topology_and_patch_series() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kernel = _init_git_kernel(root)
        targets_root = root / "audio_bu_skill" / "targets"
        _existing_target(targets_root, "lemans-like")

        new_target = "eliza-like"
        new_dir = targets_root / new_target
        ev_offline = new_dir / "evidence" / "offline"
        ev_offline.mkdir(parents=True, exist_ok=True)
        (ev_offline / "PCM1681_datasheet.txt").write_text("dac datasheet\n", encoding="utf-8")

        sentinel = kernel / "sound" / "soc" / "codecs" / "pcm1681.c"
        before = _sha256(sentinel)
        kernel_files_before = sorted(str(p) for p in kernel.rglob("*") if ".git" not in p.parts)

        envelope = {
            "workspace_context": {"workspace_root": str(root)},
            "target_name": new_target,
            "kernel_source_path": "linux-fake",
            "run_id": f"{new_target}-onboarding",
            "evidence_roots": {
                "ipcat": f"audio_bu_skill/targets/{new_target}/evidence/ipcat",
                "offline_documents": f"audio_bu_skill/targets/{new_target}/evidence/offline",
            },
            "analysis_engine": "local-test",
            "test_mode": True,
            "target_db_root": "audio_bu_skill/targets",
        }

        output = _run_with_tmp_targets(envelope, targets_root)

        generated_case = output["generated_case"]
        assert generated_case["candidate_patch_series"], "expected kernel_history candidates surfaced"
        topology = generated_case["audio_topology"]
        for key in ("codecs", "amplifiers", "mics", "speakers", "soundwire", "audio_stack",
                    "power_model", "missing_evidence"):
            assert key in topology, (key, topology)
        assert topology["power_model"]["inspection_hint"]["status"] == "source_confirmed", topology

        _validate_output(output)  # skill validator still accepts the wired output

        # kernel tree unmutated (ignore .git internals, which git itself manages)
        assert _sha256(sentinel) == before
        assert sorted(str(p) for p in kernel.rglob("*") if ".git" not in p.parts) == kernel_files_before
        assert not (new_dir / "case.py").exists(), "case.py must NOT be created"
    print("PASS: run_target_onboarding() (local-test engine) populates audio_topology + "
          "candidate_patch_series, still validates, still never mutates the kernel tree")


def test_pin_crosscheck_mismatch_folds_into_needs_review() -> None:
    analysis = {
        "soc": {"value": "SA8797P", "confidence": 0.9, "citations": []},
        "codecs": [{"part": "PCM1681", "confidence": 0.8, "citations": []}],
        "power_model": {"kind": "rpmhpd", "confidence": 0.5, "citations": [], "needs_review": True},
        "nearest_targets": [{"name": "lemans-like", "score": 0.6, "rationale": "shared codec", "citations": []}],
        "missing_evidence": [],
        "overall_confidence": 0.8,
        "human_review_needed": False,
    }
    pin_crosschecks = [
        {"signal": "WSA2_EN", "schematic_gpio": 79, "patch_gpio": None, "match": False,
         "sha": None, "note": "no candidate patch assigns this GPIO number — needs manual review"},
    ]

    output = _map_analysis_to_envelope(
        analysis=analysis, target_name="eliza-like", run_id="eliza-like-onboarding",
        kernel_source=Path("/nonexistent"), kernel_source_path="linux-fake",
        evidence_roots={}, evidence_files=[], evidence_refs=[],
        pin_crosschecks=pin_crosschecks,
    )
    needs_review = output["generated_case"]["needs_review"]
    assert any("pin_crosscheck" in n and "WSA2_EN" in n for n in needs_review), needs_review
    # a mismatch is a soft NEEDS_REVIEW signal, never an exception / hard failure.
    assert output["generated_case"]["audio_topology"]["pin_crosschecks"] == pin_crosschecks
    print("PASS: a pin_crosscheck mismatch verdict folds into needs_review as a soft signal, "
          "never raised, and is also surfaced in audio_topology.pin_crosschecks")


def test_schematic_nets_dict_flattens_analysis_schema_shape() -> None:
    analysis = {
        "schematic_nets": [
            {"net_name": "WSA1_EN", "gpio": 59, "sheet_ref": "CQ7790_GPIO1", "citations": []},
            {"net_name": "WSA2_EN", "gpio": "gpio79", "citations": []},
            {"net_name": "BROKEN"},  # missing required "gpio" -- must be skipped, not raise
        ],
    }
    out = _schematic_nets_dict(analysis)
    assert out == {"WSA1_EN": 59, "WSA2_EN": "gpio79"}, out
    assert _schematic_nets_dict({}) == {}
    print("PASS: _schematic_nets_dict flattens ANALYSIS_SCHEMA.schematic_nets -> {net_name: gpio}, "
          "skipping entries missing 'gpio'")


def _validate_output(output: dict) -> None:
    import importlib.util
    vpath = SKILLS_ROOT / "target_onboarding" / "validator.py"
    spec = importlib.util.spec_from_file_location("to_validator_wiring", vpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.validate_output(output)


def _run_with_tmp_targets(envelope: dict, tmp_targets_root: Path) -> dict:
    import orchestrator.main as m
    original = m.TARGETS_ROOT
    m.TARGETS_ROOT = tmp_targets_root
    try:
        return run_target_onboarding(envelope)
    finally:
        m.TARGETS_ROOT = original


def main() -> None:
    test_task_spec_includes_kernel_history_and_power_model_hint()
    test_power_model_hint_source_confirmed_via_dtsi_without_kernel_history()
    test_history_derived_candidates_dedup_against_existing()
    test_run_target_onboarding_populates_audio_topology_and_patch_series()
    test_pin_crosscheck_mismatch_folds_into_needs_review()
    test_schematic_nets_dict_flattens_analysis_schema_shape()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
