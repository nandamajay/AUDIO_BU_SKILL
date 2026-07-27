"""Move-2 Slice A — read-only kernel-source probe (machine_driver lane).

A ``SourceProbe`` grounds two machine_driver disclosures against the actual
kernel tree instead of a hardcoded assertion:

  (a) driver-match — is the board sound-card ``compatible`` string present in
      the ``snd_sc8280xp_dt_match[]`` table in ``sound/soc/qcom/sc8280xp.c``?
  (b) port-id ordinals — what does
      ``include/dt-bindings/sound/qcom,q6dsp-lpass-ports.h`` actually define?
      Per the Option-(iii) ruling the probe reports BOTH ceilings:

        * ``global_name_ceiling`` — the highest ordinal *name* that appears
          anywhere (MI2S-inclusive); confirms the SENARY claim.
        * ``tdm_family_ceiling`` — the highest ``*_TDM_*`` ordinal, the
          bind-relevant ceiling for ``*_TDM_RX_0`` / ``*_TDM_TX_0``.
        * ``octonary_tdm_defined`` — whether ``OCTONARY_TDM_*`` exists.
        * ``missing_rungs`` — the ``*_TDM`` rungs between the family ceiling
          and OCTONARY that are undefined.

Hard constraints (Move-2 Slice A):

  * READ-ONLY. Opens *at most* the two literal files below. No glob, no walk,
    no writes, no network. Never raises on a missing tree / file — a missing
    input degrades honestly to ``FILE_NOT_FOUND`` (→ UNVERIFIED downstream),
    never a fabricated FOUND / ABSENT.
  * DISCLOSURE-ONLY. This object flows into ``contributes_rows`` notes only.
    It NEVER reaches ``cross_verification``, ``TrustedFacts``, or any gate;
    ``is_open`` does not consult it. It cannot promote a candidate or open a
    closed gate.
  * The probe result changes NOTE TEXT ONLY. The emitted DTSI bytes are
    byte-identical whether the probe is present-FOUND, present-ABSENT, or an
    absent tree.

The frozen dataclass is deterministic: same tree contents → same probe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ── The two literal files this probe is permitted to open. ──────────────────
_DRIVER_MATCH_REL = "sound/soc/qcom/sc8280xp.c"
_PORTS_HDR_REL = "include/dt-bindings/sound/qcom,q6dsp-lpass-ports.h"

#: The match-table symbol whose membership decides claim (a).
_MATCH_TABLE_SYMBOL = "snd_sc8280xp_dt_match"

#: Every ``.compatible = "..."`` string literal (the match-table entries).
_COMPATIBLE_RE = re.compile(r'\.compatible\s*=\s*"([^"]+)"')

#: LPASS port ordinal prefixes, low → high. Rank is the list index.
_ORDINALS: tuple[str, ...] = (
    "PRIMARY",
    "SECONDARY",
    "TERTIARY",
    "QUATERNARY",
    "QUINARY",
    "SENARY",
    "SEPTENARY",
    "OCTONARY",
)

_DEFINE_RE = re.compile(r"^\s*#define\s+([A-Z0-9_]+)\s+(\d+)\b")


class ClaimStatus(str, Enum):
    """Ternary observation state for a single grounded claim.

    ``FOUND`` / ``ABSENT`` are *observations* from real file contents.
    ``FILE_NOT_FOUND`` means the input could not be read — it is NOT an
    observation and downstream must render it UNVERIFIED, never a fabricated
    FOUND / ABSENT.
    """

    FOUND = "FOUND"
    ABSENT = "ABSENT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"


@dataclass(frozen=True)
class SourceProbe:
    """Immutable, disclosure-only observation of the kernel source tree.

    Every field is either an observation (``ClaimStatus`` / value / line) or
    ``None`` when the underlying file was unreadable. Construct via
    :meth:`from_tree`; never mutate.
    """

    tree: str | None

    # ── claim (a): driver-match table ───────────────────────────────────────
    #: File-read status only: FOUND means the driver .c was read; FILE_NOT_FOUND
    #: means it was unreadable. This is NOT a membership decision — membership is
    #: a per-compatible query (:meth:`driver_match`) so the probe stays board-
    #: agnostic and the runner never needs the board's compatible string.
    driver_status: ClaimStatus = ClaimStatus.FILE_NOT_FOUND
    match_table_symbol: str = _MATCH_TABLE_SYMBOL
    driver_match_file: str = _DRIVER_MATCH_REL
    match_table_line: int | None = None
    #: Every ``.compatible = "..."`` literal observed in the driver .c, in file
    #: order. Empty when the file was unreadable. The raw observation from which
    #: :meth:`driver_match` derives FOUND / ABSENT for a given board string.
    match_table_compatibles: tuple[str, ...] = ()

    # ── claim (b): port-id ordinals ─────────────────────────────────────────
    ports_file: str = _PORTS_HDR_REL
    ports_status: ClaimStatus = ClaimStatus.FILE_NOT_FOUND
    global_name_ceiling: str | None = None
    global_name_ceiling_line: int | None = None
    tdm_family_ceiling: str | None = None
    tdm_family_ceiling_line: int | None = None
    octonary_tdm_defined: ClaimStatus = ClaimStatus.FILE_NOT_FOUND
    missing_rungs: tuple[str, ...] = ()

    #: (name, value, lineno) for every ``#define <NAME> <int>`` in the ports
    #: header — lets a caller ground a specific placeholder macro (e.g.
    #: ``QUATERNARY_TDM_RX_0`` = 72). Empty when the header was unreadable.
    port_defs: tuple[tuple[str, int, int], ...] = field(default=())

    # ── construction ────────────────────────────────────────────────────────
    @classmethod
    def from_tree(cls, tree: str | None) -> "SourceProbe":
        """Build a probe by reading at most the two literal files under ``tree``.

        ``tree`` may be ``None`` or a path that does not exist / is not a
        directory — every such case yields a fully-``FILE_NOT_FOUND`` probe
        with no exception raised. The probe is board-agnostic: it records the
        raw match-table compatibles it observed, and the caller asks about a
        specific board string via :meth:`driver_match`.
        """
        if not tree:
            return cls(tree=tree)

        root = Path(tree)
        if not root.is_dir():
            return cls(tree=tree)

        driver = cls._probe_driver_match(root)
        ports = cls._probe_ports(root)
        return cls(tree=tree, **driver, **ports)

    # ── claim (a) ────────────────────────────────────────────────────────────
    @staticmethod
    def _probe_driver_match(root: Path) -> dict:
        path = root / _DRIVER_MATCH_REL
        text = _safe_read(path)
        if text is None:
            return {
                "driver_status": ClaimStatus.FILE_NOT_FOUND,
                "match_table_line": None,
                "match_table_compatibles": (),
            }

        match_table_line: int | None = None
        compatibles: list[str] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if match_table_line is None and _MATCH_TABLE_SYMBOL in line:
                match_table_line = lineno
            m = _COMPATIBLE_RE.search(line)
            if m:
                compatibles.append(m.group(1))
        # FOUND here means only that the driver .c was read; per-board membership
        # is decided later by :meth:`driver_match`, keeping the probe board-blind.
        return {
            "driver_status": ClaimStatus.FOUND,
            "match_table_line": match_table_line,
            "match_table_compatibles": tuple(compatibles),
        }

    # ── claim (b) ────────────────────────────────────────────────────────────
    @staticmethod
    def _probe_ports(root: Path) -> dict:
        path = root / _PORTS_HDR_REL
        text = _safe_read(path)
        if text is None:
            return {
                "ports_status": ClaimStatus.FILE_NOT_FOUND,
                "global_name_ceiling": None,
                "global_name_ceiling_line": None,
                "tdm_family_ceiling": None,
                "tdm_family_ceiling_line": None,
                "octonary_tdm_defined": ClaimStatus.FILE_NOT_FOUND,
                "missing_rungs": (),
                "port_defs": (),
            }

        defs: list[tuple[str, int, int]] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _DEFINE_RE.match(line)
            if m:
                defs.append((m.group(1), int(m.group(2)), lineno))

        # global name ceiling: highest-rank ordinal prefix appearing anywhere.
        global_rank = -1
        global_line: int | None = None
        # tdm family ceiling: highest-rank ordinal prefix with a *_TDM_* macro.
        tdm_rank = -1
        tdm_line: int | None = None
        tdm_prefixes: set[str] = set()
        for name, _value, lineno in defs:
            prefix = name.split("_", 1)[0]
            if prefix in _ORDINALS:
                rank = _ORDINALS.index(prefix)
                if rank > global_rank:
                    global_rank, global_line = rank, lineno
                if "_TDM_" in name or name.endswith("_TDM"):
                    tdm_prefixes.add(prefix)
                    if rank > tdm_rank:
                        tdm_rank, tdm_line = rank, lineno

        octonary_defined = any(
            n.startswith("OCTONARY_TDM_") or n == "OCTONARY_TDM" for n, _, _ in defs
        )
        octonary_status = (
            ClaimStatus.FOUND if octonary_defined else ClaimStatus.ABSENT
        )

        # missing rungs: ordinals strictly above the TDM family ceiling and
        # strictly below OCTONARY that have no *_TDM_* macro, named "<ORD>_TDM".
        # OCTONARY itself is NOT a rung here — it is reported separately via
        # ``octonary_tdm_defined`` (Option-(iii) ruling: the two must not be
        # collapsed). For the real Nord tree this yields
        # [SENARY_TDM, SEPTENARY_TDM].
        missing: list[str] = []
        if tdm_rank >= 0:
            octonary_rank = _ORDINALS.index("OCTONARY")
            for rank in range(tdm_rank + 1, octonary_rank):
                prefix = _ORDINALS[rank]
                if prefix not in tdm_prefixes:
                    missing.append(f"{prefix}_TDM")

        return {
            "ports_status": ClaimStatus.FOUND,
            "global_name_ceiling": _ORDINALS[global_rank] if global_rank >= 0 else None,
            "global_name_ceiling_line": global_line,
            "tdm_family_ceiling": (
                f"{_ORDINALS[tdm_rank]}_TDM" if tdm_rank >= 0 else None
            ),
            "tdm_family_ceiling_line": tdm_line,
            "octonary_tdm_defined": octonary_status,
            "missing_rungs": tuple(missing),
            "port_defs": tuple(defs),
        }

    # ── queries (disclosure-only) ────────────────────────────────────────────
    def driver_match(self, compatible: str) -> tuple[ClaimStatus, int | None]:
        """Ground a board compatible against the match table: (status, line).

        ``FILE_NOT_FOUND`` if the driver .c was unreadable; ``FOUND`` if
        ``compatible`` is among the observed ``.compatible = "..."`` literals;
        ``ABSENT`` if the driver was read but does not list it (the real Nord
        observation). ``line`` is the match-table symbol line when known. Keeps
        membership a caller-side query so the probe itself stays board-blind.
        """
        if self.driver_status is ClaimStatus.FILE_NOT_FOUND:
            return (ClaimStatus.FILE_NOT_FOUND, None)
        if compatible in self.match_table_compatibles:
            return (ClaimStatus.FOUND, self.match_table_line)
        return (ClaimStatus.ABSENT, self.match_table_line)

    def port_macro(self, name: str) -> tuple[ClaimStatus, int | None, int | None]:
        """Ground a specific port macro: (status, value, lineno).

        ``FILE_NOT_FOUND`` if the ports header was unreadable; ``FOUND`` with
        the observed value/line if defined; ``ABSENT`` if the header was read
        but the macro is not defined.
        """
        if self.ports_status is ClaimStatus.FILE_NOT_FOUND:
            return (ClaimStatus.FILE_NOT_FOUND, None, None)
        for n, value, lineno in self.port_defs:
            if n == name:
                return (ClaimStatus.FOUND, value, lineno)
        return (ClaimStatus.ABSENT, None, None)


def _safe_read(path: Path) -> str | None:
    """Read a single file's text, returning ``None`` on any I/O problem.

    Never raises: a missing / unreadable file is a first-class UNVERIFIED
    input, not an error condition.
    """
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
