"""G-3A.15 Slice 2 — board_variant as first curated consumer (WP-69).

Validates:
  6. GAP-FILL: curated "IQ10-EVK" emits model = "IQ10-EVK" in DTSI.
  9. Missing curation → silent NOT_ATTESTED (FIXME literal, no error).
 10. Malformed curation → loud ValueError at projector validation.
 11. ONLY the model line changes — no other bytes move.
 12. contributes_rows carries origin = reviewer_curated (visual tag).

All fixtures are SYNTHETIC. Results are NOT real-target.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.hw_template.projector import project
from orchestrator.generation.machine_driver import (
    generate_machine_driver,
    _MODEL_FIXME_LITERAL,
)
from orchestrator.generation.model import GeneratedArtifact

# Reuse the clean Nord facts helper from Phase A tests
from tests.test_generation_source_probe import _clean_nord_facts


# ── Helpers ──────────────────────────────────────────────────────────────────

def _project_with_env(**kwargs):
    """Call project() with H1_VALIDATION_ALLOWS_FIXTURES=1."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(**kwargs)
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


def _board_variant_curated_template(value="IQ10-EVK"):
    """Build a template dict with curated board_variant (reviewer_curated origin)."""
    return {
        "board_metadata": {
            "board_variant": {
                "value": value,
                "ncc_state": "ATTESTED",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            },
        }
    }


def _not_attested_template():
    """Build a template dict with NOT_ATTESTED board_variant (no curation)."""
    return {
        "board_metadata": {
            "board_variant": {
                "value": None,
                "ncc_state": "NOT_ATTESTED",
                "authority": {"strength": "UNAVAILABLE", "origin": "none"},
            },
        }
    }


def _gc_with_open_gates():
    """Minimal gc that opens machine_driver gates (T5 soc MATCH row).

    NOT real-target — SYNTHETIC fixture.
    """
    return {
        "cross_verification": {
            "rows": [
                {
                    "track": "T5",
                    "subject": "soc",
                    "verdict": "MATCH",
                    "source": "sa8775p",
                    "citations": ["<fixture: NOT_REAL_TARGET>"],
                    "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"},
                },
            ]
        }
    }


# ── Test 6: GAP-FILL — curated board_variant emits in model line ─────────────


