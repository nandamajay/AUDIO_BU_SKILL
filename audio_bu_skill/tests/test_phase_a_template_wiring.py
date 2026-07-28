"""Phase A — H-1 template wiring + soc_family provenance tests.

Validates:
  1. Three-tier provenance cascade (CURATED > DONOR_DERIVED > RESOLUTION_FAILED)
  2. Byte-identity preserved when template is NOT_ATTESTED (Nord)
  3. Byte-identity preserved when template is None (backward compat)
  4. _template_value helper returns attested values only
  5. hint_provenance flows through to gc["generation"]["source_resolution"]
  6. _T5_FAMILY_RE pattern sync between main.py import and crossverify.py

All fixtures are synthetic or fixture-derived. Results are NOT real-target.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_FIXTURES = _REPO / "tests" / "fixtures"
_RESOLVED_TREE = str(_FIXTURES / "kernel_trees" / "resolved_tree")
_NORD_TEMPLATE = _REPO / "targets" / "nord-iq10" / "h1_validation" / "audio_hardware_template.json"
_EXPECTED_DTSI = _FIXTURES / "phase2b" / "nord_machine_driver_expected.dtsi"

from orchestrator.generation.machine_driver import (
    _template_value,
    generate_machine_driver,
)
from orchestrator.generation.model import GeneratedArtifact
from orchestrator.generation.runner import _run_generation
from orchestrator.generation.soc_descriptor import (
    ResolutionMethod,
    resolve_driver_source,
)
from orchestrator.reasoning.crossverify import _T5_FAMILY_RE


def _clean_nord_facts():
    """Import the shared helper for Nord TrustedFacts fixture."""
    from tests.test_generation_source_probe import _clean_nord_facts as _inner
    return _inner()


# ── Provenance cascade tests ─────────────────────────────────────────────────


class TestProvenanceCascade:
    """Three-tier soc_family provenance (CURATED > DONOR_DERIVED > RESOLUTION_FAILED)."""

    def test_donor_derived_from_nearest_target(self):
        """nearest_target="SA8775P (lemans)" + no soc_family_hint → DONOR_DERIVED.

        NOT real-target — fixture-derived result.
        """
        nearest = "SA8775P (lemans)"
        m = _T5_FAMILY_RE.search(nearest)
        assert m is not None
        derived = m.group("fam").lower()
        assert derived == "sa8775p"

        desc = resolve_driver_source(
            _RESOLVED_TREE, derived, hint_provenance="DONOR_DERIVED"
        )
        assert desc.hint_provenance == "DONOR_DERIVED"
        assert desc.soc_family_hint == "sa8775p"
        assert desc.method == ResolutionMethod.DISCOVERED

    def test_curated_override(self):
        """Explicit soc_family_hint → CURATED provenance.

        NOT real-target — fixture-derived result.
        """
        desc = resolve_driver_source(
            _RESOLVED_TREE, "sa8775p", hint_provenance="CURATED"
        )
        assert desc.hint_provenance == "CURATED"
        assert desc.soc_family_hint == "sa8775p"
        assert desc.method == ResolutionMethod.DISCOVERED

    def test_resolution_failed_no_family_match(self):
        """nearest_target="unknown_chip" → regex yields None → RESOLUTION_FAILED.

        NOT real-target — fixture-derived result.
        """
        nearest = "unknown_chip_xyz"
        m = _T5_FAMILY_RE.search(nearest)
        assert m is None

        desc = resolve_driver_source(None, None, hint_provenance=None)
        assert desc.hint_provenance is None
        assert desc.method == ResolutionMethod.RESOLUTION_FAILED

    def test_hint_provenance_in_to_dict(self):
        """hint_provenance is serialized in to_dict() output.

        NOT real-target — fixture-derived result.
        """
        desc = resolve_driver_source(
            _RESOLVED_TREE, "sa8775p", hint_provenance="DONOR_DERIVED"
        )
        d = desc.to_dict()
        assert d["hint_provenance"] == "DONOR_DERIVED"


# ── Byte-identity tests ──────────────────────────────────────────────────────


class TestByteIdentity:
    """Template wiring must not change emitted bytes for Nord."""

    def test_byte_identity_with_nord_template(self):
        """Nord template (mostly NOT_ATTESTED) → same bytes as fixture.

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        template = json.loads(_NORD_TEMPLATE.read_text("utf-8"))

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        expected = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ == expected, (
            "Template-driven output diverges from expected fixture bytes"
        )

    def test_byte_identity_no_template(self):
        """template=None (backward compat) → same bytes as fixture.

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()

        result = generate_machine_driver(facts, template=None)
        assert isinstance(result, GeneratedArtifact)

        expected = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ == expected

    def test_byte_identity_template_vs_no_template(self):
        """Template (NOT_ATTESTED) and no template produce identical bytes.

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        template = json.loads(_NORD_TEMPLATE.read_text("utf-8"))

        r_with = generate_machine_driver(facts, template=template)
        r_without = generate_machine_driver(facts, template=None)

        assert isinstance(r_with, GeneratedArtifact)
        assert isinstance(r_without, GeneratedArtifact)
        assert r_with.bytes_ == r_without.bytes_


