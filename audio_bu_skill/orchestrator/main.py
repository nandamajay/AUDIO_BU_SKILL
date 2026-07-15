"""Entrypoint: drive one audio bring-up target's run through the generic
orchestrator, and record a reproducible audit trail.

Thin CLI. All state-walking lives in orchestrator.bringup_walk.run_bringup
(generic, target-agnostic); all per-target facts + analyst judgment live in
targets/<name>/case.py; the reproducibility layer lives in
orchestrator.run_manifest.

Three modes:
    # normal run (fresh or resume) — writes artifacts/<run_id>/
    python -m orchestrator.main --target nord-iq10 --evidence-source ipcat_first
    python -m orchestrator.main --target nord-iq10 --kernel-source linux-nord

    # reconstruct a prior run from its artifacts, WITHOUT invoking any skill
    python -m orchestrator.main --replay nord-iq10-audio-bringup-2026-07

    # compare today's inputs against a recorded run's fingerprints
    python -m orchestrator.main --rerun nord-iq10-audio-bringup-2026-07

    # onboard a new target: detect nearest target + propose case.generated.py
    # (v1.2 — read-only, never writes case.py, never generates code; reasoning is
    # QGenie/Claude-backed and mandatory, no silent local fallback)
    python -m orchestrator.main --onboard my-new-target --kernel-source linux-nord

    # test-only: exercise the demoted local comparator instead of QGenie
    python -m orchestrator.main --onboard my-new-target --kernel-source linux-nord \
        --analysis-engine local-test --test-mode

Kernel-source resolution (first present wins): --kernel-source, then the case's
own kernel_source_path; a run fails only if neither yields a valid kernel tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from orchestrator import run_manifest, run_store
from orchestrator.bringup_walk import BringupCase, EVIDENCE_SOURCES, merge_cases, run_bringup, validate_case
from orchestrator.driver import BringupOrchestrator, OrchestratorError
from orchestrator.reasoning import ReasoningUnavailableError, get_reasoning_client
from orchestrator.reasoning import cardinality as cardinality_authority
from orchestrator.reasoning import ledger as confidence_ledger
from orchestrator.reasoning.result import reasoning_fingerprints
from orchestrator.runners.codec_driver_porting_runner import run_codec_driver_porting
from orchestrator.runners.source_intake_runner import discover_evidence, run_source_intake
from orchestrator.runners.target_onboarding_runner import resolve_onboarding_task_spec, run_target_onboarding
from orchestrator.runners.triage_runner import run_triage
from orchestrator.workspace_loader import load_workspace_context

# skill_state values for which a target_onboarding invocation is "done" for
# attempt-selection purposes. SUCCESS counts as terminal here even though
# skill_state_machine.TERMINAL_STATES excludes it: onboarding's
# requires_human_review:true means SUCCESS never auto-advances to APPROVED,
# so treating SUCCESS as non-terminal would permanently block re-onboarding
# (there is deliberately no (SUCCESS, READY) transition — see do_onboard).
_ONBOARDING_TERMINAL_SKILL_STATES = {"SUCCESS", "FAILED", "APPROVED", "SKIPPED"}

ANALYSIS_ENGINES = ("qgenie", "local-test")

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = WORKSPACE_ROOT / "audio_bu_skill" / "skills"
TARGETS_ROOT = WORKSPACE_ROOT / "audio_bu_skill" / "targets"

KERNEL_REQUIRED_SUBDIRS = ("arch", "drivers", "sound", "Documentation")


# --------------------------------------------------------------------------- #
# case loading + inheritance
# --------------------------------------------------------------------------- #
def _import_case(target: str) -> BringupCase:
    case_path = TARGETS_ROOT / target / "case.py"
    if not case_path.is_file():
        available = sorted(p.name for p in TARGETS_ROOT.iterdir() if (p / "case.py").is_file()) if TARGETS_ROOT.is_dir() else []
        raise SystemExit(f"no case for target {target!r} (looked for {case_path}); available: {available}")
    spec = importlib.util.spec_from_file_location(f"target_case_{target.replace('-', '_')}", case_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = getattr(module, "CASE", None)
    if not isinstance(case, BringupCase):
        raise SystemExit(f"targets/{target}/case.py must export a BringupCase named CASE")
    return case


def load_case(target: str, _seen: tuple[str, ...] = ()) -> BringupCase:
    """Import targets/<target>/case.py, resolving inherit_from by deep-merge.

    Parent is resolved first, then child overrides it (child wins; dicts merge
    key-wise). Guards against self-inheritance and cycles.
    """
    if target in _seen:
        raise SystemExit(f"inheritance cycle detected: {' -> '.join(_seen + (target,))}")
    case = _import_case(target)
    parent_name = getattr(case, "inherit_from", "")
    if parent_name:
        if parent_name == target:
            raise SystemExit(f"targets/{target}/case.py cannot inherit from itself")
        parent = load_case(parent_name, _seen + (target,))
        case = merge_cases(parent, case)
    return case


# --------------------------------------------------------------------------- #
# kernel-source resolution + validation
# --------------------------------------------------------------------------- #
def resolve_kernel_source(cli_value: str | None, case: BringupCase) -> str:
    candidate = cli_value or case.kernel_source_path
    if not candidate:
        raise SystemExit(
            "no kernel source available: pass --kernel-source <path> or set "
            "kernel_source_path in the target's case.py"
        )
    return validate_kernel_source(candidate)


def validate_kernel_source(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = (WORKSPACE_ROOT / path)
    path = path.resolve()
    if not path.is_dir():
        raise SystemExit(f"--kernel-source {path_str!r} is not a directory: {path}")
    if not (path / ".git").exists():
        raise SystemExit(f"kernel source {path} has no .git — expected a kernel git checkout")
    missing = [d for d in KERNEL_REQUIRED_SUBDIRS if not (path / d).is_dir()]
    if missing:
        raise SystemExit(f"kernel source {path} is missing expected subdirs: {missing}")
    return str(path)


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive an audio bring-up target through the orchestrator.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--target", help="target name = directory under audio_bu_skill/targets/")
    mode.add_argument("--replay", metavar="RUN_ID",
                      help="reconstruct a prior run from artifacts/<run_id>/ without invoking any skill")
    mode.add_argument("--rerun", metavar="RUN_ID",
                      help="compare current inputs against artifacts/<run_id>/ fingerprints (REPEATABLE / DRIFT DETECTED)")
    mode.add_argument("--onboard", metavar="TARGET",
                      help="onboard a new target: detect nearest target + write targets/<target>/case.generated.py (never case.py)")
    parser.add_argument("--evidence-source", choices=EVIDENCE_SOURCES, default=None,
                        help="override the case's evidence_source (default: use the case's own value)")
    parser.add_argument("--kernel-source", default=None,
                        help="path to the kernel git checkout (default: the case's kernel_source_path)")
    parser.add_argument("--analysis-engine", choices=ANALYSIS_ENGINES, default="qgenie",
                        help="reasoning engine for --onboard (default: qgenie, the only production engine); "
                             "'local-test' is a demoted regression comparator, rejected unless --test-mode is also set")
    parser.add_argument("--test-mode", action="store_true",
                        help="required alongside --analysis-engine local-test to unlock the demoted local comparator")
    parser.add_argument("--analysis-timeout", type=int, default=None, metavar="SECONDS",
                        help="override the QGenie analysis subprocess timeout (default: 900s); "
                             "raise this for large kernel trees / evidence sets that legitimately need longer")
    args = parser.parse_args()
    if not (args.target or args.replay or args.rerun or args.onboard):
        parser.error("one of --target, --replay, --rerun, or --onboard is required")
    if args.analysis_engine == "local-test" and not args.test_mode:
        parser.error("--analysis-engine local-test requires --test-mode (no silent local fallback in production)")
    return args


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #
def do_replay(run_id: str) -> None:
    manifest = run_manifest.load_manifest(WORKSPACE_ROOT, run_id)
    art_dir = run_manifest.artifacts_dir(WORKSPACE_ROOT, run_id)
    print(f"replaying run {run_id} (no skills invoked)")
    print(f"  target      : {manifest['target']} ({manifest['target_soc']})")
    print(f"  final state : {manifest['final_state']}")
    print(f"  evidence    : {manifest['evidence_source']}  "
          f"({manifest['analytics']['evidence_count']} refs)")
    print("  trajectory  :")
    for t in manifest["state_transitions"]:
        gate = f" [{t['failed_gate']}]" if t.get("failed_gate") else ""
        print(f"    {t['from']} -> {t['to']}{gate}: {t.get('reason')}")
    blocker = art_dir / "blocker_report.md"
    if blocker.is_file():
        print(f"  blocker report: {blocker}")


def do_rerun(run_id: str, cli_kernel_source: str | None) -> int:
    recorded = run_manifest.load_manifest(WORKSPACE_ROOT, run_id)
    if "attempt" in recorded:
        # onboarding runs have no case.py yet — route to the reasoning-only path.
        return _do_rerun_onboarding(recorded, cli_kernel_source)
    target = recorded["target"]

    case = load_case(target)
    kernel_source = resolve_kernel_source(cli_kernel_source, case)
    workspace_context = load_workspace_context(WORKSPACE_ROOT)
    workspace_context["kernel_source"] = kernel_source

    registry = _load_registry()
    current = run_manifest.compute_fingerprints(
        workspace_context=workspace_context, case=case, target=target,
        targets_root=TARGETS_ROOT, skills_root=SKILLS_ROOT, skill_registry=registry,
    )
    drift = run_manifest.diff_fingerprints(recorded.get("fingerprints", {}), current)
    if not drift:
        print(f"REPEATABLE — inputs for {run_id} are unchanged since the recorded run")
        return 0
    print(f"DRIFT DETECTED — {len(drift)} input(s) changed since the recorded run:")
    for line in drift:
        print(f"  {line}")
    return 2


def _do_rerun_onboarding(recorded: dict, cli_kernel_source: str | None) -> int:
    """--rerun for an onboarding run (no case.py exists yet).

    Recomputes the reasoning fingerprints' *inputs* — task_spec hash, kernel
    commit, evidence hashes, IPCAT provenance id, and (via a cheap `doctor`
    probe only, never a re-analysis) the current QGenie profile/model/CLI
    identity — and diffs them against the recorded run's fingerprints. Never
    re-invokes QGenie's analyze(); --rerun is a fingerprint diff, not a
    re-analysis, mirroring the v1.0 --rerun contract.
    """
    target = recorded["target"]
    target_dir = TARGETS_ROOT / target
    kernel_source = validate_kernel_source(cli_kernel_source or recorded.get("kernel_source") or "")
    evidence_roots, _ = _resolve_evidence_roots(target, target_dir)

    resolved = resolve_onboarding_task_spec(WORKSPACE_ROOT, target, kernel_source, evidence_roots)

    recorded_reasoning = (recorded.get("fingerprints") or {}).get("reasoning", {}) or {}
    engine_id = recorded_reasoning.get("engine_id") or "qgenie"
    client = get_reasoning_client(engine_id, test_mode=(engine_id == "local-test"))
    profile_note: str | None = None
    try:
        client.preflight(require_ipcat=bool(resolved["ipcat_provenance"]))
    except ReasoningUnavailableError as exc:
        profile_note = f"{exc.code}: {exc.message}"

    current_reasoning = reasoning_fingerprints(
        task_spec=resolved["task_spec"], engine_id=engine_id,
        model_id=getattr(client, "model_id", "") or "",
        cli_version=getattr(client, "cli_version", "") or "",
        schema_version=recorded_reasoning.get("schema_version", ""),
        ipcat_provenance=resolved["ipcat_provenance"],
        qgenie_cli_home=getattr(client, "qgenie_cli_home", None),
        config_root=getattr(client, "config_root", None),
        data_root=getattr(client, "data_root", None),
        kernel_commit=resolved["kernel_commit"],
        evidence_sha256=resolved["evidence_sha256"],
    )
    current = {
        "kernel_source": kernel_source,
        "kernel_commit": resolved["kernel_commit"],
        "evidence": resolved["evidence_sha256"],
        "reasoning": current_reasoning,
    }
    if profile_note:
        print(f"  NOTE: could not verify the current QGenie profile — {profile_note}")
        print("        (model_id/cli_version/config_root/data_root drift below may be incomplete)")

    drift = run_manifest.diff_fingerprints(recorded.get("fingerprints", {}), current)
    if not drift:
        print(f"REPEATABLE — inputs for {recorded['run_id']} are unchanged since the recorded run")
        return 0
    print(f"DRIFT DETECTED — {len(drift)} input(s) changed since the recorded run:")
    for line in drift:
        print(f"  {line}")
    return 2


def _load_registry() -> dict:
    """Load + validate the skill registry (same path the orchestrator uses)."""
    from orchestrator.loader_skill_manifest import load_skill_registry
    reg = load_skill_registry(SKILLS_ROOT)
    if reg["validation_status"] != "valid":
        raise SystemExit(f"skill registry invalid: {reg['errors']}")
    return reg["skills"]


def do_run(target: str, cli_evidence_source: str | None, cli_kernel_source: str | None) -> None:
    case = load_case(target)
    if cli_evidence_source is not None:
        case.evidence_source = cli_evidence_source
    validate_case(case, target=target)

    kernel_source = resolve_kernel_source(cli_kernel_source, case)
    workspace_context = load_workspace_context(WORKSPACE_ROOT)
    workspace_context["kernel_source"] = kernel_source

    orchestrator = BringupOrchestrator(workspace_root=WORKSPACE_ROOT, skills_root=SKILLS_ROOT, run_id=case.run_id)
    orchestrator.register_runner("source_intake", run_source_intake)
    orchestrator.register_runner("triage", run_triage)
    orchestrator.register_runner("codec_driver_porting", run_codec_driver_porting)

    try:
        orchestrator.resume_run()
        print(f"resumed run {case.run_id} at {orchestrator.current_bringup_state()}")
    except OrchestratorError as exc:
        if exc.code != "RUN_NOT_FOUND":
            raise
        orchestrator.start_run(target_soc=case.target_soc, nearest_target=case.nearest_target)
        print(f"started run {case.run_id} at INIT")

    final_state = run_bringup(orchestrator, workspace_context, case, on_event=lambda msg: print(f"  · {msg}"))
    print(f"run {case.run_id} is now at {final_state}")

    _record_artifacts(target, case, workspace_context, orchestrator)


def _record_artifacts(target, case, workspace_context, orchestrator) -> None:
    state_record = orchestrator.resume_run()
    fingerprints = run_manifest.compute_fingerprints(
        workspace_context=workspace_context, case=case, target=target,
        targets_root=TARGETS_ROOT, skills_root=SKILLS_ROOT, skill_registry=orchestrator.skill_registry,
    )

    # Evidence is a pure function of the case's policy — derive it directly so a
    # resume no-op (where no skill re-ran) still records the real evidence set,
    # rather than the empty last_outputs of this session.
    discovery = discover_evidence(WORKSPACE_ROOT, case.evidence_roots or {}, case.evidence_source)
    evidence_refs = discovery["paths"]
    provenance = discovery["provenance"]

    # Skill outputs: this session's invocations, layered over any prior run's
    # (a resume that advanced re-runs some skills; a no-op resume runs none).
    skill_outputs = dict(run_manifest.load_skill_outputs(WORKSPACE_ROOT, case.run_id))
    skill_outputs.update(orchestrator.last_outputs)

    manifest = run_manifest.build_manifest(
        run_id=case.run_id, target=target, case=case, workspace_context=workspace_context,
        state_record=state_record, fingerprints=fingerprints, evidence_refs=evidence_refs,
        generated_artifact_count=0,
    )
    result = run_manifest.write_artifacts(
        workspace_root=WORKSPACE_ROOT, run_id=case.run_id, manifest=manifest,
        state_record=state_record, evidence_refs=evidence_refs, evidence_provenance=provenance,
        skill_outputs=skill_outputs, case=case,
    )
    print(f"  wrote {len(result['files'])} artifacts to {result['dir']}")


# --------------------------------------------------------------------------- #
# onboarding attempt model (v1.2) — attempt-scoped run_ids, no FSM changes
# --------------------------------------------------------------------------- #
def _onboarding_run_id_for_attempt(target: str, attempt: int) -> str:
    # Attempt 1 stays unsuffixed so pre-existing state/<target>-onboarding.json
    # (from before the attempt model) is recognized as attempt 1, not orphaned.
    return f"{target}-onboarding" if attempt == 1 else f"{target}-onboarding-{attempt}"


def _existing_onboarding_attempts(target: str) -> dict[int, str]:
    """Map attempt number -> run_id for every persisted onboarding attempt."""
    state_dir = WORKSPACE_ROOT / "audio_bu_skill" / "state"
    if not state_dir.is_dir():
        return {}
    pattern = re.compile(rf"^{re.escape(target)}-onboarding(?:-(\d+))?\.json$")
    attempts: dict[int, str] = {}
    for path in state_dir.iterdir():
        m = pattern.match(path.name)
        if not m:
            continue
        attempts[int(m.group(1)) if m.group(1) else 1] = path.stem
    return attempts


def _resolve_onboarding_run_id(target: str) -> tuple[str, int, bool]:
    """Select the run_id for this onboarding invocation.

    Resumes the latest attempt if it's still in-flight (non-terminal);
    allocates a new attempt number if the latest is terminal or none exists
    yet. This is purely a run_id choice made before invoke_skill runs, so it
    needs no FSM change: a terminal SUCCESS just gets a fresh run_id instead
    of an illegal (SUCCESS, READY) re-entry into the same one.

    Returns (run_id, attempt_number, is_new_attempt).
    """
    attempts = _existing_onboarding_attempts(target)
    if not attempts:
        return _onboarding_run_id_for_attempt(target, 1), 1, True

    latest_attempt = max(attempts)
    latest_run_id = attempts[latest_attempt]
    record = run_store.load_run(WORKSPACE_ROOT, latest_run_id) or {}
    skill_state = record.get("skill_invocations", {}).get("target_onboarding", {}).get("skill_state")
    if skill_state in _ONBOARDING_TERMINAL_SKILL_STATES:
        next_attempt = latest_attempt + 1
        return _onboarding_run_id_for_attempt(target, next_attempt), next_attempt, True
    return latest_run_id, latest_attempt, False


def _hash_evidence_files(evidence_files: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in evidence_files:
        fp = Path(f)
        if not fp.is_file():
            continue
        try:
            rel = fp.relative_to(WORKSPACE_ROOT)
        except ValueError:
            rel = fp
        out[str(rel)] = run_manifest._sha256_file(fp)
    return out


def _record_onboarding_artifacts(*, target: str, run_id: str, attempt: int, kernel_source: str,
                                  output: dict, orchestrator: BringupOrchestrator) -> None:
    """Write durable per-attempt artifacts to artifacts/<run_id>/, mirroring
    do_run's _record_artifacts but without a case object (onboarding has none
    yet). Records the 5 mandated reproducibility fields: qgenie version and
    model id and task_spec hash (all inside reasoning fingerprints), plus
    evidence hash and kernel commit computed directly here.
    """
    state_record = orchestrator.resume_run()
    reasoning = output.get("_reasoning") or {}
    evidence_files = (output.get("evidence_inventory") or {}).get("files", []) or []
    evidence = _hash_evidence_files(evidence_files)
    kernel_commit = run_manifest._kernel_commit(kernel_source)

    evidence_refs = (output.get("evidence") or {}).get("evidence_refs", [])
    conf = (output.get("similarity_report") or {}).get("confidence", {})
    generated_case = output.get("generated_case") or {}

    manifest = run_manifest.build_onboarding_manifest(
        run_id=run_id, target=target, attempt=attempt, state_record=state_record,
        target_soc=generated_case.get("target_soc", target),
        nearest_target=conf.get("top") or "(pending onboarding)",
        evidence_source=generated_case.get("evidence_source", ""),
        kernel_source=kernel_source, kernel_commit=kernel_commit,
        evidence=evidence, reasoning_fingerprints=reasoning.get("fingerprints", {}),
        evidence_refs=evidence_refs,
    )
    skill_outputs = dict(run_manifest.load_skill_outputs(WORKSPACE_ROOT, run_id))
    skill_outputs.update(orchestrator.last_outputs)
    result = run_manifest.write_artifacts(
        workspace_root=WORKSPACE_ROOT, run_id=run_id, manifest=manifest, state_record=state_record,
        evidence_refs=evidence_refs, evidence_provenance=None, skill_outputs=skill_outputs, case=None,
    )
    print(f"  wrote {len(result['files'])} attempt artifacts to {result['dir']}")


def do_onboard(target: str, cli_kernel_source: str | None, analysis_engine: str = "qgenie",
                test_mode: bool = False, analysis_timeout: int | None = None) -> None:
    """Detect the nearest existing target and propose targets/<target>/case.generated.py.

    Read-only w.r.t. the kernel tree and case.py: it invokes only the
    target_onboarding skill (which stops at SUCCESS behind the human-review gate),
    then writes proposal artifacts. It NEVER calls run_bringup, drives no BringupState
    transition past INIT, generates no kernel code, and never writes case.py.

    The reasoning step is QGenie/Claude-backed and MANDATORY (no silent fallback):
    if it's unavailable, this writes reasoning_error.json and exits non-zero
    instead of producing a fabricated or low-confidence local guess.
    """
    if not cli_kernel_source:
        raise SystemExit("--onboard requires --kernel-source (no case.py exists yet for a new target)")
    kernel_source = validate_kernel_source(cli_kernel_source)

    target_dir = TARGETS_ROOT / target
    target_dir.mkdir(parents=True, exist_ok=True)
    evidence_roots, evidence_note = _resolve_evidence_roots(target, target_dir)
    if evidence_note:
        print(f"  evidence: {evidence_note}")

    run_id, attempt, is_new_attempt = _resolve_onboarding_run_id(target)
    workspace_context = load_workspace_context(WORKSPACE_ROOT)
    workspace_context["kernel_source"] = kernel_source

    orchestrator = BringupOrchestrator(workspace_root=WORKSPACE_ROOT, skills_root=SKILLS_ROOT, run_id=run_id)
    orchestrator.register_runner("target_onboarding", run_target_onboarding)
    try:
        orchestrator.resume_run()
    except OrchestratorError as exc:
        if exc.code != "RUN_NOT_FOUND":
            raise
        orchestrator.start_run(target_soc=target, nearest_target="(pending onboarding)")
    status = "new attempt" if is_new_attempt else "resuming in-flight attempt"
    print(f"onboarding {target} (run {run_id}, attempt {attempt} [{status}], "
          f"engine={analysis_engine}{'  [TEST MODE]' if test_mode else ''})")

    envelope = {
        "workspace_context": workspace_context,
        "target_name": target,
        "kernel_source_path": cli_kernel_source,
        "run_id": run_id,
        "evidence_roots": evidence_roots,
        "analysis_engine": analysis_engine,
        "test_mode": test_mode,
        "analysis_timeout": analysis_timeout,
    }
    try:
        output = orchestrator.invoke_skill("target_onboarding", envelope)
    except OrchestratorError as exc:
        cause = exc.__cause__
        if isinstance(cause, ReasoningUnavailableError):
            _write_reasoning_error_artifact(target_dir, cause)
            print(f"FAILED: QGenie/IPCAT analysis unavailable — {cause.code}: {cause.message}", file=sys.stderr)
            raise SystemExit(1) from cause
        raise

    # ── Phase-2A WP8 — Schematic ↔ IPCAT Cross-Verification wiring ───────────
    # Runs only when the chip is RESOLVED (via phase1b_resolution.json or the
    # profile's ``resolved_chip`` field). Silent try/except: this is diagnostic
    # only — must never break onboarding. No timestamps, no random ordering.
    try:
        _run_crossverify(target, target_dir, output)
    except Exception as exc:  # noqa: BLE001 — diagnostic never propagates
        print(f"  [crossverify] skipped: {type(exc).__name__}: {exc}")

    _write_onboarding_artifacts(target_dir, output)
    _record_onboarding_artifacts(target=target, run_id=run_id, attempt=attempt,
                                  kernel_source=kernel_source, output=output, orchestrator=orchestrator)

    conf = output["similarity_report"]["confidence"]
    top = conf.get("top") or "(none)"
    print(f"  nearest target : {top}  (score {conf.get('score')}, confidence {conf.get('confidence')})")
    if output.get("human_review_needed"):
        print("  HUMAN REVIEW NEEDED — see NEEDS_REVIEW in onboarding_report.md")
    print(f"  wrote proposal artifacts to {target_dir}")
    print(f"  NEXT: review case.generated.py, then `mv {target_dir}/case.generated.py {target_dir}/case.py` to activate")


def _write_reasoning_error_artifact(target_dir: Path, exc: ReasoningUnavailableError) -> None:
    """On QGenie unavailability, write ONLY a structured error artifact — never a
    fabricated/local-guess profile, and never case.generated.py."""
    from datetime import datetime, timezone
    payload = {
        "code": exc.code,
        "message": exc.message,
        "details": exc.details,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    (target_dir / "reasoning_error.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _resolve_evidence_roots(target: str, target_dir: Path) -> tuple[dict[str, str], str]:
    """Discover the REAL evidence roots for a target; never fabricate empty ones.

    The v1.1 bug: this created empty ``evidence/{ipcat,offline}`` dirs and pointed
    the runner at them, so real datasheets sitting in a sibling ``offline/`` /
    ``ipcat/`` folder were never seen (files:[] → codecs:[] → misleading result).

    Resolution per source, first non-empty wins, checked in this order:
      1. ``targets/<t>/evidence/<sub>``  (the documented convention)
      2. ``targets/<t>/<legacy>``        (legacy sibling: ``offline/`` / ``ipcat/``)
    A root is only included if it exists AND contains at least one file. We do NOT
    mkdir empty dirs — if nothing is found, the key is omitted so the downstream
    evidence gate fails honestly rather than on a fabricated empty directory.

    Returns (evidence_roots, human-readable note).
    """
    base_rel = f"audio_bu_skill/targets/{target}/evidence"
    # (root_key, [candidate relative dirs in priority order])
    plan = [
        ("ipcat", [f"{base_rel}/ipcat", f"audio_bu_skill/targets/{target}/ipcat"]),
        ("offline_documents", [f"{base_rel}/offline", f"audio_bu_skill/targets/{target}/offline"]),
    ]
    roots: dict[str, str] = {}
    notes: list[str] = []
    for root_key, candidates in plan:
        for rel in candidates:
            abs_dir = WORKSPACE_ROOT / rel
            if abs_dir.is_dir() and _dir_has_file(abs_dir):
                roots[root_key] = rel
                notes.append(f"{root_key} -> {rel}")
                break
    if not roots:
        notes.append(
            f"NO EVIDENCE FOUND under targets/{target}/ (evidence/{{ipcat,offline}} "
            "or legacy ipcat/, offline/) — the evidence gate will fail; drop "
            "datasheets/schematics/IPCAT exports in first"
        )
    return roots, "; ".join(notes)


def _dir_has_file(directory: Path) -> bool:
    return any(f.is_file() for f in directory.rglob("*"))


def _write_onboarding_artifacts(target_dir: Path, output: dict) -> None:
    """Write the proposal artifacts. NEVER writes case.py."""
    reasoning = output.get("_reasoning") or {}
    (target_dir / "profile.json").write_text(
        json.dumps(output["target_profile"], indent=2) + "\n", encoding="utf-8")
    (target_dir / "similarity_report.json").write_text(
        json.dumps(output["similarity_report"], indent=2) + "\n", encoding="utf-8")
    (target_dir / "evidence_inventory.json").write_text(
        json.dumps(output["evidence_inventory"], indent=2) + "\n", encoding="utf-8")
    (target_dir / "case.generated.py").write_text(
        _render_case_generated(output["generated_case"]), encoding="utf-8")
    (target_dir / "onboarding_report.md").write_text(
        _render_onboarding_report(output), encoding="utf-8")
    if reasoning:
        # gitignored — may embed confidential evidence paths/content; artifact only,
        # never JSONL/state (RAW_CONTENT_FORBIDDEN).
        (target_dir / "qgenie_task_spec.json").write_text(
            json.dumps(reasoning.get("task_spec", {}), indent=2) + "\n", encoding="utf-8")
        (target_dir / "qgenie_raw_output.txt").write_text(
            reasoning.get("raw_text", ""), encoding="utf-8")
        (target_dir / "qgenie_analysis.json").write_text(
            json.dumps(reasoning.get("analysis", {}), indent=2) + "\n", encoding="utf-8")


def _py_literal(value) -> str:
    """Render a JSON-ish value as a Python literal for the generated case file."""
    return json.dumps(value, indent=8).replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")


def _render_case_generated(gc: dict) -> str:
    """Emit a valid Python file building a BringupCase, with NEEDS_REVIEW markers.

    Named case.generated.py so main.load_case (which imports case.py) never picks
    it up. Promotion to case.py is a manual rename by the engineer.
    """
    needs_review = gc.get("needs_review") or []
    review_by_field = {}
    for note in needs_review:
        field_name = note.split(":", 1)[0].strip()
        review_by_field.setdefault(field_name, []).append(note.split(":", 1)[1].strip() if ":" in note else note)

    def field_line(name: str, value, always_comment: str | None = None) -> str:
        literal = _py_literal(value)
        comment = ""
        notes = review_by_field.get(name)
        if notes:
            comment = f"  # NEEDS_REVIEW: {'; '.join(notes)}"
        elif always_comment:
            comment = f"  # {always_comment}"
        return f"    {name}={literal},{comment}"

    lines = [
        '"""AUTO-GENERATED by target_onboarding (v1.1 Phase 1) — DO NOT trust blindly.',
        "",
        "This is a PROPOSED case, not an active one. Review every field — especially",
        "those marked NEEDS_REVIEW below — then rename this file to case.py to activate:",
        "",
        "    mv case.generated.py case.py",
        "",
        "Nothing here was compiled or applied to the kernel tree; codecs, power model,",
        "and nearest_target are best-effort detections requiring human confirmation.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from orchestrator.bringup_walk import BringupCase",
        "",
    ]
    if needs_review:
        lines.append("# NEEDS_REVIEW summary:")
        lines.extend(f"#   - {note}" for note in needs_review)
        lines.append("")
    lines.append("CASE = BringupCase(")
    lines.append(field_line("target_soc", gc.get("target_soc", "")))
    lines.append(field_line("nearest_target", gc.get("nearest_target", "")))
    lines.append(field_line("run_id", gc.get("run_id", "")))
    lines.append(field_line("inherit_from", gc.get("inherit_from", ""),
                            always_comment="empty = no inheritance; set to a parent target name to inherit"))
    lines.append(field_line("evidence_source", gc.get("evidence_source", "ipcat_first")))
    lines.append(field_line("evidence_roots", gc.get("evidence_roots", {})))
    lines.append(field_line("kernel_source_path", gc.get("kernel_source_path", "")))
    lines.append(field_line("power_model_source", gc.get("power_model_source", "")))
    lines.append(field_line("codec_part_numbers", gc.get("codec_part_numbers", [])))
    lines.append(field_line("codec_verdicts", gc.get("codec_verdicts", {})))
    if gc.get("audio_topology"):
        lines.append(field_line("audio_topology", gc["audio_topology"]))
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _render_kernel_history_section(gc: dict) -> list[str]:
    """Onboarding Accuracy Upgrade slice 7: surface kernel_history's FROMLIST/RFC
    candidates (already in generated_case["candidate_patch_series"] since slice 6)
    in the human-readable report. Additive — omitted entirely when absent, so a
    pre-slice-6 generated_case renders exactly as before."""
    candidates = gc.get("candidate_patch_series") or []
    if not candidates:
        return []
    lines = [
        "",
        "## Kernel History / FROMLIST Findings",
        "",
        "Candidate commits found via read-only kernel git archaeology "
        "(`git log`/`show`/`merge-base` only — never applied or checked out):",
        "",
    ]
    for c in candidates:
        applied = c.get("applied")
        applied_str = "applied (already an ancestor of HEAD)" if applied is True else \
            "unapplied" if applied is False else "unknown"
        files_changed = c.get("files_changed") or []
        shown_files = ", ".join(f"`{f}`" for f in files_changed[:5])
        if len(files_changed) > 5:
            shown_files += f", … (+{len(files_changed) - 5} more)"
        lines.append(f"### `{(c.get('sha') or '')[:12]}` — {c.get('subject', '(no subject)')}")
        lines.append("")
        lines.append(f"- status               : {applied_str}")
        if c.get("donor_hint"):
            lines.append(f"- donor hint            : {c['donor_hint']}")
        compat = c.get("compatible_fallbacks") or []
        if compat:
            lines.append(f"- compatible fallbacks  : {', '.join(f'`{x}`' for x in compat)}")
        lines.append(f"- files changed         : {shown_files or '(none recorded)'}")
        lines.append("")
    return lines


