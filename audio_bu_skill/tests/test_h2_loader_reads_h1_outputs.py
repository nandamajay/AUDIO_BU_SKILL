"""H-2 loader — reads all four H-1 targets with zero exceptions.

Phase-1 loader exit criterion: :func:`orchestrator.reviewer.loader.load`
parses every target that has H-1 output and returns a well-formed
:class:`TargetView` with no promotion and no side effects.

Includes the **Nord Reality Check** (Rule 9): the real Nord target has
exactly 2 codecs and every other entity family empty — the loader must
NOT synthesise or fill anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.reviewer.loader import context_for_target, load
from orchestrator.reviewer.model import GAP_REASONS, TargetView

_TARGETS_DIR = Path(__file__).resolve().parent.parent / "targets"

_ALL_TARGETS = ("nord-iq10", "eliza", "synthetic-i2s-min", "synthetic-swr-min")


def _load(target: str) -> TargetView:
    ctx = context_for_target(_TARGETS_DIR / target, target)
    return load(ctx)


@pytest.mark.parametrize("target", _ALL_TARGETS)
def test_loader_parses_target_without_exception(target: str) -> None:
    view = _load(target)
    assert isinstance(view, TargetView)
    assert view.target_name  # non-empty
    assert view.schema_version == "0.1.0-design"


@pytest.mark.parametrize("target", _ALL_TARGETS)
def test_all_gap_reasons_are_closed(target: str) -> None:
    view = _load(target)
    for gap in view.gaps:
        assert gap.reason in GAP_REASONS
        # Phase-1: no severity / state / comment assigned yet.
        assert gap.severity is None
        assert gap.state is None
        assert gap.comment is None


@pytest.mark.parametrize("target", _ALL_TARGETS)
def test_loader_is_idempotent(target: str) -> None:
    assert _load(target) == _load(target)


def test_nord_reality_check() -> None:
    """Real Nord: exactly 2 codecs, all other families empty (Rule 9)."""
    view = _load("nord-iq10")
    assert len(view.entities_of("codec")) == 2
    for empty_kind in ("amplifier", "bus", "clock", "audio_link"):
        assert view.entities_of(empty_kind) == (), (
            f"Nord must not synthesise {empty_kind} entities (Rule 9)"
        )
    # board_metadata is the singleton group, present once.
    assert len(view.entities_of("board_metadata")) == 1
    # 8 gaps: 2 candidate_only + 6 not_attested.
    assert view.summary["gap_count"] == 8
    assert view.summary["gap_count_by_reason"] == {
        "candidate_only": 2,
        "not_attested": 6,
    }


def test_nord_codec_role_candidate_not_promoted() -> None:
    """codecs[0].role is candidate_derived; value MUST remain None (I-1/I-4)."""
    view = _load("nord-iq10")
    codec0 = view.entities_of("codec")[0]
    role = codec0.fields["role"]
    assert role.candidate_derived is True
    assert role.value is None  # never promoted from candidate_value
    assert role.candidate_value == "DAC / playback path, I2C-attached"
    assert role.authority_strength == "UNAVAILABLE"


def test_swr_min_has_attested_entities() -> None:
    """synthetic-swr-min carries attested IPCAT authorities — projected verbatim."""
    view = _load("synthetic-swr-min")
    # at least one field somewhere carries a non-UNAVAILABLE authority.
    strengths = {
        f.authority_strength
        for e in view.entities
        for f in e.fields.values()
    }
    assert strengths & {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE"}, (
        f"expected an attested authority in synthetic-swr-min, saw {strengths}"
    )
