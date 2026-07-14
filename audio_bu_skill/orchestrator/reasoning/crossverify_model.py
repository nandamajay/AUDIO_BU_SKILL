"""Phase-2A WP2 — VerificationRow model + verdict/track/authority/coverage enums.

Pure, stdlib-only value object for the Schematic ↔ IPCAT Cross-Verification
Engine (Phase-2A). Mirrors the sibling reasoning dataclasses
(``orchestrator/reasoning/result.py``): ``from __future__ import annotations``,
``to_dict()``, no third-party deps, no network, no timestamps.

One ``VerificationRow`` is emitted per cross-check by a track (T1..T5). The
model is the *shared vocabulary* every track speaks; it does not perform any
comparison itself. It enforces the invariants the spec (PHASE2A_SPECIFICATION_V2
§3, §4) requires so no track can emit an internally inconsistent row:

  * the ``track`` / ``verdict`` / ``authority.strength`` / ``confidence`` values
    are drawn from closed enums (illegal values raise ``ValueError``);
  * a ``coverage_gap_reason`` is present exactly when the verdict is
    ``NOT_CROSS_CHECKABLE`` (a gap must say *why*, and only a gap may);
  * ``warning`` (the reviewer-work-list flag) defaults from the verdict —
    ``True`` for ``DISAGREE_WITH_AUTHORITY``/``REVIEW_REQUIRED``, ``False``
    otherwise — unless the caller sets it explicitly.

Serialization is deterministic: ``to_dict()`` emits a fixed key order, copies
list fields in place (no reordering of caller-meaningful sequences), and
contains no clock/entropy — so ``json.dumps(row.to_dict(), sort_keys=True)`` is
byte-stable across runs and the pure Comparison Core replays identically.

Run the tests: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_model``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Closed enums (PHASE2A_SPECIFICATION_V2 §3/§4) ────────────────────────────

#: Validation tracks. T4 is split into T4a (SoC endpoint, implementable) and
#: T4b (codec binding, structurally out of scope) per V2 §2.
TRACKS: frozenset[str] = frozenset({"T1", "T2", "T3", "T4a", "T4b", "T5"})

#: The five common verdicts (V2 §3.1).
VERDICTS: frozenset[str] = frozenset(
    {
        "MATCH",
        "PARTIAL_MATCH",
        "DISAGREE_WITH_AUTHORITY",
        "NOT_CROSS_CHECKABLE",
        "REVIEW_REQUIRED",
    }
)

#: Authority strength (V2 §4.4). UNAVAILABLE covers both a transient tool
#: failure and the permanent T4b out-of-scope boundary.
AUTHORITY_STRENGTHS: frozenset[str] = frozenset(
    {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
)

#: Coverage-gap reasons (V2 §3.6 / §4.3). Every NOT_CROSS_CHECKABLE row carries
#: exactly one. ``authority_out_of_scope`` is the permanent/architectural gap
#: (IPCAT structurally does not model the fact); ``authority_unavailable`` is a
#: transient run-time failure; the rest are data/lane conditions.
COVERAGE_GAP_REASONS: frozenset[str] = frozenset(
    {
        "source_ambiguous",
        "authority_unavailable",
        "authority_out_of_scope",
        "insufficient_lanes",
        "revision_not_pinned",
    }
)

#: Verdict confidence (V2 §2 confidence rules). ``provisional`` marks a verdict
#: resting on a capped ``swi_search_swi`` result whose set-stability is not yet
#: confirmed (the W4 discipline as a first-class attribute).
CONFIDENCE_LEVELS: frozenset[str] = frozenset(
    {"high", "medium", "provisional", "none"}
)

#: Verdicts whose ``warning`` flag defaults to True (i.e. they land on the
#: reviewer work list) when the caller does not set it explicitly. Every other
#: verdict defaults to False.
_WARNING_DEFAULT_TRUE: frozenset[str] = frozenset(
    {"DISAGREE_WITH_AUTHORITY", "REVIEW_REQUIRED"}
)

#: Fixed serialization key order (stable, deterministic).
_KEY_ORDER: tuple[str, ...] = (
    "track",
    "subject",
    "source",
    "authority",
    "verdict",
    "confidence",
    "coverage_gap_reason",
    "rule_id",
    "warning",
    "review_actions",
    "citations",
    "notes",
)


def _normalize_authority(authority: Any) -> dict[str, Any]:
    """Return a validated authority object with a legal ``strength``.

    Accepts ``None`` (→ an UNAVAILABLE/none authority), or a dict carrying at
    least ``strength``. ``origin`` defaults to ``"none"`` when absent. Any extra
    keys the caller supplies (e.g. an authority ``value``) are preserved.
    """
    if authority is None:
        return {"strength": "UNAVAILABLE", "origin": "none"}
    if not isinstance(authority, dict):
        raise ValueError(f"authority must be a dict or None, got {type(authority).__name__}")
    strength = authority.get("strength")
    if strength not in AUTHORITY_STRENGTHS:
        raise ValueError(
            f"illegal authority.strength {strength!r}; "
            f"expected one of {sorted(AUTHORITY_STRENGTHS)}"
        )
    normalized = dict(authority)
    normalized.setdefault("origin", "none")
    return normalized


@dataclass
class VerificationRow:
    """One schematic↔IPCAT cross-check result.

    Required: ``track``, ``subject``, ``verdict``. Everything else has a safe
    default so a track can build a row incrementally. Construction validates the
    enums and the coverage-gap / warning invariants (see ``__post_init__``); an
    illegal row cannot exist.

    ``source`` is the schematic/design-side value; ``authority`` is the
    IPCAT-side object (``{strength, origin, ...}``). ``warning`` is a tri-state
    on input — ``None`` means "derive from the verdict"; ``True``/``False`` is
    an explicit override.
    """

    track: str
    subject: str
    verdict: str
    source: Any = None
    authority: Any = None
    confidence: str = "none"
    coverage_gap_reason: str | None = None
    rule_id: str | None = None
    warning: bool | None = None
    review_actions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.track not in TRACKS:
            raise ValueError(
                f"illegal track {self.track!r}; expected one of {sorted(TRACKS)}"
            )
        if self.verdict not in VERDICTS:
            raise ValueError(
                f"illegal verdict {self.verdict!r}; expected one of {sorted(VERDICTS)}"
            )
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"illegal confidence {self.confidence!r}; "
                f"expected one of {sorted(CONFIDENCE_LEVELS)}"
            )

        # authority.strength is validated inside _normalize_authority.
        self.authority = _normalize_authority(self.authority)

        # coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE.
        if self.verdict == "NOT_CROSS_CHECKABLE":
            if self.coverage_gap_reason is None:
                raise ValueError(
                    "coverage_gap_reason is required when verdict is NOT_CROSS_CHECKABLE"
                )
            if self.coverage_gap_reason not in COVERAGE_GAP_REASONS:
                raise ValueError(
                    f"illegal coverage_gap_reason {self.coverage_gap_reason!r}; "
                    f"expected one of {sorted(COVERAGE_GAP_REASONS)}"
                )
        elif self.coverage_gap_reason is not None:
            raise ValueError(
                "coverage_gap_reason must be absent unless verdict is "
                f"NOT_CROSS_CHECKABLE (verdict={self.verdict!r})"
            )

        # warning defaults from the verdict unless the caller set it explicitly.
        if self.warning is None:
            self.warning = self.verdict in _WARNING_DEFAULT_TRUE
        else:
            self.warning = bool(self.warning)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order.

        List fields are copied (so the returned dict cannot be mutated through
        the row, and vice-versa) in their existing order — the order a track
        emits review actions/citations/notes is meaningful and preserved, not
        sorted. Contains no timestamps or other non-deterministic fields, so
        repeated calls and ``json.dumps(..., sort_keys=True)`` are byte-stable.
        """
        values: dict[str, Any] = {
            "track": self.track,
            "subject": self.subject,
            "source": self.source,
            "authority": dict(sorted(self.authority.items())),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "coverage_gap_reason": self.coverage_gap_reason,
            "rule_id": self.rule_id,
            "warning": self.warning,
            "review_actions": list(self.review_actions),
            "citations": list(self.citations),
            "notes": list(self.notes),
        }
        return {key: values[key] for key in _KEY_ORDER}
