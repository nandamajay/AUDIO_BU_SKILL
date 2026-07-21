"""Unit tests for the similarity engine (v1.1 Phase 1).

Pure, no filesystem: hand-build TargetProfiles and assert scoring/confidence.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_similarity_engine
(or: python3 audio_bu_skill/tests/test_similarity_engine.py)
"""

from __future__ import annotations

from orchestrator.similarity import (
    ADSP_ROLE_SIGNALS,
    CANONICAL_ROLES,
    ROLE_ALIASES,
    ROLE_SIGNALS,
    SNDCARD_ROLE_SIGNALS,
    TargetProfile,
    confidence,
    normalize_role,
    rank,
    rank_per_role,
    role_confidence,
    score,
)
from orchestrator.similarity.engine import MIN_MARGIN, MIN_SCORE


def _profile(name, **kw) -> TargetProfile:
    p = TargetProfile(target_name=name)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_identical_profiles_score_one() -> None:
    a = _profile("a", soc="SA8797P", codecs={"PCM1681", "ADAU1979"},
                 dt_compatibles={"qcom,q6apm"}, power_domain_providers={"rpmhpd"},
                 audioreach=True, soundwire={"present": True, "master_count": 2})
    b = _profile("b", soc="SA8797P", codecs={"PCM1681", "ADAU1979"},
                 dt_compatibles={"qcom,q6apm"}, power_domain_providers={"rpmhpd"},
                 audioreach=True, soundwire={"present": True, "master_count": 2})
    per = score(a, b)
    for signal, val in per.items():
        assert val == 1.0, f"{signal} expected 1.0, got {val}"
    ranked = rank(a, [b])
    assert ranked[0].overall == 1.0
    print("PASS: identical profiles score 1.0 across all signals")


def test_disjoint_profiles_score_near_zero() -> None:
    a = _profile("a", soc="SA8797P", codecs={"PCM1681"},
                 dt_compatibles={"qcom,q6apm"}, power_domain_providers={"rpmhpd"},
                 audioreach=True, soundwire={"present": True, "master_count": 1})
    b = _profile("b", soc="QCS9100", codecs={"WCD9385"},
                 dt_compatibles={"qcom,soundwire"}, power_domain_providers={"scmi11_pd"},
                 audioreach=False, soundwire={"present": False, "master_count": 0})
    ranked = rank(a, [b])
    assert ranked[0].overall < 0.05, f"expected ~0, got {ranked[0].overall}"
    print("PASS: disjoint profiles score ~0")


def test_low_confidence_gating() -> None:
    new = _profile("new", codecs={"PCM1681", "ADAU1979"}, power_domain_providers={"rpmhpd"})
    # two near-tied candidates -> margin below MIN_MARGIN -> low_confidence
    c1 = _profile("c1", codecs={"PCM1681", "ADAU1979"}, power_domain_providers={"rpmhpd"})
    c2 = _profile("c2", codecs={"PCM1681", "ADAU1979"}, power_domain_providers={"rpmhpd"})
    ranked = rank(new, [c1, c2])
    conf = confidence(ranked)
    assert conf["margin"] < MIN_MARGIN
    assert conf["low_confidence"] is True, conf
    print("PASS: near-tied top candidates trip low_confidence (margin gate)")


def test_low_score_gating() -> None:
    new = _profile("new", codecs={"PCM1681"}, power_domain_providers={"rpmhpd"})
    weak = _profile("weak", codecs={"WCD9385"}, power_domain_providers={"scmi11_pd"})
    ranked = rank(new, [weak])
    conf = confidence(ranked)
    assert conf["score"] < MIN_SCORE
    assert conf["low_confidence"] is True, conf
    print("PASS: weak-only match trips low_confidence (score gate)")


def test_confident_match_not_gated() -> None:
    new = _profile("new", soc="SA8797P", codecs={"PCM1681", "ADAU1979"},
                   dt_compatibles={"qcom,q6apm", "qcom,adsp-pas"},
                   power_domain_providers={"rpmhpd"}, audioreach=True,
                   soundwire={"present": False, "master_count": 0})
    strong = _profile("strong", soc="SA8797P", codecs={"PCM1681", "ADAU1979"},
                      dt_compatibles={"qcom,q6apm", "qcom,adsp-pas"},
                      power_domain_providers={"rpmhpd"}, audioreach=True,
                      soundwire={"present": False, "master_count": 0})
    weak = _profile("weak", soc="QCS9100", codecs={"WCD9385"},
                    dt_compatibles={"qcom,soundwire"}, power_domain_providers={"scmi11_pd"},
                    audioreach=False, soundwire={"present": True, "master_count": 3})
    ranked = rank(new, [strong, weak])
    conf = confidence(ranked)
    assert conf["top"] == "strong"
    assert conf["low_confidence"] is False, conf
    print("PASS: strong+clear-margin match is not gated")


