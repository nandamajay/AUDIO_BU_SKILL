"""Feature extraction for target similarity (v1.1 Phase 1).

Pure, offline, deterministic. Given a kernel git checkout + evidence folders
(for a *new* target) or an existing target's ``BringupCase`` (for a DB entry),
build a ``TargetProfile``: a small bag of audio-bring-up signals, each recording
the file(s) it was derived from so the onboarding report can cite its evidence.

No new dependencies, no network, no LLM: every signal is a regex/glob over the
kernel tree or a read of case fields, so a profile is reproducible and hashable.
Signals that cannot be determined are left empty and reported ``n/a`` by the
scoring engine rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# where audio DT + codec drivers live in a mainline-style kernel tree
# --------------------------------------------------------------------------- #
_QCOM_DTS_REL = "arch/arm64/boot/dts/qcom"
_CODECS_REL = "sound/soc/codecs"

# audio-relevant compatible substrings (kept broad but audio-scoped so we don't
# pick up every unrelated node in a full SoC .dtsi).
_AUDIO_COMPAT_HINTS = (
    "audio", "codec", "q6", "apr", "apm", "audioreach", "lpass", "lpi",
    "soundwire", "swr", "wcd", "wsa", "va-macro", "rx-macro", "tx-macro",
    "w, ", "dai", "sndcard", "sound",
)
_AUDIOREACH_HINTS = ("q6apm", "audioreach", "q6dsp", "gprbus", "gpr", "apm")
_SOUNDWIRE_HINTS = ("soundwire", "swr-", "swr_", "qcom,soundwire")

_COMPATIBLE_RE = re.compile(r'compatible\s*=\s*"([^"]+)"')
_POWER_DOMAIN_PROVIDER_RE = re.compile(r"power-domains\s*=\s*<\s*&(\w+)")
_ROOT_COMPAT_SOC_RE = re.compile(r'"qcom,([a-z0-9]+)"')


@dataclass
class TargetProfile:
    """A comparable feature bag for one audio bring-up target.

    Every signal set records where it came from in ``cites`` (signal -> sorted
    list of file paths) so a similarity result can be justified with evidence.
    """

    target_name: str
    soc: str = ""
    codecs: set[str] = field(default_factory=set)
    dt_compatibles: set[str] = field(default_factory=set)
    power_domain_providers: set[str] = field(default_factory=set)
    audioreach: bool | None = None            # None == undetectable (n/a)
    soundwire: dict[str, Any] = field(default_factory=lambda: {"present": None, "master_count": 0})
    cites: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "soc": self.soc,
            "codecs": sorted(self.codecs),
            "dt_compatibles": sorted(self.dt_compatibles),
            "power_domain_providers": sorted(self.power_domain_providers),
            "audioreach": self.audioreach,
            "soundwire": dict(self.soundwire),
            "cites": {k: sorted(v) for k, v in self.cites.items()},
        }


def _cite(profile: TargetProfile, signal: str, path: str) -> None:
    profile.cites.setdefault(signal, [])
    if path not in profile.cites[signal]:
        profile.cites[signal].append(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return ""


def _codec_driver_stems(kernel_source: Path) -> dict[str, str]:
    """Map an upper-cased codec token -> its ASoC driver file (for citation).

    Stem ``pcm1681`` from ``sound/soc/codecs/pcm1681.c`` becomes key ``PCM1681``.
    """
    stems: dict[str, str] = {}
    codecs_dir = kernel_source / _CODECS_REL
    if not codecs_dir.is_dir():
        return stems
    for c_file in sorted(codecs_dir.glob("*.c")):
        stems[c_file.stem.upper()] = str(c_file)
    return stems


def _dtsi_family(kernel_source: Path, target_name: str, soc_hint: str) -> list[Path]:
    """The .dtsi/.dts files that describe *this* target's audio, matched by name.

    Matched strictly against the target name or SoC hint. We deliberately do NOT
    fall back to "every qcom .dtsi": a brand-new target has no .dtsi yet (that is
    what Phase-2 generation would produce), and scanning the whole SoC family
    would fold every unrelated platform's codecs/power-domains into this target's
    profile — misleading noise. No match => no DT signals from the kernel (the new
    target's signals then come from evidence), which is the honest result.
    """
    dts_dir = kernel_source / _QCOM_DTS_REL
    if not dts_dir.is_dir():
        return []
    all_dts = sorted(p for p in dts_dir.glob("*.dts*") if p.is_file())
    needles = [n.lower() for n in (target_name, soc_hint) if n]
    if not needles:
        return []
    return [p for p in all_dts if any(n in p.name.lower() for n in needles)]


def _extract_from_kernel(profile: TargetProfile, kernel_source: Path, target_name: str) -> None:
    """Fill DT/power/audioreach/soundwire signals from the kernel tree in place."""
    codec_stems = _codec_driver_stems(kernel_source)
    dtsi_files = _dtsi_family(kernel_source, target_name, profile.soc)

    for dts in dtsi_files:
        text = _read_text(dts)
        if not text:
            continue
        cite_path = str(dts)

        # SoC identity from the first qcom root compatible we haven't set yet.
        if not profile.soc:
            soc_match = _ROOT_COMPAT_SOC_RE.search(text)
            if soc_match:
                profile.soc = soc_match.group(1).upper()
                _cite(profile, "soc", cite_path)

        for compat in _COMPATIBLE_RE.findall(text):
            low = compat.lower()
            if any(hint in low for hint in _AUDIO_COMPAT_HINTS):
                profile.dt_compatibles.add(compat)
                _cite(profile, "dt_compatibles", cite_path)
            if any(hint in low for hint in _AUDIOREACH_HINTS):
                profile.audioreach = True
                _cite(profile, "audioreach", cite_path)
            if any(hint in low for hint in _SOUNDWIRE_HINTS):
                profile.soundwire["present"] = True
                profile.soundwire["master_count"] += 1
                _cite(profile, "soundwire", cite_path)

        for provider in _POWER_DOMAIN_PROVIDER_RE.findall(text):
            profile.power_domain_providers.add(provider)
            _cite(profile, "power_domain_providers", cite_path)

        # Codec presence: any codec driver stem named in this audio DT file.
        upper = text.upper()
        for stem_upper, driver_file in codec_stems.items():
            if stem_upper in upper:
                profile.codecs.add(stem_upper)
                _cite(profile, "codecs", driver_file)

    # If we saw audio DT but no AudioReach/SoundWire signature, they are absent
    # (False), not undetectable (None). Only leave None when there was no DT at all.
    if dtsi_files:
        if profile.audioreach is None:
            profile.audioreach = False
        if profile.soundwire["present"] is None:
            profile.soundwire["present"] = False


def _extract_from_case(profile: TargetProfile, case: Any, kernel_source: Path | None) -> None:
    """Fill signals from an existing target's BringupCase (the DB entry path)."""
    case_file = f"targets/{profile.target_name}/case.py"

    if getattr(case, "target_soc", ""):
        profile.soc = str(case.target_soc).upper()
        _cite(profile, "soc", case_file)

    for part in getattr(case, "codec_part_numbers", []) or []:
        profile.codecs.add(str(part).upper())
        _cite(profile, "codecs", case_file)

    # codec_verdicts carry the driver path each codec resolved to — cite it and,
    # when the driver is present on the resolved tree, record the file.
    verdicts = getattr(case, "codec_verdicts", {}) or {}
    for part, verdict in verdicts.items():
        driver_rel = (verdict or {}).get("driver_path")
        if driver_rel and kernel_source is not None:
            driver_path = kernel_source / driver_rel
            if driver_path.is_file():
                _cite(profile, "codecs", str(driver_path))


def extract_profile(
    *,
    target_name: str,
    kernel_source: str | Path | None,
    evidence_roots: dict[str, str] | None = None,
    case: Any | None = None,
) -> TargetProfile:
    """Build a TargetProfile for one target.

    - ``case`` given (an existing DB target): codecs/SoC come from the case; DT
      signals are extracted from ``kernel_source`` when that tree is present.
    - ``case`` None (the new target being onboarded): everything is extracted
      from ``kernel_source`` (+ evidence folder names as codec hints).
    """
    profile = TargetProfile(target_name=target_name)
    kernel_path = Path(kernel_source).expanduser() if kernel_source else None

    if case is not None:
        _extract_from_case(profile, case, kernel_path)

    if kernel_path is not None and kernel_path.is_dir():
        _extract_from_kernel(profile, kernel_path, target_name)

    # Evidence folder file *names* are a cheap, honest codec hint for a new
    # target (datasheet filenames routinely contain the part number). We only
    # match against codec driver stems that actually exist in the tree.
    if case is None and kernel_path is not None and evidence_roots:
        stems = _codec_driver_stems(kernel_path)
        for root_rel in evidence_roots.values():
            root = Path(root_rel)
            if not root.is_absolute() and kernel_path is not None:
                # evidence roots are workspace-relative; try as-given too.
                pass
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if not f.is_file():
                    continue
                name_upper = f.name.upper()
                for stem_upper, driver_file in stems.items():
                    if stem_upper in name_upper:
                        profile.codecs.add(stem_upper)
                        _cite(profile, "codecs", str(f))

    return profile
