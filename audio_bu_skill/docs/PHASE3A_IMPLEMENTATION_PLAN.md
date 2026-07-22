# Phase-3A Implementation Plan — Audio BU Skill

**Status:** PROPOSED (planning only — no code written)
**Author:** onboarding session 2026-07-22
**Governing docs:** PHASE3_ARCHITECTURE.md (scope authority), WP_F_DESIGN_REVISION.md
(coverage semantics), PHASE3_KNOWN_GAPS.md (deferred-gap ledger)
**HEAD at planning time:** d8edec2

---

## §1 — GOAL and Success Criterion (North Star)

### North-Star GOAL (verbatim, non-negotiable)

> The skill must generate machine_driver + dt_scaffolding + audioreach_topology +
> codec_stub artifacts for Audio BU targets, **including FRESH targets that have no
> prior reference patches.** This is the north star. Every WP in Phase-3A must be
> evaluated against whether it moves this goal forward.

### Success criterion (measurable, binary)

Running:

    python -m orchestrator.main --onboard <target> --generate

on a target **must** produce **all four** artifact directories populated under
`artifacts/<run_id>/generated/` (the on-disk contract in
`orchestrator/codegen/artifacts.py:11-16`), where each of the four generation
skills emits either:

- a **GeneratedArtifact** (a non-empty ChangeSet with proposal-quality content +
  FIXMEs), OR
- an **explicit OBSERVED_PROPOSAL / GeneratorSkipped record with a named,
  cited reason** — never a silent absence.

"Populated" = the four generation lanes each ran to a *recorded verdict*. It does
**not** require a green build.

### Anti-goal (explicit scope fence)

