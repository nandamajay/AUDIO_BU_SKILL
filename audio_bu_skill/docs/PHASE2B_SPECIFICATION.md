# Phase-2B Specification — Verified Artifact Generation Engine

**Type:** Planning only. **No code, no implementation, no commits. No Phase-2A modifications. No live IPCAT access from this document.**
**Consumes:** Phase-2A output — trusted, verified `cross_verification` rows and the snapshot provenance that produced them.
**Emits:** Generated design artifacts (DTS scaffolding, codec stubs, machine driver, AudioReach XML) — **each one gated by pre-generation and post-generation cross-verification against the same Phase-2A rows**.
**Discipline:** Mirrors Phase-2A V2. Diagnostic-first, additive-only rendering, no fabricated values, "unknown recorded as unknown," pure Comparison Core, fail-closed on any warning or REVIEW_REQUIRED.
**Style anchor:** `docs/PHASE2A_SPECIFICATION_V2.md` (section numbering, invariants posture, per-track shape).
**Build-order anchor:** `docs/PHASE2A_IMPLEMENTATION_PLAN.md` (WP layout, commit boundaries, gate-green discipline).

---

## 0. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-07-15 | Initial draft. Establishes scope, four-stage engine architecture (Collector → Comparison Core → Generator → Post-Gen Verifier), WP breakdown WP1–WP9, verification gates per generator, human-in-the-loop contract, non-goals, open questions. |

---

## 1. Scope, invariants, non-goals

### 1.1 Scope (§1 mirror of Phase-2A §0)

Phase-2B produces the **first draft** of the four design artifacts a Nord/Eliza-class audio bring-up requires, **only after** the schematic↔IPCAT view has been cross-verified by Phase-2A on the input side, and **only if** the generated artifact re-verifies clean on the output side against the same Phase-2A rows.

Generated artifact classes:
1. **DT scaffolding** — pinctrl, gcc/aoss/tlmm nodes, GPR/AudioReach nodes, power-domain skeleton.
2. **Codec driver stub / upstream check** — presence check against Linux mainline; when missing, produce a stub with `compatible` / register-map skeleton.
3. **Machine driver** (ASoC card + DAI links) — C source producing an ASoC card matching the DT declarations.
4. **AudioReach topology** — XML/DTS binding describing the LPASS/GPR graph.

### 1.2 Invariants (VERBATIM from Phase-2A discipline)

- **Pure Comparison Core.** Every generator is a pure function `(trusted_facts, kb) → artifact_bytes | generator_skipped_row`. Zero I/O. Zero network. Zero filesystem writes from the Core. Byte-deterministic replay.
- **Diagnostic-first, gating-second.** No autonomous commit; no autonomous patch send; no autonomous build; no autonomous flash. The engine renders artifacts and a verification report; a human decides.
- **No fabricated values.** Every field in every generated artifact traces to a Phase-2A `VerificationRow` with a non-`UNAVAILABLE` authority, or to a KB rule with a `rule_id`. A field with no traceable authority is either omitted (with a `generator-skipped` verification row) or emitted as an explicit `FIXME(<subject>)` marker — never guessed.
- **Fail-closed on warning / REVIEW_REQUIRED.** If any of the Phase-2A rows the generator depends on has `warning=true` OR verdict `REVIEW_REQUIRED` OR verdict `DISAGREE_WITH_AUTHORITY`, that generator emits a `generator-skipped` row and produces no artifact for that subject. A wrong artifact costs more than a missing artifact (Phase-2A §C.9 asymmetry, inherited).
- **Additive-only renderer.** The Phase-2B renderer appends a `## Generated Artifacts` section after Phase-2A's `## Schematic ↔ IPCAT Cross-Verification` section. When there are no generated artifacts on this run, the renderer returns `[]` and the report is byte-identical to the Phase-2A-only baseline. Same null-guard test discipline (`test_no_artifacts_key_returns_empty`, etc.).
- **No Phase-2A modification.** Phase-2A's `orchestrator/reasoning/crossverify.py`, `crossverify_model.py`, `crossverify_config.py`, `runners/crossverify_collector.py`, `main._render_crossverify_section` are frozen. Phase-2B imports them; it does not touch them. WP-C lane (`cardinality.py`, `cardinality_config.py`, pinned at `28f2f07`) remains untouched — inherited invariant.
- **Read-only IPCAT.** Phase-2B introduces no new IPCAT tool calls. All silicon authority Phase-2B consumes is already present in the Phase-2A snapshot; if a generator needs a fact Phase-2A did not surface, the Generator emits a `generator-skipped` row with reason `authority_not_in_snapshot`. No live probe at generation time.
- **TLS `verify=True`, env-var-first credentials, no `.credentials.json` read.** Inherited from Phase-1/Phase-2A envelope. Phase-2B introduces no new I/O path that could weaken this.
- **Human-in-the-loop by construction.** Every generated artifact requires **explicit human acknowledgment** before it is written to a tracked path or committed. The Generator writes only to `generated/<run_id>/…` (untracked) unless the human ack lever is set (see §5).

