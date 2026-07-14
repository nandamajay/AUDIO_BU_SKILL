# Phase 2 Foundation — Generation Lane Scaffolding (v1.1)

> **Status: foundation only. Generation is deferred and inert.** This document
> describes scaffolding that is in the tree today but is not reachable from the
> shipped CLI. No device tree, driver, machine driver, AudioReach topology, patch,
> or commit is generated. The default engine proposes an empty change set; the real
> engines raise `NotImplementedError`. Generation stays deferred until Eliza
> onboarding validates Phase 1 similarity + generated-case quality.

## 1. Why a foundation, and why inert

Phase 1 (target onboarding + nearest-target detection) removed the blank page for a
new target's `case.py` — read-only, human-gated, no code generation. Phase 2 is the
generation lane: proposing the kernel changes a new target needs (codec driver, DT
audio nodes, machine driver, AudioReach/SoundWire wiring) as reviewable diffs behind
a human gate.

Building the *foundation* now — the data models, the engine seam, the artifact
layout, the skill packages, the validators, the runner stubs, and the tests — means
that when Eliza validates onboarding quality, turning scaffolding into generation is
a small, well-scoped change (swap one engine, fill each runner's `task_spec` builder,
add a CLI mode) rather than a from-scratch build. Keeping it **inert** means none of
that risk lands early: the shipped `--target` / `--replay` / `--rerun` / `--onboard`
flows are byte-for-byte unchanged, and nothing can trigger generation by accident.

## 2. Two-lane model

```
GENERATION lane (Phase 2 — foundation only, inert today)
  target_onboarding                (Phase 1, shipped)
    -> codec_generation
    -> dt_scaffolding
    -> machine_driver_generation
    -> audioreach_generation
    -> patch_generation  --------->  PatchSeries  --[human gate #3]-->  approved
                                        |
VALIDATION lane (v1.0 — shipped)        v
  source_intake -> codec_driver_porting -> (apply approved series) -> triage
    -> bring-up walk: INIT..VERIFIED / TRIAGE / BLOCKED
```

The generation lane **proposes**; the validation lane **applies and verifies**. A
`ChangeSet` never mutates the kernel tree or `case.py` in place — proposed diffs are
written under `artifacts/<run_id>/generated/` and only applied after a human approves
the patch series.

## 3. Data models — `orchestrator/codegen/models.py`

Pure, deterministic dataclasses mirroring the `orchestrator/similarity/` style
(`to_dict()`, `from __future__ import annotations`, no dependencies).

- **`Change`** — one proposed change to one file: `path` (always kernel-tree-relative),
  `change_type` (`create` | `modify` | `delete`), `skill_id`, `unified_diff` (**empty
  in the foundation** — no engine emits a diff), `rationale`, `needs_review`.
- **`ChangeSet`** — everything one generation-skill invocation proposes: `skill_id`,
  `target`, `engine_id`, `changes`, `summary`. `is_empty()` is true in the foundation.
- **`PatchSeries`** — an ordered collection of `ChangeSet`s awaiting the patch-series
  human gate: `run_id`, `target`, `change_sets`, `approved` (flips **only** at gate #3;
  the foundation always leaves it `False`), `ordered_changes()`, `is_empty()`.
- **`generation_fingerprints(*, target_profile, task_spec, engine_id, model_id="")`** —
  the **generation** reproducibility contract, distinct from the v1.0 **validation**
  contract (`run_manifest.compute_fingerprints`, which hashes kernel_commit / evidence /
  case). Generation is reproducible over what conditioned it: the target profile, the
  task spec, and the engine/model identity. Deterministic (keys sorted before hashing).

## 4. Engine seam — `orchestrator/codegen/engine.py`

The pluggable abstraction the future lane plugs into — the whole point of the
foundation.

- **`CodegenEngine`** (ABC) — `engine_id`; abstract `generate(task_spec) -> ChangeSet`.
  Implementations never mutate on disk.
- **`NullEngine`** (`engine_id="null"`, **the default**) — `generate()` returns an
  **empty** `ChangeSet`. This is what keeps the whole lane inert.
- **`ClaudeCodeEngine`** / **`QGenieEngine`** — `generate()` raises
  `NotImplementedError("Phase 2 generation deferred until Eliza onboarding is validated")`.
- **`resolve_engine(name="null")`** — factory; **unknown names fall back to
  `NullEngine`** rather than raising, so a typo can never accidentally activate
  generation.

## 5. Generated-artifact layout — `orchestrator/codegen/artifacts.py`

`generated_dir(workspace_root, run_id)` = `artifacts/<run_id>/generated/` (same
path-traversal guard as the v1.0 `run_manifest.artifacts_dir`), parallel to the v1.0
validation artifacts and never overlapping them:

