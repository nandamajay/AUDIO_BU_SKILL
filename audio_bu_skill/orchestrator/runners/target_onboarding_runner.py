"""target_onboarding runner: QGenie/Claude-backed nearest-target + proposed case (v1.2).

The reasoning (schematic / IPCAT / datasheet / kernel analysis, codec/topology/power
inference, nearest-target selection) is done by QGenie/Claude via
``orchestrator.reasoning``; this runner does orchestration only — resolve the real
evidence, build the task_spec, call the reasoning client, and map the validated
``ANALYSIS_SCHEMA`` result into the existing output-envelope shape so the validator,
artifact writers, and do_onboard are unchanged in shape.

**Strict, no silent fallback.** If QGenie is unavailable the client raises
``ReasoningUnavailableError``; this runner lets it propagate (do_onboard turns it
into a loud failure + error artifact). The demoted local similarity engine is
reachable only via the explicit, test-gated ``analysis_engine="local-test"`` +
``test_mode=True`` path — never in production.

It NEVER generates kernel code, compiles, or writes case.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from orchestrator.reasoning import ANALYSIS_SCHEMA, get_reasoning_client
from orchestrator.reasoning.result import reasoning_fingerprints
from orchestrator.run_manifest import _sha256_file
from orchestrator.runners.kernel_history_discovery import discover_kernel_history
from orchestrator.runners.pin_crosscheck import cross_check_pins
from orchestrator.runners.power_model_inspection import inspect_power_model_source
from orchestrator.runners.source_intake_runner import discover_evidence

# Evidence-source default carried into every generated case (v1.0 default).
_DEFAULT_EVIDENCE_SOURCE = "ipcat_first"
# overall_confidence at or below this trips the low-confidence / human-review gate.
_MIN_OVERALL_CONFIDENCE = 0.75

# Matches the platform stem out of a `qcom,<stem>-<suffix>` compatible string,
# e.g. "qcom,eliza-rpmhpd" -> "eliza". Used to turn a kernel_history
# compatible_fallback into a candidate target name hint.
_QCOM_COMPATIBLE_PLATFORM_RE = re.compile(r'^qcom,([a-z0-9]+)-')
_QCOM_RPMHPD_COMPAT_RE = re.compile(r'^qcom,[a-z0-9]+-rpmhpd$')


def _resolve(workspace_root: Path, rel_or_abs: str) -> Path:
    candidate = Path(rel_or_abs)
    return candidate if candidate.is_absolute() else (workspace_root / candidate)


def resolve_onboarding_task_spec(
    workspace_root: Path, target_name: str, kernel_source_path: str,
    evidence_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Rebuild the task_spec + its supporting facts WITHOUT calling reasoning.

    This is exactly steps 1-2 of ``run_target_onboarding``, factored out so
    ``--rerun`` can recompute the reasoning fingerprints' *inputs* (task_spec
    hash, kernel commit, evidence hashes, IPCAT provenance) for drift detection
    without re-invoking QGenie (rerun is a fingerprint diff, never a re-analysis).

    Also runs the two read-only collectors added by the Onboarding Accuracy
    Upgrade — ``discover_kernel_history`` (FROMLIST/RFC git archaeology) and
    ``inspect_power_model_source`` (rpmhpd.c LCX/LMX inspection) — and folds
    their output into task_spec as ``kernel_history`` / ``power_model_hint``,
    plus expands candidate_targets with any kernel-history donor hints /
    compatible-string fallbacks. Both collectors are read-only and their
    fingerprints (git commit / evidence hashes) are unaffected by this.
    """
    kernel_source = _resolve(workspace_root, kernel_source_path)
    discovery = discover_evidence(workspace_root, evidence_roots or {}, _DEFAULT_EVIDENCE_SOURCE)
    evidence_files = list(discovery["paths"])
    ipcat_provenance = (discovery.get("provenance") or {}).get("mcp")
    kernel_commit = _kernel_commit(kernel_source)

    kernel_history = discover_kernel_history(kernel_source, target_name)
    power_model_hint = _power_model_hint(kernel_source, kernel_history)

    local_candidates = _candidate_targets(workspace_root, kernel_source, exclude=target_name)
    candidate_targets = local_candidates + _history_derived_candidates(
        kernel_history, existing_names={c["name"] for c in local_candidates} | {target_name},
    )

    task_spec = _build_task_spec(
        target_name=target_name, kernel_source=kernel_source, kernel_commit=kernel_commit,
        evidence_files=evidence_files, evidence_roots=evidence_roots or {},
        ipcat_provenance=ipcat_provenance,
        candidate_targets=candidate_targets,
        kernel_history=kernel_history, power_model_hint=power_model_hint,
    )
    return {
        "task_spec": task_spec,
        "kernel_source": kernel_source,
        "kernel_commit": kernel_commit,
        "evidence_files": evidence_files,
        "ipcat_provenance": ipcat_provenance,
        "evidence_sha256": _hash_evidence_files(workspace_root, evidence_files),
        "kernel_history": kernel_history,
        "power_model_hint": power_model_hint,
    }