### 1.3 Non-goals for Phase-2B (see §6 for the full list)

- **No Kconfig modification.** Phase-2B does not edit `arch/arm64/configs/*_defconfig` or `sound/soc/qcom/Kconfig`.
- **No build.** Phase-2B does not invoke `make`, `bazel`, or any kernel/module compile.
- **No hardware access.** No flashing, no boot, no runtime probe.
- **No upstream submission.** Phase-2B does not `git send-email`, does not open a MR/PR, does not post to lkml.
- **No autonomous git commit.** The engine writes artifacts to an untracked staging directory. Committing is a human step, following review of the Phase-2A cross-verification of the *generated* artifacts.

---

## 2. Engine architecture

Phase-2B extends Phase-2A's three-stage pipeline into four stages. **Stages 1–3 are Phase-2A, imported unchanged.** Only Stage 4 is new.

```
┌─────────────┐     ┌────────────────┐     ┌──────────┐     ┌──────────────┐
│  Collector  │ ──► │ Comparison     │ ──► │ Renderer │     │  Generator   │
│  (impure)   │     │ Core (pure)    │     │ (pure)   │ ─┬─►│  (pure)      │
│  Phase-2A   │     │ Phase-2A       │     │ Phase-2A │  │  │  Phase-2B    │
└─────────────┘     └────────────────┘     └──────────┘  │  └──────┬───────┘
                                                         │         │
                                        Phase-2A rows ───┘         ▼
                                        (trusted facts +      Generated
                                         gating verdicts)     artifacts
                                                                    │
                                                                    ▼
                                                          ┌──────────────────┐
                                                          │ Post-Gen Verify  │
                                                          │  (Phase-2A over  │
                                                          │  generated view) │
                                                          └────────┬─────────┘
                                                                   ▼
                                                          Human review
```

### 2.1 Stage 1 — Collector (Phase-2A, unchanged)

Impure. Reads the live IPCAT snapshot (chip, GPIO map, SWI, cores, QUPs). Written by Phase-2A WP2. **Phase-2B imports it. Phase-2B does not modify it.**

### 2.2 Stage 2 — Comparison Core (Phase-2A, unchanged)

Pure. Emits the six-track cross-verification (`T1..T5` including `T4a` / `T4b`) as a list of `VerificationRow`. Written by Phase-2A WP3–WP7. **Phase-2B imports it. Phase-2B does not modify it.**

### 2.3 Stage 3 — Renderer (Phase-2A, unchanged additive-only)

Pure. Emits the `## Schematic ↔ IPCAT Cross-Verification` section. Written by Phase-2A WP8. **Phase-2B does not modify it.** Phase-2B adds a *sibling* renderer for its own `## Generated Artifacts` section (WP9 of Phase-2B), preserving the additive-only invariant.

### 2.4 Stage 4 — Generator (NEW, pure)

Pure function signature (one per artifact class):

```python
def generate_<artifact>(
    trusted_facts: TrustedFacts,   # projection of Phase-2A rows
    kb: KnowledgeBase | None,
) -> GenerationResult:
    ...
```

Where:

- **`TrustedFacts`** is an immutable projection built by the Phase-2B *fact projector* (WP2) from the Phase-2A `cross_verification.rows`. It exposes only the subset of rows a given generator depends on — a generator that consumes a fact never surfaced in Phase-2A gets `UNAVAILABLE` and produces a `generator-skipped` row.
- **`GenerationResult`** is a discriminated union:
  - `GeneratedArtifact { subject, path_hint, bytes, contributes_rows: list[VerificationRow] }` — a generated artifact plus the *new* schematic-view rows it introduces (e.g. a generated DT node introduces new claims that the post-gen verifier must cross-check against the same IPCAT authority).
  - `GeneratorSkipped { subject, reason, gating_rows: list[str] }` — an explicit non-emission, with the Phase-2A row IDs that gated the generator closed.

### 2.5 Pre-generation gate

