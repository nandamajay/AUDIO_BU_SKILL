"""Phase-3A WP-E — Fact Registry ReviewRecord and ReviewDecision.

Attached to a :class:`FactValue` iff its ``authority_class`` is MANUAL.
Also attached to a :class:`FactProvenance` entry when that entry itself
supersedes or revokes a prior chain entry via manual review.

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §8):

- :class:`ReviewDecision` has exactly four members: PROVIDE, RESOLVE_CONFLICT,
  OVERRIDE, REJECT.
- :meth:`ReviewRecord.__post_init__` enforces six checks:

  1. ``reviewer_id``, ``reviewer_role``, ``question``, ``answer`` non-empty.
  2. ``answered_at >= requested_at`` (both tz-aware UTC).
  3. ``expires_at``, if set, ``> answered_at``.
  4. ``supersedes_provenance_index``, if set, is non-negative.
  5. ``decision == RESOLVE_CONFLICT`` implies index is set.
  6. ``decision == REJECT`` implies index is set.

- :attr:`ReviewRecord.has_evidence` is the substrate for the manual-fact
  confidence cap in :class:`FactValue` (``min(confidence, 0.4)`` when
  no ticket/email/doc).
- :meth:`ReviewRecord.is_expired` is queried by :meth:`Registry.load` at
  read time; expired manual facts remain loaded but tagged with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse


# ── ReviewDecision enum (§8) ──────────────────────────────────────────────

class ReviewDecision(str, Enum):
    """Kind of intervention the reviewer performed. String-valued so JSON
    serialisation is trivial."""

    PROVIDE = "provide"                      # supplied a value where none existed
    RESOLVE_CONFLICT = "resolve_conflict"    # chose a winner among conflicting values
    OVERRIDE = "override"                    # replaced a non-conflicting existing value
    REJECT = "reject"                        # withdrew a previously accepted MANUAL fact


# ── shared validators ─────────────────────────────────────────────────────

def _require_non_empty_str(name: str, s: Any) -> None:
    if not isinstance(s, str) or not s:
        raise ValueError(f"{name}: expected non-empty str, got {s!r}")


def _require_utc(name: str, dt: datetime) -> None:
    if not isinstance(dt, datetime):
        raise TypeError(f"{name}: expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValueError(f"{name}: datetime must be tz-aware (got naive)")
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"{name}: datetime must be UTC (offset != 0)")


# ── ReviewRecord (§8) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReviewRecord:
    """A dated, signed intervention by a human reviewer.

    Fields exactly follow §8 of the WP-E design. Frozen so callers cannot
    mutate a review after it has been captured into a fact's provenance.
    """

    reviewer_id: str
    reviewer_role: str
    requested_at: datetime
    answered_at: datetime
    question: str
    answer: str
    decision: ReviewDecision
    ticket_url: str | None = None
    email_msgid: str | None = None
    doc_ref: str | None = None
    expires_at: datetime | None = None
    supersedes_provenance_index: int | None = None

    def __post_init__(self) -> None:
        # 1. Required non-empty text fields.
        _require_non_empty_str("ReviewRecord.reviewer_id", self.reviewer_id)
        _require_non_empty_str("ReviewRecord.reviewer_role", self.reviewer_role)
        _require_non_empty_str("ReviewRecord.question", self.question)
        _require_non_empty_str("ReviewRecord.answer", self.answer)

        # decision must be a genuine enum member (not a stray string).
        if not isinstance(self.decision, ReviewDecision):
            raise TypeError(
                "ReviewRecord.decision: expected ReviewDecision, "
                f"got {type(self.decision).__name__}"
            )

        # 2. answered_at >= requested_at (both tz-aware UTC).
        _require_utc("ReviewRecord.requested_at", self.requested_at)
        _require_utc("ReviewRecord.answered_at", self.answered_at)
        if self.answered_at < self.requested_at:
            raise ValueError(
                "ReviewRecord.answered_at must be >= requested_at "
                f"(got {self.answered_at.isoformat()} < {self.requested_at.isoformat()})"
            )

        # 3. expires_at, if set, must be strictly > answered_at.
        if self.expires_at is not None:
            _require_utc("ReviewRecord.expires_at", self.expires_at)
            if self.expires_at <= self.answered_at:
                raise ValueError(
                    "ReviewRecord.expires_at must be strictly greater than "
                    f"answered_at (got {self.expires_at.isoformat()} <= "
                    f"{self.answered_at.isoformat()})"
                )

        # 4. supersedes_provenance_index, if set, must be non-negative.
        if self.supersedes_provenance_index is not None:
            if (
                not isinstance(self.supersedes_provenance_index, int)
                or isinstance(self.supersedes_provenance_index, bool)
                or self.supersedes_provenance_index < 0
            ):
                raise ValueError(
                    "ReviewRecord.supersedes_provenance_index: expected "
                    f"non-negative int or None, got {self.supersedes_provenance_index!r}"
                )

        # 5. RESOLVE_CONFLICT implies index is set.
        if (
            self.decision == ReviewDecision.RESOLVE_CONFLICT
            and self.supersedes_provenance_index is None
        ):
            raise ValueError(
                "ReviewRecord: decision RESOLVE_CONFLICT requires "
                "supersedes_provenance_index"
            )

        # 6. REJECT implies index is set.
        if (
            self.decision == ReviewDecision.REJECT
            and self.supersedes_provenance_index is None
        ):
            raise ValueError(
                "ReviewRecord: decision REJECT requires "
                "supersedes_provenance_index"
            )

        # Optional-field shape checks.
        if self.ticket_url is not None:
            if not isinstance(self.ticket_url, str) or not self.ticket_url:
                raise ValueError(
                    "ReviewRecord.ticket_url: expected non-empty str or None, "
                    f"got {self.ticket_url!r}"
                )
            parsed = urlparse(self.ticket_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(
                    "ReviewRecord.ticket_url: URL must have both scheme and "
                    f"netloc (got {self.ticket_url!r})"
                )

        if self.email_msgid is not None:
            if not isinstance(self.email_msgid, str) or not self.email_msgid:
                raise ValueError(
                    "ReviewRecord.email_msgid: expected non-empty str or None, "
                    f"got {self.email_msgid!r}"
                )
            # RFC 5322 Message-ID surface check: must include an '@'.
            if "@" not in self.email_msgid:
                raise ValueError(
                    "ReviewRecord.email_msgid: expected RFC 5322 Message-ID "
                    f"(must contain '@'), got {self.email_msgid!r}"
                )

        if self.doc_ref is not None and (
            not isinstance(self.doc_ref, str) or not self.doc_ref
        ):
            raise ValueError(
                "ReviewRecord.doc_ref: expected non-empty str or None, "
                f"got {self.doc_ref!r}"
            )

    @property
    def has_evidence(self) -> bool:
        """True iff any of ``ticket_url``, ``email_msgid``, ``doc_ref`` is set.

        Read by :class:`FactValue` construction: when a manual fact carries no
        evidence, confidence is clamped to ``min(confidence, 0.4)`` per
        PHASE3_ARCHITECTURE.md §6.2.
        """
        return any((self.ticket_url, self.email_msgid, self.doc_ref))

    def is_expired(self, now: datetime) -> bool:
        """True iff ``expires_at`` is set and ``now >= expires_at``.

        WP-E surfaces expiry as a load warning; freshness policy is WP-F's
        responsibility.
        """
        _require_utc("ReviewRecord.is_expired.now", now)
        return self.expires_at is not None and now >= self.expires_at


__all__ = [
    "ReviewDecision",
    "ReviewRecord",
]
