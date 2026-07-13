"""Unit tests for the Cardinality Authority (Track C / WP-C).

Pure-function tests over orchestrator.reasoning.cardinality — no orchestrator run
needed. Covers:
  * config integrity: applicable_sources subset of LANE_KEYS, known/unknown class
    handling, soundwire_master excludes dt (SWR-P1 not-DT-inferred doctrine).
  * verdict truth table: agree / disagree / not_cross_checkable /
    benign_divergence / disagree_with_authority each hit by a crafted fixture.
  * the two correctness rules the real data forced (C / WP-C pre-flight):
      1. dt=0 under dt_applied=false is NOT a usable count (no false disagree);
      2. ambiguous:true → not_cross_checkable regardless of lane integers.
  * post-SWI authority path (catalog present) — inert today, proven by shape.
  * Nord-like (all unapplied, one ambiguous) and Eliza-like (mixed applied,
    real evidence≠proposal SoundWire ambiguity) regression fixtures, sanitized.
  * additive-only proof: a case with no element_counts yields [] (section
    omitted); element_counts never perturbs the confidence ledger.
  * determinism: identical input → identical rows, config-ordered.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_cardinality
"""

from __future__ import annotations

from orchestrator.reasoning import cardinality as C
from orchestrator.reasoning import cardinality_config as cfg
from orchestrator.reasoning import ledger as L


def _rows_by_class(gc: dict) -> dict[str, dict]:
    return {r["element_class"]: r for r in C.compare_element_counts(gc)}


def _gc(*items: dict) -> dict:
    return {"audio_topology": {"element_counts": list(items)}}


# ── config integrity ─────────────────────────────────────────────────────────

def test_config_applicable_sources_valid() -> None:
    for name in cfg.known_classes():
        for lane in cfg.applicable_sources(name):
            assert lane in cfg.LANE_KEYS, (name, lane)
    print("PASS: every class's applicable_sources are valid lane keys")


def test_soundwire_master_excludes_dt() -> None:
    # SWR-P1 / provenance: master count is not DT-inferred.
    assert "dt" not in cfg.applicable_sources("soundwire_master")
    assert cfg.divergence_rule("soundwire_master") == "SWR-D1"
    print("PASS: soundwire_master excludes dt (SWR-P1) and carries SWR-D1 divergence rule")


def test_unknown_class_ignored() -> None:
    assert not cfg.is_known_class("no_such_class")
    rows = C.compare_element_counts(_gc({"element_class": "no_such_class", "proposal": 3, "citations": []}))
    assert rows == []
    print("PASS: unknown element class is ignored (no row, no crash)")


# ── verdict truth table ──────────────────────────────────────────────────────

def test_agree_two_lanes_match() -> None:
    row = _rows_by_class(_gc(
        {"element_class": "dmic_line", "evidence": 8, "proposal": 8, "citations": ["p4"]}
    ))["dmic_line"]
    assert row["verdict"] == C.VERDICT_AGREE, row
    assert row["warning"] is False, row
    print("PASS: agree — two usable lanes report the same count")


def test_disagree_two_lanes_differ() -> None:
    # dai_link has no divergence rule → a genuine mismatch is a warning.
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "evidence": 2, "proposal": 3, "citations": []}
    ))["dai_link"]
    assert row["verdict"] == C.VERDICT_DISAGREE, row
    assert row["warning"] is True, row
    print("PASS: disagree — two usable lanes differ, no divergence rule → warning")


def test_not_cross_checkable_single_lane() -> None:
    # proposal only (evidence null / dt not applicable-and-null) → nothing to compare.
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "dt": None, "evidence": None, "proposal": 2, "citations": []}
    ))["dai_link"]
    assert row["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE, row
    assert row["warning"] is False, row
    print("PASS: not_cross_checkable — only one usable lane")


def test_benign_divergence_uses_kb_rule() -> None:
    # soundwire_master evidence≠proposal, but SWR-D1 covers count-vs-routing.
    row = _rows_by_class(_gc(
        {"element_class": "soundwire_master", "evidence": 3, "proposal": 1, "citations": []}
    ))["soundwire_master"]
    assert row["verdict"] == C.VERDICT_BENIGN_DIVERGENCE, row
    assert row["rule_id"] == "SWR-D1", row
    assert row["warning"] is False, row  # informational, not a warning (C.5)
    print("PASS: benign_divergence — mismatch downgraded via SWR-D1, informational")


def test_disagree_with_authority_post_swi() -> None:
    # catalog present (post-SWI, inert today) → other lanes compared to it.
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "evidence": 2, "proposal": 2, "catalog": 3, "citations": []}
    ))["dai_link"]
    assert row["verdict"] == C.VERDICT_DISAGREE_WITH_AUTHORITY, row
    assert row["warning"] is True, row
    print("PASS: disagree_with_authority — a lane differs from catalog_count (post-SWI)")


def test_agree_with_authority_post_swi() -> None:
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "evidence": 2, "proposal": 2, "catalog": 2, "citations": []}
    ))["dai_link"]
    assert row["verdict"] == C.VERDICT_AGREE, row
    print("PASS: agree — all lanes match catalog_count (post-SWI)")


