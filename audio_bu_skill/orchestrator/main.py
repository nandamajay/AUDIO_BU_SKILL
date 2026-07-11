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
    # (v1.1 Phase 1 — read-only, never writes case.py, never generates code)
    python -m orchestrator.main --onboard my-new-target --kernel-source linux-nord

Kernel-source resolution (first present wins): --kernel-source, then the case's
own kernel_source_path; a run fails only if neither yields a valid kernel tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from orchestrator import run_manifest
from orchestrator.bringup_walk import BringupCase, EVIDENCE_SOURCES, merge_cases, run_bringup, validate_case
from orchestrator.driver import BringupOrchestrator, OrchestratorError
from orchestrator.runners.codec_driver_porting_runner import run_codec_driver_porting
from orchestrator.runners.source_intake_runner import discover_evidence, run_source_intake
from orchestrator.runners.target_onboarding_runner import run_target_onboarding
from orchestrator.runners.triage_runner import run_triage
from orchestrator.workspace_loader import load_workspace_context

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
    args = parser.parse_args()
    if not (args.target or args.replay or args.rerun or args.onboard):
        parser.error("one of --target, --replay, --rerun, or --onboard is required")
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
# onboarding mode (v1.1 Phase 1) — standalone; never enters run_bringup
# --------------------------------------------------------------------------- #
def do_onboard(target: str, cli_kernel_source: str | None) -> None:
    """Detect the nearest existing target and propose targets/<target>/case.generated.py.

    Read-only w.r.t. the kernel tree and case.py: it invokes only the
    target_onboarding skill (which stops at SUCCESS behind the human-review gate),
    then writes proposal artifacts. It NEVER calls run_bringup, drives no BringupState
    transition past INIT, generates no kernel code, and never writes case.py.
    """
    if not cli_kernel_source:
        raise SystemExit("--onboard requires --kernel-source (no case.py exists yet for a new target)")
    kernel_source = validate_kernel_source(cli_kernel_source)

    target_dir = TARGETS_ROOT / target
    target_dir.mkdir(parents=True, exist_ok=True)
    evidence_roots = _default_evidence_roots(target, target_dir)

    run_id = f"{target}-onboarding"
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
    print(f"onboarding {target} (run {run_id})")

    envelope = {
        "workspace_context": workspace_context,
        "target_name": target,
        "kernel_source_path": cli_kernel_source,
        "run_id": run_id,
        "evidence_roots": evidence_roots,
    }
    output = orchestrator.invoke_skill("target_onboarding", envelope)

    _write_onboarding_artifacts(target_dir, output)

    conf = output["similarity_report"]["confidence"]
    top = conf.get("top") or "(none)"
    print(f"  nearest target : {top}  (score {conf.get('score')}, confidence {conf.get('confidence')})")
    if output.get("human_review_needed"):
        print("  HUMAN REVIEW NEEDED — see NEEDS_REVIEW in onboarding_report.md")
    print(f"  wrote proposal artifacts to {target_dir}")
    print(f"  NEXT: review case.generated.py, then `mv {target_dir}/case.generated.py {target_dir}/case.py` to activate")


def _default_evidence_roots(target: str, target_dir: Path) -> dict[str, str]:
    """The per-target evidence convention: targets/<name>/evidence/{ipcat,offline}."""
    (target_dir / "evidence" / "ipcat").mkdir(parents=True, exist_ok=True)
    (target_dir / "evidence" / "offline").mkdir(parents=True, exist_ok=True)
    base = f"audio_bu_skill/targets/{target}/evidence"
    return {"ipcat": f"{base}/ipcat", "offline_documents": f"{base}/offline"}


def _write_onboarding_artifacts(target_dir: Path, output: dict) -> None:
    """Write the 5 proposal artifacts. NEVER writes case.py."""
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
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


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
        do_onboard(args.onboard, args.kernel_source)
        return
    do_run(args.target, args.evidence_source, args.kernel_source)


if __name__ == "__main__":
    main()
