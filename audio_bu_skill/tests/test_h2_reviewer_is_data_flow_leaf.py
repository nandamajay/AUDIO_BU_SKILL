"""H-2 firewall test #1 — the reviewer subsystem is a data-flow leaf.

Mirrors ``test_h1_projector_is_data_flow_leaf.py``: an AST scan over
every ``*.py`` under ``orchestrator/reviewer/`` asserting that no module
writes ``gc["cross_verification"]["rows"]`` (or any ``cross_verification``
subscript) by assignment or by a mutating method call. The reviewer is
downstream of authority and must never feed a value back into it
(invariant I-1).

This is the H-2 counterpart of the H-1 leaf guard and extends the WP-64
disclosure firewall to the new subsystem.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REVIEWER_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "reviewer"

_MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "pop", "clear", "__setitem__", "update"}
)


def _reviewer_py_files() -> list[Path]:
    return sorted(_REVIEWER_DIR.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_cross_verification_subscript(node: ast.AST) -> bool:
    """True if ``node`` is a subscript chain ending in ["cross_verification"]."""
    cur = node
    while isinstance(cur, ast.Subscript):
        sl = cur.slice
        key = sl.value if isinstance(sl, ast.Constant) else None
        if key == "cross_verification":
            return True
        cur = cur.value
    return False


def _find_assign_writers(tree: ast.Module) -> list[int]:
    """Line numbers of assignments whose target is a cross_verification subscript."""
    hits: list[int] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Subscript) and _is_cross_verification_subscript(t):
                hits.append(node.lineno)
    return hits


def _find_method_mutators(tree: ast.Module) -> list[int]:
    """Line numbers of mutating method calls on a cross_verification subscript."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _MUTATING_METHODS:
            continue
        if _is_cross_verification_subscript(func.value):
            hits.append(node.lineno)
    return hits


def test_subsystem_present() -> None:
    """Sanity: the reviewer package exists and has at least model + loader."""
    files = {p.name for p in _reviewer_py_files()}
    assert "__init__.py" in files
    assert "model.py" in files
    assert "loader.py" in files


@pytest.mark.parametrize("path", _reviewer_py_files(), ids=lambda p: p.name)
def test_no_cross_verification_assignments(path: Path) -> None:
    hits = _find_assign_writers(_parse(path))
    assert not hits, (
        f"{path.name} assigns into a cross_verification subscript at lines {hits}; "
        "the reviewer is a data-flow leaf and must never write authority (I-1)."
    )


@pytest.mark.parametrize("path", _reviewer_py_files(), ids=lambda p: p.name)
def test_no_cross_verification_mutators(path: Path) -> None:
    hits = _find_method_mutators(_parse(path))
    assert not hits, (
        f"{path.name} mutates a cross_verification subscript at lines {hits}; "
        "the reviewer must never write authority (I-1)."
    )


@pytest.mark.parametrize("path", _reviewer_py_files(), ids=lambda p: p.name)
def test_no_trusted_facts_writes(path: Path) -> None:
    """No assignment target named TrustedFacts / trusted_facts."""
    tree = _parse(path)
    hits: list[int] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            name = None
            if isinstance(t, ast.Name):
                name = t.id
            elif isinstance(t, ast.Attribute):
                name = t.attr
            if name in {"TrustedFacts", "trusted_facts"}:
                hits.append(node.lineno)
    assert not hits, (
        f"{path.name} assigns TrustedFacts at lines {hits}; forbidden (I-1)."
    )
