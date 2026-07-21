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

# Phase B — role-specific signal weights. The single WEIGHTS blend collapses two
# functionally distinct donors (an ADSP/audio-stack donor and a sound-card/codec
# donor) into one scalar, which is why a split target like Nord IQ-10 lands at a
# muddy ~0.72 with a thin margin. These two dicts re-weight the SAME per-signal
# scores from ``score()`` toward each role's decisive signals so each donor can
# be ranked and graded independently. Each sums to 1.0; a signal absent from a
# role dict simply doesn't count toward that role (``_overall`` renormalizes over
# the signals that are both weighted AND defined, exactly as for WEIGHTS).
ADSP_ROLE_SIGNALS: dict[str, float] = {
    "audioreach": 0.40,
    "power_domain_providers": 0.35,
    "soc": 0.25,
}
SNDCARD_ROLE_SIGNALS: dict[str, float] = {
    "codecs": 0.60,
    "soundwire": 0.25,
    "dt_compatibles": 0.15,
}
# Canonical role -> weight-dict map. Keys are the role-confidence keys used
# throughout Phase B (also the generated_case / similarity_report keys).
ROLE_SIGNALS: dict[str, dict[str, float]] = {
    "adsp_stack": ADSP_ROLE_SIGNALS,
    "sound_card": SNDCARD_ROLE_SIGNALS,
}

# Canonical role vocabulary + legacy-alias folding. Phase A landed with QGenie
# tagging nearest_targets roles as "adsp_donor"/"soundcard_donor"; Phase B settled
# on "adsp_stack"/"sound_card" as the canonical keys (they name the functional
# role, not the donor relationship, and match the ROLE_SIGNALS keys that actually
# drive per-role scoring). ``normalize_role`` folds the legacy aliases into the
# canonical set at ingest so every downstream consumer sees ONE vocabulary; the
# runner mirrors this map locally (it does not import the engine on the production
# onboarding path). Canonical and unknown/empty strings pass through unchanged.
CANONICAL_ROLES: tuple[str, ...] = ("adsp_stack", "sound_card")
ROLE_ALIASES: dict[str, str] = {
    "adsp_donor": "adsp_stack",
    "soundcard_donor": "sound_card",
}


def normalize_role(role: str) -> str:
    """Fold a possibly-legacy role string to the canonical vocabulary.

    ``adsp_donor`` -> ``adsp_stack``; ``soundcard_donor`` -> ``sound_card``.
    Canonical strings and unknown/empty strings are returned unchanged.
    """
    return ROLE_ALIASES.get(role, role)

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


def _overall(per_signal: dict[str, float | None], weights: dict[str, float] = WEIGHTS) -> float:
    """Weighted mean over the signals that are defined (weights renormalized).

    ``weights`` defaults to the blended WEIGHTS; Phase B passes a per-role weight
    dict (ADSP_ROLE_SIGNALS / SNDCARD_ROLE_SIGNALS) to re-weight the same
    per-signal scores toward one donor role. Renormalization is over the signals
    present in ``weights`` AND defined in ``per_signal`` — so a role dict that
    omits a signal, or a signal that is None (undetectable on both profiles),
    simply drops out of that role's mean rather than counting as zero.
    """
    num = 0.0
    denom = 0.0
    for signal, weight in weights.items():
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


# ---------------------------------------------------------------------------
# Phase B — per-role ranking and confidence
#
# The blended rank()/confidence() above answer "which one donor is nearest?".
# For a split target that has TWO donors (an ADSP-stack donor and a sound-card
# donor) that single answer is misleading: the codec signals and the ADSP
# signals pull toward different candidates, so the blend lands between them at a
# thin margin. rank_per_role()/role_confidence() re-rank the SAME candidates
# once per role using ROLE_SIGNALS, so each donor is graded on the signals that
# actually decide that role. This is additive and advisory — it does not replace
# rank()/confidence() and drives no generation.
# ---------------------------------------------------------------------------


def rank_per_role(
    new: TargetProfile, db: list[TargetProfile],
    role_signals: dict[str, dict[str, float]] = ROLE_SIGNALS,
) -> dict[str, list[Ranked]]:
    """Rank DB candidates against ``new`` once per role, highest overall first.

    Returns ``{role: [Ranked, ...]}`` for each role in ``role_signals``. The
    per-signal scores are computed once per candidate (via ``score``) and then
    re-weighted per role through ``_overall``, so the only thing that differs
    between roles is which signals dominate the overall — the underlying
    similarity is identical to what ``rank`` sees.
    """
    per_by_candidate = [(c, score(new, c)) for c in db]
    out: dict[str, list[Ranked]] = {}
    for role, weights in role_signals.items():
        ranked = [
            Ranked(
                target_name=candidate.target_name,
                overall=_overall(per, weights),
                per_signal={k: (v if v is not None else -1.0) for k, v in per.items()},
                cites=candidate.cites,
            )
            for candidate, per in per_by_candidate
        ]
        ranked.sort(key=lambda r: r.overall, reverse=True)
        out[role] = ranked
    return out


def role_confidence(ranked_by_role: dict[str, list[Ranked]]) -> dict[str, dict[str, Any]]:
    """Per-role confidence, one ``confidence()``-shaped block per role.

    Returns ``{role: {"top", "score", "margin", "confidence", "low_confidence",
    "min_score", "min_margin"}}`` — the exact shape ``confidence()`` returns,
    computed independently for each role's ranking using the identical formula
    (``top * (margin + MARGIN_FLOOR)`` clamped, gated on MIN_SCORE / MIN_MARGIN).
    A role whose ranking is empty gets the same empty-ranking block ``confidence``
    produces.
    """
    return {role: confidence(ranked) for role, ranked in ranked_by_role.items()}
