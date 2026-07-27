"""H-2 firewall — import discipline (invariant I-2).

The reviewer subsystem is a JSON-only downstream leaf. It must NOT import
any of the upstream authority-bearing subsystems:

  * ``orchestrator.hw_template.*`` — H-1; H-2 reads its JSON output, not
    its Python objects (this is why the closed enums are re-declared in
    ``reviewer/model.py``).
  * ``orchestrator.reasoning.*`` — cross-verification / authority.
  * ``orchestrator.generation.*`` — the is_open-gated generator pipeline.
  * ``orchestrator.codegen.*`` — the NullEngine codegen pipeline.

An AST scan of every ``*.py`` under ``orchestrator/reviewer/`` checks
both ``import X`` and ``from X import ...`` forms.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REVIEWER_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "reviewer"

_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "orchestrator.hw_template",
    "orchestrator.reasoning",
    "orchestrator.generation",
    "orchestrator.codegen",
)


def _reviewer_py_files() -> list[Path]:
    return sorted(_REVIEWER_DIR.rglob("*.py"))


def _imported_modules(tree: ast.Module) -> list[tuple[str, int]]:
    """Return (module_name, lineno) for every import in the tree."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import; module may be None for "from . import x"
            if node.level == 0 and node.module:
                out.append((node.module, node.lineno))
    return out


def _is_forbidden(module: str) -> bool:
    return any(
        module == p or module.startswith(p + ".") for p in _FORBIDDEN_PREFIXES
    )


@pytest.mark.parametrize("path", _reviewer_py_files(), ids=lambda p: p.name)
def test_no_forbidden_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = [
        (mod, ln) for mod, ln in _imported_modules(tree) if _is_forbidden(mod)
    ]
    assert not violations, (
        f"{path.name} imports forbidden upstream module(s) {violations}; "
        "the reviewer must read JSON, not import H-1/reasoning/generation/codegen "
        "(invariant I-2)."
    )
