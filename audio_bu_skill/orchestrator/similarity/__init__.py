"""Target similarity engine (v1.1 Phase 1).

Pure-Python, offline, deterministic nearest-target detection for onboarding.
See features.py (signal extraction) and engine.py (weighted scoring).
"""

from __future__ import annotations

from orchestrator.similarity.engine import (
    MIN_MARGIN,
    MIN_SCORE,
    WEIGHTS,
    Ranked,
    confidence,
    rank,
    score,
)
from orchestrator.similarity.features import TargetProfile, extract_profile

__all__ = [
    "TargetProfile",
    "extract_profile",
    "rank",
    "score",
    "confidence",
    "Ranked",
    "WEIGHTS",
    "MIN_SCORE",
    "MIN_MARGIN",
]