# ── correctness rule 1: dt_applied=false + dt=0 is not a usable count ─────────

def test_dt0_unapplied_not_a_false_disagree() -> None:
    # Nord shape: dt=0/dt_applied=false + proposal=2. dt must be dropped so this
    # is not a spurious disagree; only proposal remains → not_cross_checkable.
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "dt": 0, "dt_applied": False,
         "evidence": None, "proposal": 2, "citations": []}
    ))["dai_link"]
    assert row["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE, row
    assert any("unapplied-at-HEAD" in n for n in row["notes"]), row["notes"]
    print("PASS: dt=0 under dt_applied=false is excluded — no false disagree")


def test_dt0_applied_is_a_real_zero() -> None:
    # dt=0 with dt_applied=true is an affirmative zero → a usable count.
    row = _rows_by_class(_gc(
        {"element_class": "dai_link", "dt": 0, "dt_applied": True,
         "proposal": 2, "citations": []}
    ))["dai_link"]
    assert row["counts"].get("dt_count") == 0, row
    assert row["verdict"] == C.VERDICT_DISAGREE, row  # 0 vs 2, no divergence rule
    print("PASS: dt=0 under dt_applied=true is an affirmative zero (usable, can disagree)")


# ── correctness rule 2: ambiguous → not_cross_checkable ───────────────────────

def test_ambiguous_forces_not_cross_checkable() -> None:
    # Even with two lanes that would otherwise "agree", ambiguous disowns the number.
    row = _rows_by_class(_gc(
        {"element_class": "soundwire_master", "evidence": 2, "proposal": 2,
         "ambiguous": True, "ambiguity_note": "could be 1 or 2 masters", "citations": []}
    ))["soundwire_master"]
    assert row["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE, row
    assert row["ambiguous"] is True and row["ambiguity_note"], row
    print("PASS: ambiguous:true → not_cross_checkable regardless of lane integers")


def test_dt_not_authority_for_soundwire_master() -> None:
    # A dt count present for soundwire_master must be reported-but-excluded (SWR-P1).
    row = _rows_by_class(_gc(
        {"element_class": "soundwire_master", "dt": 2, "dt_applied": True,
         "proposal": 1, "citations": []}
    ))["soundwire_master"]
    assert "dt_count" not in row["counts"], row
    assert any("not an authority" in n for n in row["notes"]), row["notes"]
    print("PASS: dt count for soundwire_master is reported but excluded from the check")


# ── regression fixtures modeled on real (sanitized) Nord / Eliza data ─────────

# Nord: every class unapplied at HEAD (dt=0/dt_applied=false); one class ambiguous.
# All lanes but proposal are 0-or-null ⇒ every row not_cross_checkable, no warnings.
_NORD_LIKE = _gc(
    {"element_class": "dsp_subsystem_instance", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 1, "citations": []},
    {"element_class": "dai_link", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 2, "citations": []},
    {"element_class": "audioreach_port", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 2, "ambiguous": True,
     "ambiguity_note": "logical-port macro is a placeholder", "citations": []},
    {"element_class": "amplifier", "dt": 0, "dt_applied": False,
     "evidence": 0, "proposal": 0, "citations": []},
    {"element_class": "soundwire_master", "dt": 0, "dt_applied": False,
     "evidence": 0, "proposal": 0, "citations": []},
    {"element_class": "lpass_macro_instance", "dt": 0, "dt_applied": False,
     "evidence": 0, "proposal": 0, "citations": []},
)

# Eliza: mixed — dsp_subsystem applied (dt=1); soundwire_master evidence≠proposal
# and ambiguous; dmic_line & amplifier & speaker evidence==proposal (agree).
_ELIZA_LIKE = _gc(
    {"element_class": "dsp_subsystem_instance", "dt": 1, "dt_applied": True,
     "evidence": None, "proposal": 1, "citations": []},
    {"element_class": "soundwire_master", "dt": 0, "dt_applied": False,
     "evidence": 3, "proposal": 1, "ambiguous": True,
     "ambiguity_note": "evidence and proposal disagree; 1 or 2 masters", "citations": []},
    {"element_class": "dmic_line", "dt": 0, "dt_applied": False,
     "evidence": 8, "proposal": 8, "citations": []},
    {"element_class": "amplifier", "dt": 0, "dt_applied": False,
     "evidence": 2, "proposal": 2, "citations": []},
    {"element_class": "speaker", "dt": 0, "dt_applied": False,
     "evidence": 2, "proposal": 2, "citations": []},
    {"element_class": "lpass_macro_instance", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 2, "citations": []},
    {"element_class": "dai_link", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 2, "citations": []},
    {"element_class": "audioreach_port", "dt": 0, "dt_applied": False,
     "evidence": None, "proposal": 2, "citations": []},
)


def test_nord_like_no_false_warnings() -> None:
    rows = _rows_by_class(_NORD_LIKE)
    # No row is a warning — everything is unapplied/single-lane.
    assert not any(r["warning"] for r in rows.values()), rows
    assert rows["audioreach_port"]["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE
    assert rows["dsp_subsystem_instance"]["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE
    print("PASS: Nord-like (all unapplied, one ambiguous) → zero false warnings")


def test_eliza_like_verdicts() -> None:
    rows = _rows_by_class(_ELIZA_LIKE)
    # ambiguous SoundWire → not_cross_checkable (not benign_divergence, ambiguity wins).
    assert rows["soundwire_master"]["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE
    # dmic_line / amplifier / speaker evidence==proposal → agree.
    for cls in ("dmic_line", "amplifier", "speaker"):
        assert rows[cls]["verdict"] == C.VERDICT_AGREE, (cls, rows[cls])
    # dsp applied but single usable lane (dt=1, proposal=1) → they agree.
    assert rows["dsp_subsystem_instance"]["verdict"] == C.VERDICT_AGREE, rows["dsp_subsystem_instance"]
    assert rows["dsp_subsystem_instance"]["counts"] == {"dt_count": 1, "proposal_count": 1}
    # no warnings on the real Eliza shape.
    assert not any(r["warning"] for r in rows.values()), rows
    print("PASS: Eliza-like verdicts — ambiguous SWR not_cross_checkable, dmic/amp/spk agree, dsp agree")


def test_ambiguity_beats_benign_divergence() -> None:
    # soundwire_master carries SWR-D1, but ambiguity is evaluated first.
    row = _rows_by_class(_ELIZA_LIKE)["soundwire_master"]
    assert row["verdict"] != C.VERDICT_BENIGN_DIVERGENCE
    assert row["verdict"] == C.VERDICT_NOT_CROSS_CHECKABLE
    print("PASS: ambiguity precedence beats benign_divergence for ambiguous SWR")


# ── additive-only / non-interference ─────────────────────────────────────────

def test_no_element_counts_yields_empty() -> None:
    assert C.compare_element_counts({"audio_topology": {}}) == []
    assert C.compare_element_counts({}) == []
    assert C.compare_element_counts({"audio_topology": {"element_counts": []}}) == []
    print("PASS: no element_counts → [] (section omitted, pre-1.3.0 report unchanged)")


def test_rows_in_config_order() -> None:
    # Provide rows scrambled; output must follow ELEMENT_CLASSES config order.
    scrambled = _gc(
        {"element_class": "speaker", "evidence": 2, "proposal": 2, "citations": []},
        {"element_class": "dmic_line", "evidence": 8, "proposal": 8, "citations": []},
        {"element_class": "soundwire_master", "evidence": 1, "proposal": 1, "citations": []},
    )
    order = [r["element_class"] for r in C.compare_element_counts(scrambled)]
    known = cfg.known_classes()
    assert order == [c for c in known if c in order], order
    assert order.index("soundwire_master") < order.index("dmic_line") < order.index("speaker")
    print("PASS: rows emitted in config order regardless of input order")


def test_determinism() -> None:
    assert C.compare_element_counts(_ELIZA_LIKE) == C.compare_element_counts(_ELIZA_LIKE)
    assert C.compare_element_counts(_NORD_LIKE) == C.compare_element_counts(_NORD_LIKE)
    print("PASS: deterministic — identical input yields identical rows")


def test_element_counts_does_not_perturb_ledger() -> None:
    # WP-B non-interference (mirror of the ledger's own guard): adding
    # element_counts must leave every confidence-ledger row byte-identical.
    base = {"audio_topology": {
        "codecs": [{"part": "A", "confidence": 0.8, "citations": ["ds.pdf", "patch.diff"]}],
        "soundwire": {"present": True, "confidence": 0.55, "citations": ["a", "b"]},
    }}
    with_ec = {"audio_topology": {
        **base["audio_topology"],
        "element_counts": _ELIZA_LIKE["audio_topology"]["element_counts"],
    }}
    assert L.build_ledger(base, None) == L.build_ledger(with_ec, None)
    print("PASS: element_counts leaves the confidence ledger byte-identical (WP-B untouched)")


def main() -> None:
    test_config_applicable_sources_valid()
    test_soundwire_master_excludes_dt()
    test_unknown_class_ignored()
    test_agree_two_lanes_match()
    test_disagree_two_lanes_differ()
    test_not_cross_checkable_single_lane()
    test_benign_divergence_uses_kb_rule()
    test_disagree_with_authority_post_swi()
    test_agree_with_authority_post_swi()
    test_dt0_unapplied_not_a_false_disagree()
    test_dt0_applied_is_a_real_zero()
    test_ambiguous_forces_not_cross_checkable()
    test_dt_not_authority_for_soundwire_master()
    test_nord_like_no_false_warnings()
    test_eliza_like_verdicts()
    test_ambiguity_beats_benign_divergence()
    test_no_element_counts_yields_empty()
    test_rows_in_config_order()
    test_determinism()
    test_element_counts_does_not_perturb_ledger()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