def run_target_onboarding(input_envelope: dict[str, Any]) -> dict[str, Any]:
    workspace_context = input_envelope["workspace_context"]
    target_name = input_envelope["target_name"]
    kernel_source_path = input_envelope["kernel_source_path"]
    run_id = input_envelope["run_id"]
    evidence_roots = input_envelope.get("evidence_roots") or {}
    analysis_engine = input_envelope.get("analysis_engine") or "qgenie"
    test_mode = bool(input_envelope.get("test_mode"))
    analysis_timeout = input_envelope.get("analysis_timeout")

    workspace_root = Path(workspace_context["workspace_root"])

    # --- 1+2. resolve the REAL evidence and build the task_spec (paths/refs only) ---
    resolved = resolve_onboarding_task_spec(workspace_root, target_name, kernel_source_path, evidence_roots)
    kernel_source = resolved["kernel_source"]
    kernel_commit = resolved["kernel_commit"]
    evidence_files = resolved["evidence_files"]
    ipcat_provenance = resolved["ipcat_provenance"]
    task_spec = resolved["task_spec"]
    evidence_sha256 = resolved["evidence_sha256"]

    # --- 3. reason via QGenie/Claude (MANDATORY; no fallback) ---
    client = get_reasoning_client(analysis_engine, test_mode=test_mode)
    analyze_kwargs: dict[str, Any] = {"json_schema": ANALYSIS_SCHEMA}
    if analysis_timeout:
        analyze_kwargs["timeout"] = analysis_timeout
    result = client.analyze(task_spec, **analyze_kwargs)
    analysis = result.parsed

    # --- 3b. pin cross-check: schematic-derived GPIO/net findings (if QGenie
    # returned any) against the candidate patches' DT GPIO assignments. A
    # mismatch is NEEDS_REVIEW, never a hard failure -- see pin_crosscheck.py.
    schematic_nets = _schematic_nets_dict(analysis)
    pin_crosschecks = (
        cross_check_pins(schematic_nets, resolved["kernel_history"].get("candidates", []), kernel_source)
        if schematic_nets else []
    )

    # --- 4. map ANALYSIS_SCHEMA -> the existing output-envelope shape ---
    cited = _collect_citations(analysis)
    evidence_refs = _dedup(evidence_files + cited)

    output = _map_analysis_to_envelope(
        analysis=analysis, target_name=target_name, run_id=run_id,
        kernel_source=kernel_source, kernel_source_path=kernel_source_path,
        evidence_roots=evidence_roots, evidence_files=evidence_files,
        evidence_refs=evidence_refs,
        kernel_history=resolved["kernel_history"], power_model_hint=resolved["power_model_hint"],
        pin_crosschecks=pin_crosschecks,
    )

    # --- 5. attach reasoning provenance for do_onboard to artifact (never logged) ---
    # evidence_sha256 (computed in step 1+2 above) keys are relative to
    # workspace_root — the same convention main.py's _hash_evidence_files uses
    # for the non-reasoning fingerprints, so the two hash maps are directly
    # comparable across --rerun.
    output["_reasoning"] = {
        "engine_id": result.engine_id,
        "model_id": result.model_id,
        "cli_version": result.cli_version,
        "schema_version": result.schema_version,
        "argv_fingerprint": result.argv_fingerprint,
        "test_mode": test_mode,
        "task_spec": task_spec,
        "raw_text": result.raw_text,       # gitignored artifact only — never JSONL/state
        "analysis": analysis,
        "summary": result.summary(),
        "fingerprints": reasoning_fingerprints(
            task_spec=task_spec, engine_id=result.engine_id, model_id=result.model_id,
            cli_version=result.cli_version, schema_version=result.schema_version,
            ipcat_provenance=ipcat_provenance,
            qgenie_cli_home=getattr(client, "qgenie_cli_home", None),
            config_root=getattr(client, "config_root", None),
            data_root=getattr(client, "data_root", None),
            kernel_commit=kernel_commit,
            evidence_sha256=evidence_sha256,
        ),
    }
    return output


