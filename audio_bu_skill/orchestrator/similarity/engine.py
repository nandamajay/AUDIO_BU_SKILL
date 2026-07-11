"""Weighted similarity scoring over TargetProfiles (v1.1 Phase 1).

Pure functions, deterministic, no dependencies. ``score`` computes a per-signal
similarity in [0,1] between two profiles; ``rank`` combines them into a weighted
overall score for each DB candidate and sorts, then computes a confidence that
reflects both the top score and its margin over the runner-up. Below either
threshold the top candidate is flagged ``low_confidence`` so the caller refuses
to auto-finalize the nearest-target choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.similarity.features import TargetProfile

# Signal weights — recorded in the output for reproducibility. Sum to 1.0.
WEIGHTS: dict[str, float] = {
    "codecs": 0.30,
    "power_domain_providers": 0.20,
    "dt_compatibles": 0.20,
    "audioreach": 0.15,
    "soundwire": 0.10,
    "soc": 0.05,
}

# Gating: a nearest-target is only auto-usable when it clears BOTH.
MIN_SCORE = 0.75
MIN_MARGIN = 0.10
MARGIN_FLOOR = 0.10   # keeps a lone top candidate's confidence from collapsing to ~0


@dataclass
class Ranked:
    target_name: str
    overall: float
    per_signal: dict[str, float]
    cites: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "overall": round(self.overall, 4),
            "per_signal": {k: round(v, 4) for k, v in self.per_signal.items()},
            "cites": self.cites,
        }


def _jaccard(a: set[str], b: set[str]) -> float | None:
    """Jaccard overlap; None when both sides are empty (undetectable, not 0)."""
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


def _bool_sim(a: bool | None, b: bool | None) -> float | None:
    if a is None or b is None:
        return None
    return 1.0 if a == b else 0.0


def _soundwire_sim(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    pa, pb = a.get("present"), b.get("present")
    base = _bool_sim(pa, pb)
    if base is None:
        return None
    if base == 0.0:
        return 0.0
    # both present-flags equal; if both present, factor in master-count closeness.
    if pa and pb:
        ca, cb = a.get("master_count", 0), b.get("master_count", 0)
        if ca == 0 and cb == 0:
            return 1.0
        return 1.0 - abs(ca - cb) / max(ca, cb, 1)
    return 1.0


def _soc_sim(a: str, b: str) -> float | None:
    if not a and not b:
        return None
    return 1.0 if a and b and a.upper() == b.upper() else 0.0


def score(new: TargetProfile, other: TargetProfile) -> dict[str, float | None]:
    """Per-signal similarity in [0,1]; None for a signal undetectable on both."""
    return {
        "codecs": _jaccard(new.codecs, other.codecs),
        "power_domain_providers": _jaccard(new.power_domain_providers, other.power_domain_providers),
        "dt_compatibles": _jaccard(new.dt_compatibles, other.dt_compatibles),
        "audioreach": _bool_sim(new.audioreach, other.audioreach),
        "soundwire": _soundwire_sim(new.soundwire, other.soundwire),
        "soc": _soc_sim(new.soc, other.soc),
    }


def _overall(per_signal: dict[str, float | None]) -> float:
    """Weighted mean over the signals that are defined (weights renormalized)."""
    num = 0.0
    denom = 0.0
    for signal, weight in WEIGHTS.items():
        val = per_signal.get(signal)
        if val is None:
            continue
        num += weight * val
        denom += weight
    return num / denom if denom else 0.0


def rank(new: TargetProfile, db: list[TargetProfile]) -> list[Ranked]:
    """Rank DB candidates against ``new``, highest overall first."""
    ranked: list[Ranked] = []
    for candidate in db:
        per = score(new, candidate)
        ranked.append(
            Ranked(
                target_name=candidate.target_name,
                overall=_overall(per),
                # keep None-as-"n/a" out of the numeric map but preserve it for display
                per_signal={k: (v if v is not None else -1.0) for k, v in per.items()},
                cites=candidate.cites,
            )
        )
    ranked.sort(key=lambda r: r.overall, reverse=True)
    return ranked


def confidence(ranked: list[Ranked]) -> dict[str, Any]:
    """Confidence for the top candidate + whether it should be auto-finalized.

    confidence = top * (top - second + MARGIN_FLOOR), clamped to [0,1].
    low_confidence trips when top < MIN_SCORE OR margin < MIN_MARGIN (or no
    candidates at all).
    """
    if not ranked:
        return {"top": None, "score": 0.0, "margin": 0.0, "confidence": 0.0,
                "low_confidence": True, "min_score": MIN_SCORE, "min_margin": MIN_MARGIN}
    top = ranked[0].overall
    second = ranked[1].overall if len(ranked) > 1 else 0.0
    margin = top - second
    conf = max(0.0, min(1.0, top * (margin + MARGIN_FLOOR)))
    low = top < MIN_SCORE or margin < MIN_MARGIN
    return {
        "top": ranked[0].target_name,
        "score": round(top, 4),
        "margin": round(margin, 4),
        "confidence": round(conf, 4),
        "low_confidence": low,
        "min_score": MIN_SCORE,
        "min_margin": MIN_MARGIN,
    }