def _render_power_model_inspection_section(gc: dict) -> list[str]:
    """Slice 7: surface power_model_hint (rpmhpd.c LCX/LMX inspection, folded into
    generated_case["audio_topology"]["power_model"]["inspection_hint"] since slice
    6) in the report. Additive — omitted when audio_topology/inspection_hint absent."""
    hint = ((gc.get("audio_topology") or {}).get("power_model") or {}).get("inspection_hint")
    if not hint:
        return []
    lines = [
        "",
        "## Power Model Inspection",
        "",
        "Best-effort `rpmhpd.c` LCX/LMX inspection (read-only; corroborating "
        "evidence only — never auto-finalizes `power_model_source`):",
        "",
        f"- status        : `{hint.get('status')}`",
        f"- kind          : `{hint.get('kind')}`",
        f"- LCX present   : {hint.get('lcx_present')}",
        f"- LMX present   : {hint.get('lmx_present')}",
        f"- LCX+LMX both  : {hint.get('lcx_lmx_present')}",
    ]
    citations = hint.get("citations") or []
    if citations:
        lines.append(f"- citations     : {', '.join(f'`{c}`' for c in citations)}")
    lines.append(
        "- needs human review: **yes — power model is never auto-finalized; "
        "confirm rpmhpd vs. SCMI with the Power team**"
    )
    lines.append("")
    return lines


