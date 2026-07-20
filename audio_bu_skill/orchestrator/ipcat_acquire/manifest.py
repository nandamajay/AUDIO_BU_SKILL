"""WP-IPCAT-A C1 — declarative acquisition manifest (Q2 closure).

This module is the **architectural definition of acquisition completeness** for
a Nord IQ-10 IPCAT cache. It is pure data: importing it opens no socket, reads
no file, and performs no I/O. It is the realisation of the closed Q2 — the query
set is itself reproducible evidence, so a reviewer can see *exactly* which
read-only tools were called and with which parameters.

A "complete" Nord cache is defined by two disjoint tool sets (design §0 / Q2):

**Mandatory (8) — verification-serving.** These are the tools whose responses
the coverage/authority check actually consumes; a cache missing any of them is
incomplete and acquisition must not publish it:

    1. chips_list_chips              {}
    2. cores_list_core_instances     {chip}
    3. swi_search_swi                {chip, term=SOUNDWIRE_MASTER}   ┐ one entry
    4. swi_search_swi                {chip, term=SWR_MSTR}           ├ per union
    5. swi_search_swi                {chip, term=SWR}                ┘ term (W4)
    6. gpio_get_gpio_map             {chip}
    7. gpio_list_gpios_from_map      {gpio_map_id}
    8. gpio_list_tlmm_gpios          {chip}
    9. chipio_get_qups               {chip}
   10. buses_list_buses              {chip}

(The three ``swi_search_swi`` entries collapse to a *single* logical query in
provenance — the union-term W4 count — but are three distinct manifest entries
because each is a separate ``tools/call``.)

**Optional (2) — provenance-only.** Acquired for audit context when reachable;
their absence never blocks publication:

    - buses_list_bus_gateways        {chip}
    - buses_list_bidpidmids          {chip}

Permanently **out of scope** (design / Q2): T4b codec bindings and SCMI power
domains. They are intentionally absent from this manifest.

The manifest is frozen (tuples of frozen dataclasses) so it cannot be mutated at
runtime, and :data:`SWI_UNION_TERMS` records the W4 union set that
``normalize`` counts over. **T-IA-13** asserts this manifest contains exactly
the 10 tools above in the correct mandatory/optional partition, preventing
accidental drift.

Argument placeholders (``"{chip}"``, ``"{gpio_map_id}"``) are literal template
markers, not resolved values — the client binds them to the resolved chip alias
and the runtime ``gpio_map_id`` at call time. Keeping them as markers here means
the manifest stays a pure, target-agnostic declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# Argument placeholder markers bound by the client at call time.
CHIP = "{chip}"
GPIO_MAP_ID = "{gpio_map_id}"

# W4 discipline: swi_search_swi is capped + relevance-ranked and its
# ``total_hits`` is unreliable, so a count is only trusted when the union of
# these terms yields a set-stable, below-cap result (design §3.1 count_method).
SWI_UNION_TERMS: tuple[str, ...] = ("SOUNDWIRE_MASTER", "SWR_MSTR", "SWR")


@dataclass(frozen=True)
class ManifestEntry:
    """One read-only ``tools/call`` in the acquisition plan.

    ``tool``       corrected real MCP tool name (never the probe's W1/D1 typo).
    ``args``       argument template; placeholder markers bound at call time.
    ``query_id``   stable id used to key provenance ``queries[]``.
    ``result_file``normalized output filename under ``evidence/ipcat/``.
    ``mandatory``  True → verification-serving; missing ⇒ incomplete cache.
    """

    tool: str
    args: Mapping[str, str]
    query_id: str
    result_file: str
    mandatory: bool = True

    def __post_init__(self) -> None:
        if not self.tool:
            raise ValueError("ManifestEntry.tool must be non-empty")
        if not self.query_id:
            raise ValueError("ManifestEntry.query_id must be non-empty")
        if not self.result_file:
            raise ValueError("ManifestEntry.result_file must be non-empty")


# ── The Nord manifest (Q2) — order is stable and part of the contract ─────────

NORD_MANIFEST: tuple[ManifestEntry, ...] = (
    ManifestEntry(
        tool="chips_list_chips",
        args={},
        query_id="q1",
        result_file="chips_list_chips.json",
    ),
    ManifestEntry(
        tool="cores_list_core_instances",
        args={"chip": CHIP},
        query_id="q2",
        result_file="cores_list_core_instances.json",
    ),
    ManifestEntry(
        tool="swi_search_swi",
        args={"chip": CHIP, "q": "SOUNDWIRE_MASTER"},
        query_id="q3a",
        result_file="swi_search_swi__soundwire_master.json",
    ),
    ManifestEntry(
        tool="swi_search_swi",
        args={"chip": CHIP, "q": "SWR_MSTR"},
        query_id="q3b",
        result_file="swi_search_swi__swr_mstr.json",
    ),
    ManifestEntry(
        tool="swi_search_swi",
        args={"chip": CHIP, "q": "SWR"},
        query_id="q3c",
        result_file="swi_search_swi__swr.json",
    ),
    ManifestEntry(
        tool="gpio_get_gpio_map",
        args={"chip": CHIP},
        query_id="q4",
        result_file="gpio_get_gpio_map.json",
    ),
    ManifestEntry(
        tool="gpio_list_gpios_from_map",
        args={"gpio_map_id": GPIO_MAP_ID},
        query_id="q5",
        result_file="gpio_list_gpios_from_map.json",
    ),
    ManifestEntry(
        tool="gpio_list_tlmm_gpios",
        args={"chip": CHIP},
        query_id="q6",
        result_file="gpio_list_tlmm_gpios.json",
    ),
    ManifestEntry(
        tool="chipio_get_qups",
        args={"chip": CHIP},
        query_id="q7",
        result_file="chipio_get_qups.json",
    ),
    ManifestEntry(
        tool="buses_list_buses",
        args={"chip": CHIP},
        query_id="q8",
        result_file="buses_list_buses.json",
    ),
    # ── optional / provenance-only ──
    ManifestEntry(
        tool="buses_list_bus_gateways",
        args={"chip": CHIP},
        query_id="q9",
        result_file="buses_list_bus_gateways.json",
        mandatory=False,
    ),
    ManifestEntry(
        tool="buses_list_bidpidmids",
        args={"chip": CHIP},
        query_id="q10",
        result_file="buses_list_bidpidmids.json",
        mandatory=False,
    ),
)


# The 8 mandatory verification-serving tools, as a frozenset for exact-match
# guardrails (T-IA-13). ``swi_search_swi`` counts once here — it is one tool
# though three manifest entries.
MANDATORY_TOOLS: frozenset[str] = frozenset(
    e.tool for e in NORD_MANIFEST if e.mandatory
)

# The 2 optional provenance-only tools.
OPTIONAL_TOOLS: frozenset[str] = frozenset(
    e.tool for e in NORD_MANIFEST if not e.mandatory
)


def mandatory_entries() -> tuple[ManifestEntry, ...]:
    """Return the mandatory (verification-serving) manifest entries, in order."""
    return tuple(e for e in NORD_MANIFEST if e.mandatory)


def optional_entries() -> tuple[ManifestEntry, ...]:
    """Return the optional (provenance-only) manifest entries, in order."""
    return tuple(e for e in NORD_MANIFEST if not e.mandatory)


__all__ = [
    "ManifestEntry",
    "NORD_MANIFEST",
    "MANDATORY_TOOLS",
    "OPTIONAL_TOOLS",
    "SWI_UNION_TERMS",
    "CHIP",
    "GPIO_MAP_ID",
    "mandatory_entries",
    "optional_entries",
]
