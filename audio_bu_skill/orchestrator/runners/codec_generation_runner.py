"""codec_generation runner (Phase 2 foundation — INERT).

Builds a ``task_spec`` from the input envelope and asks a ``CodegenEngine`` to
propose codec driver source (sound/soc/codecs/). In the foundation the default ``NullEngine`` returns an **empty**
ChangeSet, so this runner generates nothing, writes nothing, and never touches the
kernel tree — swapping the engine (see orchestrator.codegen.engine) is the entire
remaining Phase-2 implementation.

**Not registered in any CLI mode.** No ``--generate`` mode exists; nothing in the
shipped tool reaches this runner. Tests call it directly.
"""

from __future__ import annotations

from typing import Any

from orchestrator.codegen.engine import resolve_engine

SKILL_ID = "codec_generation"


def run_codec_generation(input_envelope: dict[str, Any]) -> dict[str, Any]:
    target_name = input_envelope["target_name"]
    target_profile = input_envelope.get("target_profile") or {}

    # engine_id defaults to "null" (the inert NullEngine); an unknown id also falls
    # back to NullEngine in resolve_engine, so the foundation can never accidentally
    # activate generation.
    engine = resolve_engine(input_envelope.get("engine_id", "null"))

    task_spec = {
        "skill_id": SKILL_ID,
        "target": target_name,
        "run_id": input_envelope["run_id"],
        "target_profile": target_profile,
        # Provenance guard (WP G-3B-beta §2): every downstream engine sees the
        # honest provenance state of the profile it is conditioned on. Codec
        # source paths come from candidate .dts material (G-3A.9); T4a QUP MATCH
        # is same-source per G-3A.11. Neither is independently verified.
        "provenance": _provenance_from_profile(target_profile),
    }
    change_set = engine.generate(task_spec)

    # Cite whatever the caller conditioned generation on (profile-derived files /
    # evidence). In the foundation the profile is the sole evidence; a real engine
    # would add the specific source files it read.
    evidence_refs = _evidence_refs(input_envelope, target_profile)

    return {
        "change_set": change_set.to_dict(),
        "human_review_needed": not change_set.is_empty(),
        "evidence": {"evidence_refs": evidence_refs},
    }


def _evidence_refs(input_envelope: dict[str, Any], target_profile: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    cites = target_profile.get("cites") if isinstance(target_profile, dict) else None
    if isinstance(cites, dict):
        for cite_list in cites.values():
            if isinstance(cite_list, list):
                refs.extend(str(c) for c in cite_list)
    # A profile with no cited files still yields at least one honest reference so the
    # evidence gate has something to record.
    if not refs:
        refs.append(f"target_profile:{input_envelope.get('target_name', '')}")
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _provenance_from_profile(target_profile: dict[str, Any]) -> dict[str, Any]:
    """Extract the provenance state of a target profile (WP G-3B-beta §2).

    Honest labels only — engines downstream inherit these into their disclosure
    payload. ``independently_verified`` and ``same_source_t4a`` are hard-wired
    to reflect the current trust state (G-3A.11): candidate .dts material is
    NOT independently verified, and T4a QUP MATCH is same-source (IPCAT vs.
    IPCAT). Neither flag flips until authority integration lands.
    """
    codec_source = (
        target_profile.get("codec_source") if isinstance(target_profile, dict) else None
    )
    if not isinstance(codec_source, str) or not codec_source:
        codec_source = None
    return {
        "codec_source_path": codec_source,
        "candidate_derived": bool(codec_source),
        "independently_verified": False,
        "same_source_t4a": True,
    }