def _render_pin_crosscheck_section(gc: dict) -> list[str]:
    """Slice 7: surface pin_crosscheck verdicts (folded into generated_case
    ["audio_topology"]["pin_crosschecks"] since slice 6) in the report. Additive —
    omitted when no schematic nets were cross-checked."""
    verdicts = (gc.get("audio_topology") or {}).get("pin_crosschecks") or []
    if not verdicts:
        return []
    lines = [
        "",
        "## Pin Cross-Check",
        "",
        "Schematic-derived GPIO/net findings cross-checked against candidate patches' "
        "DT GPIO assignments. A mismatch is a NEEDS_REVIEW signal, never a hard failure:",
        "",
        "| signal | schematic GPIO | patch/DT GPIO | match | needs review |",
        "|--------|----------------|---------------|-------|--------------|",
    ]
    for v in verdicts:
        match = v.get("match")
        match_str = "✅ match" if match is True else "❌ mismatch" if match is False else "⚠️ unresolved"
        needs_review = "yes" if match is not True else "no"
        patch_gpio = v.get("patch_gpio")
        lines.append(
            f"| {v.get('signal', '')} | {v.get('schematic_gpio')} | "
            f"{patch_gpio if patch_gpio is not None else '—'} | {match_str} | {needs_review} |"
        )
    lines.append("")
    return lines


