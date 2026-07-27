"""WP-64 — per-lane generator import guards.

For each generator lane, assert that the module source:

  * MAY import ``orchestrator.reasoning.crossverify_model`` (for the
    ``VerificationRow`` type — needed to build ``contributes_rows``).
  * MUST NOT import ``orchestrator.reasoning.crossverify`` (the verifier
    module).
  * MUST NOT import ``orchestrator.reasoning.cardinality`` (the Track C
    verifier module).
  * MUST NOT import any other ``orchestrator.reasoning.*`` submodule.

Generators are downstream authority consumers, not producers. They must
never re-enter the verifier from the generation lane — that would create
a channel by which a generator could (a) re-verify its own disclosures
into authority, or (b) mutate the crossverify state after
``project_facts`` has already produced the projection.

The generator lanes under guard (all four Phase-2B generators):

  * machine_driver.py
  * audioreach_topology.py
  * dt_scaffolding.py
  * codec_stub.py

Runs stdlib-only, AST-based, zero filesystem I/O beyond source reads.

Run: ``PYTHONPATH=audio_bu_skill python3 -m pytest
audio_bu_skill/tests/test_generator_import_guards.py -v``
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from orchestrator.generation import (
    audioreach_topology as audioreach_module,
    codec_stub as codec_module,
    dt_scaffolding as dt_module,
    machine_driver as machine_module,
)


# ── The invariant table ─────────────────────────────────────────────────────

# Allow-list is a single module: crossverify_model (the row type). Any other
# `orchestrator.reasoning.*` import is a firewall breach.
_ALLOWED_REASONING_IMPORTS: frozenset[str] = frozenset(
    {"orchestrator.reasoning.crossverify_model"}
)

_GENERATOR_MODULES = {
    "machine_driver": machine_module,
    "audioreach_topology": audioreach_module,
    "dt_scaffolding": dt_module,
    "codec_stub": codec_module,
}


# ── Shared collector ────────────────────────────────────────────────────────


def _collect_reasoning_imports(src: str) -> list[tuple[int, str]]:
    """Return every ``orchestrator.reasoning.*`` import in ``src``.

    Each hit is ``(lineno, dotted_module_name)``. Aliased imports are
    normalized to the underlying module name (``from x.y import z as _z``
    → hit is on ``x.y``, since that is the module actually loaded).
    """
    tree = ast.parse(src)
    hits: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # `from orchestrator.reasoning.X import ...`
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "orchestrator.reasoning" or module.startswith(
                "orchestrator.reasoning."
            ):
                hits.append((node.lineno, module))
        # `import orchestrator.reasoning.X [as _y]`
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "orchestrator.reasoning" or name.startswith(
                    "orchestrator.reasoning."
                ):
                    hits.append((node.lineno, name))
    return hits


def _assert_reasoning_import_shape(lane_name: str, module_obj) -> None:
    """Every reasoning import in ``module_obj`` must be in the allow-list."""
    src_path = Path(inspect.getsourcefile(module_obj))  # type: ignore[arg-type]
    src = src_path.read_text(encoding="utf-8")
    imports = _collect_reasoning_imports(src)

    violations = [
        (lineno, name)
        for (lineno, name) in imports
        if name not in _ALLOWED_REASONING_IMPORTS
    ]
    assert not violations, (
        f"{lane_name} generator imports a non-allow-listed reasoning module. "
        f"Allow-list: {sorted(_ALLOWED_REASONING_IMPORTS)!r}. "
        f"Violations (line, module): {violations!r}"
    )
    # A generator that emits contributes_rows MUST have imported
    # VerificationRow. This second assertion turns a silent no-op into a
    # signal: if the import disappears (renamed, moved, etc.) we catch it.
    has_verifrow_import = any(
        name == "orchestrator.reasoning.crossverify_model"
        for (_, name) in imports
    )
    assert has_verifrow_import, (
        f"{lane_name} generator does not import "
        "orchestrator.reasoning.crossverify_model — regression: how is "
        "VerificationRow being obtained for contributes_rows?"
    )


# ── Per-lane tests ──────────────────────────────────────────────────────────


def test_machine_driver_reasoning_imports_are_row_type_only() -> None:
    _assert_reasoning_import_shape("machine_driver", machine_module)


def test_audioreach_topology_reasoning_imports_are_row_type_only() -> None:
    _assert_reasoning_import_shape("audioreach_topology", audioreach_module)


def test_dt_scaffolding_reasoning_imports_are_row_type_only() -> None:
    _assert_reasoning_import_shape("dt_scaffolding", dt_module)


def test_codec_stub_reasoning_imports_are_row_type_only() -> None:
    _assert_reasoning_import_shape("codec_stub", codec_module)


# ── Meta-test: enumerate all generators, ensure this test covers each ──────


@pytest.mark.parametrize(
    "lane_name",
    sorted(_GENERATOR_MODULES.keys()),
)
def test_all_generators_covered(lane_name: str) -> None:
    """Redundant with the four per-lane tests above, but exercises the
    parametrized path so future lanes added to ``_GENERATOR_MODULES``
    inherit the guard without adding a hand-written test."""
    _assert_reasoning_import_shape(lane_name, _GENERATOR_MODULES[lane_name])


if __name__ == "__main__":
    # stdlib-only entry point — mirrors WP5/WP6 test style.
    test_machine_driver_reasoning_imports_are_row_type_only()
    test_audioreach_topology_reasoning_imports_are_row_type_only()
    test_dt_scaffolding_reasoning_imports_are_row_type_only()
    test_codec_stub_reasoning_imports_are_row_type_only()
    for lane in sorted(_GENERATOR_MODULES.keys()):
        _assert_reasoning_import_shape(lane, _GENERATOR_MODULES[lane])
    print("PASS: all 4 generator lanes import only crossverify_model from reasoning")