def _hash_evidence_files(workspace_root: Path, evidence_files: list[str]) -> dict[str, str]:
    """sha256 of every discovered evidence file, keyed by path relative to
    workspace_root (or the absolute path if it falls outside the workspace)."""
    out: dict[str, str] = {}
    for f in evidence_files:
        fp = Path(f)
        if not fp.is_file():
            continue
        try:
            rel = fp.relative_to(workspace_root)
        except ValueError:
            rel = fp
        out[str(rel)] = _sha256_file(fp)
    return out


# --------------------------------------------------------------------------- #
# task_spec + candidate targets
# --------------------------------------------------------------------------- #
def _build_task_spec(
    *, target_name, kernel_source, kernel_commit, evidence_files, evidence_roots,
    ipcat_provenance, candidate_targets, kernel_history, power_model_hint,
) -> dict[str, Any]:
    ipcat = [f for f in evidence_files if "/ipcat/" in f or "\\ipcat\\" in f]
    offline = [f for f in evidence_files if f not in ipcat]
    evidence: dict[str, Any] = {"ipcat": ipcat, "offline": offline}
    if ipcat_provenance:
        # an agent-mediated IPCAT cache exists -> let QGenie also query IPCAT
        # live via the qgenie-chat MCP plugin server (no config path needed --
        # the plugin's own MCP server is auto-managed and pre-authenticated).
        evidence["ipcat_mcp"] = True
        evidence["ipcat_provenance"] = ipcat_provenance
    return {
        "skill_id": "target_onboarding",
        "target": target_name,
        "kernel": {"path": str(kernel_source), "commit": kernel_commit},
        "evidence": evidence,
        "candidate_targets": candidate_targets,
        # Onboarding Accuracy Upgrade collectors (slices 1-3): read-only git
        # archaeology, rpmhpd.c inspection -- surfaced to QGenie as extra
        # context, never mutated, never fed back into the kernel tree.
        "kernel_history": kernel_history,
        "power_model_hint": power_model_hint,
        "candidate_patch_series": kernel_history.get("candidates", []),
        "questions": [
            "identify SoC/board, codecs, amplifiers, mics, speakers, buses, SoundWire, "
            "LPASS/ADSP/AudioReach/GPR/APM stack, and the power model",
            "rank the nearest existing targets with rationale and citations",
            "list missing evidence",
        ],
    }


def _candidate_targets(workspace_root: Path, kernel_source: Path, *, exclude: str) -> list[dict[str, Any]]:
    """Lightweight descriptors for every existing target (from its case.py facts)."""
    from orchestrator.main import TARGETS_ROOT, load_case  # lazy: breaks import cycle

    out: list[dict[str, Any]] = []
    if not TARGETS_ROOT.is_dir():
        return out
    for entry in sorted(TARGETS_ROOT.iterdir()):
        if not entry.is_dir() or entry.name == exclude or not (entry / "case.py").is_file():
            continue
        try:
            case = load_case(entry.name)
        except SystemExit:
            continue
        out.append({
            "name": entry.name,
            "soc": getattr(case, "target_soc", ""),
            "codecs": list(getattr(case, "codec_part_numbers", []) or []),
            "codec_verdicts": dict(getattr(case, "codec_verdicts", {}) or {}),
            "power_model_source": getattr(case, "power_model_source", ""),
        })
    return out


