"""Unit tests for the Confidence Ledger (Track B / WP-B).

Pure-function tests over orchestrator.reasoning.ledger — no orchestrator run
needed. Covers:
  * field→domain table total coverage vs ANALYSIS_SCHEMA (drift guard, B.4/§6).
  * min-confidence band roll-up (weakest field governs, B.3/B.4).
  * status truth table: each of MISSING/NEEDS_REVIEW/CORROBORATED/VERIFY/
    NOT_APPLICABLE hit by a crafted fixture (B.2/B.4).
  * an all-MISSING target still renders all 9 rows (target-agnostic proof, B.1).
  * determinism (same input → identical rows).

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_confidence_ledger
"""

from __future__ import annotations

from orchestrator.reasoning import ledger as L
from orchestrator.reasoning.schemas import ANALYSIS_SCHEMA


def _rows_by_domain(gc: dict, analysis: dict | None = None) -> dict[str, dict]:
    return {r["domain"]: r for r in L.build_ledger(gc, analysis)}


def test_all_nine_domains_always_present() -> None:
    # Empty audio_topology → full 9-row table, all MISSING (B.1 gauge property).
    rows = L.build_ledger({"audio_topology": {}}, None)
    assert [r["domain"] for r in rows] == L.DOMAINS
    assert len(rows) == 9
    for r in rows:
        assert r["status"] == L.STATUS_MISSING, r
        assert r["band"] == "—", r
    print("PASS: all 9 domains present, all MISSING for empty topology")


def test_field_domain_table_covers_schema() -> None:
    """Every ANALYSIS_SCHEMA leaf is either mapped to a domain or explicitly
    excluded — the drift guard from spec §6/B.4."""
    props = ANALYSIS_SCHEMA["properties"]
    for top_key, spec in props.items():
        # nested object leaves (audio_stack.*) are mapped by dotted path
        if top_key == "audio_stack":
            for leaf in spec["properties"]:
                if leaf == "citations":
                    continue
                path = f"audio_stack.{leaf}"
                assert path in L.FIELD_DOMAIN_MAP, f"unmapped schema leaf {path}"
            continue
        assert (
            top_key in L.FIELD_DOMAIN_MAP or top_key in L.FIELD_DOMAIN_EXCLUDED
        ), f"schema field {top_key!r} neither mapped nor excluded"
    # every mapped domain is a real domain
    for path, domain in L.FIELD_DOMAIN_MAP.items():
        assert domain in L.DOMAINS, f"{path} maps to unknown domain {domain}"
    print("PASS: field→domain table covers every schema leaf")


def test_min_confidence_band_governs() -> None:
    """A domain's band is its weakest contributing field's band (min roll-up)."""
    gc = {
        "audio_topology": {
            "codecs": [
                {"part": "A", "confidence": 0.95, "citations": ["x", "y"]},
                {"part": "B", "confidence": 0.30, "citations": ["z"]},  # weakest
            ],
        }
    }
    row = _rows_by_domain(gc)["codecs"]
    assert row["band"] == "low", row  # 0.30 governs, not 0.95
    print("PASS: min-confidence weakest field governs band")


def test_status_corroborated() -> None:
    # Two independent citations on the governing field, not review-flagged.
    gc = {
        "audio_topology": {
            "codecs": [
                {"part": "A", "confidence": 0.8, "citations": ["ds.pdf", "patch.diff"]},
            ]
        }
    }
    assert _rows_by_domain(gc)["codecs"]["status"] == L.STATUS_CORROBORATED
    print("PASS: CORROBORATED — >=2 sources on governing field")


def test_status_needs_review_single_source() -> None:
    gc = {
        "audio_topology": {
            "codecs": [{"part": "A", "confidence": 0.8, "citations": ["only.pdf"]}]
        }
    }
    assert _rows_by_domain(gc)["codecs"]["status"] == L.STATUS_NEEDS_REVIEW
    print("PASS: NEEDS_REVIEW — single source")


