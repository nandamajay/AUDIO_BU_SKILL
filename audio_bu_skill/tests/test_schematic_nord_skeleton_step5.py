"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 5 + WP-CODEC-IDENTITY-ATTEST Part 2
— Nord curated_overrides: mechanism (step 5) AND the first real human FILL.

Step 4 (0083591) made ``codec_stub`` a CONSUMER of schematic-attested leaves.
Step 5 shipped ``targets/nord-iq10/curated_overrides.json`` as a SCHEMA-ONLY
skeleton (six null placeholders). WP-CODEC-IDENTITY-ATTEST Part 2 then had a
human (ajay.nandam) FILL five of those leaves from schematic LD20-94440:
``board_metadata.mclk`` = 12288000 (Sheet 98), and — role-anchored — the two
codec identities plus their I2C addresses (DAC->pcm1681@0x4c Sheet 48;
ADC->adau1979@0x31 Sheet 53). The remaining leaves stay null placeholders.

So Nord is no longer a pure skeleton — it is PARTIALLY CURATED. This module
pins BOTH halves: the placeholder mechanism (proven on SYNTHETIC data, so it
does not depend on Nord's now-mutable file) and Nord's current filled state.

The tension the placeholder mechanism resolves: ``_validate_curated_overrides``
raises on ANY ``value: null`` entry, and the H-1 harness AUTO-LOADS
``targets/<t>/curated_overrides.json``. A naive null entry would therefore crash
regeneration. Resolution (projector.py ``_is_placeholder_entry``): an entry with
``value`` null AND no ``authority`` AND no ``attestation`` is a PLACEHOLDER —
path legality is still enforced, but it is skipped as "not yet curated" (no
ATTESTED promotion). A ``value: null`` entry that DOES carry a claim
(authority/attestation) is NOT a placeholder and stays a loud error.

Contract pinned here:

  1. Nord's FILLED curation, driven through the REAL projector + the REAL codec
     consumer → codec_stub emits BOTH addresses (0x31/0x4c) carrying the pinned
     schematic-attested provenance comment. Nord's codec_stub bytes CHANGE from
     the pre-fill baseline — the added provenance is the intended win — and are
     byte-locked to ``nord_codec_stub_attested_expected.c``.
  2. SYNTHETIC placeholder (value=null, no claim) entries load cleanly (no raise)
     and stay NOT_ATTESTED / value=null — the mechanism, proven independent of
     Nord's filled file.
  3. HANDOFF: a human filling one entry with value + authority + attestation →
     that leaf goes ATTESTED and the consumer emits the pinned disclosure comment
     (proven with a SYNTHETIC filled copy).
  4. Nord's curated_overrides is PARTIALLY CURATED: exactly five filled leaves
     (value + KB_RULE/schematic authority + citing attestation) and six null
     placeholders, all paths legal.
  5. A ``value: null`` entry that carries an attestation block is NOT a
     placeholder → stays loud (the existing firewall contract is intact).

Run: ``PYTHONPATH=.:audio_bu_skill python -m pytest \
    audio_bu_skill/tests/test_schematic_nord_skeleton_step5.py -q``
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

from orchestrator.generation.codec_stub import generate_codec_stub
from orchestrator.generation.model import GeneratedArtifact, TrustedFacts
from orchestrator.hw_template.projector import (
    _is_placeholder_entry,
    load_curated_overrides,
    project,
)
from orchestrator.reasoning.crossverify_model import VerificationRow

_FIXTURES = _REPO / "tests" / "fixtures" / "phase2b"
_NORD_DIR = _REPO / "targets" / "nord-iq10"
_SKELETON = _NORD_DIR / "curated_overrides.json"
_EXPECTED_ATTESTED_C = _FIXTURES / "nord_codec_stub_attested_expected.c"

_SHEET = "Schematic LD20-94440 rev A, audio sheet"
_PINNED_SUFFIX = ", NOT IPCAT-cross-verified"

_SCHEMATIC_LEAVES = ("mclk", "global_md_oe", "scmi_index")
_CODEC_LEAVES = ("i2c_bus_label", "i2c_address", "reset_gpios")


# ── shared builders (mirror step-4 test module) ──────────────────────────────


def _rehydrate_wp2_fixture() -> TrustedFacts:
    """Rehydrate the committed Nord WP2 facts fixture → TrustedFacts."""
    path = _FIXTURES / "nord_trusted_facts.json"
    assert path.is_file(), f"missing WP2 fixture: {path!r}"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, VerificationRow] = {}
    for key, rd in data["rows_by_track_subject"].items():
        rows[key] = VerificationRow(
            track=rd["track"],
            subject=rd["subject"],
            verdict=rd["verdict"],
            source=rd.get("source", {}),
            authority=rd.get("authority"),
            confidence=rd.get("confidence", "none"),
            coverage_gap_reason=rd.get("coverage_gap_reason"),
            rule_id=rd.get("rule_id"),
            warning=rd.get("warning"),
            review_actions=list(rd.get("review_actions", [])),
            citations=list(rd.get("citations", [])),
            notes=list(rd.get("notes", [])),
        )
    return TrustedFacts(rows_by_track_subject=rows)


