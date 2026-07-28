"""WP-CODEC-IDENTITY-ATTEST — guarded schematic promotion of the codec identity.

Nord's committed H-1 template carries ``part_number.value = null`` AND
``candidate_value = null`` for both codecs (the part names live only in the
refused candidate DTS 5267b2e1, which the projector does not source). Only
``role`` is populated, and only as a *candidate* ("DAC / playback path,
I2C-attached" / "ADC / capture path, I2C-attached"). So the codec identity that
``codecs.<key>.i2c_address`` keys on simply does not exist yet.

This WP adds the mechanism to attest that identity from the schematic:

  * ``part_number`` joins ``_CODEC_SCHEMATIC_FIELDS`` but is addressed
    ROLE-ANCHORED (``codecs.role:<kw>.part_number``) — it cannot key itself.
  * A GUARDED promotion (``_apply_identity_leaf``) may lift a NOT_ATTESTED
    part_number — candidate_derived or not — to ATTESTED, but ONLY through an
    explicit role-anchored override that the validator has already proven to
    carry an ``attestation.evidence`` sheet citation. NEVER auto-promoted,
    NEVER from the candidate value, NEVER without evidence.
  * Two-pass apply: identity leaves first, so a later identity-keyed
    ``codecs.<identity>.<field>`` resolves against the now-attested identity,
    regardless of dict order.

The candidate self-promotion firewall (model.py:138) stays fully intact for the
NO-override case — a candidate_derived part_number with no override cannot
promote itself.

Run:
    PYTHONPATH=.:audio_bu_skill python -m pytest \
        audio_bu_skill/tests/test_codec_identity_attest.py -q
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.hw_template.model import FactRecord
from orchestrator.hw_template.projector import (
    _CODEC_IDENTITY_KEYED_FIELDS,
    _CODEC_SCHEMATIC_FIELDS,
    load_curated_overrides,
    project,
    write_outputs,
)
from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS

_NORD_DIR = _REPO / "targets" / "nord-iq10"
_NORD_TEMPLATE = _NORD_DIR / "h1_validation" / "audio_hardware_template.json"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _auth() -> dict:
    return {"strength": "KB_RULE", "origin": "schematic"}


def _att(evidence: str) -> dict:
    return {
        "attested_by": "reviewer@example.com",
        "timestamp": "2026-07-28",
        "evidence": evidence,
        "target": "synth-t",
    }


def _nord_shaped_gc() -> dict:
    """Two codecs with NO part_number/name/model (null identity, like Nord),
    each carrying only a candidate ``role`` string."""
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"role": "DAC / playback path, I2C-attached"},
            {"role": "ADC / capture path, I2C-attached"},
        ],
    }


def _project(gc: dict, overrides: dict | None):
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(
            gc=gc, target_name="synth-t", run_id="codec-identity-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


def _codec_by_role(template, needle: str) -> dict:
    needle = needle.lower()
    for c in template.codecs:
        role = c["role"]
        text = role.value if role.value is not None else role.candidate_value
        if isinstance(text, str) and needle in text.lower():
            return c
    raise AssertionError(f"no codec matched role {needle!r}")


# ── 1. positive: identity promotes, then i2c_address resolves off it ──────────


def test_role_anchored_part_number_promotes_to_attested():
    """A role-anchored schematic override lifts a null-identity part_number to
    ATTESTED with origin=schematic and the sheet evidence persisted."""
    overrides = {
        "codecs.role:DAC.part_number": {
            "value": "adau1979", "authority": _auth(),
            "attestation": _att("LD20-94440 Sheet 53"),
        },
    }
    result = _project(_nord_shaped_gc(), overrides)
    pn = _codec_by_role(result.template, "DAC")["part_number"]

    assert pn.value == "adau1979"
    assert pn.ncc_state == "ATTESTED"
    assert pn.authority["origin"] == "schematic"
    assert pn.authority["strength"] == "KB_RULE"
    assert pn.candidate_derived is False
    assert pn.attestation["evidence"] == "LD20-94440 Sheet 53"


def test_i2c_address_resolves_against_freshly_attested_identity():
    """The chicken-and-egg is resolved by two-pass apply: part_number is
    attested first (role-anchored), then codecs.<identity>.i2c_address resolves.
    Order in the dict is deliberately identity-keyed-FIRST to prove pass
    ordering, not dict ordering, is what matters."""
    overrides = {
        # i2c_address listed BEFORE the identity it depends on — must still work.
        "codecs.adau1979.i2c_address": {
            "value": "0x31", "authority": _auth(),
            "attestation": _att("LD20-94440 Sheet 53 (ADDR0/1=GND)"),
        },
        "codecs.pcm1681.i2c_address": {
            "value": "0x4c", "authority": _auth(),
            "attestation": _att("LD20-94440 Sheet 48 (MSEL->GND)"),
        },
        "codecs.role:DAC.part_number": {
            "value": "adau1979", "authority": _auth(),
            "attestation": _att("LD20-94440 Sheet 53"),
        },
        "codecs.role:ADC.part_number": {
            "value": "pcm1681", "authority": _auth(),
            "attestation": _att("LD20-94440 Sheet 48"),
        },
    }
    result = _project(_nord_shaped_gc(), overrides)

    dac = _codec_by_role(result.template, "DAC")
    adc = _codec_by_role(result.template, "ADC")
    assert dac["part_number"].value == "adau1979"
    assert dac["i2c_address"].value == "0x31"
    assert dac["i2c_address"].ncc_state == "ATTESTED"
    assert dac["i2c_address"].authority["origin"] == "schematic"
    assert adc["part_number"].value == "pcm1681"
    assert adc["i2c_address"].value == "0x4c"
    assert adc["i2c_address"].ncc_state == "ATTESTED"


# ── 2. NEGATIVE: candidate part_number cannot self-promote (door locked) ──────


def test_candidate_part_number_cannot_self_promote_without_override():
    """A codec WITH a name (so part_number is candidate_derived) projected with
    NO override stays NOT_ATTESTED / value=None / UNAVAILABLE. The candidate can
    never lift itself — only an explicit cited override can."""
    gc = {
        "cross_verification": {"rows": []},
        "codecs": [{"part_number": "adau1979", "role": "DAC playback"}],
    }
    result = _project(gc, None)
    pn = result.template.codecs[0]["part_number"]

    assert pn.value is None
    assert pn.ncc_state == "NOT_ATTESTED"
    assert pn.candidate_derived is True
    assert pn.candidate_value == "adau1979"
    assert pn.authority["strength"] == "UNAVAILABLE"


def test_model_self_promotion_firewall_intact():
    """model.py:138: constructing a candidate_derived FactRecord with a real
    authority strength still raises — the promotion this WP enables is done by
    REPLACING the record (candidate_derived=False), never by mutating a
    candidate into a real-authority state."""
    with pytest.raises(ValueError, match="candidate_derived is True"):
        FactRecord(
            candidate_derived=True,
            authority={"strength": "KB_RULE", "origin": "schematic"},
            attestation={"evidence": "x"},
        )


# ── 3. NEGATIVE: override without citation is loud ────────────────────────────


def test_part_number_override_without_evidence_raises():
    """An identity override with empty evidence is a loud ValueError, never a
    silent promotion."""
    overrides = {
        "codecs.role:DAC.part_number": {
            "value": "adau1979", "authority": _auth(),
            "attestation": _att(""),  # empty evidence
        },
    }
    with pytest.raises(ValueError, match="evidence"):
        _project(_nord_shaped_gc(), overrides)


def test_part_number_override_missing_attestation_block_raises():
    """No attestation block at all -> loud (attestation must be a dict)."""
    overrides = {
        "codecs.role:DAC.part_number": {
            "value": "adau1979", "authority": _auth(),
        },
    }
    with pytest.raises(ValueError, match="attestation"):
        _project(_nord_shaped_gc(), overrides)


# ── 4. NEGATIVE: role anchor must be unambiguous / matched ────────────────────


def test_ambiguous_role_anchor_raises():
    """A role anchor matching >1 codec is an authoring error, not a silent
    pick-first."""
    gc = {
        "cross_verification": {"rows": []},
        "codecs": [{"role": "DAC path"}, {"role": "ADC path"}],
    }
    overrides = {
        "codecs.role:path.part_number": {
            "value": "x", "authority": _auth(), "attestation": _att("S1"),
        },
    }
    with pytest.raises(ValueError, match="matched 2"):
        _project(gc, overrides)


def test_unmatched_role_anchor_raises():
    """A role anchor matching zero codecs is loud."""
    overrides = {
        "codecs.role:WOOFER.part_number": {
            "value": "x", "authority": _auth(), "attestation": _att("S1"),
        },
    }
    with pytest.raises(ValueError, match="matched 0"):
        _project(_nord_shaped_gc(), overrides)


def test_part_number_not_identity_keyable():
    """part_number is EXCLUDED from the identity-keyed fields — an attempt to
    address it as codecs.<identity>.part_number is an illegal path (must use the
    role: anchor instead)."""
    overrides = {
        "codecs.adau1979.part_number": {
            "value": "adau1979", "authority": _auth(), "attestation": _att("S1"),
        },
    }
    with pytest.raises(ValueError, match="illegal template path"):
        _project(_nord_shaped_gc(), overrides)


# ── 5. firewall: promotion is disclosure-only ────────────────────────────────


def test_identity_promotion_never_touches_cross_verification():
    """Attesting an identity + address must not mutate
    gc['cross_verification']['rows']."""
    gc = _nord_shaped_gc()
    before = deepcopy(gc)
    overrides = {
        "codecs.role:DAC.part_number": {
            "value": "adau1979", "authority": _auth(), "attestation": _att("S53"),
        },
        "codecs.adau1979.i2c_address": {
            "value": "0x31", "authority": _auth(), "attestation": _att("S53b"),
        },
    }
    _project(gc, overrides)
    assert gc["cross_verification"]["rows"] == before["cross_verification"]["rows"]
    assert gc["cross_verification"]["rows"] == []


# ── 6. closed-enum + allowlist shape invariants ──────────────────────────────


def test_authority_strengths_unchanged_closed_set():
    assert AUTHORITY_STRENGTHS == frozenset(
        {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
    )
    assert len(AUTHORITY_STRENGTHS) == 4


def test_part_number_in_schematic_fields_but_not_identity_keyed():
    assert "part_number" in _CODEC_SCHEMATIC_FIELDS
    assert "part_number" not in _CODEC_IDENTITY_KEYED_FIELDS
    assert _CODEC_IDENTITY_KEYED_FIELDS == frozenset(
        {"i2c_bus_label", "i2c_address", "reset_gpios"}
    )


# ── 7. NON-NEGOTIABLE: un-curated Nord still byte-identical ───────────────────


def test_nord_skeleton_still_byte_identical():
    """The mechanism must not perturb Nord's emitted template. Nord ships the
    SCHEMA-ONLY skeleton (all placeholders) — every entry is skipped as
    un-curated, so no identity is promoted and the template is byte-identical to
    the committed fixture. This proves shipping the mechanism (before any human
    fills a real value) is a no-op on Nord bytes."""
    analysis = json.loads((_NORD_DIR / "qgenie_analysis.json").read_text("utf-8"))
    gc = {
        "soc": analysis.get("soc"),
        "codecs": analysis.get("codecs") or [],
        "amplifiers": analysis.get("amplifiers") or [],
        "buses": analysis.get("buses") or {},
        "soundwire": analysis.get("soundwire") or {},
        "ipcat": analysis.get("ipcat") or {},
        "cross_verification": {
            "rows": [],
            "snapshot_provenance": {
                "note": "H-1 validation harness — real target, rows not persisted",
            },
        },
    }
    curated = load_curated_overrides(
        _NORD_DIR / "curated_overrides.json", required=False
    )
    result = project(
        gc, target_name="nord-iq10", run_id="h1-validation-nord-iq10",
        curated_overrides=curated,
    )
    committed = _NORD_TEMPLATE.read_text("utf-8")
    with tempfile.TemporaryDirectory() as d:
        write_outputs(result, Path(d))
        fresh = (Path(d) / "audio_hardware_template.json").read_text("utf-8")

    assert fresh == committed, "codec-identity mechanism perturbed Nord bytes"
