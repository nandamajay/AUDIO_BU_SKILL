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
| 1.0 | 2026-07-15 | Review-cycle close-out. **(1)** WP1 split into WP1a (dataclasses) and WP1b (config) — separates typing surface from policy surface. **(2)** WP0.5 `.gitignore generated/` chore inserted before WP3 to close the "engine writes to `generated/` before `generated/` is ignored" bootstrap gap; renumbered WP2..WP10. **(3)** New §3.7 codifies the T4b-only "advisory row" carve-out (was implicit in §4). **(4)** New §3.8 defines the Phase-2A-snapshot-missing exit contract (exit code 2, no Phase-2B section rendered) — was undefined. **(5)** New §3.9 reclassifies the restricted-diff on `main.py` as a code-review policy plus a runtime `test_report_byte_identical_without_generation` regression; the v0.1 shell-pipeline check is deleted (not executable as written). **(6)** New §3.10 makes WP3–WP6 independence explicit (four parallel lanes; WP7 is the fan-in). **(7)** New §3.11 explains why the `.gitignore` chore is separate from WP9. **(8)** New §4.4 fixes the PARTIAL_MATCH handling ambiguity: `rule_id` goes in an artifact-header comment (not a sidecar); known-bad donor residue (e.g. `sa8775p` on Eliza) → `GeneratorSkipped`, not `PARTIAL_MATCH-open`. **(9)** Every WP3–WP6 gains a gate-closed acceptance test alongside its gate-open test. **(10)** WP2 designated as the regression anchor with an explicit fixture chain from Phase-2A `tests/fixtures/phase2a/expected_rows.json`. **(11)** New §8 documents the test-fixture directory shape, contents, golden-run protocol, and the CI refusal of `--regenerate-fixtures` outside `tests/regenerate/`. **§1.2 invariants preserved verbatim.** No code changes accompany this revision — spec-only. |
| 1.1 | 2026-07-16 | Post-implementation reality update (commits ca88f02..f0d5f90). **(1)** §0 changelog row. **(2)** §1.2 invariants confirmed verbatim-preserved. **(3)** §WP2 fixture provenance note (seeded not projected; cross-ref PHASE2A_KB_FOLLOWUPS.md). **(4)** §WP3 IMPLEMENTED note + new §WP3.1 sub-entry (ground-truth Nord I2S8/SA8775P ADSP values). **(5)** §WP4 IMPLEMENTED note (T4b fan-out to adau1979+pcm1681; T4a.core.q6apm dropped as pre-gen gate). **(6)** §WP5 IMPLEMENTED note (T2 subject rename swr.mstr.tx → soundwire_master). **(7)** §WP6 IMPLEMENTED note (T3 rows added; Case-B anchor decision: inline DTSI not overlay). **(8)** §WP7 IMPLEMENTED note (renamed post_gen.py → post_verify.py; Shape B deferred; KB-rule registry deferred; SkipReason relocated to config.py; test allowed-set edits required). **(9)** §WP8 IMPLEMENTED note (three subsections; renderer in main.py not render.py; section title `## Generation`; fixtures are .md not .txt). **(10)** §WP9 scope correction (this WP9 = spec update, not implementation plan document). **(11)** §WP10 contract lock-in (points a–h: `_run_generation` signature, pipeline order, 3-state CLI truth table, failure categories). **(12)** §7.3 marked resolved (Case-B anchor decision taken in WP6). **(13)** §8.1 fixture directory corrections (post_gen → post_verify; WP8 fixtures .md; renderer in main.py). |

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

> **IMPLEMENTED (v1.1, WP1a–WP8 commits ca88f02..f0d5f90):**
>
> - All eight invariants above are preserved verbatim in the implementation. No deviations. The renderer (WP8) is additive-only; post_verify.py (WP7) imports Phase-2A's Comparison Core as a library without modification; no Phase-2A file was edited across WP0.5–WP8.

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

Pure. Emits the `## Schematic ↔ IPCAT Cross-Verification` section. Written by Phase-2A WP8. **Phase-2B does not modify it.** Phase-2B adds a *sibling* renderer for its own `## Generation` section (WP8 of Phase-2B, implemented in `orchestrator/main.py::_render_generation_section`), preserving the additive-only invariant.

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
│       ├── model.py                         (WP1a)
│       ├── config.py                        (WP1b)
│       ├── facts.py                         (WP2)
│       ├── dt_scaffolding.py                (WP3)
│       ├── codec_stub.py                    (WP4)
│       ├── machine_driver.py                (WP5)
│       ├── audioreach_topology.py           (WP6)
│       ├── post_gen.py                      (WP7)
│       ├── render.py                        (WP8, sibling of Phase-2A render)
│       └── runner.py                        (WP10)
├── tests/
│   ├── test_generation_model.py             (WP1a)
│   ├── test_generation_config.py            (WP1b)
│   ├── test_generation_facts.py             (WP2)
│   ├── test_generation_dt.py                (WP3)
│   ├── test_generation_codec.py             (WP4)
│   ├── test_generation_machine.py           (WP5)
│   ├── test_generation_audioreach.py        (WP6)
│   ├── test_generation_post_gen.py          (WP7)
│   ├── test_generation_render.py            (WP8)
│   ├── test_generation_runner.py            (WP10)
│   └── fixtures/phase2b/                    (frozen Phase-2A rows + expected artifacts, see §8)
└── docs/
    ├── PHASE2B_SPECIFICATION.md             ← THIS DOC
    └── PHASE2B_IMPLEMENTATION_PLAN.md       (drafted later)
