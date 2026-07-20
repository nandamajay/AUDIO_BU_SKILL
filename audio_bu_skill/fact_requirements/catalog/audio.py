"""Phase-3A WP-D — Audio domain fact families.

Eleven ``Audio.*`` families that describe every fact class the audio
bring-up skill treats as first-class. Per-subject requiredness matches
PHASE3_ARCHITECTURE.md §5.5's threshold table:

  * Audio.GPIO / Audio.QUP / Audio.CLOCK / Audio.POWER /
    Audio.SMMU_SID / Audio.ADSP_REG_BASE / Audio.AUDIOREACH_PORT /
    Audio.CODEC_BINDING       — 100% MANDATORY subjects, ``critical=True``.
  * Audio.INTERCONNECT        — 100% MANDATORY paths-in-use.
  * Audio.DSP_TOPOLOGY / Audio.MBHC_THRESHOLD — advisory-only.

Subject patterns are literal identifiers unless flagged ``is_regex=True``.
Regex forms are used sparingly for enumerable-but-numbered subjects
(``MI2S<n>``, ``QUP<n>``) so the catalog captures the *shape* of a required
fact without hard-coding every instance.

Phase-3A does not enforce ``promotion_relevant`` / ``generation_relevant``
— they exist so later phases (case.py promotion, code generation) can key
off the same catalog without a schema change.
"""

from __future__ import annotations

from audio_bu_skill.fact_requirements.schema import (
    Authority,
    Domain,
    FactFamilyDef,
    Requiredness,
    SubjectRequirement,
)

# ─────────────────────────────────────────────────────────────────────────
# 1. Audio.GPIO
# ─────────────────────────────────────────────────────────────────────────

_GPIO = FactFamilyDef(
    domain=Domain.AUDIO,
    name="GPIO",
    description="TLMM GPIO pins used for audio (I2S/TDM data/clock/frame lines).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.SCHEMATIC_PDF, Authority.KERNEL_DTS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"MI2S[0-9]+_(SCK|WS|SD0|SD1|SD2|SD3)",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="Every claimed I2S/TDM pin must have a concrete GPIO number.",
        ),
        SubjectRequirement(
            subject_pattern=r"TDM[0-9]+_(SCK|WS|SD)",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="TDM pin numbering (when TDM is used instead of I2S).",
        ),
        SubjectRequirement(
            subject_pattern=r"MI2S[0-9]+_MCLK",
            requiredness=Requiredness.ADVISORY,
            promotion_relevant=False,
            generation_relevant=True,
            is_regex=True,
            notes="MCLK is optional depending on codec.",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY. See Nord IQ-10 I2S8 pinmux.",
)

# ─────────────────────────────────────────────────────────────────────────
# 2. Audio.QUP
# ─────────────────────────────────────────────────────────────────────────

_QUP = FactFamilyDef(
    domain=Domain.AUDIO,
    name="QUP",
    description="QUP (Qualcomm Universal Peripheral) I2C/SPI instances used to talk to codecs.",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.KERNEL_DTS, Authority.KERNEL_BINDINGS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"QUP[0-9]+_I2C_SLAVE_ADDR",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="Slave address on the QUP I2C bus.",
        ),
        SubjectRequirement(
            subject_pattern=r"QUP[0-9]+_BASE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="QUP register base — verified against IPCAT.",
        ),
        SubjectRequirement(
            subject_pattern=r"QUP[0-9]+_INSTANCE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="Which QUP core instance owns the bus (e.g. QUPV3_SE0).",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY on used QUPs.",
)

# ─────────────────────────────────────────────────────────────────────────
# 3. Audio.CLOCK
# ─────────────────────────────────────────────────────────────────────────

_CLOCK = FactFamilyDef(
    domain=Domain.AUDIO,
    name="CLOCK",
    description="Audio-domain clock sources, rates and parent trees (LPASS/CDC).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.KERNEL_DTS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"LPASS_AUDIO_HM_(H|L)_CLK",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="Top-level audio hardware manager clocks.",
        ),
        SubjectRequirement(
            subject_pattern=r"LPASS_CORE_CC_(EXT_)?MCLK[0-9]+_CLK",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="MCLK feeding codecs — verified via IPCAT clock plan.",
        ),
        SubjectRequirement(
            subject_pattern=r"MI2S[0-9]+_IBIT_CLK",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="Bit clock per used MI2S port.",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY on used audio clocks.",
)

