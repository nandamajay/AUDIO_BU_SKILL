"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 2 — curated allowlist + path grammar.

Step 2 extends the G-3A.15 curated-override envelope so it can capture the six
schematic-attested leaves added (inert) in step 1:

  * three flat board leaves: board_metadata.mclk / .global_md_oe / .scmi_index
  * three per-codec leaves addressed IDENTITY-KEYED as
    codecs.<key>.i2c_bus_label / .i2c_address / .reset_gpios
    (e.g. codecs.adau1979.i2c_address) — NOT positional codecs[0]

and accepts origin="schematic" (an ORIGIN string only; authority strength stays
the closed 4-member AUTHORITY_STRENGTHS set).

Everything else is unchanged from step 1: still GAP-FILL-ONLY (NOT_ATTESTED
leaves only; never overwrites an attested value), still DISCLOSURE-ONLY (nothing
here reaches cross_verification / TrustedFacts / any gate), and no live wiring
(step 3) and no consumer (step 4). Byte-identity on Nord is unaffected because
no curated file is loaded yet — that is proven structurally here (an absent
override leaves every schematic leaf NOT_ATTESTED / value=null).

All fixtures are SYNTHETIC. Results are NOT real-target.

Run: ``PYTHONPATH=.:audio_bu_skill python -m pytest \
    audio_bu_skill/tests/test_schematic_curated_paths_step2.py -q``
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.hw_template.model import FactRecord
from orchestrator.hw_template.projector import project
from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS


# ── fixtures ──────────────────────────────────────────────────────────────────


def _gc_two_codecs() -> dict:
    """gc seeding two candidate-only codecs (adau1979 primary, pcm1681 secondary).

    No authoritative rows: every schematic leaf lands NOT_ATTESTED / value=null,
    and each codec's part_number identity is candidate-derived (mirrors real
    Nord). ``_codec_identity`` therefore resolves ``codecs.adau1979.*`` to the
    first entry and ``codecs.pcm1681.*`` to the second.
    """
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


