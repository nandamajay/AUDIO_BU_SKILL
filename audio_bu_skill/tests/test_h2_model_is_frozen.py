"""H-2 model — frozen dataclasses + closed-enum drift guard.

Two properties:

  * All five view dataclasses are ``frozen`` — a projected fact cannot be
    mutated back into something H-1 did not produce.
  * The locally re-declared authority / NCC enums (I-2 forces H-2 to
    duplicate rather than import them) still match H-1's values, and do
    NOT contain ``SCHEMATIC_DIRECT`` or ``HUMAN_ATTESTED`` (invariant
    I-4). If H-1 ever widens its enum this guard fails loudly, forcing
    the duplicate to be updated in lock-step.
"""

from __future__ import annotations

import dataclasses

import pytest

from orchestrator.reviewer.model import (
    AUTHORITY_STRENGTHS,
    ENTITY_KINDS,
    GAP_REASONS,
    NCC_STATES,
    EntityView,
    FactView,
    GapView,
    ReviewerContext,
    TargetView,
)


@pytest.mark.parametrize(
    "cls", [ReviewerContext, FactView, GapView, EntityView, TargetView]
)
def test_dataclass_is_frozen(cls) -> None:
    params = getattr(cls, "__dataclass_params__", None)
    assert params is not None, f"{cls.__name__} is not a dataclass"
    assert params.frozen, f"{cls.__name__} must be frozen"


def test_factview_cannot_be_mutated() -> None:
    fv = FactView()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fv.value = "tampered"  # type: ignore[misc]


def test_authority_enum_is_the_closed_four() -> None:
    assert AUTHORITY_STRENGTHS == frozenset(
        {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
    )
    assert "SCHEMATIC_DIRECT" not in AUTHORITY_STRENGTHS
    assert "HUMAN_ATTESTED" not in AUTHORITY_STRENGTHS


def test_ncc_states_closed_set() -> None:
    assert NCC_STATES == frozenset(
        {"ATTESTED", "NOT_ATTESTED", "NOT_CROSS_CHECKABLE"}
    )


def test_gap_reasons_closed_set() -> None:
    assert GAP_REASONS == frozenset(
        {"candidate_only", "not_attested", "authority_out_of_scope"}
    )


def test_entity_kinds_closed_set() -> None:
    assert ENTITY_KINDS == frozenset(
        {"board_metadata", "codec", "amplifier", "bus", "clock", "audio_link"}
    )


def test_factview_rejects_illegal_authority() -> None:
    with pytest.raises(ValueError):
        FactView(authority_strength="SCHEMATIC_DIRECT")
    with pytest.raises(ValueError):
        FactView(authority_strength="HUMAN_ATTESTED")


def test_factview_rejects_illegal_ncc_state() -> None:
    with pytest.raises(ValueError):
        FactView(ncc_state="BOGUS")


def test_gapview_rejects_illegal_reason() -> None:
    with pytest.raises(ValueError):
        GapView(path="codecs[0].role", reason="not_a_reason", fact=FactView())


def test_entityview_rejects_illegal_kind() -> None:
    with pytest.raises(ValueError):
        EntityView(kind="widget", index=0)


def test_from_record_copies_verbatim_no_promotion() -> None:
    """candidate_derived record projects value=None (no promotion)."""
    record = {
        "value": None,
        "authority": {"strength": "UNAVAILABLE", "origin": "none"},
        "citations": [],
        "candidate_derived": True,
        "candidate_value": "some role",
        "reviewer_required": True,
        "ncc_state": "NOT_ATTESTED",
    }
    fv = FactView.from_record(record, path="codecs[0].role")
    assert fv.value is None
    assert fv.candidate_value == "some role"
    assert fv.candidate_derived is True
    assert fv.path == "codecs[0].role"
    # tuples, not lists — deeply immutable.
    assert isinstance(fv.citations, tuple)
    assert isinstance(fv.not_attested_disclosures, tuple)
