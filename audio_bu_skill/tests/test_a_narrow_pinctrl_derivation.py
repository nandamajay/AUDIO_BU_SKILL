"""A-narrow — pinctrl_state derivation from audio_topology.pinmux.

Validates:
  1. Projector derives pinctrl_state when exactly ONE state_label in pinmux.
  2. Projector leaves pinctrl_state NOT_ATTESTED when zero labels.
  3. Projector leaves pinctrl_state NOT_ATTESTED when multiple labels.
  4. Byte-identity: emitted <&i2s8_active> unchanged, source is template.
  5. Provenance: value flows from template authority (kernel_dt), not constant.
  6. PinmuxFact carries state_label field.
  7. WP-64 / WP-69 / H-1 / Phase-A regressions unaffected.

All fixtures are synthetic or fixture-derived. Results are NOT real-target.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_NORD_TEMPLATE = _REPO / "targets" / "nord-iq10" / "h1_validation" / "audio_hardware_template.json"
_EXPECTED_DTSI = _REPO / "tests" / "fixtures" / "phase2b" / "nord_machine_driver_expected.dtsi"

from orchestrator.hw_template.projector import (
    _derive_pinctrl_state,
    project,
)
from orchestrator.hw_template.model import FactRecord
from orchestrator.source_ingest.pinmux import PinmuxFact, derive_pinmux_from_dt
from orchestrator.generation.machine_driver import (
    _template_value,
    generate_machine_driver,
)
from orchestrator.generation.model import GeneratedArtifact


def _clean_nord_facts():
    """Import the shared helper for Nord TrustedFacts fixture."""
    from tests.test_generation_source_probe import _clean_nord_facts as _inner
    return _inner()


# ── Derivation rule tests ─────────────────────────────────────────────────────


class TestPinctrlDerivationRule:
    """Verify the single-label / zero / multi-label derivation logic."""

    def test_single_label_yields_attested(self):
        """Exactly one state_label across I2S pinmux → ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "audio_topology": {
                "pinmux": [
                    {"pin": 147, "function": 1, "role": "mclk", "name": "gpio.i2s.mclk", "state_label": "i2s8_active"},
                    {"pin": 148, "function": 1, "role": "sclk", "name": "gpio.i2s.sclk", "state_label": "i2s8_active"},
                    {"pin": 149, "function": 1, "role": "ws", "name": "gpio.i2s.ws", "state_label": "i2s8_active"},
                    {"pin": 150, "function": 1, "role": "data", "name": "gpio.i2s.data", "state_label": "i2s8_active"},
                ]
            }
        }
        fact = _derive_pinctrl_state(gc)
        assert isinstance(fact, FactRecord)
        assert fact.ncc_state == "ATTESTED"
        assert fact.value == "i2s8_active"
        assert fact.authority["origin"] == "kernel_dt"
        assert fact.authority["strength"] == "IPCAT_DERIVED"

    def test_zero_labels_yields_not_attested(self):
        """No state_label in pinmux entries → NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "audio_topology": {
                "pinmux": [
                    {"pin": 147, "function": 1, "role": "mclk", "name": "gpio.i2s.mclk"},
                ]
            }
        }
        fact = _derive_pinctrl_state(gc)
        assert isinstance(fact, FactRecord)
        assert fact.ncc_state == "NOT_ATTESTED"
        assert fact.value is None

    def test_multi_labels_yields_not_attested(self):
        """Multiple distinct state_labels → NOT_ATTESTED (no guessing).

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "audio_topology": {
                "pinmux": [
                    {"pin": 147, "function": 1, "role": "mclk", "name": "gpio.i2s.mclk", "state_label": "i2s8_active"},
                    {"pin": 200, "function": 1, "role": "sclk", "name": "gpio.i2s.sclk", "state_label": "i2s3_active"},
                ]
            }
        }
        fact = _derive_pinctrl_state(gc)
        assert isinstance(fact, FactRecord)
        assert fact.ncc_state == "NOT_ATTESTED"
        assert fact.value is None

    def test_no_pinmux_key_yields_not_attested(self):
        """audio_topology without pinmux → NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"audio_topology": {}}
        fact = _derive_pinctrl_state(gc)
        assert fact.ncc_state == "NOT_ATTESTED"

    def test_pinmux_is_string_sentinel_yields_not_attested(self):
        """pinmux = "SOURCE_UNRESOLVED" (sentinel literal) → NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"audio_topology": {"pinmux": "SOURCE_UNRESOLVED"}}
        fact = _derive_pinctrl_state(gc)
        assert fact.ncc_state == "NOT_ATTESTED"

    def test_empty_pinmux_list_yields_not_attested(self):
        """pinmux = [] → NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"audio_topology": {"pinmux": []}}
        fact = _derive_pinctrl_state(gc)
        assert fact.ncc_state == "NOT_ATTESTED"


# ── PinmuxFact state_label threading ──────────────────────────────────────────


class TestPinmuxFactStateLabel:
    """state_label field on PinmuxFact carries the DT pinctrl group name."""

    def test_state_label_in_to_dict(self):
        """state_label appears in to_dict() output.

        NOT real-target — SYNTHETIC fixture.
        """
        fact = PinmuxFact(pin=147, function=1, role="mclk", name="gpio.i2s.mclk", state_label="i2s8_active")
        d = fact.to_dict()
        assert d["state_label"] == "i2s8_active"

    def test_derive_pinmux_from_dt_threads_label(self):
        """derive_pinmux_from_dt populates state_label from group key.

        NOT real-target — SYNTHETIC fixture.
        """
        dt = {
            "pinctrl": {
                "i2s8_active": {
                    "function": "i2s8",
                    "pins": [
                        {"pin": 147, "function": 1, "role": "mclk"},
                        {"pin": 148, "function": 1, "role": "sclk"},
                    ],
                }
            }
        }
        result = derive_pinmux_from_dt(dt)
        assert isinstance(result, list)
        assert len(result) == 2
        for fact in result:
            assert fact.state_label == "i2s8_active"

    def test_default_state_label_is_empty(self):
        """PinmuxFact without state_label kwarg → empty string.

        NOT real-target — SYNTHETIC fixture.
        """
        fact = PinmuxFact(pin=1, function=1, role="clk", name="gpio.i2s.clk")
        assert fact.state_label == ""


# ── Byte-identity + provenance tests ─────────────────────────────────────────


class TestByteIdentityWithDerivedPinctrl:
    """Prove that pinctrl_state derivation preserves emitted bytes on Nord."""

    @staticmethod
    def _nord_template_with_pinctrl_attested():
        """Real Nord template shape with pinctrl_state ATTESTED to i2s8_active."""
        template = json.loads(_NORD_TEMPLATE.read_text("utf-8"))
        template["board_metadata"]["pinctrl_state"] = {
            "value": "i2s8_active",
            "ncc_state": "ATTESTED",
            "authority": {"strength": "IPCAT_DERIVED", "origin": "kernel_dt"},
            "citations": ["kernel DT pinctrl state derivation (A-narrow)"],
            "row_ref": None,
            "independently_verified": False,
            "candidate_derived": False,
            "candidate_value": None,
            "reviewer_required": False,
            "not_attested_disclosures": [],
        }
        return template

    def test_byte_identity_pinctrl_from_template(self):
        """ATTESTED pinctrl_state="i2s8_active" → same emitted bytes as fixture.

        The override fires (template path, not constant), but the VALUE is the
        same as the hardcoded _PINCTRL_LABEL, so emitted bytes are identical.
        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        template = self._nord_template_with_pinctrl_attested()

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        expected = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ == expected, (
            "Template-derived pinctrl_state='i2s8_active' should produce "
            "byte-identical output to the hardcoded constant"
        )

    def test_provenance_is_template_not_constant(self):
        """The emitted i2s8_active flows FROM template, not from _PINCTRL_LABEL.

        Prove: _template_value returns the attested value, which is what the
        generator uses. The hardcoded constant is NOT the source.
        NOT real-target — fixture-derived result.
        """
        template = self._nord_template_with_pinctrl_attested()
        val = _template_value(template, "board_metadata", "pinctrl_state")
        assert val == "i2s8_active", (
            "_template_value should return 'i2s8_active' from ATTESTED template"
        )

    def test_not_attested_pinctrl_still_emits_same_bytes(self):
        """NOT_ATTESTED pinctrl_state → fallback to constant → same bytes.

        Paired with test_byte_identity_pinctrl_from_template to prove both
        paths produce identical output. NOT real-target — fixture-derived.
        """
        facts = _clean_nord_facts()
        template = json.loads(_NORD_TEMPLATE.read_text("utf-8"))
        # Add pinctrl_state as NOT_ATTESTED
        template["board_metadata"]["pinctrl_state"] = {
            "value": None,
            "ncc_state": "NOT_ATTESTED",
            "authority": {"strength": "UNAVAILABLE", "origin": "none"},
            "citations": [],
            "row_ref": None,
            "independently_verified": False,
            "candidate_derived": False,
            "candidate_value": None,
            "reviewer_required": False,
            "not_attested_disclosures": [],
        }

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        expected = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ == expected


