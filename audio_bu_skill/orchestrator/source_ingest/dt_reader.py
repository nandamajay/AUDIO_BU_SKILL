"""WP-SRC-A2 commit 1: kernel-DT reader (dts/dtsi → analysis["dt"]).

Reads audio pinctrl-state blocks from a kernel source tree and emits a
dict shape consumable by
:func:`orchestrator.source_ingest.pinmux.derive_pinmux_from_dt`. This
module is the *source-of-facts* half of WP-SRC-A2 — a follow-up commit
threads it through ``_build_audio_topology`` so real ``--onboard``
runs populate ``analysis["dt"]`` with real DT facts instead of the
empty placeholder currently pinned by the "nothing populates
analysis['dt']" note at ``target_onboarding_runner.py:645``.

Contract pinned by T-SRC-A2-{1,3,4} (``tests/test_source_ingest_dt_reader.py``):

  * ``read_dt_pinctrl(kernel_source_path, target) -> dict``.
  * Success: ``{"pinctrl": {<label>: {"function": <str>, "pins":
    [{"pin": <int>, "function": <int>, "role": <str>}, ...]}, ...}}``
    with a non-empty ``pinctrl`` sub-dict — composes with
    ``derive_pinmux_from_dt`` to yield a non-empty ``list[PinmuxFact]``.
  * Missing / non-directory / no ``arch/arm64/boot/dts/qcom`` subdir /
    no dtsi files / malformed dtsi / zero audio groups → ``{}`` (an
    empty dict, NOT the ``SOURCE_UNRESOLVED`` sentinel — sentinel
    emission is the wiring layer's job, so this reader has zero
    dependency on ``models.py`` and can be exercised in isolation).
  * Determinism (T-SRC-A2-4): sorted file iteration, sorted group
    keys, and pin lists sorted by ``(pin, role)`` guarantee
    byte-identical output on repeat invocations. Independently
    reinforced by ``json.dumps(..., sort_keys=True)`` at the test
    boundary.

Extraction strategy: regex-based scan of labelled pinctrl-state
blocks, filtered to labels whose prefix names an audio bus
(``i2s*``, ``mi2s*``, ``audio*``). Full DTS parsing (includes,
preprocessor, phandle resolution) is *deliberately* out of scope —
the pinctrl subset is regular enough that a naive brace-matched
regex sweep is sufficient for the WP-SRC-A2 north-star flip. Real
Nord dtsi files carry many properties the reader ignores by
construction.

Explicitly out of scope for commit 1:
  * Wiring into ``_build_audio_topology`` — T-SRC-A2 commit 2, will
    flip T-SRC-A2-2 from red to green on real ``--onboard`` runs.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * QUP endpoint derivation — WP-SRC-B territory.
  * Full DTS AST / preprocessor / include resolution — deferred until
    a phase where the regex approach demonstrably falls short.

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-A2, §5a (test-first),
      docs/PHASE3_KNOWN_GAPS.md G-3A.9.

Signed-off-by: Ajay Kumar Nandam <ajayn@qti.qualcomm.com>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Label-prefix hints for pinctrl nodes that name audio buses. sa8775p /
# Nord uses ``i2s*`` and ``mi2s*``; other SoCs use ``audio-*``. The list
# is a prefix filter, not an allowlist — any label whose lowercased
# prefix matches will be treated as an audio pinctrl state.
_AUDIO_LABEL_PREFIXES = ("i2s", "mi2s", "audio")

# TLMM I2S/mI2S function selector for sa8775p — the numeric selector
# consumed by the register-level cross-check in ``derive_pinmux_from_dt``.
# Kept as a constant because the mapping is fixed for our supported
# chips; generalising to a per-chip table is deferred (WP-SRC-B or
# later) so this reader stays SoC-agnostic in structure but only
# semantically valid for sa8775p Nord. Documented here so a future
# reader knows to promote it, not to duplicate it.
_I2S_FUNCTION_SELECTOR = 1


def _is_audio_label(label: str) -> bool:
    """True when ``label`` prefix names an audio-bus pinctrl namespace.

    Case-insensitive; matches Nord's ``i2s8_default`` and
    ``mi2s_primary_default`` styles as well as generic ``audio_*``.
    """
    low = label.lower()
    return any(low.startswith(p) for p in _AUDIO_LABEL_PREFIXES)


def _role_from_sub_name(name: str) -> str:
    """Sub-node ``<role>-pins`` → semantic role ``<role>``.

    Matches the DT convention where labelled sub-nodes suffix
    ``-pins`` (e.g. ``mclk-pins`` → ``mclk``). Names without the
    suffix pass through unchanged so unusual layouts still produce a
    recognisable role identifier for the ``gpio.i2s.<role>`` subject
    namespace downstream.
    """
    if name.endswith("-pins"):
        return name[: -len("-pins")]
    return name


def _find_matching_brace(text: str, start: int) -> int:
    """Return the index of the ``}`` matching ``text[start] == '{'``.

    Naive depth-counted brace matcher. Ignores braces inside strings
    and comments, which is safe here because DTS pinctrl blocks don't
    contain those constructs. Returns ``-1`` on unbalanced input,
    which cascades to a caller-visible "no groups extracted" outcome —
    exactly the T-SRC-A2-3 malformed-dtsi contract.
    """
    if start >= len(text) or text[start] != "{":
        return -1
    depth = 1
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_pins_from_body(body: str) -> list[dict[str, Any]]:
    """Extract ``{pin, function, role, _fn_name}`` entries from a state body.

    Iterates sub-blocks like::

        mclk-pins {
            pins = "gpio147";
            function = "i2s8";
            drive-strength = <8>;
        };

    and yields one entry per gpio referenced in the ``pins`` property.
    ``function`` (int) is the fixed TLMM I2S selector; ``_fn_name``
    (str) is the DT function-name string (e.g. ``"i2s8"``) — surfaced
    as the group-level ``function`` so ``_is_i2s_function`` matches
    downstream.
    """
    results: list[dict[str, Any]] = []
    sub_re = re.compile(r"([\w-]+)\s*\{")
    pins_re = re.compile(r"pins\s*=\s*([^;]+);")
    fn_re = re.compile(r'function\s*=\s*"([^"]+)"')
    gpio_re = re.compile(r'"gpio(\d+)"')

    pos = 0
    while pos < len(body):
        m = sub_re.search(body, pos)
        if not m:
            break
        sub_name = m.group(1)
        brace_start = m.end() - 1
        brace_end = _find_matching_brace(body, brace_start)
        if brace_end < 0:
            break
        sub_body = body[brace_start + 1 : brace_end]

        pins_prop = pins_re.search(sub_body)
        fn_prop = fn_re.search(sub_body)
        if pins_prop and fn_prop:
            role = _role_from_sub_name(sub_name)
            fn_name = fn_prop.group(1)
            for pin_str in gpio_re.findall(pins_prop.group(1)):
                results.append(
                    {
                        "pin": int(pin_str),
                        "function": _I2S_FUNCTION_SELECTOR,
                        "role": role,
                        "_fn_name": fn_name,
                    }
                )

        # Advance past the matched sub-block so a subsequent
        # ``sub_re.search`` doesn't re-enter this sub-body — critical
        # for correctness when the sub-body itself contains braces
        # (e.g. ``drive-strength = <8>;`` cannot but a future DT with
        # nested nodes could).
        pos = brace_end + 1

    return results


def _extract_pinctrl_groups(text: str) -> dict[str, dict[str, Any]]:
    """Extract audio pinctrl groups from a dtsi text.

    Scans labelled pinctrl-state blocks of the form
    ``<label>: <name>-state { ... }`` and, for each label matching
    :func:`_is_audio_label`, extracts its pin sub-blocks into a group
    entry ``{"function": <fn_name>, "pins": [<sorted entries>]}``.

    Insertion order is deterministic per input text (first-seen wins
    on label collision within a single file); ``read_dt_pinctrl``
    then re-sorts keys before returning to guarantee cross-file
    determinism.
    """
    groups: dict[str, dict[str, Any]] = {}
    label_re = re.compile(r"(\w+)\s*:\s*[\w-]+\s*\{")

    pos = 0
    while pos < len(text):
        m = label_re.search(text, pos)
        if not m:
            break
        label = m.group(1)
        brace_start = m.end() - 1
        brace_end = _find_matching_brace(text, brace_start)
        if brace_end < 0:
            break

        if _is_audio_label(label):
            body = text[brace_start + 1 : brace_end]
            pins_list = _extract_pins_from_body(body)
            if pins_list:
                fn_name = pins_list[0]["_fn_name"]
                clean_pins = sorted(
                    (
                        {
                            "pin": p["pin"],
                            "function": p["function"],
                            "role": p["role"],
                        }
                        for p in pins_list
                    ),
                    key=lambda p: (p["pin"], p["role"]),
                )
                # First-seen wins on label collision within one file —
                # combined with sorted file iteration in the caller,
                # this makes the aggregate output deterministic.
                if label not in groups:
                    groups[label] = {"function": fn_name, "pins": clean_pins}

        pos = brace_end + 1

    return groups


def read_dt_pinctrl(kernel_source_path: str, target: str) -> dict[str, Any]:
    """Read audio pinctrl groups from a kernel source tree.

    Walks ``<kernel_source_path>/arch/arm64/boot/dts/qcom/`` for
    ``*.dts`` and ``*.dtsi`` files, extracts audio-labelled pinctrl
    state blocks, and returns them in a dict shape consumable by
    ``derive_pinmux_from_dt``.

    Args:
      kernel_source_path: Filesystem path to a kernel source tree
        (e.g. the ``linux-nord`` checkout resolved from
        ``--kernel-source``).
      target: Target identifier (e.g. ``"nord-iq10"``). Reserved for
        future per-target dts filtering; the current reader is
        target-agnostic and merges audio groups from every dts/dtsi
        it finds under the qcom subdir. Kept in the signature so the
        caller does not need to change when target-scoped filtering
        lands.

    Returns:
      * On success — ``{"pinctrl": {<label>: {"function": <str>,
        "pins": [{"pin": <int>, "function": <int>, "role": <str>},
        ...]}, ...}}`` with a non-empty ``pinctrl`` sub-dict.
      * On missing path, non-directory, no ``arch/arm64/boot/dts/qcom``
        subdir, no dtsi files, malformed dtsi, or zero audio groups
        found — ``{}`` (empty dict). The caller at the wiring layer
        (``_build_audio_topology``) converts empty-dict downstream
        into the ``SOURCE_UNRESOLVED`` sentinel; this reader has zero
        knowledge of the sentinel and does not import ``models``.

    Determinism (T-SRC-A2-4): file iteration is ``sorted(...)``,
    groups within each file are extracted in document order,
    per-group pin lists are sorted by ``(pin, role)``, and the
    returned ``pinctrl`` dict is rebuilt in sorted-label order.
    ``json.dumps(..., sort_keys=True)`` at the test boundary then
    produces byte-identical output across repeated calls.
    """
    del target  # reserved — see docstring; suppress linter unused-arg

    try:
        root = Path(kernel_source_path)
    except (TypeError, ValueError):
        return {}
    if not root.is_dir():
        return {}

    dts_dir = root / "arch" / "arm64" / "boot" / "dts" / "qcom"
    if not dts_dir.is_dir():
        return {}

    try:
        candidates = sorted(
            list(dts_dir.glob("*.dts")) + list(dts_dir.glob("*.dtsi"))
        )
    except OSError:
        return {}

    all_groups: dict[str, dict[str, Any]] = {}
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, group in _extract_pinctrl_groups(text).items():
            # First-seen wins across the sorted file iteration — makes
            # aggregation deterministic without a merge policy.
            if label not in all_groups:
                all_groups[label] = group

    if not all_groups:
        return {}

    return {"pinctrl": {label: all_groups[label] for label in sorted(all_groups.keys())}}