Before calling `generate_<artifact>`, the runner evaluates the artifact's gating expression (see §4). If **any** gating row is `REVIEW_REQUIRED`, `DISAGREE_WITH_AUTHORITY`, or has `warning=true`, the generator is **not called**; a `GeneratorSkipped` row is emitted instead. This is the WP-C asymmetry made explicit: the engine's default is *not* to produce.

### 2.6 Post-generation verification

Every non-skipped `GeneratedArtifact` produces `contributes_rows` — schematic-view claims derived from the generated artifact. Phase-2B **feeds these rows back through Phase-2A's Comparison Core** (against the same IPCAT snapshot from the collector) and appends the resulting `VerificationRow`s to a `post_gen` bucket. If any post-gen row is not `MATCH` / `PARTIAL_MATCH`, the artifact is marked `NEEDS_REVIEW` in the report. **Post-gen verification is Phase-2A, invoked as a library. No new comparison logic is written.**

### 2.7 Byte-deterministic replay

Same `(trusted_facts, kb)` → byte-identical artifact bytes and byte-identical `contributes_rows`. Same rendering rules as Phase-2A: rows sorted by `(track, subject)`, artifacts sorted by `(artifact_class, subject)`.

---

## 3. Work-package breakdown

Each WP has: **Purpose**, **Files to create**, **Files to modify** (Phase-2A files are never listed here), **Dependencies**, **Acceptance criteria**, **Commit boundary**.

Package layout (proposed additions only; Phase-2A layout untouched):

```
audio_bu_skill/
├── orchestrator/
│   └── generation/                          ← NEW top-level package (Phase-2B)
│       ├── __init__.py
│       ├── config.py                        (WP1)
│       ├── model.py                         (WP1)
│       ├── facts.py                         (WP2)
│       ├── dt_scaffolding.py                (WP3)
│       ├── codec_stub.py                    (WP4)
│       ├── machine_driver.py                (WP5)
│       ├── audioreach_topology.py           (WP6)
│       ├── post_gen.py                      (WP7)
│       └── render.py                        (WP8, sibling of Phase-2A render)
├── tests/
│   ├── test_generation_model.py             (WP1)
│   ├── test_generation_facts.py             (WP2)
│   ├── test_generation_dt.py                (WP3)
│   ├── test_generation_codec.py             (WP4)
│   ├── test_generation_machine.py           (WP5)
│   ├── test_generation_audioreach.py        (WP6)
│   ├── test_generation_post_gen.py          (WP7)
│   ├── test_generation_render.py            (WP8)
│   └── fixtures/phase2b/                    (frozen Phase-2A rows + expected artifacts)
└── docs/
    ├── PHASE2B_SPECIFICATION.md             ← THIS DOC
    └── PHASE2B_IMPLEMENTATION_PLAN.md       (drafted later)
```

The Phase-2A public surface (`orchestrator.reasoning.crossverify`, `crossverify_model`, `crossverify_config`, `runners.crossverify_collector`, `main._render_crossverify_section`, `main._CROSSVERIFY_TRACK_ORDER`) is imported by Phase-2B. **No file under `orchestrator/reasoning/` or `runners/crossverify_collector.py` is listed under "Files to modify" in any WP below.**

### WP1 — Foundations: config, model, gating vocabulary

**Purpose.** Establish the Phase-2B constants (artifact classes, gating expressions, sort orders), the `GenerationResult` discriminated union, and the `TrustedFacts` projection type. This is the Phase-2B analogue of Phase-2A WP1.

**Files to create.**
- `orchestrator/generation/config.py` — `_GENERATION_ARTIFACT_ORDER = ("dt_scaffolding", "codec_stub", "machine_driver", "audioreach_topology")`; per-artifact `GATING_ROWS` dict (see §4); `SKIP_REASONS` enum (`gating_row_warning`, `gating_row_review_required`, `gating_row_disagree`, `authority_not_in_snapshot`, `kb_rule_missing`).
- `orchestrator/generation/model.py` — `GeneratedArtifact`, `GeneratorSkipped`, `GenerationResult` (union), `TrustedFacts` (immutable projection). Every dataclass has `.to_dict()` returning JSON-serializable output, mirroring `VerificationRow.to_dict()`.
- `tests/test_generation_model.py` — dataclass invariants, JSON round-trip, sort-key determinism.

**Files to modify.** None.
**Dependencies.** None (imports from Phase-2A `crossverify_model` for type parity).
**Acceptance criteria.**
- `python3 -m tests.test_generation_model` → all green.
- No import cycles: `generation/*` may import from `reasoning/*`; the reverse is forbidden (a lint or import-guard test enforces this).

