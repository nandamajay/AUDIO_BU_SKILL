"""Unit tests for pin_crosscheck (schematic nets vs. FROMLIST-patch GPIOs).

Uses a real temp git repo (same fixture style as test_kernel_history_discovery)
so cross_check_pins exercises the real `git show` diff path, not a mock.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_pin_crosscheck
(or: python3 audio_bu_skill/tests/test_pin_crosscheck.py)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from orchestrator.runners.pin_crosscheck import cross_check_pins, extract_gpio_assignments


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "initial")


def _add_dts_patch(repo: Path) -> str:
    dts = repo / "newboard-cqs-evk.dts"
    dts.write_text(
        'spkr_1_sd_n_active: spkr-1-sd-n-active-state {\n'
        '    pins = "gpio59";\n'
        '    function = "gpio";\n'
        '};\n\n'
        '&pm7550_gpios {\n'
        '    dmic-eldo-en-hog {\n'
        '        gpio-hog;\n'
        '        gpios = <7 GPIO_ACTIVE_HIGH>;\n'
        '        output-high;\n'
        '    };\n'
        '};\n\n'
        'left_spkr: speaker@0,0 {\n'
        '    powerdown-gpios = <&tlmm 59 GPIO_ACTIVE_LOW>;\n'
        '};\n',
        encoding="utf-8",
    )
    _git(repo, "add", "newboard-cqs-evk.dts")
    _git(repo, "commit", "-q", "-m", "FROMLIST: arm64: dts: vendor: newboard: sound card support")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _fake_patch_entry(sha: str) -> dict:
    return {"sha": sha, "subject": "FROMLIST: sound card support", "files_changed": ["newboard-cqs-evk.dts"]}


def test_extract_gpio_assignments_covers_all_three_shapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)
        from orchestrator.runners.kernel_history_discovery import _diff_text
        diff = _diff_text(repo, sha)

        assignments = extract_gpio_assignments(diff)
        gpios = {a["gpio"] for a in assignments}
        assert 59 in gpios, assignments   # both pinctrl "gpio59" and powerdown-gpios <&tlmm 59 ...>
        assert 7 in gpios, assignments    # gpio-hog gpios = <7 ...>
        kinds = {a["kind"] for a in assignments}
        assert "gpio_property" in kinds and "gpio_hog" in kinds and "pinctrl_pins" in kinds, kinds
    print("PASS: extract_gpio_assignments finds controller-ref, gpio-hog, and pinctrl-pin GPIOs")


def test_match_found_for_matching_net() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)

        schematic_nets = {"WSA1_EN": 59, "DMIC_ELDO_EN": 7}
        results = cross_check_pins(schematic_nets, [_fake_patch_entry(sha)], repo)

        by_signal = {r["signal"]: r for r in results}
        assert by_signal["WSA1_EN"]["match"] is True, by_signal["WSA1_EN"]
        assert by_signal["WSA1_EN"]["sha"] == sha
        assert by_signal["DMIC_ELDO_EN"]["match"] is True, by_signal["DMIC_ELDO_EN"]
    print("PASS: matching schematic GPIO net found in FROMLIST patch -> match=True with sha")


def test_mismatch_is_needs_review_not_hard_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)

        schematic_nets = {"WSA2_EN": 79}  # not present in any patch (only 59 and 7 are)
        results = cross_check_pins(schematic_nets, [_fake_patch_entry(sha)], repo)

        assert len(results) == 1
        assert results[0]["match"] is False, results[0]
        assert results[0]["signal"] == "WSA2_EN"
        assert "note" in results[0]  # explanatory, not an exception
    print("PASS: non-matching net -> match=False + note, no exception raised (soft NEEDS_REVIEW signal)")


def test_gpio_label_string_normalized() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)

        schematic_nets = {"WSA1_EN": "gpio59"}  # string label, not a bare int
        results = cross_check_pins(schematic_nets, [_fake_patch_entry(sha)], repo)
        assert results[0]["match"] is True, results[0]
        assert results[0]["schematic_gpio"] == 59
    print("PASS: string GPIO labels (e.g. 'gpio59') are normalized to int before comparison")


def test_unparseable_schematic_value_flagged_not_crashed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)

        schematic_nets = {"CODEC_RESET_N": "PMIC_D_GPIO_05"}  # no digits at all... actually has "05"
        schematic_nets_truly_unparseable = {"MYSTERY_NET": None}
        results = cross_check_pins(schematic_nets_truly_unparseable, [_fake_patch_entry(sha)], repo)
        assert results[0]["match"] is None, results[0]
        assert "note" in results[0]
    print("PASS: unparseable schematic GPIO value -> match=None + note, no crash")


def test_ignores_patches_not_touching_dts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)
        non_dts_patch = {"sha": sha, "subject": "irrelevant", "files_changed": ["Makefile"]}

        results = cross_check_pins({"WSA1_EN": 59}, [non_dts_patch], repo)
        assert results[0]["match"] is False, results[0]
    print("PASS: patches whose files_changed lists no .dts/.dtsi are skipped for GPIO extraction")


def test_never_mutates_kernel_tree() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "kernel"
        _init_repo(repo)
        sha = _add_dts_patch(repo)
        before = sorted(str(p) for p in repo.rglob("*"))

        cross_check_pins({"WSA1_EN": 59, "WSA2_EN": 79}, [_fake_patch_entry(sha)], repo)

        after = sorted(str(p) for p in repo.rglob("*"))
        assert before == after
    print("PASS: cross_check_pins never mutates the kernel tree")


def main() -> None:
    test_extract_gpio_assignments_covers_all_three_shapes()
    test_match_found_for_matching_net()
    test_mismatch_is_needs_review_not_hard_failure()
    test_gpio_label_string_normalized()
    test_unparseable_schematic_value_flagged_not_crashed()
    test_ignores_patches_not_touching_dts()
    test_never_mutates_kernel_tree()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