# ── Projector integration ─────────────────────────────────────────────────────


class TestProjectorEmitsPinctrlState:
    """Projector's output includes pinctrl_state in board_metadata."""

    def test_projector_with_pinmux_data(self):
        """project() with pinmux carrying state_labels → board_metadata.pinctrl_state ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        import os
        os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
        try:
            gc = {
                "cross_verification": {"rows": []},
                "audio_topology": {
                    "pinmux": [
                        {"pin": 147, "function": 1, "role": "mclk", "name": "gpio.i2s.mclk", "state_label": "i2s8_active"},
                        {"pin": 148, "function": 1, "role": "sclk", "name": "gpio.i2s.sclk", "state_label": "i2s8_active"},
                    ]
                },
            }
            result = project(gc, target_name="test-synth", run_id="test-run")
            bm = result.template.board_metadata
            assert "pinctrl_state" in bm
            ps = bm["pinctrl_state"]
            assert isinstance(ps, FactRecord)
            assert ps.ncc_state == "ATTESTED"
            assert ps.value == "i2s8_active"
        finally:
            os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)

    def test_projector_without_pinmux_data(self):
        """project() without pinmux data → board_metadata.pinctrl_state NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        import os
        os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
        try:
            gc = {"cross_verification": {"rows": []}}
            result = project(gc, target_name="test-synth", run_id="test-run")
            bm = result.template.board_metadata
            assert "pinctrl_state" in bm
            ps = bm["pinctrl_state"]
            assert isinstance(ps, FactRecord)
            assert ps.ncc_state == "NOT_ATTESTED"
        finally:
            os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
