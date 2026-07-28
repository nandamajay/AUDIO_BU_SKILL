"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 3b — persist attestation for the consumer.

Steps 1-3 carried a latent bug: ``_validate_curated_overrides`` *requires* an
``attestation.evidence`` sheet reference (projector.py:1009), but
``_apply_curated_overrides`` then constructed the applied FactRecord WITHOUT it
(the block was validated, then dropped), and ``FactRecord.to_dict()`` never
serialized ``attestation`` at all. A generation consumer reading the raw-dict
template therefore could not surface the sheet ref ``<X>`` in the pinned
disclosure comment ``schematic-attested (sheet <X>), NOT IPCAT-cross-verified``
(design §3.1). The value the validator demanded was thrown away.

Step 3b closes that gap, minimally:

  * ``FactRecord`` gains an optional ``attestation: dict | None = None`` field
    (appended LAST — every call site is keyword-arg, so this is safe).
  * ``FactRecord.to_dict()`` serializes ``attestation`` ONLY when non-None.
    An un-curated leaf (the common case — every Nord schematic leaf) omits the
    key entirely, so the committed template's bytes are unperturbed.
  * ``_apply_curated_overrides`` threads the validated ``attestation`` block
    onto the applied FactRecord instead of discarding it.

Contract pinned by these tests:
  * curated leaf with evidence  -> attestation persists through to_dict();
    evidence is readable by a raw-dict consumer (this is what step 4 needs).
  * no curated file (Nord)       -> attestation absent -> BYTE-IDENTICAL to the
    committed 0f81452 fixture (proven, not asserted-by-fiat).
  * ATTESTED leaf missing evidence -> still loud ValueError at validate
    (existing step-2 behavior preserved).
  * firewall: attestation is disclosure-only — never enters cross_verification.
  * candidate_derived leaf still cannot carry non-UNAVAILABLE authority
    (model.py:138 invariant intact).
  * AUTHORITY_STRENGTHS still the closed 4-member set.

All fixtures are SYNTHETIC except the byte-identity check, which reads the real
committed Nord template. No consumer (step 4) is introduced here.

Run: ``PYTHONPATH=.:audio_bu_skill python -m pytest \
    audio_bu_skill/tests/test_schematic_attestation_persist_step3b.py -q``
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
    load_curated_overrides,
    project,
    write_outputs,
)
from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS

_NORD_DIR = _REPO / "targets" / "nord-iq10"
_NORD_TEMPLATE = _NORD_DIR / "h1_validation" / "audio_hardware_template.json"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _gc_two_codecs() -> dict:
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


_SHEET = "Schematic LD20-94440 rev A, audio sheet"


def _codec_override(codec_key: str, field: str, value, *, evidence: str = _SHEET) -> dict:
    return {
        f"codecs.{codec_key}.{field}": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": evidence,
                "target": "synth-t",
            },
        }
    }


