"""Phase-3A WP-E — tests for the Fact Registry model layer (FactKey,
FactProvenance, FactValue) — T-E1..T-E10.

Runs entirely in-process; does not touch case.py, case.generated.py, WP7,
onboarding, or any runtime flow. Advisory-only per PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=.:audio_bu_skill python3 -m tests.test_fact_registry_models
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from audio_bu_skill.fact_requirements import Authority, AuthorityClass, Domain
from audio_bu_skill.orchestrator.fact_registry import (
    FactKey,
    FactProvenance,
    FactValue,
    IPCATCachedRef,
    KernelRef,
    ManualRef,
    ReviewDecision,
    ReviewRecord,
    SchematicRef,
)

UTC = timezone.utc
_TS = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)


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


# ── helpers ───────────────────────────────────────────────────────────────

def _kernel_ref() -> KernelRef:
    return KernelRef(
        kind="kernel", kernel_ref_kind="dts", repo="kernel/msm-5.15",
        commit="b" * 40, path="a.dts", line_start=10, line_end=12,
    )


def _prov(**overrides) -> FactProvenance:
    kw = dict(
        value=42,
        authority=Authority.KERNEL_DTS,
        authority_class=AuthorityClass.PRIMARY,
        source_ref=_kernel_ref(),
        captured_at=_TS,
        confidence=0.9,
        note="obs",
    )
    kw.update(overrides)
    return FactProvenance(**kw)


def _manual_review(**overrides) -> ReviewRecord:
    kw = dict(
        reviewer_id="alice", reviewer_role="audio-lead",
        requested_at=_TS, answered_at=_TS,
        question="q", answer="a",
        decision=ReviewDecision.PROVIDE,
        ticket_url="https://tracker.example.com/A-1",
    )
    kw.update(overrides)
    return ReviewRecord(**kw)


def _value_from_prov(prov: FactProvenance) -> FactValue:
    """Build a single-entry FactValue whose descriptor matches ``prov``."""
    return FactValue(
        prov.value, prov.authority, prov.authority_class, prov.captured_at,
        prov.source_ref, prov.confidence, prov.review, prov.note, (prov,),
    )


# ── T-E1 — FactKey.parse(as_string) round-trips ────────────────────────────

def test_te1_factkey_roundtrip() -> None:
    fk = FactKey(Domain.AUDIO, "codec", "wcd9395", "reset_gpio")
    assert fk.as_string() == "Audio.codec/wcd9395/reset_gpio"
    assert FactKey.parse(fk.as_string()) == fk


# ── T-E2 — FactKey rejects malformed identifiers ───────────────────────────

def test_te2_factkey_rejects_malformed() -> None:
    # bad family (starts with digit)
    _assert_raises(lambda: FactKey(Domain.AUDIO, "9bad", "s", "a"), ValueError)
    # bad attribute (uppercase)
    _assert_raises(lambda: FactKey(Domain.AUDIO, "codec", "s", "Attr"), ValueError)
    # empty subject
    _assert_raises(lambda: FactKey(Domain.AUDIO, "codec", "", "a"), ValueError)
    # domain not a Domain instance
    _assert_raises(lambda: FactKey("Audio", "codec", "s", "a"), TypeError)
    # parse: wrong part count
    _assert_raises(lambda: FactKey.parse("Audio.codec/only_two"), ValueError)
    # parse: unknown domain
    _assert_raises(lambda: FactKey.parse("Nope.codec/s/a"), ValueError)


# ── T-E3 — MANUAL authority_class requires a review ────────────────────────

def test_te3_manual_requires_review() -> None:
    # FactProvenance: MANUAL class => MANUAL authority; still valid w/o review
    # at the provenance layer, but FactValue inv4 requires review non-null.
    prov = _prov(
        authority=Authority.MANUAL,
        authority_class=AuthorityClass.MANUAL,
        source_ref=ManualRef(kind="manual", note="n",
                             ticket_url="https://tracker.example.com/A-1"),
        review=None,
    )
    _assert_raises(lambda: _value_from_prov(prov), ValueError)


# ── T-E4 — INFERRED class requires INFERRED authority ──────────────────────

def test_te4_inferred_class_requires_inferred_authority() -> None:
    _assert_raises(
        lambda: _prov(
            authority=Authority.KERNEL_DTS,
            authority_class=AuthorityClass.INFERRED,
        ),
        ValueError,
    )


# ── T-E5 — MANUAL class requires MANUAL authority ──────────────────────────

def test_te5_manual_class_requires_manual_authority() -> None:
    _assert_raises(
        lambda: _prov(
            authority=Authority.KERNEL_DTS,
            authority_class=AuthorityClass.MANUAL,
        ),
        ValueError,
    )


# ── T-E6 — confidence capped at 0.4 when review has no evidence ────────────

def test_te6_confidence_capped_without_evidence() -> None:
    # Review with NO evidence (no ticket/email/doc) => has_evidence False.
    review = ReviewRecord(
        reviewer_id="alice", reviewer_role="audio-lead",
        requested_at=_TS, answered_at=_TS,
        question="q", answer="a",
        decision=ReviewDecision.PROVIDE,
    )
    assert review.has_evidence is False
    prov = _prov(
        authority=Authority.MANUAL,
        authority_class=AuthorityClass.MANUAL,
        source_ref=ManualRef(kind="manual", note="n"),
        confidence=0.95,
        review=review,
    )
    fv = _value_from_prov(prov)
    assert fv.confidence == 0.4  # capped

    # With evidence, the same 0.95 is preserved.
    prov2 = _prov(
        authority=Authority.MANUAL,
        authority_class=AuthorityClass.MANUAL,
        source_ref=ManualRef(kind="manual", note="n",
                             ticket_url="https://tracker.example.com/A-1"),
        confidence=0.95,
        review=_manual_review(),
    )
    fv2 = _value_from_prov(prov2)
    assert fv2.confidence == 0.95


# ── T-E7 — rejects naive captured_at ───────────────────────────────────────

def test_te7_rejects_naive_captured_at() -> None:
    naive = datetime(2026, 7, 15, 10, 0, 0)  # no tzinfo
    _assert_raises(lambda: _prov(captured_at=naive), ValueError)


# ── T-E8 — rejects confidence outside [0, 1] ───────────────────────────────

def test_te8_rejects_confidence_out_of_range() -> None:
    _assert_raises(lambda: _prov(confidence=1.5), ValueError)
    _assert_raises(lambda: _prov(confidence=-0.1), ValueError)
    # bool must be rejected (not a valid float confidence)
    _assert_raises(lambda: _prov(confidence=True), TypeError)


# ── T-E9 — FactValue rejects descriptor != last provenance entry ───────────

def test_te9_rejects_descriptor_mismatch() -> None:
    prov = _prov(value=42)
    # Descriptor value 99 != chain top value 42.
    _assert_raises(
        lambda: FactValue(
            99, prov.authority, prov.authority_class, prov.captured_at,
            prov.source_ref, prov.confidence, prov.review, prov.note, (prov,),
        ),
        ValueError,
    )


# ── T-E10 — authority ↔ source_ref cross-check enforced ────────────────────

def test_te10_authority_source_ref_crosscheck() -> None:
    # KERNEL_DTS authority with a schematic source_ref must be rejected.
    _assert_raises(
        lambda: _prov(
            authority=Authority.KERNEL_DTS,
            authority_class=AuthorityClass.PRIMARY,
            source_ref=SchematicRef(kind="schematic", doc_id="D", revision="A", page=1),
        ),
        ValueError,
    )
    # IPCAT_CACHED authority with a kernel source_ref must be rejected.
    _assert_raises(
        lambda: _prov(
            authority=Authority.IPCAT_CACHED,
            authority_class=AuthorityClass.PRIMARY,
            source_ref=_kernel_ref(),
        ),
        ValueError,
    )
    # Correct pairing (IPCAT_CACHED ↔ ipcat_cached) is accepted.
    ok = _prov(
        authority=Authority.IPCAT_CACHED,
        authority_class=AuthorityClass.PRIMARY,
        source_ref=IPCATCachedRef(kind="ipcat_cached", path="p", sha256="a" * 64),
    )
    assert ok.authority is Authority.IPCAT_CACHED


def main() -> None:
    # T-E1..T-E2  FactKey
    test_te1_factkey_roundtrip()
    test_te2_factkey_rejects_malformed()
    # T-E3..T-E8  FactProvenance / FactValue invariants
    test_te3_manual_requires_review()
    test_te4_inferred_class_requires_inferred_authority()
    test_te5_manual_class_requires_manual_authority()
    test_te6_confidence_capped_without_evidence()
    test_te7_rejects_naive_captured_at()
    test_te8_rejects_confidence_out_of_range()
    # T-E9..T-E10  descriptor match + cross-check
    test_te9_rejects_descriptor_mismatch()
    test_te10_authority_source_ref_crosscheck()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