# ─────────────────────────────────────────────────────────────────────────
# 4. Audio.POWER
# ─────────────────────────────────────────────────────────────────────────

_POWER = FactFamilyDef(
    domain=Domain.AUDIO,
    name="POWER",
    description="Regulators / voltage rails powering the audio subsystem (LCX, LMX, VDD_AUDIO...).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.SCHEMATIC_PDF, Authority.KERNEL_DTS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern="VDD_LCX",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="LPASS core rail. Nord IQ-10 FIXME still open.",
        ),
        SubjectRequirement(
            subject_pattern="VDD_LMX",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="LPASS memory rail. Nord IQ-10 FIXME still open.",
        ),
        SubjectRequirement(
            subject_pattern="VDD_AUDIO_CODEC",
            requiredness=Requiredness.ADVISORY,
            promotion_relevant=False,
            generation_relevant=True,
            notes="Codec-side supply; some codecs self-power.",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY on required rails.",
)

# ─────────────────────────────────────────────────────────────────────────
# 5. Audio.SMMU_SID
# ─────────────────────────────────────────────────────────────────────────

_SMMU_SID = FactFamilyDef(
    domain=Domain.AUDIO,
    name="SMMU_SID",
    description="SMMU stream IDs bound to the audio DMA masters (ADSP → APPS crossings).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.KERNEL_DTS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern="LPASS_APPS_SMMU_SID",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="Stream ID for ADSP DMA access into APPS memory.",
        ),
        SubjectRequirement(
            subject_pattern="LPASS_LPI_SMMU_SID",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="Stream ID for LPI island DMA.",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY on used SIDs.",
)

# ─────────────────────────────────────────────────────────────────────────
# 6. Audio.ADSP_REG_BASE
# ─────────────────────────────────────────────────────────────────────────

_ADSP_REG_BASE = FactFamilyDef(
    domain=Domain.AUDIO,
    name="ADSP_REG_BASE",
    description="Register base addresses of ADSP-visible peripherals (LPASS, HM, WCSS-audio).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED,),
    allowed_manual=False,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern="LPASS_TOP_BASE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="LPASS top-level register base — must come from IPCAT.",
        ),
        SubjectRequirement(
            subject_pattern="LPASS_AUDIO_HM_BASE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="Audio HW-manager base.",
        ),
        SubjectRequirement(
            subject_pattern="LPASS_CORE_CC_BASE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            notes="LPASS core clock controller base.",
        ),
    ),
    notes="Manual override disallowed (§5.5) — register bases are hardware fact.",
)

# ─────────────────────────────────────────────────────────────────────────
# 7. Audio.AUDIOREACH_PORT
# ─────────────────────────────────────────────────────────────────────────

_AUDIOREACH_PORT = FactFamilyDef(
    domain=Domain.AUDIO,
    name="AUDIOREACH_PORT",
    description="AudioReach port bindings (logical port ↔ HW resource) for each audio path.",
    primary_authorities=(Authority.ACDB_EXPORT,),
    fallback_authorities=(Authority.KERNEL_DTS, Authority.KERNEL_BINDINGS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"AR_PORT_[A-Z0-9_]+",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="One MANDATORY entry per used AudioReach port.",
        ),
    ),
    notes="Nord IQ-10 open FIXME: logical port assignment for I2S8.",
)

# ─────────────────────────────────────────────────────────────────────────
# 8. Audio.INTERCONNECT
# ─────────────────────────────────────────────────────────────────────────

