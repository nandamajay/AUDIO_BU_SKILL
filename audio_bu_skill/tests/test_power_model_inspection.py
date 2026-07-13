"""Unit tests for power_model_inspection (fixture rpmhpd.c / dtsi snippets).

Fixtures mirror the real drivers/pmdomain/qcom/rpmhpd.c structure enough to
exercise each graded status: source_confirmed (LCX+LMX present, as for
Eliza), source_confirmed (LCX+LMX absent, as for Nord), unknown (compatible
string not in file at all), missing (no rpmhpd.c present), and inferred
(compatible found but the backing array can't be resolved).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_power_model_inspection
(or: python3 audio_bu_skill/tests/test_power_model_inspection.py)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from orchestrator.runners.power_model_inspection import find_target_rpmhpd_compatible, inspect_power_model_source

_RPMHPD_FIXTURE = """
static struct rpmhpd *nord_rpmhpds[] = {
	[RPMHPD_CX] = &cx,
	[RPMHPD_MX] = &mx,
};

static const struct rpmhpd_desc nord_desc = {
	.rpmhpds = nord_rpmhpds,
	.num_pds = ARRAY_SIZE(nord_rpmhpds),
};

static struct rpmhpd *eliza_rpmhpds[] = {
	[RPMHPD_CX] = &cx,
	[RPMHPD_LCX] = &lcx,
	[RPMHPD_LMX] = &lmx,
	[RPMHPD_MX] = &mx,
};

static const struct rpmhpd_desc eliza_desc = {
	.rpmhpds = eliza_rpmhpds,
	.num_pds = ARRAY_SIZE(eliza_rpmhpds),
};

