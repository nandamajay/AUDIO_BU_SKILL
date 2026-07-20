"""Phase-3A WP-E — import-isolation test — T-E34.

Asserts the fact_registry package is architecturally advisory-only: none of its
modules import from the runtime lanes (orchestrator.runners), the entrypoint
(orchestrator.main), or targets/. This enforces the WP-E design rule that the
registry never depends on — and thus can never perturb — any runtime flow.

Runs entirely in-process; does not touch case.py, case.generated.py, WP7,
onboarding, or any runtime flow. Advisory-only per PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=.:audio_bu_skill python3 -m tests.test_fact_registry_import_isolation
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG_DIR = (
    Path(__file__).resolve().parent.parent
    / "orchestrator"
    / "fact_registry"
)

# Any imported module whose dotted path contains one of these segments is a
# forbidden runtime dependency for the advisory-only registry.
_FORBIDDEN = (
    "orchestrator.runners",
    "orchestrator.main",
    ".runners",
    ".main",
    "targets",
)


def _imported_names(tree: ast.AST) -> list[str]:
    """Collect every dotted module path referenced by import statements."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports carry level>0; record the module (may be None
            # for `from . import x`, in which case the aliases carry the name).
            mod = node.module or ""
            prefix = "." * node.level
            names.append(prefix + mod)
    return names


def _is_forbidden(dotted: str) -> bool:
    return any(seg in dotted for seg in _FORBIDDEN)


# ── T-E34 — no fact_registry module imports from runners/main/targets ──────

def test_te34_no_runtime_imports() -> None:
    py_files = sorted(PKG_DIR.glob("*.py"))
    assert py_files, f"no fact_registry modules found under {PKG_DIR}"

    violations: list[str] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for dotted in _imported_names(tree):
            if _is_forbidden(dotted):
                violations.append(f"{path.name}: imports {dotted!r}")

    assert not violations, (
        "fact_registry must not import from runtime lanes; found:\n  "
        + "\n  ".join(violations)
    )


def main() -> None:
    # T-E34  advisory-only import isolation
    test_te34_no_runtime_imports()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
