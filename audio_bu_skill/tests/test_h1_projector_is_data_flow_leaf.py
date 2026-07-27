"""H-1 firewall regression test: projector is a data-flow leaf.

**Contract:** no module under ``orchestrator/hw_template/`` may write to
``gc["cross_verification"]["rows"]`` — that would break the WP-64
firewall guarantee that the crossverify subsystem is the sole authority
for row content. This test AST-scans every ``.py`` file under
``orchestrator/hw_template/`` and asserts:

  1. No assignment target matching ``gc["cross_verification"]["rows"]``,
     ``gc["cross_verification"]``, or ``cross_verification["rows"]``.
  2. No ``.append(`` / ``.extend(`` / ``.insert(`` / ``.pop(`` /
     ``.clear(`` / ``.__setitem__(`` call on such a target.

Kept parallel to ``tests/test_disclosure_firewall.py`` Test C, which
enforces the same rule on ``orchestrator/main.py`` (a single legal
writer at line ~1192). Here the answer is: **zero writers allowed**.

Rationale: the projector emits reviewer disclosures only. If it ever
mutates rows, a downstream reader could observe row content that no
crossverify rule ever attested, defeating the disclosure-only firewall.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# ── Locate the subsystem ────────────────────────────────────────────────────

_HW_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "orchestrator" / "hw_template"
)


def _iter_hw_template_modules() -> list[Path]:
    """Return every .py file under orchestrator/hw_template/."""
    assert _HW_TEMPLATE_DIR.is_dir(), (
        f"expected {_HW_TEMPLATE_DIR} to exist; H-1 subsystem missing"
    )
    return sorted(_HW_TEMPLATE_DIR.rglob("*.py"))


# ── AST helpers ─────────────────────────────────────────────────────────────


def _is_cross_verification_subscript(node: ast.expr) -> bool:
    """True iff ``node`` is a subscript into cross_verification.

    Matches (at any nesting depth):
      * ``gc["cross_verification"]``
      * ``gc["cross_verification"]["rows"]``
      * ``cross_verification["rows"]``
      * ``<anything>["cross_verification"]``
      * ``<anything>["cross_verification"]["rows"]``
    """
    if not isinstance(node, ast.Subscript):
        return False

    # ast.Subscript.slice may be a Constant (py3.9+) or an Index wrapping
    # a Constant (older). Accept both.
    def _key(sub: ast.Subscript) -> str | None:
        s = sub.slice
        if isinstance(s, ast.Constant) and isinstance(s.value, str):
            return s.value
        if isinstance(s, ast.Index):  # pragma: no cover — py<3.9
            v = s.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return v.value
        return None

    k = _key(node)
    if k == "cross_verification":
        return True
    if k == "rows":
        # gc[X]["rows"] — walk one step deeper to see if X is
        # "cross_verification" (either as a subscript key or as a
        # bare name).
        inner = node.value
        if isinstance(inner, ast.Subscript) and _key(inner) == "cross_verification":
            return True
        if isinstance(inner, ast.Name) and inner.id == "cross_verification":
            return True
    return False


def _find_assign_writers(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, snippet) for every Assign / AugAssign / AnnAssign
    whose target is a cross_verification subscript.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        else:
            continue
        for t in targets:
            if _is_cross_verification_subscript(t):
                hits.append((node.lineno, ast.unparse(t)))
    return hits


_MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "pop", "clear", "__setitem__", "update"}
)


def _find_method_mutators(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, snippet) for every ``.append``-style call on a
    cross_verification subscript.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _MUTATING_METHODS:
            continue
        if _is_cross_verification_subscript(node.func.value):
            hits.append((node.lineno, ast.unparse(node.func)))
    return hits


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("module_path", _iter_hw_template_modules(), ids=str)
def test_no_cross_verification_assignments(module_path: Path) -> None:
    """No module under orchestrator/hw_template/ assigns to cross_verification."""
    src = module_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(module_path))
    hits = _find_assign_writers(tree)
    assert hits == [], (
        f"{module_path.name} contains {len(hits)} illegal assignment(s) to "
        f"cross_verification — the H-1 projector must be a data-flow leaf. "
        f"Offenders: {hits}"
    )


@pytest.mark.parametrize("module_path", _iter_hw_template_modules(), ids=str)
def test_no_cross_verification_mutators(module_path: Path) -> None:
    """No module under orchestrator/hw_template/ mutates cross_verification in-place."""
    src = module_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(module_path))
    hits = _find_method_mutators(tree)
    assert hits == [], (
        f"{module_path.name} contains {len(hits)} illegal mutator call(s) on "
        f"cross_verification (e.g. .append, .extend). Offenders: {hits}"
    )


def test_subsystem_present() -> None:
    """Sanity: there is at least one module under orchestrator/hw_template/."""
    modules = _iter_hw_template_modules()
    names = {m.name for m in modules}
    assert "model.py" in names, f"model.py missing from {names}"
    assert "projector.py" in names, f"projector.py missing from {names}"
    assert "__init__.py" in names, f"__init__.py missing from {names}"


def test_reasoning_import_discipline() -> None:
    """Only ``orchestrator.reasoning.crossverify_model`` may be imported
    from ``orchestrator.reasoning.*`` inside the hw_template subsystem.

    Mirrors ``tests/test_generator_import_guards.py`` but for the
    projector's allow-list.
    """
    allowed = frozenset({"orchestrator.reasoning.crossverify_model"})
    offenders: list[tuple[str, int, str]] = []
    for module_path in _iter_hw_template_modules():
        src = module_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("orchestrator.reasoning") and mod not in allowed:
                    offenders.append((module_path.name, node.lineno, f"from {mod}"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    if mod.startswith("orchestrator.reasoning") and mod not in allowed:
                        offenders.append(
                            (module_path.name, node.lineno, f"import {mod}")
                        )
    assert offenders == [], (
        "hw_template subsystem imported a disallowed reasoning module — "
        f"only {sorted(allowed)} is on the allow-list. Offenders: {offenders}"
    )