def _project(gc: dict, overrides: dict | None):
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(
            gc=gc, target_name="synth-t", run_id="step3b-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


def _adau(template) -> dict:
    return next(
        c for c in template.codecs
        if (c["part_number"].value or c["part_number"].candidate_value) == "adau1979"
    )


# ── 1. curated leaf: attestation persists through to_dict() ───────────────────


def test_attestation_persists_on_applied_factrecord():
    """A curated schematic override lands its attestation block on the applied
    FactRecord (not dropped)."""
    overrides = _codec_override("adau1979", "i2c_address", "0x31")
    result = _project(_gc_two_codecs(), overrides)
    leaf = _adau(result.template)["i2c_address"]

    assert leaf.value == "0x31"
    assert leaf.ncc_state == "ATTESTED"
    assert leaf.attestation is not None
    assert leaf.attestation["evidence"] == _SHEET
    assert leaf.attestation["attested_by"] == "reviewer@example.com"
    assert leaf.attestation["target"] == "synth-t"


def test_evidence_readable_from_raw_dict():
    """The step-4 consumer reads the raw dict (template.to_dict()); the sheet ref
    <X> MUST be reachable there via ['attestation']['evidence']."""
    overrides = _codec_override("adau1979", "i2c_address", "0x31")
    result = _project(_gc_two_codecs(), overrides)
    raw = result.template.to_dict()

    leaf = next(
        c["i2c_address"] for c in raw["codecs"]
        if (c["part_number"]["value"] or c["part_number"]["candidate_value"]) == "adau1979"
    )
    assert leaf["attestation"]["evidence"] == _SHEET
    # And the full audit trail (G-3A.15) survives, not just the sheet string.
    assert set(leaf["attestation"]) >= {"attested_by", "timestamp", "evidence", "target"}


# ── 2. un-curated leaf: attestation key OMITTED (byte-identity foundation) ─────


def test_uncurated_leaf_omits_attestation_key():
    """A NOT_ATTESTED leaf (no curated override) has attestation=None -> the key
    is ABSENT from to_dict() (not present-as-null). This omission is what keeps
    an already-persisted template byte-identical."""
    result = _project(_gc_two_codecs(), None)
    raw = result.template.to_dict()

    bm = raw["board_metadata"]
    for field in ("mclk", "global_md_oe", "scmi_index"):
        assert "attestation" not in bm[field], field
        assert bm[field]["ncc_state"] == "NOT_ATTESTED"
    for c in raw["codecs"]:
        for field in ("i2c_bus_label", "i2c_address", "reset_gpios"):
            assert "attestation" not in c[field], field


def test_default_factrecord_omits_attestation():
    """A bare FactRecord() (default attestation=None) never emits the key."""
    assert "attestation" not in FactRecord().to_dict()


# ── 3. NON-NEGOTIABLE: Nord byte-identity vs committed 0f81452 fixture ────────


def test_nord_template_byte_identical_to_committed_fixture():
    """Regenerate the real Nord template through the exact harness path and prove
    it is BYTE-identical to the committed audio_hardware_template.json.

    Nord ships no curated_overrides.json -> every schematic leaf stays
    attestation=None -> the new key is omitted everywhere -> zero drift.
    """
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
    curated = load_curated_overrides(_NORD_DIR / "curated_overrides.json", required=False)
    assert curated is None, "Nord must have NO curated file for byte-identity to hold"

    result = project(
        gc, target_name="nord-iq10", run_id="h1-validation-nord-iq10",
        curated_overrides=curated,
    )
    committed = _NORD_TEMPLATE.read_text("utf-8")
    with tempfile.TemporaryDirectory() as d:
        write_outputs(result, Path(d))
        fresh = (Path(d) / "audio_hardware_template.json").read_text("utf-8")

    assert fresh == committed, "Nord template drifted — step-3b broke byte-identity"


# ── 4. ATTESTED leaf missing evidence -> still loud (step-2 behavior kept) ────


def test_missing_evidence_still_raises_at_validate():
    """Persisting attestation must NOT weaken the validator: an override with
    empty evidence is still a loud ValueError, never a silent apply."""
    overrides = _codec_override("adau1979", "i2c_address", "0x31", evidence="")
    with pytest.raises(ValueError, match="evidence"):
        _project(_gc_two_codecs(), overrides)


# ── 5. firewall: attestation is disclosure-only ───────────────────────────────


def test_attestation_never_enters_cross_verification():
    """A curated override carrying attestation MUST NOT mutate
    gc['cross_verification']['rows']."""
    gc = _gc_two_codecs()
    gc_before = deepcopy(gc)
    overrides = _codec_override("pcm1681", "reset_gpios", "gpio77")

    result = _project(gc, overrides)

    assert gc["cross_verification"]["rows"] == gc_before["cross_verification"]["rows"]
    assert gc["cross_verification"]["rows"] == []
    c = next(
        x for x in result.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "pcm1681"
    )
    assert c["reset_gpios"].attestation["evidence"] == _SHEET


# ── 6. model invariants intact ────────────────────────────────────────────────


def test_candidate_derived_still_forbids_real_authority():
    """model.py:138 firewall untouched: a candidate_derived leaf with a non-
    UNAVAILABLE strength still raises, even now that attestation is a field."""
    with pytest.raises(ValueError, match="candidate_derived is True"):
        FactRecord(
            candidate_derived=True,
            authority={"strength": "KB_RULE", "origin": "schematic"},
            attestation={"evidence": "x"},
        )


def test_authority_strengths_unchanged_closed_set():
    assert AUTHORITY_STRENGTHS == frozenset(
        {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
    )
    assert len(AUTHORITY_STRENGTHS) == 4


def test_none_and_empty_override_still_byte_identical():
    """Adding the attestation field must not break the step-2 None/{} parity."""
    r_none = _project(_gc_two_codecs(), None)
    r_empty = _project(_gc_two_codecs(), {})
    t1 = json.dumps(r_none.template.to_dict(), sort_keys=True)
    t2 = json.dumps(r_empty.template.to_dict(), sort_keys=True)
    assert t1 == t2
