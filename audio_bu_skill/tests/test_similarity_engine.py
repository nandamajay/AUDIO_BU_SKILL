"""Unit tests for the similarity engine (v1.1 Phase 1).

Pure, no filesystem: hand-build TargetProfiles and assert scoring/confidence.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_similarity_engine
(or: python3 audio_bu_skill/tests/test_similarity_engine.py)
"""

from __future__ import annotations

from orchestrator.similarity import TargetProfile, confidence, rank, score
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


def main() -> None:
    test_identical_profiles_score_one()
    test_disjoint_profiles_score_near_zero()
    test_low_confidence_gating()
    test_low_score_gating()
    test_confident_match_not_gated()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