**Commit boundary.** `feat(2b): WP1 generation model + config`

### WP2 — Fact projector: Phase-2A rows → TrustedFacts

**Purpose.** Build `TrustedFacts` from a Phase-2A `cross_verification.rows` list. Pure function. This is the *only* place that reads Phase-2A rows and knows the mapping `(track, subject) → fact_field`.

**Files to create.**
- `orchestrator/generation/facts.py` — `project_facts(rows: list[VerificationRow]) -> TrustedFacts`. Handles `UNAVAILABLE` authority by leaving the corresponding fact field `None`. Never guesses.
- `tests/test_generation_facts.py` — (a) empty rows → empty facts; (b) Phase-2A fixture `expected_rows.json` (6 rows) → deterministic `TrustedFacts`; (c) rows with `warning=true` still project but are marked gating-closed in the fact metadata (the fact itself is `None` on the projection so no downstream generator can use it silently); (d) unknown `(track, subject)` combinations do not raise — they are ignored with a `notes` entry.

**Files to modify.** None.
**Dependencies.** WP1.
**Acceptance criteria.** `TrustedFacts` from the Phase-2A frozen fixture is byte-deterministic across runs. Every field carries a back-reference to the Phase-2A row that populated it (for citation).

**Commit boundary.** `feat(2b): WP2 fact projector (Phase-2A rows → TrustedFacts)`

### WP3 — DT scaffolding generator

**Purpose.** Given `TrustedFacts` with pinctrl / clock / power-domain claims backed by T1/T5 rows, emit a DTS fragment.

**Gating rows.** All of: `T1.gpio.i2s.*` MATCH; `T5.dts.firmware` MATCH or PARTIAL_MATCH; `T5.dts.compatible` MATCH.
**Fallback markers.** For any pin without a `T1.gpio.i2s.<pin>` MATCH row, the generator emits `FIXME(<pin>)` and a `generator-skipped` sub-row for that pin (partial artifacts are allowed at pin granularity, not at file granularity).

**Files to create.** `orchestrator/generation/dt_scaffolding.py`, `tests/test_generation_dt.py`, `tests/fixtures/phase2b/nord_dt_expected.dtsi`.
**Files to modify.** None.
**Dependencies.** WP1, WP2.
**Acceptance criteria.**
- Nord `TrustedFacts` (from Phase-1C evidence) → Nord DTSI byte-identical to `nord_dt_expected.dtsi`.
- Eliza `TrustedFacts` where `T5.dts.firmware=PARTIAL_MATCH` (donor `sa8775p` residue) → `GeneratorSkipped(reason=gating_row_partial_match_donor_residue)` — the donor bug does *not* get baked into a generated DTS.
- No `TrustedFacts` field marked `UNAVAILABLE` appears verbatim in generated bytes.

**Commit boundary.** `feat(2b): WP3 DT scaffolding generator (gated by T1+T5)`

### WP4 — Codec driver stub / upstream presence check

**Purpose.** For each codec surfaced in T4b, check the KB for an upstream Linux mainline driver reference (`compatible` string). If present, emit an `UpstreamReference` (no code, just a citation). If absent, emit a stub C file with `compatible`, register-map skeleton, and `TODO(reviewer)` markers.

**Gating rows.** `T4a.<codec_endpoint>` MATCH (the codec's SoC-side endpoint is confirmed) AND `T4b.<codec>` MATCH or REVIEW_REQUIRED (T4b REVIEW_REQUIRED is permitted here because T4b's authority is "OOS by design" — the reviewer signs off the binding manually).
**Skip rule.** `T4b.<codec>` DISAGREE → `GeneratorSkipped(reason=codec_binding_disagreement)`.

**Files to create.** `orchestrator/generation/codec_stub.py`, `tests/test_generation_codec.py`, `tests/fixtures/phase2b/wsa883x_stub_expected.c`.
**Files to modify.** None.
**Dependencies.** WP1, WP2.
**Acceptance criteria.**
- Codec present upstream (KB match) → `UpstreamReference{compatible, kernel_source_path}` with **no C code emitted**.
- Codec absent upstream → stub with matching `compatible` and no fabricated register values (all registers are `TODO(reviewer)` unless a KB rule provides them).

**Commit boundary.** `feat(2b): WP4 codec stub / upstream reference (gated by T4a+T4b)`

### WP5 — Machine driver (ASoC card + DAI links)