_INTERCONNECT = FactFamilyDef(
    domain=Domain.AUDIO,
    name="INTERCONNECT",
    description="NoC / bus interconnect paths carrying audio traffic (ADSP ↔ DDR, ADSP ↔ QUP).",
    primary_authorities=(Authority.IPCAT_LIVE,),
    fallback_authorities=(Authority.IPCAT_CACHED, Authority.KERNEL_DTS),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"ICC_[A-Z0-9_]+_TO_[A-Z0-9_]+",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="One MANDATORY entry per path in use (§5.5: 100% of paths-in-use).",
        ),
    ),
    notes="Only paths in use — dormant paths do not need to be catalogued.",
)

# ─────────────────────────────────────────────────────────────────────────
# 9. Audio.CODEC_BINDING
# ─────────────────────────────────────────────────────────────────────────

_CODEC_BINDING = FactFamilyDef(
    domain=Domain.AUDIO,
    name="CODEC_BINDING",
    description="Codec device bindings: codec type, I2C address, reset GPIO, IRQ.",
    primary_authorities=(Authority.KERNEL_BINDINGS,),
    fallback_authorities=(Authority.KERNEL_DTS, Authority.SCHEMATIC_PDF),
    allowed_manual=True,
    critical=True,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"CODEC_[A-Za-z0-9_]+_COMPATIBLE",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="DT compatible string for each attached codec.",
        ),
        SubjectRequirement(
            subject_pattern=r"CODEC_[A-Za-z0-9_]+_I2C_ADDR",
            requiredness=Requiredness.MANDATORY,
            promotion_relevant=True,
            generation_relevant=True,
            is_regex=True,
            notes="I2C address per codec.",
        ),
        SubjectRequirement(
            subject_pattern=r"CODEC_[A-Za-z0-9_]+_RESET_GPIO",
            requiredness=Requiredness.ADVISORY,
            promotion_relevant=False,
            generation_relevant=True,
            is_regex=True,
            notes="Some codecs have no external reset.",
        ),
    ),
    notes="§5.5 threshold: 100% MANDATORY per codec present.",
)

# ─────────────────────────────────────────────────────────────────────────
# 10. Audio.DSP_TOPOLOGY  (advisory-only)
# ─────────────────────────────────────────────────────────────────────────

_DSP_TOPOLOGY = FactFamilyDef(
    domain=Domain.AUDIO,
    name="DSP_TOPOLOGY",
    description="AudioReach graph topology (calibration blob metadata: use-cases, tags).",
    primary_authorities=(Authority.ACDB_EXPORT,),
    fallback_authorities=(),
    allowed_manual=True,
    critical=False,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"USECASE_[A-Z0-9_]+",
            requiredness=Requiredness.ADVISORY,
            promotion_relevant=False,
            generation_relevant=False,
            is_regex=True,
            notes="Each use-case in the ACDB is nice to enumerate but never blocks a run.",
        ),
    ),
    notes="Advisory-only per §5.5 — never gates verdicts.",
)

# ─────────────────────────────────────────────────────────────────────────
# 11. Audio.MBHC_THRESHOLD  (advisory-only)
# ─────────────────────────────────────────────────────────────────────────

_MBHC_THRESHOLD = FactFamilyDef(
    domain=Domain.AUDIO,
    name="MBHC_THRESHOLD",
    description="Headset MBHC (multi-button headset control) thresholds and impedance ranges.",
    primary_authorities=(Authority.KERNEL_DTS,),
    fallback_authorities=(Authority.KERNEL_BINDINGS,),
    allowed_manual=True,
    critical=False,
    subject_requirements=(
        SubjectRequirement(
            subject_pattern=r"MBHC_BUTTON_[0-9]_UV",
            requiredness=Requiredness.ADVISORY,
            promotion_relevant=False,
            generation_relevant=False,
            is_regex=True,
            notes="Threshold microvolts per button. Advisory — tuned per HW.",
        ),
    ),
    notes="Advisory-only per §5.5 — never gates verdicts.",
)


FAMILIES: tuple[FactFamilyDef, ...] = (
    _GPIO,
    _QUP,
    _CLOCK,
    _POWER,
    _SMMU_SID,
    _ADSP_REG_BASE,
    _AUDIOREACH_PORT,
    _INTERCONNECT,
    _CODEC_BINDING,
    _DSP_TOPOLOGY,
    _MBHC_THRESHOLD,
)

__all__ = ["FAMILIES"]