class TestGapFillBoardVariantEmits:
    """GAP-FILL: curated 'IQ10-EVK' produces model = 'IQ10-EVK' in DTSI."""

    def test_curated_board_variant_appears_in_model_line(self):
        """Curated board_variant fills NOT_ATTESTED slot → model line updated.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = _board_variant_curated_template("IQ10-EVK")

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert 'model = "IQ10-EVK"' in output
        assert _MODEL_FIXME_LITERAL not in output

    def test_curated_board_variant_different_value(self):
        """Different curated value → different model line.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = _board_variant_curated_template("IQ10-RRD-REV-A")

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert 'model = "IQ10-RRD-REV-A"' in output

    def test_end_to_end_projector_to_generator(self):
        """Full pipeline: projector gap-fill → generator model line.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = _gc_with_open_gates()
        overrides = {
            "board_metadata.board_variant": {
                "value": "IQ10-EVK",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
                "citations": ["Schematic LD20-94440", "<fixture: NOT_REAL_TARGET>"],
                "attestation": {
                    "attested_by": "test@example.com",
                    "timestamp": "2026-07-28T00:00:00Z",
                    "evidence": "Schematic LD20-94440 rev A",
                    "target": "test-synth",
                },
            }
        }

        proj_result = _project_with_env(
            gc=gc, target_name="test-synth", run_id="r",
            curated_overrides=overrides,
        )

        # Template now has ATTESTED board_variant
        tpl_dict = proj_result.template.to_dict()
        bv = tpl_dict["board_metadata"]["board_variant"]
        assert bv["ncc_state"] == "ATTESTED"
        assert bv["value"] == "IQ10-EVK"
        assert bv["authority"]["origin"] == "reviewer_curated"

        # Feed to generator
        facts = _clean_nord_facts()
        gen_result = generate_machine_driver(facts, template=tpl_dict)
        assert isinstance(gen_result, GeneratedArtifact)

        output = gen_result.bytes_.decode("utf-8")
        assert 'model = "IQ10-EVK"' in output


# ── Test 9: Missing curation → silent NOT_ATTESTED ───────────────────────────


class TestMissingCurationSilent:
    """No curation → FIXME literal emitted (no error, no crash)."""

    def test_no_template_emits_fixme(self):
        """template=None → model line is FIXME literal.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()

        result = generate_machine_driver(facts, template=None)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert f'model = "{_MODEL_FIXME_LITERAL}"' in output

    def test_not_attested_template_emits_fixme(self):
        """Template with NOT_ATTESTED board_variant → FIXME literal.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = _not_attested_template()

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        output = result.bytes_.decode("utf-8")
        assert f'model = "{_MODEL_FIXME_LITERAL}"' in output


# ── Test 10: Malformed curation → loud ValueError ────────────────────────────


class TestMalformedCurationLoud:
    """Malformed curated_overrides raise ValueError at projector validation."""

    def test_invalid_strength_raises(self):
        """Strength not in AUTHORITY_STRENGTHS → ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = _gc_with_open_gates()
        overrides = {
            "board_metadata.board_variant": {
                "value": "IQ10-EVK",
                "authority": {"strength": "INVENTED_STRENGTH", "origin": "reviewer_curated"},
                "attestation": {
                    "attested_by": "x", "timestamp": "2026-01-01",
                    "evidence": "e", "target": "test-synth",
                },
            }
        }
        with pytest.raises(ValueError, match="illegal authority.strength"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )

    def test_missing_attestation_raises(self):
        """Missing attestation dict → ValueError.

        NOT real-target — SYNTHETIC fixture.
        """
        gc = _gc_with_open_gates()
        overrides = {
            "board_metadata.board_variant": {
                "value": "IQ10-EVK",
                "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            }
        }
        with pytest.raises(ValueError, match="attestation"):
            _project_with_env(
                gc=gc, target_name="test-synth", run_id="r",
                curated_overrides=overrides,
            )


# ── Test 11: ONLY the model line changes — no other bytes move ───────────────


class TestOnlyModelLineChanges:
    """Curated board_variant changes ONLY the model line — no other bytes."""

    def test_only_model_line_differs(self):
        """Comparing curated vs FIXME output: exactly ONE line differs.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()

        # Baseline: no template → FIXME literal
        baseline_result = generate_machine_driver(facts, template=None)
        assert isinstance(baseline_result, GeneratedArtifact)
        baseline_lines = baseline_result.bytes_.decode("utf-8").splitlines()

        # Curated: IQ10-EVK
        curated_result = generate_machine_driver(
            facts, template=_board_variant_curated_template("IQ10-EVK")
        )
        assert isinstance(curated_result, GeneratedArtifact)
        curated_lines = curated_result.bytes_.decode("utf-8").splitlines()

        # Same number of lines
        assert len(baseline_lines) == len(curated_lines)

        # Find differing lines
        diffs = [
            (i, bl, cl)
            for i, (bl, cl) in enumerate(zip(baseline_lines, curated_lines))
            if bl != cl
        ]

        # Exactly ONE line differs
        assert len(diffs) == 1, (
            f"Expected exactly 1 differing line, got {len(diffs)}: {diffs}"
        )

        line_idx, baseline_line, curated_line = diffs[0]

        # The differing line IS the model line
        assert "model =" in baseline_line
        assert "model =" in curated_line
        assert _MODEL_FIXME_LITERAL in baseline_line
        assert "IQ10-EVK" in curated_line


# ── Test 12: contributes_rows carries origin = reviewer_curated ──────────────


class TestContributesRowsCarriesOrigin:
    """Contributes_rows visually tags reviewer_curated provenance."""

    def test_curated_contributes_row_has_reviewer_curated(self):
        """When model comes from curation, contributes_row notes say so.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = _board_variant_curated_template("IQ10-EVK")

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        # Find the board_variant contributes_row
        bv_rows = [
            r for r in result.contributes_rows
            if "board_variant" in r.subject
        ]
        assert len(bv_rows) == 1
        bv_row = bv_rows[0]

        # Notes mention reviewer_curated
        notes_text = " ".join(bv_row.notes)
        assert "reviewer_curated" in notes_text
        assert "HUMAN-ATTESTED" in notes_text

    def test_fixme_contributes_row_does_not_say_reviewer_curated(self):
        """When model is FIXME (no curation), notes say NOT_ATTESTED.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()

        result = generate_machine_driver(facts, template=None)
        assert isinstance(result, GeneratedArtifact)

        bv_rows = [
            r for r in result.contributes_rows
            if "board_variant" in r.subject
        ]
        assert len(bv_rows) == 1
        bv_row = bv_rows[0]

        notes_text = " ".join(bv_row.notes)
        assert "reviewer_curated" not in notes_text
        assert "NOT_ATTESTED" in notes_text

    def test_automation_contributes_row_shows_automation_origin(self):
        """When model comes from automation (not curation), notes say so.

        NOT real-target — SYNTHETIC fixture.
        """
        facts = _clean_nord_facts()
        template = {
            "board_metadata": {
                "board_variant": {
                    "value": "AUTOMATION-DERIVED",
                    "ncc_state": "ATTESTED",
                    "authority": {"strength": "IPCAT_DIRECT", "origin": "ipcat_swi"},
                },
            }
        }

        result = generate_machine_driver(facts, template=template)
        assert isinstance(result, GeneratedArtifact)

        bv_rows = [
            r for r in result.contributes_rows
            if "board_variant" in r.subject
        ]
        assert len(bv_rows) == 1
        bv_row = bv_rows[0]

        notes_text = " ".join(bv_row.notes)
        assert "ipcat_swi" in notes_text
        assert "reviewer_curated" not in notes_text
        assert "automation" in notes_text
