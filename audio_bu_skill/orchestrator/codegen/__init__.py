"""Code-generation package for the Phase 2 foundation (v1.1).

Pure-Python, deterministic scaffolding for a generation lane that is **inert by
design**: the default ``NullEngine`` proposes nothing and the real engines raise
``NotImplementedError``. See models.py (Change/ChangeSet/PatchSeries), engine.py
(the pluggable ``CodegenEngine`` seam), and artifacts.py (the
``artifacts/<run_id>/generated/`` layout).

Nothing here is wired into the shipped CLI — swapping ``NullEngine`` for a real
engine is the only remaining work to turn this scaffolding into generation.
"""

from __future__ import annotations

from orchestrator.codegen.artifacts import (
    GeneratedArtifactError,
    generated_dir,
    write_patch_series,
)
from orchestrator.codegen.codec_preview_engine import CodecPreviewEngine
from orchestrator.codegen.engine import (
    ClaudeCodeEngine,
    CodegenEngine,
    NullEngine,
    QGenieEngine,
    resolve_engine,
)
from orchestrator.codegen.models import (
    CHANGE_TYPES,
    Change,
    ChangeSet,
    PatchSeries,
    generation_fingerprints,
)

__all__ = [
    "Change",
    "ChangeSet",
    "PatchSeries",
    "CHANGE_TYPES",
    "generation_fingerprints",
    "CodegenEngine",
    "NullEngine",
    "ClaudeCodeEngine",
    "QGenieEngine",
    "CodecPreviewEngine",
    "resolve_engine",
    "generated_dir",
    "write_patch_series",
    "GeneratedArtifactError",
]