def test_status_needs_review_power_model_never_finalized() -> None:
    # power_model.needs_review True forces NEEDS_REVIEW even with 2 citations.
    gc = {
        "audio_topology": {
            "power_model": {
                "kind": "rpmhpd",
                "confidence": 0.9,
                "citations": ["a", "b"],
                "needs_review": True,
            }
        }
    }
    assert _rows_by_domain(gc)["power_model"]["status"] == L.STATUS_NEEDS_REVIEW
    print("PASS: NEEDS_REVIEW — power model never auto-finalized")


def test_status_missing_from_missing_evidence() -> None:
    gc = {
        "audio_topology": {
            "soundwire": {},  # no positive evidence
            "missing_evidence": ["SoundWire master count unknown — no enumeration"],
        }
    }
    assert _rows_by_domain(gc)["soundwire"]["status"] == L.STATUS_MISSING
    print("PASS: MISSING — flagged in missing_evidence, no positive evidence")


def test_status_not_applicable() -> None:
    gc = {"audio_topology": {"soundwire": {"present": False, "confidence": 0.9, "citations": ["a", "b"]}}}
    assert _rows_by_domain(gc)["soundwire"]["status"] == L.STATUS_NOT_APPLICABLE
    print("PASS: NOT_APPLICABLE — soundwire present == False")


def test_status_verify_authoritative_unconfirmed() -> None:
    # An authoritative-but-unconfirmed contributor → VERIFY (inert path, but the
    # truth table must produce it when the shape appears).
    contribs = [{"confidence": 0.8, "citations": ["catalog"], "authoritative": True, "confirmed": False}]
    status = L._status_of(contribs, domain_missing=False, needs_review=False, not_applicable=False)
    assert status == L.STATUS_VERIFY
    print("PASS: VERIFY — authoritative but unconfirmed")


def test_determinism() -> None:
    gc = {
        "audio_topology": {
            "codecs": [{"part": "A", "confidence": 0.5, "citations": ["a", "b"]}],
            "power_model": {"kind": "rpmhpd", "confidence": 0.6, "citations": ["p"], "needs_review": True},
            "soundwire": {"present": True, "confidence": 0.4, "citations": ["s"]},
            "audio_stack": {"adsp": True, "lpass": True, "audioreach": True, "citations": ["k"]},
            "missing_evidence": ["clock rates unknown"],
        }
    }
    r1 = L.build_ledger(gc, None)
    r2 = L.build_ledger(gc, None)
    assert r1 == r2, "ledger is not deterministic"
    print("PASS: deterministic — identical input yields identical rows")


def test_rule_ids_degrade_gracefully() -> None:
    # codecs has no governing KB rule → empty rule_ids (blank cell), never crash.
    rows = _rows_by_domain({"audio_topology": {"codecs": [{"part": "A", "confidence": 0.9, "citations": ["a", "b"]}]}})
    assert rows["codecs"]["rule_ids"] == []
    assert rows["soundwire"]["rule_ids"] == ["SWR-D1"]
    print("PASS: KB rule column degrades gracefully to blank")


# ─────────────────────────────────────────────────────────────────────────────
# WP-B refinement regression fixtures (§3.1–3.4), modeled on the real Nord/Eliza
# onboarding outputs. These are the cases the post-implementation review caught.
# ─────────────────────────────────────────────────────────────────────────────

