"""WP-SRC-A commit 1: pinmux source ingestion (DT → PinmuxFact list).

Pure, deterministic derivation function. Consumes a device-tree dict
carrying pinctrl groups and emits one ``PinmuxFact`` per pin in every
I2S* group. The emitted ``name`` field lands in the ``gpio.i2s.*``
namespace so the downstream ``machine_driver`` gate (prefix scan
``T1.gpio.i2s.*`` at ``machine_driver.py:217-226``) can flip open
once ``track_t1`` emits a row for it — that integration ships in the
T-SRC-A-2 wiring commit, not here.

Contract pinned by T-SRC-A-1 (``tests/test_source_ingest_pinmux.py``):

  * Function name: ``derive_pinmux_from_dt(dt) -> list[PinmuxFact]``.
  * For a DT carrying an I2S8 pinctrl group, the result MUST be
    non-empty.
  * Every entry MUST carry a ``name`` field (non-None) under the
    ``gpio.i2s.*`` namespace — per §4a-1 / R-SRC-A-1, a row without
    ``name`` closes the T1 gate even if pin/function match.

Determinism (T-SRC-A-4): iteration over pinctrl groups uses
``sorted(...)``; pin lists are consumed in given order (Python 3.7+
preserves list order, so this is stable). Byte-identical DT input
therefore yields byte-identical output. Mirrors the canonical-JSON
discipline enforced by ``crossverify_collector._canonical_json_bytes``.

Explicitly out of scope for commit 1:
  * ``SOURCE_UNRESOLVED`` sentinel — T-SRC-A-3 commit (Design B, see
    ``models.py``).
  * Wiring into ``_build_audio_topology`` — T-SRC-A-2 commit.
  * QUP endpoint derivation — WP-SRC-B territory.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * DT plumbing from ``--kernel-source`` into ``analysis["dt"]`` —
    G-3A.9 / WP-SRC-A2, blocks north-star flip.

Refs: PHASE3A_IMPLEMENTATION_PLAN.md §4 WP-SRC-A1, §5a (test-first),
      docs/PHASE3_KNOWN_GAPS.md G-3A.7, G-3A.9.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Re-exported so T-SRC-A-3's tri-path import contract passes; canonical
# definition lives in ``models.py``. Do NOT redefine it here.
from .models import SOURCE_UNRESOLVED as SOURCE_UNRESOLVED  # noqa: F401


@dataclass(frozen=True)
class PinmuxFact:
    """One derived pinmux entry.

    Immutable so callers cannot mutate ingestion output post-hoc; the
    downstream ``track_t1`` reader treats source facts as authoritative
    for the source side of the cross-verify comparison.

    Fields:
      * ``pin``: integer pin number (matches IPCAT ``gpio_list_gpios_from_map``
        payload ``number`` field for cross-check).
      * ``function``: integer function selector (matches IPCAT payload
        ``function`` field for cross-check).
      * ``role``: semantic role within the bus (e.g. ``mclk``, ``sclk``,
        ``ws``, ``data`` for I2S). Not currently cross-checked; kept for
        report readability and future subject decomposition.
      * ``name``: canonical subject namespace name — MUST be
        ``gpio.i2s.<role>`` for I2S groups so the machine_driver gate
        prefix scan matches.
    """

    pin: int
    function: int
    role: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict shaped for consumption by ``track_t1``.

        ``asdict`` on a frozen dataclass is deterministic (field
        declaration order), which preserves the T-SRC-A-4 canonical-JSON
        property across the dataclass → dict → JSON path.
        """
        return asdict(self)


def _is_i2s_function(function_name: Any) -> bool:
    """True when a DT pinctrl group's ``function`` names an I2S variant.

    Matches on the ``i2s`` prefix, case-insensitively — the sa8775p /
    Nord DT uses ``i2s8`` for I2S8, but the same code path handles
    ``i2s0``…``i2s9`` and any future variant without additional casework.
    """
    if not isinstance(function_name, str):
        return False
    return function_name.strip().lower().startswith("i2s")


def derive_pinmux_from_dt(dt: dict[str, Any]) -> list[PinmuxFact] | Any:
    """Derive pinmux facts from a DT dict's pinctrl section.

    Expected input shape::

        {
          "pinctrl": {
            "<group_name>": {
              "function": "i2s8" | "i2s<N>" | ...,
              "pins": [
                {"pin": <int>, "function": <int>, "role": <str>},
                ...
              ],
            },
            ...
          },
          ...
        }

    For each pinctrl group whose ``function`` names an I2S variant
    (see :func:`_is_i2s_function`), emits one :class:`PinmuxFact` per
    pin entry. The emitted ``name`` is ``f"gpio.i2s.{role}"``. Malformed
    groups (missing keys, non-dict entries) are skipped silently at the
    per-group level — silent-skip is acceptable within the loop because
    at least one well-formed I2S group produces a non-empty result.

    Return contract (§5 evidence doctrine, T-SRC-A-3, Design B):
      * At least one derived fact  → non-empty ``list[PinmuxFact]``.
      * Zero derivable facts (no pinctrl section, no I2S groups, or
        no valid pin entries in any I2S group) → the
        ``SOURCE_UNRESOLVED`` bare-singleton sentinel, NEVER a silent
        ``[]``. This is the "fail loudly, not silently" contract
        T-SRC-A-3 pins.

    Downstream consumers gate on **identity**: the canonical predicate
    is ``result is SOURCE_UNRESOLVED``, not ``isinstance(result, list)``
    or ``result == SOURCE_UNRESOLVED``. Identity distinguishes "we
    tried and got nothing usable" (sentinel) from "we got these
    specific facts" (list) unambiguously; equality / isinstance guards
    would confuse a payload that happened to shadow the sentinel with
    the sentinel itself, which Design B rejects by construction.
    """
    pinctrl = dt.get("pinctrl") if isinstance(dt, dict) else None
    if not isinstance(pinctrl, dict):
        return SOURCE_UNRESOLVED

    facts: list[PinmuxFact] = []
    # sorted() keeps output byte-identical across dict-insert-order
    # variations of the input — the T-SRC-A-4 determinism guarantee.
    for group_name in sorted(pinctrl.keys()):
        group = pinctrl[group_name]
        if not isinstance(group, dict):
            continue
        if not _is_i2s_function(group.get("function")):
            continue
        pins = group.get("pins")
        if not isinstance(pins, list):
            continue
        for entry in pins:
            if not isinstance(entry, dict):
                continue
            pin = entry.get("pin")
            fn = entry.get("function")
            role = entry.get("role")
            # A pinmux fact without a role has no name to render into
            # gpio.i2s.<role>; skip rather than emit a broken row (which
            # would close the machine_driver gate by R-SRC-A-1).
            if pin is None or fn is None or not isinstance(role, str) or not role:
                continue
            try:
                pin_int = int(pin)
                fn_int = int(fn)
            except (TypeError, ValueError):
                continue
            facts.append(
                PinmuxFact(
                    pin=pin_int,
                    function=fn_int,
                    role=role,
                    name=f"gpio.i2s.{role}",
                )
            )
    if not facts:
        return SOURCE_UNRESOLVED
    return facts