def _render_ipcat_findings_section(gc: dict) -> list[str]:
    """Fix #4 (Benchmark Readiness): surface IPCAT coverage clarity (folded into
    generated_case["audio_topology"]["ipcat_findings"] by
    target_onboarding_runner._ipcat_evidence_summary) in the report. Additive —
    omitted when audio_topology/ipcat_findings absent."""
    findings = (gc.get("audio_topology") or {}).get("ipcat_findings")
    if not findings:
        return []
    lines = [
        "",
        "## IPCAT Coverage",
        "",
        "Diagnostic-only: whether IPCAT evidence was queried and whether it was "
        "target-specific or only generic multi-SoC boilerplate. The orchestrator "
        "cannot observe live MCP tool calls itself, so the MCP fields below are "
        "QGenie's own self-report, combined with the orchestrator's own count of "
        "offline-cached `evidence/ipcat/` files:",
        "",
        f"- status                         : `{findings.get('status')}`",
        f"- summary                        : {findings.get('summary')}",
        f"- offline IPCAT files found      : {findings.get('offline_file_count')}",
        f"- IPCAT MCP query requested      : {findings.get('mcp_requested')}",
        f"- IPCAT MCP query self-reported  : {findings.get('mcp_queried_self_reported')}",
        f"- MCP returned target-specific   : {findings.get('mcp_returned_target_specific')}",
        f"- MCP returned generic only      : {findings.get('mcp_returned_generic_only')}",
    ]
    notes = findings.get("self_report_notes")
    if notes:
        lines.append(f"- self-report notes              : {notes}")
    citations = findings.get("self_report_citations") or []
    if citations:
        lines.append(f"- self-report citations          : {', '.join(f'`{c}`' for c in citations)}")
    lines.append("")
    return lines


