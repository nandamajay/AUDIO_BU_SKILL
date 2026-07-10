# Audio_BU_Skill — Run & Verify Playbook

## Where the skill lives

```
/local/mnt/workspace/NORD_BU/audio_bu_skill/
├── orchestrator/                  <- the orchestrator engine (our own, not laei's run_fixture)
│   ├── main.py                    <- thin argparse CLI: --target | --replay | --rerun
│   ├── bringup_walk.py            <- generic outcome-driven run_bringup() + BringupCase model
│   ├── driver.py                  <- BringupOrchestrator: loads manifests, calls runners, validates
│   ├── run_manifest.py            <- fingerprints, run_manifest.json, artifacts/<run_id>/ writer
│   ├── bringup_state.py           <- whole-run FSM (INIT..VERIFIED / TRIAGE / BLOCKED)
│   ├── skill_state_machine.py     <- per-invocation FSM (PENDING..APPROVED)
│   ├── run_store.py               <- persists run state to ../state/<run_id>.json
│   ├── logger_json.py             <- appends JSONL events to <workspace_root>/logs/<run_id>.jsonl
│   ├── loader_skill_manifest.py   <- reads all skill.yaml manifests, validates the registry
│   ├── schema_validation.py       <- shared JSON-Schema + error-wrapping helpers
│   ├── workspace_loader.py        <- reads workspace.yaml
│   └── runners/                   <- plain-function runners (judgment-based, no run_fixture)
│       ├── source_intake_runner.py
│       ├── triage_runner.py
│       └── codec_driver_porting_runner.py
├── skills/                        <- one directory per skill = manifest + schema + validator
│   ├── audio_bu_orchestrator/     <- skill.yaml + schema.json + validator.py (no separate runner —
│   │                                  BringupOrchestrator itself IS this skill)
│   ├── source_intake/             <- skill.yaml + schema.json + validator.py
│   ├── triage/                    <- skill.yaml + schema.json + validator.py
│   └── codec_driver_porting/      <- skill.yaml + schema.json + validator.py
├── targets/                       <- one directory per bring-up target (the per-target content)
│   └── nord-iq10/
│       ├── case.py                <- exports CASE: this SoC's facts + analyst judgment
│       └── evidence/              <- (convention) locked per-source folders for new targets:
│           ├── ipcat/             <-   evidence/ipcat/    (globbed when evidence_source=ipcat|both|ipcat_first)
│           └── offline/           <-   evidence/offline/  (globbed when evidence_source=offline_documents|both, or as ipcat_first fallback)
├── state/                         <- created on first run; <run_id>.json, gitignored
└── (workspace_root)/artifacts/    <- created on first run; artifacts/<run_id>/ audit set, gitignored
```

The generic engine (`orchestrator/` + `skills/`) is target-agnostic — every
target-specific fact lives in `targets/<name>/case.py`. Nord's case reuses the
existing top-level `Documents/` folders as its evidence roots rather than the
`targets/<name>/evidence/` convention, so the large gitignored PDFs don't move.

Workspace root (one level up) also has:
```
/local/mnt/workspace/NORD_BU/
├── workspace.yaml                 <- artifact manifest the runners/loader consult
├── AUDIO_EVIDENCE_TABLE.md        <- the authoritative evidence log the diagnosis cites
├── AUDIO_SCHEMATIC_FINDINGS.md    <- schematic-derived HW facts
├── logs/<run_id>.jsonl            <- created on first run, gitignored
└── linux-nord/                    <- the actual kernel tree the DT/driver evidence comes from
```

## How to run it

```
cd /local/mnt/workspace/NORD_BU
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target nord-iq10 --evidence-source ipcat_first
```

- `--target <name>` selects `audio_bu_skill/targets/<name>/case.py`.
- `--evidence-source ipcat|offline_documents|both|ipcat_first` (optional) overrides
  the case's own `evidence_source`; omit it to use the case default (`ipcat_first`).
