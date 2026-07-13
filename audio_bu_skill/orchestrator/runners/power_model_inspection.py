"""Power-model source inspection for target_onboarding.

Mirrors the manual "read drivers/pmdomain/qcom/rpmhpd.c directly" step done
during the independent Eliza bring-up analysis, where the driver source
itself settled a question (does this SoC's rpmhpd array include LCX/LMX?)
that the current skill would otherwise leave as a blanket NEEDS_REVIEW.

Read-only: only ever reads files under kernel_source. Never writes, greps
via subprocess, or mutates anything.

Returns a graded status instead of a boolean:
  - "source_confirmed": the target's rpmhpd array was located and parsed;
    lcx_present/lmx_present are trustworthy.
  - "inferred": the target's compatible string (or its .data desc) was
    found, but the rpmhpd array itself could not be parsed with confidence.
  - "unknown": an rpmhpd.c was found, but this target's compatible string
    does not appear in it at all.
  - "missing": no rpmhpd driver source could be located under kernel_source.

Wired into target_onboarding_runner._power_model_hint (slice 2 of the
Onboarding Accuracy Upgrade, benchmark-readiness Fix #3).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_RPMHPD_CANDIDATE_PATHS = (
    "drivers/pmdomain/qcom/rpmhpd.c",
    "drivers/soc/qcom/rpmhpd.c",
)
_MAX_DTSI_SCAN = 500


def _find_rpmhpd_source(kernel_source: Path) -> Path | None:
    for rel in _RPMHPD_CANDIDATE_PATHS:
        candidate = kernel_source / rel
        if candidate.is_file():
            return candidate
    return None


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_desc_var(text: str, compatible: str) -> tuple[str, int] | None:
    """Find the `.data = &<desc_var>` paired with `.compatible = "<compatible>"`."""
    pattern = re.compile(
        r'\.compatible\s*=\s*"' + re.escape(compatible) + r'"\s*,\s*\.data\s*=\s*&(\w+)',
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1), _line_of(text, match.start())


def _find_array_name(text: str, desc_var: str) -> tuple[str, int] | None:
    """Find `.rpmhpds = <arr_name>` inside the `<desc_var> = { ... };` block."""
    desc_pattern = re.compile(re.escape(desc_var) + r'\s*=\s*\{(.*?)\};', re.DOTALL)
    desc_match = desc_pattern.search(text)
    if not desc_match:
        return None
    body = desc_match.group(1)
    arr_pattern = re.compile(r'\.rpmhpds\s*=\s*(\w+)')
    arr_match = arr_pattern.search(body)
    if not arr_match:
        return None
    return arr_match.group(1), _line_of(text, desc_match.start())


def _find_array_body(text: str, arr_name: str) -> tuple[str, int] | None:
    """Find the body of `static ... <arr_name>[] = { ... };`."""
    pattern = re.compile(re.escape(arr_name) + r'\s*\[\]\s*=\s*\{(.*?)\};', re.DOTALL)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1), _line_of(text, match.start())


_RPMHPD_COMPAT_IN_DTSI_RE = re.compile(r'compatible\s*=\s*"(qcom,[a-z0-9]+-rpmhpd)"')


def find_target_rpmhpd_compatible(kernel_source: str | Path, dtsi_search_name: str) -> str | None:
    """Best-effort: find the target's own ``qcom,<x>-rpmhpd`` compatible string
    directly in its checked-out .dts/.dtsi, independent of kernel_history.

    kernel_history's git-log archaeology only surfaces compatible strings
    introduced by FROMLIST/RFC/audio-tagged commits -- a target's rpmhpd node
    is typically wired up by an ordinary (non-audio-tagged) base-platform
    commit and is simply present in the checked-out tree today, so it is
    invisible to that search. This scans the target's own dtsi file(s)
    directly instead. Read-only; returns None (never raises) if no match.
    """
    if not dtsi_search_name:
        return None
    ks = Path(kernel_source)
    dts_root = ks / "arch" / "arm64" / "boot" / "dts"
    search_root = dts_root if dts_root.is_dir() else ks
    pattern = f"*{dtsi_search_name}*"
    candidates = list(search_root.rglob(pattern))[:_MAX_DTSI_SCAN]
    for path in candidates:
        if not path.is_file() or path.suffix not in (".dtsi", ".dts"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = _RPMHPD_COMPAT_IN_DTSI_RE.search(text)
        if match:
            return match.group(1)
    return None


def _scan_dtsi_for_adsp_power_domains(kernel_source: Path, dtsi_search_name: str) -> bool | None:
    """Best-effort: does `remoteproc_adsp`'s power-domain-names include lcx AND lmx?

    Returns None if no matching dtsi/node was found at all (not searched
    successfully), True/False once a remoteproc_adsp node was actually found.
    """
    if not dtsi_search_name:
        return None
    dts_root = kernel_source / "arch" / "arm64" / "boot" / "dts"
    search_root = dts_root if dts_root.is_dir() else kernel_source
    pattern = f"*{dtsi_search_name}*"
    candidates = list(search_root.rglob(pattern))[:_MAX_DTSI_SCAN]
    for path in candidates:
        if not path.is_file() or path.suffix not in (".dtsi", ".dts"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        node_match = re.search(r'remoteproc_adsp\s*:\s*remoteproc[^{]*\{(.*?)\n\s*\};', text, re.DOTALL)
        if not node_match:
            continue
        node_body = node_match.group(1)
        names_match = re.search(r'power-domain-names\s*=\s*([^;]+);', node_body)
        if not names_match:
            return False
        names = names_match.group(1).lower()
        return "lcx" in names and "lmx" in names
    return None


def inspect_power_model_source(
    kernel_source: str | Path, target_soc_compatible: str, *, dtsi_search_name: str = "",
) -> dict[str, Any]:
    """Inspect the kernel's rpmhpd driver source directly for target_soc_compatible.

    target_soc_compatible is the platform's `qcom,<x>-rpmhpd` compatible
    string (e.g. "qcom,eliza-rpmhpd"); dtsi_search_name, if given, is used to
    best-effort locate the SoC's own .dtsi and cross-check its
    remoteproc_adsp power-domain-names against the rpmhpd findings.
    """
    ks = Path(kernel_source)
    rpmhpd_path = _find_rpmhpd_source(ks)
    if rpmhpd_path is None:
        return {
            "status": "missing", "kind": None, "lcx_present": None, "lmx_present": None,
            "lcx_lmx_present": None, "dtsi_confirms_lcx_lmx": None, "citations": [],
        }

    text = rpmhpd_path.read_text(encoding="utf-8", errors="ignore")
    rel_path = str(rpmhpd_path.relative_to(ks)) if _is_relative(rpmhpd_path, ks) else str(rpmhpd_path)
    dtsi_confirms = _scan_dtsi_for_adsp_power_domains(ks, dtsi_search_name)

    desc_hit = _find_desc_var(text, target_soc_compatible)
    if desc_hit is None:
        return {
            "status": "unknown", "kind": None, "lcx_present": None, "lmx_present": None,
            "lcx_lmx_present": None, "dtsi_confirms_lcx_lmx": dtsi_confirms,
            "citations": [f"{rel_path} (compatible string not found)"],
        }
    desc_var, compat_line = desc_hit

    arr_hit = _find_array_name(text, desc_var)
    if arr_hit is None:
        return {
            "status": "inferred", "kind": "rpmhpd", "lcx_present": None, "lmx_present": None,
            "lcx_lmx_present": None, "dtsi_confirms_lcx_lmx": dtsi_confirms,
            "citations": [f"{rel_path}:{compat_line}"],
        }
    arr_name, desc_line = arr_hit

    body_hit = _find_array_body(text, arr_name)
    if body_hit is None:
        return {
            "status": "inferred", "kind": "rpmhpd", "lcx_present": None, "lmx_present": None,
            "lcx_lmx_present": None, "dtsi_confirms_lcx_lmx": dtsi_confirms,
            "citations": [f"{rel_path}:{compat_line}", f"{rel_path}:{desc_line}"],
        }
    body, arr_line = body_hit

    lcx_present = "RPMHPD_LCX" in body
    lmx_present = "RPMHPD_LMX" in body

    return {
        "status": "source_confirmed", "kind": "rpmhpd",
        "lcx_present": lcx_present, "lmx_present": lmx_present,
        "lcx_lmx_present": lcx_present and lmx_present,
        "dtsi_confirms_lcx_lmx": dtsi_confirms,
        "citations": [f"{rel_path}:{compat_line}", f"{rel_path}:{desc_line}", f"{rel_path}:{arr_line}"],
    }


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
