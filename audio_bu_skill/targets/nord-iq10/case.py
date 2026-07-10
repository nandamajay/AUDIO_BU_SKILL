"""Nord IQ-10 (SA8797P) audio bring-up — per-target case.

This is the human-authored, per-run half of the bring-up: the target's
identity, its evidence sources, its codec verdicts, and — most importantly
— the analyst judgment (root cause, cited evidence, proposed fix) for the
one real blocker this run hit. The generic walk in orchestrator.bringup_walk
consumes this; none of the prose here is auto-generated.

Real current state (reflected below): DT scaffolding for the ADSP
remoteproc + AudioReach stack landed and builds cleanly (5 commits,
2026-07-09). The drafted `power-domains = <&rpmhpd RPMHPD_LCX/LMX>` wiring's
root cause is confirmed directly against driver source: qcom_q6v5_pas.c
attaches these proxy PDs by name (transport-agnostic, not the blocker);
nord_rpmhpds[] in drivers/pmdomain/qcom/rpmhpd.c deliberately excludes
LCX/LMX (reviewed upstream commit eaefa3d6095), and no SCMI lcx/lmx
precedent exists anywhere in-tree to swap in instead. Both local-file and
MCP IPCAT sources were checked and confirmed structurally incapable of
containing this data. Recorded as a WARNING requiring Power team
confirmation (not a dead-end). The DT node is kept drafted with
status="disabled" and the finding is documented inline in nord-iq10.dtsi.
The run halts in BLOCKED pending that confirmation — not because triage
failed, but because the fix is external to source.
"""

from __future__ import annotations

from orchestrator.bringup_walk import BringupCase

CASE = BringupCase(
    target_soc="SA8797P",
    nearest_target="SA8775P (lemans)",
    run_id="nord-iq10-audio-bringup-2026-07",
    case_version="1.0.0",

    # --- source_intake: INIT -> SCAFFOLD ---
    power_model_source="QGenie deep-research over soc_commit/Confluence/Jira (QSTABILITY-24906579)",
    evidence_source="ipcat_first",
    evidence_roots={
        "ipcat": "Documents/IPCAT",
        "offline_documents": "Documents",
    },
    scaffold_reason="evidence sources resolved (IPCAT + schematics + downstream QGenie research)",

    # --- codec_driver_porting: SCAFFOLD -> PATCH_APPLIED ---
    # PCM1681 DAC + ADAU1979 ADC (ADAU1979 handled by the ADAU1977 driver family).
    kernel_source_path="linux-nord",
    codec_part_numbers=["PCM1681", "ADAU1979"],
    codec_verdicts={
        "PCM1681": {"driver_path": "sound/soc/codecs/pcm1681.c", "status": "upstream_present"},
        "ADAU1979": {"driver_path": "sound/soc/codecs/adau1977.c", "status": "upstream_present"},
    },
    patch_reason="ADSP remoteproc+AudioReach DT scaffolding landed and builds clean "
                 "(commits a80334db73e..9fd9ff82f4f, 2026-07-09 07:58-08:01)",

    # --- triage: PATCH_APPLIED -> TRIAGE -> BLOCKED ---
    triage_input={
        "failed_gate": "compile",
        "transition_reason": "drafted power-domains = <&rpmhpd RPMHPD_LCX/LMX> is known-wrong for an "
                             "SCMI-managed part; cannot proceed to ON_TARGET until the scmiN_pd "
                             "provider+index for the adsp lcx/lmx proxy domains is confirmed",
        "gate_evidence": (
            "Root cause confirmed directly against driver source (not inferred): "
            "drivers/remoteproc/qcom_q6v5_pas.c attaches the adsp proxy PDs by NAME "
            "('lcx'/'lmx' via qcom_pas_pds_attach()/devm_pm_domain_attach_by_name()) — "
            "the driver is transport-agnostic and is not the blocker. "
            "drivers/pmdomain/qcom/rpmhpd.c: nord_rpmhpds[] (commit eaefa3d6095, "
            "reviewed upstream) deliberately excludes RPMHPD_LCX/RPMHPD_LMX (only "
            "CX/EBI/GFX/GFX1/MX/MMCX/MXC/NSP0-3), unlike every other lcx/lmx-gated "
            "adsp-pas platform in-tree (sa8775p, sa8540p, milos, kodiak, sc7280); "
            "'qcom,nord-rpmhpd' structurally cannot expose LCX/LMX. Full-tree grep of "
            "every SCMI-managed peer (nord-sa8797p.dtsi's own <&scmi11_pd N>/<&scmi3_pd 0> "
            "pattern for i2c/ufs, plus every other in-tree SoC) found zero platforms "
            "naming an SCMI power domain 'lcx'/'lmx' — no upstream or linux-next "
            "precedent exists to copy an SCMI index from. IPCAT (local export + MCP "
            "HPG_DOCUMENTS source) independently confirmed to carry no SCMI power-domain "
            "enumeration data at all (structurally out of scope: register/address catalog, "
            "not firmware SCMI mapping)."
        ),
        "diagnosis": {
            "root_cause": "ADSP power-domains drafted against rpmhpd LCX/LMX, which "
                          "'qcom,nord-rpmhpd' structurally does not expose (nord_rpmhpds[] "
                          "omits them by design, per reviewed upstream commit eaefa3d6095). "
                          "No SCMI lcx/lmx precedent exists anywhere in-tree to swap in "
                          "instead. Two candidate fixes, resolvable only by the Power team: "
                          "(1) nord_rpmhpds[] is missing LCX/LMX by omission — needs a "
                          "follow-up driver patch, or (2) Nord intentionally moved adsp "
                          "lcx/lmx to SCMI — needs the real <&scmiN_pd idx> from the "
                          "Power/SCMI-server team, no DT source contains it.",
            "cited_evidence": [
                "linux-nord/drivers/remoteproc/qcom_q6v5_pas.c",
                "linux-nord/drivers/pmdomain/qcom/rpmhpd.c",
                "linux-nord/arch/arm64/boot/dts/qcom/nord-sa8797p.dtsi",
                "AUDIO_EVIDENCE_TABLE.md#L72-L74",
            ],
            "proposed_fix": "kept power-domains = <&rpmhpd RPMHPD_LCX/LMX> as drafted "
                            "(mirrors lemans structurally, node left status=\"disabled\"); "
                            "marked WARNING(sa8797p-audio) in nord-iq10.dtsi pending Power "
                            "team confirmation of which fix applies before enabling",
            "failure_category": "compile",
            "needs_external_input": "Power team confirmation: rpmhpd driver fix (add "
                                    "LCX/LMX to nord_rpmhpds[]) vs. real <&scmiN_pd idx> "
                                    "for adsp lcx/lmx — root cause is nailed, exact fix "
                                    "value is not",
        },
    },
    blocked_reason="root cause confirmed (nord_rpmhpds[] excludes LCX/LMX by design; no "
                   "SCMI lcx/lmx precedent in-tree) but the fix itself is a warning "
                   "pending Power team confirmation, not something triage/DT-authoring "
                   "can resolve unilaterally — node kept disabled and flagged in-tree",

    # blocker taxonomy (structured, for run_manifest reporting)
    blocked_category="external_team_input",
    blocked_owner="power-team",
    expected_unblock_signal="Power team confirms rpmhpd LCX/LMX driver fix "
                            "(add to nord_rpmhpds[]) vs. real <&scmiN_pd idx> for adsp lcx/lmx",

    # boot_outcome / audio_outcome intentionally unset: this run halts at BLOCKED
    # before reaching ON_TARGET, pending the Power-team answer.
)