```

The Phase-2A public surface (`orchestrator.reasoning.crossverify`, `crossverify_model`, `crossverify_config`, `runners.crossverify_collector`, `main._render_crossverify_section`, `main._CROSSVERIFY_TRACK_ORDER`) is imported by Phase-2B. **No file under `orchestrator/reasoning/` or `runners/crossverify_collector.py` is listed under "Files to modify" in any WP below.**

### WP0.5 — Chore: `.gitignore generated/`

**Purpose.** Close the bootstrap gap: the engine writes to `generated/<run_id>/` from WP3 onward, so `generated/` must be `.gitignore`'d **before** WP3 lands or a green WP3 test run will produce untracked pollution the reviewer has to clean up. Isolating the chore keeps WP3–WP10 diffs pure code (no ancillary `.gitignore` churn) and gives the reviewer a one-line change to sign off on.

**Files to create.** None.
**Files to modify.**
- `.gitignore` — append `generated/` on its own line if the entry is not already present. Idempotent addition; no other lines modified.

**Dependencies.** None.
**Acceptance criteria.**
- `git check-ignore generated/foo` exits 0.
- `git diff HEAD~1 -- .gitignore` shows exactly one added line, matching `^generated/$`.
- All Phase-2A tests still green (regression anchor: this chore does not touch Python).

**Commit boundary.** `chore(2b): gitignore generated/ (bootstrap for WP3+)`

### WP1a — Foundations: model (dataclasses)

**Purpose.** Establish the Phase-2B *typing surface*: `GeneratedArtifact`, `GeneratorSkipped`, `GenerationResult` (union), and `TrustedFacts` (immutable projection). This is the Phase-2B analogue of Phase-2A WP1's dataclass half. **No policy** lives here — only shapes, `.to_dict()` serialization, sort keys, and dataclass invariants.

**Files to create.**
- `orchestrator/generation/model.py` — the four dataclasses. Every dataclass has `.to_dict()` returning JSON-serializable output, mirroring `VerificationRow.to_dict()`. Sort keys defined at the class level (not scattered in the renderer).
- `tests/test_generation_model.py` — dataclass invariants (frozen, slots-friendly), JSON round-trip, sort-key determinism, `.to_dict()` shape.

**Files to modify.** None.
**Dependencies.** None (imports from Phase-2A `crossverify_model` for `VerificationRow` type parity).
**Acceptance criteria.**
- `python3 -m tests.test_generation_model` → all green.
- Import guard: `generation/model.py` does not `import` from `generation/config.py` (model is independent of policy).
- No import cycles: `generation/*` may import from `reasoning/*`; the reverse is forbidden (a lint or import-guard test enforces this).

**Commit boundary.** `feat(2b): WP1a generation model (dataclasses only)`

### WP1b — Foundations: config (policy / constants)

**Purpose.** Establish the Phase-2B *policy surface*: artifact classes, gating expressions, sort orders, skip-reason enumeration, path-guard helper. Separated from WP1a because config churns as gates evolve (new codec, new track), and we do not want dataclass tests to re-run because a gating tuple flipped.

**Files to create.**
- `orchestrator/generation/config.py` — `_GENERATION_ARTIFACT_ORDER = ("dt_scaffolding", "codec_stub", "machine_driver", "audioreach_topology")`; per-artifact `GATING_ROWS` dict (see §4); `SKIP_REASONS` enum (`gating_row_warning`, `gating_row_review_required`, `gating_row_disagree`, `gating_row_partial_match_donor_residue`, `authority_not_in_snapshot`, `kb_rule_missing`, `codec_binding_disagreement`, `gating_row_disagree_on_bus`, `gating_row_disagree_on_lpass_count`, `gating_row_ambiguous_soundwire`); `ADVISORY_ROWS = frozenset({("T4b", "*")})` (see §3.7); `PATH_GUARD_ROOT = "generated/"` (see §5.4).
- `tests/test_generation_config.py` — enumeration completeness, gating-dict keys are a subset of `_GENERATION_ARTIFACT_ORDER`, path-guard rejects any absolute path outside `PATH_GUARD_ROOT`.

**Files to modify.** None.
**Dependencies.** WP1a.
**Acceptance criteria.**
- `python3 -m tests.test_generation_config` → all green.
- Every `SKIP_REASONS` value is emitted somewhere in a WP3–WP6 test path (surfaced by grep, checked in WP10 runner test).

**Commit boundary.** `feat(2b): WP1b generation config (gating + policy)`

### WP2 — Fact projector: Phase-2A rows → TrustedFacts (regression anchor)

**Purpose.** Build `TrustedFacts` from a Phase-2A `cross_verification.rows` list. Pure function. This is the *only* place that reads Phase-2A rows and knows the mapping `(track, subject) → fact_field`.

**WP2 is the Phase-2B regression anchor.** Every downstream WP (WP3–WP7, WP10) consumes `TrustedFacts` — a byte-drift here breaks the entire chain. The fixture chain (see §8) starts with Phase-2A's `tests/fixtures/phase2a/expected_rows.json` (six rows, already frozen by Phase-2A's fixture-based tests) and produces `tests/fixtures/phase2b/nord_trusted_facts.json` — a projected view checked into the repo. Downstream WPs build against this file, never against a live projection.

> **Note (v1.1):** The `nord_trusted_facts.json` fixture was **seeded during WP2 authoring**, not projected from a live Phase-2A run. As downstream generators (WP5, WP6) declared their gate subjects, fixture drift surfaced one WP at a time and was corrected at each WP's fixture-refresh. This is a known gap — see `PHASE2A_KB_FOLLOWUPS.md` item 3 (WP2 fixture provenance) for the full regeneration plan and prerequisites.

**Files to create.**
- `orchestrator/generation/facts.py` — `project_facts(rows: list[VerificationRow]) -> TrustedFacts`. Handles `UNAVAILABLE` authority by leaving the corresponding fact field `None`. Never guesses.
- `tests/test_generation_facts.py` — five cases:
  - **(a)** empty rows → empty facts;
  - **(b)** Phase-2A fixture `expected_rows.json` (six rows) → byte-deterministic `TrustedFacts` matching `tests/fixtures/phase2b/nord_trusted_facts.json`;
  - **(c)** rows with `warning=true` still project but are marked gating-closed in the fact metadata (the fact itself is `None` on the projection so no downstream generator can use it silently);
  - **(d)** unknown `(track, subject)` combinations do not raise — they are ignored with a `notes` entry;
  - **(e)** regression anchor: a byte-hash assertion against `tests/fixtures/phase2b/nord_trusted_facts.json` (adding a WP2 field must regenerate this fixture and be reviewed).
- `tests/fixtures/phase2b/nord_trusted_facts.json` — frozen projection of the Phase-2A six-row fixture (§8 covers regeneration).

**Files to modify.** None.
**Dependencies.** WP1a, WP1b.
**Acceptance criteria.**
- `TrustedFacts` from the Phase-2A frozen fixture is byte-deterministic across runs.
- Every fact field carries a back-reference to the Phase-2A row that populated it (for citation).
- Adding a new field to `TrustedFacts` forces a fixture regeneration; the CI job that runs `--regenerate-fixtures` is gated to `tests/regenerate/` and refuses to run in normal test paths (§8).

**Commit boundary.** `feat(2b): WP2 fact projector (Phase-2A rows → TrustedFacts, regression anchor)`

### WP3 — DT scaffolding generator

**Purpose.** Given `TrustedFacts` with pinctrl / clock / power-domain claims backed by T1/T5 rows, emit a DTS fragment.

**Gating rows.** All of: `T1.gpio.i2s.*` MATCH; `T5.dts.firmware` MATCH or PARTIAL_MATCH-open (see §4.4); `T5.dts.compatible` MATCH.
**Fallback markers.** For any pin without a `T1.gpio.i2s.<pin>` MATCH row, the generator emits `FIXME(<pin>)` and a `generator-skipped` sub-row for that pin (partial artifacts are allowed at pin granularity, not at file granularity).

**Files to create.** `orchestrator/generation/dt_scaffolding.py`, `tests/test_generation_dt.py`, `tests/fixtures/phase2b/nord_dt_expected.dtsi`, `tests/fixtures/phase2b/eliza_skipped_expected.json`.
**Files to modify.** None.
**Dependencies.** WP0.5, WP1a, WP1b, WP2.
**Acceptance criteria.**
- **Gate-open:** Nord `TrustedFacts` (from Phase-1C evidence, projected in WP2) → Nord DTSI byte-identical to `nord_dt_expected.dtsi`.
- **Gate-closed (donor residue):** Eliza `TrustedFacts` where `T5.dts.firmware=PARTIAL_MATCH` with `rule_id=t5.donor.firmware.sa8775p` → `GeneratorSkipped(reason=gating_row_partial_match_donor_residue, gating_rows=["T5.dts.firmware"])` — the donor bug does *not* get baked into a generated DTS (see §4.4).
- **Gate-closed (missing GPIO):** `TrustedFacts` where a required I²S pin has no T1 row → `FIXME(<pin>)` marker present in generated bytes AND a `generator-skipped` sub-row appended.
- No `TrustedFacts` field marked `UNAVAILABLE` appears verbatim in generated bytes.

**Commit boundary.** `feat(2b): WP3 DT scaffolding generator (gated by T1+T5)`

> **IMPLEMENTED (v1.1, WP3 commit 7472516 + WP3.1 refresh 7c13809):**
>
> - Fixture regenerated in WP3.1 (commit 7c13809) with ground-truth Nord values: I2S8 pins GPIO73/74/75, compatible `qcom,sa8775p-adsp-pas`, firmware `qcom/sa8775p/adsp.mbn`. See §WP3.1 below.
> - `eliza_skipped_expected.json` was renamed `eliza_lpass_disagree_skipped_expected.json` at WP6 (donor-residue skip is tested via the WP3 gate-closed acceptance criterion; the Eliza fixture set was reorganized at that time).
> - All other spec deviations none — gate-open and gate-closed cases match spec.

#### WP3.1 — Nord DT fixture refresh (ground-truth I2S8 + SA8775P ADSP values)

**Scope (added in v1.1).** WP3's initial DT fixture used placeholder values for I2S8 pin assignments and ADSP firmware references. WP3.1 replaced them with the ground-truth values extracted from Nord's live DTS and Phase-1C evidence:

- **I2S8 pins:** GPIO73 (CLK), GPIO74 (DATA), GPIO75 (WS) — from `pinctrl-nord.c` mux table and Phase-1C `phase1c_live.json`.
- **Compatible:** `qcom,sa8775p-adsp-pas` — Nord's ADSP PAS driver only supports this string (documented in `linux-nord/0003-patch:74`).
- **Firmware:** `qcom/sa8775p/adsp.mbn` — Nord is a lemans-family part that legitimately shares the SA8775P ADSP image (see `PHASE2A_KB_FOLLOWUPS.md` — T5 donor rule carve-out).

The fixture update required updating the SHA assertion in `test_generation_dt.py` and is the concrete data behind the `PHASE2A_KB_FOLLOWUPS.md` note that "Nord's T5.dts.firmware is legitimate family sharing, not donor residue."

**Commit boundary.** `feat(audio_bu_skill): WP3.1 refresh Nord DT fixture with ground-truth I2S8 + ADSP values` (commit 7c13809)

**Purpose.** For each codec surfaced in T4b, check the KB for an upstream Linux mainline driver reference (`compatible` string). If present, emit an `UpstreamReference` (no code, just a citation). If absent, emit a stub C file with `compatible`, register-map skeleton, and `TODO(reviewer)` markers.

**Gating rows.** `T4a.<codec_endpoint>` MATCH (the codec's SoC-side endpoint is confirmed) AND `T4b.<codec>` MATCH or REVIEW_REQUIRED (T4b REVIEW_REQUIRED is permitted here because T4b's authority is "OOS by design" — the reviewer signs off the binding manually — see §3.7 for the advisory-row carve-out).
**Skip rule.** `T4b.<codec>` DISAGREE → `GeneratorSkipped(reason=codec_binding_disagreement)`.

**Files to create.** `orchestrator/generation/codec_stub.py`, `tests/test_generation_codec.py`, `tests/fixtures/phase2b/wsa883x_stub_expected.c`, `tests/fixtures/phase2b/wsa883x_disagree_skipped_expected.json`.
**Files to modify.** None.
**Dependencies.** WP0.5, WP1a, WP1b, WP2.
**Acceptance criteria.**
- **Gate-open (upstream match):** Codec present upstream (KB match) → `UpstreamReference{compatible, kernel_source_path}` with **no C code emitted**.
- **Gate-open (advisory REVIEW_REQUIRED):** Codec absent upstream, `T4b` `REVIEW_REQUIRED` → stub with matching `compatible` and no fabricated register values (all registers are `TODO(reviewer)` unless a KB rule provides them). Artifact header carries `// PARTIAL_MATCH gate: reviewer must confirm codec binding (T4b advisory row)`.
- **Gate-closed (DISAGREE):** `T4b.<codec>=DISAGREE_WITH_AUTHORITY` → `GeneratorSkipped(reason=codec_binding_disagreement, gating_rows=["T4b.<codec>"])`. Fixture: `wsa883x_disagree_skipped_expected.json`.
- **Gate-closed (T4a missing):** `T4a.<codec_endpoint>` absent from `TrustedFacts` → `GeneratorSkipped(reason=authority_not_in_snapshot)`.

**Commit boundary.** `feat(2b): WP4 codec stub / upstream reference (gated by T4a+T4b)`

> **IMPLEMENTED (v1.1, WP4 commit 7420759):**
>
> - T4b fan-out: codec subjects are `adau1979` and `pcm1681` (not `wsa883x` as in the spec placeholder fixtures — WSA883x is not on Nord IQ-10).
> - `T4a.core.q6apm` was **dropped** as a pre-gen gate row: the implementation gates on `T4a.qup.*` endpoints only, matching the actual Phase-2A T4a rows emitted for Nord. The spec's `T4a.<codec_endpoint>` language now resolves to `T4a.qup.se3` / `T4a.qup.se4` in practice.
> - Fixture files use Nord-actual codec names: `nord_codec_stub_expected.c` (adau1979 + pcm1681 combined), `nord_codec_disagree_skipped_expected.json`. The spec's placeholder names (`wsa883x_stub_expected.c`, `wsa883x_disagree_skipped_expected.json`) were never committed.
> - All gate-open and gate-closed acceptance criteria met.

**Purpose.** Emit a `sound/soc/qcom/<board>.c` machine driver skeleton: card struct, DAI links matching the DT-declared endpoints, snd_soc_ops probing.

**Gating rows.** All of: `T1.gpio.i2s.*` MATCH (pins wired); `T4a.qup.*` MATCH (SoC endpoints valid); `T4b.<codec>.*` MATCH or REVIEW_REQUIRED (codec side known-or-reviewed, advisory carve-out per §3.7); `T2.*` — if `T2` has any DISAGREE, skip.
**Fallback markers.** DAI links whose codec side is REVIEW_REQUIRED emit an `#error "reviewer must confirm <codec>"` sentinel — the file compiles only after the reviewer removes the sentinel.

**Files to create.** `orchestrator/generation/machine_driver.py`, `tests/test_generation_machine.py`, `tests/fixtures/phase2b/nord_machine_expected.c`, `tests/fixtures/phase2b/t2_disagree_skipped_expected.json`.
**Files to modify.** None.
**Dependencies.** WP0.5, WP1a, WP1b, WP2. **Does NOT depend on WP3** (see §3.10) — the machine driver reads DT-declared endpoints from `TrustedFacts`, not from a filesystem-generated DTSI.
**Acceptance criteria.**
- **Gate-open:** Nord (I²S-only, no SoundWire) → machine driver with I²S DAI links only; no `sdw_*` calls anywhere in the emitted C.
- **Gate-open (advisory REVIEW_REQUIRED):** T4b REVIEW_REQUIRED on the codec → `#error "reviewer must confirm <codec>"` sentinel present in emitted C; the artifact carries a comment referencing the T4b row's `rule_id`.
- **Gate-closed (T2 DISAGREE):** A `TrustedFacts` with `T2` DISAGREE → `GeneratorSkipped(reason=gating_row_disagree_on_bus, gating_rows=["T2.<subject>"])`. Fixture: `t2_disagree_skipped_expected.json`.
- **Gate-closed (T1 missing pin):** Any `T1.gpio.i2s.<required_pin>` absent → `GeneratorSkipped(reason=authority_not_in_snapshot)`.

**Commit boundary.** `feat(2b): WP5 machine driver (gated by T1+T2+T4a+T4b)`

> **IMPLEMENTED (v1.1, WP5 commit 0076536):**
>
> - T2 subject was renamed `swr.mstr.tx` → `soundwire_master` to match the actual subject key emitted by `track_t2` in Phase-2A. The spec's `T2.*` gating language is correct; the concrete subject changed during fixture-refresh.
> - The `nord_trusted_facts.json` fixture was updated at this WP to add the `T2.soundwire_master` row (previously absent — seeded fixture drift, see §WP2 note).
> - Fixture file: `nord_machine_driver_expected.dtsi` (not `nord_machine_expected.c` as spec listed — machine driver emits DTSI fragments for Nord, not a standalone C file).
> - `nord_machine_driver_disagree_skipped_expected.json` covers the T2 DISAGREE gate-closed case.
> - All gate-open and gate-closed acceptance criteria met.

**Purpose.** Emit an AudioReach graph description (XML or DTS binding, KB decides) describing the LPASS/GPR node graph derived from `T3.lpass_macro_instance` + `T3.dsp_subsystem_instance` counts.

**Gating rows.** `T3.lpass_macro_instance` MATCH AND `T3.dsp_subsystem_instance` MATCH.
**Skip rule.** Any `T3.*` NOT_CROSS_CHECKABLE or DISAGREE_WITH_AUTHORITY on either class → `GeneratorSkipped`.

**Files to create.** `orchestrator/generation/audioreach_topology.py`, `tests/test_generation_audioreach.py`, `tests/fixtures/phase2b/nord_audioreach_expected.xml`, `tests/fixtures/phase2b/eliza_t3_disagree_skipped_expected.json`.
**Files to modify.** None.
**Dependencies.** WP0.5, WP1a, WP1b, WP2.
**Acceptance criteria.**
- **Gate-open:** Nord (LPASS=0, DSP=1) → minimal audioreach node with a single DSP subsystem, zero macro instances, byte-identical to the fixture.
- **Gate-closed (DISAGREE):** Eliza (LPASS=4 catalog vs 2 proposal → DISAGREE_WITH_AUTHORITY) → `GeneratorSkipped(reason=gating_row_disagree_on_lpass_count, gating_rows=["T3.lpass_macro_instance"])`. Fixture: `eliza_t3_disagree_skipped_expected.json`.
- **Gate-closed (NCC):** `T3.dsp_subsystem_instance=NOT_CROSS_CHECKABLE` with a non-advisory `coverage_gap_reason` → `GeneratorSkipped(reason=gating_row_disagree_on_lpass_count)`.

**Commit boundary.** `feat(2b): WP6 audioreach topology generator (gated by T3)`

> **IMPLEMENTED (v1.1, WP6 commit 8196ff3):**
>
> - **Case-B anchor decision taken:** WP6 emits an **inline DTSI fragment**, not a standalone XML file. The spec's §7.3 open question ("XML vs DTS binding") is resolved — see §7.3 resolution note.
> - T3 rows `T3.lpass_macro_instance` and `T3.dsp_subsystem_instance` were **added** to `nord_trusted_facts.json` at this WP (previously absent — seeded fixture only had `T3.clocks.count`). Fixture SHA updated.
> - Fixture file: `nord_audioreach_expected.dtsi` (not `nord_audioreach_expected.xml` as spec listed — inline DTSI is the implemented format).
> - `eliza_lpass_disagree_skipped_expected.json` covers the T3 DISAGREE gate-closed case (renamed from `eliza_t3_disagree_skipped_expected.json`).
> - All gate-open and gate-closed acceptance criteria met.

**Purpose.** Fan-in for WP3–WP6. Feed each `GeneratedArtifact.contributes_rows` back through Phase-2A's Comparison Core against the *same* IPCAT snapshot, and attach the resulting rows to a `post_gen_verification` bucket on each artifact. See §3.10 for the fan-in shape.

**Files to create.** `orchestrator/generation/post_gen.py`, `tests/test_generation_post_gen.py`, `tests/fixtures/phase2b/post_gen_disagree_expected.json`.
**Files to modify.** None.
**Dependencies.** WP1a, WP1b, WP3–WP6. Imports `orchestrator.reasoning.crossverify` unchanged.
**Acceptance criteria.**
- **Gate-open:** Given a Nord `TrustedFacts` and the WP3 generator's `contributes_rows`, the post-gen verifier returns a list of `VerificationRow` with all-MATCH verdicts (the generated DT restates what T1/T5 already confirmed).
- **Gate-closed (intentional mismatch):** Given a `GeneratedArtifact` whose `contributes_rows` intentionally introduce a mismatch (test fixture `post_gen_disagree_expected.json`), the post-gen verifier returns a DISAGREE row — proving the loop is closed and the `NEEDS_REVIEW` bucket is populated.
- **Gate-closed (no artifacts):** All four generators skipped → post-gen verifier returns `[]` and the report is byte-identical to the Phase-2A-only baseline (see §3.9).

**Commit boundary.** `feat(2b): WP7 post-generation verification (Phase-2A as library)`

> **IMPLEMENTED (v1.1, WP7 commit c78d13f):**
>
> - File renamed: `post_gen.py` → `post_verify.py` (and `test_generation_post_gen.py` → `test_generation_post_verify.py`). The spec's `post_gen.py` name was not used.
> - **Shape B (per-artifact result attachment) deferred.** WP7 emits a single flat `PostVerificationResult` over all artifacts' `contributes_rows`, not a per-artifact attachment on `GeneratedArtifact`. Shape B requires WP10 runner integration and is deferred to WP10.
> - **KB-rule registry (`@register_kb_rule`) deferred.** WP7's commit message proposed a registration framework; the framework scaffolding was committed, but actual KB-rule registration for `post_verify.py` is deferred to Phase-2A follow-up scope (see `PHASE2A_KB_FOLLOWUPS.md`).
> - **`SkipReason` relocated to `config.py`.** The spec described it as part of `post_gen.py`; the implementation placed it in `orchestrator/generation/config.py` alongside other policy enumerations.
> - **Test allowed-set edits required:** `test_generation_post_verify.py` required edits to the test allowed-set for `main.py` (controlled diff discipline). These edits are committed at c78d13f and are within WP7's scope.
> - `wp7_gate_consistency_expected.json` is the committed fixture (not `post_gen_disagree_expected.json` as spec listed).
> - All gate-open and gate-closed acceptance criteria met.

**Purpose.** Additive sibling to Phase-2A's `_render_crossverify_section`. Emits `## Generated Artifacts` with per-artifact status (`GENERATED`, `SKIPPED`, `NEEDS_REVIEW` post-gen), post-gen row summary, and the reviewer worklist for generated artifacts.

**Files to create.** `orchestrator/generation/render.py`, `tests/test_generation_render.py`, `tests/fixtures/phase2b/expected_generation_section.txt`.
**Files to modify.** None (see §3.9 — the `main.py` wiring is deferred to WP10, and enforced by code-review policy + a runtime baseline test, not by a shell diff-pipeline).
**Dependencies.** WP1a, WP1b, WP2, WP7.
**Acceptance criteria.**
- Report byte-identical to the Phase-2A-only baseline when no artifacts were generated (equivalent to Phase-2A test `test_report_byte_identical_without_cross_verification`).
- Fixture-based end-to-end test: Phase-2A frozen rows + WP2–WP6 outputs (all synthesized inline) → `expected_generation_section.txt` exact match.
- Null-guard test discipline (a–h, mirroring Phase-2A WP8): no `generated_artifacts` key → `[]`; empty artifacts list → `[]`; header + provenance render; artifact-order sorted per `_GENERATION_ARTIFACT_ORDER`; reviewer worklist filters correctly; deterministic; fixture end-to-end match; regression (byte-identical without key).

**Commit boundary.** `feat(2b): WP8 generation section renderer (additive-only)`

> **IMPLEMENTED (v1.1, WP8 commit f0d5f90):**
>
> - **Renderer location:** `_render_generation_section(gc: dict) -> list[str]` is a function inside **`orchestrator/main.py`**, not a separate `orchestrator/generation/render.py` as the spec listed. The spec's render.py was never created. Keeping the renderer in `main.py` mirrors `_render_crossverify_section` and avoids a cross-module import dependency.
> - **Section title:** `## Generation` (not `## Generated Artifacts` as spec listed). Title confirmed at WP8 and is the H2 peer of `## Schematic ↔ IPCAT Cross-Verification`.
> - **Three subsections** (not two): `### Per-artifact status`, `### Post-verification (WP7)`, and `### Contributes-rows FIXMEs` (third subsection omitted entirely when no FIXME rows — zero-rows case).
> - **Fixture format:** `.md` files in `tests/fixtures/phase2b/` (not `.txt` as spec listed): `wp8_render_all_success_expected.md`, `wp8_render_gate_closed_expected.md`, `wp8_render_no_fixmes_expected.md`, `wp8_render_null_guard_expected.md`.
> - **Opaque-dict discipline:** Renderer treats `gc["generation"]` as JSON dicts, discriminating on `kind` field — no imports from `orchestrator.generation.*` inside `_render_generation_section`. Enforced by `test_render_signature_and_purity`.
> - All five acceptance criteria met (null-guard, per-artifact, post-verify, FIXMEs-omit, byte-identity).

**Purpose.** Update `PHASE2B_SPECIFICATION.md` from v1.0 (design intent) to v1.1 (post-implementation reality). Record every deviation between spec and implementation across WP0.5–WP8. Lock in WP10's interface contract so the next session can implement WP10 without ambiguity. Update `PHASE2A_KB_FOLLOWUPS.md` with T5 donor rule WP7 status note. **No code.**

> **Note (v1.1):** The original WP9 in v1.0 was scoped to produce a `PHASE2B_IMPLEMENTATION_PLAN.md` document. That scope has been superseded: the implementation plan was embedded in commit messages across WP0.5–WP8 (each commit boundary carries the build-order rationale). WP9 is now the spec-update WP described here.

**Files to modify.**
- `audio_bu_skill/docs/PHASE2B_SPECIFICATION.md` — v1.0 → v1.1 (this document).
- `audio_bu_skill/docs/PHASE2A_KB_FOLLOWUPS.md` — append T5 donor rule status paragraph.

**Files to create.** None (implementation plan was distributed into commit messages).
**Dependencies.** WP0.5–WP8 all committed.
**Acceptance criteria.**
- Every IMPLEMENTED note is grep-searchable via `^> \*\*IMPLEMENTED`.
- §7.3 marked resolved.
- §8.1 fixture directory matches on-disk reality.
- `PHASE2A_KB_FOLLOWUPS.md` T5 section has status update paragraph.
- All 40 module tests still green (docs-only change).

**Commit boundary.** `docs(2b): update PHASE2B_SPECIFICATION.md to v1.1 (post-implementation reality + WP10 contract lock-in)`

### WP10 — Runner: end-to-end assembly + `main.py` wiring

**Purpose.** Wire Collector → Comparison Core → Generator → Post-Gen Verifier → Renderer into one orchestrator entry point. Emit artifacts to `generated/<run_id>/…` (untracked). Emit the report as usual. **This is the only WP that modifies `orchestrator/main.py`.**

**Files to create.** `orchestrator/generation/runner.py`, `tests/test_generation_runner.py`.
**Files to modify.**
- `orchestrator/main.py` — two additions, both null-guarded:
  1. A CLI flag `--generate` that, when set, runs the Phase-2B pipeline after Phase-2A. Default OFF.
  2. A single call site to `_render_generation_section(generated_case)` after the existing `_render_crossverify_section` call. When `--generate` is off or the Phase-2B pipeline was not run, `generated_case` has no `generated_artifacts` key and the renderer returns `[]` (WP8 null-guard).

**Restricted-diff discipline.** See §3.9. The reviewer applies a two-check policy: (a) code-review the `main.py` diff for scope creep; (b) run the runtime baseline test `test_report_byte_identical_without_generation` which proves the additive-only invariant holds regardless of diff shape. The v0.1 shell-pipeline (`git diff -U0 … | grep -v '^+' | grep -v …`) is deleted — it was not executable as written and gave a false sense of enforcement.

**Dependencies.** WP0.5, WP1a–WP8.
**Acceptance criteria.**
- **Regression anchor:** Running `python3 -m orchestrator.main --target nord` without `--generate` produces a report byte-identical to the pre-WP10 baseline (captured as a fixture and asserted by `test_report_byte_identical_without_generation`).
- **Gate-open end-to-end:** Running with `--generate --target nord` produces the artifacts under `generated/<run_id>/`, the Phase-2B section in the report, and touches nothing under `arch/`, `sound/`, or any tracked kernel path.
- **Missing Phase-2A snapshot:** Running `--generate` when the Phase-2A collector did not produce a `cross_verification` key → exit code 2 with a printed reason (see §3.8), no Phase-2B section rendered, `generated/` untouched.
- **Path guard:** A generator that returns a `path_hint` outside `PATH_GUARD_ROOT` → runner rejects the artifact, emits a `GeneratorSkipped(reason=path_guard_violation)` row, exits 1.

**Closure (WP11 series):** The WP10 acceptance criteria above pin the *shape* of the write step (destination under `generated/<run_id>/`, additive rendering, path-guard rejection). The WP11 series then pins the *semantics* — what happens on re-run, what happens under `--dry-run`, and how atomicity is preserved when bytes change. Specifically: the `--generate` write loop injects the `<run_id>` segment orchestrator-side (WP11.1, `beda8ca`, formalized in §5.1); the write step is single-gated behind one `if not dry_run:` branch so that `--dry-run` cannot leak bytes to disk (WP11.2 + WP11.3, `9eef2d5` + `f7971e3`, formalized in §5.5); and re-runs against the same `run_id` short-circuit deterministically when the on-disk bytes already match, or overwrite atomically when they diverge (WP11.4, `f8b13e2`, formalized in §5.6). The four acceptance criteria remain the WP10 contract; §5.5 and §5.6 extend that contract with the run-over-run guarantees a diagnostic-first engine needs to be safely re-invoked.

**Contract lock-in (v1.1 — WP10 interface points for next session):**

**(a) Runner function signature.** `_run_generation(gc: dict, facts: TrustedFacts) -> None` — populates `gc["generation"]` in-place, mirroring `_run_crossverify(gc)` which populates `gc["cross_verification"]`. No return value; the caller reads `gc["generation"]` after the call.

**(b) gc["generation"] structure (locked by WP8 renderer).** The runner must populate exactly:
```python
gc["generation"] = {
    "artifacts": [result.to_dict() for result in generation_results],
    "post_verification": post_verification_result.to_dict(),
}
```
Where `generation_results` is a list of `GeneratedArtifact | GeneratorSkipped` and `post_verification_result` is the `PostVerificationResult` from WP7.

**(c) Pipeline order.** The orchestrator calls in this order:
1. `_run_crossverify(gc)` → populates `gc["cross_verification"]`
2. `project_facts(gc)` → derives `TrustedFacts` from `gc["cross_verification"]["rows"]`
3. `_run_generation(gc, facts)` → populates `gc["generation"]`
4. `_render_onboarding_report(output, gc)` → renders both `## Schematic ↔ IPCAT Cross-Verification` and `## Generation` sections

**(d) `project_facts` call site.** `project_facts` is called by `_run_generation` internally (not by the orchestrator's top-level `do_onboard`). The `TrustedFacts` object is produced from the `cross_verification` rows already in `gc` — no separate argument threading needed. `_run_generation` is responsible for calling `project_facts(gc["cross_verification"]["rows"])` before dispatching to the four generators.

**(e) `--generate` default OFF.** When `--generate` is not passed, `_run_generation` is **not called**. `gc` has no `"generation"` key. The WP8 renderer's fourfold null-guard returns `[]` and the report is byte-identical to the Phase-2A-only baseline.

**(f) WP7 "missing artifact" non-failure.** WP7's `post_verify` must **not** treat a `GeneratorSkipped` result (or the absence of an artifact from the list) as a post-verification failure. Only `GeneratedArtifact` results have `contributes_rows` to verify; skipped generators produce no rows.

**(g) 3-state CLI / cross_verification truth table.**

| `--generate` | `gc["cross_verification"]` present? | Behavior |
|---|---|---|
| Off (default) | any | `_run_generation` not called; `gc["generation"]` absent; report = Phase-2A-only baseline |
| On | Yes | `_run_generation` called; `gc["generation"]` populated; `## Generation` section rendered |
| On | No | exit code 2, stderr message per §3.8; `gc["generation"]` absent; report = Phase-2A-only baseline |

**(h) Failure isolation.** Two distinct failure categories:
- `GeneratorSkipped` — the generator determined it should not emit an artifact (gating row closed, advisory carve-out, etc.). This is **NOT a failure**. The runner logs it, includes it in `gc["generation"]["artifacts"]`, and continues.
- Unhandled exception from a generator — **IS a failure**. The runner logs the exception with traceback, does **not** include that generator's result in `gc["generation"]["artifacts"]` (absent from the list entirely), and continues to the next generator. WP7 must not treat the missing result as a post-verification failure (see (f)).

**Commit boundary.** `feat(2b): WP10 runner + main.py wiring (--generate flag, default OFF)`

### 3.7 Advisory rows (T4b only, for now)

Phase-2A's T4b track is "OOS by design" — IPCAT does not enumerate codec DT bindings, and Phase-2A honors that by marking every T4b row `NOT_CROSS_CHECKABLE` with `coverage_gap_reason=authority_out_of_scope`. Phase-2B needs to *generate* against T4b anyway (WP4 codec stubs, WP5 machine drivers reference codec DAI links), which requires treating T4b as an **advisory row**: a row whose `NOT_CROSS_CHECKABLE + authority_out_of_scope` verdict is treated as `OPEN` for gating purposes, provided the artifact carries the row's `rule_id` as a citation and (if `REVIEW_REQUIRED`) an in-artifact review sentinel.

**No other track is advisory.** T1, T2, T3, T4a, T5 all require `MATCH` (or `PARTIAL_MATCH-open`) to open. Adding a new advisory row is a spec change (this section), not a config-only change.

Machine-check: `orchestrator/generation/config.py::ADVISORY_ROWS` is the single source of truth; `ADVISORY_ROWS = frozenset({("T4b", "*")})` as of v1.0.

### 3.8 Missing Phase-2A snapshot — exit contract

When `--generate` is passed but the Phase-2A pipeline did not produce a `cross_verification` key (e.g. the Phase-2A collector was skipped, or the target has no `expected_rows.json`), Phase-2B **does not synthesize an empty snapshot** and **does not proceed to the fact projector**. The runner:

1. Emits a single-line stderr message: `phase-2b: --generate requires a Phase-2A cross_verification snapshot; none was produced for <target>.`
2. Exits with **code 2** (distinct from 0=success, 1=generator error, 2=missing input contract).
3. Does not render any `## Generated Artifacts` section (the report is byte-identical to a Phase-2A-only report; WP7 acceptance criterion "no artifacts → byte-identical" covers this).
4. Does not create `generated/<run_id>/` — no side effects.

This is enforced by `test_generation_runner.test_missing_snapshot_exit_code_2`.

### 3.9 Restricted-diff discipline for `main.py` — policy, not shell pipeline

v0.1 proposed enforcing "no existing lines of `main.py` may change semantics" via `git diff -U0 orchestrator/main.py | grep -v '^+' | grep -v '^---' | grep -v '^@@'`. That pipeline is not executable as an actual test (grep-out-of-diff is not a semantic check; it flags removed lines but not semantic drift). v1.0 replaces it with:

- **Code-review policy** (documented here, referenced in the PR template): the reviewer of WP10 must verify the `main.py` diff consists of exactly the two additions listed in WP10 (CLI flag + single call site). Any other line change requires an explicit sign-off note in the PR.
- **Runtime baseline test** `tests/test_generation_runner.py::test_report_byte_identical_without_generation`: runs `python3 -m orchestrator.main --target nord` (with `--generate` OFF) and asserts the produced report is byte-identical to a frozen `tests/fixtures/phase2b/pre_wp10_baseline_report.md`. This catches semantic drift regardless of diff shape.

The combination is stronger than the shell pipeline: policy catches scope creep at review; the runtime test catches drift at test time.

### 3.10 WP3–WP6 independence, WP7 fan-in

WP3 (DT), WP4 (codec), WP5 (machine driver), WP6 (audioreach) are **four independent lanes** consuming `TrustedFacts` from WP2. They do not depend on each other's output — no generator reads a filesystem artifact produced by another generator; every generator reads `TrustedFacts`. This is a hard rule enforced by the pure-function signature (§2.4) and by the WP5 acceptance criterion "does NOT depend on WP3."

WP7 (post-gen verifier) is the **fan-in**: it iterates over the union of `contributes_rows` from all successful generators, feeds them through Phase-2A's Comparison Core, and attaches results. WP7 is single-threaded and single-implementation regardless of how many generators are enabled.

Diagram:

```
WP2 TrustedFacts ─┬─► WP3 DT      ──┐
                  ├─► WP4 codec   ──┤
                  ├─► WP5 machine ──┼─► WP7 Post-Gen ─► WP8 Renderer
                  └─► WP6 audioreach ┘
```

Practical consequence: WP3–WP6 can be reviewed and merged in any order (or in parallel). WP7 blocks on all four, but only on their *type contracts* — a stub WP4 that always returns `GeneratorSkipped` unblocks WP7's development.

### 3.11 Why WP0.5 (`.gitignore`) is separate from WP10

Two reasons:

1. **Ordering.** WP3 introduces the first commit that writes to `generated/<run_id>/` when its tests run. If `.gitignore` doesn't include `generated/` by then, a green WP3 test run leaves untracked files the reviewer must clean before landing WP3. Landing `.gitignore` in WP0.5 (before WP3) eliminates that friction.
2. **Diff purity.** Bundling `.gitignore` into WP10 mixes a one-line config change with a several-hundred-line runner + `main.py` diff. Separating it lets the reviewer sign off on the config change in one glance and focus on WP10's substance separately.

### Commit boundary summary

| # | Scope | Green gate |
|---|---|---|
| 1 | WP0.5 `.gitignore generated/` | `git check-ignore generated/foo` = 0; Phase-2A tests green |
| 2 | WP1a model | `test_generation_model` |
| 3 | WP1b config | `test_generation_config` |
| 4 | WP2 fact projector | `test_generation_facts` (regression anchor) + Phase-2A tests still green |
| 5 | WP3 DT generator | `test_generation_dt` (gate-open + gate-closed cases) |
| 6 | WP4 codec generator | `test_generation_codec` (gate-open + gate-closed cases) |
| 7 | WP5 machine driver | `test_generation_machine` (gate-open + gate-closed cases) |
| 8 | WP6 audioreach | `test_generation_audioreach` (gate-open + gate-closed cases) |
| 9 | WP7 post-gen verifier | `test_generation_post_gen` (all three cases) |
| 10 | WP8 renderer | `test_generation_render` + Phase-2A byte-identical regression |
| 11 | WP9 spec update (v1.0 → v1.1) | reviewer sign-off; `grep -c IMPLEMENTED docs/PHASE2B_SPECIFICATION.md` ≥ 8 |
| 12 | WP10 runner + main.py wiring | end-to-end smoke: `--generate` off → byte-identical to Phase-2A; `--generate` on → artifacts appear; missing-snapshot → exit 2 |

No WP under Phase-2B touches Phase-2A source (except WP10's `main.py` additive wiring, which is bounded by §3.9's policy + runtime test). This is a design invariant, not a coincidence.

---

## 4. Verification gates

Each generator declares a **gating expression** — a Boolean over Phase-2A rows. The runner evaluates the expression *before* calling the generator. **If any dependency is closed (warning, REVIEW_REQUIRED, DISAGREE_WITH_AUTHORITY), the generator is not called** and the run emits a `generator-skipped` row instead.

Rows evaluate as follows:

| Row state | Gating value |
|---|---|
| `MATCH` | OPEN |
| `PARTIAL_MATCH` (KB rule downgrade) | OPEN (see §4.4 for donor-residue known-bad handling) |
| `NOT_CROSS_CHECKABLE` with `coverage_gap_reason=authority_out_of_scope` | OPEN only for advisory rows (see §3.7; T4b is the only such row in scope) — otherwise CLOSED |
| `NOT_CROSS_CHECKABLE` (any other reason) | CLOSED |
| `REVIEW_REQUIRED` | CLOSED (except for advisory rows per §3.7, where the generator emits an in-artifact reviewer sentinel) |
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

### 4.4 PARTIAL_MATCH handling — where the `rule_id` goes, and known-bad exceptions

A Phase-2A row with verdict `PARTIAL_MATCH` carries a KB `rule_id` explaining why the match is partial (e.g. `t5.donor.firmware.sa8775p` says "donor DTSI residue references `sa8775p` firmware; the row matches the SoC family but not the exact firmware path").

**Where the citation lives.** Phase-2B does *not* emit a separate sidecar JSON per artifact. Instead, when a generator opens a gate on a `PARTIAL_MATCH` row, it emits a **header comment** at the top of the artifact bytes:

```
// PARTIAL_MATCH gate: T5.dts.firmware (rule_id=t5.donor.firmware.sa8775p)
//   The row matched on SoC family but a KB rule downgraded the verdict to
//   PARTIAL_MATCH; the reviewer must confirm the firmware path before this
//   artifact is merged.
```

The comment is machine-parseable (the `rule_id=…` token is stable) and human-readable. Post-gen verification (WP7) sees the same `rule_id` in the row's `contributes_rows` and echoes it in the report.

**Known-bad exception: donor residue.** Some `PARTIAL_MATCH` rows are **known-bad**, not "review-needed." Eliza's `T5.dts.firmware` with `rule_id=t5.donor.firmware.sa8775p` is such a case: the donor DTSI is a legacy Nord fragment whose firmware path is *known* to be wrong for Eliza (`sa8775p` is Nord's SoC, not Eliza's). Emitting a PARTIAL_MATCH-open DTS here would bake the donor bug into a generated artifact.

For known-bad `rule_id`s (enumerated in `orchestrator/generation/config.py::KNOWN_BAD_PARTIAL_MATCH_RULES`), the generator emits `GeneratorSkipped(reason=gating_row_partial_match_donor_residue)` instead of opening the gate. As of v1.0, `KNOWN_BAD_PARTIAL_MATCH_RULES = frozenset({"t5.donor.firmware.sa8775p"})`. Adding a rule to this set is a spec change (this section), not a config-only change — it changes the gate-open surface.

WP3's acceptance criteria include this exact case: Eliza `TrustedFacts` with `T5.dts.firmware=PARTIAL_MATCH, rule_id=t5.donor.firmware.sa8775p` → `GeneratorSkipped`, fixture-verified.

---

## 5. Human-in-the-loop contract

Phase-2B is **diagnostic-first, gating-second**, exactly like Phase-2A. The engine does not commit, does not send patches, does not build, does not flash. Every step that leaves the "diagnostic report" boundary requires an explicit human lever.

### 5.1 What the engine does autonomously

- Reads the Phase-2A snapshot (no new I/O).
- Runs generators whose gates are OPEN.
- Writes generated bytes to **an untracked directory** `generated/<run_id>/<artifact_class>/`. The `<run_id>` segment is injected orchestrator-side, not by the generator: the `do_onboard` write loop rewrites each artifact's `path_hint` into `generated/<run_id>/<stripped>` immediately before calling `write_artifact_bytes` (see `orchestrator/main.py:584`, `dest_hint` construction). Generators therefore emit run-agnostic path hints; the runner alone owns the per-run namespace. The path-guard rules that gate every write are specified in §5.4.
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

- The engine writes to `generated/<run_id>/` only. `generated/` is `.gitignore`'d (WP0.5).
- The engine never invokes `git` (nor any shell/`os.system`/`subprocess` targeting `git`). A test enforces this: `grep -r 'import subprocess\|os\.system\|git ' orchestrator/generation/` yields no matches outside of type stubs.
- The engine has no write access to any tracked kernel path from within `orchestrator/generation/`. The path-guard helper in `orchestrator/generation/config.py` (`PATH_GUARD_ROOT = "generated/"`) rejects any write path outside `PATH_GUARD_ROOT`; violation → `GeneratorSkipped(reason=path_guard_violation)` and exit 1 (WP10 acceptance criterion). The guard's acceptance check (`is_path_within_guard`, `config.py:219-263`) is deliberately suffix-agnostic: it normalizes the candidate path and requires the `generated/` prefix only, so the atomic-overwrite temp files used by the idempotency layer — sibling paths of the form `<dest>.tmp.<pid>` — pass through without special-casing. Their semantics are pinned in §5.6.

### 5.5 `--dry-run` semantics

`--dry-run` is the review lever that lets an operator preview what a `--generate` invocation *would* do without leaving any bytes on disk. It is not an approximation of generation and it is not a stubbed-out variant; it runs the full pipeline — collector, comparison, generators, post-verifier, renderer — and stops one line short of the filesystem. This lets a reviewer read the `## Generation` section and the four-value status column exactly as it will render in production, judge the outcome, and only then re-invoke without the flag.

**Design constraints.** The flag is bound by two invariants that must hold together, not one at a time:

- **C4 (side-effect-free).** No bytes are written under `generated/<run_id>/`. No directory is created. No temp file is left behind. `--dry-run` observed by `stat` and `find` is indistinguishable from a run that never happened, apart from the report on stdout.
- **Report fidelity.** The report the reviewer sees under `--dry-run` is the report they would have seen after a real run against the current disk state — same rows, same `path_hint` promises, same status column values (including "unchanged" when a dest already matches on disk, per §5.6).

These two constraints are not in tension by accident. Fidelity requires that the idempotency probe (§5.6) still run — it needs to compare the generator's bytes against whatever is already on disk so it can render "unchanged" honestly. Side-effect-freedom requires that once the probe has decided, the write step is skipped whether the decision was CREATE, OVERWRITE, or SKIP. Both are satisfied by making the probe read-only and by placing every filesystem-mutating operation behind a single gate.

**Implementation.** The `--generate` write loop in `orchestrator/main.py` funnels every mutating operation — `mkdir`, sibling-temp write, `Path.replace`, `st_mtime_ns` preservation — through one `if not dry_run:` branch at `orchestrator/main.py:629`. There is exactly one such gate; there is no second write path that could be reached under `--dry-run`. The idempotency probe that computes `art_hash` and (if the dest exists) `disk_hash` runs *before* this gate, and its outputs feed the status column regardless of `dry_run`. If the probe decides SKIP (hashes match), the status is "unchanged" and the gate is a no-op because there is nothing to write anyway. If the probe decides OVERWRITE or CREATE, the status is "updated" or "created" as it would be in production, and the gate skips the mutating operations; the status reflects what *would* happen, not what did.

**Test contract.** `--dry-run` correctness is asserted at three seams:

1. **Absence of bytes.** After `--generate --dry-run` completes, `generated/<run_id>/` either does not exist or contains no files from this run. The test walks the tree and asserts an empty file listing under the run's directory.
2. **Absence of temp siblings.** No `<dest>.tmp.<pid>` files remain from a partial atomic-overwrite attempt. This catches a class of bugs where the temp file is created before the gate is checked.
3. **Report parity with reality.** When a dest already exists and matches the generator's bytes, `--dry-run` renders status "unchanged" and `dest.stat().st_mtime_ns` is byte-identical before and after the invocation. This is the strongest observable that no write occurred and the probe's honesty is preserved.

The third assertion is the seam where `--dry-run` and idempotency (§5.6) intersect. It's what the WP11.3/WP11.4 test at `tests/test_wp11_idempotency.py::test_dry_run_reports_unchanged_when_dest_matches` locks in.

### 5.6 Idempotency contract

Re-running `--generate` against the same `run_id` must produce a deterministic outcome. The three legitimate outcomes are enumerated below; anything else — a partial write, a lost temp file, a spurious re-emission that moves `st_mtime` without changing bytes — is a bug. The engine does not carry an on-disk manifest, does not maintain a `.hashes.json` sidecar, and does not persist any idempotency state between invocations. The disk itself is the source of truth. On each run, the engine hashes the generator's bytes, hashes whatever is on disk at the dest path (if anything), and decides in one of three ways.

**The three-branch decision (D3).**

- **CREATE** — dest does not exist. Write the generator's bytes via the atomic overwrite protocol (below). Status column: **"created"**.
- **SKIP** — dest exists and its bytes hash-match the generator's bytes. Do not open the file for writing, do not touch `st_mtime`, do not create a temp sibling. Status column: **"unchanged"**.
- **OVERWRITE** — dest exists and its bytes do not hash-match. Write the generator's bytes via the atomic overwrite protocol (below). Status column: **"updated"**.

The fourth possible cell — **"—"** (em-dash) — is reserved for artifacts where the write loop did not run at all, such as `GeneratorSkipped` rows or the WP8 render-fallback path at `orchestrator/main.py:1412`. This yields a four-value status column: `"created" | "updated" | "unchanged" | "—"`.

**Hash source rule.** Two hashes participate in the decision, and they are semantically distinct operations that must not be confused:

- `art_hash = sha256(artifact.bytes_)` reads the generator's in-memory bytes only (`orchestrator/main.py:599`).
- `disk_hash = sha256(dest.read_bytes())` reads the pre-existing dest file's bytes — never a file this run just wrote (`orchestrator/main.py:603`).

These two hashes are compared. If they match, no write occurs. The prohibition is against computing `art_hash` by writing the bytes then re-reading them: that pattern defeats the short-circuit because the write happens before the probe can prevent it. It is not a prohibition on reading a pre-existing file — that read is *the* signal the probe uses to decide.

**Atomicity.** OVERWRITE is atomic-ish on the same POSIX filesystem: the engine writes to a sibling temp path (`<dest>.tmp.<pid>`) in the same directory as `dest`, then calls `Path.replace()` to rename the temp over `dest`. A crash mid-write leaves a partial temp file — never a truncated dest. The temp sibling is chosen deliberately (not `/tmp/`) so the rename is a same-filesystem operation that POSIX guarantees to be atomic; a cross-filesystem rename would degrade to a copy and could be observed mid-flight. The path-guard permits the temp path because its check is suffix-agnostic (§5.4).

**Mtime preservation.** On the SKIP branch, `dest.stat().st_mtime_ns` must not change. This is not cosmetic: `st_mtime_ns` is the strongest observable that the file was not touched, short of tracing the syscall stream. Naive `st_mtime` (whole seconds) is too coarse — a rewrite within the same second would pass a naive check even though the disk was mutated. `st_mtime_ns` catches a rewrite to single-nanosecond granularity on filesystems that support it (Linux ext4/xfs default), and reduces cleanly to `st_mtime` behavior on filesystems that don't. Downstream tooling that depends on "did the artifact change" answers correctly under this discipline; tooling that reads the whole file every run also answers correctly, but pays a needless I/O cost the SKIP branch is designed to eliminate.

**Report addendum.** The `## Generation` section's per-artifact status table carries the four-value column defined above. The renderer applies a fallback of `art.get("generation_status", "—")` at `orchestrator/main.py:1412` so that rows for which the write loop did not assign a status render as em-dash rather than as `KeyError` or empty string. This is how `GeneratorSkipped` rows and any WP8-synthetic dicts render safely without a status.

**Test contract.** Idempotency correctness is asserted at five seams in `tests/test_wp11_idempotency.py`:

1. Second `--generate` on same `run_id` short-circuits and preserves `st_mtime_ns` (SKIP branch).
2. Divergent dest bytes trigger atomic-rename overwrite; no `<dest>.tmp.<pid>` sibling survives (OVERWRITE branch, atomicity).
3. Clean-tree `--generate` produces bytes via the CREATE branch and renders status "created" (CREATE branch).
4. Two-run status column rendering: first run "created", second run "unchanged" (report addendum × SKIP branch).
5. `--dry-run` against a matching dest renders "unchanged" with frozen `st_mtime_ns` and no temp siblings (§5.5 × SKIP branch).

Together these lock the C3 (idempotent re-run) and C4 (dry-run side-effect-freedom) design constraints against every reachable branch of the decision.

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

**Not blocking WP1a–WP3.** Blocks WP4 acceptance criteria.

### 7.2 Pre-runtime machine driver validation (WP5)

**Question.** Absent a build and absent hardware, what can the engine assert about a generated machine driver beyond "the file matches the DT declarations"? Options include (a) a static C parse + symbol reference check against a pinned kernel source tree; (b) a syntax-only lint (no semantic check); (c) nothing — leave everything to the reviewer.

**Why it matters.** A generated machine driver that references a nonexistent `snd_soc_dai_link` field, an undefined codec `.of_match_table` entry, or a mistyped `dai_fmt` constant will fail at build. Catching those pre-runtime keeps the human from bouncing on a build error the engine could have flagged.

**Not blocking WP1a–WP4, WP6.** Blocks WP5 acceptance criteria depth. WP5 can ship with option (c) and be strengthened later.

### 7.3 AudioReach topology XML source of truth (WP6)

**Question.** AudioReach graphs have both an XML schema (upstream QC releases, GPR bindings) and DTS-embedded fragments (used in some SoCs' `.dtsi`). Which is Phase-2B's target artifact for WP6 — the XML, the DTS binding, or both? And which reference schema anchors the KB (upstream Qualcomm public specs, internal Qualcomm audio DSP repo, kernel `Documentation/`)?

**Why it matters.** WP6's post-gen verification (T3.lpass_macro_instance / T3.dsp_subsystem_instance) is straightforward — count named blocks in the emitted artifact and compare against the Phase-2A rows. But *what* to emit, and against *which* schema, is undecided. Emitting the wrong shape means a downstream tool (GPR runtime, audioreach loader) rejects the file even when the counts are right.

**Not blocking WP1a–WP5, WP7–WP10.** Blocks WP6 acceptance criteria.

> **RESOLVED (v1.1, WP6 commit 8196ff3 — Case-B anchor decision):**
>
> - WP6 emits an **inline DTSI fragment** (Case-B: DTS-embedded, not standalone XML). This matches the pattern in Nord's own `.dtsi` sources and avoids a dependency on the GPR XML loader.
> - The reference schema is the LPASS GPR DT binding in `kernel Documentation/devicetree/bindings/sound/qcom,lpass-audioreach.yaml` (upstream anchor).
> - Fixture: `nord_audioreach_expected.dtsi` (inline DTSI, not XML). Post-gen verification counts `T3.lpass_macro_instance` and `T3.dsp_subsystem_instance` named blocks within the DTSI fragment.
> - This question is closed. No further design decision required for WP6.

---

## 8. Test fixtures — directory shape, contents, golden-run protocol

Every WP under Phase-2B has at least one fixture-based test. This section documents the fixture directory shape, the naming convention, the golden-run protocol for regenerating fixtures, and the CI guardrails.

### 8.1 Directory shape

```
tests/fixtures/phase2b/
├── nord_trusted_facts.json                          (WP2 — regression anchor)
├── nord_dt_expected.dtsi                            (WP3 gate-open)
├── eliza_lpass_disagree_skipped_expected.json       (WP3/WP6 gate-closed; renamed at WP6)
├── nord_codec_stub_expected.c                       (WP4 gate-open; Nord: adau1979 + pcm1681)
├── nord_codec_disagree_skipped_expected.json        (WP4 gate-closed)
├── nord_machine_driver_expected.dtsi                (WP5 gate-open; DTSI not C)
├── nord_machine_driver_disagree_skipped_expected.json  (WP5 gate-closed)
├── nord_audioreach_expected.dtsi                    (WP6 gate-open; inline DTSI not XML)
├── eliza_skipped_expected.json                      (WP6 gate-closed Eliza T3 disagree)
├── wp7_gate_consistency_expected.json               (WP7 gate-closed loop)
├── wp8_render_all_success_expected.md               (WP8 renderer — all success)
├── wp8_render_gate_closed_expected.md               (WP8 renderer — gate closed)
├── wp8_render_no_fixmes_expected.md                 (WP8 renderer — no FIXMEs)
├── wp8_render_null_guard_expected.md                (WP8 renderer — null guard, empty file)
└── pre_wp10_baseline_report.md                      (WP10 regression anchor per §3.9)
```

> **Note (v1.1):** Several spec-listed names were not committed — see IMPLEMENTED notes on the relevant WPs. The renderer (`_render_generation_section`) lives in `orchestrator/main.py`, not in a separate `render.py`. WP8 fixtures are `.md` not `.txt`. WP7 fixture is `wp7_gate_consistency_expected.json` not `post_gen_disagree_expected.json`.

### 8.2 Fixture chain (regression traceability)

Every fixture derives from a stable ancestor:

- `tests/fixtures/phase2a/expected_rows.json` — Phase-2A frozen output, six rows, already anchored by Phase-2A tests.
- → `tests/fixtures/phase2b/nord_trusted_facts.json` — WP2 projection of the above. WP2 acceptance criterion (e) enforces byte-identity.
- → `tests/fixtures/phase2b/nord_dt_expected.dtsi`, `nord_machine_driver_expected.dtsi`, `nord_audioreach_expected.dtsi`, `nord_codec_stub_expected.c` — WP3/WP4/WP5/WP6 outputs derived from the `nord_trusted_facts.json` above.
- → `tests/fixtures/phase2b/wp8_render_all_success_expected.md` (and sibling WP8 fixtures) — WP8 renderer output derived from WP3–WP7 outputs above.

If Phase-2A `expected_rows.json` changes, WP2's fixture regenerates; if WP2's fixture changes, all downstream fixtures may need regeneration. The chain is single-rooted, which makes drift attribution easy.

### 8.3 Golden-run protocol

The generation script `tests/regenerate/regenerate_phase2b_fixtures.py` (created in WP2 alongside the fixture) drives all regenerations. Invocation:

```
python3 tests/regenerate/regenerate_phase2b_fixtures.py --wp <2|3|4|5|6|7|8|10>
```

Each `--wp` flag regenerates that WP's fixtures and no others. `--wp 2` cascades: because WP2's output changes the fact projection, the script prints (but does not run) the follow-up commands for WP3–WP8. The reviewer approves each regeneration explicitly.

### 8.4 CI guardrail: `--regenerate-fixtures` is not a test path

`tests/regenerate/` is a **separate directory** from `tests/`. The pytest / test runner discovers only `tests/` (not `tests/regenerate/`). CI does not run the regeneration script. A test in `tests/test_generation_facts.py` asserts: "the `--regenerate-fixtures` flag is not accepted by any test module." This prevents accidental fixture drift via a `--regenerate` flag in a normal test invocation.

The regeneration script writes only to `tests/fixtures/phase2b/`; a path-guard rejects writes elsewhere. Regeneration produces a git diff the reviewer inspects before committing — no automated "regenerate then commit" path exists.

### 8.5 Fixture format discipline

- **JSON fixtures** — sorted keys, 2-space indent, trailing newline. Matches Phase-2A convention.
- **`.dtsi` / `.c` / `.xml` fixtures** — LF line endings, no BOM, no trailing whitespace on any line. `git config --local core.autocrlf false` in the repo README ensures cross-platform stability.
- **Byte-identity assertion** — every fixture test reads the fixture bytes, runs the generator on the corresponding `TrustedFacts`, and asserts byte-equality (not string-equality after normalization). Whitespace, ordering, and encoding differences are all failures.

---

*Planning and specification only. No code. No commits. No Phase-2A modifications. WP-C cardinality lane at `28f2f07` remains untouched. All values referenced are traced to Phase-1B/1C/2A evidence artifacts already in-repo; no value is fabricated.*