**Purpose.** Emit a `sound/soc/qcom/<board>.c` machine driver skeleton: card struct, DAI links matching the DT-declared endpoints, snd_soc_ops probing.

**Gating rows.** All of: `T1.gpio.i2s.*` MATCH (pins wired); `T4a.qup.*` MATCH (SoC endpoints valid); `T4b.<codec>.*` MATCH or REVIEW_REQUIRED (codec side known-or-reviewed); `T2.*` — if `T2` has any DISAGREE, skip.
**Fallback markers.** DAI links whose codec side is REVIEW_REQUIRED emit an `#error "reviewer must confirm <codec>"` sentinel — the file compiles only after the reviewer removes the sentinel.

**Files to create.** `orchestrator/generation/machine_driver.py`, `tests/test_generation_machine.py`, `tests/fixtures/phase2b/nord_machine_expected.c`.
**Files to modify.** None.
**Dependencies.** WP1, WP2, WP3 (imports DT-fragment structural info via the pure `TrustedFacts` projection — never by reading the WP3 output file).
**Acceptance criteria.**
- Nord (I²S-only, no SoundWire) → machine driver with I²S DAI links only; no `sdw_*` calls anywhere in the emitted C.
- A `TrustedFacts` with `T2` DISAGREE → `GeneratorSkipped(reason=gating_row_disagree_on_bus)`.

**Commit boundary.** `feat(2b): WP5 machine driver (gated by T1+T2+T4a+T4b)`

### WP6 — AudioReach topology generator

**Purpose.** Emit an AudioReach graph description (XML or DTS binding, KB decides) describing the LPASS/GPR node graph derived from `T3.lpass_macro_instance` + `T3.dsp_subsystem_instance` counts.

**Gating rows.** `T3.lpass_macro_instance` MATCH AND `T3.dsp_subsystem_instance` MATCH.
**Skip rule.** Any `T3.*` NOT_CROSS_CHECKABLE or DISAGREE_WITH_AUTHORITY on either class → `GeneratorSkipped`.

**Files to create.** `orchestrator/generation/audioreach_topology.py`, `tests/test_generation_audioreach.py`, `tests/fixtures/phase2b/nord_audioreach_expected.xml`.
**Files to modify.** None.
**Dependencies.** WP1, WP2.
**Acceptance criteria.**
- Nord (LPASS=0, DSP=1) → minimal audioreach node with a single DSP subsystem, zero macro instances, byte-identical to the fixture.
- Eliza (LPASS=4 catalog vs 2 proposal → DISAGREE_WITH_AUTHORITY) → `GeneratorSkipped(reason=gating_row_disagree_on_lpass_count)`.

**Commit boundary.** `feat(2b): WP6 audioreach topology generator (gated by T3)`

### WP7 — Post-generation verifier

**Purpose.** Feed each `GeneratedArtifact.contributes_rows` back through Phase-2A's Comparison Core against the *same* IPCAT snapshot, and attach the resulting rows to a `post_gen_verification` bucket on each artifact.

**Files to create.** `orchestrator/generation/post_gen.py`, `tests/test_generation_post_gen.py`.
**Files to modify.** None.
**Dependencies.** WP1, WP2, WP3–WP6. Imports `orchestrator.reasoning.crossverify` unchanged.
**Acceptance criteria.**
- Given a Nord `TrustedFacts` and the WP3 generator's `contributes_rows`, the post-gen verifier returns a list of `VerificationRow` with all-MATCH verdicts (the generated DT restates what T1/T5 already confirmed).
- Given a `GeneratedArtifact` whose `contributes_rows` intentionally introduce a mismatch (test fixture), the post-gen verifier returns a DISAGREE row — proving the loop is closed.

**Commit boundary.** `feat(2b): WP7 post-generation verification (Phase-2A as library)`

### WP8 — Renderer: `## Generated Artifacts` section

**Purpose.** Additive sibling to Phase-2A's `_render_crossverify_section`. Emits `## Generated Artifacts` with per-artifact status (`GENERATED`, `SKIPPED`, `NEEDS_REVIEW` post-gen), post-gen row summary, and the reviewer worklist for generated artifacts.

