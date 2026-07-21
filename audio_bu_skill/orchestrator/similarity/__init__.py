"""Target similarity engine (v1.1 Phase 1).

Pure-Python, offline, deterministic nearest-target detection for onboarding.
See features.py (signal extraction) and engine.py (weighted scoring).
"""

from __future__ import annotations

from orchestrator.similarity.engine import (
    ADSP_ROLE_SIGNALS,
    CANONICAL_ROLES,
    MIN_MARGIN,
    MIN_SCORE,
    ROLE_ALIASES,
    ROLE_SIGNALS,
    SNDCARD_ROLE_SIGNALS,
    WEIGHTS,
    Ranked,
    confidence,
    normalize_role,
    rank,
    rank_per_role,
    role_confidence,
    score,
)
from orchestrator.similarity.features import TargetProfile, extract_profile

__all__ = [
    "TargetProfile",
    "extract_profile",
    "rank",
    "rank_per_role",
    "score",
    "confidence",
    "role_confidence",
    "normalize_role",
    "Ranked",
    "WEIGHTS",
    "ADSP_ROLE_SIGNALS",
    "SNDCARD_ROLE_SIGNALS",
    "ROLE_SIGNALS",
    "CANONICAL_ROLES",
    "ROLE_ALIASES",
    "MIN_SCORE",
    "MIN_MARGIN",
]