- `--kernel-source <path>` (optional) overrides which kernel tree the codec/DT
  evidence is read from. Resolution order, first present wins: (a) `--kernel-source`,
  (b) the case's own `kernel_source_path`, (c) fail if neither yields a valid tree.
  The path is validated: it must be a directory with `.git` and the `arch/`,
  `drivers/`, `sound/`, `Documentation/` subdirs, else the run exits naming what's
  missing. A relative path is resolved against the workspace root. Nord's case sets
  `kernel_source_path="linux-nord"`, so no flag is needed for the default run.

`--target` is one of three mutually-exclusive modes; `--replay` and `--rerun`
(below) are the other two.

No other setup needed — no venv, no extra deps beyond `jsonschema` + `pyyaml`.

- **First run** ("fresh"): prints `started run <run_id> at INIT`, walks the
  canonical trajectory invoking `source_intake`, `codec_driver_porting`, and
  (if the target hit a blocker) `triage`, printing each transition, then prints
  where the run settled.
- **Every run after that** ("resume"): prints `resumed run ... at <state>` then
  settles at the same state — idempotent, does not re-invoke skills or
  double-write state/logs.

For Nord specifically the run walks `INIT→SCAFFOLD→PATCH_APPLIED→TRIAGE→BLOCKED`
and lands in `BLOCKED` (see "What BLOCKED means" below). A target with no
compile/DT blocker and passing boot/audio outcomes instead runs all the way to
`VERIFIED`.

## How to add a new target

1. `mkdir -p audio_bu_skill/targets/<name>/evidence/{ipcat,offline}` and drop the
   IPCAT exports / schematics / datasheets into the matching subfolder.
2. Write `audio_bu_skill/targets/<name>/case.py` exporting a `CASE = BringupCase(...)`
   (copy `targets/nord-iq10/case.py` as a template). Fill in `target_soc`,
   `nearest_target`, `run_id`, `power_model_source`, `evidence_roots`, the codec
   part numbers + verdicts, and the per-gate reason strings. Supply `triage_input`
   only if the target hits a compile/DT blocker; supply `boot_outcome` /
   `audio_outcome` (`{"passed": bool, "reason": str}`) for the on-target and
   audio-path gates if the run is expected to proceed past PATCH_APPLIED.
3. **`run_id` must be unique per target** (and must contain the target name or
   SoC — `main.py` refuses to run otherwise) so `state/<run_id>.json` and
   `logs/<run_id>.jsonl` never collide between targets.
4. Run: `PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target <name>`.

### Sharing a base case with `inherit_from`

A target whose behavior is mostly the same as another's can inherit it instead of
copy-pasting. Set `inherit_from="<parent-target-name>"` in the child's `CASE`; at
load time `main.load_case` resolves the parent first and deep-merges the child over
it (a new `BringupCase` — parent files are never mutated):

- **dict fields** (`codec_verdicts`, `evidence_roots`, `triage_input`, …) merge
  key-wise: the child overrides only the keys it names and inherits the rest.
- **scalars / lists**: the child wins only when it sets a *meaningful* value; a field
  the child leaves empty (`""`, `[]`, `{}`, `None`) or at its default inherits the
  parent's. So a child that omits `nearest_target` keeps the parent's.
- self-inheritance and cycles are rejected; `inherit_from` is cleared on the
  resolved case.

The resolved case is what `validate_case` checks and what the run uses.

## Refreshing IPCAT evidence via MCP (agent-mediated)

The `qgenie-chat` IPCAT MCP tools live in the interactive Claude agent runtime,
authenticated by the session's OAuth — a `python -m orchestrator.main` subprocess
**cannot** reach them. So IPCAT-first is an *agent-mediated cache*, not a live CLI
fetch:

1. In the agent session, run the IPCAT MCP search and materialize the results into
   the target's `evidence/ipcat/` folder (for Nord, its `ipcat` root is the existing
   `Documents/IPCAT`).
