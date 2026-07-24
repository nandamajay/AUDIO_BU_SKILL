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

### Scope correction — what Phase-3A actually proves vs. the "fresh targets" clause (G-3A.13)

The north-star sentence above bundles two claims that Phase-3A does **not** deliver
together. Be precise about which one this phase closes:

- **Phase-3A proves the PIPELINE is target-generic.** Ingestion → cross-verify →
  gate-open is driven by the target's `profile` / `TrustedFacts` and carries no
  baked target identity. A fresh target with real source populates real facts,
  real facts open real gates, and the gates fire the generators. That mechanism is
  what the scorecard flip (§5) measures, and it is genuinely target-agnostic.

- **The four GENERATORS currently emit Nord/SA8797P identity** (`G-3A.13`,
  `PHASE3_KNOWN_GAPS.md`). `machine_driver` bakes `qcom,nord-iq10-sndcard` /
  `IQ10-EVK` / `i2s8_active` as module constants; `codec_stub` bakes the
  `_NORD_CODECS` table; `dt_scaffolding` and `audioreach_topology` bake the
  SA8775P ADSP compatible/firmware and Nord-specific comment/FIXME blocks. None of
  these are derived from the target profile. **The "fresh targets" clause therefore
  requires a separate generalization WP (parameterize every emitted identity
  literal from the profile), which is DEFERRED — it is not part of Phase-3A.**

- **The Phase-3A scorecard counts whether a generator PRODUCES an artifact, NOT
  whether the artifact is target-correct.** A hypothetical "3/4 on Eliza" means
  three generators *ran to a GeneratedArtifact verdict* — the emitted files would
  still carry **Nord** identity strings (`qcom,nord-iq10-sndcard`, `IQ10-EVK`, the
  `_NORD_CODECS` table, `qcom,sa8775p-adsp-pas`) until `G-3A.13` closes. A green
  scorecard on a non-Nord target is a **pipeline** result, never proof of
  target-correct output.

**One-line reconciliation:** Phase-3A closes "the pipeline can reach and fire all
four generators for any target with real source." It does **not** close "the
generators emit that target's identity." The latter is `G-3A.13`, deferred to a
generalization WP.

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
| **WP-SRC-A1** (pinmux ingestion contract) | **No alone — inert without A2** | Provides `derive_pinmux_from_dt` + Design B `SOURCE_UNRESOLVED` sentinel + wiring in `_build_audio_topology`. On real Nord/Eliza `analysis["dt"]` is empty (G-3A.9), so this branch always emits the sentinel string until A2 lands. Coupled with WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2. |
| **WP-SRC-A2** (DT plumbing: `--kernel-source` → `analysis["dt"]`) | **No alone — half-open with A1** | Loads the kernel DT into `analysis["dt"]` so A1's derivation actually returns a `list[PinmuxFact]` on real targets. Together A1+A2 open *one half* of the machine_driver gate (`T1.gpio.i2s.*`); the other half (`T4a.qup.*`) requires WP-SRC-B1+B2 → scorecard stays 1/4 until the B pair lands. Closes G-3A.9. |
| **WP-SRC-B1** (endpoint ingestion contract/T4a + separator reconcile) | **No alone — inert without B2** | Ships `derive_endpoints_from_ipcat` + `EndpointFact` + wiring in `_build_audio_topology`, AND reconciles the `T4a.qup:`/`T4a.qup.` producer↔gate separator (crossverify.py:1743-1754 vs machine_driver.py:229 / codec_stub.py:214). Proven on the B1 fixture; on real Nord/Eliza endpoints resolve to `SOURCE_UNRESOLVED` (G-3A.11) until B2 lands. Scorecard stays 1/4. |
| **WP-SRC-B2** (IPCAT QUP enrichment: `buses` + `chipio_get_qups.json` → track_t4a) | **Completes the 1/4 → 3/4 flip (A2 + B3 already landed)** | Rewires `derive_endpoints_from_ipcat` onto real IPCAT QUP data so B1's wiring reaches `track_t4a` with populated endpoints on real targets (closes G-3A.11). Opens the `T4a.qup.*` half. The `T4b.codec.*` half is already open post-B3 (`_t4b_row` emits `codec.<part>` — G-3A.12 CLOSED `9aa07ff`), and the `T1.gpio.i2s.*` half is open post-A2. So `T4a.qup.*` is the **only** remaining REQUIRE-OPEN gate on both `machine_driver` and `codec_stub`. **WP-SRC-B2 alone completes the 1/4 → 3/4 flip** — there is no fourth hidden gate (audit in G-3A.12 Status). |
| **WP-SRC-B3** (T4b producer/gate subject reconcile — G-3A.12) | **✅ CLOSED 2026-07-24 (`fcf4268` red, `9aa07ff` green)** | Reconciled producer-side: `_t4b_row` now emits `subject = f"codec.{_t4b_norm_part(codec)}"` (strip `vendor,`, lowercase — rule b), matching the `T4b.codec.` prefix both generators scan. Real-Nord verified: subjects resolve to `codec.pcm1681` / `codec.adau1979`, T4b advisory half of both gates opens. Scorecard stayed 1/4 (T4a still needs B2). See `docs/PHASE3_KNOWN_GAPS.md` G-3A.12. |
| **WP-SRC-C** (DTS/T5 + producer/gate reconcile) | **YES — independently** | Stages `targets/<t>/dts/` AND fixes the `track_t5` producer so it can emit MATCH/PARTIAL_MATCH for `dts.firmware` (currently emits only DISAGREE + NCC — see G-3A.7). Flips `dt_scaffolding` 0→1 (scorecard → 4/4). Requires a `WP_SRC_C_DESIGN_NOTE.md` blocking first commit — not pure ingestion. |
| **WP-MCP-BANNER** (degradation banner) | **Guards the goal** | Makes silent MCP-down degradation loud (closes G-3A.6). Prevents a "success" that is actually a silent skip. |