# ── Template override effectiveness tests ─────────────────────────────────────


class TestTemplateOverrideEffective:
    """Prove template values OVERRIDE hardcoded constants when ATTESTED.

    Distinguishes "wired and effective" from "wired but inert".
    """

    @staticmethod
    def _attested_template():
        """Synthetic template with ATTESTED board_variant and pinctrl_state."""
        return {
            "board_metadata": {
                "board_variant": {
                    "value": "SYNTH-EVK-2.0",
                    "ncc_state": "ATTESTED",
                    "authority": {"strength": "MODERATE", "origin": "synthetic-test"},
                },
                "pinctrl_state": {
                    "value": "i2s3_active",
                    "ncc_state": "ATTESTED",
                    "authority": {"strength": "MODERATE", "origin": "synthetic-test"},
                },
            }
        }

    def test_attested_model_overrides_fixme_literal(self):
        """ATTESTED board_variant → emitted model= differs from hardcoded FIXME.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = self._attested_template()

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        # Template value present in output
        assert 'model = "SYNTH-EVK-2.0"' in output
        # Hardcoded FIXME absent
        assert "FIXME(board_variant): NOT_ATTESTED" not in output

    def test_attested_pinctrl_overrides_hardcoded_label(self):
        """ATTESTED pinctrl_state → emitted pinctrl-0 uses template value.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = self._attested_template()

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        # Template value present
        assert "<&i2s3_active>" in output
        # Hardcoded i2s8_active absent from pinctrl-0 line
        assert "pinctrl-0 = <&i2s8_active>" not in output

    def test_attested_template_differs_from_fixture(self):
        """ATTESTED template produces DIFFERENT bytes than the Nord fixture.

        Proves template override is EFFECTIVE — not inert.
        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = self._attested_template()

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        expected_fixture = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ != expected_fixture, (
            "ATTESTED template should produce DIFFERENT bytes than the "
            "hardcoded-constant fixture — override is not effective"
        )

    def test_not_attested_falls_back_to_constant(self):
        """NOT_ATTESTED board_variant → falls back to hardcoded FIXME literal.

        Paired with test_attested_model_overrides_fixme_literal to prove
        both paths work. NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = {
            "board_metadata": {
                "board_variant": {
                    "value": None,
                    "ncc_state": "NOT_ATTESTED",
                    "authority": {"strength": "UNAVAILABLE", "origin": "none"},
                },
                "pinctrl_state": {
                    "value": None,
                    "ncc_state": "NOT_ATTESTED",
                    "authority": {"strength": "UNAVAILABLE", "origin": "none"},
                },
            }
        }

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        # Falls back to fixture (byte-identity)
        expected_fixture = _EXPECTED_DTSI.read_bytes()
        assert result.bytes_ == expected_fixture


# ── _template_value helper tests ─────────────────────────────────────────────


