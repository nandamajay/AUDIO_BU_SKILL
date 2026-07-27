"""H-1 firewall regression test: projector never promotes a candidate.

**Contract:** the projector must never construct a :class:`FactRecord`
where ``candidate_derived`` is ``True`` but ``authority.strength`` is
anything other than ``"UNAVAILABLE"``. That combination — a
schematic-side value carrying a real authority — is precisely the
promotion the disclosure-only firewall exists to prevent.

Two layers of enforcement:

  1. **Static (FactRecord.__post_init__).** :func:`test_direct_promotion_rejected`
     shows the constructor raises ``ValueError`` when handed the
     illegal combination.
  2. **Runtime (projector.project on adversarial gc).**
     :func:`test_projector_never_promotes_on_adversarial_gc` runs the
     real projector on inputs designed to tempt it into promoting a
     candidate, then asserts every emitted FactRecord in the resulting
     template + gap_manifest still satisfies the invariant.

Also verifies (via :func:`test_projector_treats_unknown_verdict_safely`)
that unknown verdicts — DISAGREE_WITH_AUTHORITY, REVIEW_REQUIRED, or
anything else the projector doesn't recognise — resolve to a
NOT_ATTESTED FactRecord with UNAVAILABLE authority. If a future
crossverify verdict slips through without the projector handling it,
this test flags it explicitly (a candidate must not appear ATTESTED
just because the verdict was unfamiliar).
"""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.hw_template.model import FactRecord
from orchestrator.hw_template.projector import ProjectionResult, project


# ── Static invariant on FactRecord itself ───────────────────────────────────


def test_direct_promotion_rejected() -> None:
    """FactRecord.__post_init__ refuses candidate_derived + real authority."""
    for strength in ("IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE"):
        with pytest.raises(ValueError, match="candidate cannot be promoted"):
            FactRecord(
                value=None,
                authority={"strength": strength, "origin": "adversarial"},
                candidate_derived=True,
                candidate_value="adversarial",
                ncc_state="NOT_ATTESTED",
            )


def test_direct_promotion_via_value_slot_rejected() -> None:
    """A candidate_derived FactRecord must not carry a non-None ``value``."""
    with pytest.raises(ValueError, match="``value`` is populated"):
        FactRecord(
            value="promoted-candidate",
            authority={"strength": "UNAVAILABLE", "origin": "none"},
            candidate_derived=True,
            candidate_value="promoted-candidate",
            ncc_state="NOT_ATTESTED",
        )


def test_independently_verified_requires_attested() -> None:
    """independently_verified=True is illegal unless ncc_state == ATTESTED."""
    with pytest.raises(ValueError, match="independently_verified"):
        FactRecord(
            value="x",
            authority={"strength": "IPCAT_DIRECT", "origin": "test"},
            independently_verified=True,
            ncc_state="NOT_ATTESTED",
        )


# ── Runtime invariant on the projector ──────────────────────────────────────


def _adversarial_gc() -> dict[str, Any]:
    """A gc dict designed to lure the projector into promoting candidates.

    * A codec with no row at all → candidate_derived should be True and
      authority must stay UNAVAILABLE.
    * An amplifier row with verdict=DISAGREE_WITH_AUTHORITY and a real
      authority strength → projector must NOT copy that authority
      strength into an ATTESTED FactRecord for that amp.
    * A T5 row with verdict=REVIEW_REQUIRED, ``source`` populated and
      a real authority strength — the projector must still refuse to
      elevate the source to an attested value.
    * An unfamiliar verdict "FUTURE_VERDICT_XYZ" — projector must treat
      it as NOT_ATTESTED, not as an implicit ATTESTED.
    """
    return {
        "soc": None,
        "codecs": [
            {"part_number": "WCD9385", "vendor": "QCom", "role": "primary"},
        ],
        "amplifiers": [{"part_number": "WSA8845", "vendor": "QCom", "role": "left"}],
        "buses": {"i2s": [{"instance": "1", "role": "playback"}]},
        "soundwire": {"present": False},
        "cross_verification": {
            "rows": [
                {
                    "track": "T2",
                    "subject": "amplifier.WSA8845",
                    "source": "WSA8845",
                    "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat"},
                    "verdict": "DISAGREE_WITH_AUTHORITY",
                    "confidence": "high",
                    "coverage_gap_reason": None,
                    "rule_id": "adversarial.disagree",
                    "warning": "authority disagrees with candidate",
                    "review_actions": ["reviewer resolves"],
                    "citations": ["adversarial-cite"],
                    "notes": "This row must NOT produce an ATTESTED amp.",
                },
                {
                    "track": "T5",
                    "subject": "soc",
                    "source": "SM8XXX-FAKE",
                    "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat"},
                    "verdict": "REVIEW_REQUIRED",
                    "confidence": "medium",
                    "coverage_gap_reason": "authority_unavailable",
                    "rule_id": "adversarial.review",
                    "warning": "reviewer must decide",
                    "review_actions": ["reviewer decides SoC"],
                    "citations": ["adversarial-cite"],
                    "notes": "REVIEW_REQUIRED must not become ATTESTED.",
                },
                {
                    "track": "T4b",
                    "subject": "qup_i2s.1",
                    "source": "qup_i2s.1",
                    "authority": {"strength": "IPCAT_DERIVED", "origin": "ipcat"},
                    "verdict": "FUTURE_VERDICT_XYZ",
                    "confidence": "high",
                    "coverage_gap_reason": None,
                    "rule_id": "adversarial.future",
                    "warning": None,
                    "review_actions": [],
                    "citations": ["adversarial-cite"],
                    "notes": "Unknown verdict must NOT be silently attested.",
                },
            ]
        },
    }