def _history_derived_candidates(
    kernel_history: dict[str, Any], *, existing_names: set[str],
) -> list[dict[str, Any]]:
    """Extra candidate-target stubs from kernel_history donor hints / compatible
    fallbacks, deduplicated against the local ``targets/`` DB and the current
    target itself. These are name-only hints (no case.py facts exist for them
    yet) -- surfaced so QGenie can consider a donor architecture that was never
    onboarded locally but is visible in kernel git history.
    """
    seen = {n.lower() for n in existing_names}
    out: list[dict[str, Any]] = []
    for candidate in kernel_history.get("candidates", []):
        hints: list[str] = []
        if candidate.get("donor_hint"):
            hints.append(str(candidate["donor_hint"]))
        for compat in candidate.get("compatible_fallbacks") or []:
            match = _QCOM_COMPATIBLE_PLATFORM_RE.match(str(compat))
            if match:
                hints.append(match.group(1))
        for hint in hints:
            key = hint.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": hint,
                "soc": "",
                "codecs": [],
                "codec_verdicts": {},
                "power_model_source": "",
                "source": "kernel_history_donor_hint",
                "sha": candidate.get("sha"),
            })
    return out


def _power_model_hint(kernel_source: Path, kernel_history: dict[str, Any]) -> dict[str, Any]:
    """Best-effort rpmhpd.c LCX/LMX inspection (slice 2), keyed off any
    ``qcom,<x>-rpmhpd`` compatible string surfaced by kernel_history's diffs.
    Returns ``{"status": "missing", ...}`` (never raises) when no such
    compatible string was found -- there is nothing to inspect yet.
    """
    compat = _guess_rpmhpd_compatible(kernel_history)
    if not compat:
        return {"status": "missing", "kind": None, "lcx_present": None, "lmx_present": None,
                 "lcx_lmx_present": None, "dtsi_confirms_lcx_lmx": None, "citations": []}
    return inspect_power_model_source(kernel_source, compat)


def _guess_rpmhpd_compatible(kernel_history: dict[str, Any]) -> str | None:
    for candidate in kernel_history.get("candidates", []):
        for compat in candidate.get("compatible_fallbacks") or []:
            if _QCOM_RPMHPD_COMPAT_RE.match(str(compat)):
                return str(compat)
    return None


def _schematic_nets_dict(analysis: dict[str, Any]) -> dict[str, Any]:
    """QGenie's optional ``schematic_nets`` list -> {net_name: gpio} for
    pin_crosscheck.cross_check_pins, which expects a flat mapping."""
    out: dict[str, Any] = {}
    for item in analysis.get("schematic_nets") or []:
        if isinstance(item, dict) and item.get("net_name") is not None and "gpio" in item:
            out[str(item["net_name"])] = item["gpio"]
    return out