# ---------------------------------------------------------------------------
# Phase B — per-role ranking + confidence
# ---------------------------------------------------------------------------

def test_role_signal_weights_sum_to_one() -> None:
    assert round(sum(ADSP_ROLE_SIGNALS.values()), 6) == 1.0, ADSP_ROLE_SIGNALS
    assert round(sum(SNDCARD_ROLE_SIGNALS.values()), 6) == 1.0, SNDCARD_ROLE_SIGNALS
    assert set(ROLE_SIGNALS) == {"adsp_stack", "sound_card"}, ROLE_SIGNALS
    assert ROLE_SIGNALS["adsp_stack"] is ADSP_ROLE_SIGNALS
    assert ROLE_SIGNALS["sound_card"] is SNDCARD_ROLE_SIGNALS
    print("PASS: role signal weight dicts sum to 1.0 and ROLE_SIGNALS maps both roles")


def test_normalize_role_folds_legacy_aliases() -> None:
    # Canonical vocabulary is adsp_stack/sound_card; legacy Phase A aliases fold in.
    assert normalize_role("adsp_donor") == "adsp_stack"
    assert normalize_role("soundcard_donor") == "sound_card"
    # canonical strings pass through unchanged (idempotent)
    assert normalize_role("adsp_stack") == "adsp_stack"
    assert normalize_role("sound_card") == "sound_card"
    # unknown / empty pass through unchanged (no silent drop)
    assert normalize_role("mystery_role") == "mystery_role"
    assert normalize_role("") == ""
    # alias map + canonical set are consistent with ROLE_SIGNALS
    assert set(CANONICAL_ROLES) == set(ROLE_SIGNALS), (CANONICAL_ROLES, set(ROLE_SIGNALS))
    assert set(ROLE_ALIASES.values()) <= set(CANONICAL_ROLES), ROLE_ALIASES
    assert not (set(ROLE_ALIASES) & set(CANONICAL_ROLES)), "no alias may collide with a canonical key"
    print("PASS: normalize_role folds legacy aliases, passes canonical/unknown through")


def test_rank_per_role_picks_role_specific_winners() -> None:
    # A split target: ADSP signals (audioreach + power + soc) point at adsp_donor;
    # codec/soundwire signals point at snd_donor. The blend would land between
    # them; per-role ranking must pick the RIGHT winner for each role.
    new = _profile("new", soc="SA8797P", codecs={"WSA8845", "WCD9385"},
                   dt_compatibles={"qcom,q6apm"}, power_domain_providers={"rpmhpd"},
                   audioreach=True, soundwire={"present": True, "master_count": 2})
    adsp_donor = _profile("adsp_donor", soc="SA8797P", codecs={"NOMATCH"},
                          dt_compatibles={"qcom,other"}, power_domain_providers={"rpmhpd"},
                          audioreach=True, soundwire={"present": False, "master_count": 0})
    snd_donor = _profile("snd_donor", soc="QCS9100", codecs={"WSA8845", "WCD9385"},
                         dt_compatibles={"qcom,q6apm"}, power_domain_providers={"scmi_pd"},
                         audioreach=False, soundwire={"present": True, "master_count": 2})
    by_role = rank_per_role(new, [adsp_donor, snd_donor])
    assert set(by_role) == {"adsp_stack", "sound_card"}, by_role
    assert by_role["adsp_stack"][0].target_name == "adsp_donor", by_role["adsp_stack"]
    assert by_role["sound_card"][0].target_name == "snd_donor", by_role["sound_card"]
    print("PASS: rank_per_role picks the ADSP donor for adsp_stack and the codec donor for sound_card")


def test_role_confidence_shape_and_formula() -> None:
    new = _profile("new", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True,
                   codecs={"WSA8845"}, soundwire={"present": True, "master_count": 2})
    strong = _profile("strong", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True,
                      codecs={"WSA8845"}, soundwire={"present": True, "master_count": 2})
    weak = _profile("weak", soc="QCS9100", power_domain_providers={"scmi_pd"}, audioreach=False,
                    codecs={"NOPE"}, soundwire={"present": False, "master_count": 0})
    by_role = rank_per_role(new, [strong, weak])
    rc = role_confidence(by_role)
    assert set(rc) == {"adsp_stack", "sound_card"}, rc
    for role, block in rc.items():
        # confidence()-shaped block
        for key in ("top", "score", "margin", "confidence", "low_confidence", "min_score", "min_margin"):
            assert key in block, (role, key, block)
        # formula check: confidence == clamp(score * (margin + 0.10))
        expected = max(0.0, min(1.0, block["score"] * (block["margin"] + 0.10)))
        assert abs(block["confidence"] - round(expected, 4)) < 1e-6, (role, block, expected)
        assert block["top"] == "strong", (role, block)
    print("PASS: role_confidence returns a confidence()-shaped block per role obeying the same formula")