```
artifacts/<run_id>/generated/
  patch_series.json            <- the whole PatchSeries (ordered, approved flag)
  generation_manifest.json     <- run id, target, engine, per-skill summary
  change_sets/<skill_id>.json  <- one ChangeSet per generation skill
  <skill_id>/*.patch           <- reserved for Phase-2 proposed diffs (NONE today)
```

`write_patch_series(...)` writes the JSON records but **no `.patch` files** when a
change set is empty — the foundation case. A real engine would additionally emit each
`change.unified_diff` to `generated/<skill_id>/*.patch`.

## 6. Skill packages — `skills/<gen-skill>/`

Five standard 3-file packages (`skill.yaml` + `schema.json` + `validator.py`), so
`load_skill_registry` reports `valid`:

| skill | depends on | proposes |
|---|---|---|
| `codec_generation` | `target_onboarding` | codec driver (`sound/soc/codecs/`) |
| `dt_scaffolding` | `codec_generation` | SoC `.dtsi` audio nodes |
| `machine_driver_generation` | `dt_scaffolding` | ASoC machine driver (`sound/soc/qcom/`) |
| `audioreach_generation` | `machine_driver_generation` | AudioReach/SoundWire graph + topology |
| `patch_generation` | all four above | assembled `PatchSeries` for the human gate |

Each manifest carries all 17 required fields with foundation values: `version 0.1.0`,
`sdlc_phase implementation`, `status prototype`, `requires_human_review true`,
`evidence_required true`, `writes_knowledge true`, `confidence 0.5`. Mandatory inputs:
`workspace_context`, `target_name`, `run_id`, `target_profile`. Outputs: `change_set`,
`evidence`.

Each `validator.py` enforces schema + three `validation_rules`:
- **`must_emit_change_set`** — a `change_set` with an `engine_id` and a `changes` list.
- **`must_not_mutate_kernel_tree`** — every `change.path` is kernel-tree-relative (no
  absolute path, no `..`). The validator checks *shape only*; it never applies a diff.
- **`must_flag_generated_for_review`** — any non-empty change set must set
  `human_review_needed` (an empty foundation set passes trivially).

## 7. Runner stubs — `orchestrator/runners/<gen-skill>_runner.py`

Each `run_<skill>(input_envelope)` builds a `task_spec`, calls
`resolve_engine(...).generate(task_spec)` (default `NullEngine` → empty `ChangeSet`),
and returns `{"change_set": cs.to_dict(), "human_review_needed": not cs.is_empty(),
"evidence": {"evidence_refs": [...]}}`. With the default engine this is a valid
**no-op** that generates nothing and writes nothing.

**These runners are not registered in any CLI mode.** `main.do_run` registers only its
three v1.0 runners; there is no `--generate` mode. Nothing in the shipped tool reaches
a generation runner — the tests call them directly.

## 8. Four human gates

All four are the same `requires_human_review` primitive; none is auto-cleared:

1. **Similarity acceptance** — onboarding's nearest-target proposal (Phase 1).
2. **Generated-case promotion** — the manual `mv case.generated.py case.py` (Phase 1).
3. **Patch-series approval** — `PatchSeries.approved` flips only here (Phase 2).
4. **Final signoff** — the bring-up run's terminal verification (v1.0).

## 9. What is inert today (exhaustive)

- `NullEngine.generate()` returns an empty `ChangeSet`; it is the default everywhere.
- `ClaudeCodeEngine` / `QGenieEngine` raise `NotImplementedError`.
- Every `Change.unified_diff` is `""`; `write_patch_series` emits no `.patch` files.
- No generation runner is registered; there is no `--generate` CLI mode.
- No kernel-tree write, no `case.py` write, no compile, no commit.

## 10. The precise Phase-2 to-do (turning scaffolding into generation)

1. Implement `ClaudeCodeEngine.generate()` (and/or `QGenieEngine.generate()`) to emit
   real `Change`s with populated `unified_diff`.
2. Fill each runner's `task_spec` builder with the real conditioning inputs and select
   the engine via `resolve_engine(...)`.
3. Add a `--generate <target>` CLI mode in `main.py` that registers the five
   generation runners (alongside `do_run`'s three) and walks the generation lane,
   writing the `PatchSeries` via `write_patch_series`.
4. Add `generation_fingerprints` to the replay/rerun path so a generated series is
   drift-checkable alongside the validation fingerprints.
5. Add `compile_validation` + bounded repair loop and `commit_generation` (Phase 3).

## 11. Explicit non-goals for the foundation

No DTS / driver / machine-driver / AudioReach code generation, no `unified_diff`
content, no `.patch` emission, no kernel-tree mutation, no compile/repair loop, no
commit generation, no `--generate` CLI mode, no Phase-3 reproducibility wiring.
