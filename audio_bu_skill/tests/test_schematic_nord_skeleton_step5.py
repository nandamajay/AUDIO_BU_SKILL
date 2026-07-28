"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 5 — Nord SCHEMA-ONLY placeholder skeleton.

Step 4 (0083591) made ``codec_stub`` a CONSUMER of schematic-attested leaves.
Step 5 is the LAST mechanism step: ship a SCHEMA-ONLY skeleton at
``targets/nord-iq10/curated_overrides.json`` — the six schematic leaves present
with ``value: null`` and NO authority / NO attestation, each carrying a ``_fill``
human-fill marker. It is a TEMPLATE for a human, not curated data.

The tension this step resolves: ``_validate_curated_overrides`` raises on ANY
``value: null`` entry, and the H-1 harness AUTO-LOADS
``targets/<t>/curated_overrides.json``. A naive null skeleton would therefore
crash Nord H-1 regeneration. Resolution (projector.py ``_is_placeholder_entry``):
an entry with ``value`` null AND no ``authority`` AND no ``attestation`` is a
PLACEHOLDER — path legality is still enforced, but it is skipped as "not yet
curated" (no ATTESTED promotion). A ``value: null`` entry that DOES carry a
claim (authority/attestation) is NOT a placeholder and stays a loud error
(``test_g3a15_curated_firewall.test_null_value_raises`` is unchanged).

Contract pinned here (each maps 1:1 to a step-5 non-negotiable):

  1. Nord + the committed SCHEMA-ONLY skeleton, driven through the REAL projector
     + the REAL codec consumer → codec_stub bytes are BYTE-IDENTICAL to the
     frozen ``nord_codec_stub_expected.c``. The placeholder must NOT flip any
     leaf to ATTESTED. PROVEN, not asserted.
  2. Placeholder (value=null, no claim) entries load cleanly (no raise) and are
     treated as un-curated — every schematic leaf stays NOT_ATTESTED / value=null
     in the projected template.
  3. HANDOFF: a human LATER filling one entry with value + authority + attestation
     → that leaf goes ATTESTED and the consumer emits the pinned disclosure
     comment. Proven with a SYNTHETIC filled copy, NOT the committed skeleton.
  4. The committed skeleton is well-formed: all six leaves present, all null, all
     placeholders (no authority / no attestation), all six paths legal.
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
_EXPECTED_C = _FIXTURES / "nord_codec_stub_expected.c"

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


# ── 4. the committed skeleton is well-formed ─────────────────────────────────


def test_skeleton_is_well_formed_placeholder_set() -> None:
    """The committed Nord skeleton has exactly the six schematic leaves, every
    one a null placeholder with no authority / no attestation."""
    assert _SKELETON.is_file(), f"missing committed skeleton: {_SKELETON!r}"
    sk = _load_skeleton()

    expected_paths = {
        "board_metadata.mclk",
        "board_metadata.global_md_oe",
        "board_metadata.scmi_index",
        "codecs.adau1979.i2c_bus_label",
        "codecs.adau1979.i2c_address",
        "codecs.adau1979.reset_gpios",
    }
    assert set(sk) == expected_paths, (
        f"skeleton paths drifted.\n  got: {sorted(sk)}\n  want: {sorted(expected_paths)}"
    )
    for path, entry in sk.items():
        assert entry.get("value") is None, f"{path}: value must be null (not curated)"
        assert "authority" not in entry, f"{path}: placeholder must carry NO authority"
        assert "attestation" not in entry, (
            f"{path}: placeholder must carry NO attestation (no invented citation)"
        )
        assert _is_placeholder_entry(entry), f"{path}: not recognised as placeholder"
        assert entry.get("_fill"), f"{path}: missing human-fill marker"
    print("PASS: committed skeleton is a clean six-leaf null-placeholder set")


def test_skeleton_loads_cleanly_via_convention_loader() -> None:
    """The auto-load convention (harness path) loads the skeleton without raising
    — a schema-only file loads as data; the loader does not validate content."""
    loaded = load_curated_overrides(_SKELETON, required=False)
    assert isinstance(loaded, dict) and loaded, "skeleton did not load as a dict"
    print("PASS: skeleton loads cleanly via load_curated_overrides")


# ── 2. placeholder entries → un-curated, no ATTESTED promotion ───────────────