def _render_confidence_ledger(gc: dict) -> list[str]:
    """Track B / WP-B: a per-domain trust summary rendered as an additive report
    section. Diagnostic-only — no onboarding decision or promotion path reads it.

    Mirrors the sibling `_render_*_section(gc) -> list[str]` contract: reads only
    data already in `gc` (`audio_topology` + `needs_review`), null-guarded like
    the other sections. Renders all 9 fixed domains for any real run (a *gauge*);
    returns [] only for a truly empty generated_case so a bare fixture is
    unaffected. The raw analysis envelope is not available at render time, so
    dt_topology derives from audio_topology alone (resolves to MISSING when the
    only source is the raw envelope's buses/schematic_nets)."""
    if not gc:
        return []
    rows = confidence_ledger.build_ledger(gc, None)
    if not rows:
        return []
    lines = [
        "",
        "## Confidence Ledger",
        "",
        "Per-domain confidence and provenance. **Diagnostic only — does not change "
        "onboarding decisions.** `CORROBORATED` means ≥2 sources *agree*, not that "
        "they are *correct*. The band reflects the domain's weakest (governing) "
        "field (conservative min-roll-up). `MISSING`/`NEEDS_REVIEW`/`VERIFY` rows "
        "are the reviewer work list; `CORROBORATED` rows need no action.",
        "",
        "| Domain | Confidence | Status | Evidence source (abbrev) | KB rule |",
        "|--------|-----------|--------|--------------------------|---------|",
    ]
    for row in rows:
        sources = ", ".join(f"`{s}`" for s in row["sources"]) if row["sources"] else "—"
        rule_ids = ", ".join(f"`{r}`" for r in row["rule_ids"]) if row["rule_ids"] else "—"
        lines.append(
            f"| {row['domain']} | {row['band']} | {row['status']} | {sources} | {rule_ids} |"
        )
    lines.append("")
    return lines


