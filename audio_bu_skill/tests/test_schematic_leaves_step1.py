"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 1 — NOT_ATTESTED schematic leaves.

Step 1 adds six schematic-attested slots to the H-1 projector output, all
defaulting to NOT_ATTESTED / value=null, with NO consumer and NO curated
wiring (that is step 2+). These tests pin the *inert* contract:

  * board_metadata gains mclk / global_md_oe / scmi_index
  * each codec gains i2c_bus_label / i2c_address / reset_gpios
  * every new leaf is NOT_ATTESTED, value=null, candidate_derived=False,
    authority.strength=UNAVAILABLE — i.e. it never promotes anything and
    never carries the candidate DTS 0x31/0x4c addresses
  * each new leaf is registered in the gap manifest under reason
    "not_attested" (a legal GapManifest bucket)

Byte-identity of generation is guaranteed structurally: value=null ⟹ every
consumer's ``_template_value`` returns None ⟹ the hardcoded fallback fires.
That is asserted at the leaf level here; the generation byte-identity suite
(test_phase_a_template_wiring.py) continues to pass unchanged.

Run: ``PYTHONPATH=audio_bu_skill python -m pytest tests/test_schematic_leaves_step1.py -q``
"""

from __future__ import annotations

from orchestrator.hw_template.projector import project

_BOARD_SCHEMATIC_LEAVES = ("mclk", "global_md_oe", "scmi_index")
_CODEC_SCHEMATIC_LEAVES = ("i2c_bus_label", "i2c_address", "reset_gpios")


def _minimal_gc() -> dict:
    """A tiny gen-context with two codecs and no authoritative rows.

    Mirrors the real-Nord shape: codecs carry only a candidate part_number;
    there is no row that would attest any codec field, so every schematic
    leaf must land NOT_ATTESTED / value=null.
    """
    return {
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


def _project_template() -> dict:
    result = project(_minimal_gc(), target_name="unit-target", run_id="step1-unit")
    return result.template.to_dict()


def _assert_not_attested_null(leaf: dict, where: str) -> None:
    assert leaf["ncc_state"] == "NOT_ATTESTED", f"{where}: ncc_state"
    assert leaf["value"] is None, f"{where}: value must be null"
    assert leaf["candidate_derived"] is False, f"{where}: not candidate-derived"
    assert leaf["candidate_value"] is None, f"{where}: no candidate value"
    assert leaf["authority"]["strength"] == "UNAVAILABLE", f"{where}: strength"


def test_board_metadata_schematic_leaves_present_and_not_attested() -> None:
    bm = _project_template()["board_metadata"]
    for field in _BOARD_SCHEMATIC_LEAVES:
        assert field in bm, f"board_metadata missing schematic leaf {field!r}"
        _assert_not_attested_null(bm[field], f"board_metadata.{field}")


def test_codec_schematic_leaves_present_and_not_attested() -> None:
    codecs = _project_template()["codecs"]
    assert len(codecs) == 2, "expected the two seeded codecs"
    for idx, codec in enumerate(codecs):
        for field in _CODEC_SCHEMATIC_LEAVES:
            assert field in codec, f"codecs[{idx}] missing schematic leaf {field!r}"
            _assert_not_attested_null(codec[field], f"codecs[{idx}].{field}")


def test_i2c_address_never_carries_candidate_bytes() -> None:
    """The candidate 0x31/0x4c addresses must NOT leak into the schematic slot.

    They are candidate-derived (from commit 5267b2e1) and stay hardcoded
    generator fallbacks; the schematic slot must be a clean NOT_ATTESTED
    value=null with no candidate_value either.
    """
    for codec in _project_template()["codecs"]:
        addr = codec["i2c_address"]
        assert addr["value"] is None
        assert addr["candidate_value"] is None


def test_schematic_leaves_registered_in_gap_manifest() -> None:
    result = project(_minimal_gc(), target_name="unit-target", run_id="step1-unit")
    manifest = result.gap_manifest.to_dict()
    paths = {entry["path"] for entry in manifest["gaps"]}

    for field in _BOARD_SCHEMATIC_LEAVES:
        assert f"board_metadata.{field}" in paths, f"manifest missing {field}"
    for idx in range(2):
        for field in _CODEC_SCHEMATIC_LEAVES:
            assert f"codecs[{idx}].{field}" in paths, (
                f"manifest missing codecs[{idx}].{field}"
            )

    # Each new leaf buckets under the legal "not_attested" reason.
    for entry in manifest["gaps"]:
        p = entry["path"]
        is_board = any(p == f"board_metadata.{f}" for f in _BOARD_SCHEMATIC_LEAVES)
        is_codec = any(
            p == f"codecs[{i}].{f}"
            for i in range(2)
            for f in _CODEC_SCHEMATIC_LEAVES
        )
        if is_board or is_codec:
            assert entry["reason"] == "not_attested", f"{p}: wrong bucket"