2. Alongside them write `evidence/ipcat/provenance.json`:
   ```json
   {"source": "qgenie-chat:ipcat", "query": "...", "doc_ids": ["..."],
    "fetched_at": "2026-07-11T12:00:00Z",
    "files": [{"name": "...", "sha256": "..."}]}
   ```
3. Run the CLI with `--evidence-source ipcat_first`. The runner globs the `ipcat`
   root first and reads `provenance.json` into the run's `provenance.mcp`. **If the
   `ipcat` root is missing or empty** (nobody fetched, IPCAT busy) it falls back to
   `offline_documents`, recording `provenance.fell_back=true` +
   `fallback_reason` and an informational note in `ambiguities`. Fallback is a
   supported path, **not** a run failure.

Writing `evidence/ipcat/*` + `provenance.json` is the agent's job; the CLI only
consumes the on-disk cache, which is what makes replay/rerun fingerprinting trivial.

## Replay & audit — `artifacts/<run_id>/`

Every `--target` run writes an audit set to `<workspace_root>/artifacts/<run_id>/`
(idempotent — overwritten each run, so a resumed run refreshes it without degrading
it):

- `manifest.json` — run identity, kernel source, evidence source, resolved
  transitions, per-input **fingerprints**, and a lightweight `analytics` block
  (`evidence_count`, `skill_count`, `blocker_count`, `final_state`,
  `blocked_category`, `blocked_owner`, `generated_artifact_count`).
- `state.json` — the persisted FSM record.
- `evidence_refs.json` — resolved evidence paths + their sha256 + MCP provenance.
- `skill_outputs.json` — each skill's validated output (a resume layers this
  session's invocations over the prior run's, so a no-op resume keeps the real set).
- `timeline.md` (human) and `timeline.json` (dashboard/automation) — the transitions.
- `blocker_report.md` — **only when the run ended BLOCKED**: category, owner, root
  cause, proposed fix, needs-external-input, and cited evidence.

Two standalone modes read this set **without invoking any skill or touching state**:

```
# reconstruct a prior run's trajectory + blocker summary from its artifacts
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --replay nord-iq10-audio-bringup-2026-07

# compare today's inputs against a recorded run's fingerprints
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --rerun nord-iq10-audio-bringup-2026-07
```

`--rerun` recomputes fingerprints (kernel commit, each evidence file, `case.py`,
each skill version, and the framework files: `workspace.yaml` + every
`skill.yaml`/`schema.json`/`validator.py`) and diffs them against the recorded run:

- **`REPEATABLE`** (exit 0) — every input hash matches.
- **`DRIFT DETECTED`** (exit non-zero, CI-usable) — lists each changed fingerprint
  `key: old -> new` (e.g. `evidence[...JSON.gz]: <old> -> <new>`, `kernel_commit`,
  `case_sha256`, `skill_versions[triage]`).


## How to verify it end-to-end

1. **Run twice, confirm idempotency:**
   ```
   PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target nord-iq10 --evidence-source ipcat_first   # started ... -> BLOCKED
   PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target nord-iq10                                  # resumed ... -> BLOCKED (same state)
   ```

2. **Inspect persisted run state** (proves the FSM history is real, not just stdout):
   ```
   python3 -m json.tool audio_bu_skill/state/nord-iq10-audio-bringup-2026-07.json
   ```
   Check `bringup_state == "BLOCKED"`, `bringup_history` has 4 entries ending
   `TRIAGE->BLOCKED`, and `skill_invocations` has `source_intake`,
   `codec_driver_porting`, and `triage` all at `skill_state == "SUCCESS"`
   (codec_driver_porting is a live phase — it confirms the PCM1681/ADAU1979
   drivers exist in-tree before DT scaffolding is accepted).