**Files to create.** `orchestrator/generation/render.py`, `tests/test_generation_render.py`, `tests/fixtures/phase2b/expected_generation_section.txt`.
**Files to modify.** `orchestrator/main.py` — add exactly one call site to append the generation section after the cross-verification section. **Restricted diff:** the modification must be a single new function call and its null-guarded returns; no existing lines of `main.py` may change semantics (the diff must pass a `git diff -U0 orchestrator/main.py | grep -v '^+' | grep -v '^---' | grep -v '^@@'` = empty subtraction check equivalent).
**Dependencies.** WP1–WP7.
**Acceptance criteria.**
- Report byte-identical to the Phase-2A-only baseline when no artifacts were generated (equivalent to Phase-2A test `test_report_byte_identical_without_cross_verification`).
- Fixture-based end-to-end test: Phase-2A frozen rows + WP2–WP6 outputs → `expected_generation_section.txt` exact match.

**Commit boundary.** `feat(2b): WP8 generation section renderer (additive-only)`

### WP9 — Runner: end-to-end assembly

**Purpose.** Wire Collector → Comparison Core → Generator → Post-Gen Verifier → Renderer into one orchestrator entry point. Emit artifacts to `generated/<run_id>/…` (untracked). Emit the report as usual.

**Files to create.** `orchestrator/generation/runner.py`.
**Files to modify.** `orchestrator/main.py` — add a CLI flag `--generate` that, when set, runs the Phase-2B pipeline after Phase-2A. Default OFF (the engine is diagnostic-only unless the human turns generation on).
**Dependencies.** WP1–WP8.
**Acceptance criteria.**
- Running `python3 -m orchestrator.main --target nord` without `--generate` produces the Phase-2A-identical report (regression anchor).
- Running with `--generate` produces the artifacts under `generated/<run_id>/`, the Phase-2B section in the report, and touches nothing under `arch/`, `sound/`, or any tracked kernel path.

**Commit boundary.** `feat(2b): WP9 runner + CLI --generate flag (default OFF)`

### Commit boundary summary

| # | Scope | Green gate |
|---|---|---|
| 1 | WP1 model + config | `test_generation_model` |
| 2 | WP2 fact projector | `test_generation_facts` + regression: Phase-2A tests still green |
| 3 | WP3 DT generator | `test_generation_dt` |
| 4 | WP4 codec generator | `test_generation_codec` |
| 5 | WP5 machine driver | `test_generation_machine` |
| 6 | WP6 audioreach | `test_generation_audioreach` |
| 7 | WP7 post-gen verifier | `test_generation_post_gen` |
| 8 | WP8 renderer | `test_generation_render` + Phase-2A byte-identical regression |
| 9 | WP9 runner | end-to-end smoke: `--generate` off → byte-identical to Phase-2A |

No WP under Phase-2B touches Phase-2A source. This is a design invariant, not a coincidence.

---

## 4. Verification gates

Each generator declares a **gating expression** — a Boolean over Phase-2A rows. The runner evaluates the expression *before* calling the generator. **If any dependency is closed (warning, REVIEW_REQUIRED, DISAGREE_WITH_AUTHORITY), the generator is not called** and the run emits a `generator-skipped` row instead.

Rows evaluate as follows:

| Row state | Gating value |
|---|---|
| `MATCH` | OPEN |
| `PARTIAL_MATCH` (KB rule downgrade) | OPEN, but the artifact carries the `rule_id` citation |
| `NOT_CROSS_CHECKABLE` with `coverage_gap_reason=authority_out_of_scope` | OPEN only for artifacts declaring the row as "advisory" (T4b is the only such row in scope; see WP4) — otherwise CLOSED |
| `NOT_CROSS_CHECKABLE` (any other reason) | CLOSED |
| `REVIEW_REQUIRED` | CLOSED |
| `DISAGREE_WITH_AUTHORITY` | CLOSED |
| any row with `warning=true` | CLOSED |

### 4.1 Gating table (generator × gating rows)

| Generator | Required rows (all must be OPEN) | Skip verdict when closed |
|---|---|---|
| WP3 DT scaffolding | `T1.gpio.i2s.<pin>` (per-pin), `T5.dts.firmware`, `T5.dts.compatible` | `gating_row_warning` / `gating_row_partial_match_donor_residue` |
| WP4 codec stub | `T4a.<codec_endpoint>`, `T4b.<codec>` (REVIEW_REQUIRED tolerated) | `codec_binding_disagreement` |
| WP5 machine driver | `T1.gpio.i2s.*`, `T4a.qup.*`, `T4b.<codec>.*`, `T2.*` (no DISAGREE) | `gating_row_disagree_on_bus` |
| WP6 audioreach | `T3.lpass_macro_instance`, `T3.dsp_subsystem_instance` | `gating_row_disagree_on_lpass_count` / `gating_row_ambiguous_soundwire` |

