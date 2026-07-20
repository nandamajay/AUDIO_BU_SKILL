"""T-IA-12 + T-IA-13 — ipcat_acquire package isolation and manifest integrity.

T-IA-12: The acquisition package must not import from orchestrator.fact_registry
or orchestrator.state.  Importing ipcat_acquire must be safe in a cold
environment that does not have a registry on disk.

T-IA-13: Manifest integrity.  NORD_MANIFEST must contain exactly:
  - 8 mandatory verification-serving tools (T-IA-13a)
  - 2 optional provenance-only tools      (T-IA-13b)
  The goal is preventing accidental manifest drift — adding, removing, or
  reclassifying an entry is an intentional, auditable change, not a silent
  accident.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_isolation
"""

from __future__ import annotations

import sys


# ── T-IA-12 ──────────────────────────────────────────────────────────────────

def test_no_fact_registry_import() -> None:
    """ipcat_acquire must not pull in orchestrator.fact_registry."""
    import audio_bu_skill.orchestrator.ipcat_acquire  # noqa: F401 — import under test
    for mod in sys.modules:
        assert "fact_registry" not in mod, (
            f"T-IA-12 violated: fact_registry imported via {mod!r}"
        )
    print("PASS T-IA-12a: no fact_registry in sys.modules after importing ipcat_acquire")


def test_no_state_import() -> None:
    """ipcat_acquire must not pull in orchestrator.state."""
    import audio_bu_skill.orchestrator.ipcat_acquire  # noqa: F401
    for mod in sys.modules:
        assert not (mod.startswith("orchestrator.state") or mod.endswith(".state")), (
            f"T-IA-12 violated: state module imported via {mod!r}"
        )
    print("PASS T-IA-12b: no state module in sys.modules after importing ipcat_acquire")


def test_no_runner_import() -> None:
    """ipcat_acquire must not import any runner (inertness guarantee)."""
    import audio_bu_skill.orchestrator.ipcat_acquire  # noqa: F401
    for mod in sys.modules:
        assert "runners" not in mod or "ipcat" not in mod.split(".")[-1], (
            f"T-IA-12 violated: runner module imported via {mod!r}"
        )
    print("PASS T-IA-12c: no runner modules transitively imported by ipcat_acquire")


def test_no_main_import() -> None:
    """ipcat_acquire must not import orchestrator.main."""
    import audio_bu_skill.orchestrator.ipcat_acquire  # noqa: F401
    for mod in sys.modules:
        assert mod != "orchestrator.main", (
            "T-IA-12 violated: orchestrator.main is in sys.modules"
        )
    print("PASS T-IA-12d: orchestrator.main not imported by ipcat_acquire")


# ── T-IA-13 ──────────────────────────────────────────────────────────────────

_EXPECTED_MANDATORY_TOOLS = frozenset({
    "chips_list_chips",
    "cores_list_core_instances",
    "swi_search_swi",
    "gpio_get_gpio_map",
    "gpio_list_gpios_from_map",
    "gpio_list_tlmm_gpios",
    "chipio_get_qups",
    "buses_list_buses",
})

_EXPECTED_OPTIONAL_TOOLS = frozenset({
    "buses_list_bus_gateways",
    "buses_list_bidpidmids",
})


def test_mandatory_tool_count() -> None:
    """T-IA-13a: exactly 8 mandatory tools in NORD_MANIFEST."""
    from orchestrator.ipcat_acquire.manifest import MANDATORY_TOOLS
    assert len(MANDATORY_TOOLS) == 8, (
        f"T-IA-13a: expected 8 mandatory tools, got {len(MANDATORY_TOOLS)}: "
        f"{sorted(MANDATORY_TOOLS)}"
    )
    print(f"PASS T-IA-13a: MANDATORY_TOOLS count == 8 ({sorted(MANDATORY_TOOLS)})")


def test_mandatory_tool_identity() -> None:
    """T-IA-13b: mandatory set matches the closed Q2 verification-serving set."""
    from orchestrator.ipcat_acquire.manifest import MANDATORY_TOOLS
    assert MANDATORY_TOOLS == _EXPECTED_MANDATORY_TOOLS, (
        f"T-IA-13b mandatory set mismatch.\n"
        f"  expected : {sorted(_EXPECTED_MANDATORY_TOOLS)}\n"
        f"  actual   : {sorted(MANDATORY_TOOLS)}\n"
        f"  extra    : {sorted(MANDATORY_TOOLS - _EXPECTED_MANDATORY_TOOLS)}\n"
        f"  missing  : {sorted(_EXPECTED_MANDATORY_TOOLS - MANDATORY_TOOLS)}"
    )
    print("PASS T-IA-13b: MANDATORY_TOOLS identity matches closed Q2 set")


def test_optional_tool_count() -> None:
    """T-IA-13c: exactly 2 optional (provenance-only) tools."""
    from orchestrator.ipcat_acquire.manifest import OPTIONAL_TOOLS
    assert len(OPTIONAL_TOOLS) == 2, (
        f"T-IA-13c: expected 2 optional tools, got {len(OPTIONAL_TOOLS)}: "
        f"{sorted(OPTIONAL_TOOLS)}"
    )
    print(f"PASS T-IA-13c: OPTIONAL_TOOLS count == 2 ({sorted(OPTIONAL_TOOLS)})")


def test_optional_tool_identity() -> None:
    """T-IA-13d: optional set matches the closed Q2 provenance-only set."""
    from orchestrator.ipcat_acquire.manifest import OPTIONAL_TOOLS
    assert OPTIONAL_TOOLS == _EXPECTED_OPTIONAL_TOOLS, (
        f"T-IA-13d optional set mismatch.\n"
        f"  expected : {sorted(_EXPECTED_OPTIONAL_TOOLS)}\n"
        f"  actual   : {sorted(OPTIONAL_TOOLS)}\n"
        f"  extra    : {sorted(OPTIONAL_TOOLS - _EXPECTED_OPTIONAL_TOOLS)}\n"
        f"  missing  : {sorted(_EXPECTED_OPTIONAL_TOOLS - OPTIONAL_TOOLS)}"
    )
    print("PASS T-IA-13d: OPTIONAL_TOOLS identity matches closed Q2 provenance-only set")


def test_manifest_total_entries() -> None:
    """T-IA-13e: 12 total entries (10 logical tools, 3 swi entries)."""
    from orchestrator.ipcat_acquire.manifest import NORD_MANIFEST
    assert len(NORD_MANIFEST) == 12, (
        f"T-IA-13e: expected 12 manifest entries (3 swi + 9 others), "
        f"got {len(NORD_MANIFEST)}"
    )
    print("PASS T-IA-13e: NORD_MANIFEST has 12 entries (3 swi_search_swi + 9 others)")


def test_mandatory_optional_partition_is_disjoint() -> None:
    """T-IA-13f: MANDATORY_TOOLS and OPTIONAL_TOOLS are disjoint."""
    from orchestrator.ipcat_acquire.manifest import MANDATORY_TOOLS, OPTIONAL_TOOLS
    overlap = MANDATORY_TOOLS & OPTIONAL_TOOLS
    assert not overlap, (
        f"T-IA-13f: mandatory and optional sets overlap: {sorted(overlap)}"
    )
    print("PASS T-IA-13f: mandatory/optional partition is disjoint")


# ── runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    test_no_fact_registry_import()
    test_no_state_import()
    test_no_runner_import()
    test_no_main_import()
    test_mandatory_tool_count()
    test_mandatory_tool_identity()
    test_optional_tool_count()
    test_optional_tool_identity()
    test_manifest_total_entries()
    test_mandatory_optional_partition_is_disjoint()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