class TestTemplateValueHelper:
    """Unit tests for _template_value accessor."""

    def test_returns_attested_value(self):
        """ATTESTED leaf → returns value."""
        template = {
            "board_metadata": {
                "board_variant": {
                    "value": "EVK-1.0",
                    "ncc_state": "ATTESTED",
                    "authority": {"strength": "MODERATE", "origin": "test"},
                }
            }
        }
        assert _template_value(template, "board_metadata", "board_variant") == "EVK-1.0"

    def test_returns_none_for_not_attested(self):
        """NOT_ATTESTED leaf → returns None."""
        template = {
            "board_metadata": {
                "board_variant": {
                    "value": None,
                    "ncc_state": "NOT_ATTESTED",
                    "authority": {"strength": "UNAVAILABLE", "origin": "none"},
                }
            }
        }
        assert _template_value(template, "board_metadata", "board_variant") is None

    def test_returns_none_for_candidate_derived(self):
        """candidate_derived value (ncc_state=NOT_ATTESTED, value=None) → None."""
        template = {
            "board_metadata": {
                "soc": {
                    "value": None,
                    "ncc_state": "NOT_ATTESTED",
                    "candidate_derived": True,
                    "candidate_value": "SA8797P",
                    "authority": {"strength": "UNAVAILABLE", "origin": "none"},
                }
            }
        }
        assert _template_value(template, "board_metadata", "soc") is None

    def test_returns_none_for_ncc(self):
        """NOT_CROSS_CHECKABLE leaf → returns None."""
        template = {
            "board_metadata": {
                "soc": {
                    "value": "SA8775P",
                    "ncc_state": "NOT_CROSS_CHECKABLE",
                    "authority": {"strength": "MODERATE", "origin": "test"},
                }
            }
        }
        assert _template_value(template, "board_metadata", "soc") is None

    def test_returns_none_for_none_template(self):
        """template=None → returns None."""
        assert _template_value(None, "board_metadata", "soc") is None

    def test_returns_none_for_missing_path(self):
        """Missing intermediate key → returns None."""
        template = {"board_metadata": {}}
        assert _template_value(template, "board_metadata", "soc") is None


# ── Runner integration tests ─────────────────────────────────────────────────


class TestRunnerIntegration:
    """hint_provenance and template_used flow through runner output."""

    def test_hint_provenance_in_source_resolution(self):
        """hint_provenance appears in gc["generation"]["source_resolution"].

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "test"}]}}
        _run_generation(
            gc, facts,
            kernel_source=_RESOLVED_TREE,
            soc_family_hint="sa8775p",
            hint_provenance="DONOR_DERIVED",
        )
        sr = gc["generation"]["source_resolution"]
        assert sr["hint_provenance"] == "DONOR_DERIVED"

    def test_template_used_flag(self):
        """template_used is True when template is supplied.

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "test"}]}}
        template = json.loads(_NORD_TEMPLATE.read_text("utf-8"))
        _run_generation(
            gc, facts,
            kernel_source=_RESOLVED_TREE,
            soc_family_hint="sa8775p",
            hint_provenance="CURATED",
            template=template,
        )
        assert gc["generation"]["template_used"] is True

    def test_template_used_flag_false(self):
        """template_used is False when template is None.

        NOT real-target — fixture-derived result.
        """
        facts = _clean_nord_facts()
        gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "test"}]}}
        _run_generation(
            gc, facts,
            kernel_source=_RESOLVED_TREE,
            soc_family_hint="sa8775p",
            hint_provenance="CURATED",
            template=None,
        )
        assert gc["generation"]["template_used"] is False


# ── Regex sync guard ─────────────────────────────────────────────────────────


class TestRegexSync:
    """_T5_FAMILY_RE pattern stays in sync across modules."""

    def test_crossverify_regex_matches_expected_pattern(self):
        """Drift guard: the family regex covers SA/SM/QRB/SC families."""
        assert _T5_FAMILY_RE.search("SA8775P (lemans)")
        assert _T5_FAMILY_RE.search("SM8550")
        assert _T5_FAMILY_RE.search("QRB5165P")
        assert _T5_FAMILY_RE.search("SC8280")
        assert _T5_FAMILY_RE.search("SA8797P (NordAU) v2")
        assert not _T5_FAMILY_RE.search("unknown_chip")
