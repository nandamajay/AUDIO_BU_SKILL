"""target_onboarding runner: nearest-target detection + proposed case (v1.1 Phase 1).

Read-only and offline. Extracts a feature profile for the new target from the
kernel tree + evidence, builds profiles for every existing target from its
case.py, ranks them by weighted similarity (orchestrator.similarity), and derives
a *proposed* set of BringupCase fields. Uncertain fields are listed in
``needs_review`` and never presented as finalized. This runner returns data only;
do_onboard writes the artifacts (case.generated.py etc.). It NEVER generates
kernel code, compiles, or writes case.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.similarity import confidence as compute_confidence
from orchestrator.similarity import extract_profile, rank
from orchestrator.similarity.engine import WEIGHTS

# Evidence-source default carried into every generated case (v1.0 default).
_DEFAULT_EVIDENCE_SOURCE = "ipcat_first"


def _resolve(workspace_root: Path, rel_or_abs: str) -> Path:
    candidate = Path(rel_or_abs)
    return candidate if candidate.is_absolute() else (workspace_root / candidate)


def _load_db_profiles(
    workspace_root: Path,
    targets_root: Path,
    exclude: str,
    new_kernel_source: Path | None,
) -> list:
    """Build a TargetProfile for every existing target except ``exclude``.

    Uses main.load_case so inheritance is resolved exactly as a real run would.
    Imported lazily to avoid a circular import (main imports this runner).
    """
    from orchestrator.main import load_case  # lazy: breaks the import cycle

    profiles = []
    if not targets_root.is_dir():
        return profiles
    for entry in sorted(targets_root.iterdir()):
        if not entry.is_dir() or entry.name == exclude:
            continue
        if not (entry / "case.py").is_file():
            continue
        try:
            case = load_case(entry.name)
        except SystemExit:
            continue  # a malformed/other-target case must not break onboarding
        # Prefer the DB target's own kernel tree for codec-driver citation; fall
        # back to the new target's tree (they are usually the same checkout).
        db_kernel_rel = getattr(case, "kernel_source_path", "") or ""
        db_kernel = _resolve(workspace_root, db_kernel_rel) if db_kernel_rel else new_kernel_source
        profiles.append(
            extract_profile(
                target_name=entry.name,
                kernel_source=db_kernel,
                case=case,
            )
        )
    return profiles


def run_target_onboarding(input_envelope: dict[str, Any]) -> dict[str, Any]:
    workspace_context = input_envelope["workspace_context"]
    target_name = input_envelope["target_name"]
    kernel_source_path = input_envelope["kernel_source_path"]
    run_id = input_envelope["run_id"]
    evidence_roots = input_envelope.get("evidence_roots") or {}

    workspace_root = Path(workspace_context["workspace_root"])
    targets_root_rel = input_envelope.get("target_db_root") or "audio_bu_skill/targets"
    targets_root = _resolve(workspace_root, targets_root_rel)
    kernel_source = _resolve(workspace_root, kernel_source_path)

    # --- profiles: new target + existing DB ---
    new_profile = extract_profile(
        target_name=target_name,
        kernel_source=kernel_source,
        evidence_roots=evidence_roots,
        case=None,
    )
    db_profiles = _load_db_profiles(workspace_root, targets_root, exclude=target_name,
                                    new_kernel_source=kernel_source)
    ranked = rank(new_profile, db_profiles)
    conf = compute_confidence(ranked)
    low_confidence = bool(conf["low_confidence"])

    # --- evidence inventory: files consulted (evidence + cited kernel files) ---
    evidence_files: list[str] = []
    for root_rel in evidence_roots.values():
        root = _resolve(workspace_root, root_rel)
        if root.is_dir():
            evidence_files.extend(str(f) for f in sorted(root.rglob("*")) if f.is_file())
    cited_kernel_files: list[str] = []
    for cite_list in new_profile.cites.values():
        cited_kernel_files.extend(cite_list)
    evidence_refs = _dedup(evidence_files + cited_kernel_files)

    # --- derive the proposed case fields ---
    needs_review: list[str] = []

    top_name = ranked[0].target_name if ranked else ""
    if top_name:
        nearest_target = top_name
        if low_confidence:
            needs_review.append(
                f"nearest_target: low-confidence match ({conf['score']:.2f}, "
                f"margin {conf['margin']:.2f}) — confirm before trusting"
            )
    else:
        nearest_target = "UNKNOWN (no existing target to compare against)"
        needs_review.append("nearest_target: no candidates in target DB")

    # inherit_from is only auto-set on a confident match; otherwise left empty.
    inherit_from = top_name if (top_name and not low_confidence) else ""
    if top_name and low_confidence:
        needs_review.append("inherit_from: left empty pending nearest_target confirmation")

    target_soc = new_profile.soc
    if not target_soc:
        target_soc = "UNKNOWN"
        needs_review.append("target_soc: could not parse SoC from DT/evidence — set manually")

    codec_part_numbers = sorted(new_profile.codecs)
    codec_verdicts = _derive_codec_verdicts(new_profile, kernel_source)
    if not codec_part_numbers:
        needs_review.append("codec_part_numbers: no codecs detected — populate from schematics/datasheets")

    # power_model_source is NEVER auto-finalized (rpmhpd-vs-SCMI is the Nord blocker class).
    detected_pd = ", ".join(sorted(new_profile.power_domain_providers)) or "none detected"
    power_model_source = (
        f"NEEDS_REVIEW: detected power-domain provider(s): {detected_pd}. "
        "Confirm rpmhpd vs. SCMI power model with the Power team before finalizing."
    )
    needs_review.append("power_model_source: never auto-finalized — confirm with Power team")

    generated_case = {
        "target_soc": target_soc,
        "nearest_target": nearest_target,
        "run_id": run_id,
        "inherit_from": inherit_from,
        "evidence_source": _DEFAULT_EVIDENCE_SOURCE,
        "evidence_roots": dict(evidence_roots),
        "kernel_source_path": kernel_source_path,
        "power_model_source": power_model_source,
        "codec_part_numbers": codec_part_numbers,
        "codec_verdicts": codec_verdicts,
        "needs_review": needs_review,
    }

    human_review_needed = low_confidence or bool(needs_review)

    return {
        "target_profile": new_profile.to_dict(),
        "generated_case": generated_case,
        "similarity_report": {
            "ranked": [r.to_dict() for r in ranked],
            "confidence": conf,
            "weights": dict(WEIGHTS),
        },
        "evidence_inventory": {
            "files": evidence_files,
            "evidence_roots": dict(evidence_roots),
            "kernel_source_path": str(kernel_source),
        },
        "human_review_needed": human_review_needed,
        "evidence": {"evidence_refs": evidence_refs},
    }


def _derive_codec_verdicts(profile, kernel_source: Path) -> dict[str, Any]:
    """Best-effort codec verdicts: locate each detected codec's ASoC driver.

    A detected driver present on disk is recorded ``upstream_present``; otherwise
    ``unresolved`` (a human must decide needs_port/needs_write). This mirrors the
    codec_driver_porting verdict shape without making the judgment call.
    """
    verdicts: dict[str, Any] = {}
    codecs_dir = kernel_source / "sound" / "soc" / "codecs"
    for part in sorted(profile.codecs):
        driver = codecs_dir / f"{part.lower()}.c"
        if driver.is_file():
            verdicts[part] = {"driver_path": f"sound/soc/codecs/{part.lower()}.c",
                              "status": "upstream_present"}
        else:
            verdicts[part] = {"driver_path": None, "status": "unresolved"}
    return verdicts


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