**Critical honesty gate satisfied:** WP-D/E/F/G are diagnostic/advisory infrastructure
that, by their own architecture, **cannot** unlock the three skipped generators.
Per the standing constraint ("don't smuggle diagnostic infrastructure into Phase-3A
as a substitute for real capability"), **WP-SRC-A1 + WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2
+ WP-SRC-B3 + WP-SRC-C are all mandatory** (A1+A2+B1+B2 are a coupled quadruple that,
together with the T4b subject reconcile WP-SRC-B3 / G-3A.12 — now ✅ CLOSED `9aa07ff` —
move 2/4; A1 and A2 are inert without each other, B1 and B2 are inert without each
other, and the A1/A2 pair is inert on the scorecard without the B1/B2 pair. B3 removed
the T4b fail-closed blocker: both generators previously fail-closed on the unreachable
`T4b.codec.*` gate, which B3 reconciled. With A2 + B3 landed, **WP-SRC-B2 alone completes
the A-side flip**; C is independent and moves the final 1/4). Each sub-WP is designed
at full depth in §4.

---

## §3 — Sequencing Decision

### Option A — Ship WP-D→WP-G, defer WP-SRC-A1/-A2/-B1/-B2/-C
- Delivers the coverage/observation infrastructure.
- **GOAL NOT MET.** Nord stays **1/4**, Eliza stays **1/4**. The skill still cannot
  generate 4 artifacts on any target, fresh or otherwise.
- The coverage report would faithfully report OBSERVED_GAP for the empty families —
  a correct diagnosis of a capability we chose not to build.

### Option B — Insert WP-SRC-A1/-A2/-B1/-B2/-C into Phase-3A ✅ RECOMMENDED
- Sequence: **WP-MCP-BANNER → WP-SRC-A1 → WP-SRC-A2 → WP-SRC-B1 → WP-SRC-B2 → WP-SRC-B3 → WP-SRC-C → WP-F → WP-G**
  (WP-D, WP-E already committed).
- **GOAL MET.** WP-SRC-A1 lands the pinmux ingestion contract; WP-SRC-A2 plumbs the
  DT so A1 actually returns facts on real targets; together A1+A2 open the T1 half
  of `machine_driver`; WP-SRC-B1 lands the endpoint ingestion contract + separator
  reconcile (fixture-proven); WP-SRC-B2 plumbs the real IPCAT QUP data so B1 reaches
  `track_t4a` on real targets, opening the T4a half; **WP-SRC-B3 reconciled the T4b
  producer/gate subject mismatch (G-3A.12, ✅ CLOSED 2026-07-24 `9aa07ff`) so both
  generators stopped failing-closed on the `T4b.codec.*` gate — with A2 + B3 landed,
  WP-SRC-B2 alone flips `machine_driver` and `codec_stub`**; WP-SRC-C flips `dt_scaffolding`. Nord and Eliza
  move toward **4/4**
  (or emit explicit OBSERVED_PROPOSAL per family with a cited reason — never a
  silent skip).
- WP-F/WP-G then *measure and report* the newly-populated coverage, which is their
  correct role once there is something to measure.

### Recommendation

**Option B.** Rationale: the north star is artifact generation on fresh targets.
WP-D/E/F/G do not move it (§2, proven by the run-21/22 diagnostic). Shipping Phase-3A
without WP-SRC-A1/-A2/-B1/-B2/-C would deliver a Phase where, by the plan's own
success criterion, the goal is definitionally unreachable. Sub-WPs A1/A2 and B1/B2
feed the *existing*, already-wired plumbing path (`_crossverify_source_facts` +
`_load_dts_files`, main.py:1099-1137) — no new pipeline seam is required; WP-SRC-C
additionally reconciles the T5 producer/gate mismatch documented in G-3A.7 (design
committed via `WP_SRC_C_DESIGN_NOTE.md` before code).

---

## §4 — Per-WP Breakdown

> STATUS line counts are from working-tree inspection on 2026-07-22.
> Effort is in DAYS, calibrated honestly: every WP-SRC sub-WP carries a
> design-decision component, so none is a sub-day change.

> **AMENDMENT (2026-07-22, post-empirical):** The original single WP-SRC
> block below assumed populating pinmux/endpoints/DTS unlocks all three
> gated generators. That claim is **empirically falsified** (see §4a). WP-SRC
> is split into independently-reviewable sub-WPs — originally four
> (WP-SRC-A1 / -A2 / -B / -C) — each with its own design decision and STOP.
> WP-D, WP-E, WP-MCP-BANNER, WP-F, WP-G are unchanged and retain their original
> blocks.
>
> **AMENDMENT (2026-07-23):** WP-SRC-B is further split into **WP-SRC-B1**
> (endpoint ingestion contract + T4a separator reconcile — fixture-proven, inert
> on real targets) and **WP-SRC-B2** (real IPCAT QUP data plumbing —
> `buses` + `chipio_get_qups.json` → `track_t4a`), mirroring the WP-SRC-A1/-A2
> pattern. The B1/B2 split was forced by **G-3A.11** (`derive_endpoints_from_ipcat`
> reads a fixture-only key path that no real onboard run populates). The former
> single WP-SRC-B is now the **coupled pair B1+B2**; A1+A2+B1+B2 is a coupled
> **quadruple** (§4a-2). The T4b subject reconcile **WP-SRC-B3 / G-3A.12** was a
> co-prerequisite; it is now ✅ CLOSED 2026-07-24 (`9aa07ff`), leaving B2 as the sole
> remaining gate to the flip.

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

## §4a — Empirical grounding for the WP-SRC split

The original single WP-SRC assumed "populate the three source channels → three
gates open → 3/4 generators unlock." **Execution falsifies the clean
one-channel-per-generator mapping.** Three producer↔gate facts, each confirmed by
running the live producers (see `tests/test_g3a7_source_gate.py`,
`tests/test_g3a7_t5_dts_probe.py`, both committed and green):

1. **T1 (pinmux → machine_driver):** `track_t1` builds each row's subject as
   `f"{name} (GPIO {pin})"` (crossverify.py:458-459), where `name` defaults to
   `"?"`. A bare `{pin, function}` source entry yields subject `? (GPIO 147)` →
   key `T1.? (GPIO 147)`, which does **not** match the gate prefix
   `T1.gpio.i2s.` (machine_driver.py:217). **The source entry MUST carry a
   `name` in the `gpio.i2s.*` namespace** or the row is emitted but the gate
   stays closed. Confirmed by `test_t1_named_source_opens_machine_driver_gate`
   (opens) vs `test_t1_task_literal_input_does_not_open_gate` (does not).

2. **T4a (endpoints → codec_stub AND machine_driver):** `_t4a_subject`
   (crossverify.py:1743-1754) builds `f"{kind}:{label}"` with a **COLON** →
   `T4a.qup:QUPv3_0_SE_5`. Both gates scan the prefix `T4a.qup.` with a **DOT**
   (codec_stub.py:214, machine_driver.py:229).
   `"T4a.qup:...".startswith("T4a.qup.")` is `False` → a populated endpoint
   produces a **MATCH row that still cannot open the gate**. The frozen fixture
   `tests/fixtures/phase2b/nord_trusted_facts.json` uses the DOT form only because
   it was hand-authored to the gate, not emitted by the producer (admitted in the
   codec_stub.py:204-205 comment). **This is a producer↔gate separator defect
   that WP-SRC-B1 must reconcile — populating endpoints alone is necessary but not
   sufficient.** Confirmed by
   `test_t4a_populated_source_produces_row_but_gate_is_unsatisfiable`.

3. **T5 (DTS → dt_scaffolding):** `track_t5` (crossverify.py:1312+) emits **only**
   `DISAGREE_WITH_AUTHORITY` and `NOT_CROSS_CHECKABLE` verdicts — it **never**
   emits `MATCH`/`PARTIAL_MATCH`, and the only `dts.firmware`/`dts.compatible`
   subject it can produce is a donor-LEAK row (verdict DISAGREE, warning=True).
   Since `is_open()` (model.py:213-237) requires verdict ∈ {MATCH,
   PARTIAL_MATCH} AND warning=False, **the dt_scaffolding gate
   `is_open("T5","dts.firmware")` is architecturally unsatisfiable from the live
   producer regardless of DTS content.** Staging DTS is necessary but **not
   sufficient**; the T5 producer or the gate must change. Confirmed by
   `test_dt_scaffolding_gate_unsatisfiable_from_live_t5`.

4. **T4b (codec advisory → machine_driver AND codec_stub) — RESOLVED by
   WP-SRC-B3 (`9aa07ff`):** Pre-B3, `_t4b_row` (crossverify.py) built each row's
   subject as `f"{codec}<->{controller}"` → key `T4b.ti,pcm1681<->i2s8`. **Both
   generators hard-gate on the literal prefix `T4b.codec.`** (machine_driver.py:240,
   codec_stub.py:230): `"T4b.ti,pcm1681<->i2s8".startswith("T4b.codec.")` was
   `False`, so pre-B3 the live producer could **never** open the T4b gate. That was
   a producer↔gate subject-prefix defect (G-3A.12). **WP-SRC-B3 reconciled it
   producer-side** — `_t4b_row` now emits `subject = f"codec.{_t4b_norm_part(codec)}"`
   (`codec.pcm1681` / `codec.adau1979` on real Nord), which the `T4b.codec.` scan
   matches. The T4b advisory half of **both** generators now opens on real codec
   values; the blocker is **RESOLVED**, not pending. See
   `docs/PHASE3_KNOWN_GAPS.md` G-3A.12 (CLOSED 2026-07-24).

**Consequence for sequencing (the correction to the literal "one sub-WP flips one
generator" premise):**

| Sub-WP | Channel | Opens | Flips a generator *alone*? |
|---|---|---|---|
| WP-SRC-A1 | pinmux (T1) — sentinel + wiring | `T1.gpio.i2s.*` half of machine_driver *once WP-SRC-A2 populates `analysis["dt"]`* | **No** — machine_driver also gates on `T4a.qup.*`, AND on real targets A1's wiring is inert until A2 lands |
| WP-SRC-A2 | DT plumbing (`--kernel-source` → `analysis["dt"]`) | makes WP-SRC-A1's wiring effective on real targets | **No** — depends on WP-SRC-A1 to consume its output |
| WP-SRC-B1 | endpoint ingestion contract (T4a) + separator reconcile — fixture-proven | `T4a.qup.*` on the B1 fixture only | **No** — inert on real targets (endpoints = `SOURCE_UNRESOLVED`, **G-3A.11**); needs WP-SRC-B2 for real data |
| WP-SRC-B2 | real IPCAT QUP data (`buses` + `chipio_get_qups.json`) → track_t4a | makes WP-SRC-B1's wiring effective on real targets; opens the `T4a.qup.*` half | **Completes the A-side flip** — with A2 (T1) + B3 (T4b) already landed, `T4a.qup.*` is the only remaining REQUIRE-OPEN gate on both generators, so B2 alone flips machine_driver + codec_stub |
| WP-SRC-B3 | T4b producer/gate subject reconcile (`_t4b_row` → `codec.<part>` ↔ `T4b.codec.` scan) | opens the `T4b.codec.*` gate both generators hard-require (G-3A.12) | **✅ CLOSED 2026-07-24 (`9aa07ff`)** — landed; the T4b half of both gates is open on real codec values |
| WP-SRC-C | DTS (T5) + producer/gate fix | `T5.dts.firmware` | **Yes** — dt_scaffolding 0→1 (but requires a producer change, not just staging) |

So **WP-SRC-A1 + WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2 are a coupled quadruple, and the
T4b subject reconcile (WP-SRC-B3 / G-3A.12) — now ✅ CLOSED `9aa07ff` — was a hard
prerequisite gating their scorecard credit.** Pre-B3, the quadruple moved **zero**
generators (both `machine_driver` and `codec_stub` fail-closed on the unreachable
`T4b.codec.*` gate). B3 reconciled that gate, so the quadruple now moves **two**
generators at once (machine_driver + codec_stub). The A1/A2 pair closes the T1
(pinmux) half; the B1/B2 pair closes the T4a (endpoints) half. Within each pair, the
first member is the contract/wiring (inert on real targets) and the second is the real-
data plumbing: A1 alone is inert on real targets (no DT plumbing), A2 alone has nothing
to feed; **B1 alone is inert on real targets (endpoints resolve to
`SOURCE_UNRESOLVED`, G-3A.11), B2 alone has no contract to feed.** machine_driver
needs BOTH halves (T1 *and* T4a) open plus the T4b.codec.* gate (now open post-B3);
codec_stub needs the T4a half (B1+B2) plus the same T4b.codec.* gate. **With A2 (T1)
and B3 (T4b) already landed, WP-SRC-B2 alone completes the A-side flip** — T4a is the
last remaining REQUIRE-OPEN gate. WP-SRC-C independently moves the third generator.
`audioreach_topology` is ungated and already produces (the standing 1/4). **T4b (codec
advisory) is now satisfiable from the live `_t4b_row` producer: post-B3 it emits
`codec.<part>`, which the `T4b.codec.` prefix both generators scan matches (G-3A.12
RESOLVED).** T2 (no-DISAGREE) is satisfiable and is not a blocker; this split does not
touch it.

---

### WP-SRC-A1 — Pinmux Source Ingestion (T1, sentinel + wiring only)  ⭐

**NORTH-STAR JUSTIFICATION:** Opens the `T1.gpio.i2s.*` half of the machine_driver
gate **once DT plumbing lands** (G-3A.9 / WP-SRC-A2 — see below). **Does not flip
a generator alone,** for two independent reasons: (i) machine_driver also needs
`T4a.qup.*` from WP-SRC-B1+B2, and (ii) nothing currently populates `analysis["dt"]`
in the real runner path, so the WP-SRC-A1 wiring is inert on real targets until
WP-SRC-A2 lands. Its scorecard contribution is realized jointly with WP-SRC-B1+B2
**and** WP-SRC-A2. It is sequenced first because pinmux derivation is the lower-
risk half and its schema constraint (the required `name`) is already pinned by
test.

**OBJECTIVE:** Ship the derivation function (`derive_pinmux_from_dt`), the
`SOURCE_UNRESOLVED` sentinel (Design B — bare-singleton, identity-checked), the
JSON-boundary helper (`sentinel_to_json_literal`), and the wiring in
`target_onboarding_runner._build_audio_topology` that routes derived facts (or the
sentinel) into `profile["audio_topology"]["pinmux"]`. On the WP-SRC-A2 fixture DT
this fills `pinmux` with entries carrying a `gpio.i2s.*` name (per §4a-1) so that
`track_t1` emits rows keyed under `T1.gpio.i2s.` once WP-SRC-A2 populates the DT
on real targets.

**STATUS: IN PROGRESS.** Commit 1 landed (ebe3757). Commits C (models Design B),
D (wiring Design B + JSON boundary), and E (docs) are ready to ship.

**FILES — CREATED:**
- `orchestrator/source_ingest/__init__.py`
- `orchestrator/source_ingest/models.py` — `SOURCE_UNRESOLVED` singleton (Design B,
  bare object) + `sentinel_to_json_literal` JSON-boundary helper.
- `orchestrator/source_ingest/pinmux.py` — `derive_pinmux_from_dt` + `PinmuxFact`.
- `tests/test_source_ingest_pinmux.py` — T-SRC-A-1..5.

**FILES — MODIFIED:**
- `orchestrator/runners/target_onboarding_runner.py` — `_build_audio_topology`
  reads `analysis.get("dt")`, calls `derive_pinmux_from_dt`, writes either a real
  list of pinmux dicts OR the literal string `"SOURCE_UNRESOLVED"` (via
  `sentinel_to_json_literal` at the JSON boundary) into `topology["pinmux"]`.
- `orchestrator/main.py` — **NO EDIT** (Design B removes the need; the string form
  of the sentinel is truthy-but-not-list and the existing `t1 = topology.get(...)
  or audio_pins` short-circuit falls through naturally to the `audio_pins`
  fallback).

**FILES — NOT TOUCHED:** machine_driver.py gate logic; codegen engine seam;
kernel-DT reader (G-3A.9 / WP-SRC-A2 scope).

**TESTS (T-SRC-A-*):**
- **T-SRC-A-1** pinmux ingestion from a DT with the I2S8 pin group → non-empty
  pinmux whose entries carry a `gpio.i2s.*` name.
- **T-SRC-A-2** integration: after ingestion, `track_t1` returns ≥1 row keyed under
  `T1.gpio.i2s.` and `facts.is_open("T1", subject)==True` (fixture-driven).
- **T-SRC-A-3** underivable pinmux → `SOURCE_UNRESOLVED` identity check
  (`result is SOURCE_UNRESOLVED`), not silent empty.
- **T-SRC-A-4** determinism on the degradation fixture: two runs → byte-identical
  pinmux.
- **T-SRC-A-5** integration: end-to-end runner path seeds fixture `analysis["dt"]`,
  proves the wiring calls `derive_pinmux_from_dt`, and the list branch reaches
  `topology["pinmux"]` as pinmux dicts.

**EXIT CRITERIA (boolean):**
- ☐ `pinmux` non-empty on the fixture DT; `"SOURCE_UNRESOLVED"` string on real Nord
  (until WP-SRC-A2 lands, this is the expected shape on real targets)
- ☐ T-SRC-A-1…5 green
- ☐ `track_t1` opens `T1.gpio.i2s.*` on the fixture profile (integration proof)
- ☐ Full suite still green; no generator gate code modified

**NORTH-STAR EXIT CHECK:** After WP-SRC-A1 alone, the scorecard **stays 1/4** —
this is expected and correct: (a) machine_driver still lacks `T4a.qup.*`; (b) DT
plumbing (G-3A.9 / WP-SRC-A2) is missing, so `topology["pinmux"]` on real Nord
lands as the literal string `"SOURCE_UNRESOLVED"`, not a list. The measurable
proof for A1 is that T-SRC-A-1..5 pass and the JSON boundary is honest, not a
scorecard delta. **Do not treat 1/4-after-A1 as a STOP trigger** (see §5a rule 2
guard-clause).

**RISKS:**
- **R-SRC-A-1** the derived pinmux omits the `name` (§4a-1) → row emitted but gate
  closed. *Mitigation:* T-SRC-A-2 asserts gate-open, not just non-empty dict.
- **R-SRC-A-2** fabricating a plausible-but-wrong pin group. *Mitigation:*
  `SOURCE_UNRESOLVED` + manual DT cross-check (below); never invent.

**MANUAL VERIFICATION CHECKPOINT:** on the fixture DT, eyeball derived pinmux
against the seeded I2S8 pinctrl group — pin numbers/functions/name must match.
Real-target manual DT cross-check is deferred to WP-SRC-A2.

**ATOMIC COMMIT SEQUENCE:**
1. `feat(source-ingest): pinmux fact model + derivation` — LANDED (ebe3757)
2. `feat(source-ingest): SOURCE_UNRESOLVED singleton (Design B)` — Commit C
3. `feat(source-ingest): wire pinmux into audio_topology at JSON boundary` — Commit D
4. `docs(phase3): G-3A.9 DT plumbing gap + WP-SRC-A1/A2 split` — Commit E

**ESTIMATED EFFORT:** **3–4 days** for the whole A1 body (already ~2 days spent).

**PREREQUISITES:** none blocking. **Coupled with WP-SRC-B1+B2 for scorecard effect,
AND with WP-SRC-A2 for real-target effect.**

---

### WP-SRC-A2 — DT Plumbing (kernel-source → analysis.dt)

**NORTH-STAR JUSTIFICATION:** WP-SRC-A1 ships the ingestion contract but not the
producer for its input. Nothing in the runner path currently reads the kernel DT
tree at `--kernel-source` into `analysis["dt"]`, so the WP-SRC-A1 wiring is inert
on real targets. WP-SRC-A2 closes that plumbing so `derive_pinmux_from_dt` sees a
real pinctrl subtree and can emit facts (not the sentinel) on Nord/Eliza. **Does
not flip a generator alone** — it makes WP-SRC-A1's wiring effective; the joint
scorecard move requires WP-SRC-B1+B2 on top of A1+A2.

**OBJECTIVE:** Walk the `--kernel-source` tree for the target's `.dts` / `.dtsi`
files, parse the pinctrl subtree into the dict shape `derive_pinmux_from_dt`
consumes (`{"pinctrl": {"<group>": {"function": "...", "pins": [...]}, ...}}`),
and populate `analysis["dt"]` before `_build_audio_topology` runs. Reuse the
existing DTS reader that `_crossverify_source_facts.t5` already walks under
`targets/<t>/dts/` where possible.

**STATUS: ✅ CLOSED 2026-07-22.** Discovered as G-3A.9 during WP-SRC-A1
close-out verification (2026-07-22); closed the same day by the atomic
commit sequence below. Real Nord `--onboard` (run-31) confirms
`profile.audio_topology.pinmux` transitions from the literal
`"SOURCE_UNRESOLVED"` string to a list of `PinmuxFact` dicts in the
`gpio.i2s.*` namespace; cross-verify rows expanded **11 → 20**,
confirming the `T1.gpio.i2s.*` gate now has source-side facts. **T1
side architecturally solved.** T4a side still open — see WP-SRC-B1+B2.

**FILES — CREATED / MODIFIED:**
- `orchestrator/source_ingest/dt_reader.py` (NEW) — DT-tree reader
  (`read_dt_pinctrl`).
- `orchestrator/source_ingest/__init__.py` (MODIFIED) — re-export
  `read_dt_pinctrl`.
- `orchestrator/runners/target_onboarding_runner.py` (MODIFIED) —
  import `read_dt_pinctrl`; populate `analysis["dt"]` after the
  runner produces `analysis`; relax `_build_audio_topology` signature
  so `pm` / `power_model_hint` / `pin_crosschecks` are keyword-only
  with `None` defaults (T-SRC-A2-2 exercises only the
  `analysis["dt"]` → pinmux path).
- `tests/test_source_ingest_dt_reader.py` (NEW) — T-SRC-A2-1..4
  contract, integration, missing-source, determinism tests.

**TESTS (T-SRC-A2-*):**
- **T-SRC-A2-1** unit test on a captured `.dtsi` fixture with an I2S8 pinctrl
  group → parsed dict has the expected shape.
- **T-SRC-A2-2** integration: `_build_audio_topology` on real Nord kernel source
  populates `topology["pinmux"]` with a non-empty list (not the sentinel string).
- **T-SRC-A2-3** underivable / missing DT tree → `analysis["dt"]={}`; combined
  with T-SRC-A-3 this yields `topology["pinmux"]="SOURCE_UNRESOLVED"` honestly.

**EXIT CRITERIA (boolean):**
- ☐ Real Nord `topology["pinmux"]` is a non-empty list of pinmux dicts (not the
  sentinel string).
- ☐ T-SRC-A2-1..3 green.
- ☐ `track_t1` opens `T1.gpio.i2s.*` on the **real** Nord profile.
- ☐ Full suite still green.

**NORTH-STAR EXIT CHECK:** After WP-SRC-A1 + WP-SRC-A2 alone, the scorecard
**still stays 1/4** (machine_driver still needs `T4a.qup.*` from WP-SRC-B1+B2).
A1+A2 is the "T1 half open" milestone. WP-SRC-B3 (G-3A.12) is now ✅ CLOSED `9aa07ff`
(T4b half already open); with A2 + B3 landed, **WP-SRC-B2 alone completes the joint
move to 3/4** — `T4a.qup.*` is the last remaining REQUIRE-OPEN gate.

**RISKS:**
- **R-SRC-A2-1** DT parsing pulls in a heavy library or misparses vendor
  extensions. *Mitigation:* start with a minimum viable dts-python reader on the
  pinctrl subtree only; scope down to the fields `derive_pinmux_from_dt` reads.
- **R-SRC-A2-2** silent shape mismatch (parser returns a valid dict that doesn't
  match `derive_pinmux_from_dt`'s expected keys). *Mitigation:* T-SRC-A2-1 asserts
  exact shape; regression fixture from Nord kernel source.

**ATOMIC COMMIT SEQUENCE:**
  1. `29bf385` — test(wp-src-a2): red baseline
  2. `04bb164` — feat(wp-src-a2): kernel-DT reader (A2-1/3/4 green)
  3. `cedb3f6` — feat(wp-src-a2): wire read_dt_pinctrl into
     _build_audio_topology (A2-2 green)

**ESTIMATED EFFORT:** **2–4 days** (reader + wiring + 3 tests + regression
fixture capture from a real kernel tree).

**PREREQUISITES:** WP-SRC-A1 landed (which produces the ingestion contract this
plumbing feeds).

---

### WP-SRC-B1 — Endpoint Ingestion Contract + T4a Separator Reconcile (T4a, fixture wiring)  ⭐

**NORTH-STAR JUSTIFICATION:** Ships the endpoint ingestion *contract*
(`derive_endpoints_from_ipcat` + `EndpointFact` + `_build_audio_topology` wiring)
and reconciles the producer↔gate separator, **proven on the B1 fixture.**
Populating endpoints makes `track_t4a` emit a MATCH row, but §4a-2 proves that row
keys as `T4a.qup:…` (colon) while both gates scan `T4a.qup.` (dot) — so this WP
also reconciles the separator. **Does not flip a generator alone, and is inert on
real targets:** nothing in the real runner path populates
`analysis["ipcat"]["qup_controllers"]`, so on real Nord/Eliza
`derive_endpoints_from_ipcat` returns `SOURCE_UNRESOLVED` and the endpoints land as
the literal string (**G-3A.11**). The real-data producer is **WP-SRC-B2**. B1 is to
endpoints what WP-SRC-A1 is to pinmux: the contract, inert until its plumbing lands.
**WP-SRC-A1 + WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2 jointly flip machine_driver 0→1 AND
codec_stub 0→1** on real targets. WP-SRC-B3 (the T4b subject reconcile, G-3A.12) was a
co-prerequisite; it is now ✅ CLOSED 2026-07-24 (`9aa07ff`) — the `T4b.codec.*` gate is
open, and with A2 already landed, **WP-SRC-B2 alone completes the flip** (T4a.qup.* is
the sole remaining gate).

**OBJECTIVE:** (1) Ship `derive_endpoints_from_ipcat` + `EndpointFact` + the wiring
in `_build_audio_topology` that routes derived endpoints (or the sentinel) into
`profile["audio_topology"]["endpoints"]`; (2) reconcile the `_t4a_subject`
colon/gate-dot mismatch so a populated endpoint's row keys under the gate prefix
`T4a.qup.`. On the B1 fixture (`_qup_populated_analysis`) this proves both the
contract and the reconcile end-to-end; on real targets the sentinel branch fires
until WP-SRC-B2 populates the source.

**STATUS: IN PROGRESS (fixture contract).** Nord/Eliza real endpoints resolve to
`SOURCE_UNRESOLVED` this session (**G-3A.11** — the real-data gap, deferred to
WP-SRC-B2); the separator defect confirmed by
`test_t4a_populated_source_produces_row_but_gate_is_unsatisfiable`.

**FILES — CREATED:**
- `orchestrator/source_ingest/endpoints.py` — `derive_endpoints_from_ipcat` +
  T4a endpoint facts (QUP/DAI) into the schema `track_t4a` parses.
- `EndpointFact` added to `orchestrator/source_ingest/models.py`.
- tests: `tests/test_source_ingest_endpoints.py`; separator-reconcile assertions
  extend `tests/test_g3a7_source_gate.py`.

**FILES — MODIFIED:**
- **The T4a separator.** Reconcile ONE side: either `_t4a_subject`
  (crossverify.py:1743-1754) emits a dot, or both gates (codec_stub.py:214,
  machine_driver.py:229) scan the colon. **DECISION REQUIRED before coding**
  (recorded in the commit message): changing the producer risks the frozen fixture
  `nord_trusted_facts.json`; changing the gates risks other `T4a.*` consumers.
  *Recommendation:* change the **producer** to emit the dot form and regenerate the
  fixture, because the fixture already encodes the dot form as intended — but this
  MUST be verified against every `T4a.qup.` consumer first.
- `orchestrator/runners/target_onboarding_runner.py` — `_build_audio_topology`
  routes the `derive_endpoints_from_ipcat` result (or the `"SOURCE_UNRESOLVED"`
  literal via `sentinel_to_json_literal`) into `topology["endpoints"]`.

**FILES — NOT TOUCHED:** codec_stub/machine_driver *gate-open logic* (only the
prefix separator, if the gate side is chosen); codegen engine seam; the real
IPCAT/`buses` reader (**WP-SRC-B2** scope).

**TESTS (T-SRC-B-*):**
- **T-SRC-B-1** endpoints ingestion from the fixture QUP shape → non-empty
  endpoints.
- **T-SRC-B-2** separator reconcile: `track_t4a` row now keys under `T4a.qup.`
  (dot) and `is_open("T4a", subject)==True`. Updates the assertion in
  `test_t4a_populated_source_produces_row_but_gate_is_unsatisfiable` (which
  currently asserts the gate is *un*satisfiable) — the update is itself the
  regression proof that the defect closed.
- **T-SRC-B-3** joint flip on the fixture: on the joint fixture profile with
  A + B1 applied, **both** machine_driver and codec_stub gates open (integration,
  fixture-driven — the real-target equivalent is T-SRC-B2-* after WP-SRC-B2).
- **T-SRC-B-4** underivable endpoints → SOURCE_UNRESOLVED.
- **T-SRC-B-5** determinism on the degradation fixture.

**EXIT CRITERIA (boolean):**
- ☐ `derive_endpoints_from_ipcat` returns a non-empty `list[EndpointFact]` on the
  B1 fixture; `SOURCE_UNRESOLVED` (→ `"SOURCE_UNRESOLVED"` string) on real Nord
  until WP-SRC-B2 lands
- ☐ T4a rows key under `T4a.qup.` (separator reconciled); frozen fixture updated
  and every `T4a.qup.` consumer re-verified
- ☐ T-SRC-B-1…5 green (on the fixture)
- ☐ machine_driver AND codec_stub gates both open on the **fixture** joint profile
- ☐ Full suite still green; no generator *gate-open* logic modified

**NORTH-STAR EXIT CHECK:** After WP-SRC-B1 alone, the scorecard **stays 1/4** — this
is expected and correct, mirroring WP-SRC-A1: the endpoint contract + separator
reconcile are proven on the fixture, but real endpoints are `SOURCE_UNRESOLVED`
(**G-3A.11**) until WP-SRC-B2 plumbs the real IPCAT QUP data. The measurable proof
for B1 is that T-SRC-B-1..5 pass on the fixture and the separator is reconciled, NOT
a scorecard delta. **Do not treat 1/4-after-B1 as a STOP trigger** (see §5a).

**RISKS:**
- **R-SRC-B-1** separator change breaks a `T4a.*` consumer other than the two
  gates. *Mitigation:* grep all `T4a.qup` / `startswith("T4a` sites before
  choosing a side; the decision is a commit-message-recorded design step.
- **R-SRC-B-2** frozen fixture regeneration hides a real behavior change.
  *Mitigation:* regenerate + diff-review; a fixture change requires an explicit
  test asserting the new key form.
- **R-SRC-B-3** endpoints derived but shape ≠ what `track_t4a` parses.
  *Mitigation:* T-SRC-B-1 asserts row emission, not just non-empty dict.

**MANUAL VERIFICATION CHECKPOINT:** confirm derived QUP/DAI endpoints (from the
fixture) match the resolved SA8797P QUP map; diff the regenerated fixture.

**ATOMIC COMMIT SEQUENCE:**
1. `feat(source-ingest): endpoint fact model`
2. `feat(source-ingest): derive T4a endpoints from the fixture QUP shape`
3. `fix(crossverify): reconcile T4a subject separator with gate prefix` *(design
   decision recorded in message)*
4. `feat(source-ingest): wire endpoints into audio_topology at JSON boundary`
5. `test(source-ingest): endpoints + T4a gate-open + fixture joint flip`

**ESTIMATED EFFORT:** **2–3 days** (endpoints derivation is smaller than pinmux;
the cost concentrates in the separator-reconcile blast-radius review).

**PREREQUISITES:** **WP-SRC-A1 + WP-SRC-A2**. **Coupled with WP-SRC-B2 for
real-target scorecard effect** (B1 is the fixture contract; B2 is the real-data
plumbing — the pair is the T4a analog of the A1/A2 pair).

---

### WP-SRC-B2 — IPCAT QUP Enrichment (real endpoints → track_t4a)  ⭐

**NORTH-STAR JUSTIFICATION:** Closes **G-3A.11**. Wires real IPCAT QUP data into the
endpoint fact producer so WP-SRC-B1's wiring actually reaches `track_t4a` with
populated endpoints on real Nord (today it reads a fixture-only key path and returns
`SOURCE_UNRESOLVED` on every real run). **Does not flip a generator alone** — it is
the real-data half of the endpoint pair; **WP-SRC-B1 + WP-SRC-B2 jointly move Nord
machine_driver + codec_stub 0→1 on real targets** (together with the A1+A2 pinmux
half and the B1 separator reconcile). Mirrors the WP-SRC-A1 (contract) → WP-SRC-A2
(real plumbing) pattern exactly.

**OBJECTIVE:** Rewire `derive_endpoints_from_ipcat` to read real QUP facts from
`analysis["buses"]` (the freeform bus strings, e.g. `"I2C QUP2_SE4 (i2c18,
gpio154/155) …"`) **and** the cached IPCAT evidence
`targets/<t>/evidence/ipcat/chipio_get_qups.json` (the structured 27-item QUP list),
instead of the fixture-only key path `analysis["ipcat"]["qup_controllers"]` that no
producer populates on real onboard runs.

**STATUS: NOT STARTED.**

**FILES — CREATED / MODIFIED:**
- `orchestrator/source_ingest/endpoints.py` (MODIFIED) — rewrite the reader path to
  consume `analysis["buses"]` + `chipio_get_qups.json`, **OR**
- `orchestrator/source_ingest/ipcat_reader.py` (NEW) — a dedicated IPCAT QUP reader
  analogous to `dt_reader.py`, whose output `derive_endpoints_from_ipcat` consumes
  (preferred: keeps the producer thin and mirrors the A2 `read_dt_pinctrl` split).
- `orchestrator/runners/target_onboarding_runner.py` (MODIFIED) — populate the
  real IPCAT/QUP source before `_build_audio_topology` runs (reuse the existing
  IPCAT evidence discovery under `targets/<t>/evidence/ipcat/` where possible).
- `tests/test_source_ingest_endpoints.py` (MODIFIED) / new
  `tests/test_source_ingest_ipcat_reader.py` — T-SRC-B2-* against the captured real
  Nord `chipio_get_qups.json` fixture.

**TESTS (T-SRC-B2-*):** on the real Nord fixture (captured
`chipio_get_qups.json`) —
- **T-SRC-B2-1** unit: the reader parses `chipio_get_qups.json` + `buses` into the
  `EndpointFact` shape `track_t4a` parses.
- **T-SRC-B2-2** integration: `_build_audio_topology` on real Nord populates
  `topology["endpoints"]` with a non-empty list (not the sentinel string).
- **T-SRC-B2-3** missing / underivable IPCAT evidence → `SOURCE_UNRESOLVED`
  honestly (degradation path preserved).
- **T-SRC-B2-4** determinism: two runs → byte-identical endpoints.

**EXIT CRITERIA (boolean):**
- ☐ Real Nord `--onboard` produces `profile.audio_topology.endpoints` as a
  **non-empty list**, not the `"SOURCE_UNRESOLVED"` string.
- ☐ Cross-verify emits `T4a.qup.*` rows on the **real** Nord profile.
- ☐ machine_driver AND codec_stub gates both open on **real** Nord (jointly with
  the A1+A2 pinmux half and the B1 separator reconcile).
- ☐ T-SRC-B2-1..4 green.
- ☐ Full suite still green; no generator gate-open logic modified.

**NORTH-STAR EXIT CHECK (measurable):** WP-SRC-B3 (T4b subject reconcile, G-3A.12) is
now ✅ CLOSED 2026-07-24 (`9aa07ff`); with A2 also landed, the T1 and T4b halves are
open. After WP-SRC-B2 (which opens the last T4a half), run `--onboard nord-iq10
--generate`. Scorecard MUST move **Nord 1/4 → 3/4** (the +machine_driver +codec_stub
jump; dt_scaffolding still gated pending WP-SRC-C). Eliza likewise. **Note: pre-B2,
Nord stays at 1/4 — both generators still need the `T4a.qup.*` gate; this is expected,
not a falsification. If Nord stays 1/4 after B2 lands (with A2+B3 already in), the
coupled model is falsified — STOP and read the specific `is_open()` row for
machine_driver and codec_stub that did not open.**

**RISKS / MANUAL VERIFICATION** *(analogous to WP-SRC-A2)*:
- **R-SRC-B2-1** IPCAT payload shape parsing risk — the cached
  `chipio_get_qups.json` or `buses` strings misparse or pull vendor-specific noise.
  *Mitigation:* start with a minimum-viable reader scoped to the fields
  `derive_endpoints_from_ipcat` needs; T-SRC-B2-1 asserts exact shape against the
  captured fixture.
- **R-SRC-B2-2** silent shape mismatch (reader returns a valid dict that doesn't
  match the endpoint schema). *Mitigation:* T-SRC-B2-1 asserts the `track_t4a`-row
  emission, not just non-empty.
- **R-SRC-B2-3** non-determinism from evidence-file ordering. *Mitigation:*
  T-SRC-B2-4 byte-identical determinism gate.
- **MANUAL VERIFICATION CHECKPOINT:** real-target smoke gate — run `--onboard
  nord-iq10`, confirm `endpoints` is a real list and the T4a rows are present and
  open; diff derived QUP endpoints against the resolved SA8797P QUP map.

**ATOMIC COMMIT SEQUENCE:**
1. `test(wp-src-b2): red baseline on captured Nord chipio_get_qups.json`
2. `feat(wp-src-b2): IPCAT QUP reader (buses + chipio_get_qups.json)`
3. `feat(wp-src-b2): rewire derive_endpoints_from_ipcat onto the real reader`
4. `feat(wp-src-b2): populate real IPCAT QUP source before _build_audio_topology`
5. `test(wp-src-b2): real-Nord endpoints non-empty + T4a gate-open joint flip`

**ESTIMATED EFFORT:** **2–3 days.**

**PREREQUISITES:** **WP-SRC-B1 landed** (the fixture wiring contract that B2 feeds
with real data), on top of **WP-SRC-A1 + WP-SRC-A2**.

---

### WP-SRC-C — DTS Staging + T5 Producer/Gate Reconcile (T5)  ⭐

**NORTH-STAR JUSTIFICATION:** Flips the **third** generator (dt_scaffolding 0→1)
independently of A+B. But §4a-3 proves staging DTS is **not sufficient**: the live
`track_t5` never emits MATCH/PARTIAL_MATCH, so `is_open("T5","dts.firmware")` is
architecturally unsatisfiable. **WP-SRC-C is therefore not a pure ingestion WP — it
requires a T5 producer (or gate) change**, which is why it carries a blocking
design-note first commit and the largest effort.

**OBJECTIVE:** (1) Stage the applied target DTS into `targets/<t>/dts/` so
`_load_dts_files` returns non-empty; (2) resolve the T5 unsatisfiability — decide
and implement whether `track_t5` gains a clean-match verdict for a
firmware/compatible subject, or the dt_scaffolding gate is redefined to accept the
verdicts T5 actually emits. **This decision is designed and reviewed BEFORE any
code** in `docs/WP_SRC_C_DESIGN_NOTE.md` (the blocking first commit; **not created
yet** — do not author it until WP-SRC-C is authorized to start).

**STATUS: NOT STARTED.** No `targets/<t>/dts/` dir exists; T5 unsatisfiability
confirmed by `test_dt_scaffolding_gate_unsatisfiable_from_live_t5`.

**FILES — CREATED:**
- `docs/WP_SRC_C_DESIGN_NOTE.md` — **blocking first commit.** Records the T5
  producer-vs-gate decision, the verdict semantics, and the regression risk to the
  T5 donor-leak path. No code lands before this note is reviewed.
- `orchestrator/source_ingest/dts_stage.py` — copy/resolve applied DTS into
  `targets/<t>/dts/` with a provenance stamp (source path + sha256).
- tests extend `tests/test_g3a7_t5_dts_probe.py` (the committed T5 probe):
  `tests/test_source_ingest_dts.py` for staging unit tests.

**FILES — MODIFIED:**
- `orchestrator/reasoning/crossverify.py` **or**
  `orchestrator/generation/dt_scaffolding.py` — the T5 producer/gate reconcile, per
  the design note's decision. **Exactly one** side changes; the choice is the
  design note's core content.
- `orchestrator/main.py` — DTS staging before `_run_crossverify`.
- `targets/nord-iq10/`, `targets/eliza/` — staged DTS dirs.

**FILES — NOT TOUCHED:** machine_driver/codec_stub gates; the T1/T4a producers;
codegen engine seam.

**TESTS (T-SRC-C-*):**
- **T-SRC-C-1** DTS staging copies applied DTS into `targets/<t>/dts/`;
  `_load_dts_files` returns ≥1 entry with a provenance stamp.
- **T-SRC-C-2** post-reconcile: a benign (non-leak) firmware/compatible DTS yields
  a T5 row that `is_open("T5","dts.firmware")==True`. This is the assertion
  `test_dt_scaffolding_gate_unsatisfiable_from_live_t5` currently proves
  *impossible* — its inversion is the regression proof the reconcile worked.
- **T-SRC-C-3** the donor-LEAK path still emits DISAGREE+warning (the reconcile
  must NOT turn a real leak into a clean match) — preserves
  `test_firmware_leak_dts_emits_disagree_not_match`.
- **T-SRC-C-4** determinism on the degradation fixture.

**EXIT CRITERIA (boolean):**
- ☐ `docs/WP_SRC_C_DESIGN_NOTE.md` reviewed and committed FIRST
- ☐ `targets/<t>/dts/` populated for Nord and Eliza
- ☐ T5 producer/gate reconciled: a clean firmware/compatible DTS opens the gate
- ☐ donor-leak path unchanged (still DISAGREE+warning)
- ☐ T-SRC-C-1…4 green
- ☐ Full suite still green

**NORTH-STAR EXIT CHECK (measurable):** After WP-SRC-C (with A+B already landed),
scorecard MUST move **Nord 3/4 → 4/4** and **Eliza 3/4 → 4/4**. **If dt_scaffolding
stays skipped after C, the T5 reconcile did not take — STOP and re-diagnose the
verdict/gate mismatch.**

**RISKS:**
- **R-SRC-C-1** the reconcile turns a genuine donor-leak into a false clean match
  (safety regression). *Mitigation:* T-SRC-C-3 pins the leak path; the design note
  must carve the clean-match verdict to NON-leak subjects only.
- **R-SRC-C-2** DTS staging duplicates the applied tree and drifts. *Mitigation:*
  provenance stamp (source path + sha256); T5 treats staged DTS read-only.
- **R-SRC-C-3** design decision picks the wrong side (producer vs gate) and a later
  T5 consumer breaks. *Mitigation:* the design note enumerates every T5 verdict
  consumer before deciding.
- **R-SRC-C-4** true-greenfield target has no DT → DTS channel UNRESOLVED.
  *Mitigation:* degradation fixture makes this an explicit OBSERVED_PROPOSAL, not a
  failure.

**MANUAL VERIFICATION CHECKPOINT:** `diff` staged DTS vs applied DTS (identical
modulo provenance header); read `cross_verification.rows` for the Nord output and
confirm the T5 row is present and open.

**ATOMIC COMMIT SEQUENCE:**
1. `docs(wp-src-c): T5 producer-vs-gate reconcile design note` *(blocking; first)*
2. `feat(source-ingest): stage target DTS with provenance stamp`
3. `fix(crossverify|dt_scaffolding): reconcile T5 clean-match verdict per design note`
4. `feat(source-ingest): wire DTS staging before crossverify`
5. `test(source-ingest): DTS staging + T5 gate-open + leak-path preserved`
6. `chore(targets): stage Nord + Eliza DTS`

**ESTIMATED EFFORT:** **5–6 days total** — 2-day design note (blocking first
commit) + 3–4-day implementation. The producer/gate change and its safety
regression surface (donor-leak path) are why this is the largest sub-WP, not the
DTS copy itself.

**PREREQUISITES:** **WP-SRC-A1 + WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2** landed (so the
scorecard delta for C is cleanly attributable to dt_scaffolding). Independent of the
A1+A2+B1+B2 coupling otherwise.

---

### WP-MCP-BANNER — MCP Degradation Banner (closes G-3A.6) ✅ CLOSED 2026-07-22

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

**STATUS: CLOSED 2026-07-22** by 5-commit series (b70e14f, fa72b91, 4923e40,
1c9ebab, 958ec02). Terminal + report signals now both label MCP degradation
honestly. Regression suite 60/60 green. Smoke validated on Nord: run-27 (ok path)
preserves success line; run-28 (SSL_CERT_FILE=/tmp/does-not-exist forced degraded
path) emits `[DEGRADED]` advisory in stdout and DEGRADED banner in report.

**FILES — MODIFIED:** `orchestrator/main.py` (the 3 cited points: 538-541 wrap,
692 summary line, and the crossverify snapshot-provenance handoff);
`orchestrator/runners/crossverify_collector.py` (surface the unavailable reason
instead of only swallowing it — 173-185). **CREATED:** `tests/test_mcp_banner.py`.

**INPUTS:** snapshot provenance (already carried at main.py:~1174).
**OUTPUTS:** a banner block in `onboarding_report.md` + a truthful terminal summary.

**TESTS (T-MCP-* naming):**
- **T-MCP-1** MCP down → banner=DEGRADED, terminal summary does NOT claim clean success. ✅ GREEN
- **T-MCP-2** MCP up → banner=OK. ✅ GREEN
- **T-MCP-3** collector `_call` failure surfaces a named reason, not just "unavailable". ✅ GREEN
- **T-MCP-4** degraded run still exits 0 (advisory, non-fatal) but is *labeled*. ✅ GREEN

**EXIT CRITERIA:** ☑ banner renders in all 3 states ☑ no silent success line when
degraded ☑ T-MCP-1…4 green ☑ still non-fatal (exit 0). **All met.**

**NORTH-STAR EXIT CHECK:** Artifact count itself unchanged by this WP, BUT it
prevents a *false* scorecard: after WP-MCP-BANNER a "3/4 skipped" run is
unmistakably labeled degraded. Guards the integrity of every other WP's north-star
check.

**RISKS:** R-MCP-1 over-fatal (turning advisory into a hard fail) → mitigation: keep
exit 0, banner only. R-MCP-2 banner noise on healthy runs → mitigation: OK state is
one line.

**MANUAL VERIFICATION:** run once with MCP reachable, once with it unreachable;
confirm the report and terminal differ honestly. **DONE:** run-27 (ok) vs run-28
(SSL_CERT_FILE forced degraded).

**ATOMIC COMMIT SEQUENCE (as shipped 2026-07-22 — supersedes the original 4-commit sketch):**
1. `b70e14f` test(mcp-banner): T-MCP-1..4 red before implementation *(§5a test-first)*
2. `fa72b91` fix(crossverify): reason field on unavailable + snapshot-time mcp_state
3. `4923e40` fix(crossverify): propagate mcp_state into snapshot_provenance
4. `1c9ebab` feat(wp-mcp-banner): render MCP / Authority Status section
5. `958ec02` feat(wp-mcp-banner): terminal summary mcp_state-aware

**ESTIMATED EFFORT:** **1–2 days.** **Actual: ~1 day** (5 commits landed 2026-07-22).

**PREREQUISITES:** none. Best landed *before* WP-SRC so WP-SRC's north-star checks
are read against a truthful banner. **Satisfied.**

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
[ ] WP-D        committed 1afec36 (verify on ancestry)   — DONE
[ ] WP-E        committed 4af8bdd (verify on ancestry)   — DONE
[x] WP-MCP-BANNER   CLOSED 2026-07-22 (b70e14f, fa72b91, 4923e40, 1c9ebab, 958ec02)
[ ] WP-SRC-A1   (pinmux/T1 sentinel + wiring — opens machine_driver half once WP-SRC-A2 lands; no scorecard move alone)
[x] WP-SRC-A2   (DT plumbing: --kernel-source → analysis["dt"] — makes WP-SRC-A1 effective on real targets; no scorecard move alone) ✅ CLOSED 2026-07-22 (`29bf385` + `04bb164` + `cedb3f6`)
[ ] WP-SRC-B1   (endpoint ingestion contract/T4a + separator reconcile — fixture-proven, inert on real targets; no scorecard move alone)
[ ] WP-SRC-B2   (IPCAT QUP enrichment: buses + chipio_get_qups.json → track_t4a — opens the last T4a half; with A2+B3 landed, B2 ALONE completes the 1/4 → 3/4 flip)
[x] WP-SRC-B3   (T4b producer/gate subject reconcile, G-3A.12 — ✅ CLOSED 2026-07-24 `fcf4268` red / `9aa07ff` green; T4b half of both gates now opens; stayed 1/4 pending B2's T4a)
[ ] WP-SRC-C    (DTS/T5 + producer/gate reconcile — flips dt_scaffolding)
[ ] WP-F        (coverage measurement)
[ ] WP-G        (coverage render)
```

### North-Star Scorecard (re-measured after EACH WP, four generators tracked)

Generators: **MD** = machine_driver, **CS** = codec_stub, **DT** = dt_scaffolding,
**AR** = audioreach_topology (ungated, always produces). Total is the count of the
four that produce a GeneratedArtifact.

| After WP | Nord total | Eliza total | MD | CS | DT | AR | Moved by |
|---|---|---|---|---|---|---|---|
| baseline (HEAD d8edec2) | 1/4 | 1/4 | ✗ | ✗ | ✗ | ✓ | — |
| WP-MCP-BANNER (✅ CLOSED 2026-07-22, commits b70e14f/fa72b91/4923e40/1c9ebab/958ec02) | 1/4 (*honestly labeled*) | 1/4 | ✗ | ✗ | ✗ | ✓ | — (integrity only — MCP degradation now labeled honestly in both stdout and report) |
| WP-SRC-A1 | **1/4 (unchanged — expected; A1 inert without WP-SRC-A2)** | 1/4 | ✗ (T1 half wired; DT plumbing missing) | ✗ | ✗ | ✓ | — (A1 alone moves nothing; on real targets emits `"SOURCE_UNRESOLVED"` string) |
| WP-SRC-A2 | **1/4 (unchanged — expected; A1+A2 opens T1 half only)** | 1/4 | ✗ (T1 half open; T4a still closed) | ✗ | ✗ | ✓ | ✅ **CLOSED 2026-07-22** (`29bf385` + `04bb164` + `cedb3f6`) — Nord run-31 confirms `pinmux` list of `PinmuxFact` dicts, cross-verify rows 11 → 20; scorecard stays 1/4 pending WP-SRC-B1+B2 (T4a coupled-pair completion) |
| WP-SRC-B1 | **1/4 (unchanged — expected; fixture wiring only, real endpoints still `SOURCE_UNRESOLVED` per G-3A.11)** | 1/4 | ✗ (T4a contract wired + separator reconciled, but inert on real targets) | ✗ | ✗ | ✓ | — (B1 alone moves nothing on the scorecard; contract proven on the B1 fixture, real endpoints resolve to `SOURCE_UNRESOLVED`) |
| WP-SRC-B3 (✅ CLOSED 2026-07-24, `fcf4268` red / `9aa07ff` green) | **1/4 (unchanged — expected; T4b half opens but T4a.qup.* still closed pending B2)** | 1/4 | ✗ (T1 + T4b halves open; T4a still closed) | ✗ (T4a still closed) | ✗ | ✓ | ✅ B3 reconciles the T4b subject (`_t4b_row` → `codec.<part>`) so `T4b.codec.*` opens on real codecs; **no scorecard move** — both generators still gate on the unopened `T4a.qup.*` |
| WP-SRC-B2 | **3/4** | **3/4** | ✓ | ✓ | ✗ | ✓ | **B2 alone completes the flip** (with A2 T1 + B3 T4b already landed, B2 opens the last gate `T4a.qup.*` → machine_driver + codec_stub flip 0→1) |
| WP-SRC-C | **4/4** | **4/4** | ✓ | ✓ | ✓ | ✓ | **C** |
| WP-F | 4/4 (measured) | 4/4 | ✓ | ✓ | ✓ | ✓ | — (measures) |
| WP-G | 4/4 (rendered) | 4/4 | ✓ | ✓ | ✓ | ✓ | — (renders) |

The scorecard is the single source of truth for "are we moving the north star."
**Note the deliberate flat steps at WP-SRC-A1, WP-SRC-A2, WP-SRC-B1, and WP-SRC-B2:**
A1 wires the T1 ingestion contract but is inert on real targets until A2 plumbs the DT;
A1+A2 opens only the `T1.gpio.i2s.*` half of machine_driver's gate; machine_driver also
gates on `T4a.qup.*`. B1 wires the T4a endpoint contract + separator reconcile but is
inert on real targets until B2 plumbs the real IPCAT QUP data (endpoints resolve to
`SOURCE_UNRESOLVED`, G-3A.11); the T4a half arrives with **WP-SRC-B2**. The third
gate, `T4b.codec.*`, is already open post-**WP-SRC-B3** (✅ CLOSED 2026-07-24 `9aa07ff`):
`_t4b_row` now emits `codec.<part>`, which both generators' `T4b.codec.` scan matches
(G-3A.12 RESOLVED). B3 landed first and stayed 1/4 (T4a was still closed); with A2 (T1)
and B3 (T4b) both landed, **WP-SRC-B2 alone completes the flip to 3/4** — `T4a.qup.*`
is the last remaining REQUIRE-OPEN gate. A 1/4 result after A1, after A1+A2, after
A1+A2+B1, or after A1+A2+B3 (T4a still closed) is a **prediction match, not a
regression** (see §5a rule 2).

### Manual review gates
- Each sub-WP's MANUAL VERIFICATION CHECKPOINT must be signed off before its final
  commit.
- The §8 pre-merge non-negotiables (denominator-provenance sign-off, banner renders,
  vocab-only, Nord trap-case) gate WP-F/WP-G.

### Explicit STOP conditions (per sub-WP — the causal model is falsifiable at each)
> **WP-SRC-A1:** the proof is that `derive_pinmux_from_dt(analysis["dt"])` returns
> a non-empty `list[PinmuxFact]` when `analysis["dt"]` carries an I2S8 group
> (T-SRC-A-2 integration on a synthetic DT fixture) AND `is SOURCE_UNRESOLVED`
> when the DT lacks I2S (T-SRC-A-3), NOT a scorecard delta. On real Nord/Eliza,
> `analysis["dt"]` is empty (G-3A.9), so the sentinel branch fires — that is a
> match with the §5 prediction, not a STOP. If T-SRC-A-2 fails on a populated
> DT fixture, the pinmux schema (esp. the required `name`, §4a-1) is wrong — STOP.
>
> **WP-SRC-A2:** the proof is `analysis["dt"]` becomes non-empty on real Nord
> after `--kernel-source` is resolved (T-SRC-A2-2 end-to-end), which then makes
> A1's derivation emit facts on the real target. If A2 lands and A1 still emits
> the sentinel string on real Nord, DT plumbing is not actually reaching
> `analysis["dt"]` — STOP.
>
> **WP-SRC-B1 (fixture contract):** the proof is that `derive_endpoints_from_ipcat`
> returns a non-empty `list[EndpointFact]` on the B1 fixture (T-SRC-B-1) AND the
> reconciled `track_t4a` row keys under `T4a.qup.` (dot) with `is_open("T4a",
> subject)==True` on the fixture joint profile (T-SRC-B-2/-3), NOT a scorecard
> delta. On real Nord/Eliza, endpoints resolve to `SOURCE_UNRESOLVED` (G-3A.11), so
> the sentinel branch fires — that is a match with the §5 prediction (**1/4
> unchanged**), not a STOP. **B1 STOP:** if T-SRC-B-1…5 do not all go green, or the
> separator does not reconcile on the fixture (the gate stays unsatisfiable with a
> populated endpoint), the fixture wiring contract is broken — STOP.
>
> **WP-SRC-B2 (real-data plumbing → the A1+A2+B1+B2 quadruple):** the proof is that
> real Nord `--onboard` produces `profile.audio_topology.endpoints` as a **non-empty
> list** (not the `"SOURCE_UNRESOLVED"` string) and cross-verify emits `T4a.qup.*`
> rows on the real profile (T-SRC-B2-2). **B2 STOP:** if B2 lands and real Nord
> endpoints are still the sentinel string, the real IPCAT/`buses` reader is not
> reaching `derive_endpoints_from_ipcat` — STOP. **B2 predicts 1/4 → 3/4** (with A2
> and B3 already landed, the T1 and T4b halves are open; B2 opens the last `T4a.qup.*`
> gate, flipping machine_driver + codec_stub) — a 1/4 result after B2 is now a STOP.
>
> **WP-SRC-B3 (T4b subject reconcile, G-3A.12) — ✅ CLOSED 2026-07-24 (`9aa07ff`):**
> the proof was that `_t4b_row`'s subject and both generators' `T4b.codec.` scan agree,
> so `is_open("T4b", <codec>)` is True on the real profile. Landed and verified: real
> Nord subjects resolve to `codec.pcm1681` / `codec.adau1979`; scorecard stayed 1/4
> (T4a still closed, pending B2). **Flip STOP:** if Nord is still **1/4** after B2 lands
> (with A2+B3 already in, i.e. the scorecard does not flip **1/4 → 3/4**), the
> coupled model is falsified — STOP and read the specific `is_open()` row
> for machine_driver and codec_stub that did not open (most likely the `T4a.qup.`
> separator, §4a-2, did not reconcile, or the T1 half regressed).
>
> **WP-SRC-C:** if dt_scaffolding is still skipped after C, the T5 producer/gate
> reconcile did not take — STOP and read the T5 row's verdict against the redefined
> gate (§4a-3).
>
> **Plan-level corollary:** if all sub-WPs (A1+A2+B1+B2+C) land and Nord is still
> <4/4 with no cited OBSERVED_PROPOSAL explaining the shortfall, the plan's central
> thesis (empty source is the blocker) is wrong — halt and re-plan, do not layer
> WP-F/WP-G diagnostics on top of a broken unlocker.

---

## §5a — Test-First + Smoke-Test Discipline (applies to every WP-SRC sub-WP)

1. **Write the failing test before the code.** Each sub-WP's gate-open integration
   test (T-SRC-A-2, T-SRC-B-3, T-SRC-B2-2, T-SRC-C-2) MUST be committed in a failing
   state (or demonstrably red on a clean checkout) BEFORE the implementation commit
   that makes it pass. The committed G-3A.7 probes
   (`tests/test_g3a7_source_gate.py`, `tests/test_g3a7_t5_dts_probe.py`) are the
   starting red state — several already assert the *current* unsatisfiability and
   will invert as the reconciles land.

2. **After every commit, re-measure the scorecard and compare against the §5
   prediction.** "Prediction" is the §5 scorecard ROW for that milestone, not "the
   total went up" — WP-SRC-A1's predicted total is 1/4 (unchanged), WP-SRC-A2's
   predicted total is also 1/4 (unchanged), WP-SRC-B1's predicted total is
   likewise 1/4 (unchanged), and **WP-SRC-B3's predicted total was ALSO 1/4
   (unchanged — B3 opened the T4b half, but the `T4a.qup.*` gate was still closed
   pending B2; ✅ CLOSED `9aa07ff`, stayed 1/4 as predicted)**, so 1/4 results after
   A1, A1+A2, A1+A2+B1, or +B3 are matches, not STOP triggers. Only WP-SRC-B2
   (completing the flip via the last `T4a.qup.*` gate, now that A2+B3 have landed)
   and WP-SRC-C predict an increase. A result that DIVERGES from its predicted row —
   in either direction — triggers that sub-WP's §5 STOP condition.

3. **Smoke both targets after every commit.** Run `--onboard nord-iq10` AND
   `--onboard eliza` after each commit, not just at WP end. Eliza is the fresh-target
   proxy; a Nord advance that silently regresses Eliza is a STOP.

4. **No gate-open logic edits.** WP-SRC may edit source-fact producers, the T4a/T5
   separator/verdict reconcile, and profile/target data — but MUST NOT edit the
   `is_open()` semantics (model.py:213-237) or the generators' gate-prefix scan
   logic beyond the single separator reconcile named in WP-SRC-B1/-C. Any diff that
   touches `_GATING_OPEN_VERDICTS` or a generator's `is_open(...)` call is
   out-of-scope and a STOP.

---

## §6 — Cross-WP Integration Testing

**How WP-SRC-A1 + WP-SRC-A2 + WP-SRC-B1 + WP-SRC-B2 + WP-SRC-C + WP-MCP-BANNER + WP-F + WP-G test together:**
- **Five integration keystones, one per sub-WP** — each is the joint end-to-end
  test that proves its sub-WP moved the scorecard (or, for A1/A2/B1, that the
  contract holds against its predicted 1/4 no-op):
  - **T-SRC-A-2** — populated pinmux fixture → `derive_pinmux_from_dt` returns
    non-empty `list[PinmuxFact]` → `is_open("T1","gpio.i2s.*")==True` in the
    synthetic integration path (machine_driver half-open on fixture; predicted
    real-target scorecard 1/4 unchanged because `analysis["dt"]` is empty until
    A2 plumbs it).
  - **T-SRC-A2-2** — `--kernel-source` resolves to a kernel DT dump → the DT
    loader populates `analysis["dt"]` → A1's derivation emits facts on real
    Nord (predicted scorecard 1/4 still unchanged — the T4a half remains gated
    behind B1+B2).
  - **T-SRC-B-3** — populated pinmux + populated DT + endpoints + separator
    reconcile on the **fixture** joint profile → both `T1.gpio.i2s.*` and
    `T4a.qup.*` open → `machine_driver` AND `codec_stub` flip 0→1 jointly on the
    fixture (predicted real-target scorecard 1/4 unchanged — real endpoints are
    `SOURCE_UNRESOLVED` until B2 plumbs them).
  - **T-SRC-B2-2** — real Nord IPCAT QUP data (`buses` + `chipio_get_qups.json`)
    → `derive_endpoints_from_ipcat` returns a non-empty list on the real target →
    `T4a.qup.*` open on the real Nord profile. With A2 (T1) and B3 (T4b) already
    landed, this opens the last gate → `machine_driver` AND `codec_stub` flip 0→1
    jointly on Nord (predicted scorecard **1/4 → 3/4**).
  - **T-SRC-B3-2 — ✅ CLOSED 2026-07-24 (`9aa07ff`)** — T4b producer/gate subject
    reconcile → `is_open("T4b",<codec>)` on the real Nord profile (subjects resolve
    to `codec.pcm1681` / `codec.adau1979`). Landed before B2, so the `T4a.qup.*` half
    was still closed → scorecard stayed **1/4** as predicted, pending B2.
  - **T-SRC-C-2** — staged DTS + producer/gate reconcile →
    `is_open("T5","dts.firmware")==True` for Nord → `dt_scaffolding` flips 0→1
    (predicted scorecard 4/4). Also asserts the donor-leak safety pin
    (firmware-leak DTS still emits DISAGREE_WITH_AUTHORITY + warning=True; the
    gate stays closed on the leak path — the reconcile only opens the clean path).
- **T-F** consumes the registry populated by a WP-SRC-A1/A2/B1/B2/C run (not
  synthetic-only fixtures) in at least one integration test, proving the
  source→registry→coverage chain.
- **T-G** renders a report from a real WP-SRC-A1/A2/B1/B2/C + WP-F Nord run in one
  integration test.
- **T-MCP** runs the full onboard twice (MCP up/down) asserting the banner +
  scorecard differ honestly.

**Pre-Phase-3A regression suite that MUST stay green after every WP:**
- The full existing suite (WP-D catalog tests, WP-E registry tests ~1186 LOC,
  cardinality/crossverify tests, ipcat_acquire provenance tests). Run the whole
  `tests/` directory; zero new failures is a hard gate on every commit.

**Manual smoke after each WP (including each WP-SRC sub-WP A1/A2/B/C separately):**
`--onboard nord-iq10` AND `--onboard eliza` (both, every commit) — Eliza is the
fresh-target proxy and must not regress while Nord advances. The scorecard row
in §5 defines the *expected* value at each sub-WP boundary; a mismatch is a
STOP condition per §5a (with the WP-SRC-A1/A2 guard-clause: 1/4 unchanged after
A1 alone, or after A1+A2, is a match, not a STOP — the scorecard delta only
lands with A1+A2+B jointly).

---

## §7 — Documentation to Write During Implementation

| WP | Docs to update / create |
|---|---|
| WP-SRC-A1 | No new design doc. A1 is a pure-ingestion-contract sub-WP — its design decisions (Design B bare-singleton `SOURCE_UNRESOLVED` sentinel, identity-not-equality gate predicate, `derive_pinmux_from_dt` contract, wiring pattern in `_build_audio_topology`) are captured **inline in the atomic commit messages** per the WP-SRC-A1 spec in §4. Update PHASE3_KNOWN_GAPS.md G-3A.7 status once A1+A2+B1+B2 jointly close the T1/T4a half of the gap. |
| WP-SRC-A2 | No new design doc. A2 is a pure DT-plumbing sub-WP — its design decisions (kernel DT loader source-of-truth, path resolution from `--kernel-source`, degradation when the DT is missing) are captured **inline in the atomic commit messages** per the WP-SRC-A2 spec in §4. Close PHASE3_KNOWN_GAPS.md G-3A.9 once A2 lands and A1's derivation actually returns facts on real Nord. |
| WP-SRC-B1 | No new design doc. B1's design decisions (endpoint source-of-truth precedence, the `T4a.qup:`↔`T4a.qup.` separator reconcile — producer or gate side, and the reason — the `EndpointFact` contract, and the coupled-with-A/B2 scorecard semantics) are captured **inline in the atomic commit messages** per the WP-SRC-B1 spec in §4. Update PHASE3_ARCHITECTURE.md §9 to move endpoint-side source-ingestion from out-of-scope → in-scope. |
| WP-SRC-B2 | No new design doc. B2 is a pure real-data-plumbing sub-WP — its design decisions (IPCAT QUP source-of-truth: `analysis["buses"]` + `evidence/ipcat/chipio_get_qups.json`, the reader split analogous to `dt_reader.py`, degradation when IPCAT evidence is missing) are captured **inline in the atomic commit messages** per the WP-SRC-B2 spec in §4. Close PHASE3_KNOWN_GAPS.md **G-3A.11** once B2 lands and `derive_endpoints_from_ipcat` returns real endpoints (not the sentinel) on real Nord. |
| WP-SRC-C | **NEW** `docs/WP_SRC_C_DESIGN_NOTE.md` — **blocking first commit** of WP-SRC-C (not a phase-wide design doc; scoped only to C). Documents: the `track_t5` producer/gate reconcile design decision (why track_t5 must be allowed to emit MATCH/PARTIAL_MATCH for `dts.firmware` on clean paths while preserving DISAGREE+warning on donor-leak paths), the DTS staging convention under `targets/<t>/dts/`, and the donor-leak safety-pin contract (regression-guarded by `tests/test_g3a7_t5_dts_probe.py::test_firmware_leak_dts_emits_disagree_not_match`). Also update PHASE3_ARCHITECTURE.md §9 to move DTS-side source-ingestion from out-of-scope → in-scope, and close PHASE3_KNOWN_GAPS.md G-3A.7 once C lands. |
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
3. **Degradation honesty (not a fresh-target coverage bar):** on the degradation
   fixture — a target with one or more source channels genuinely UNRESOLVED — the run
   emits an explicit `SOURCE_UNRESOLVED` provenance marker and an OBSERVED_PROPOSAL
   for each blocked family, and the scorecard reflects the honest partial count. The
   ship gate is that degradation is **explicit and cited**, NOT that the fixture hits
   any particular N/4. (Fresh-target *coverage* is a Phase-3B goal — see §9 B-1 —
   deliberately NOT a Phase-3A ship gate, because gating shipping on greenfield
   coverage would make Phase-3A un-shippable for reasons orthogonal to the source
   unlocker.)
4. All **WP_F_DESIGN_REVISION §7 inspection gates** satisfied.
5. All **PHASE3_ARCHITECTURE §10 pre-merge non-negotiables** (denominator-provenance
   sign-off, banner renders, vocab-only, Nord trap-case review) satisfied.
6. MCP degradation is **loud** (WP-MCP-BANNER) — no run can silently claim success.
7. Full regression suite green.
8. **Two-week evidence window**: Nord + Eliza re-onboarded across the window with
   stable scorecards before opening Phase-3B.

**Scope boundary (what Phase-3A does NOT gate on):** greenfield/no-DT coverage,
engine activation (codegen NullEngine stays default), and any `is_open()` semantic
change beyond the two named WP-SRC-B1/-C separator/verdict reconciles. These are
Phase-3B (§9).

---

## §9 — Post-Phase-3A Next Moves

- **B-1 (fresh-target coverage goal — relocated from the §8 ship gate):** the former
  "fresh-target hypothetical ≥2/4" criterion is a Phase-3B *goal*, not a Phase-3A
  ship gate. Target: on the degradation fixture (and a real no-prior-patch target
  when one arrives), reach ≥2/4 proposal-quality artifacts with FIXMEs, remaining
  families explicit OBSERVED_PROPOSAL. Phase-3A only requires that the degradation be
  explicit and cited (§8 criterion 3); *raising* the fresh-target count is B-1.
- **Path B (validator-after-human):** scope a human-approval gate (#3) that runs `dtc`
  / compile checks on the WP-SRC-produced proposals before they are called
  patch-ready. Prereq: WP-SRC artifacts stable across the two-week window; a defined
  "reviewer accepts proposal" record (reuse WP-E ReviewRecord). Phase-3B.
- **Path C (full greenfield bootstrap):** generating artifacts for a target with *no*
  DT and *no* schematic (pure spec-in). Deferred. **Re-eval trigger:** when a real
  Audio BU target arrives with only a datasheet + no DT, and the degradation fixture's
  OBSERVED_PROPOSAL ceiling becomes the actual customer ask.
- **Wire the codegen engine seam:** replace `NullEngine` with `ClaudeCodeEngine`/
  `QGenieEngine` (engine.py:55-70, currently NotImplementedError) — only once WP-SRC
  proves the source-fact inputs are reliable. Deferred to Phase-3B.