# --------------------------------------------------------------------------- #
# ANALYSIS_SCHEMA -> output envelope mapping
# --------------------------------------------------------------------------- #
def _map_analysis_to_envelope(
    *, analysis, target_name, run_id, kernel_source, kernel_source_path,
    evidence_roots, evidence_files, evidence_refs,
    kernel_history=None, power_model_hint=None, pin_crosschecks=None,
) -> dict[str, Any]:
    kernel_history = kernel_history or {}
    power_model_hint = power_model_hint or {}
    pin_crosschecks = pin_crosschecks or []
    overall_conf = float(analysis.get("overall_confidence") or 0.0)
    qgenie_review = bool(analysis.get("human_review_needed"))
    low_confidence = qgenie_review or overall_conf < _MIN_OVERALL_CONFIDENCE

    nearest = analysis.get("nearest_targets") or []
    ranked = [
        {"target_name": nt.get("name", ""), "overall": float(nt.get("score") or 0.0),
         "per_signal": {}, "rationale": nt.get("rationale", ""),
         "cites": {"rationale": nt.get("citations", []) or []}}
        for nt in nearest
    ]
    top_name = ranked[0]["target_name"] if ranked else ""
    top_score = ranked[0]["overall"] if ranked else 0.0
    second = ranked[1]["overall"] if len(ranked) > 1 else 0.0

    needs_review: list[str] = []
    if top_name:
        nearest_target = top_name
        if low_confidence:
            needs_review.append(
                f"nearest_target: low-confidence match (overall {overall_conf:.2f}) — confirm before trusting"
            )
    else:
        nearest_target = "UNKNOWN (QGenie returned no candidate)"
        needs_review.append("nearest_target: QGenie returned no ranked candidate")

    inherit_from = top_name if (top_name and not low_confidence) else ""
    if top_name and low_confidence:
        needs_review.append("inherit_from: left empty pending nearest_target confirmation")

    soc_val = (analysis.get("soc") or {}).get("value") or ""
    target_soc = soc_val or "UNKNOWN"
    if not soc_val:
        needs_review.append("target_soc: QGenie could not identify the SoC — set manually")

    codecs = analysis.get("codecs") or []
    codec_part_numbers = sorted({c.get("part", "") for c in codecs if c.get("part")})
    codec_verdicts = _derive_codec_verdicts(codec_part_numbers, kernel_source)
    if not codec_part_numbers:
        needs_review.append("codec_part_numbers: QGenie detected no codecs — verify evidence coverage")

    # power_model is NEVER auto-finalized (rpmhpd-vs-SCMI is the Nord blocker class).
    # power_model_hint (slice 2's rpmhpd.c inspection) is folded in as
    # corroborating evidence when available -- it can raise our confidence in
    # QGenie's proposed kind, but it never finalizes the field either.
    pm = analysis.get("power_model") or {}
    hint_status = power_model_hint.get("status")
    power_model_source = (
        f"NEEDS_REVIEW: QGenie proposes power model kind={pm.get('kind', 'unknown')!r} "
        f"(confidence {pm.get('confidence', 0.0)}). Confirm rpmhpd vs. SCMI with the Power team."
    )
    if hint_status and hint_status != "missing":
        power_model_source += (
            f" rpmhpd.c inspection: {hint_status} "
            f"(lcx_lmx_present={power_model_hint.get('lcx_lmx_present')})."
        )
    needs_review.append("power_model_source: never auto-finalized — confirm with Power team")

    for missing in analysis.get("missing_evidence") or []:
        needs_review.append(f"missing_evidence: {missing}")

    # pin cross-check (slice 3): a mismatch/unparseable net is NEEDS_REVIEW,
    # never a hard failure -- see pin_crosscheck.cross_check_pins.
    for verdict in pin_crosschecks:
        if verdict.get("match") is not True:
            needs_review.append(
                f"pin_crosscheck: signal {verdict.get('signal')!r} "
                f"{verdict.get('note', 'no matching DT GPIO assignment found')}"
            )

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
        "audio_topology": _build_audio_topology(
            analysis=analysis, pm=pm, power_model_hint=power_model_hint, pin_crosschecks=pin_crosschecks,
        ),
        "candidate_patch_series": kernel_history.get("candidates", []),
    }

    target_profile = {
        "target_name": target_name,
        "soc": target_soc if soc_val else "",
        "codecs": codec_part_numbers,
        "amplifiers": [a.get("part", "") for a in (analysis.get("amplifiers") or [])],
        "soundwire": analysis.get("soundwire") or {},
        "audio_stack": analysis.get("audio_stack") or {},
        "power_model": pm,
        "cites": _profile_cites(analysis),
        "qgenie_analysis": analysis,
    }

    confidence = {
        "top": top_name or None,
        "score": round(top_score, 4),
        "margin": round(top_score - second, 4),
        "confidence": round(overall_conf, 4),
        "low_confidence": low_confidence,
        "min_score": _MIN_OVERALL_CONFIDENCE,
        "min_margin": 0.0,
        "source": "qgenie",
    }

    return {
        "target_profile": target_profile,
        "generated_case": generated_case,
        "similarity_report": {
            "ranked": ranked,
            "confidence": confidence,
            "weights": {"note": "QGenie reasoning — nearest-target scores are model-produced, not weighted-signal"},
        },
        "evidence_inventory": {
            "files": evidence_files,
            "evidence_roots": dict(evidence_roots),
            "kernel_source_path": str(kernel_source),
        },
        "human_review_needed": bool(low_confidence or needs_review),
        "evidence": {"evidence_refs": evidence_refs},
    }