def _gc_two_codecs() -> dict:
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


def _project_synth(overrides: dict | None) -> dict:
    """Project a synthetic 2-codec target (adau1979/pcm1681) → template dict."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        result = project(
            gc=_gc_two_codecs(),
            target_name="synth-t",
            run_id="step5-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
    return result.template.to_dict()


def _load_skeleton() -> dict:
    return json.loads(_SKELETON.read_text(encoding="utf-8"))


# ── 4. Nord's curated_overrides is partially curated (5 filled + 6 placeholder) ─


def test_nord_overrides_is_partially_curated_set() -> None:
    """Nord's curated_overrides is PARTIALLY CURATED: five schematic leaves are
    filled (value + KB_RULE/schematic authority + citing attestation targeting
    nord-iq10), the rest are null placeholders. Every path is legal and every
    filled attestation carries a sheet citation (no invented value without a
    cite)."""
    assert _SKELETON.is_file(), f"missing committed overrides: {_SKELETON!r}"
    sk = _load_skeleton()

    filled_paths = {
        "board_metadata.mclk",
        "codecs.role:DAC.part_number",
        "codecs.role:ADC.part_number",
        "codecs.pcm1681.i2c_address",
        "codecs.adau1979.i2c_address",
    }
    placeholder_paths = {
        "board_metadata.global_md_oe",
        "board_metadata.scmi_index",
        "codecs.pcm1681.i2c_bus_label",
        "codecs.pcm1681.reset_gpios",
        "codecs.adau1979.i2c_bus_label",
        "codecs.adau1979.reset_gpios",
    }
    assert set(sk) == filled_paths | placeholder_paths, (
        f"overrides paths drifted.\n  got: {sorted(sk)}\n"
        f"  want: {sorted(filled_paths | placeholder_paths)}"
    )

    for path in filled_paths:
        entry = sk[path]
        assert entry.get("value") is not None, f"{path}: filled leaf must have a value"
        assert not _is_placeholder_entry(entry), f"{path}: filled leaf is not a placeholder"
        auth = entry.get("authority")
        assert isinstance(auth, dict), f"{path}: filled leaf must carry authority"
        assert auth.get("strength") == "KB_RULE", f"{path}: authority.strength"
        assert auth.get("origin") == "schematic", f"{path}: authority.origin"
        att = entry.get("attestation")
        assert isinstance(att, dict), f"{path}: filled leaf must carry attestation"
        assert att.get("evidence"), f"{path}: attestation must cite a sheet (no bare value)"
        assert att.get("target") == "nord-iq10", f"{path}: attestation.target must be nord-iq10"
        assert att.get("attested_by"), f"{path}: attestation.attested_by required"

    for path in placeholder_paths:
        entry = sk[path]
        assert entry.get("value") is None, f"{path}: placeholder value must be null"
        assert "authority" not in entry, f"{path}: placeholder must carry NO authority"
        assert "attestation" not in entry, (
            f"{path}: placeholder must carry NO attestation (no invented citation)"
        )
        assert _is_placeholder_entry(entry), f"{path}: not recognised as placeholder"
        assert entry.get("_fill"), f"{path}: missing human-fill marker"
    print("PASS: Nord overrides is a partially-curated set (5 filled + 6 placeholder)")


def test_skeleton_loads_cleanly_via_convention_loader() -> None:
    """The auto-load convention (harness path) loads the skeleton without raising
    — a schema-only file loads as data; the loader does not validate content."""
    loaded = load_curated_overrides(_SKELETON, required=False)
    assert isinstance(loaded, dict) and loaded, "skeleton did not load as a dict"
    print("PASS: skeleton loads cleanly via load_curated_overrides")


# ── 2. placeholder entries → un-curated, no ATTESTED promotion ───────────────


def test_placeholder_entries_do_not_promote_to_attested() -> None:
    """Feeding a SYNTHETIC placeholder set (value=null, no claim) through the REAL
    projector (validate + apply) does NOT raise and leaves every schematic leaf
    NOT_ATTESTED / value=null. This exercises the placeholder mechanism on
    synthetic identities — deliberately NOT Nord's now-partially-filled file,
    whose attestations target nord-iq10 and would mismatch synth-t."""
    synth_placeholders = {
        "board_metadata.mclk": {"value": None, "_fill": "placeholder"},
        "board_metadata.global_md_oe": {"value": None, "_fill": "placeholder"},
        "board_metadata.scmi_index": {"value": None, "_fill": "placeholder"},
        "codecs.adau1979.i2c_bus_label": {"value": None, "_fill": "placeholder"},
        "codecs.adau1979.i2c_address": {"value": None, "_fill": "placeholder"},
        "codecs.adau1979.reset_gpios": {"value": None, "_fill": "placeholder"},
    }
    template = _project_synth(synth_placeholders)

    bm = template["board_metadata"]
    for field in _SCHEMATIC_LEAVES:
        leaf = bm[field]
        assert leaf["value"] is None, f"board {field} promoted: {leaf!r}"
        assert leaf["ncc_state"] == "NOT_ATTESTED", f"board {field}: {leaf['ncc_state']}"

    for codec in template["codecs"]:
        pn = codec["part_number"]
        ident = pn.get("value") if pn.get("value") is not None else pn.get("candidate_value")
        for field in _CODEC_LEAVES:
            leaf = codec[field]
            assert leaf["value"] is None, f"codec {ident}.{field} promoted: {leaf!r}"
            assert leaf["ncc_state"] == "NOT_ATTESTED", (
                f"codec {ident}.{field}: {leaf['ncc_state']}"
            )
    print("PASS: placeholder entries stay NOT_ATTESTED / null (no promotion)")


def test_placeholder_never_raises_on_null_identity_codecs() -> None:
    """A codec placeholder path must be skipped BEFORE identity resolution, so a
    target whose codec identities are still null (like Nord) does not raise a
    'codec identity not found' error just for shipping a skeleton."""
    # Synthetic gc with codecs that have NO resolvable identity (both null).
    gc = {
        "cross_verification": {"rows": []},
        "codecs": [{"vendor": "adi", "role": "primary"}],  # no part_number
    }
    overrides = {
        "codecs.adau1979.i2c_address": {"value": None, "_fill": "placeholder"},
    }
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        # Must NOT raise despite adau1979 being unresolvable — placeholder skipped.
        project(gc=gc, target_name="synth-null", run_id="s5", curated_overrides=overrides)
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
    print("PASS: codec placeholder skipped before identity resolution (no raise)")


# ── 1. Nord's FILLED curation → codec_stub emits provenance, byte-locked ─────


def test_nord_codec_stub_emits_schematic_provenance_when_filled() -> None:
    """NON-NEGOTIABLE (Part 2 win): Nord's FILLED template (mclk + both codec
    identities + both I2C addresses ATTESTED, origin=schematic) fed to the
    consumer → codec_stub emits BOTH addresses carrying the pinned
    schematic-attested provenance comment, and is byte-locked to
    ``nord_codec_stub_attested_expected.c``. The numeric addresses (0x31/0x4c)
    are unchanged from the pre-fill baseline (the plain fixture) — the added
    provenance comment is the intended, disclosure-only win."""
    facts = _rehydrate_wp2_fixture()
    nord_template = json.loads(
        (_NORD_DIR / "h1_validation" / "audio_hardware_template.json").read_text(
            encoding="utf-8"
        )
    )
    result = generate_codec_stub(facts, template=nord_template)
    assert isinstance(result, GeneratedArtifact)

    text = result.bytes_.decode("utf-8")
    # Both addresses now carry the pinned schematic-attested provenance comment.
    assert "\t.addr = 0x31,  /* schematic-attested (" in text, (
        "ADC (adau1979) address did not emit the schematic-attested comment"
    )
    assert "\t.addr = 0x4c,  /* schematic-attested (" in text, (
        "DAC (pcm1681) address did not emit the schematic-attested comment"
    )
    assert _PINNED_SUFFIX in text, "pinned NOT-IPCAT-cross-verified suffix absent"
    # Disclosure-only: the schematic-attested comment must NOT claim IPCAT.
    assert "IPCAT-cross-verified" not in text.replace(_PINNED_SUFFIX, ""), (
        "codec_stub must never claim positive IPCAT cross-verification"
    )

    expected = _EXPECTED_ATTESTED_C.read_bytes()
    assert result.bytes_ == expected, (
        "Nord codec_stub drifted from the attested fixture.\n"
        f"actual (first 400):   {result.bytes_[:400]!r}\n"
        f"expected (first 400): {expected[:400]!r}"
    )
    print("PASS: Nord filled codec_stub emits both provenance comments (byte-locked)")


def test_nord_template_regenerates_filled_leaves_attested() -> None:
    """Regenerating Nord's H-1 template WITH the committed curated_overrides (via
    the real validate+apply path) reproduces the committed filled state: the five
    filled leaves regenerate ATTESTED / origin=schematic, the null placeholders
    stay NOT_ATTESTED / value=null, and the role->identity pairing is the
    hardware-correct one (DAC->pcm1681@0x4c, ADC->adau1979@0x31).

    This exercises the crux — a partially-filled file at the auto-loaded path must
    load and apply cleanly, promoting only the filled leaves, and it double-checks
    the anchor->part pairing so a swapped anchor cannot silently attest the wrong
    address to the wrong codec."""
    committed = (_NORD_DIR / "h1_validation" / "audio_hardware_template.json").read_text(
        encoding="utf-8"
    )
    committed_tpl = json.loads(committed)

    analysis_path = _NORD_DIR / "qgenie_analysis.json"
    if not analysis_path.is_file():
        pytest.skip("Nord qgenie_analysis.json absent in this checkout")
    from tests.h1_validation_harness import _synthesise_gc_from_analysis

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    gc = _synthesise_gc_from_analysis(analysis)
    overrides = load_curated_overrides(_SKELETON, required=False)

    result = project(
        gc,
        target_name="nord-iq10",
        run_id="h1-validation-nord-iq10",
        curated_overrides=overrides,
    )
    regenerated = result.template.to_dict()

    # board_metadata.mclk is filled → ATTESTED; siblings stay null placeholders.
    mclk = regenerated["board_metadata"]["mclk"]
    assert mclk["value"] == "12288000" and mclk["ncc_state"] == "ATTESTED"
    assert mclk["authority"]["origin"] == "schematic"
    for field in ("global_md_oe", "scmi_index"):
        leaf = regenerated["board_metadata"][field]
        assert leaf["value"] is None and leaf["ncc_state"] == "NOT_ATTESTED"

    # Regeneration matches the committed snapshot leaf-for-leaf.
    assert regenerated["board_metadata"]["mclk"] == committed_tpl["board_metadata"]["mclk"]
    for field in _SCHEMATIC_LEAVES:
        assert (
            regenerated["board_metadata"][field]
            == committed_tpl["board_metadata"][field]
        ), f"board_metadata.{field} drifted"
    assert len(regenerated["codecs"]) == len(committed_tpl["codecs"])
    for got, want in zip(regenerated["codecs"], committed_tpl["codecs"]):
        assert got["part_number"] == want["part_number"], "codec part_number drifted"
        for field in _CODEC_LEAVES:
            assert got[field] == want[field], f"codec {field} drifted"

    # DOUBLE-CHECK the role->identity->address pairing is hardware-correct.
    by_role = {}
    for c in regenerated["codecs"]:
        role = c["role"]
        text = role.get("value") or role.get("candidate_value") or ""
        key = "DAC" if "DAC" in text else ("ADC" if "ADC" in text else "?")
        by_role[key] = c
    dac, adc = by_role["DAC"], by_role["ADC"]
    assert dac["part_number"]["value"] == "pcm1681", "DAC slot must attest pcm1681"
    assert dac["i2c_address"]["value"] == "0x4c", "DAC/pcm1681 address must be 0x4c"
    assert dac["part_number"]["ncc_state"] == "ATTESTED"
    assert dac["i2c_address"]["ncc_state"] == "ATTESTED"
    assert adc["part_number"]["value"] == "adau1979", "ADC slot must attest adau1979"
    assert adc["i2c_address"]["value"] == "0x31", "ADC/adau1979 address must be 0x31"
    assert adc["part_number"]["ncc_state"] == "ATTESTED"
    assert adc["i2c_address"]["ncc_state"] == "ATTESTED"
    # Null codec leaves stay un-curated on both codecs.
    for c in regenerated["codecs"]:
        assert c["i2c_bus_label"]["value"] is None
        assert c["reset_gpios"]["value"] is None
    print("PASS: Nord H-1 regenerates 5 filled leaves ATTESTED, pairing hardware-correct")


# ── 3. HANDOFF: a human fills one entry → ATTESTED + disclosure ──────────────


def test_filled_entry_goes_attested_and_emits_disclosure() -> None:
    """END-TO-END HANDOFF PROOF (synthetic filled copy, NOT the committed
    skeleton): take the skeleton's i2c_address entry, fill it with a real value +
    authority + attestation → that leaf projects ATTESTED and the consumer emits
    the pinned schematic-attested disclosure comment."""
    # Start from the skeleton shape, then FILL one codec leaf (synthetic copy).
    filled = {
        "codecs.adau1979.i2c_address": {
            "value": "0x31",
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": _SHEET,
                "target": "synth-t",
            },
        }
    }
    template = _project_synth(filled)

    # The filled leaf projected ATTESTED.
    adau = next(
        c for c in template["codecs"]
        if (c["part_number"].get("value") or c["part_number"].get("candidate_value"))
        == "adau1979"
    )
    assert adau["i2c_address"]["ncc_state"] == "ATTESTED"
    assert adau["i2c_address"]["value"] == "0x31"

    # The consumer emits the pinned disclosure comment for the filled leaf.
    result = generate_codec_stub(_rehydrate_wp2_fixture(), template=template)
    assert isinstance(result, GeneratedArtifact)
    text = result.bytes_.decode("utf-8")
    expected_line = (
        f"\t.addr = 0x31,  /* schematic-attested ({_SHEET})"
        f"{_PINNED_SUFFIX} */"
    )
    assert expected_line in text, (
        "filled i2c_address did not emit the pinned schematic-attested line.\n"
        f"expected: {expected_line!r}\nemitted:\n{text}"
    )
    print("PASS: filled skeleton entry → ATTESTED + emits disclosure (handoff works)")


def test_filled_and_unfilled_coexist() -> None:
    """A partially-filled file (one leaf filled, the rest still placeholders)
    loads cleanly: the filled leaf goes ATTESTED, the placeholders stay
    un-curated. Proves the human can fill leaves incrementally."""
    mixed = {
        "codecs.adau1979.i2c_address": {
            "value": "0x31",
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": _SHEET,
                "target": "synth-t",
            },
        },
        # still-placeholder siblings
        "codecs.adau1979.reset_gpios": {"value": None, "_fill": "placeholder"},
        "board_metadata.mclk": {"value": None, "_fill": "placeholder"},
    }
    template = _project_synth(mixed)
    adau = next(
        c for c in template["codecs"]
        if (c["part_number"].get("value") or c["part_number"].get("candidate_value"))
        == "adau1979"
    )
    assert adau["i2c_address"]["ncc_state"] == "ATTESTED"
    assert adau["reset_gpios"]["ncc_state"] == "NOT_ATTESTED"
    assert adau["reset_gpios"]["value"] is None
    assert template["board_metadata"]["mclk"]["ncc_state"] == "NOT_ATTESTED"
    print("PASS: filled + placeholder leaves coexist (incremental curation)")


# ── 5. a null value WITH a claim is NOT a placeholder → stays loud ───────────


def test_null_value_with_attestation_still_raises() -> None:
    """The existing firewall contract is intact: a value=null entry that DOES
    carry an attestation block is NOT a placeholder (it makes a claim) and stays
    a loud ValueError. This is the exact shape of
    test_g3a15_curated_firewall.test_null_value_raises."""
    bad = {
        "board_metadata.mclk": {
            "value": None,
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "attestation": {
                "attested_by": "x", "timestamp": "2026-01-01",
                "evidence": "e", "target": "synth-t",
            },
        }
    }
    with pytest.raises(ValueError, match="null value"):
        _project_synth(bad)
    print("PASS: value=null WITH attestation still raises (firewall intact)")


def test_is_placeholder_entry_discriminator() -> None:
    """Unit-level truth table for the placeholder discriminator."""
    assert _is_placeholder_entry({"value": None})
    assert _is_placeholder_entry({"value": None, "_fill": "note"})
    assert _is_placeholder_entry({})  # value absent == null, no claim
    # NOT placeholders — they carry a claim or a concrete value:
    assert not _is_placeholder_entry({"value": None, "authority": {}})
    assert not _is_placeholder_entry({"value": None, "attestation": {}})
    assert not _is_placeholder_entry({"value": "0x31"})
    assert not _is_placeholder_entry("not-a-dict")
    print("PASS: _is_placeholder_entry truth table")


# ── standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_nord_overrides_is_partially_curated_set()
    test_skeleton_loads_cleanly_via_convention_loader()
    test_placeholder_entries_do_not_promote_to_attested()
    test_placeholder_never_raises_on_null_identity_codecs()
    test_nord_codec_stub_emits_schematic_provenance_when_filled()
    test_nord_template_regenerates_filled_leaves_attested()
    test_filled_entry_goes_attested_and_emits_disclosure()
    test_filled_and_unfilled_coexist()
    test_null_value_with_attestation_still_raises()
    test_is_placeholder_entry_discriminator()
    print("\nAll step-5 / Part-2 fill tests passed.")
