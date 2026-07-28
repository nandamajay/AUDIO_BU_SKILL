"""dt_scaffolding pinctrl_state template consumption tests.

Validates:
  - ATTESTED pinctrl_state from H-1 template overrides hardcoded label.
  - NOT_ATTESTED / missing template falls back to hardcoded label (byte-identity).
  - Different ATTESTED values produce correctly-named nodes.
  - template=None is backward-compatible (existing tests unaffected).

All fixtures are SYNTHETIC. Results are NOT real-target.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.generation.dt_scaffolding import (
    generate_dt,
    _PINCTRL_STATE_LABEL,
    _template_value,
)
from orchestrator.generation.model import (
    GeneratedArtifact,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Helpers ──────────────────────────────────────────────────────────────────


def _row(
    track: str,
    subject: str,
    verdict: str,
    *,
    rule_id: str | None = None,
    warning: bool | None = None,
) -> VerificationRow:
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        authority={"strength": "IPCAT_DIRECT", "origin": "ipcat.test"},
        confidence="high",
        rule_id=rule_id,
        warning=warning,
    )


def _open_facts() -> TrustedFacts:
    """Facts that open all dt_scaffolding gates."""
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    return TrustedFacts(
        rows_by_track_subject={f"{r.track}.{r.subject}": r for r in rows}
    )


def _attested_pinctrl_template(label: str = "i2s8_active") -> dict:
    """Build a template dict with ATTESTED pinctrl_state."""
    return {
        "board_metadata": {
            "pinctrl_state": {
                "value": label,
                "ncc_state": "ATTESTED",
                "authority": {"strength": "IPCAT_DERIVED", "origin": "kernel_dt"},
            },
        }
    }


def _not_attested_pinctrl_template() -> dict:
    """Build a template dict with NOT_ATTESTED pinctrl_state."""
    return {
        "board_metadata": {
            "pinctrl_state": {
                "value": None,
                "ncc_state": "NOT_ATTESTED",
                "authority": {"strength": "UNAVAILABLE", "origin": "none"},
            },
        }
    }


# ── Test: ATTESTED template fires → label appears in output ──────────────────


class TestAttestedPinctrlOverrides:
    """ATTESTED pinctrl_state from H-1 template drives the node label."""

    def test_attested_label_appears_in_output(self):
        """Template ATTESTED 'i2s8_active' → node uses that label.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()
        template = _attested_pinctrl_template("i2s8_active")

        result = generate_dt(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert "i2s8_active: i2s8-active-state {" in output

    def test_different_attested_label_changes_node(self):
        """Template ATTESTED 'i2s4_active' → node uses 'i2s4_active'.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()
        template = _attested_pinctrl_template("i2s4_active")

        result = generate_dt(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert "i2s4_active: i2s4-active-state {" in output
        assert "i2s8_active" not in output

    def test_attested_label_with_underscores_converts_to_dashes_in_node_name(self):
        """Label 'tdm3_active' → node name 'tdm3-active-state'.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()
        template = _attested_pinctrl_template("tdm3_active")

        result = generate_dt(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert "tdm3_active: tdm3-active-state {" in output


# ── Test: NOT_ATTESTED / None → hardcoded fallback (byte-identity) ───────────


class TestNotAttestedFallback:
    """NOT_ATTESTED or missing template → hardcoded label fires."""

    def test_not_attested_template_uses_hardcoded(self):
        """Template with NOT_ATTESTED pinctrl_state → hardcoded label.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()
        template = _not_attested_pinctrl_template()

        result = generate_dt(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert f"{_PINCTRL_STATE_LABEL}: " in output

    def test_none_template_uses_hardcoded(self):
        """template=None → hardcoded label (backward compatible).

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()

        result = generate_dt(facts, template=None)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert f"{_PINCTRL_STATE_LABEL}: " in output

    def test_byte_identity_none_vs_not_attested(self):
        """template=None produces same bytes as NOT_ATTESTED template.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()

        r_none = generate_dt(facts, template=None)
        r_not_attested = generate_dt(facts, template=_not_attested_pinctrl_template())

        assert isinstance(r_none, GeneratedArtifact)
        assert isinstance(r_not_attested, GeneratedArtifact)
        assert r_none.bytes_ == r_not_attested.bytes_

    def test_byte_identity_attested_matching_hardcoded(self):
        """ATTESTED label == hardcoded constant → same bytes as no template.

        This is the real-Nord case: the template derives 'i2s8_active'
        which equals the hardcoded constant — output is byte-identical.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _open_facts()

        r_none = generate_dt(facts, template=None)
        r_attested = generate_dt(
            facts, template=_attested_pinctrl_template(_PINCTRL_STATE_LABEL)
        )

        assert isinstance(r_none, GeneratedArtifact)
        assert isinstance(r_attested, GeneratedArtifact)
        assert r_none.bytes_ == r_attested.bytes_


# ── Test: _template_value helper unit tests ──────────────────────────────────


class TestTemplateValueHelper:
    """Unit tests for dt_scaffolding's _template_value helper."""

    def test_returns_attested_value(self):
        tpl = {"board_metadata": {"pinctrl_state": {
            "value": "i2s8_active", "ncc_state": "ATTESTED",
            "authority": {"strength": "IPCAT_DERIVED", "origin": "kernel_dt"},
        }}}
        assert _template_value(tpl, "board_metadata", "pinctrl_state") == "i2s8_active"

    def test_returns_none_for_not_attested(self):
        tpl = {"board_metadata": {"pinctrl_state": {
            "value": None, "ncc_state": "NOT_ATTESTED",
            "authority": {"strength": "UNAVAILABLE", "origin": "none"},
        }}}
        assert _template_value(tpl, "board_metadata", "pinctrl_state") is None

    def test_returns_none_for_none_template(self):
        assert _template_value(None, "board_metadata", "pinctrl_state") is None

    def test_returns_none_for_missing_key(self):
        tpl = {"board_metadata": {}}
        assert _template_value(tpl, "board_metadata", "pinctrl_state") is None

    def test_returns_none_for_attested_none_value(self):
        tpl = {"board_metadata": {"pinctrl_state": {
            "value": None, "ncc_state": "ATTESTED",
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
        }}}
        assert _template_value(tpl, "board_metadata", "pinctrl_state") is None