def _project(gc: dict, overrides: dict | None = None, target: str = "synth-t"):
    """Call project() with fixture citations allowed (SYNTHETIC gc)."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(
            gc=gc, target_name=target, run_id="step2-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


def _codec_schematic_override(
    codec_key: str,
    field: str,
    value,
    *,
    origin: str = "schematic",
    evidence: str = "Schematic LD20-94440 rev A, audio sheet",
    target: str = "synth-t",
) -> dict:
    """A single identity-keyed codec schematic override entry."""
    return {
        f"codecs.{codec_key}.{field}": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": origin},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": evidence,
                "target": target,
            },
        }
    }


def _board_schematic_override(
    field: str,
    value,
    *,
    origin: str = "schematic",
    evidence: str = "Schematic LD20-94440 rev A, clock sheet",
    target: str = "synth-t",
) -> dict:
    return {
        f"board_metadata.{field}": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": origin},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": evidence,
                "target": target,
            },
        }
    }


# ── 1. identity-keyed path resolves to the correct codec entry ────────────────


def test_identity_keyed_path_resolves_correct_codec():
    """codecs.pcm1681.i2c_address fills ONLY the pcm1681 entry, not adau1979."""
    overrides = _codec_schematic_override("pcm1681", "i2c_address", "0x4c")
    result = _project(_gc_two_codecs(), overrides)

    codecs = result.template.codecs
    by_id = {}
    for c in codecs:
        pn = c["part_number"]
        by_id[pn.value if pn.value is not None else pn.candidate_value] = c

    filled = by_id["pcm1681"]["i2c_address"]
    assert filled.value == "0x4c"
    assert filled.ncc_state == "ATTESTED"
    assert filled.authority["origin"] == "schematic"

    # The other codec's same slot is untouched — NOT_ATTESTED / value=null.
    untouched = by_id["adau1979"]["i2c_address"]
    assert untouched.value is None
    assert untouched.ncc_state == "NOT_ATTESTED"


def test_all_three_board_schematic_leaves_are_allowlisted():
    """The three flat board schematic leaves fill correctly with origin=schematic."""
    overrides = {}
    overrides.update(_board_schematic_override("mclk", "MCLK 24.576MHz"))
    overrides.update(_board_schematic_override("global_md_oe", "gpio120"))
    overrides.update(_board_schematic_override("scmi_index", "7"))
    result = _project(_gc_two_codecs(), overrides)

    bm = result.template.board_metadata
    for field, val in (
        ("mclk", "MCLK 24.576MHz"),
        ("global_md_oe", "gpio120"),
        ("scmi_index", "7"),
    ):
        leaf = bm[field]
        assert leaf.value == val, field
        assert leaf.ncc_state == "ATTESTED", field
        assert leaf.authority["origin"] == "schematic", field


# ── 2. unknown codec key -> loud error (not a silent no-op) ───────────────────


def test_unknown_codec_key_raises_loudly():
    """codecs.<absent-key>.field raises ValueError — never silently skipped."""
    overrides = _codec_schematic_override("wm8960", "i2c_address", "0x1a")
    with pytest.raises(ValueError, match="codec identity 'wm8960' not found"):
        _project(_gc_two_codecs(), overrides)


# ── 3. non-allowlisted path still rejected ────────────────────────────────────


def test_positional_codec_path_rejected():
    """Positional codecs[0].* is NOT the identity-keyed grammar — rejected."""
    overrides = {
        "codecs[0].i2c_address": {
            "value": "0x31",
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "attestation": {
                "attested_by": "x", "timestamp": "2026-01-01",
                "evidence": "e", "target": "synth-t",
            },
        }
    }
    with pytest.raises(ValueError, match="illegal template path"):
        _project(_gc_two_codecs(), overrides)


def test_non_schematic_codec_field_rejected():
    """codecs.<key>.part_number is NOT a schematic leaf — rejected."""
    overrides = _codec_schematic_override("adau1979", "part_number", "adau1979")
    # rebuild under the illegal field name
    overrides = {
        "codecs.adau1979.part_number": next(iter(overrides.values()))
    }
    with pytest.raises(ValueError, match="illegal template path"):
        _project(_gc_two_codecs(), overrides)


def test_unknown_board_field_rejected():
    """board_metadata.<not-a-leaf> stays rejected."""
    overrides = _board_schematic_override("bogus_field", "x")
    with pytest.raises(ValueError, match="illegal template path"):
        _project(_gc_two_codecs(), overrides)


# ── 4. origin=schematic accepted; candidate leaf still cannot be promoted ─────


def test_schematic_origin_accepted():
    """origin='schematic' passes validation (reviewer_curated still works too)."""
    ov_schematic = _codec_schematic_override(
        "adau1979", "i2c_bus_label", "&i2c18", origin="schematic"
    )
    r1 = _project(_gc_two_codecs(), ov_schematic)
    c = next(
        x for x in r1.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "adau1979"
    )
    assert c["i2c_bus_label"].authority["origin"] == "schematic"

    ov_reviewer = _codec_schematic_override(
        "adau1979", "i2c_bus_label", "&i2c18", origin="reviewer_curated"
    )
    r2 = _project(_gc_two_codecs(), ov_reviewer)
    c2 = next(
        x for x in r2.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "adau1979"
    )
    assert c2["i2c_bus_label"].authority["origin"] == "reviewer_curated"


def test_illegal_origin_still_rejected():
    """An origin outside {reviewer_curated, schematic} is rejected."""
    overrides = _codec_schematic_override(
        "adau1979", "i2c_address", "0x31", origin="ipcat_swi"
    )
    with pytest.raises(ValueError, match="authority.origin must be one of"):
        _project(_gc_two_codecs(), overrides)


def test_candidate_derived_leaf_cannot_be_promoted():
    """A candidate_derived NOT_ATTESTED leaf is never overwritten by a curated
    override — the model.py:138 firewall would reject the promotion anyway, and
    the apply guard refuses it earlier and explicitly.

    part_number on each codec is NOT_ATTESTED **and** candidate_derived=True.
    Even if part_number were on the allowlist (it is not — see
    test_non_schematic_codec_field_rejected), the candidate guard would still
    block it. Here we prove the guard directly by driving _apply_curated_overrides
    against a candidate leaf on an allowlisted-shaped path.
    """
    from orchestrator.hw_template.projector import _apply_curated_overrides

    result = _project(_gc_two_codecs())
    tmpl = result.template
    adau = next(
        c for c in tmpl.codecs
        if (c["part_number"].value or c["part_number"].candidate_value) == "adau1979"
    )
    # Sanity: part_number is the candidate-derived leaf we must never promote.
    assert adau["part_number"].candidate_derived is True
    assert adau["part_number"].ncc_state == "NOT_ATTESTED"

    # Point an override at the candidate leaf (bypassing validation, which would
    # reject the path) and confirm apply leaves it candidate-derived, unpromoted.
    _apply_curated_overrides(
        tmpl,
        {
            "codecs.adau1979.part_number": {
                "value": "PROMOTED",
                "authority": {"strength": "KB_RULE", "origin": "schematic"},
            }
        },
    )
    assert adau["part_number"].value is None
    assert adau["part_number"].candidate_derived is True
    assert adau["part_number"].ncc_state == "NOT_ATTESTED"


# ── 5. schematic override on NOT_ATTESTED leaf -> ATTESTED + needs citation ───


def test_schematic_override_fills_not_attested_leaf():
    """A schematic override gap-fills a NOT_ATTESTED codec leaf to ATTESTED."""
    overrides = _codec_schematic_override("adau1979", "i2c_address", "0x31")
    result = _project(_gc_two_codecs(), overrides)
    c = next(
        x for x in result.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "adau1979"
    )
    leaf = c["i2c_address"]
    assert leaf.value == "0x31"
    assert leaf.ncc_state == "ATTESTED"
    assert leaf.authority["origin"] == "schematic"
    assert leaf.candidate_derived is False


def test_missing_sheet_citation_raises():
    """A schematic override with empty attestation.evidence raises ValueError.

    The sheet reference IS the evidence — a schematic value with no sheet is not
    schematic-attested.
    """
    overrides = _codec_schematic_override(
        "adau1979", "i2c_address", "0x31", evidence=""
    )
    with pytest.raises(ValueError, match="evidence"):
        _project(_gc_two_codecs(), overrides)


def test_schematic_override_does_not_touch_attested_codec_leaf():
    """Gap-fill only: a schematic override never overwrites an ATTESTED leaf.

    We attest a codec i2c_address via a synthetic T2 row, then confirm a curated
    schematic override for the same slot is a no-op.
    """
    gc = _gc_two_codecs()
    # NOTE: there is no automated authority for i2c_address today, so to exercise
    # the "don't clobber attested" branch we assert it at the FactRecord level by
    # projecting, manually attesting the leaf, then applying the override.
    from orchestrator.hw_template.projector import _apply_curated_overrides

    result = _project(gc)
    tmpl = result.template
    adau = next(
        c for c in tmpl.codecs
        if (c["part_number"].value or c["part_number"].candidate_value) == "adau1979"
    )
    adau["i2c_address"] = FactRecord(
        value="0xAA",
        authority={"strength": "KB_RULE", "origin": "reviewer_curated"},
        citations=[],
        row_ref=None,
        independently_verified=False,
        candidate_derived=False,
        candidate_value=None,
        reviewer_required=False,
        ncc_state="ATTESTED",
    )
    _apply_curated_overrides(
        tmpl,
        _codec_schematic_override("adau1979", "i2c_address", "0x31"),
    )
    # Attested value survives — override ignored.
    assert adau["i2c_address"].value == "0xAA"
    assert adau["i2c_address"].authority["origin"] == "reviewer_curated"


# ── 6. firewall: overridden value never enters cross_verification/TrustedFacts ─


def test_schematic_override_never_enters_cross_verification():
    """A schematic override MUST NOT mutate gc['cross_verification']['rows']."""
    gc = _gc_two_codecs()
    gc_before = deepcopy(gc)
    overrides = _codec_schematic_override("pcm1681", "reset_gpios", "gpio77")

    result = _project(gc, overrides)

    assert gc["cross_verification"]["rows"] == gc_before["cross_verification"]["rows"]
    assert gc["cross_verification"]["rows"] == []
    # value landed in template only
    c = next(
        x for x in result.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "pcm1681"
    )
    assert c["reset_gpios"].value == "gpio77"


# ── 7. byte-identity on Nord (structural: no curated file loaded) ─────────────


def test_absent_override_leaves_all_schematic_leaves_not_attested():
    """With no curated_overrides, every schematic leaf stays NOT_ATTESTED/null.

    This is the byte-identity guarantee: value=null ⟹ every consumer's
    _template_value returns None ⟹ hardcoded fallbacks fire unchanged. No live
    wiring exists yet, so a real Nord run loads no curated file.
    """
    result = _project(_gc_two_codecs())
    bm = result.template.board_metadata
    for field in ("mclk", "global_md_oe", "scmi_index"):
        assert bm[field].value is None
        assert bm[field].ncc_state == "NOT_ATTESTED"
    for c in result.template.codecs:
        for field in ("i2c_bus_label", "i2c_address", "reset_gpios"):
            assert c[field].value is None
            assert c[field].ncc_state == "NOT_ATTESTED"


def test_none_and_empty_override_byte_identical():
    """curated_overrides=None and ={} produce byte-identical output."""
    r_none = _project(_gc_two_codecs(), None)
    r_empty = _project(_gc_two_codecs(), {})
    t1 = json.dumps(r_none.template.to_dict(), sort_keys=True)
    t2 = json.dumps(r_empty.template.to_dict(), sort_keys=True)
    assert t1 == t2
    g1 = json.dumps(r_none.gap_manifest.to_dict(), sort_keys=True)
    g2 = json.dumps(r_empty.gap_manifest.to_dict(), sort_keys=True)
    assert g1 == g2


# ── 8. authority strength enum stays closed (4 members) ───────────────────────


def test_authority_strengths_unchanged_closed_set():
    """origin='schematic' is an ORIGIN, not a strength — the strength enum is
    still exactly the closed 4-member set."""
    assert AUTHORITY_STRENGTHS == frozenset(
        {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
    )
    assert len(AUTHORITY_STRENGTHS) == 4
