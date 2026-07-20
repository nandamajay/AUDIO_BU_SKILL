"""Phase-3A WP-E — tests for the Fact Registry ReviewRecord — T-E23..T-E28.

Runs entirely in-process; does not touch case.py, case.generated.py, WP7,
onboarding, or any runtime flow. Advisory-only per PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=.:audio_bu_skill python3 -m tests.test_fact_registry_review
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from audio_bu_skill.orchestrator.fact_registry import (
    ReviewDecision,
    ReviewRecord,
)

UTC = timezone.utc
_REQ = datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)
_ANS = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)


def _assert_raises(fn, exc, message_substring=None):
    try:
        fn()
    except exc as e:
        if message_substring is not None and message_substring not in str(e):
            raise AssertionError(
                f"expected {exc.__name__} containing {message_substring!r}, "
                f"got {exc.__name__} with message {e!r}"
            )
        return
    raise AssertionError(f"expected {exc.__name__} to be raised, but nothing raised")


def _review(**overrides) -> ReviewRecord:
    kw = dict(
        reviewer_id="alice", reviewer_role="audio-lead",
        requested_at=_REQ, answered_at=_ANS,
        question="q", answer="a",
        decision=ReviewDecision.PROVIDE,
    )
    kw.update(overrides)
    return ReviewRecord(**kw)


# ── T-E23 — answered_at < requested_at rejected ────────────────────────────

def test_te23_rejects_answered_before_requested() -> None:
    _assert_raises(
        lambda: _review(requested_at=_ANS, answered_at=_REQ),
        ValueError,
    )


# ── T-E24 — expires_at <= answered_at rejected ─────────────────────────────

def test_te24_rejects_expires_not_after_answered() -> None:
    # equal to answered_at
    _assert_raises(lambda: _review(expires_at=_ANS), ValueError)
    # before answered_at
    _assert_raises(
        lambda: _review(expires_at=_ANS - timedelta(hours=1)),
        ValueError,
    )


# ── T-E25 — has_evidence True iff any of the three set ─────────────────────

def test_te25_has_evidence() -> None:
    assert _review().has_evidence is False
    assert _review(ticket_url="https://t.example.com/A-1").has_evidence is True
    assert _review(email_msgid="msg@example.com").has_evidence is True
    assert _review(doc_ref="DOC-1").has_evidence is True


# ── T-E26 — RESOLVE_CONFLICT requires supersedes index ─────────────────────

def test_te26_resolve_conflict_requires_index() -> None:
    _assert_raises(
        lambda: _review(decision=ReviewDecision.RESOLVE_CONFLICT),
        ValueError,
    )
    ok = _review(decision=ReviewDecision.RESOLVE_CONFLICT,
                 supersedes_provenance_index=0)
    assert ok.supersedes_provenance_index == 0


# ── T-E27 — REJECT requires supersedes index ───────────────────────────────

def test_te27_reject_requires_index() -> None:
    _assert_raises(
        lambda: _review(decision=ReviewDecision.REJECT),
        ValueError,
    )
    ok = _review(decision=ReviewDecision.REJECT, supersedes_provenance_index=1)
    assert ok.supersedes_provenance_index == 1


# ── T-E28 — is_expired respects datetime now ───────────────────────────────

def test_te28_is_expired() -> None:
    exp = _ANS + timedelta(days=30)
    r = _review(ticket_url="https://t.example.com/A-1", expires_at=exp)
    # before expiry
    assert r.is_expired(_ANS + timedelta(days=1)) is False
    # after expiry
    assert r.is_expired(exp + timedelta(seconds=1)) is True
    # exactly at expiry (>= => expired)
    assert r.is_expired(exp) is True
    # no expiry set => never expired
    assert _review().is_expired(_ANS + timedelta(days=365)) is False
    # naive 'now' rejected
    _assert_raises(lambda: r.is_expired(datetime(2026, 8, 1)), ValueError)


def main() -> None:
    # T-E23..T-E24  temporal invariants
    test_te23_rejects_answered_before_requested()
    test_te24_rejects_expires_not_after_answered()
    # T-E25  evidence
    test_te25_has_evidence()
    # T-E26..T-E27  supersedes-index requirements
    test_te26_resolve_conflict_requires_index()
    test_te27_reject_requires_index()
    # T-E28  expiry
    test_te28_is_expired()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
