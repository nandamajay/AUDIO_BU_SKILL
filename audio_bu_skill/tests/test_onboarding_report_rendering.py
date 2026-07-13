"""Unit tests for slice 7 of the Onboarding Accuracy Upgrade: surfacing
kernel_history / power_model_hint / pin_crosscheck data (already present in
generated_case since slice 6) in the human-readable onboarding_report.md.

Confirms:
  - the new sections (Kernel History / FROMLIST Findings, Power Model
    Inspection, Pin Cross-Check) render with the expected fields when the
    data is present, and
  - the report renders exactly as before (sections entirely absent, no
    stray headings) when generated_case has none of this data — i.e. the
    reporting change is additive/backward-compatible, not a hard requirement.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_onboarding_report_rendering
(or: python3 audio_bu_skill/tests/test_onboarding_report_rendering.py)
"""

from __future__ import annotations

from orchestrator.main import _render_onboarding_report

_BASE_OUTPUT = {
    "target_profile": {
        "target_name": "eliza-like",
        "soc": "SA8797P",
        "cites": {},
    },
    "similarity_report": {
        "ranked": [
            {"target_name": "lemans-like", "overall": 0.72, "per_signal": {}},
        ],
        "confidence": {
            "confidence": 0.72, "score": 0.72, "margin": 0.1,
            "min_score": 0.75, "min_margin": 0.0, "low_confidence": True,
        },
        "weights": {"codecs": 1},
    },
    "evidence_inventory": {"kernel_source_path": "linux-fake", "files": []},
}


def _output_with_generated_case(gc: dict) -> dict:
    return {**_BASE_OUTPUT, "generated_case": gc}


def test_report_includes_kernel_history_power_model_and_pin_crosscheck_sections() -> None:
    gc = {
        "needs_review": [],
        "candidate_patch_series": [
            {
                "sha": "deadbeefcafefeed",
                "subject": "FROMLIST: arm64: dts: vendor: newboard: Add audio support",
                "applied": False,
                "donor_hint": "DONORSOC",
                "compatible_fallbacks": ["qcom,newboard-adsp-pas", "vendor,donorsoc-adsp-pas"],
                "files_changed": ["newboard-audio.dtsi"],
            },
        ],
        "audio_topology": {
            "power_model": {
                "inspection_hint": {
                    "status": "source_confirmed", "kind": "rpmhpd",
                    "lcx_present": True, "lmx_present": True, "lcx_lmx_present": True,
                    "citations": ["drivers/pmdomain/qcom/rpmhpd.c:42"],
                },
            },
            "pin_crosschecks": [
                {"signal": "WSA1_EN", "schematic_gpio": 59, "patch_gpio": 59, "match": True,
                 "sha": "deadbeefcafefeed"},
                {"signal": "WSA2_EN", "schematic_gpio": 79, "patch_gpio": None, "match": False,
                 "note": "no candidate patch assigns this GPIO number — needs manual review"},
            ],
        },
    }
    report = _render_onboarding_report(_output_with_generated_case(gc))

    assert "## Kernel History / FROMLIST Findings" in report
    assert "deadbeefcafefeed"[:12] in report
    assert "FROMLIST: arm64: dts: vendor: newboard: Add audio support" in report
    assert "unapplied" in report
    assert "DONORSOC" in report
    assert "qcom,newboard-adsp-pas" in report
    assert "newboard-audio.dtsi" in report

    assert "## Power Model Inspection" in report
    assert "source_confirmed" in report
    assert "rpmhpd" in report
    assert "drivers/pmdomain/qcom/rpmhpd.c:42" in report
    assert "never auto-finalized" in report

    assert "## Pin Cross-Check" in report
    assert "WSA1_EN" in report and "WSA2_EN" in report
    assert "✅ match" in report
    assert "❌ mismatch" in report
    print("PASS: report includes Kernel History / Power Model Inspection / Pin Cross-Check "
          "sections with expected fields when the data is present")


def test_report_omits_new_sections_when_data_absent() -> None:
    """Backward compatibility: a pre-slice-6 generated_case (no candidate_patch_series,
    no audio_topology) must render a report with none of the new sections/headings."""
    gc = {
        "needs_review": ["power_model_source: never auto-finalized — confirm with Power team"],
    }
    report = _render_onboarding_report(_output_with_generated_case(gc))

    assert "## Kernel History / FROMLIST Findings" not in report
    assert "## Power Model Inspection" not in report
    assert "## Pin Cross-Check" not in report
    # pre-existing sections still render unaffected
    assert "## NEEDS_REVIEW" in report
    assert "## Promotion" in report
    print("PASS: report omits all three new sections when kernel_history/power_model_hint/"
          "pin_crosschecks data is absent — additive, backward-compatible")


def test_report_omits_pin_crosscheck_section_when_topology_present_but_no_verdicts() -> None:
    """audio_topology can exist (populated by every slice-6 run) without any pin
    cross-check having occurred (no schematic_nets returned by QGenie) -- that
    sub-section alone must stay absent, independent of the other two."""
    gc = {
        "needs_review": [],
        "audio_topology": {
            "power_model": {"inspection_hint": {"status": "missing"}},
        },
    }
    report = _render_onboarding_report(_output_with_generated_case(gc))
    assert "## Power Model Inspection" in report  # inspection_hint present, even if "missing"
    assert "## Pin Cross-Check" not in report      # no pin_crosschecks key at all
    print("PASS: Pin Cross-Check section independently omitted when no verdicts exist, "
          "even though Power Model Inspection (status=missing) still renders")


def test_report_includes_ipcat_findings_section() -> None:
    """Fix #4: surface audio_topology["ipcat_findings"] as its own section."""
    gc = {
        "needs_review": ["ipcat_coverage: generic_only — IPCAT (MCP) was queried but did not "
                          "report target-specific results."],
        "audio_topology": {
            "ipcat_findings": {
                "status": "generic_only",
                "summary": "IPCAT (MCP) was queried but did not report target-specific results.",
                "offline_files_present": False, "offline_file_count": 0,
                "mcp_requested": True, "mcp_queried_self_reported": True,
                "mcp_returned_target_specific": False, "mcp_returned_generic_only": True,
                "self_report_notes": "only generic multi-SoC HPG chapters returned",
                "self_report_citations": ["ipcat:HPG-generic-ch4"],
            },
        },
    }
    report = _render_onboarding_report(_output_with_generated_case(gc))

    assert "## IPCAT Coverage" in report
    assert "generic_only" in report
    assert "only generic multi-SoC HPG chapters returned" in report
    assert "ipcat:HPG-generic-ch4" in report
    assert "ipcat_coverage: generic_only" in report  # also folded into NEEDS_REVIEW
    print("PASS: report includes IPCAT Coverage section with expected fields when "
          "audio_topology.ipcat_findings is present")


def test_report_omits_ipcat_findings_section_when_absent() -> None:
    gc = {
        "needs_review": [],
        "audio_topology": {"power_model": {"inspection_hint": {"status": "missing"}}},
    }
    report = _render_onboarding_report(_output_with_generated_case(gc))
    assert "## IPCAT Coverage" not in report
    print("PASS: IPCAT Coverage section omitted when audio_topology.ipcat_findings absent, "
          "even though other audio_topology sub-sections are present")


def main() -> None:
    test_report_includes_kernel_history_power_model_and_pin_crosscheck_sections()
    test_report_omits_new_sections_when_data_absent()
    test_report_omits_pin_crosscheck_section_when_topology_present_but_no_verdicts()
    test_report_includes_ipcat_findings_section()
    test_report_omits_ipcat_findings_section_when_absent()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
