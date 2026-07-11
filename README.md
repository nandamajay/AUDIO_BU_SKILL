# AUDIO_BU_SKILL

AUDIO_BU_SKILL is a generic, multi-target Audio Bring-up Skill framework for automating and validating audio platform enablement workflows.

The framework separates generic orchestration from target-specific engineering findings. Each target provides its own case definition, evidence roots, observed outcomes, blockers, and triage diagnosis, while the orchestrator remains reusable across platforms.

The framework supports evidence-driven source intake, codec driver readiness checks, device-tree scaffolding, triage, replayability, repeatability, drift detection, target inheritance, and audit-grade run artifacts.

---

## 1. Overview

Audio bring-up on a new SoC is a repetitive, evidence-heavy workflow: resolve where the
hardware evidence comes from, confirm the codec drivers exist in the kernel tree, scaffold
the device-tree, and triage whatever blocks the first clean boot. The *shape* of that
workflow is identical across platforms; only the facts change.

AUDIO_BU_SKILL encodes the shape once — as a generic, outcome-driven orchestrator — and
keeps the per-platform facts (SoC identity, evidence roots, codec part numbers, observed
outcomes, and analyst triage judgment) in a small, human-authored `case.py` per target. The
engine is target-agnostic; a new platform is a new case file, not a new tool.

Every run is recorded as an audit-grade, replayable, drift-checkable artifact set, so a
bring-up result can be reconstructed, re-verified, and reasoned about long after the run.

## 2. Key Capabilities

- Generic multi-target audio bring-up framework
- Target-specific case files
- Target inheritance support
- Kernel source path override/fallback
- IPCAT-first evidence model with offline fallback
- Evidence provenance tracking
- Codec driver readiness validation
- Device-tree scaffolding workflow
- Triage and blocker classification
- Replayable execution
- Repeatability and drift detection
- Audit-grade run artifacts
- Resume-safe/idempotent state handling
- Drift detection for kernel, evidence, case, skill manifests, schemas, validators, and framework inputs

## 3. Architecture

The framework is a clean split between a **generic engine** and **per-target content**,
with **skill packages** enforcing the contract at each phase.

**Inputs**
- **Target case** (`targets/<name>/case.py`) — the SoC's identity, evidence roots, codec
  part numbers/verdicts, per-gate reasons, optional triage diagnosis, and boot/audio outcomes.