def test_role_margins_independent_per_role() -> None:
    # adsp_stack has a clear winner (big margin); sound_card is near-tied (small
    # margin). The two margins must be computed independently, not shared.
    new = _profile("new", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True,
                   codecs={"WSA8845", "WCD9385"}, soundwire={"present": True, "master_count": 2})
    adsp_clear = _profile("adsp_clear", soc="SA8797P", power_domain_providers={"rpmhpd"},
                          audioreach=True, codecs={"WSA8845", "WCD9385"},
                          soundwire={"present": True, "master_count": 2})
    adsp_poor = _profile("adsp_poor", soc="QCS9100", power_domain_providers={"scmi_pd"},
                         audioreach=False, codecs={"WSA8845", "WCD9385"},
                         soundwire={"present": True, "master_count": 2})
    by_role = rank_per_role(new, [adsp_clear, adsp_poor])
    rc = role_confidence(by_role)
    # sound_card: both candidates share identical codecs+soundwire -> tie -> margin 0
    assert rc["sound_card"]["margin"] == 0.0, rc["sound_card"]
    assert rc["sound_card"]["low_confidence"] is True, rc["sound_card"]
    # adsp_stack: adsp_clear wins decisively -> positive margin
    assert rc["adsp_stack"]["margin"] > 0.0, rc["adsp_stack"]
    print("PASS: per-role margins are computed independently (adsp clear, sound_card tied)")


def test_role_low_confidence_near_tie() -> None:
    # Two candidates identical on the adsp_stack signals -> margin 0 -> low_confidence.
    new = _profile("new", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True)
    c1 = _profile("c1", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True)
    c2 = _profile("c2", soc="SA8797P", power_domain_providers={"rpmhpd"}, audioreach=True)
    rc = role_confidence(rank_per_role(new, [c1, c2]))
    assert rc["adsp_stack"]["margin"] < MIN_MARGIN, rc["adsp_stack"]
    assert rc["adsp_stack"]["low_confidence"] is True, rc["adsp_stack"]
    print("PASS: near-tied per-role candidates trip low_confidence")


def test_rank_per_role_empty_db() -> None:
    new = _profile("new", soc="SA8797P", audioreach=True)
    by_role = rank_per_role(new, [])
    assert by_role == {"adsp_stack": [], "sound_card": []}, by_role
    rc = role_confidence(by_role)
    for role in ("adsp_stack", "sound_card"):
        assert rc[role]["top"] is None, rc[role]
        assert rc[role]["low_confidence"] is True, rc[role]
    print("PASS: empty DB yields empty per-role rankings and low-confidence empty blocks")


def test_split_donor_scores_higher_per_role_than_blended() -> None:
    # The core Phase B motivation: for a split target, each role's own winner
    # scores HIGHER on that role than the blended overall of either donor. Proves
    # the per-role view recovers signal the blend washes out.
    new = _profile("new", soc="SA8797P", codecs={"WSA8845", "WCD9385"},
                   dt_compatibles={"qcom,q6apm"}, power_domain_providers={"rpmhpd"},
                   audioreach=True, soundwire={"present": True, "master_count": 2})
    adsp_donor = _profile("adsp_donor", soc="SA8797P", codecs={"NOMATCH"},
                          dt_compatibles={"qcom,other"}, power_domain_providers={"rpmhpd"},
                          audioreach=True, soundwire={"present": False, "master_count": 0})
    snd_donor = _profile("snd_donor", soc="QCS9100", codecs={"WSA8845", "WCD9385"},
                         dt_compatibles={"qcom,q6apm"}, power_domain_providers={"scmi_pd"},
                         audioreach=False, soundwire={"present": True, "master_count": 2})
    blended = {r.target_name: r.overall for r in rank(new, [adsp_donor, snd_donor])}
    by_role = rank_per_role(new, [adsp_donor, snd_donor])
    adsp_role_top = by_role["adsp_stack"][0].overall
    snd_role_top = by_role["sound_card"][0].overall
    assert adsp_role_top > blended["adsp_donor"], (adsp_role_top, blended)
    assert snd_role_top > blended["snd_donor"], (snd_role_top, blended)
    print("PASS: each role's own winner scores higher per-role than its blended overall")


def main() -> None:
    test_identical_profiles_score_one()
    test_disjoint_profiles_score_near_zero()
    test_low_confidence_gating()
    test_low_score_gating()
    test_confident_match_not_gated()
    # Phase B: per-role ranking + confidence
    test_role_signal_weights_sum_to_one()
    test_normalize_role_folds_legacy_aliases()
    test_rank_per_role_picks_role_specific_winners()
    test_role_confidence_shape_and_formula()
    test_role_margins_independent_per_role()
    test_role_low_confidence_near_tie()
    test_rank_per_role_empty_db()
    test_split_donor_scores_higher_per_role_than_blended()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