# Nord audio_stack: every flag True, but the shared citation list LEADS with a
# "CAVEAT: none of this exists at the designated kernel HEAD" note, and
# missing_evidence flags the same domains. Before the refinement these rendered
# CORROBORATED; they must now render NEEDS_REVIEW.
_NORD_LIKE = {
    "audio_topology": {
        "audio_stack": {
            "adsp": True, "lpass": True, "audioreach": True,
            "gpr": True, "apm": True, "q6apm": True, "q6prm": True,
            "citations": [
                "CAVEAT: none of this exists at the task's designated kernel HEAD "
                "66b80186 -- verified via grep, zero matches for adsp/audio/gpr",
                "0003-add-ADSP-remoteproc.patch (fastrpc glink-edge subtree, "
                "reg=0x30000000 borrowed from lemans)",
                "0004-enable-audio-codecs.patch (TX_0 as an explicit placeholder port)",
                "profile.json audio_stack booleans",
            ],
        },
        "codecs": [
            # a genuinely corroborated codec: unapplied DT patch + present upstream
            # driver. The "unapplied at HEAD" qualifier must NOT disqualify it.
            {"part": "PCM1681", "confidence": 0.8,
             "citations": ["0004-enable-audio-codecs.patch (audio-codec@4c, unapplied at HEAD)",
                           "drivers/misc/pcm1681.c (upstream driver present)"]},
        ],
        "soundwire": {"present": False, "confidence": 0.7, "master_count": 0,
                      "citations": ["nord.dtsi (no SWR node)", "0004.patch (TDM ports, not SoundWire)"]},
        "missing_evidence": [
            "The AudioReach logical port macro for LPASS I2S8 is an explicit placeholder",
            "ADSP PAS remoteproc register base is unresolved",
            "Power-domain model for the ADSP path is unresolved",
        ],
    }
}

# Eliza audio_stack: NO explicit `adsp` key, but the Q6/APR stack (gpr/q6apm/
# q6prm/apm/audioreach) is all True and the DSP subsystem is plainly present.
# Before the refinement dsp_subsystem rendered MISSING; it must now be inferred.
_ELIZA_LIKE = {
    "audio_topology": {
        "audio_stack": {
            "gpr": True, "apm": True, "audioreach": True, "q6apm": True, "q6prm": True,
            "citations": [
                "drivers/soc/qcom/apr.c:603 (qcom,gpr compatible present)",
                "sound/soc/qcom/qdsp6/q6apm.c (Q6APM driver present)",
                "sound/soc/qcom/qdsp6/q6prm.c (Q6PRM driver present)",
            ],
        },
    }
}


def test_nord_boolean_stack_not_corroborated() -> None:
    """§3.1: caveated, missing_evidence-flagged boolean domains must not be
    CORROBORATED. The genuinely-sourced codec row must stay CORROBORATED."""
    rows = _rows_by_domain(_NORD_LIKE)
    for d in ("dsp_subsystem", "lpass_macros", "audioreach_ports"):
        assert rows[d]["status"] == L.STATUS_NEEDS_REVIEW, (d, rows[d])
    # the trustworthy codec (patch + present driver) is preserved
    assert rows["codecs"]["status"] == L.STATUS_CORROBORATED, rows["codecs"]
    assert rows["codecs"]["band"] == "high", rows["codecs"]
    print("PASS: §3.1 Nord boolean stack → NEEDS_REVIEW; real codec stays CORROBORATED")


def test_boolean_only_domain_never_corroborated_on_count() -> None:
    """§3.1: a boolean-only domain (no numeric confidence) cannot be promoted to
    CORROBORATED by citation count alone, even with many clean citations."""
    gc = {
        "audio_topology": {
            "audio_stack": {
                "lpass": True,
                "citations": ["clean/a.c (present)", "clean/b.c (present)", "clean/c.c (present)"],
            }
        }
    }
    assert _rows_by_domain(gc)["lpass_macros"]["status"] == L.STATUS_NEEDS_REVIEW
    print("PASS: §3.1 boolean-only domain never CORROBORATED on count alone")


def test_caveated_citations_do_not_corroborate() -> None:
    """§3.1: caveated citations are excluded from the corroboration count even for
    a numeric-confidence domain."""
    gc = {
        "audio_topology": {
            "codecs": [
                {"part": "X", "confidence": 0.8, "citations": [
                    "CAVEAT: none of this exists at HEAD",
                    "placeholder node only",
                ]},
            ]
        }
    }
    # both citations are caveated → 0 trustworthy → not CORROBORATED
    assert _rows_by_domain(gc)["codecs"]["status"] == L.STATUS_NEEDS_REVIEW
    print("PASS: §3.1 caveated citations excluded from corroboration count")