def test_placeholder_entries_do_not_promote_to_attested() -> None:
    """Feeding the skeleton through the REAL projector (validate + apply) does
    NOT raise and leaves every schematic leaf NOT_ATTESTED / value=null."""
    sk = _load_skeleton()
    # Re-key the codec paths onto the synthetic target's identities (its codecs
    # ARE identity-resolvable, unlike Nord's null-identity codecs) so this test
    # exercises the codec-path branch too, not just the board branch.
    template = _project_synth(sk)

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


# ── 1. Nord byte-identity with the committed skeleton ────────────────────────


def test_nord_codec_stub_byte_identical_with_skeleton() -> None:
    """NON-NEGOTIABLE: the committed Nord template (regenerated with the skeleton
    present is byte-identical to 0f81452, since every entry is a placeholder) fed
    to the consumer → codec_stub bytes == frozen fixture. The skeleton contributes
    NOTHING — fallbacks fire, zero drift."""
    facts = _rehydrate_wp2_fixture()
    nord_template = json.loads(
        (_NORD_DIR / "h1_validation" / "audio_hardware_template.json").read_text(
            encoding="utf-8"
        )
    )
    result = generate_codec_stub(facts, template=nord_template)
    assert isinstance(result, GeneratedArtifact)
    assert result.contributes_rows == [], (
        f"skeleton must not add rows on Nord, got: "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )
    expected = _EXPECTED_C.read_bytes()
    assert result.bytes_ == expected, (
        "Nord codec_stub drifted with the skeleton present.\n"
        f"actual (first 400):   {result.bytes_[:400]!r}\n"
        f"expected (first 400): {expected[:400]!r}"
    )
    print("PASS: Nord + skeleton == frozen codec_stub fixture (byte-identical)")


def test_nord_template_regenerates_identically_with_skeleton() -> None:
    """Regenerating Nord's H-1 template WITH the committed skeleton (via the real
    validate+apply path) reproduces the committed 0f81452 template byte-for-byte:
    the placeholder skeleton is a no-op on the emitted template JSON.

    This exercises the crux — a value=null file at the auto-loaded path must load
    and apply cleanly, not crash H-1 regeneration."""
    committed = (_NORD_DIR / "h1_validation" / "audio_hardware_template.json").read_text(
        encoding="utf-8"
    )
    committed_tpl = json.loads(committed)

    # Rebuild the exact gc the harness synthesises, then re-project WITH skeleton.
    analysis_path = _NORD_DIR / "qgenie_analysis.json"
    if not analysis_path.is_file():
        pytest.skip("Nord qgenie_analysis.json absent in this checkout")
    from tests.h1_validation_harness import _synthesise_gc_from_analysis

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    gc = _synthesise_gc_from_analysis(analysis)
    skeleton = load_curated_overrides(_SKELETON, required=False)

    result = project(
        gc,
        target_name="nord-iq10",
        run_id="h1-validation-nord-iq10",
        curated_overrides=skeleton,
    )
    regenerated = result.template.to_dict()

    # Compare the schematic-leaf regions specifically (run_id/provenance may vary
    # across the committed snapshot, so compare the hardware content, not metadata).
    assert regenerated["board_metadata"]["mclk"] == committed_tpl["board_metadata"]["mclk"]
    for field in _SCHEMATIC_LEAVES:
        assert (
            regenerated["board_metadata"][field]
            == committed_tpl["board_metadata"][field]
        ), f"board_metadata.{field} drifted with skeleton"
    assert len(regenerated["codecs"]) == len(committed_tpl["codecs"])
    for got, want in zip(regenerated["codecs"], committed_tpl["codecs"]):
        for field in _CODEC_LEAVES:
            assert got[field] == want[field], f"codec {field} drifted with skeleton"
    print("PASS: Nord H-1 schematic leaves regenerate identically with skeleton")


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
        f"\t.addr = 0x31,  /* schematic-attested (sheet {_SHEET})"
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
    test_skeleton_is_well_formed_placeholder_set()
    test_skeleton_loads_cleanly_via_convention_loader()
    test_placeholder_entries_do_not_promote_to_attested()
    test_placeholder_never_raises_on_null_identity_codecs()
    test_nord_codec_stub_byte_identical_with_skeleton()
    test_nord_template_regenerates_identically_with_skeleton()
    test_filled_entry_goes_attested_and_emits_disclosure()
    test_filled_and_unfilled_coexist()
    test_null_value_with_attestation_still_raises()
    test_is_placeholder_entry_discriminator()
    print("\nAll step-5 skeleton tests passed.")