### 4.2 Fail-closed default

The gating expression is **conjunctive** and **restrictive by default**. Adding a new track or a new subject in Phase-2A does *not* automatically open new generation paths in Phase-2B — a Phase-2B WP has to explicitly consume the new row. This is the "surface, not suppress" asymmetry inherited from WP-C: unknown rows are treated as ungated → the generator is *not* called until a WP-explicit rule opens it.

### 4.3 Post-gen gate

After generation, the artifact re-enters Phase-2A's Comparison Core (WP7) with `contributes_rows`. If any post-gen row is not MATCH or PARTIAL_MATCH, the artifact is stamped `NEEDS_REVIEW` in the report and moved to a `post_gen_review_required` worklist bucket — the human must sign off before it moves out of `generated/<run_id>/`.

---

## 5. Human-in-the-loop contract

Phase-2B is **diagnostic-first, gating-second**, exactly like Phase-2A. The engine does not commit, does not send patches, does not build, does not flash. Every step that leaves the "diagnostic report" boundary requires an explicit human lever.

### 5.1 What the engine does autonomously

- Reads the Phase-2A snapshot (no new I/O).
- Runs generators whose gates are OPEN.
- Writes generated bytes to **an untracked directory** `generated/<run_id>/`.
- Runs post-gen verification.
- Appends the `## Generated Artifacts` section to the report.

### 5.2 What the engine does NOT do autonomously (require human ack)

| Action | Where the human lever lives |
|---|---|
| Copy any `generated/<run_id>/…` file into a tracked path (`arch/…`, `sound/…`, `.dtsi` under `linux/`, etc.) | Manual `cp` or a review script; never the engine. |
| `git add` / `git commit` any generated bytes | Manual `git`; never the engine. |
| Modify `Kconfig` / `defconfig` to enable generated modules | Out of scope (§6). Manual. |
| Invoke a build | Out of scope (§6). Manual. |
| Send a patch series (`git send-email`, MR, PR) | Out of scope (§6). Manual. |
| Override a `GeneratorSkipped` verdict ("force-generate") | Not supported. If the reviewer disagrees with a skip, they resolve the underlying Phase-2A row and re-run; there is no `--force` flag. |
| Delete or overwrite existing tracked artifacts under review | Not supported. The engine writes side-by-side under `generated/<run_id>/`; the reviewer merges. |

### 5.3 Review checkpoints

Two hard checkpoints per run:

1. **Pre-generation checkpoint** — the reviewer inspects Phase-2A's `## Schematic ↔ IPCAT Cross-Verification` section, in particular the reviewer worklist and any `DISAGREE_WITH_AUTHORITY` / `REVIEW_REQUIRED` rows. Only after the reviewer accepts the Phase-2A verdicts do they enable `--generate`. This checkpoint is *implicit* — it is enforced by the CLI default of `--generate` OFF.
2. **Post-generation checkpoint** — the reviewer inspects the `## Generated Artifacts` section, in particular the `post_gen_review_required` worklist. Only after this checkpoint do generated artifacts leave `generated/<run_id>/`.

### 5.4 "No autonomous commits" concretely

- The engine writes to `generated/<run_id>/` only. `generated/` is `.gitignore`'d (WP9 acceptance criterion adds the entry if missing).
- The engine never invokes `git` (nor any shell/`os.system`/`subprocess` targeting `git`). A test enforces this: `grep -r 'import subprocess\|os\.system\|git ' orchestrator/generation/` yields no matches outside of type stubs.
- The engine has no write access to any tracked kernel path from within `orchestrator/generation/`. A path-guard helper in `orchestrator/generation/config.py` rejects any write path outside `generated/<run_id>/`.

---

## 6. Non-goals for Phase-2B

The following are **explicitly out of scope** for Phase-2B and are deferred to Phase-2C or later. Being explicit lets Phase-2B stay small.