def _build_audio_topology(
    *, analysis: dict[str, Any], pm: dict[str, Any], power_model_hint: dict[str, Any],
    pin_crosschecks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Populate BringupCase.audio_topology (slice 4) from QGenie's analysis
    plus the Onboarding Accuracy Upgrade collectors' output. Purely additive
    context alongside the flat codec_part_numbers/codec_verdicts fields --
    never itself finalizes power_model_source or any other NEEDS_REVIEW field.
    """
    topology: dict[str, Any] = {
        "codecs": analysis.get("codecs") or [],
        "amplifiers": analysis.get("amplifiers") or [],
        "mics": analysis.get("mics") or [],
        "speakers": analysis.get("speakers") or [],
        "soundwire": analysis.get("soundwire") or {},
        "audio_stack": analysis.get("audio_stack") or {},
        "power_model": {**pm, "inspection_hint": power_model_hint},
        "missing_evidence": analysis.get("missing_evidence") or [],
    }
    if pin_crosschecks:
        topology["pin_crosschecks"] = pin_crosschecks
    cites = _profile_cites(analysis)
    if cites:
        topology["citations"] = cites
    return topology


def _derive_codec_verdicts(codec_part_numbers: list[str], kernel_source: Path) -> dict[str, Any]:
    """Best-effort codec verdicts: locate each detected codec's ASoC driver.

    A detected driver present on disk is recorded ``upstream_present``; otherwise
    ``unresolved`` (a human must decide needs_port/needs_write).
    """
    verdicts: dict[str, Any] = {}
    codecs_dir = kernel_source / "sound" / "soc" / "codecs"
    for part in sorted(codec_part_numbers):
        driver = codecs_dir / f"{part.lower()}.c"
        if driver.is_file():
            verdicts[part] = {"driver_path": f"sound/soc/codecs/{part.lower()}.c",
                              "status": "upstream_present"}
        else:
            verdicts[part] = {"driver_path": None, "status": "unresolved"}
    return verdicts


def _collect_citations(analysis: dict[str, Any]) -> list[str]:
    """Every citation QGenie attached to any finding (evidence/IPCAT/kernel refs)."""
    cites: list[str] = []

    def _take(obj: Any) -> None:
        if isinstance(obj, dict):
            for c in obj.get("citations") or []:
                cites.append(str(c))
            for v in obj.values():
                _take(v)
        elif isinstance(obj, list):
            for item in obj:
                _take(item)

    _take(analysis)
    return _dedup(cites)


def _profile_cites(analysis: dict[str, Any]) -> dict[str, list[str]]:
    """Group citations by signal for the onboarding report's 'Cited evidence' block."""
    out: dict[str, list[str]] = {}
    for key in ("soc", "power_model", "soundwire"):
        block = analysis.get(key)
        if isinstance(block, dict) and block.get("citations"):
            out[key] = list(block["citations"])
    codec_cites: list[str] = []
    for c in analysis.get("codecs") or []:
        codec_cites.extend(c.get("citations") or [])
    if codec_cites:
        out["codecs"] = _dedup(codec_cites)
    return out


def _kernel_commit(kernel_source: Path) -> str | None:
    from orchestrator.run_manifest import _kernel_commit as _kc  # reuse the git probe
    return _kc(str(kernel_source))


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