- **Kernel source** — the kernel git checkout the codec/DT evidence is read from
  (`--kernel-source` override, else the case's `kernel_source_path`).
- **Evidence source** — the policy that selects which evidence roots are globbed
  (`ipcat`, `offline_documents`, `both`, `ipcat_first`).
- **IPCAT / offline evidence** — on-disk evidence roots the source-intake skill resolves.

**Generic orchestrator** (`orchestrator/`)
- **Bring-up state machine** (`bringup_state.py`) — the whole-run FSM
  (INIT → SCAFFOLD → PATCH_APPLIED → ON_TARGET → VERIFY → VERIFIED, plus TRIAGE / BLOCKED).
- **Skill invocation** (`driver.py`) — drives each skill through its per-invocation
  lifecycle (`skill_state_machine.py`), calling the registered runner and validating
  input/output against the skill's schema + rules.
- **State persistence** (`run_store.py`) — persists the run record to `state/<run_id>.json`.
- **Transition recording** (`logger_json.py`, `run_manifest.py`) — appends JSONL events and
  builds the fingerprinted run manifest + artifact set.
- **Generic walk** (`bringup_walk.py`) — the outcome-driven `run_bringup()` and the
  `BringupCase` model shared by every target.

**Skill packages** (`skills/<skill>/` = `skill.yaml` + `schema.json` + `validator.py`)
- **source_intake** — resolves and validates where evidence comes from.
- **codec_driver_porting** — confirms the codec drivers exist in the kernel tree before DT
  scaffolding is accepted.
- **dt_scaffolding** *(roadmap — see below)* — device-tree generation/patch authoring.
- **triage** — diagnoses a compile/DT blocker and classifies it (owner, category,
  expected unblock signal).
- **target_onboarding** *(v1.1 Phase 1)* — detects the nearest existing target and proposes a
  `case.generated.py` for a new target; read-only, human-gated (see §14).

**Outputs** (`artifacts/<run_id>/`)
- `manifest.json`, `state.json`, `evidence_refs.json`, `skill_outputs.json`,
  `timeline.md`, `timeline.json`, and `blocker_report.md` (when the run ended BLOCKED).

## 4. Bring-up State Flow

```
INIT
  -> SCAFFOLD
  -> PATCH_APPLIED
  -> ON_TARGET
  -> VERIFY
  -> VERIFIED
```

Any phase may route to:

```
  TRIAGE -> BLOCKED
```

A target with no compile/DT blocker and passing boot/audio outcomes runs all the way to the
terminal `VERIFIED`. A target that hits a blocker routes to `TRIAGE`; if the fix needs
external input, the run halts at `BLOCKED` with the reasoning on record.

## 5. Repository Structure

```
AUDIO_BU_SKILL/                      <- repository root (workspace root)
├── README.md
├── .gitignore
├── workspace.yaml                   <- workspace-level artifact manifest (runtime contract)
└── audio_bu_skill/
    ├── PLAYBOOK.md                  <- run / add-target / replay / verify playbook
    ├── orchestrator/                <- the generic engine
    │   ├── main.py                  <- thin CLI: --target | --replay | --rerun
    │   ├── bringup_walk.py          <- generic run_bringup() + BringupCase model
    │   ├── driver.py                <- BringupOrchestrator: runners + validation
    │   ├── run_manifest.py          <- fingerprints, manifest, artifacts writer
    │   ├── bringup_state.py         <- whole-run FSM
    │   ├── skill_state_machine.py   <- per-invocation FSM
    │   ├── run_store.py             <- persists run state
    │   ├── logger_json.py           <- JSONL event log
    │   ├── loader_skill_manifest.py <- reads/validates the skill registry
    │   ├── schema_validation.py     <- shared JSON-Schema helpers
    │   ├── workspace_loader.py      <- reads workspace.yaml
    │   ├── similarity/              <- (v1.1) nearest-target detection: features + weighted scoring
    │   └── runners/                 <- plain-function skill runners
    ├── skills/                      <- one dir per skill: skill.yaml + schema.json + validator.py
    │   ├── audio_bu_orchestrator/
    │   ├── source_intake/
    │   ├── codec_driver_porting/
    │   ├── target_onboarding/       <- (v1.1 Phase 1) nearest-target + proposed case.generated.py
    │   └── triage/
    ├── targets/                     <- one dir per bring-up target (per-target content)
    │   └── nord-iq10/
    │       ├── case.py              <- this SoC's facts + analyst judgment
    │       └── evidence/
    │           ├── ipcat/           <- (gitignored) IPCAT evidence cache
    │           └── offline/         <- (gitignored) hand-dropped offline evidence
    └── tests/                       <- framework tests
```

Runtime-generated directories (`state/`, `logs/`, `artifacts/`) and confidential evidence
collateral are gitignored — see the Confidentiality Notice below.

## 6. Running a Target

```
cd /local/mnt/workspace/NORD_BU

PYTHONPATH=audio_bu_skill python3 -m orchestrator.main \
  --target nord-iq10 \
  --evidence-source ipcat_first
```

Optional kernel-source override (first present wins: `--kernel-source`, then the case's
`kernel_source_path`; the resolved path must be a git checkout with `arch/`, `drivers/`,
`sound/`, `Documentation/`):

```
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main \
  --target nord-iq10 \
  --evidence-source ipcat_first \
  --kernel-source linux-nord
```

- **First run** ("fresh"): walks the trajectory invoking each skill and settles at a state.
- **Every run after** ("resume"): idempotent — resumes and settles at the same state without
  re-invoking skills or double-writing state/logs.

## 7. Evidence Source Modes

- `ipcat` — glob the IPCAT evidence root only.
- `offline_documents` — glob the offline evidence root only.
- `both` — glob both roots.
- `ipcat_first` — glob IPCAT first; if it is missing or empty, fall back to offline and
  record the fallback (not a failure).

## 8. IPCAT-first Evidence Model

The IPCAT MCP tools live in the interactive agent runtime, authenticated by the session's
OAuth — a `python -m orchestrator.main` subprocess cannot reach them. IPCAT-first is
therefore an **agent-mediated cache**:

1. The agent runs the IPCAT MCP search and materializes the results into the target's
   `evidence/ipcat/` folder.
2. Alongside them it writes `evidence/ipcat/provenance.json`
   (`{source, query, doc_ids, fetched_at, files:[{name, sha256}]}`).
3. The CLI is run with `--evidence-source ipcat_first`. The runner globs the `ipcat` root
   first and reads `provenance.json` into the run's provenance. **If the `ipcat` root is
   missing or empty**, it falls back to `offline_documents`, recording `fell_back=true` and a
   `fallback_reason`.

Because the evidence is on-disk and hashable, replay and drift detection are trivial. See
`audio_bu_skill/PLAYBOOK.md` for the full MCP refresh procedure.

## 9. Replay

Reconstruct a prior run's trajectory and blocker summary from its recorded artifacts —
**without invoking any skill or touching state**:

```
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main \
  --replay <run_id>
```

## 10. Repeatability / Drift Detection

Compare today's inputs against a recorded run's fingerprints:

```
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main \
  --rerun <run_id>
```

`--rerun` recomputes and diffs fingerprints for the kernel commit, each evidence file, the
target `case.py`, each skill version, and the framework inputs (`workspace.yaml` and every
`skill.yaml` / `schema.json` / `validator.py`):

- **REPEATABLE** (exit 0) — every input hash matches the recorded run.
- **DRIFT DETECTED** (exit non-zero) — lists each changed fingerprint `key: old -> new`
  (CI-usable).

## 11. Run Artifacts

Every `--target` run writes an audit-grade set (idempotent — refreshed on resume):

```
artifacts/<run_id>/
  manifest.json          <- identity, inputs, transitions, fingerprints, analytics
  state.json             <- persisted FSM record
  evidence_refs.json     <- resolved evidence paths + sha256 + provenance
  skill_outputs.json     <- each skill's validated output
  timeline.md            <- human-readable transitions
  timeline.json          <- structured transitions (dashboard/automation)
  blocker_report.md      <- only when the run ended BLOCKED
```

## 12. Adding a New Target

Currently a new target requires:

- `targets/<name>/case.py`
- `targets/<name>/evidence/ipcat/`
- `targets/<name>/evidence/offline/`
- target-specific evidence files
- target metadata, codec inputs, power model details, and optional triage / boot / audio outcomes

Copy `targets/nord-iq10/case.py` as a template. The `run_id` must be unique per target and
must encode the SoC or target name so `state/<run_id>.json` cannot collide between targets.
See `audio_bu_skill/PLAYBOOK.md` for the step-by-step guide.

## 13. Target Inheritance

A target whose behavior is mostly the same as another's can inherit it instead of
copy-pasting. Set `inherit_from="<parent-target-name>"` in the child's `CASE`; at load time
the parent is resolved first and the child is deep-merged over it (a new `BringupCase` —
parent files are never mutated):

- **dict fields** (`codec_verdicts`, `evidence_roots`, `triage_input`, …) merge key-wise: the
  child overrides only the keys it names and inherits the rest.
- **scalars / lists**: the child wins only when it sets a meaningful (non-empty, non-default)
  value; otherwise it inherits the parent's.
- self-inheritance and cycles are rejected; `inherit_from` is cleared on the resolved case.

The resolved case is what validation checks and what the run uses.

## 14. Target Onboarding (v1.1 Phase 1)

Hand-authoring `targets/<name>/case.py` — nearest_target, run_id, codec list,
evidence_roots, kernel_source_path — is the most painful, error-prone step of
adding a target. **Target onboarding removes the blank page.** Given a target
name, a kernel tree, and evidence folders, the framework auto-detects the nearest
existing target, extracts a feature profile with cited evidence, and writes a
*proposed* `case.generated.py` for a human to review and promote.

```
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main \
  --onboard <new-target> \
  --kernel-source linux-nord
```

`--onboard` is a fourth, standalone CLI mode alongside `--target`/`--replay`/`--rerun`.
It is **read-only** and **additive**: it never enters the bring-up walk, never drives
a `BringupState` transition past INIT, never generates kernel code, never compiles, and
**never writes `case.py`**.

**What it does:**
1. **Extracts a feature profile** of the new target from the kernel tree + evidence:
   codecs (grepped from evidence filenames + confirmed against `sound/soc/codecs/`),
   audio DT `compatible` strings, power-domain providers (`rpmhpd` vs. `scmiN_pd` — the
   Nord blocker axis), AudioReach / SoundWire signatures, and SoC identity. Each signal
   records the file(s) it came from, for evidence citation.
2. **Ranks the nearest existing targets** by weighted per-signal similarity
   (codecs 0.30, power-domains 0.20, DT 0.20, AudioReach 0.15, SoundWire 0.10, SoC 0.05),
   with a confidence score and margin. Below `MIN_SCORE`/`MIN_MARGIN` the match is flagged
   **low-confidence** and `nearest_target`/`inherit_from` are *not* auto-finalized.
3. **Proposes a `case.generated.py`** deriving `run_id`, `target_soc`, `nearest_target`,
   `inherit_from`, `evidence_roots`, `kernel_source_path`, `codec_part_numbers`/`verdicts`,
   and `evidence_source=ipcat_first`. Every uncertain field is marked `# NEEDS_REVIEW`.

**Outputs** (written to `targets/<new-target>/`):
`case.generated.py`, `onboarding_report.md`, `similarity_report.json`,
`evidence_inventory.json`, `profile.json`.

**Human review gate.** The onboarding skill sets `requires_human_review: true`, so the
skill invocation stops at SUCCESS (proposed, not approved). Promotion is a deliberate,
manual rename by the engineer:

```
# review the report + generated case, then:
mv targets/<new-target>/case.generated.py targets/<new-target>/case.py
# then run the normal v1.0 flow:
PYTHONPATH=audio_bu_skill python3 -m orchestrator.main --target <new-target>
```

**What stays manual (by design):** promoting `case.generated.py` → `case.py`; confirming
the **power model** (rpmhpd vs. SCMI is never auto-finalized); and finalizing the codec
list/verdicts (a detected driver is proposed `upstream_present`; port/write judgments are
the engineer's).

**One expected side-effect:** adding the `target_onboarding` skill grows the skill
registry, which `--rerun` fingerprints. A Nord manifest recorded *before* this framework
gained the skill will show `DRIFT DETECTED` on the new skill's files until a normal
`--target nord-iq10` run refreshes the manifest — correct drift-detection behavior, not a
regression.

**Deferred to Phase 2/3 (NOT implemented):** device-tree scaffolding, codec / machine-driver
/ AudioReach code generation, patch generation, compile validation + repair loop, commit
generation, and any pluggable code-generation engine. Onboarding proposes *metadata* only;
it authors no kernel code.

## 16. Roadmap

Target onboarding + nearest-target detection (**v1.1 Phase 1**) is implemented — see §14.
It removes the most painful manual work (authoring `nearest_target` and the initial
`case.py`) while staying low-risk: read-only, additive, human-gated, no code generation.

**v1.1 Phase 1 — done:**
- ✅ Target onboarding skill (`target_onboarding`)
- ✅ Nearest-target detection via a weighted similarity engine over existing targets
- ✅ Auto-propose `case.generated.py` (nearest_target, run_id, codec list, evidence_roots,
  kernel_source_path) with uncertain fields flagged `NEEDS_REVIEW`
- ✅ Human review gate + manual promotion to `case.py`

**Phase 2/3 — planned (not started):**
- Device-tree scaffolding / codec / machine-driver / AudioReach code generation
- Patch generation (proposed diffs behind a human gate)
- Compile validation + bounded repair loop
- Commit generation + generation-side reproducibility
- Pluggable code-generation engine
- Fleet-level analytics dashboard
- More audio validation skills:
  - SoundWire enablement
  - AudioReach validation
  - DSP image validation
  - Speaker protection validation
  - SSR validation

## 17. Confidentiality Notice

Do not commit IPCAT exports, schematics, board collateral, generated run artifacts, state
files, logs, kernel trees, or internal documents. These are excluded via `.gitignore` and
must remain local to your workspace. The framework code is the shareable product; running a
real target requires the confidential collateral, which stays out of version control.
