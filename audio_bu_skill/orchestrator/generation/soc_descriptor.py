"""Phase B — SoC-aware driver source resolution.

Replaces the hardcoded ``_DRIVER_MATCH_REL`` / ``_MATCH_TABLE_SYMBOL``
constants in ``source_probe.py`` with discovery-based resolution that:

  * Identifies the machine-driver file from the kernel source tree by
    scanning ``sound/soc/qcom/*.c`` for match-table entries that reference
    the target SoC family.
  * Supports future SoCs (any family string) and future kernels (any new
    driver file layout).
  * Emits explicit disclosures for unresolved cases (``reviewer_required``).
  * Never fabricates a match — RESOLUTION_FAILED with evidence when no
    driver file can be grounded.

Design model (Phase B requirements):

  * **Onboarding** told us WHAT hardware exists (SoC = sa8775p family).
  * **Kernel source** tells us HOW upstream expresses it (which ``.c``
    file hosts the family, which symbol names the match table).
  * **Curated** input = the ``soc_family_hint`` itself — it is REVIEW_REQUIRED
    because neither onboarding nor kernel source can canonically derive it.
  * **Generation** deterministically uses the resolved descriptor.

Hard constraints:

  * READ-ONLY. Scans files (open + read), never writes/globs outside
    ``sound/soc/qcom/``, no network.
  * DETERMINISTIC. Same tree + same hint → same descriptor.
  * HONEST DEGRADATION. Missing tree / no match → RESOLUTION_FAILED,
    never a fabricated match.
  * DISCLOSURE-ONLY DOWNSTREAM. The descriptor informs ``SourceProbe``
    which file to open; it does not itself reach any gate or byte output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ResolutionMethod(str, Enum):
    """How the driver source was resolved."""

    DISCOVERED = "DISCOVERED"
    STATIC_FALLBACK = "STATIC_FALLBACK"
    RESOLUTION_FAILED = "RESOLUTION_FAILED"


_MODULE_DEVICE_TABLE_RE = re.compile(
    r"MODULE_DEVICE_TABLE\s*\(\s*of\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
)

_MATCH_ENTRY_DATA_RE = re.compile(
    r'\{\s*\.compatible\s*=\s*"[^"]+"\s*,\s*"([^"]+)"\s*\}'
)


@dataclass(frozen=True)
class SocDriverDescriptor:
    """Resolved driver-source information for a SoC family.

    Produced by :func:`resolve_driver_source`; consumed by
    :meth:`SourceProbe.from_tree` to replace the hardcoded path constants.
    """

    method: ResolutionMethod
    driver_file: str | None = None
    match_table_symbol: str | None = None
    soc_family_hint: str | None = None
    resolution_notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "driver_file": self.driver_file,
            "match_table_symbol": self.match_table_symbol,
            "soc_family_hint": self.soc_family_hint,
            "resolution_notes": list(self.resolution_notes),
        }


_SCAN_DIR = "sound/soc/qcom"


def resolve_driver_source(
    tree: str | None,
    soc_family_hint: str | None,
) -> SocDriverDescriptor:
    """Discover which driver ``.c`` file hosts the target SoC family.

    Scans ``sound/soc/qcom/*.c`` in the given kernel tree for files that:
      1. Contain a ``MODULE_DEVICE_TABLE(of, <symbol>)`` declaration.
      2. Have at least one match-table entry whose ``.data``-position string
         equals ``soc_family_hint`` (case-sensitive exact match).

    Returns:
      * ``DISCOVERED`` — exactly one file found; descriptor is fully populated.
      * ``RESOLUTION_FAILED`` — zero matches, multiple matches, or
        inputs invalid; ``resolution_notes`` explain why and set
        ``reviewer_required``.
      * ``STATIC_FALLBACK`` is NOT produced here (reserved for the case where
        the caller explicitly opts into a hardcoded path, e.g. missing hint).

    Parameters
    ----------
    tree:
        Path to the kernel source root. May be None / non-directory.
    soc_family_hint:
        The SoC family string to look for in match-table ``.data`` fields
        (e.g. ``"sa8775p"``). This is a curated input — the resolver does
        not fabricate it.
    """
    if not tree or not soc_family_hint:
        notes = []
        if not tree:
            notes.append(
                "RESOLUTION_FAILED: no kernel source tree provided; "
                "cannot discover driver file."
            )
        if not soc_family_hint:
            notes.append(
                "RESOLUTION_FAILED: no soc_family_hint provided; "
                "cannot identify target family."
            )
        return SocDriverDescriptor(
            method=ResolutionMethod.RESOLUTION_FAILED,
            soc_family_hint=soc_family_hint,
            resolution_notes=tuple(notes),
        )

    root = Path(tree)
    scan_path = root / _SCAN_DIR
    if not scan_path.is_dir():
        return SocDriverDescriptor(
            method=ResolutionMethod.RESOLUTION_FAILED,
            soc_family_hint=soc_family_hint,
            resolution_notes=(
                f"RESOLUTION_FAILED: {_SCAN_DIR}/ not found in tree "
                f"{tree!r}; cannot scan for machine drivers.",
            ),
        )

    candidates: list[tuple[str, str]] = []  # (rel_path, symbol)

    for c_file in sorted(scan_path.glob("*.c")):
        try:
            text = c_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        symbol_m = _MODULE_DEVICE_TABLE_RE.search(text)
        if not symbol_m:
            continue

        data_values = _MATCH_ENTRY_DATA_RE.findall(text)
        if soc_family_hint in data_values:
            rel = f"{_SCAN_DIR}/{c_file.name}"
            candidates.append((rel, symbol_m.group(1)))

    if len(candidates) == 1:
        rel_path, symbol = candidates[0]
        return SocDriverDescriptor(
            method=ResolutionMethod.DISCOVERED,
            driver_file=rel_path,
            match_table_symbol=symbol,
            soc_family_hint=soc_family_hint,
            resolution_notes=(
                f"DISCOVERED: soc_family_hint={soc_family_hint!r} matched "
                f"in {rel_path} (symbol={symbol}); single unambiguous result.",
            ),
        )

    if len(candidates) == 0:
        return SocDriverDescriptor(
            method=ResolutionMethod.RESOLUTION_FAILED,
            soc_family_hint=soc_family_hint,
            resolution_notes=(
                f"RESOLUTION_FAILED: soc_family_hint={soc_family_hint!r} "
                f"not found in any match-table .data field across "
                f"{_SCAN_DIR}/*.c; reviewer_required=true.",
            ),
        )

    # Multiple matches — ambiguous, cannot resolve.
    files = ", ".join(c[0] for c in candidates)
    return SocDriverDescriptor(
        method=ResolutionMethod.RESOLUTION_FAILED,
        soc_family_hint=soc_family_hint,
        resolution_notes=(
            f"RESOLUTION_FAILED: soc_family_hint={soc_family_hint!r} "
            f"matched in multiple files [{files}]; ambiguous resolution, "
            f"reviewer_required=true.",
        ),
    )