_CARDINALITY_VERDICT_GLYPH: dict[str, str] = {
    cardinality_authority.VERDICT_AGREE: "✅ agree",
    cardinality_authority.VERDICT_DISAGREE: "⚠️ disagree",
    cardinality_authority.VERDICT_DISAGREE_WITH_AUTHORITY: "⚠️ disagree_with_authority",
    cardinality_authority.VERDICT_NOT_CROSS_CHECKABLE: "ℹ️ not_cross_checkable",
    cardinality_authority.VERDICT_BENIGN_DIVERGENCE: "ℹ️ benign_divergence",
}


# ── Phase-2A WP8 — Schematic ↔ IPCAT Cross-Verification renderer ────────────
_CROSSVERIFY_TRACK_ORDER: tuple[str, ...] = ("T1", "T2", "T3", "T4a", "T4b", "T5")
_CROSSVERIFY_VERDICT_ORDER: tuple[str, ...] = (
    "MATCH",
    "PARTIAL_MATCH",
    "DISAGREE_WITH_AUTHORITY",
    "NOT_CROSS_CHECKABLE",
    "REVIEW_REQUIRED",
)


def _resolved_chip_for_target(target: str, target_dir: Path, gc: dict) -> str | None:
    """Return the resolved chip alias/id for cross-verification, or None.

    Priority (WP8): (1) ``targets/<t>/phase1b_resolution.json`` if present with
    a non-empty ``resolved_chip`` field; (2) ``gc["resolved_chip"]`` on the
    profile. Any I/O error is treated as "not resolved" — the caller silently
    skips cross-verification in that case.
    """
    p1b = target_dir / "phase1b_resolution.json"
    if p1b.is_file():
        try:
            data = json.loads(p1b.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            chip = data.get("resolved_chip")
            if isinstance(chip, str) and chip:
                return chip
    if isinstance(gc, dict):
        chip = gc.get("resolved_chip")
        if isinstance(chip, str) and chip:
            return chip
    return None


def _crossverify_source_facts(gc: dict) -> dict[str, object]:
    """Assemble per-track source-facts from the generated-case profile.

    Mapping (WP8 requirement):
      T1 GPIO   → ``gc["audio_topology"]["pinmux"]`` or profile ``audio_pins``
      T2 bus    → ``gc["audio_topology"]["soundwire"]``
      T3 counts → pass ``gc`` unchanged
      T4a soc   → ``gc["audio_topology"]["endpoints"]`` or ``soc_endpoints``
      T4b codec → ``gc["audio_topology"]["codecs"]``
      T5 DTS    → read ``*.dts``/``*.dtsi`` files under ``targets/<t>/dts/``
    """
    topology = (gc.get("audio_topology") if isinstance(gc, dict) else None) or {}
    t1 = topology.get("pinmux") or gc.get("audio_pins") or {}
    t2 = topology.get("soundwire") or {}
    t4a = topology.get("endpoints") or gc.get("soc_endpoints") or {}
    t4b = topology.get("codecs") or {}
    return {"t1": t1, "t2": t2, "t4a": t4a, "t4b": t4b}


def _load_dts_files(target_dir: Path) -> list[dict[str, str]]:
    """Load ``*.dts`` / ``*.dtsi`` under ``targets/<t>/dts/`` for track T5.

    Returns an empty list if the directory does not exist. Files are read once
    each, sorted by path for determinism, and returned as ``[{name, text}, …]``.
    Any per-file OSError is silently skipped — T5 will treat missing DTS as
    NCC(revision_not_pinned) or authority_out_of_scope by itself.
    """
    dts_dir = target_dir / "dts"
    if not dts_dir.is_dir():
        return []
    entries: list[dict[str, str]] = []
    paths = sorted(list(dts_dir.rglob("*.dts")) + list(dts_dir.rglob("*.dtsi")))
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entries.append({"name": str(p.relative_to(target_dir)), "text": text})
    return entries


def _run_crossverify(target: str, target_dir: Path, output: dict) -> None:
    """Phase-2A WP8 orchestrator wiring — six-track cross-verification.

    Only runs when the chip is RESOLVED (Phase-1B artifact OR profile). Uses
    the read-only, TLS-verified transport built by
    ``crossverify_collector._live_transport()``. Every step is best-effort:
    the caller wraps this in try/except and never propagates failure.
    """
    gc = output.get("generated_case")
    if not isinstance(gc, dict):
        print("  [crossverify] skipped: no generated_case on output")
        return
    chip = _resolved_chip_for_target(target, target_dir, gc)
    if not chip:
        print("  [crossverify] skipped: chip not resolved (no phase1b_resolution.json)")
        return

    from orchestrator.reasoning import crossverify
    from orchestrator.runners import crossverify_collector

    transport = crossverify_collector._live_transport()
    snapshot = crossverify_collector.collect_snapshot(chip, transport=transport)
    facts = _crossverify_source_facts(gc)
    dts = _load_dts_files(target_dir)

    all_rows: list = []
    all_rows += list(crossverify.track_t1(snapshot=snapshot, source=facts["t1"]) or [])
    all_rows += list(crossverify.track_t2(snapshot=snapshot, source=facts["t2"]) or [])
    all_rows += list(crossverify.track_t3(snapshot=snapshot, gc=gc) or [])
    all_rows += list(crossverify.track_t4a(snapshot=snapshot, source=facts["t4a"]) or [])
    all_rows += list(crossverify.track_t4b(snapshot=snapshot, source=facts["t4b"]) or [])
    all_rows += list(crossverify.track_t5(snapshot=snapshot, dts=dts) or [])

    gc["cross_verification"] = {
        "rows": [row.to_dict() for row in all_rows],
        "snapshot_provenance": snapshot.get("provenance") or {},
    }
    print(f"  [crossverify] chip={chip}  rows={len(all_rows)}")


def _render_cardinality_section(gc: dict) -> list[str]:
    """Track C / WP-C: per-element-class cardinality cross-check rendered as an
    additive report section. Diagnostic-only — no onboarding decision, promotion,
    or gating path reads it (mirrors the Confidence Ledger contract).

    Reads only `gc["audio_topology"]["element_counts"]` (schema 1.3.0 / Fix A),
    null-guarded like the sibling `_render_*_section(gc)` code. Returns [] when a
    case carries no element_counts (a pre-1.3.0 run), so the section simply does
    not appear and older reports are byte-unchanged."""
    if not gc:
        return []
    rows = cardinality_authority.compare_element_counts(gc)
    if not rows:
        return []
    lines = [
        "",
        "## Cardinality Authority",
        "",
        "Per-element-class instance-count cross-check across independent "
        "enumeration lanes (dt / evidence / proposal; catalog is the post-SWI "
        "authority, always empty pre-SWI). **Diagnostic only — does not change "
        "onboarding decisions.** `agree` means the available lanes report the same "
        "count (not that the count is *correct*); `not_cross_checkable` means <2 "
        "usable lanes (silence would falsely imply agreement); `disagree` rows are "
        "the reviewer work list. A `dt` lane that is 0 only because the audio "
        "scaffolding is unapplied at the pinned HEAD (`dt_applied=false`), and any "
        "count the reasoning pass flagged `ambiguous`, are excluded from the "
        "cross-check by design.",
        "",
        "| Element class | Counts (lane→n) | Verdict | KB rule | Notes |",
        "|---------------|-----------------|---------|---------|-------|",
    ]
    for row in rows:
        counts = row["counts"]
        counts_str = ", ".join(f"{s}={n}" for s, n in counts.items()) if counts else "—"
        verdict = _CARDINALITY_VERDICT_GLYPH.get(row["verdict"], row["verdict"])
        rule = f"`{row['rule_id']}`" if row.get("rule_id") else "—"
        note_parts = list(row.get("notes") or [])
        if row.get("ambiguous"):
            note_parts.insert(0, f"ambiguous: {row.get('ambiguity_note') or 'unresolved count'}")
        notes_str = "; ".join(note_parts) if note_parts else "—"
        lines.append(
            f"| {row['element_class']} | {counts_str} | {verdict} | {rule} | {notes_str} |"
        )
    lines.append("")
    return lines


def _render_crossverify_section(gc: dict) -> list[str]:
    """Phase-2A WP8: Schematic ↔ IPCAT Cross-Verification section (additive).

    Renders the six-track verification result attached by the WP8 orchestrator
    wiring at ``gc["cross_verification"]`` (a dict with ``rows`` and
    ``snapshot_provenance``). Mirrors ``_render_cardinality_section``:
    null-guarded, list-of-strings return, byte-unchanged report when there are
    no rows. Pure — no I/O, no timestamps; identical input → identical output.
    """
    if not gc:
        return []
    cv = gc.get("cross_verification")
    if not isinstance(cv, dict):
        return []
    rows = cv.get("rows") or []
    if not rows:
        return []

    provenance = cv.get("snapshot_provenance") or {}
    lines: list[str] = [
        "",
        "## Schematic ↔ IPCAT Cross-Verification",
        "",
        "Six-track cross-verification between the schematic/design-side facts and "
        "the IPCAT authority. **Diagnostic only** — does not change onboarding "
        "decisions or generated case content. Tracks: T1 GPIO, T2 SoundWire bus, "
        "T3 element counts, T4a SoC endpoint, T4b codec binding (permanent OOS), "
        "T5 DTS consistency.",
        "",
        "### Snapshot provenance",
        "",
    ]
    # Deterministic sub-header — one line per key, fixed order (chip / tls /
    # readonly_tools / gpio_map). Missing keys render as "—".
    chip = gc.get("resolved_chip") or provenance.get("chip") or "—"
    tls = provenance.get("tls")
    if isinstance(tls, dict):
        tls_str = f"verify={tls.get('verify')}, ssl_cert_file={tls.get('ssl_cert_file')}"
    else:
        tls_str = "—"
    readonly_tools = provenance.get("readonly_tools")
    if isinstance(readonly_tools, (list, tuple)):
        readonly_str = ", ".join(str(t) for t in readonly_tools) or "—"
    else:
        readonly_str = "—"
    gpio_map = provenance.get("gpio_map")
    if isinstance(gpio_map, dict):
        gpio_str = f"id={gpio_map.get('id')}, release={gpio_map.get('release')}"
    else:
        gpio_str = "—"
    lines += [
        f"- chip           : `{chip}`",
        f"- tls            : {tls_str}",
        f"- readonly_tools : {readonly_str}",
        f"- gpio_map       : {gpio_str}",
    ]

    # Verdict summary — one line per verdict kind, only when count > 0.
    verdict_counts: dict[str, int] = {v: 0 for v in _CROSSVERIFY_VERDICT_ORDER}
    for row in rows:
        v = row.get("verdict")
        if v in verdict_counts:
            verdict_counts[v] += 1
    if any(n > 0 for n in verdict_counts.values()):
        lines += ["", "### Verdict summary", ""]
        for v in _CROSSVERIFY_VERDICT_ORDER:
            n = verdict_counts[v]
            if n > 0:
                lines.append(f"- {v}: {n}")

    # Row table grouped by track T1 → T2 → T3 → T4a → T4b → T5; rows sorted by
    # subject within each track for determinism.
    lines += [
        "",
        "### Rows",
        "",
        "| track | subject | verdict | confidence | warning |",
        "|-------|---------|---------|------------|---------|",
    ]
    by_track: dict[str, list[dict]] = {t: [] for t in _CROSSVERIFY_TRACK_ORDER}
    for row in rows:
        t = row.get("track")
        if t in by_track:
            by_track[t].append(row)
    for track in _CROSSVERIFY_TRACK_ORDER:
        track_rows = sorted(by_track[track], key=lambda r: str(r.get("subject") or ""))
        for row in track_rows:
            subject = row.get("subject") or "—"
            verdict = row.get("verdict") or "—"
            confidence = row.get("confidence") or "—"
            warning = "⚠️" if row.get("warning") else ""
            lines.append(f"| {track} | {subject} | {verdict} | {confidence} | {warning} |")

    # Reviewer worklist — rows where warning=True OR verdict==REVIEW_REQUIRED.
    worklist = [
        row for row in rows
        if row.get("warning") is True or row.get("verdict") == "REVIEW_REQUIRED"
    ]
    if worklist:
        # Sort by (track order, subject) for determinism.
        track_idx = {t: i for i, t in enumerate(_CROSSVERIFY_TRACK_ORDER)}
        worklist.sort(key=lambda r: (
            track_idx.get(r.get("track"), len(_CROSSVERIFY_TRACK_ORDER)),
            str(r.get("subject") or ""),
        ))
        lines += ["", "### Reviewer worklist", ""]
        for row in worklist:
            actions = row.get("review_actions") or []
            first_action = actions[0] if actions else "—"
            lines.append(
                f"- **{row.get('track')} / {row.get('subject')}** "
                f"({row.get('verdict')}): {first_action}"
            )
    lines.append("")
    return lines


def _render_onboarding_report(output: dict) -> str:
    """Human-readable Markdown onboarding report with cited evidence."""
    gc = output["generated_case"]
    sim = output["similarity_report"]
    conf = sim["confidence"]
    profile = output["target_profile"]
    ranked = sim["ranked"]

    def fmt_signal(v) -> str:
        return "n/a" if v is None or v == -1.0 else f"{v:.2f}"

    lines = [
        f"# Onboarding report — {profile['target_name']}",
        "",
        "> AUTO-GENERATED by `target_onboarding` (v1.1 Phase 1). This proposes a case;",
        "> it does **not** activate one, generate kernel code, or compile anything.",
        "",
        "## Inputs",
        "",
        f"- target name        : `{profile['target_name']}`",
        f"- detected SoC        : `{profile.get('soc') or 'UNKNOWN'}`",
        f"- kernel source       : `{output['evidence_inventory'].get('kernel_source_path', '')}`",
        f"- evidence files seen : {len(output['evidence_inventory'].get('files', []))}",
        "",
        "## Nearest-target ranking",
        "",
        f"Confidence: **{conf.get('confidence')}** (top score {conf.get('score')}, "
        f"margin {conf.get('margin')}; thresholds score≥{conf.get('min_score')}, margin≥{conf.get('min_margin')}). "
        f"{'⚠️ LOW CONFIDENCE — human review required.' if conf.get('low_confidence') else '✅ Confident match.'}",
        "",
        "| target | overall | codecs | power | dt | audioreach | soundwire | soc |",
        "|--------|---------|--------|-------|----|-----------|-----------|-----|",
    ]
    for r in ranked:
        ps = r["per_signal"]
        lines.append(
            f"| {r['target_name']} | {r['overall']:.2f} | {fmt_signal(ps.get('codecs'))} | "
            f"{fmt_signal(ps.get('power_domain_providers'))} | {fmt_signal(ps.get('dt_compatibles'))} | "
            f"{fmt_signal(ps.get('audioreach'))} | {fmt_signal(ps.get('soundwire'))} | {fmt_signal(ps.get('soc'))} |"
        )
    weights = ", ".join(f"{k} {v}" for k, v in sim["weights"].items())
    lines += ["", f"_Signal weights: {weights}._", ""]

    lines += [
        "## Proposed case fields",
        "",
        "| field | value | status |",
        "|-------|-------|--------|",
    ]
    review_fields = {n.split(":", 1)[0].strip() for n in (gc.get("needs_review") or [])}
    for name in ("target_soc", "nearest_target", "run_id", "inherit_from", "evidence_source",
                 "kernel_source_path", "power_model_source", "codec_part_numbers"):
        val = gc.get(name)
        status = "⚠️ NEEDS_REVIEW" if name in review_fields else "proposed"
        shown = json.dumps(val) if not isinstance(val, str) else val
        if isinstance(shown, str) and len(shown) > 80:
            shown = shown[:77] + "..."
        lines.append(f"| `{name}` | {shown} | {status} |")

    lines += ["", "## NEEDS_REVIEW", ""]
    if gc.get("needs_review"):
        lines.extend(f"- {note}" for note in gc["needs_review"])
    else:
        lines.append("- (none — all fields confidently derived; still confirm before promoting)")

    lines += [
        "",
        "## Cited evidence",
        "",
        "Signals were derived from these files:",
        "",
    ]
    for signal, files in sorted((profile.get("cites") or {}).items()):
        lines.append(f"- **{signal}**: {', '.join(f'`{f}`' for f in files)}")

    lines += _render_kernel_history_section(gc)
    lines += _render_power_model_inspection_section(gc)
    lines += _render_pin_crosscheck_section(gc)
    lines += _render_ipcat_findings_section(gc)
    lines += _render_confidence_ledger(gc)
    lines += _render_cardinality_section(gc)
    lines += _render_crossverify_section(gc)

    lines += [
        "",
        "## Promotion",
        "",
        "1. Review `case.generated.py` and every NEEDS_REVIEW field above.",
        "2. Confirm the power model with the Power team (never auto-finalized).",
        "3. Promote:",
        "",
        "   ```",
        "   mv case.generated.py case.py",
        "   ```",
        "",
        "4. Run the normal v1.0 flow: "
        "`PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target "
        f"{profile['target_name']}`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    if args.replay:
        do_replay(args.replay)
        return
    if args.rerun:
        sys.exit(do_rerun(args.rerun, args.kernel_source))
    if args.onboard:
        do_onboard(args.onboard, args.kernel_source, args.analysis_engine, args.test_mode,
                   analysis_timeout=args.analysis_timeout)
        return
    do_run(args.target, args.evidence_source, args.kernel_source)


if __name__ == "__main__":
    main()
