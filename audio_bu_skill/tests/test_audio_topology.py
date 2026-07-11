"""Unit tests for BringupCase.audio_topology (slice 4 of the Onboarding
Accuracy Upgrade).

Covers: the field defaults to {} and is fully optional (backward compatible
with every existing target, incl. nord-iq10's real case.py, which never sets
it); merge_cases merges it key-wise like codec_verdicts; validate_case is
unaffected by its presence or absence.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_audio_topology
(or: python3 audio_bu_skill/tests/test_audio_topology.py)
"""

from __future__ import annotations

from orchestrator.bringup_walk import BringupCase, merge_cases, validate_case


def _minimal_case(**overrides) -> BringupCase:
    base = dict(target_soc="TESTSOC", nearest_target="x", run_id="testsoc-audio-bringup")
    base.update(overrides)
    return BringupCase(**base)


def test_audio_topology_defaults_to_empty_dict() -> None:
    case = _minimal_case()
    assert case.audio_topology == {}, case.audio_topology
    print("PASS: audio_topology defaults to {} when unset")


def test_nord_iq10_style_case_unaffected() -> None:
    """A case built exactly like the real nord-iq10/case.py (no audio_topology
    kwarg at all) must still construct and validate cleanly."""
    case = BringupCase(
        target_soc="SA8797P",
        nearest_target="x",
        run_id="nord-iq10-audio-bringup-2026-07",
        kernel_source_path="linux-fake",
        codec_part_numbers=["PCM1681", "ADAU1979"],
        codec_verdicts={"PCM1681": {"driver_path": "sound/soc/codecs/pcm1681.c", "status": "upstream_present"}},
        power_model_source="confirmed",
    )
    assert case.audio_topology == {}
    validate_case(case, target="nord-iq10")  # must not raise
    print("PASS: nord-iq10-style case (no audio_topology kwarg) constructs and validates unchanged")


def test_merge_cases_merges_audio_topology_key_wise() -> None:
    parent = _minimal_case(audio_topology={"codecs": [{"part": "WCD9378"}], "soundwire": {"present": True}})
    child = _minimal_case(audio_topology={"soundwire": {"present": True, "master_count": 1}})

    merged = merge_cases(parent, child)

    # child's "soundwire" key overrides parent's; parent's "codecs" key (absent
    # in child) is preserved -- same key-wise dict merge semantics as codec_verdicts.
    assert merged.audio_topology["codecs"] == [{"part": "WCD9378"}], merged.audio_topology
    assert merged.audio_topology["soundwire"] == {"present": True, "master_count": 1}, merged.audio_topology
    print("PASS: merge_cases merges audio_topology key-wise (child wins per-key, parent keys preserved)")


def test_merge_cases_child_empty_inherits_parent_topology() -> None:
    parent = _minimal_case(audio_topology={"codecs": [{"part": "WCD9378"}]})
    child = _minimal_case()  # audio_topology left at default {}

    merged = merge_cases(parent, child)
    assert merged.audio_topology == {"codecs": [{"part": "WCD9378"}]}, merged.audio_topology
    print("PASS: child leaving audio_topology at default {} inherits parent's audio_topology untouched")


def test_validate_case_accepts_rich_audio_topology() -> None:
    case = _minimal_case(audio_topology={
        "codecs": [{"part": "WCD9378", "confidence": 0.9}],
        "amplifiers": [{"part": "WSA8845", "role": "amp"}],
        "speakers": [{"part": "WSA8845", "role": "left"}, {"part": "WSA8845", "role": "right"}],
        "mics": [], "soundwire": {"present": True, "master_count": 1},
        "lpass": {"present": True}, "adsp": {"present": True},
        "audioreach": {"gpr": True, "apm": True},
        "power_model": {"status": "source_confirmed", "kind": "rpmhpd", "lcx_lmx_present": True},
        "candidate_patch_series": [{"sha": "abc123", "subject": "FROMLIST: ..."}],
        "pin_crosschecks": [{"signal": "WSA1_EN", "match": True}],
        "missing_evidence": ["codec-side SoundWire bus not wired in FROMLIST series"],
        "citations": {"soc": ["kernel/arch/.../fakesoc.dtsi"]},
    })
    validate_case(case, target="eliza")  # must not raise
    print("PASS: validate_case accepts a fully-populated audio_topology without complaint")


def main() -> None:
    test_audio_topology_defaults_to_empty_dict()
    test_nord_iq10_style_case_unaffected()
    test_merge_cases_merges_audio_topology_key_wise()
    test_merge_cases_child_empty_inherits_parent_topology()
    test_validate_case_accepts_rich_audio_topology()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
