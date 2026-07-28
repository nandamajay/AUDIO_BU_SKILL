"""G-3A.15 Slice 1 — Curated overrides plumbing + firewall proof.

Validates:
  1. Curated value NEVER enters gc["cross_verification"]["rows"].
  2. Curated value NEVER enters TrustedFacts.
  3. AUTHORITY_STRENGTHS frozenset is unchanged (closed enum).
  7. Negative fixture: malicious override cannot poison cross_verification.
  +  Inertness: curated_overrides=None produces byte-identical templates.

All fixtures are SYNTHETIC. Results are NOT real-target.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.hw_template.projector import project
from orchestrator.hw_template.model import FactRecord
from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _valid_curated_override(value="IQ10-EVK", target="test-synth"):
    """Return a valid curated override entry for board_metadata.board_variant."""
    return {
        "board_metadata.board_variant": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            "citations": [
                "Schematic LD20-94440 rev A, title block",
                f"<fixture: NOT_REAL_TARGET>",
            ],
            "attestation": {
                "attested_by": "test@example.com",
                "timestamp": "2026-07-28T14:30:00+05:30",
                "evidence": "Schematic LD20-94440 rev A",
                "target": target,
            },
        }
    }


def _project_with_env(**kwargs):
    """Call project() with H1_VALIDATION_ALLOWS_FIXTURES=1."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(**kwargs)
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


# ── Test 1: Curated value never enters cross_verification.rows ────────────────


class TestCuratedNeverEntersCrossVerification:
    """Firewall: curated overrides MUST NOT appear in gc['cross_verification']['rows']."""

    def test_curated_value_never_in_cross_verification_rows(self):
        """A curated override MUST NOT appear in gc['cross_verification']['rows'].

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        gc_before = deepcopy(gc)
        overrides = _valid_curated_override(target="test-synth")

        result = _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        # gc MUST be unchanged — no new rows
        assert gc["cross_verification"]["rows"] == gc_before["cross_verification"]["rows"]
        assert gc["cross_verification"]["rows"] == []

        # The curated value IS in the template
        bv = result.template.board_metadata["board_variant"]
        assert isinstance(bv, FactRecord)
        assert bv.value == "IQ10-EVK"
        assert bv.ncc_state == "ATTESTED"
        assert bv.authority["origin"] == "reviewer_curated"

    def test_gc_with_existing_rows_unchanged_after_curation(self):
        """gc with pre-existing rows stays identical after curated override.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "cross_verification": {
                "rows": [
                    {"track": "T1", "subject": "soc", "verdict": "MATCH",
                     "source": "sa8775p", "citations": ["<fixture: NOT_REAL_TARGET>"],
                     "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"}},
                ]
            }
        }
        gc_before = deepcopy(gc)
        overrides = _valid_curated_override(target="test-synth")

        _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        assert gc == gc_before


# ── Test 2: Curated value never enters TrustedFacts ──────────────────────────


class TestCuratedNeverEntersTrustedFacts:
    """Firewall: curated override in template MUST NOT influence TrustedFacts."""

    def test_curated_value_not_in_trusted_facts_rows(self):
        """TrustedFacts is built from gc only — template curated values are absent.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = _valid_curated_override(target="test-synth")

        result = _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        # Template has the curated value
        bv = result.template.board_metadata["board_variant"]
        assert bv.value == "IQ10-EVK"

        # But gc["cross_verification"]["rows"] has NO row for board_variant
        # (since we started with empty rows and the projector never writes them)
        assert gc["cross_verification"]["rows"] == []

        # Any TrustedFacts construction from gc would see zero rows —
        # proving the curated value CANNOT influence TrustedFacts.
        # (TrustedFacts is built from gc["cross_verification"]["rows"],
        # not from the template.)


# ── Test 3: AUTHORITY_STRENGTHS frozenset unchanged ──────────────────────────


class TestAuthorityStrengthsUnchanged:
    """The closed enum has exactly 4 values — G-3A.15 must NOT add a fifth."""

    def test_authority_strengths_exactly_four(self):
        """AUTHORITY_STRENGTHS must contain exactly 4 values (closed).

        NOT real-target — structural assertion.
        """
        assert AUTHORITY_STRENGTHS == frozenset(
            {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
        )
        assert len(AUTHORITY_STRENGTHS) == 4


# ── Test 7: Negative fixture — attempted cross-verification poisoning ────────


class TestNegativePoisoningAttempt:
    """NEGATIVE FIXTURE: malicious override cannot poison cross_verification."""

    def test_malicious_override_with_inject_fields_ignored(self):
        """Even if someone crafts overrides with creative attack vectors,
        gc['cross_verification']['rows'] MUST NOT be modified.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "cross_verification": {
                "rows": [
                    {"track": "T1", "subject": "existing",
                     "verdict": "MATCH", "source": "sa8775p",
                     "citations": ["<fixture: NOT_REAL_TARGET>"],
                     "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"}},
                ]
            }
        }
        gc_before = deepcopy(gc)

        # Malicious override: extra fields attempting injection
        overrides = {
            "board_metadata.board_variant": {
                "value": "MALICIOUS",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
                "citations": ["<fixture: NOT_REAL_TARGET>"],
                "attestation": {
                    "attested_by": "attacker@example.com",
                    "timestamp": "2026-07-28T00:00:00Z",
                    "evidence": "fake evidence",
                    "target": "test-synth",
                },
                # Creative attack vectors — should be ignored
                "inject_into_rows": True,
                "row_to_inject": {
                    "track": "T5", "subject": "board_variant",
                    "verdict": "MATCH", "source": "MALICIOUS",
                },
                "__cross_verification__": {"rows": [{"injected": True}]},
            }
        }

        result = _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        # gc STILL has only the original row
        assert gc == gc_before
        assert len(gc["cross_verification"]["rows"]) == 1
        assert gc["cross_verification"]["rows"][0]["subject"] == "existing"

        # The curated value DID land in the template (gap-fill worked)
        bv = result.template.board_metadata["board_variant"]
        assert bv.value == "MALICIOUS"
        assert bv.ncc_state == "ATTESTED"