Phase-3A success is **NOT** upstream-ready patches. Proposal-quality artifacts that
carry FIXMEs, `needs_review` markers, and OBSERVED_* advisory verdicts are the
target. Compilation, `dtc` validation, and patch-series human approval (gate #3)
remain deferred to Phase-3B+.

### The gating chain the GOAL must break (confirmed by reading code)

Three of the four generators are **hard-gated on open cross-verify rows**, and the
fourth is not — which is exactly why only one artifact is produced today:

| Generator | File | Gate | Source-fact it needs |
|---|---|---|---|
| machine_driver | `orchestrator/generation/machine_driver.py:217-226` | open `T1.gpio.i2s.*` | `gc["audio_topology"]["pinmux"]` |
| codec_stub | `orchestrator/generation/codec_stub.py:214-222` | open `T4a.qup.*` | `gc["audio_topology"]["endpoints"]` |
| dt_scaffolding | `orchestrator/generation/dt_scaffolding.py:205-243` | open `T5.dts.firmware` | DTS files under `targets/<t>/dts/` |
| audioreach_topology | *(no is_open gate)* | — | (produces unconditionally) |

`is_open()` (`orchestrator/generation/model.py:213-237`) is **fail-closed**: a row is
OPEN iff it exists AND `warning=False` AND `verdict ∈ {MATCH, PARTIAL_MATCH}`. A
**missing** row is not open. And rows go missing at the *source* step, before any
MCP authority is consulted: `_crossverify_source_facts` (main.py:1099-1113) reads
`pinmux`/`endpoints`/DTS, and `track_t1`/`track_t4a` short-circuit to
`[]` when the source is empty (`orchestrator/reasoning/crossverify.py:416-417,
1816-1817`). `track_t5` does **not** short-circuit — it emits a
`NOT_CROSS_CHECKABLE` row on empty DTS; see G-3A.7 in `PHASE3_KNOWN_GAPS.md`
for the corrected T5 mechanism.

**Empirically confirmed this session (the load-bearing finding):**

    Nord  profile.json: audio_topology.pinmux=None, .endpoints=None, no targets/nord-iq10/dts/
    Eliza profile.json: audio_topology.pinmux=None, .endpoints=None, no targets/eliza/dts/

Both targets have an **empty source side**. This is why runs 21 and 22 *both*
produced 3× GeneratorSkipped + 1× GeneratedArtifact regardless of MCP state
(run-21 MCP up, run-22 MCP down). **The blocker is the empty profile source, not
the MCP authority.** This is the gap WP-SRC closes.

---

## §2 — Goal → WP Traceability

| WP | Moves north star? | How (or why not) |
|---|---|---|
| **WP-D** (fact family catalog + requirements) | **Indirect / infra** | Defines *what* facts exist. Committed (`1afec36`), inert. Does not populate any source; does not unlock a generator. |
| **WP-E** (advisory provenance registry) | **Indirect / infra** | Records *where facts came from*. Committed (`4af8bdd`), inert. Advisory-only by architecture (§3, §10) — cannot flip a gate. |
| **WP-F** (family coverage engine) | **No (diagnostic)** | Computes OBSERVED_COMPLETE/GAP against ESM denominator. Tells you the source is empty; does not fill it. |
| **WP-G** (coverage report render) | **No (diagnostic)** | Renders the `## Fact Coverage` section. Reporting only. |
| **WP-SRC** (source ingestion) | **YES — the only WP that does** | Populates `audio_topology.pinmux` / `.endpoints` and stages `targets/<t>/dts/` so T1/T4a/T5 emit rows → the 3 gated generators unlock. **Directly satisfies §1 success criterion.** |
| **WP-MCP-BANNER** (degradation banner) | **Guards the goal** | Makes silent MCP-down degradation loud (closes G-3A.6). Prevents a "success" that is actually a silent skip. |

**Critical honesty gate satisfied:** WP-D/E/F/G are diagnostic/advisory infrastructure
that, by their own architecture, **cannot** unlock the three skipped generators.
Per the standing constraint ("don't smuggle diagnostic infrastructure into Phase-3A
as a substitute for real capability"), **WP-SRC is mandatory** and is designed at
full depth in §4.

---

## §3 — Sequencing Decision

### Option A — Ship WP-D→WP-G, defer source ingestion
- Delivers the coverage/observation infrastructure.
- **GOAL NOT MET.** Nord stays **1/4**, Eliza stays **1/4**. The skill still cannot
  generate 4 artifacts on any target, fresh or otherwise.
- The coverage report would faithfully report OBSERVED_GAP for the empty families —
  a correct diagnosis of a capability we chose not to build.

### Option B — Insert WP-SRC into Phase-3A ✅ RECOMMENDED
- Sequence: **WP-SRC → WP-MCP-BANNER → WP-F → WP-G** (WP-D, WP-E already committed).
- **GOAL MET.** WP-SRC unlocks T1/T4a/T5; the 3 gated generators run. Nord and Eliza
  move toward **4/4** (or emit explicit OBSERVED_PROPOSAL per family with a cited
  reason — never a silent skip).
- WP-F/WP-G then *measure and report* the newly-populated coverage, which is their
  correct role once there is something to measure.

### Recommendation

**Option B.** Rationale: the north star is artifact generation on fresh targets.
WP-D/E/F/G do not move it (§2, proven by the run-21/22 diagnostic). Shipping Phase-3A
without WP-SRC would deliver a Phase where, by the plan's own success criterion, the
goal is definitionally unreachable. WP-SRC is well-scoped: it feeds an *existing*,
already-wired plumbing path (`_crossverify_source_facts` + `_load_dts_files`,
main.py:1099-1137) — no new pipeline seam is required.

---

## §4 — Per-WP Breakdown

> STATUS line counts are from working-tree inspection on 2026-07-22.
> Effort is in DAYS, calibrated to ~1–2 atomic WPs/day.

---

### WP-D — Fact Family Catalog & Requirements Schema

**NORTH-STAR JUSTIFICATION:** Indirect. Defines the fact vocabulary WP-F/WP-SRC name
their families against. Does not itself populate a source or unlock a generator.

**OBJECTIVE:** (already achieved) A declarative catalog of audio fact families +
per-family freshness policy + a requirements schema.

**STATUS: COMMITTED & DONE** at `1afec36 feat(wp-d): fact family catalog and
requirements schema`. Inert-by-design (not imported by main.py or
target_onboarding_runner.py). Files:
- `orchestrator/fact_requirements/schema.py` (394)
- `orchestrator/fact_requirements/catalog/audio.py` (419)
- `orchestrator/fact_requirements/loader.py` (130)
- `orchestrator/fact_requirements/fact_freshness.yaml` (71)
- `orchestrator/fact_requirements/__init__.py` (48)
- `orchestrator/fact_requirements/catalog/generic.py` (17)
- test: `tests/test_fact_requirements_catalog.py` (479)

**FILES — CREATED:** (done). **MODIFIED:** none remaining. **NOT TOUCHED:**
main.py, generators.

**INPUTS:** none (static catalog). **OUTPUTS:** `FactFamily`/`FactRequirement`
objects consumed by WP-F.

**TESTS:** T-D-* — all present and green in `test_fact_requirements_catalog.py`.

**EXIT CRITERIA:** ☑ committed ☑ tests green ☑ inert. **All met.**

**NORTH-STAR EXIT CHECK:** n/a (infra). Artifact count unchanged: Nord 1/4.

**RISKS:** R-D-1 catalog drift vs. real families → mitigated by WP-F consuming it as
the single source of family names.

**MANUAL VERIFICATION:** confirm `1afec36` present on HEAD ancestry.

**ATOMIC COMMIT SEQUENCE:** (already landed) — no new commits.

**ESTIMATED EFFORT:** **0 days remaining** (done).

**PREREQUISITES:** none.

---

### WP-E — Advisory Provenance Registry

**NORTH-STAR JUSTIFICATION:** Indirect. Records fact provenance/authority_class.
Advisory-only (§3, §10) — architecturally cannot flip a gate.

**STATUS: COMMITTED & DONE** at `4af8bdd feat(fact-registry): implement advisory
provenance registry` (spec finalized `3cd5533`). Inert-by-design. Files:
- `orchestrator/fact_registry/models.py` (616), `store.py` (795),
  `source_refs.py` (337), `review.py` (210), `hash.py` (186),
  `locking.py` (151), `constants.py` (139), `__init__.py` (106), `errors.py` (48)
- tests: `test_fact_registry_store.py` (546), `_models.py` (264),
  `_review.py` (133), `_source_refs.py` (161), `_import_isolation.py` (82)

**FILES — CREATED:** (done). **NOT TOUCHED:** main.py, generators.

**INPUTS:** SourceRef tagged union (IPCATLive/IPCATCached/Kernel/Schematic/ACDB/Manual).
**OUTPUTS:** registry store consumed by WP-F confidence axis.

**TESTS:** present, green (~1186 test LOC).

**EXIT CRITERIA:** ☑ committed ☑ tests green ☑ inert. **All met.**

**NORTH-STAR EXIT CHECK:** n/a. Nord 1/4 unchanged.

**RISKS:** R-E-1 registry unused if WP-F never wires it → mitigated by making
"WP-F consumes WP-E" a WP-F exit criterion.

**ESTIMATED EFFORT:** **0 days remaining** (done).

**PREREQUISITES:** none.

---

### WP-SRC — Source-Fact Ingestion  ⭐ (NEW — the north-star WP)

**NORTH-STAR JUSTIFICATION:** **Direct and primary.** This is the *only* WP that
populates the profile source side. Empty `pinmux`/`endpoints`/DTS is the confirmed
root cause of 3/4 generators skipping (§1, empirically shown for both Nord and
Eliza). Filling them makes `track_t1`/`track_t4a`/`track_t5` emit rows → the
is_open() gates in machine_driver.py:217, codec_stub.py:214, dt_scaffolding.py:205
can open → all four artifacts generate. **Without WP-SRC the §1 success criterion is
definitionally unreachable.**

**OBJECTIVE:** Populate, per target, the three source-fact channels the existing
cross-verify plumbing already reads:
1. `profile["audio_topology"]["pinmux"]` — I2S/TDM pin group facts (T1 source)
2. `profile["audio_topology"]["endpoints"]` — SoC-side QUP/DAI endpoint facts (T4a source)
3. `targets/<target>/dts/*.dts|*.dtsi` — staged DTS for T5 firmware/compatible facts

so that `_crossverify_source_facts` (main.py:1099-1113) and `_load_dts_files`
(main.py:1118-1137) return non-empty structures. **No new pipeline seam** — WP-SRC
feeds channels that are already wired into `_run_crossverify` (main.py:1140-1178).

**STATUS: NOT STARTED.** Confirmed absent this session:
- Nord `profile.json`: `audio_topology` = `{}` after load; `pinmux`/`endpoints`=None.
- Eliza `profile.json`: same.
- No `targets/nord-iq10/dts/` and no `targets/eliza/dts/` directory exists.
- `orchestrator/codegen/` engine scaffolding is UNTRACKED and inert
  (`NullEngine` default; `ClaudeCodeEngine`/`QGenieEngine` raise NotImplementedError —
  engine.py:60-70). WP-SRC does **not** activate an engine; it feeds *source facts*
  upstream of the generators, which already contain their own (non-NullEngine)
  proposal logic gated on is_open rows.

**FILES — CREATED:**
- `orchestrator/source_ingest/__init__.py` — package seam
- `orchestrator/source_ingest/pinmux.py` — derive T1 pinmux facts from
  resolved DT / IPCAT GPIO map into the `pinmux` schema `track_t1` expects
- `orchestrator/source_ingest/endpoints.py` — derive T4a endpoint facts (QUP/DAI)
  into the `endpoints` schema `track_t4a` expects
- `orchestrator/source_ingest/dts_stage.py` — copy/resolve the applied target DTS
  into `targets/<t>/dts/` (the dir `_load_dts_files` reads)
- `orchestrator/source_ingest/models.py` — PinmuxFact / EndpointFact dataclasses
  (to_dict, deterministic; mirror codegen/models.py style)
- tests: `tests/test_source_ingest_pinmux.py`,
  `tests/test_source_ingest_endpoints.py`, `tests/test_source_ingest_dts.py`,
  `tests/test_source_ingest_integration.py`
- fixtures: `tests/fixtures/source_ingest/` (a fresh-target synthetic profile with
  known pinmux/endpoints + a minimal staged DTS)

**FILES — MODIFIED:**
- `orchestrator/main.py` — call the ingestion pass to populate
  `gc["audio_topology"]["pinmux"]`/`["endpoints"]` and stage DTS **before**
  `_run_crossverify` (single insertion, immediately prior to main.py:1140). Guarded:
  if a source channel cannot be derived, write an explicit `provenance:
  SOURCE_UNRESOLVED` marker (not silent empty) so WP-F/WP-G can report OBSERVED_GAP
  with a cited reason.
- `targets/nord-iq10/profile.json`, `targets/eliza/profile.json` — populated
  pinmux/endpoints (or a SOURCE_UNRESOLVED marker where genuinely underivable).

**FILES — NOT TOUCHED:** the generators themselves (machine_driver/codec_stub/
dt_scaffolding — their gate logic is correct; WP-SRC feeds their inputs), WP-D/WP-E
committed packages, the codegen engine seam.

**INPUTS:** resolved chip (`phase1b_resolution.json`), applied kernel DTS
(`linux-nord/.../<target>.dts[i]`), IPCAT GPIO/QUP evidence under
`targets/<t>/evidence/ipcat/`.

**OUTPUTS:** non-empty `pinmux` dict, non-empty `endpoints` dict, ≥1 file under
`targets/<t>/dts/`, each carrying a provenance tag (DERIVED_FROM_DT / DERIVED_FROM_IPCAT
/ SOURCE_UNRESOLVED).

**TESTS (T-SRC-* naming):**
- **T-SRC-1** pinmux ingestion from a DT with I2S8 pin group → non-empty pinmux with
  expected keys; `track_t1` then returns ≥1 row (integration).
- **T-SRC-2** endpoints ingestion from QUP evidence → non-empty endpoints;
  `track_t4a` returns ≥1 row.
- **T-SRC-3** DTS staging copies applied DTS into `targets/<t>/dts/`;
  `_load_dts_files` returns ≥1 entry; `track_t5` firmware row present.
- **T-SRC-4** underivable source → `SOURCE_UNRESOLVED` marker written, NOT a silent
  empty; downstream verdict is OBSERVED_GAP with a cited reason (never a crash).
- **T-SRC-5** determinism: two runs on identical inputs produce byte-identical
  pinmux/endpoints (sorted keys).
- **T-SRC-6** end-to-end on fresh-target fixture: after ingestion, all three gates
  (T1.gpio.i2s.*, T4a.qup.*, T5.dts.firmware) are is_open()==True.
- **T-SRC-7** fresh target with genuinely no schematic/DT for one channel → 3/4 or
  2/4 with the missing channel emitting OBSERVED_PROPOSAL, proving the "fresh target,
  no prior patch" north-star path degrades explicitly, not silently.

**EXIT CRITERIA (boolean):**
- ☐ `pinmux` non-empty (or SOURCE_UNRESOLVED-marked) for Nord and Eliza
- ☐ `endpoints` non-empty (or marked) for Nord and Eliza
- ☐ `targets/<t>/dts/` populated for Nord and Eliza
- ☐ T-SRC-1…7 green
- ☐ Full pre-Phase-3A suite still green (§6)
- ☐ No generator gate code modified

**NORTH-STAR EXIT CHECK (measurable):** After WP-SRC, run
`--onboard nord-iq10 --generate` and `--onboard eliza --generate`. Scorecard MUST
move **Nord 1/4 → ≥3/4** (target 4/4) and **Eliza 1/4 → ≥3/4**, with any short of
4/4 accounted for by an explicit OBSERVED_PROPOSAL + cited reason. **If Nord stays
1/4 after WP-SRC, the source→gate causal model is wrong — STOP and re-diagnose.**

**RISKS:**
- **R-SRC-1** pinmux schema mismatch: the shape WP-SRC writes ≠ what `track_t1`
  parses → rows still empty. *Mitigation:* T-SRC-1 asserts row emission, not just
  non-empty dict; derive the exact schema by reading `track_t1` parsing before
  coding.
- **R-SRC-2** DTS staging duplicates the applied tree and drifts. *Mitigation:* stage
  by reference/copy with a provenance stamp recording source path + sha256; T5 treats
  it read-only.
- **R-SRC-3** ingestion masks a genuine gap by fabricating a plausible-but-wrong
  pinmux. *Mitigation:* SOURCE_UNRESOLVED marker + confidence tag; never invent —
  underivable is a GAP, not a guess. Aligns with WP-F anti-vacuity (T-F-DENOM).
- **R-SRC-4** fresh target has *no* DT at all (true greenfield) → all three channels
  UNRESOLVED. *Mitigation:* T-SRC-7 makes this an explicit OBSERVED_PROPOSAL path, not
  a failure; documents the honest Phase-3A ceiling for pure greenfield.

**MANUAL VERIFICATION CHECKPOINTS:**
1. After pinmux.py: eyeball Nord pinmux against `iq10-evk.dts` I2S8 pinctrl — do the
   pin numbers/functions match the DT?
2. After endpoints.py: confirm QUP/DAI endpoints match the resolved SA8797P QUP map.
3. After DTS staging: `diff` staged DTS vs. applied DTS — identical modulo the
   provenance header.
4. After integration: read `cross_verification.rows` in the Nord output — confirm
   T1/T4a/T5 rows now present and open.

**ATOMIC COMMIT SEQUENCE:**
1. `feat(source-ingest): pinmux + endpoint fact models`
2. `feat(source-ingest): derive T1 pinmux from resolved DT`
3. `feat(source-ingest): derive T4a endpoints from QUP evidence`
4. `feat(source-ingest): stage target DTS for T5`
5. `feat(source-ingest): wire ingestion into onboarding before crossverify`
6. `test(source-ingest): fresh-target integration + degradation coverage`
7. `chore(targets): populate Nord + Eliza source facts`

**ESTIMATED EFFORT:** **4–6 days** (largest WP: 4 derivation modules + wiring +
7 tests + 2 real-target population passes + manual DT cross-checks). Calibrated to
1–2 WPs/day but this is a multi-commit WP.

**PREREQUISITES:** none blocking (plumbing already exists). WP-F benefits from
running *after* WP-SRC so it has populated families to measure.

---

### WP-MCP-BANNER — MCP Degradation Banner (closes G-3A.6)

**NORTH-STAR JUSTIFICATION:** Guards the goal. Today `_run_crossverify` is wrapped in
a silent try/except (main.py:538-541), the collector `_call` swallows BaseException →
unavailable (crossverify_collector.py:173-185), and main.py:692 prints "wrote proposal
artifacts" unconditionally. A run with MCP down can *look* successful while silently
producing degraded output. A "4/4" that is actually "1/4 + 3 silent skips" would be a
false north-star claim. This WP makes degradation loud.

**OBJECTIVE:** Emit a visible, non-fatal `## MCP / Authority Status` banner
(EMPTY / DEGRADED / OK) whenever a cross-verify authority call fails or returns no
snapshot, and make the terminal summary reflect degraded state instead of the
unconditional success line.

**STATUS: NOT STARTED.**

**FILES — MODIFIED:** `orchestrator/main.py` (the 3 cited points: 538-541 wrap,
692 summary line, and the crossverify snapshot-provenance handoff);
`orchestrator/runners/crossverify_collector.py` (surface the unavailable reason
instead of only swallowing it — 173-185). **CREATED:** `tests/test_mcp_banner.py`.

**INPUTS:** snapshot provenance (already carried at main.py:~1174).
**OUTPUTS:** a banner block in `onboarding_report.md` + a truthful terminal summary.

**TESTS (T-MCP-* naming):**
- **T-MCP-1** MCP down → banner=DEGRADED, terminal summary does NOT claim clean success.
- **T-MCP-2** MCP up → banner=OK.
- **T-MCP-3** collector `_call` failure surfaces a named reason, not just "unavailable".
- **T-MCP-4** degraded run still exits 0 (advisory, non-fatal) but is *labeled*.

**EXIT CRITERIA:** ☐ banner renders in all 3 states ☐ no silent success line when
degraded ☐ T-MCP-1…4 green ☐ still non-fatal (exit 0).

**NORTH-STAR EXIT CHECK:** Artifact count itself unchanged by this WP, BUT it
prevents a *false* scorecard: after WP-MCP-BANNER a "3/4 skipped" run is
unmistakably labeled degraded. Guards the integrity of every other WP's north-star
check.

**RISKS:** R-MCP-1 over-fatal (turning advisory into a hard fail) → mitigation: keep
exit 0, banner only. R-MCP-2 banner noise on healthy runs → mitigation: OK state is
one line.

**MANUAL VERIFICATION:** run once with MCP reachable, once with it unreachable;
confirm the report and terminal differ honestly.

**ATOMIC COMMIT SEQUENCE:**
1. `fix(crossverify): surface authority-unavailable reason instead of swallowing`
2. `feat(report): MCP/authority status banner`
3. `fix(onboard): terminal summary reflects degraded crossverify`
4. `test(mcp-banner): degraded vs healthy vs empty`

**ESTIMATED EFFORT:** **1–2 days.**

**PREREQUISITES:** none. Best landed *before* WP-SRC so WP-SRC's north-star checks
are read against a truthful banner.

---

### WP-F — Family Coverage Engine

**NORTH-STAR JUSTIFICATION:** Diagnostic. Measures whether WP-SRC actually populated
families (OBSERVED_COMPLETE vs OBSERVED_GAP against the ESM denominator). Does not
generate; it *verifies the generation precondition* — valuable only once WP-SRC gives
it something to measure.

**OBJECTIVE:** Compute per-family coverage across the four axes (coverage, freshness,
confidence, conflict) + corroboration, against the ESM denominator, emitting
observation vocabulary only (never PASS/WARN/FAIL).

**STATUS: NOT STARTED.** `orchestrator/coverage/` does **not** exist. Fully specified
in PHASE3_ARCHITECTURE.md §8.

**FILES — CREATED:** `orchestrator/coverage/{engine,models,esm,freshness,conflict,
confidence}.py` + `tests/test_coverage_*.py` + `tests/fixtures/coverage/`.
**MODIFIED:** none (render is WP-G). **Consumes WP-E registry** (exit criterion).

**INPUTS:** WP-E registry store, WP-D catalog, `targets/<t>/expected_subjects.json`
(ESM). **OUTPUTS:** `FamilyCoverage` objects for WP-G.

**TESTS (reuse §8 T-F naming exactly):** T-F-DENOM, T-F-VACUOUS, T-F-ESM-MISSING,
T-F-DECLARED-EMPTY, T-F-SURPLUS, T-F-MISMATCH, T-F-CORROBORATED, T-F1…T-F11.

**EXIT CRITERIA:** ☐ all T-F* green ☐ consumes WP-E ☐ ESM denominator rule enforced
(null when |required|=0 or missing, never 100%) ☐ observation vocab only.

**NORTH-STAR EXIT CHECK:** After WP-SRC + WP-F, Nord's populated families report
OBSERVED_COMPLETE/PARTIAL (proving WP-SRC worked) and any still-empty family reports
OBSERVED_GAP with denominator provenance. Artifact count unchanged by WP-F itself.

**RISKS:** R-F-1 vacuous present/present=100% → mitigated by T-F-DENOM/T-F-VACUOUS.
R-F-2 collapsing 4 axes into one number → forbidden by design; T-F asserts axes stay
separate.

**MANUAL VERIFICATION:** review Nord coverage against the WP_F_DESIGN_REVISION §7
inspection gates; confirm the "Nord trap-case" denominator sign-off.

**ATOMIC COMMIT SEQUENCE:** per §8 —
1. `feat(coverage): models + ESM denominator`
2. `feat(coverage): freshness + confidence + conflict axes`
3. `feat(coverage): family coverage engine`
4. `test(coverage): anti-vacuity + axis + monotonicity suite`

**ESTIMATED EFFORT:** **3–4 days** (6 modules + the full T-F suite).

**PREREQUISITES:** WP-E (done). Best after WP-SRC (else it measures all-empty).

---

### WP-G — Coverage Report Render

**NORTH-STAR JUSTIFICATION:** Diagnostic/reporting. Surfaces WP-F results in the
onboarding report so a human can see the north-star scorecard per family. No
generation.

**OBJECTIVE:** Render `## Fact Coverage` immediately after `## IPCAT Coverage`
(position 9, per §7), plus the mandatory registry-provenance banner
(EMPTY / HAND_SEEDED / IPCAT_POPULATED) as a blocking gate for external sharing.

**STATUS: NOT STARTED.**

**FILES — CREATED:** `orchestrator/coverage/render.py` + `tests/test_coverage_render.py`.
**MODIFIED:** `orchestrator/main.py` — ONE insertion point after the `## IPCAT
Coverage` section.

**INPUTS:** WP-F `FamilyCoverage`. **OUTPUTS:** report section + provenance banner.

**TESTS (§8):** T-G1…T-G7, T-G-BANNER, T-G-VOCAB.

**EXIT CRITERIA:** ☐ section renders at position 9 ☐ banner blocks external share
when EMPTY/HAND_SEEDED ☐ observation-vocab only (T-G-VOCAB) ☐ all T-G* green.

**NORTH-STAR EXIT CHECK:** The report now shows a per-family scorecard; the human can
read "Nord 4/4 generated, coverage OBSERVED_COMPLETE for pinmux/endpoints/firmware"
at a glance. Artifact count unchanged by WP-G.

**RISKS:** R-G-1 banner not blocking → T-G-BANNER asserts the gate. R-G-2 vocab leak
(PASS/FAIL) → T-G-VOCAB.

**MANUAL VERIFICATION:** open Nord + Eliza reports; confirm section placement, banner
state, vocabulary.

**ATOMIC COMMIT SEQUENCE:** per §8 —
1. `feat(coverage): report renderer + provenance banner`
2. `feat(report): insert Fact Coverage section after IPCAT Coverage`
3. `test(coverage): render + banner + vocab`

**ESTIMATED EFFORT:** **1–2 days.**

**PREREQUISITES:** WP-F.

---

## §5 — Progress-Tracking Mechanism

### In-doc checklist (updated as WPs land)
```
[ ] WP-D    committed 1afec36 (verify on ancestry)   — DONE
[ ] WP-E    committed 4af8bdd (verify on ancestry)   — DONE
[ ] WP-MCP-BANNER  (guards scorecard integrity)
[ ] WP-SRC  (north-star unlocker)
[ ] WP-F    (coverage measurement)
[ ] WP-G    (coverage render)
```

### North-Star Scorecard (re-measured after EACH WP)
| After WP | Nord | Eliza | Fresh-target hypothetical |
|---|---|---|---|
| baseline (HEAD d8edec2) | 1/4 | 1/4 | 0/4 |
| WP-MCP-BANNER | 1/4 (now *honestly* labeled) | 1/4 | 0/4 |
| **WP-SRC** | **→ ≥3/4 (target 4/4)** | **→ ≥3/4** | **≥2/4 proposal + FIXMEs** |
| WP-F | unchanged (measured) | unchanged | unchanged |
| WP-G | unchanged (rendered) | unchanged | unchanged |

The scorecard is the single source of truth for "are we moving the north star."

### Manual review gates
- Each WP's MANUAL VERIFICATION CHECKPOINTS must be signed off before its final commit.
- The §8 pre-merge non-negotiables (denominator-provenance sign-off, banner renders,
  vocab-only, Nord trap-case) gate WP-F/WP-G.

### Explicit STOP condition
> **If WP-SRC lands and the Nord scorecard is still 1/4, PAUSE.** The source→gate
> causal model would be falsified and the plan is wrong. Do not proceed to WP-F/WP-G
> layering diagnostics on top of a broken unlocker. Re-diagnose the gate that did not
> open (read the specific `is_open()` row it produced).
> Corollary: if any 3 WPs land and Nord is still 1/4, the plan's central thesis
> (empty source is the blocker) is wrong — halt and re-plan.

---

## §6 — Cross-WP Integration Testing

**How WP-SRC + WP-MCP-BANNER + WP-F + WP-G test together:**
- **T-SRC-6/7** is the integration keystone: fresh-target fixture → ingestion → all
  three gates open → 4 artifacts. This is the north-star end-to-end.
- **T-F** consumes the registry populated by a WP-SRC run (not synthetic-only
  fixtures) in at least one integration test, proving the source→registry→coverage
  chain.
- **T-G** renders a report from a real WP-SRC+WP-F Nord run in one integration test.
- **T-MCP** runs the full onboard twice (MCP up/down) asserting the banner + scorecard
  differ honestly.

**Pre-Phase-3A regression suite that MUST stay green after every WP:**
- The full existing suite (WP-D catalog tests, WP-E registry tests ~1186 LOC,
  cardinality/crossverify tests, ipcat_acquire provenance tests). Run the whole
  `tests/` directory; zero new failures is a hard gate on every commit.

**Manual smoke after each WP:** `--onboard nord-iq10` AND `--onboard eliza` (both,
every WP) — Eliza is the fresh-target proxy and must not regress while Nord advances.

---

## §7 — Documentation to Write During Implementation

| WP | Docs to update / create |
|---|---|
| WP-SRC | **NEW** `docs/WP_SRC_DESIGN.md` (source-fact schemas, provenance markers, degradation semantics); update PHASE3_ARCHITECTURE.md §9 to move source-ingestion from out-of-scope → in-scope with rationale; update PHASE3_KNOWN_GAPS.md G-3A.7 status. |
| WP-MCP-BANNER | Update PHASE3_KNOWN_GAPS.md G-3A.6 → closed; note banner semantics in PHASE3_ARCHITECTURE.md §7 report design. |
| WP-F | **NEW** `docs/WP_F_DESIGN.md` if the DESIGN_REVISION is not itself the design of record; else cite it. Update §7 report-position note. |
| WP-G | Update PHASE3_ARCHITECTURE.md §7 with the final rendered banner states. |
| every WP | Append a `docs/session_notes/` entry per working session. |

---

## §8 — Success Criteria for Shipping Phase-3A

Phase-3A ships when ALL hold:
1. **Nord: 4/4** artifacts generated, OR any family short of 4 emits an explicit
   OBSERVED_PROPOSAL with a cited reason — **never a silent skip.**
2. **Eliza: 4/4** (or explicit OBSERVED_PROPOSAL per family).
3. **Fresh-target hypothetical (T-SRC-7 fixture): ≥2/4** proposal-quality with FIXMEs,
   remaining families explicitly OBSERVED_PROPOSAL — proving the "no prior patch" path
   degrades honestly.
4. All **WP_F_DESIGN_REVISION §7 inspection gates** satisfied.
5. All **PHASE3_ARCHITECTURE §10 pre-merge non-negotiables** (denominator-provenance
   sign-off, banner renders, vocab-only, Nord trap-case review) satisfied.
6. MCP degradation is **loud** (WP-MCP-BANNER) — no run can silently claim success.
7. Full regression suite green.
8. **Two-week evidence window**: Nord + Eliza re-onboarded across the window with
   stable scorecards before opening Phase-3B.

---

## §9 — Post-Phase-3A Next Moves

- **Path B (validator-after-human):** scope a human-approval gate (#3) that runs `dtc`
  / compile checks on the WP-SRC-produced proposals before they are called
  patch-ready. Prereq: WP-SRC artifacts stable across the two-week window; a defined
  "reviewer accepts proposal" record (reuse WP-E ReviewRecord). Phase-3B.
- **Path C (full greenfield bootstrap):** generating artifacts for a target with *no*
  DT and *no* schematic (pure spec-in). Deferred. **Re-eval trigger:** when a real
  Audio BU target arrives with only a datasheet + no DT, and T-SRC-7's OBSERVED_PROPOSAL
  ceiling becomes the actual customer ask.
- **Wire the codegen engine seam:** replace `NullEngine` with `ClaudeCodeEngine`/
  `QGenieEngine` (engine.py:55-70, currently NotImplementedError) — only once WP-SRC
  proves the source-fact inputs are reliable. Deferred to Phase-3B.
