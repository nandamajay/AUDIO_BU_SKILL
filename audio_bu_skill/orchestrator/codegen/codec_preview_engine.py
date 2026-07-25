"""CodecPreviewEngine — Pipeline-2 codec preview lane (G-3B-beta, WP).

Preview-only replacement for ``NullEngine`` on the ``codec_generation`` lane.
Emits reviewer-facing codec driver *previews* — never a diff, never a
cross-verification row, never a disk write. Sits behind the same
``CodegenEngine`` ABC and is reached only via ``resolve_engine("codec_preview")``.

Contract (this WP, non-negotiable):

1. **Disclosure-only.** Every ``Change`` this engine emits carries reviewer
   disclosures in ``needs_review`` and a body preview in ``rationale``. Nothing
   this engine returns is shaped to be indexed as ``cross_verification.rows``.
2. **Provenance-guarded.** Codec identity comes from ``target_profile["codecs"]``
   (candidate-derived) and provenance from ``target_profile["codec_source"]``
   (candidate-derived path, if any). Every emitted ``Change`` inherits the
   labels ``candidate-derived / NOT independently verified`` and, for T4a-derived
   facts, ``same-source presence signal / NOT cross-verified`` (G-3A.11).
3. **No PASS from generator output.** Fresh authoritative evidence is required
   before any new cross-verification PASS/MATCH is recorded. This engine's
   output is not a cross-verification input.
4. **No cross-pipeline coupling.** Pipeline 1 (``orchestrator/generation``) is
   not imported, referenced, or diffed. ``is_open()``, ``_GATING_OPEN_VERDICTS``,
   and ``_rows_with_prefix`` are not touched.

The engine is reached via ``resolve_engine("codec_preview")``. It is NOT wired
into ``--generate`` or any CLI mode — reachable only through test or explicit
envelope override.
"""

from __future__ import annotations

from typing import Any

from orchestrator.codegen.engine import CodegenEngine, _ENGINES
from orchestrator.codegen.models import Change, ChangeSet

_ENGINE_ID = "codec_preview"

# Disclosure lines are deterministic, sorted at emission time, and byte-stable
# across runs. They are the enforcement surface of the disclosure-only rule.
_REVIEWER_DISCLOSURES: tuple[str, ...] = (
    "REVIEWER: confirm MCLK feed (LPASS vs. crystal) against schematic",
    "REVIEWER: confirm codec-domain output-enable line against schematic",
    "REVIEWER: confirm reset-gpios pin against schematic",
)

_PROV_T4A = (
    "PROVENANCE: T4a QUP MATCH is same-source (IPCAT-vs-IPCAT); "
    "NOT cross-verified per G-3A.11"
)


def _provenance_codec_source(codec_source: str | None) -> str:
    """Return the codec-source provenance line, honestly labeled.

    A populated ``codec_source`` yields the candidate-derived label. Absence is
    reported explicitly — never silently dropped, so the reviewer always sees
    the provenance state.
    """
    if codec_source:
        return (
            f"PROVENANCE: codec source is candidate-derived from {codec_source}, "
            "NOT independently verified"
        )
    return "PROVENANCE: no codec source path provided"


def _parse_compatible(compat: str) -> tuple[str, str] | None:
    """Split a ``"vendor,part"`` compatible string. Return None if malformed.

    Malformed entries are skipped (no ``Change`` emitted), not raised — the
    engine is preview-only and MUST NOT halt on a bad profile row.
    """
    if not isinstance(compat, str) or "," not in compat:
        return None
    vendor, _, part = compat.partition(",")
    vendor = vendor.strip()
    part = part.strip()
    if not vendor or not part:
        return None
    return vendor, part


def _preview_body(vendor: str, part: str, codec_source: str | None) -> str:
    """Render the preview body for one codec. String-only, multi-line, in rationale.

    Deliberately minimal: a stub kernel-style header comment + a MODULE_DEVICE_TABLE
    line + a footer marker. Real codec source generation is out of scope for this
    WP — this is the *reviewer preview*, not a compilable driver.
    """
    provenance_note = (
        f"candidate-derived from {codec_source}" if codec_source else "no codec source path"
    )
    return (
        f"// SPDX-License-Identifier: GPL-2.0-only\n"
        f"// codec preview for {vendor},{part}\n"
        f"// {provenance_note}; NOT independently verified\n"
        f"// disclosure-only — reviewer must confirm reset/MCLK/OE against schematic\n"
        f"\n"
        f"static const struct of_device_id {part}_of_match[] = {{\n"
        f'\t{{ .compatible = "{vendor},{part}" }},\n'
        f"\t{{ }},\n"
        f"}};\n"
        f"MODULE_DEVICE_TABLE(of, {part}_of_match);\n"
        f"\n"
        f"// END preview ({vendor},{part})\n"
    )


class CodecPreviewEngine(CodegenEngine):
    """Pipeline-2 codec preview engine (G-3B-beta).

    ``generate(task_spec)`` returns a ``ChangeSet`` whose ``Change`` entries are
    reviewer-attached disclosures with a body preview in ``rationale``. Never
    emits a unified_diff. Never writes disk. Never feeds cross-verification.
    """

    engine_id = _ENGINE_ID

    def generate(self, task_spec: dict[str, Any]) -> ChangeSet:
        skill_id = str(task_spec.get("skill_id", ""))
        target = str(task_spec.get("target", ""))
        target_profile = task_spec.get("target_profile") or {}

        # Codec identity comes from the profile — never hardcoded, never derived
        # from Pipeline 1's static ``_NORD_CODECS`` dict.
        raw_codecs = target_profile.get("codecs") if isinstance(target_profile, dict) else None
        codec_source = (
            target_profile.get("codec_source") if isinstance(target_profile, dict) else None
        )
        if not isinstance(codec_source, str) or not codec_source:
            codec_source = None

        parsed: list[tuple[str, str]] = []
        if isinstance(raw_codecs, list):
            for entry in raw_codecs:
                pair = _parse_compatible(entry)
                if pair is not None:
                    parsed.append(pair)

        if not parsed:
            return ChangeSet(
                skill_id=skill_id,
                target=target,
                engine_id=self.engine_id,
                changes=[],
                summary="codec preview: no codecs in profile — preview skipped",
            )

        # Deterministic order: sort by part, then vendor. Same input → same output.
        parsed.sort(key=lambda p: (p[1], p[0]))

        prov_codec_source = _provenance_codec_source(codec_source)
        base_needs_review = sorted(
            (prov_codec_source, _PROV_T4A) + _REVIEWER_DISCLOSURES
        )

        changes: list[Change] = []
        for vendor, part in parsed:
            changes.append(
                Change(
                    path=f"sound/soc/codecs/{part}-preview.c",
                    change_type="create",
                    skill_id=skill_id,
                    unified_diff="",  # foundation contract: no diff in this WP
                    rationale=_preview_body(vendor, part, codec_source),
                    needs_review=list(base_needs_review),
                )
            )

        return ChangeSet(
            skill_id=skill_id,
            target=target,
            engine_id=self.engine_id,
            changes=changes,
            summary=(
                f"codec preview: {len(changes)} codec(s), "
                "provenance-labeled, disclosure-only"
            ),
        )


# Register with the ABC factory. Unknown-name fallback in ``resolve_engine``
# still points at NullEngine — this registration is additive.
_ENGINES[_ENGINE_ID] = CodecPreviewEngine