- **Kconfig / defconfig modification.** Enabling generated modules in the build system is Phase-2C. Phase-2B produces C/DTS bytes; whether the build picks them up is a separate concern.
- **Build invocation.** No `make`, no `bazel`, no cross-compile. The engine does not know whether the generated bytes compile — that is a reviewer step, downstream.
- **Hardware access.** No flashing (`fastboot`), no `adb`, no serial, no boot, no runtime probe.
- **Upstream submission.** No `git send-email`, no lkml post, no MR/PR creation on Gerrit/GitHub/GitLab. Phase-2B does not know the target upstream repository — the reviewer selects it.
- **Runtime validation of the machine driver.** Confirming `snd_soc_card` probes on hardware is a runtime concern; the engine's guarantee stops at "the generated C matches the DT and passes post-gen cross-verification against IPCAT."
- **Interactive/loop generation.** No iterative "generate → review → re-generate" loop. Every run is one-shot: same trusted facts + same KB → same bytes. Iteration is a human step, expressed as a new run.
- **Cross-artifact refactoring.** The engine does not, e.g., factor a shared header out of two generated C files. Every artifact is a fresh emission from its generator; consolidation is a human step.
- **Modifying Phase-2A source.** Phase-2B imports Phase-2A; it does not extend Phase-2A tracks (T1..T5). If Phase-2B needs a fact Phase-2A does not surface, the fact is `UNAVAILABLE` and the generator emits `GeneratorSkipped` — the correct fix is a Phase-2A follow-up WP, not a Phase-2B workaround.
- **Modifying the WP-C cardinality lane.** Inherited from Phase-2A. Untouched.
- **New IPCAT tool calls.** The engine reuses only what Phase-2A's collector already fetched. No new live IPCAT dependency.
- **Any credential handling beyond the inherited env-var-first path.** Phase-2B introduces no new authentication surface. `auth.json` / `.credentials.json` remain untouched.

---

## 7. Open questions

These are the substantive questions Phase-2B cannot answer from what Phase-2A hands it. Each has to be resolved (in a docs-only decision record, no code) before the corresponding WP is implemented.

### 7.1 Codec DT bindings source of truth (WP4)

**Question.** For a codec like WSA883x, PCM1681, or ADAU1979, where is the *authoritative* Linux DT binding definition — `Documentation/devicetree/bindings/sound/*.yaml` in mainline, an out-of-tree vendor tree, an internal Qualcomm codec-driver repo, or the codec vendor's datasheet?

**Why it matters.** The WP4 codec stub / upstream-reference generator has to (a) *check* for upstream presence and (b) *cite* the binding when present, or (c) construct a stub whose `compatible` and register-map schema match what a real reviewer would upstream. The wrong source of truth means the generated stub either duplicates an existing driver (waste) or diverges from the eventual upstream binding (rework).

**Decision blockers.** T4b is `authority_out_of_scope` by design in Phase-2A because IPCAT does not enumerate codec DT bindings. Phase-2B needs a *different* authority for this — likely a curated KB entry per codec, populated by a human. The question is which repo(s) that KB should mirror and how it stays fresh.

**Not blocking WP1–WP3.** Blocks WP4 acceptance criteria.

### 7.2 Pre-runtime machine driver validation (WP5)

**Question.** Absent a build and absent hardware, what can the engine assert about a generated machine driver beyond "the file matches the DT declarations"? Options include (a) a static C parse + symbol reference check against a pinned kernel source tree; (b) a syntax-only lint (no semantic check); (c) nothing — leave everything to the reviewer.

**Why it matters.** A generated machine driver that references a nonexistent `snd_soc_dai_link` field, an undefined codec `.of_match_table` entry, or a mistyped `dai_fmt` constant will fail at build. Catching those pre-runtime keeps the human from bouncing on a build error the engine could have flagged.

**Not blocking WP1–WP4, WP6.** Blocks WP5 acceptance criteria depth. WP5 can ship with option (c) and be strengthened later.

### 7.3 AudioReach topology XML source of truth (WP6)

**Question.** AudioReach graphs have both an XML schema (upstream QC releases, GPR bindings) and DTS-embedded fragments (used in some SoCs' `.dtsi`). Which is Phase-2B's target artifact for WP6 — the XML, the DTS binding, or both? And which reference schema anchors the KB (upstream Qualcomm public specs, internal Qualcomm audio DSP repo, kernel `Documentation/`)?

**Why it matters.** WP6's post-gen verification (T3.lpass_macro_instance / T3.dsp_subsystem_instance) is straightforward — count named blocks in the emitted artifact and compare against the Phase-2A rows. But *what* to emit, and against *which* schema, is undecided. Emitting the wrong shape means a downstream tool (GPR runtime, audioreach loader) rejects the file even when the counts are right.

**Not blocking WP1–WP5, WP7–WP9.** Blocks WP6 acceptance criteria.

---

*Planning and specification only. No code. No commits. No Phase-2A modifications. WP-C cardinality lane at `28f2f07` remains untouched. All values referenced are traced to Phase-1B/1C/2A evidence artifacts already in-repo; no value is fabricated.*