static const struct of_device_id rpmhpd_match_table[] = {
	{ .compatible = "qcom,nord-rpmhpd", .data = &nord_desc },
	{ .compatible = "qcom,eliza-rpmhpd", .data = &eliza_desc },
	{ .compatible = "qcom,ghost-rpmhpd", .data = &ghost_desc },
	{ }
};
"""

_ELIZA_DTSI_FIXTURE = """
remoteproc_adsp: remoteproc@1234000 {
	compatible = "qcom,eliza-adsp-pas";
	power-domains = <&rpmhpd RPMHPD_LCX>, <&rpmhpd RPMHPD_LMX>;
	power-domain-names = "lcx", "lmx";
	status = "disabled";
};
"""

_NORD_DTSI_FIXTURE = """
remoteproc_adsp: remoteproc@5678000 {
	compatible = "qcom,nord-adsp-pas";
	power-domains = <&rpmhpd RPMHPD_CX>;
	power-domain-names = "cx";
	status = "disabled";
};
"""


def _make_kernel(root: Path, *, with_rpmhpd: bool = True) -> Path:
    kernel = root / "linux-fake"
    rpmhpd_dir = kernel / "drivers" / "pmdomain" / "qcom"
    rpmhpd_dir.mkdir(parents=True, exist_ok=True)
    if with_rpmhpd:
        (rpmhpd_dir / "rpmhpd.c").write_text(_RPMHPD_FIXTURE, encoding="utf-8")
    return kernel


def _add_dtsi(kernel: Path, name: str, content: str) -> None:
    dts_dir = kernel / "arch" / "arm64" / "boot" / "dts" / "qcom"
    dts_dir.mkdir(parents=True, exist_ok=True)
    (dts_dir / f"{name}.dtsi").write_text(content, encoding="utf-8")


def test_source_confirmed_lcx_lmx_present_eliza() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        _add_dtsi(kernel, "eliza", _ELIZA_DTSI_FIXTURE)

        result = inspect_power_model_source(kernel, "qcom,eliza-rpmhpd", dtsi_search_name="eliza")
        assert result["status"] == "source_confirmed", result
        assert result["kind"] == "rpmhpd"
        assert result["lcx_present"] is True, result
        assert result["lmx_present"] is True, result
        assert result["lcx_lmx_present"] is True, result
        assert result["dtsi_confirms_lcx_lmx"] is True, result
        assert result["citations"], result
    print("PASS: eliza-style rpmhpd array (LCX+LMX present) -> source_confirmed, True/True")


def test_source_confirmed_lcx_lmx_absent_nord() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        _add_dtsi(kernel, "nord-iq10", _NORD_DTSI_FIXTURE)

        result = inspect_power_model_source(kernel, "qcom,nord-rpmhpd", dtsi_search_name="nord")
        assert result["status"] == "source_confirmed", result
        assert result["lcx_present"] is False, result
        assert result["lmx_present"] is False, result
        assert result["lcx_lmx_present"] is False, result
        assert result["dtsi_confirms_lcx_lmx"] is False, result
    print("PASS: nord-style rpmhpd array (LCX+LMX absent) -> source_confirmed, False/False "
          "(both are 'confirmed', just different answers)")


def test_unknown_compatible_not_in_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        result = inspect_power_model_source(kernel, "qcom,totally-unheard-of-rpmhpd")
        assert result["status"] == "unknown", result
        assert result["lcx_lmx_present"] is None, result
    print("PASS: compatible string absent from rpmhpd.c -> unknown")


def test_missing_no_rpmhpd_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp), with_rpmhpd=False)
        result = inspect_power_model_source(kernel, "qcom,eliza-rpmhpd")
        assert result["status"] == "missing", result
        assert result["citations"] == [], result
    print("PASS: no rpmhpd.c found anywhere under kernel_source -> missing")


def test_inferred_when_array_unresolvable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        rpmhpd_path = kernel / "drivers" / "pmdomain" / "qcom" / "rpmhpd.c"
        # ghost_desc's .data pointer is referenced in the match table but the
        # ghost_desc struct itself (and its backing array) is never defined --
        # simulates an unresolvable indirection (e.g. defined in another TU).
        result = inspect_power_model_source(kernel, "qcom,ghost-rpmhpd")
        assert result["status"] == "inferred", result
        assert result["lcx_lmx_present"] is None, result
        assert rpmhpd_path.is_file()  # sanity: file exists, just unresolvable
    print("PASS: compatible found but backing desc/array unresolvable -> inferred, not a false source_confirmed")


def test_dtsi_confirms_none_when_no_dtsi_given() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        result = inspect_power_model_source(kernel, "qcom,eliza-rpmhpd")  # no dtsi_search_name
        assert result["status"] == "source_confirmed", result
        assert result["dtsi_confirms_lcx_lmx"] is None, result
    print("PASS: omitting dtsi_search_name leaves dtsi_confirms_lcx_lmx=None, doesn't fabricate a match")


def test_never_writes_to_kernel_tree() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        _add_dtsi(kernel, "eliza", _ELIZA_DTSI_FIXTURE)
        before = sorted(str(p) for p in kernel.rglob("*"))
        inspect_power_model_source(kernel, "qcom,eliza-rpmhpd", dtsi_search_name="eliza")
        after = sorted(str(p) for p in kernel.rglob("*"))
        assert before == after, "kernel tree gained/lost files during inspection"
    print("PASS: inspect_power_model_source never mutates the kernel tree")


def test_find_target_rpmhpd_compatible_from_own_dtsi() -> None:
    """Real-world shape: the target's rpmhpd node (and its own compatible
    string) is wired directly in the checked-out .dtsi -- e.g. eliza.dtsi has
    `rpmhpd: power-controller { compatible = "qcom,eliza-rpmhpd"; ... }` --
    introduced by an ordinary base-platform commit kernel_history never sees.
    This must be found without any kernel_history involvement at all."""
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        _add_dtsi(kernel, "eliza", _ELIZA_DTSI_FIXTURE + '\n\nrpmhpd: power-controller {\n\tcompatible = "qcom,eliza-rpmhpd";\n};\n')

        compat = find_target_rpmhpd_compatible(kernel, "eliza")
        assert compat == "qcom,eliza-rpmhpd", compat
    print("PASS: find_target_rpmhpd_compatible locates the target's own rpmhpd compatible string in its dtsi")


def test_find_target_rpmhpd_compatible_none_when_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        _add_dtsi(kernel, "ghostboard", "// no rpmhpd node here\n")

        compat = find_target_rpmhpd_compatible(kernel, "ghostboard")
        assert compat is None, compat
    print("PASS: find_target_rpmhpd_compatible returns None (never fabricates) when no rpmhpd node exists")


def test_find_target_rpmhpd_compatible_empty_search_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _make_kernel(Path(tmp))
        assert find_target_rpmhpd_compatible(kernel, "") is None
    print("PASS: find_target_rpmhpd_compatible returns None on empty dtsi_search_name, no crash")


def main() -> None:
    test_source_confirmed_lcx_lmx_present_eliza()
    test_source_confirmed_lcx_lmx_absent_nord()
    test_unknown_compatible_not_in_file()
    test_missing_no_rpmhpd_source()
    test_inferred_when_array_unresolvable()
    test_dtsi_confirms_none_when_no_dtsi_given()
    test_never_writes_to_kernel_tree()
    test_find_target_rpmhpd_compatible_from_own_dtsi()
    test_find_target_rpmhpd_compatible_none_when_absent()
    test_find_target_rpmhpd_compatible_empty_search_name()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