def test_eliza_dsp_inferred_from_q6_stack() -> None:
    """§3.3: a present DSP subsystem (gpr/q6apm/q6prm all True) is classified even
    when the explicit `adsp` key is absent — no longer MISSING."""
    rows = _rows_by_domain(_ELIZA_LIKE)
    assert rows["dsp_subsystem"]["status"] == L.STATUS_NEEDS_REVIEW, rows["dsp_subsystem"]
    assert rows["dsp_subsystem"]["status"] != L.STATUS_MISSING
    print("PASS: §3.3 DSP subsystem inferred from Q6 stack when adsp key absent")


def test_not_applicable_band_is_dash() -> None:
    """§3.4: a NOT_APPLICABLE row shows band '—' even when the source carried a
    numeric confidence."""
    row = _rows_by_domain(_NORD_LIKE)["soundwire"]
    assert row["status"] == L.STATUS_NOT_APPLICABLE, row
    assert row["band"] == "—", row
    print("PASS: §3.4 NOT_APPLICABLE row forces band '—'")


def test_evidence_column_readable() -> None:
    """§3.2: path citations collapse to basenames; prose citations clip cleanly
    (no arbitrary 'text after last slash' fragments)."""
    # bare path → basename+line
    assert L._abbrev_one("drivers/soc/qcom/apr.c:603 (gpr present)").startswith("apr.c:603")
    # mixed abs-path-in-prose → basename, not a mid-sentence slash fragment
    out = L._abbrev_one("No controller string present in /a/b/c/eliza.dtsi — cannot confirm")
    assert "eliza.dtsi" in out and "/a/b/c" not in out, out
    # pure prose → clipped with ellipsis, not sliced on '/'
    prose = "CAVEAT: none of this exists at the designated kernel HEAD 66b80186 verified via grep"
    ab = L._abbrev_one(prose)
    assert ab.startswith("CAVEAT: none of this exists") and ab.endswith("…"), ab
    print("PASS: §3.2 evidence column readable for path, mixed, and prose citations")


def test_element_counts_does_not_perturb_ledger() -> None:
    """Fix A / §3 non-interference: element_counts (schema 1.3.0, WP-C input,
    NOT a ledger domain) must leave every ledger row byte-identical. The ledger
    reads none of it — it is excluded from the field→domain table on purpose."""
    base_gc = {
        "audio_topology": {
            "codecs": [{"part": "A", "confidence": 0.8, "citations": ["ds.pdf", "patch.diff"]}],
            "soundwire": {"present": True, "confidence": 0.55, "citations": ["a", "b"]},
        }
    }
    with_ec = {
        "audio_topology": {
            **base_gc["audio_topology"],
            "element_counts": [
                {"element_class": "dmic_line", "dt": 0, "evidence": 8, "proposal": 8,
                 "catalog": None, "ambiguous": False, "dt_applied": False, "citations": ["p4"]},
                {"element_class": "soundwire_master", "dt": 0, "evidence": None, "proposal": 1,
                 "catalog": None, "ambiguous": True, "dt_applied": False, "citations": ["mc=1"]},
            ],
        }
    }
    assert L.build_ledger(base_gc, None) == L.build_ledger(with_ec, None)
    print("PASS: element_counts leaves ledger rows byte-identical (WP-B untouched)")


def main() -> None:
    test_all_nine_domains_always_present()
    test_field_domain_table_covers_schema()
    test_min_confidence_band_governs()
    test_status_corroborated()
    test_status_needs_review_single_source()
    test_status_needs_review_power_model_never_finalized()
    test_status_missing_from_missing_evidence()
    test_status_not_applicable()
    test_status_verify_authoritative_unconfirmed()
    test_determinism()
    test_rule_ids_degrade_gracefully()
    # WP-B refinement regressions (§3.1–3.4)
    test_nord_boolean_stack_not_corroborated()
    test_boolean_only_domain_never_corroborated_on_count()
    test_caveated_citations_do_not_corroborate()
    test_eliza_dsp_inferred_from_q6_stack()
    test_not_applicable_band_is_dash()
    test_evidence_column_readable()
    test_element_counts_does_not_perturb_ledger()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
