"""Pin-level schematic-to-DT cross-check for target_onboarding.

Mirrors the manual "does the schematic's GPIO net match the FROMLIST patch's
GPIO assignment" check done during the independent Eliza analysis (e.g.
schematic net SM_GPIO_79 -> WSA2_EN, cross-checked against FROMLIST commit
347a51dff15e's ``powerdown-gpios = <&tlmm 79 ...>`` for the right speaker).

Matching is done purely by GPIO NUMBER equality between a schematic-derived
net (``{signal_name: gpio_number}``) and every GPIO number found in the
patches' diffs -- there is no attempt to correlate DT node/property names
back to schematic net labels (that mapping is unreliable across vendors), so
a match is corroborating evidence, never proof, and a non-match is a
NEEDS_REVIEW signal, never a hard failure.

Read-only: only ever runs ``git show`` against kernel_source. Never writes,
applies, or checks out anything.

Not wired into the onboarding runner yet (slice 3 of the Onboarding Accuracy
Upgrade) -- this file is standalone and self-tested only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from orchestrator.runners.kernel_history_discovery import _diff_text

_GPIO_CONTROLLER_RE = re.compile(r'gpios?\s*=\s*<&\w+\s+(\d+)')
_GPIO_HOG_RE = re.compile(r'gpios?\s*=\s*<(\d+)\s+GPIO_ACTIVE')
_GPIO_PINCTRL_RE = re.compile(r'pins\s*=\s*"gpio(\d+)"')
_GPIO_NUMBER_IN_STRING_RE = re.compile(r'(\d+)')


def extract_gpio_assignments(diff_text: str) -> list[dict[str, Any]]:
    """Every added-line GPIO number assignment relevant to pin cross-checking.

    Covers the three shapes seen in the real FROMLIST series: controller-
    referenced GPIOs (``powerdown-gpios = <&tlmm 59 ...>``), gpio-hog children
    (``gpios = <7 GPIO_ACTIVE_HIGH>``), and pinctrl pin-name states
    (``pins = "gpio59";``).
    """
    results: list[dict[str, Any]] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        context = line[1:].strip()
        for pattern, kind in (
            (_GPIO_CONTROLLER_RE, "gpio_property"),
            (_GPIO_HOG_RE, "gpio_hog"),
            (_GPIO_PINCTRL_RE, "pinctrl_pins"),
        ):
            for match in pattern.finditer(line):
                results.append({"gpio": int(match.group(1)), "context": context, "kind": kind})
    return results


def _normalize_gpio(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = _GPIO_NUMBER_IN_STRING_RE.search(value)
        if match:
            return int(match.group(1))
    return None


def _touches_dts(patch: dict[str, Any]) -> bool:
    return any(str(f).endswith((".dts", ".dtsi")) for f in patch.get("files_changed") or [])


def cross_check_pins(
    schematic_nets: dict[str, Any], candidate_patches: list[dict[str, Any]], kernel_source: str | Path,
) -> list[dict[str, Any]]:
    """Cross-check schematic-derived GPIO nets against candidate patches' DT GPIOs.

    schematic_nets: {net_name: gpio_number_or_label}, e.g.
        {"WSA1_EN": 59, "WSA2_EN": "gpio79", "DMIC_ELDO_EN": 7}
    candidate_patches: the ``candidates`` list from discover_kernel_history
        (each needs at least ``sha`` and ``files_changed``); only patches
        touching a .dts/.dtsi are inspected.

    Returns one verdict per schematic net; never raises, never treats a
    non-match as fatal.
    """
    ks = Path(kernel_source)
    dts_patches = [p for p in candidate_patches if _touches_dts(p)]

    diff_cache: dict[str, str] = {}

    def _diff(sha: str) -> str:
        if sha not in diff_cache:
            diff_cache[sha] = _diff_text(ks, sha)
        return diff_cache[sha]

    results: list[dict[str, Any]] = []
    for net_name, raw_value in schematic_nets.items():
        gpio_number = _normalize_gpio(raw_value)
        if gpio_number is None:
            results.append({
                "signal": net_name, "schematic_gpio": raw_value, "patch_gpio": None,
                "match": None, "sha": None, "note": "schematic GPIO value unparseable — needs manual review",
            })
            continue

        found: dict[str, Any] | None = None
        for patch in dts_patches:
            for assignment in extract_gpio_assignments(_diff(patch["sha"])):
                if assignment["gpio"] == gpio_number:
                    found = {"sha": patch["sha"], "subject": patch.get("subject", ""),
                              "context": assignment["context"]}
                    break
            if found:
                break

        if found:
            results.append({
                "signal": net_name, "schematic_gpio": gpio_number, "patch_gpio": gpio_number,
                "match": True, "sha": found["sha"], "subject": found["subject"], "context": found["context"],
            })
        else:
            results.append({
                "signal": net_name, "schematic_gpio": gpio_number, "patch_gpio": None,
                "match": False, "sha": None,
                "note": "no candidate patch assigns this GPIO number — needs manual review",
            })
    return results