3. **Inspect the JSONL log** (proves every skill/bring-up transition was logged with a reason):
   ```
   tail -10 logs/nord-iq10-audio-bringup-2026-07.jsonl | python3 -c \
     "import sys,json; [print(json.loads(l)['event_type'], json.loads(l).get('message','')[:90]) for l in sys.stdin]"
   ```

4. **Negative test — confirm the validator actually rejects bad output** (this is the part that
   proves the skill packages aren't decorative). Temporarily break a runner's output and re-run,
   e.g. edit `orchestrator/runners/source_intake_runner.py` to omit `evidence_source` from
   `resolved_evidence_sources`, delete `audio_bu_skill/state/nord-iq10-audio-bringup-2026-07.json`
   and `logs/nord-iq10-audio-bringup-2026-07.jsonl`, then re-run
   (`... -m orchestrator.main --target nord-iq10 --evidence-source ipcat_first`) — it should raise
   `OrchestratorError(code="SKILL_OUTPUT_INVALID", ...)` instead of silently continuing. Revert the
   runner edit afterward and re-run to restore the run to BLOCKED.

5. **Generic-walk proof (optional) — confirm the walk isn't hardwired to Nord's BLOCKED path.**
   Create a throwaway `audio_bu_skill/targets/_smoketest/case.py` with no `triage_input` and passing
   `boot_outcome`/`audio_outcome` (`{"passed": True, "reason": "..."}`), run
   `... -m orchestrator.main --target _smoketest` — it walks
   `INIT→SCAFFOLD→PATCH_APPLIED→ON_TARGET→VERIFY→VERIFIED` and settles at the terminal `VERIFIED`.
   Delete the target + its `state`/`logs` files afterward.

6. **Audit artifacts + replay/rerun:**
   ```
   ls (workspace_root)/artifacts/nord-iq10-audio-bringup-2026-07/   # manifest.json, timeline.md/json, evidence_refs.json, skill_outputs.json, blocker_report.md
   PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --replay nord-iq10-audio-bringup-2026-07   # prints trajectory, invokes NO skill
   PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --rerun  nord-iq10-audio-bringup-2026-07   # REPEATABLE (exit 0) right after a run
   ```
   Touch any tracked evidence or framework file and re-run `--rerun` → it prints
   `DRIFT DETECTED` naming the exact changed fingerprint and exits non-zero. Revert
   to restore `REPEATABLE`.

7. **Delete state to start clean** (only do this deliberately — it discards the persisted run):
   ```
   rm audio_bu_skill/state/nord-iq10-audio-bringup-2026-07.json
   rm logs/nord-iq10-audio-bringup-2026-07.jsonl
   ```

## What "BLOCKED" means here (expected, not a bug)

The run is *supposed* to land in `BLOCKED`. It reflects the real, current state of the Nord IQ-10
audio bring-up: DT scaffolding for the ADSP remoteproc + AudioReach stack has landed and builds
clean, but the `power-domains = <&rpmhpd RPMHPD_LCX/LMX>` wiring is flagged as a confirmed
root-cause **warning** (see `WARNING(sa8797p-audio)` comment in
`linux-nord/arch/arm64/boot/dts/qcom/nord-iq10.dtsi`) pending Power team confirmation of which fix
applies. The orchestrator's job is to halt correctly here with the reasoning on record — not to
guess a value nobody has confirmed yet.

## Re-running after the Power team answers

Once Power team confirms the fix, update `targets/nord-iq10/case.py` — supply the
confirmed value in the `triage_input.diagnosis` (clearing `needs_external_input`
so triage no longer reports `blocked_on_external_input`) and add a passing
`boot_outcome`/`audio_outcome` — and re-run; the generic walk will carry the run
from `BLOCKED` onward. `BLOCKED -> PATCH_APPLIED` is an approved transition in
`bringup_state.APPROVED_TRANSITIONS`, so the resumed walk picks up cleanly.
Alternatively, transition once by hand:
```python
orchestrator.transition_bringup(to_state="PATCH_APPLIED", reason="<power-team answer + citation>")
```