def _iter_fact_dicts(obj: Any):
    """Yield every FactRecord.to_dict()-shaped dict under ``obj``.

    A dict is FactRecord-shaped iff it has the ``authority`` +
    ``candidate_derived`` + ``ncc_state`` triple.
    """
    if isinstance(obj, dict):
        if (
            "authority" in obj
            and "candidate_derived" in obj
            and "ncc_state" in obj
        ):
            yield obj
        for v in obj.values():
            yield from _iter_fact_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_fact_dicts(v)


def test_projector_never_promotes_on_adversarial_gc() -> None:
    """Run the real projector on an adversarial gc; scan every FactRecord."""
    gc = _adversarial_gc()
    result: ProjectionResult = project(
        gc, target_name="adversarial", run_id="h1-invariant-1"
    )
    template = result.template.to_dict()
    gap_manifest = result.gap_manifest.to_dict()

    # Every FactRecord in the template must satisfy the invariant.
    facts = list(_iter_fact_dicts(template))
    assert facts, "expected at least one FactRecord in the template"
    for fact in facts:
        if fact["candidate_derived"]:
            assert fact["authority"]["strength"] == "UNAVAILABLE", (
                f"candidate_derived FactRecord carried authority "
                f"{fact['authority']!r} — a promotion escaped the projector. "
                f"row_ref={fact['row_ref']}"
            )
            assert fact["value"] is None, (
                f"candidate_derived FactRecord has non-None value {fact['value']!r} "
                f"— candidate value must live in candidate_value only. "
                f"row_ref={fact['row_ref']}"
            )

    # And the same for every gap entry.
    for gap in gap_manifest["gaps"]:
        if gap["candidate_derived"]:
            assert gap["authority"]["strength"] == "UNAVAILABLE"
            assert gap["value"] is None


def test_projector_treats_unknown_verdict_safely() -> None:
    """A future/unknown verdict must land NOT_ATTESTED, not ATTESTED."""
    gc = _adversarial_gc()
    result = project(gc, target_name="adversarial", run_id="h1-invariant-2")
    template = result.template.to_dict()

    # Find the i2s bus that came from the FUTURE_VERDICT_XYZ row.
    bus_facts = template["buses"]
    assert bus_facts, "expected at least one bus"
    # The i2s bus instance came from the unknown-verdict row; that must
    # NOT be ATTESTED.
    for bus in bus_facts:
        if (
            bus["kind"]["value"] == "i2s"
            or bus["kind"].get("candidate_value") == "i2s"
        ):
            inst = bus["instance"]
            assert inst["ncc_state"] != "ATTESTED", (
                f"i2s bus instance from unknown verdict landed ATTESTED: {inst!r}"
            )
            assert inst["authority"]["strength"] == "UNAVAILABLE"


def test_projector_disagree_verdict_stays_not_attested() -> None:
    """DISAGREE_WITH_AUTHORITY row must NOT ATTEST the amp."""
    gc = _adversarial_gc()
    result = project(gc, target_name="adversarial", run_id="h1-invariant-3")
    template = result.template.to_dict()

    amps = template["amplifiers"]
    assert amps, "expected at least one amplifier"
    amp = amps[0]["part_number"]
    assert amp["ncc_state"] != "ATTESTED", (
        f"DISAGREE_WITH_AUTHORITY row produced ATTESTED amp: {amp!r}"
    )
    assert amp["authority"]["strength"] == "UNAVAILABLE"


def test_review_required_verdict_stays_not_attested() -> None:
    """REVIEW_REQUIRED row must NOT ATTEST the SoC."""
    gc = _adversarial_gc()
    result = project(gc, target_name="adversarial", run_id="h1-invariant-4")
    template = result.template.to_dict()
    soc = template["board_metadata"]["soc"]
    assert soc["ncc_state"] != "ATTESTED", (
        f"REVIEW_REQUIRED row produced ATTESTED SoC: {soc!r}"
    )
    assert soc["authority"]["strength"] == "UNAVAILABLE"


def test_ncc_state_produces_disclosure() -> None:
    """A NOT_CROSS_CHECKABLE row must produce a disclosure entry."""
    gc = {
        "cross_verification": {
            "rows": [
                {
                    "track": "T5",
                    "subject": "board_variant",
                    "source": None,
                    "authority": {"strength": "UNAVAILABLE", "origin": "none"},
                    "verdict": "NOT_CROSS_CHECKABLE",
                    "confidence": "none",
                    "coverage_gap_reason": "authority_out_of_scope",
                    "rule_id": "wp-69.disclosure",
                    "warning": None,
                    "review_actions": [],
                    "citations": [],
                    "notes": "",
                }
            ]
        }
    }
    result = project(gc, target_name="ncc-only", run_id="h1-invariant-5")
    template = result.template.to_dict()
    variant = template["board_metadata"]["board_variant"]
    assert variant["ncc_state"] == "NOT_CROSS_CHECKABLE"
    assert variant["value"] is None
    assert variant["not_attested_disclosures"], (
        "NOT_CROSS_CHECKABLE row produced no disclosure entry"
    )
    assert (
        variant["not_attested_disclosures"][0]["reason"] == "authority_out_of_scope"
    )