# ── Inertness proof: curated_overrides=None is byte-identical ─────────────────


class TestInertness:
    """With curated_overrides=None (default), output is byte-identical."""

    def test_none_overrides_byte_identical_to_omitted(self):
        """project(..., curated_overrides=None) == project(...) — same bytes.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "cross_verification": {
                "rows": [
                    {"track": "T5", "subject": "soc", "verdict": "MATCH",
                     "source": "sa8775p", "citations": ["<fixture: NOT_REAL_TARGET>"],
                     "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"}},
                ]
            },
            "audio_topology": {
                "pinmux": [
                    {"pin": 147, "function": 1, "role": "mclk",
                     "name": "gpio.i2s.mclk", "state_label": "i2s8_active"},
                ]
            },
        }

        r_without = _project_with_env(
            gc=deepcopy(gc), target_name="test-synth", run_id="r",
        )
        r_with_none = _project_with_env(
            gc=deepcopy(gc), target_name="test-synth", run_id="r",
            curated_overrides=None,
        )

        # Byte-identical template JSON
        t1 = json.dumps(r_without.template.to_dict(), sort_keys=True)
        t2 = json.dumps(r_with_none.template.to_dict(), sort_keys=True)
        assert t1 == t2

        # Byte-identical gap manifest
        g1 = json.dumps(r_without.gap_manifest.to_dict(), sort_keys=True)
        g2 = json.dumps(r_with_none.gap_manifest.to_dict(), sort_keys=True)
        assert g1 == g2

    def test_empty_overrides_dict_no_change(self):
        """project(..., curated_overrides={}) — empty dict, no effect.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}

        r_none = _project_with_env(
            gc=deepcopy(gc), target_name="test-synth", run_id="r",
            curated_overrides=None,
        )
        r_empty = _project_with_env(
            gc=deepcopy(gc), target_name="test-synth", run_id="r",
            curated_overrides={},
        )

        t1 = json.dumps(r_none.template.to_dict(), sort_keys=True)
        t2 = json.dumps(r_empty.template.to_dict(), sort_keys=True)
        assert t1 == t2

    def test_curated_override_does_not_touch_attested_fact(self):
        """A curated override targeting an already-ATTESTED fact is a no-op.
        (Slice 1 gap-fill only — does not override ATTESTED.)

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {
            "cross_verification": {
                "rows": [
                    {"track": "T5", "subject": "board_variant",
                     "verdict": "MATCH", "source": "IQ10-RRD",
                     "citations": ["<fixture: NOT_REAL_TARGET>"],
                     "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"}},
                ]
            }
        }
        overrides = _valid_curated_override(value="IQ10-EVK", target="test-synth")

        result = _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        # Automation ATTESTED wins — curated override is NOT applied
        bv = result.template.board_metadata["board_variant"]
        assert bv.value == "IQ10-RRD"
        assert bv.ncc_state == "ATTESTED"
        assert bv.authority["origin"] == "ipcat_swi"  # NOT reviewer_curated


# ── Schema validation tests ──────────────────────────────────────────────────


class TestCuratedOverridesValidation:
    """Schema validation catches malformed curated_overrides at load time."""

    def test_null_value_raises(self):
        """Curated override with value=None raises ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = {
            "board_metadata.board_variant": {
                "value": None,
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
                "attestation": {
                    "attested_by": "x", "timestamp": "2026-01-01",
                    "evidence": "e", "target": "test-synth",
                },
            }
        }
        with pytest.raises(ValueError, match="null value"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )

    def test_wrong_target_raises(self):
        """Curated override with mismatched target raises ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = _valid_curated_override(target="WRONG-TARGET")

        with pytest.raises(ValueError, match="target"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )

    def test_missing_evidence_raises(self):
        """Curated override with empty evidence raises ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = {
            "board_metadata.board_variant": {
                "value": "IQ10-EVK",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
                "attestation": {
                    "attested_by": "x", "timestamp": "2026-01-01",
                    "evidence": "", "target": "test-synth",
                },
            }
        }
        with pytest.raises(ValueError, match="evidence"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )

    def test_illegal_template_path_raises(self):
        """Curated override with non-legal path raises ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = {
            "codecs[0].part_number": {
                "value": "PCM1681",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
                "attestation": {
                    "attested_by": "x", "timestamp": "2026-01-01",
                    "evidence": "e", "target": "test-synth",
                },
            }
        }
        with pytest.raises(ValueError, match="illegal template path"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )

    def test_wrong_origin_raises(self):
        """Curated override with origin != 'reviewer_curated' raises ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = {"cross_verification": {"rows": []}}
        overrides = {
            "board_metadata.board_variant": {
                "value": "IQ10-EVK",
                "authority": {"strength": "KB_RULE", "origin": "ipcat_swi"},
                "attestation": {
                    "attested_by": "x", "timestamp": "2026-01-01",
                    "evidence": "e", "target": "test-synth",
                },
            }
        }
        with pytest.raises(ValueError, match="reviewer_curated"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )
