# Phase-3 Known Gaps

Accepted architectural gaps identified during Phase-3A design. Each entry
records the gap, why it is being accepted (rather than fixed now), the
observable impact, and the dependency chain that must complete before it can
be closed.

Adding a gap here is not a bug filing — it is a design decision to defer.
Closing a gap requires an explicit work-package with its own spec and
pre-merge checklist, not a drive-by patch.

---

## G-3A.1 — IPCAT Acquisition Lifecycle

### Title

IPCAT Acquisition Lifecycle

### Problem

Current onboarding consumes:

- cached IPCAT evidence
- offline documents
- prior evidence

but does not perform live IPCAT acquisition.

As a result:

`LIVE_IPCAT_VERIFIED`

is effectively unreachable from standard onboarding.

### Impacts

- `onboard`/`generate` cannot acquire missing authority facts.
- Coverage may remain incomplete.
- `NO_IPCAT_EVIDENCE` persists even when IPCAT is available.
- Evidence refresh is manual.

### Resolution Strategy

Defer implementation until:

- WP-E Fact Registry
- WP-F Coverage Engine
- WP-G Coverage Reporting

are complete.

### Future Work

Once the Coverage Engine can identify:

- missing facts
- stale facts
- authority source

selective IPCAT acquisition can then target only missing facts rather than
performing full refreshes. Live-acquisition scope becomes a function of the
Coverage-Engine's missing-fact set, not a blanket "refresh everything"
sweep, which:

- bounds MCP round-trip cost per onboarding run,
- keeps the acquisition path idempotent (re-runs only touch facts still
  flagged missing/stale),
- gives the operator a stable, per-fact audit trail of which authority
  produced which value (recorded in the fact registry's provenance chain
  per `WP_E_FACT_REGISTRY_DESIGN.md` §6).

### Dependencies

Blocked by, in order:

1. **WP-E — Fact Registry.** A place to write acquired facts with
   provenance. Without this, live-acquired values have nowhere durable to
   land and the tri-state (`LIVE_IPCAT_VERIFIED` /
   `CACHED_IPCAT_ONLY` / `NO_IPCAT_EVIDENCE`) has no substrate. Design in
   `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md`.
2. **WP-F — Coverage Engine.** The consumer that decides which facts are
   missing and which are stale. Without WP-F, the acquisition path would
   have to make its own coverage judgment, duplicating logic and inviting
   drift.
3. **WP-G — Coverage Reporting.** The surface where the operator sees
   which facts were live-acquired vs cached vs absent. Without WP-G, a
   live acquisition would happen but be invisible in the onboarding report.

### Status

**Accepted architectural gap. Deferred beyond Phase-3A.**

Phase-3A ships without live IPCAT acquisition. Onboarding reports will
correctly render `NO_IPCAT_EVIDENCE` or `CACHED_IPCAT_ONLY` per the WP7
tri-state until this gap is closed. Operators requiring live-verified facts
during Phase-3A must use the manual review path (`ReviewRecord`, per
`WP_E_FACT_REGISTRY_DESIGN.md` §8), which is a first-class authority in
the registry.

### Exit Criteria (for closing this gap in a later phase)

- WP-E, WP-F, WP-G committed and green.
- A new work-package (tentatively "WP-H — Selective IPCAT Acquisition")
  scoped, designed, and reviewed.
- Acquisition path writes only into the fact registry via the existing
  `Registry.append_provenance()` API — no new state surface.
- Acquisition never rewrites `case.py` or `case.generated.py` and never
  bypasses the ManualFact evidence rules for facts it did not acquire.
- Onboarding report renders `LIVE_IPCAT_VERIFIED` for facts the run
  actually re-fetched, with an IPCAT `query_id` in the provenance chain
  visible in the audit trail.

#### Update — 2026-07-22

Sibling gap G-3A.7 identified today via nord-iq10-onboarding-{21,22}
diagnosis: T1/T4a cross-verify tracks short-circuit on empty
source facts (`orchestrator/reasoning/crossverify.py:416, 1816`) BEFORE the
authority side (IPCAT/MCP) is consulted; T5 does not short-circuit but
still fails its gate (see G-3A.7 for the corrected T5 mechanism). This
means the original framing above,
which treated G-3A.1's live-IPCAT gap as the sole reason generation
is degraded, was too narrow. Live IPCAT unlocks the authority side
of cross-verify but does NOT unlock generation on its own —
profile-side source facts (see G-3A.7) are a separate hard
dependency. G-3A.1 remains deferred as originally stated; its scope
is now narrower than modeled.

### Cross-references

- `audio_bu_skill/docs/PHASE3_LANDSCAPE.md` §1 Trust Doctrine (three-tier
  model: IPCAT-only / IPCAT+schematic / schematic-only).
- `audio_bu_skill/docs/PHASE3_ARCHITECTURE.md` §7 (Report design), §8
  (WP-E/WP-F/WP-G specs), §9 (Out-of-scope for Phase-3A).
- `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md` §1 Objectives (WP-E
  advisory-only in Phase-3A; not imported by any runner), §7 SourceRef
  variants (`IPCATLiveRef` reserved for this future path).
- WP7 tri-state implementation:
  `LIVE_IPCAT_VERIFIED` / `CACHED_IPCAT_ONLY` / `NO_IPCAT_EVIDENCE`
  (commit `e6b66a0`).

---

## G-3A.2 — ESM under-specification hazard (deferred)

Failure mode: a hand-authored ESM (`targets/<target>/expected_subjects.json`)
may silently omit MANDATORY subjects declared by the catalog. Gate 2
(`WP_F_DESIGN_REVISION.md` §6.3 gate 2) then becomes fail-silent: the coverage
engine correctly computes coverage against an under-specified denominator, and
trap families (Nord: VDD_LCX/LMX, I2S8 logical port) can read
`OBSERVED_COMPLETE` when they should read `OBSERVED_GAP`.

Rigor note: `schema.py:234–241` (`FactFamilyDef.__post_init__`) enforces at
construction time that critical families have ≥1 MANDATORY subject. So an empty
ESM for a critical family is structurally under-specified — a theorem, not a
heuristic. This is what makes a future defense easy to prove correct.

Deferred, not fixed. Candidate defenses are drafted in
`docs/session_notes/WP_F_ESM_INTEGRITY_DRAFT_2026-07-22.md`:

- Process gate 1b: pre-Gate-2 ESM authoring review
- Engine defense: `ESM_UNDERSPECIFIED` state + catalog cross-reference in
  `esm.py`

Exit criterion: promote the draft to a real revision IF the failure mode
surfaces during the post-WP-G two-week evidence window (§10) OR during any
Nord/Eliza ESM authoring review. Do not promote pre-emptively.

---

## G-3A.6 — Silent cross-verify / MCP degradation

### Title

Silent cross-verify / MCP degradation

### Problem

The cross-verify pass can fail or run degraded (MCP authority unreachable,
snapshot empty) without the onboarding run signalling it. Three code points
make the degradation silent:

- `orchestrator/main.py:538-541` — `_run_crossverify` is wrapped in a
  try/except that swallows failure and continues.
- `orchestrator/runners/crossverify_collector.py:173-185` — `_call` catches
  `BaseException` and returns an "unavailable" sentinel, discarding the reason.
- `orchestrator/main.py:692` — the terminal summary prints "wrote proposal
  artifacts" unconditionally, regardless of whether cross-verify degraded.

### Impacts

- A run with MCP down can *look* successful while silently producing degraded
  output.
- A "4/4 artifacts" claim cannot be trusted without inspecting internals: a
  degraded run that is actually "1/4 + 3 silent skips" is indistinguishable
  from a healthy run at the terminal.
- Undermines the integrity of every north-star scorecard measurement — the
  scorecard could report a false positive.

### Resolution Strategy

Scheduled as **WP-MCP-BANNER** in `docs/PHASE3A_IMPLEMENTATION_PLAN.md` §4.
Emit a visible, non-fatal `## MCP / Authority Status` banner
(EMPTY / DEGRADED / OK) and make the terminal summary reflect degraded state
instead of the unconditional success line. Keep exit 0 (advisory), but label
the degradation loudly.

### Status

**CLOSED 2026-07-22 by WP-MCP-BANNER** (commits b70e14f, fa72b91, 4923e40,
1c9ebab, 958ec02). Terminal + report signals now both label MCP degradation
honestly. Regression suite 60/60 green. Smoke validated on Nord: run-27 (ok
path) preserves success line; run-28 (SSL_CERT_FILE=/tmp/does-not-exist forced
degraded path) emits `[DEGRADED]` advisory in stdout and DEGRADED banner in
report.

### Exit Criteria (for closing this gap)

- Banner renders in all three states (EMPTY / DEGRADED / OK).
- No silent success line when cross-verify degraded.
- `_call` surfaces a named unavailable-reason instead of only a sentinel.
- Degraded run still exits 0 but is unmistakably labeled.
- Tests T-MCP-1…4 green.

### Cross-references

- `docs/PHASE3A_IMPLEMENTATION_PLAN.md` §4 (WP-MCP-BANNER), §2 (goal-guard
  justification).
- `orchestrator/main.py:538-541,692`;
  `orchestrator/runners/crossverify_collector.py:173-185`.

---

## G-3A.7 — Empty profile source side blocks generation (north-star root cause)

### Title

Empty profile source side blocks three of four generators

### Problem

Three of the four generation skills are hard-gated on open cross-verify rows,
and those rows never come into existence because the **profile source side is
empty**:

| Generator | Gate (is_open row) | Source-fact channel it needs |
|---|---|---|
| `machine_driver.py:217-226` | `T1.gpio.i2s.*` | `gc["audio_topology"]["pinmux"]` |
| `codec_stub.py:214-222` | `T4a.qup.*` | `gc["audio_topology"]["endpoints"]` |
| `dt_scaffolding.py:205-243` | `T5.dts.firmware` | DTS under `targets/<t>/dts/` |

`is_open()` (`orchestrator/generation/model.py:213-237`) is fail-closed: a
missing row is not open, and a present row whose verdict ∉ {MATCH,
PARTIAL_MATCH} (or that carries `warning=True`) is not open either. Rows fail
to open at the *source* step — `_crossverify_source_facts`
(`main.py:1099-1113`) reads `pinmux`/`endpoints`, `_load_dts_files`
(`main.py:1118-1137`) reads the DTS dir — but the **mechanism differs by
track**, and the difference matters for diagnosing which generator is blocked
and why:

- **T1 and T4a — short-circuit to zero rows.** On empty `pinmux`/`endpoints`,
  `track_t1` and `track_t4a` `return []`
  (`orchestrator/reasoning/crossverify.py:416-417, 1816-1817`) *before* any MCP
  authority is consulted. No `T1.*`/`T4a.*` row is ever created, so the
  machine_driver and codec_stub gates close on a **missing** row.
- **T5 — does NOT short-circuit; emits one present-but-NCC row.** On empty
  DTS, `track_t5` falls through to its Path-1/Path-2 revision-anchor sweep and
  emits **one** `NOT_CROSS_CHECKABLE` row (`subject=dts.revision`,
  `coverage_gap_reason=revision_not_pinned`,
  `orchestrator/reasoning/crossverify.py:1402,1472`). Critically, `track_t5`
  emits *only* `DISAGREE_WITH_AUTHORITY` and `NOT_CROSS_CHECKABLE` verdicts —
  it **never** emits `MATCH`/`PARTIAL_MATCH`, and it never emits a subject
  named `dts.firmware` or `dts.compatible` (those come only from donor-rule
  `kind` values `firmware`/`compatible`, which fire only when the DTS text
  matches a donor pattern). So the dt_scaffolding gate
  (`is_open("T5","dts.firmware")`) closes on a **row that does exist for a
  different subject, or a present-but-non-open verdict** — not on a missing
  `T5.*` row.

The observable outcome is identical for all three (verdict ∉ open-set → gate
closed → generator skipped), but the *reason string* the generator reports
differs: dt_scaffolding sees `firmware_row is None` →
`authority_not_in_snapshot` (`dt_scaffolding.py:219`), whereas machine_driver
sees no `T1.gpio.i2s.*` rows at all. Conflating "short-circuit to `[]`" across
all three tracks (as the original G-3A.7 text did) mis-describes the T5 path
and would send a debugger looking for a missing row that is in fact present.

**Confirmed empirically (2026-07-22):** both Nord (`nord-iq10`) and Eliza
(`eliza`) `profile.json` have `audio_topology.pinmux=None`,
`.endpoints=None`, and no `targets/<t>/dts/` directory. Runs 21 (MCP up) and
22 (MCP down) *both* produced 3× GeneratorSkipped + 1× GeneratedArtifact —
proving the blocker is the empty source, not MCP state. The fourth generator
(`audioreach_topology`) has no is_open gate, which is why exactly one artifact
is produced.

### Impacts

- The north-star GOAL (generate all four artifacts, incl. for fresh targets)
  is **definitionally unreachable** while the source side is empty.
- Every target sits at 1/4 regardless of MCP health, IPCAT cache, or evidence.
- This is the root cause that G-3A.1 was originally (mis-)attributed to IPCAT
  acquisition — see the G-3A.1 Status block.

### Resolution Strategy

Scheduled as **WP-SRC** (Source-Fact Ingestion) in
`docs/PHASE3A_IMPLEMENTATION_PLAN.md` §4 — the only WP that moves the north
star. Populate `pinmux`/`endpoints` and stage `targets/<t>/dts/` before
`_run_crossverify`, feeding the *existing* plumbing (no new pipeline seam).
Underivable channels write an explicit `SOURCE_UNRESOLVED` provenance marker
(never a silent empty, never a fabricated guess).

### Status

**Accepted for closure IN Phase-3A (mandatory, not deferred).** Per the
standing scope constraint, diagnostic infrastructure (WP-F/WP-G) may not be
shipped as a substitute for this real capability. WP-SRC is the mandatory
north-star unlocker.

### Exit Criteria (for closing this gap)

- `pinmux` non-empty (or `SOURCE_UNRESOLVED`-marked) for Nord and Eliza.
- `endpoints` non-empty (or marked) for Nord and Eliza.
- `targets/<t>/dts/` populated for Nord and Eliza.
- After ingestion, T1/T4a/T5 rows are `is_open()==True` on the fresh-target
  fixture (T-SRC-6).
- North-star scorecard moves Nord **1/4 → ≥3/4** (target 4/4) and Eliza
  likewise; any family short of 4/4 emits an explicit OBSERVED_PROPOSAL with a
  cited reason.
- Tests T-SRC-1…7 green; full regression suite green; no generator gate code
  modified.
- **STOP condition:** if WP-SRC lands and Nord is still 1/4, the source→gate
  causal model is falsified — halt and re-diagnose before proceeding.

### Cross-references

- `docs/PHASE3A_IMPLEMENTATION_PLAN.md` §1 (gating chain), §4 (WP-SRC full
  spec), §5 (scorecard + STOP condition).
- G-3A.1 Status block (G-3A.7 narrows G-3A.1's scope; G-3A.1's live-IPCAT
  gap unlocks the authority side of cross-verify, while G-3A.7 addresses the
  source side).
- Gate code: `orchestrator/generation/machine_driver.py:217`,
  `orchestrator/generation/codec_stub.py:214`,
  `orchestrator/generation/dt_scaffolding.py:205`,
  `orchestrator/generation/model.py:213-237`.
- Source plumbing: `main.py:1099-1137`,
  `orchestrator/reasoning/crossverify.py:416-417,1816-1817` (T1/T4a
  short-circuit), `orchestrator/reasoning/crossverify.py:1402,1472` (T5
  NCC revision-anchor row).

---

## G-3A.8 — codec_driver_porting emits empty evidence_refs on --generate

### Title

`codec_driver_porting_runner` returns `evidence_refs: []` when input verdicts
are absent, triggering `EVIDENCE_REFERENCE_MISSING` and killing the run

### Problem

`PYTHONPATH=audio_bu_skill python -m orchestrator.main --target nord-iq10
--generate --kernel-source ./linux-nord/` on run `nord-iq10-onboarding-23`
crashed at `VALIDATING → FAILED` with `EVIDENCE_REFERENCE_MISSING`. The failure
event is preserved verbatim at
`audio_bu_skill/state/nord-iq10-onboarding-23.json:55-70`.

The chain is a driver-layer policy gate closing on an empty evidence list
supplied by a runner that has nothing to cite:

- `audio_bu_skill/skills/codec_driver_porting/skill.yaml:27` declares
  `evidence_required: true`.
- `audio_bu_skill/orchestrator/driver.py:181-186` reads
  `output["evidence"]["evidence_refs"]`; when the list is empty and the skill
  declares `evidence_required`, it raises
  `OrchestratorError(code="EVIDENCE_REFERENCE_MISSING", …)` and transitions the
  skill from `VALIDATING → FAILED`.
- `audio_bu_skill/orchestrator/runners/codec_driver_porting_runner.py:27-36`
  only appends to `evidence_refs` when `verdicts.get(part_number)` returns a
  truthy verdict with a non-`None` `driver_path`; if the caller passes
  `verdicts={}` (the current `--generate` path), every codec falls into the
  `"unresolved"` bucket at line 27 and `evidence_refs` stays `[]`.

The runner cannot cite what it never resolved. The driver policy is
correct in principle — a "success" without evidence is exactly the
silent-degradation shape WP-MCP-BANNER exists to prevent — but on
`--generate` the runner is being handed an empty verdict dict and
returning "success" with `[]`, which is neither a real success nor a
useful failure.

### Impacts

- `--generate` is unrunnable end-to-end on Nord until the runner
  either produces real evidence or fails cleanly earlier.
- The failure message (`skill output missing evidence_refs`) points at
  the policy layer, not the empty-verdicts input — a debugger reaches
  `driver.py:185` before understanding the real cause at
  `codec_driver_porting_runner.py:27`.

### Resolution Strategy

Two candidate fixes; both out-of-scope for WP-MCP-BANNER (which is
constrained to four cited surfaces: collector `_call`, snapshot_provenance
merge, banner renderer, terminal summary emitter):

1. **Runner-side upstream:** make `codec_driver_porting_runner` fail
   fast when `verdicts` is empty, with an explicit
   `NO_CODEC_VERDICTS_TO_PORT` code — replaces the misleading
   `EVIDENCE_REFERENCE_MISSING` with a diagnostic that names the real
   input gap.
2. **Runner-side downstream:** trace `--generate` upstream and populate
   `verdicts` before invocation (may be a `_generate` orchestration bug
   where `codec_driver_porting` runs before whatever produces
   verdicts).

Option (1) is the smaller change and treats the runner's contract as
authoritative; option (2) is the correct architectural fix if a
producer is genuinely missing from the `--generate` chain. Diagnosis
should decide which before code lands.

### Status

**Deferred — logged during WP-MCP-BANNER, out of that WP's cited
surface set (PHASE3A_IMPLEMENTATION_PLAN §4).** Not blocked by any
other gap; can be closed in a standalone WP after WP-MCP-BANNER
commits 3–4 land.

### Exit Criteria (for closing this gap)

- `--generate` on Nord either produces `evidence_refs` from real
  codec drivers ported, or fails at
  `codec_driver_porting_runner` with a codec-specific diagnostic
  (`NO_CODEC_VERDICTS_TO_PORT` or equivalent) — never the misleading
  `EVIDENCE_REFERENCE_MISSING` from the driver policy gate.
- Test asserting the runner refuses empty-verdicts input (fails
  fast with the codec-specific code) before ever handing the
  output to the driver validator.

### Cross-references

- `audio_bu_skill/orchestrator/driver.py:181-186` (policy gate that
  raises `EVIDENCE_REFERENCE_MISSING`).
- `audio_bu_skill/orchestrator/runners/codec_driver_porting_runner.py:27-36`
  (empty `evidence_refs` root).
- `audio_bu_skill/skills/codec_driver_porting/skill.yaml:27`
  (`evidence_required: true` declaration).
- `audio_bu_skill/state/nord-iq10-onboarding-23.json:55-70`
  (recorded failure event).

---

## G-3A.9 — DT Plumbing Missing (kernel-source → analysis.dt)

### Title

DT Plumbing Missing (kernel-source → analysis.dt)

### Discovered

2026-07-22, during WP-SRC-A close-out verification (Q4/Q5 north-star
scorecard check on real Nord).

### Problem

`derive_pinmux_from_dt` and the WP-SRC-A1 wiring at
`target_onboarding_runner._build_audio_topology` correctly consume
`analysis["dt"]` — but **nothing in the real runner path populates
`analysis["dt"]` from the `--kernel-source` tree**. The DT dict shape
that the T-SRC-A-5 integration test seeds via the `_dt_with_i2s8()`
fixture (`{"pinctrl": {...}}`) has no producer in production.

Consequence: on real Nord (and Eliza), `analysis.get("dt") or {}` is
`{}`, `derive_pinmux_from_dt` returns `SOURCE_UNRESOLVED`, and
`topology["pinmux"]` lands on disk as the literal string
`"SOURCE_UNRESOLVED"`. The pinmux row never reaches `track_t1`, the
`gpio.i2s.*` gate stays closed, and the north-star scorecard does NOT
flip after WP-SRC-A1 alone.

### Why accepted

WP-SRC-A1 (sentinel + wiring) is the demonstrable half. Shipping it now
proves the ingestion contract end-to-end and unlocks parallel WP-SRC-B
work on QUP endpoints. DT plumbing is a distinct, self-contained
follow-on with its own kernel-DT parsing surface and validation.

### Impact

- **Blocks north-star flip.** Without WP-SRC-A2, the WP-SRC-A1 wiring
  is inert on real targets — the sentinel is what lands on disk.
- **Blocks the T-SRC-A-5 real-target proof.** The fixture-driven
  integration test passes without WP-SRC-A2; a real-target smoke check
  cannot.
- **Does not affect** the WP-SRC-A1 shipped tests: T-SRC-A-1 (facts
  derivation), T-SRC-A-3 (sentinel identity), T-SRC-A-5 (wiring on
  fixture DT) are all green with A1 alone.

### Resolution — WP-SRC-A2 candidate

Estimated ~2-4 days. Scope: add a DT reader that walks
`--kernel-source` for the target-specific `.dts`/`.dtsi` files, parses
the pinctrl subtree into the dict shape `derive_pinmux_from_dt` expects,
and populates `analysis["dt"]` before `_build_audio_topology` runs.
Reuse the existing DTS reader that `_crossverify_source_facts.t5`
already walks under `targets/<t>/dts/` where possible.

### Status

**CLOSED 2026-07-22 by WP-SRC-A2 wiring commit cedb3f6.**
Real Nord `--onboard` (run-31) confirms `profile.audio_topology.pinmux`
transitions from `SOURCE_UNRESOLVED` sentinel to non-empty list of
`PinmuxFact` dicts with `gpio.i2s.*` names. Cross-verify rows expanded
11 → 20, confirming `T1.gpio.i2s.*` gate now has source-side facts.
WP-SRC-A2 (kernel-DT reader + wiring) architecturally complete.

Full ledger for WP-SRC-A2:
  - `29bf385` — test(wp-src-a2): red baseline
  - `04bb164` — feat(wp-src-a2): kernel-DT reader (A2-1/3/4 green)
  - `cedb3f6` — feat(wp-src-a2): wire read_dt_pinctrl into
    _build_audio_topology (A2-2 green)

T1 half of G-3A.7 architecturally solved. T4a half still open —
addressed by WP-SRC-B (T4a separator reconciliation).

### Blocks north-star flip

Yes. Nord machine_driver row on the §5 scorecard stays at "gated
closed" until WP-SRC-A2 lands (independently of WP-SRC-A1 status).

### Cross-references

- `audio_bu_skill/orchestrator/source_ingest/pinmux.py:94-171`
  (`derive_pinmux_from_dt`; consumer, correctly wired).
- `audio_bu_skill/orchestrator/runners/target_onboarding_runner.py:622-654`
  (`_build_audio_topology`; correctly reads `analysis.get("dt")`
  but has no producer).
- `audio_bu_skill/tests/test_source_ingest_pinmux.py` (T-SRC-A-5
  fixture-DT integration test; passes because fixture bypasses the
  missing plumbing).
- `audio_bu_skill/docs/PHASE3A_IMPLEMENTATION_PLAN.md` §4 WP-SRC-A2
  (planned resolution).

---

## G-3A.11 — IPCAT QUP Enrichment Missing (ipcat.qup_controllers never populated)

### Title

IPCAT QUP Enrichment Missing (analysis.ipcat.qup_controllers → endpoints)

### Discovered

2026-07-23, during WP-SRC-B commit 3 (WIRING) pre-commit verification
(Q2 real-Nord endpoint check under advisor review). Same disk-write /
producer-reads-fixture-only-key-path pattern as G-3A.9.

### Problem

`derive_endpoints_from_ipcat` and the WP-SRC-B commit 3 wiring at
`target_onboarding_runner._build_audio_topology` correctly consume
`analysis["ipcat"]["qup_controllers"]` — but **nothing in the real
runner path populates `analysis["ipcat"]["qup_controllers"]`**. The
`ipcat.qup_controllers` list shape that the T-SRC-B fixture seeds via
`_qup_populated_analysis()` (`tests/test_source_ingest_endpoints.py:82-120`)
has no producer in production.

Confirmed by reading the real Nord artifact
(`targets/nord-iq10/qgenie_analysis.json`): top-level keys are
`[amplifiers, audio_stack, board, buses, codecs, dt, element_counts,
human_review_needed, ipcat_findings, mics, missing_evidence,
nearest_targets, overall_confidence, power_model, schematic_nets, soc,
soundwire, speakers]`. **There is NO `ipcat` key** — `analysis.get("ipcat")`
is `None`, and `qup_controllers` appears nowhere. The fixture docstring
(`test_source_ingest_endpoints.py:85-88`) claims the shape "matches what
the WP-SRC-A2 wiring commit's `analysis` mapping already carries on real
`--onboard` runs" — that claim is false; the producer was written to the
fixture, and the two agree with each other while disagreeing with reality.

QUP facts DO exist on real Nord, but in two other forms neither of which
the producer reads:

- `analysis["buses"]` — freeform strings, e.g.
  `"I2C QUP2_SE4 (i2c18, gpio154/155) — codec control per applied
  nord-iq10.dtsi pinmux"` and
  `"LPASS I2S8 / TDM8 (audio data path, proposed per
  candidate_patch_series:5267b2e1)"`.
- Cached IPCAT evidence
  `targets/nord-iq10/evidence/ipcat/chipio_get_qups.json` — a structured
  27-element list, each entry
  `{clk, gpios:[[{function, name:"SAILSS_QUP0_SE0_L0", number, pad, ...}]]}`.

Consequence: on real Nord (and Eliza), `derive_endpoints_from_ipcat(analysis)`
returns `SOURCE_UNRESOLVED`, `topology["endpoints"]` lands on disk as the
literal string `"SOURCE_UNRESOLVED"` (confirmed at
`targets/nord-iq10/case.generated.py:188`), `track_t4a` emits zero
`T4a.qup.*` rows, and the `codec_stub` / `machine_driver` gates stay
closed. The north-star scorecard does NOT flip after WP-SRC-B alone.

### Why accepted

WP-SRC-B commit 1 (producer) + commit 2 (`track_t4a` separator reconcile)
+ commit 3 (wiring) prove the endpoint ingestion contract end-to-end on
the fixture, mirroring the WP-SRC-A1 → A2 split. The enrichment producer
(populate `analysis["ipcat"]["qup_controllers"]` from real IPCAT/`buses`
evidence, or repoint `derive_endpoints_from_ipcat` at
`chipio_get_qups.json` + `buses`) is a distinct, self-contained follow-on
with its own IPCAT-parsing surface and real-shape validation — a peer to
WP-SRC-A2's kernel-DT reader, not a fix that belongs inside c3 wiring.

### Impact

- **Blocks north-star flip.** Without the enrichment producer, the
  WP-SRC-B wiring is inert on real targets — the sentinel is what lands
  on disk. WP-SRC-B commit 3 does NOT move Nord 1/4 → 3/4.
- **Blocks the T-SRC-B real-target proof.** The fixture-driven
  T-SRC-B-3 joint-flip test passes without the producer; a real-target
  smoke check cannot.
- **Does not affect** the WP-SRC-B shipped fixture tests: T-SRC-B-1
  (producer non-empty on fixture), the separator reconcile, and the
  joint-flip open assertion are green on the fixture alone.
- Compounds with the **T-SRC-B-2 prerequisite gap**: `VerificationGate`
  is not defined in `orchestrator/generation/model.py` (grep for
  `class VerificationGate` across `orchestrator/` returns nothing), so
  `test_t4a_row_subject_uses_dot_separator_and_is_open` is currently red
  at the import step — a separate missing symbol, tracked alongside this
  gap.

### Resolution — WP-SRC-B2 candidate

Scope: add an IPCAT QUP enrichment reader that either (a) parses the
cached `chipio_get_qups.json` corpus + `analysis["buses"]` strings into
the `qup_controllers` dict shape `derive_endpoints_from_ipcat` expects
and populates `analysis["ipcat"]["qup_controllers"]` before
`_build_audio_topology` runs, or (b) repoints `derive_endpoints_from_ipcat`
directly at the real evidence shapes. Reuse the existing IPCAT evidence
discovery that `source_intake_runner.discover_evidence` already walks
under `targets/<t>/evidence/ipcat/` where possible. Also land the
`VerificationGate` symbol so T-SRC-B-2 can exercise `is_open`.

### Status

**Accepted architectural gap. Deferred to WP-SRC-B2.** WP-SRC-B commits
1–3 ship the fixture-proven contract; real-target endpoint population is
the mandatory follow-on that actually flips the T4a half of the
north-star. Per the standing scope constraint, fixture-green is NOT a
substitute for real-target capability.

### Blocks north-star flip

Yes. Nord codec_stub and machine_driver rows on the §5 scorecard stay at
"gated closed" until the enrichment producer lands (independently of
WP-SRC-B commit-3 wiring status). This is the T4a analog of G-3A.9's T1
finding.

### Cross-references

- `audio_bu_skill/orchestrator/source_ingest/endpoints.py:4,14-18`
  (`derive_endpoints_from_ipcat`; consumer, reads
  `analysis["ipcat"]["qup_controllers"]`, correctly wired to a shape no
  producer emits).
- `audio_bu_skill/orchestrator/runners/target_onboarding_runner.py:690-694`
  (`_build_audio_topology` endpoints branch; correctly reads the producer
  result but the producer has no real input).
- `audio_bu_skill/tests/test_source_ingest_endpoints.py:82-120`
  (`_qup_populated_analysis` fixture; docstring claims real-run parity
  that the real artifact contradicts).
- `audio_bu_skill/targets/nord-iq10/qgenie_analysis.json` (real analysis:
  no `ipcat` key; QUP facts live in `buses` + cached
  `evidence/ipcat/chipio_get_qups.json`).
- `audio_bu_skill/targets/nord-iq10/case.generated.py:188`
  (`"endpoints": "SOURCE_UNRESOLVED"` — the sentinel that lands on disk
  today).
- G-3A.9 (structurally identical DT-plumbing gap; G-3A.11 is the T4a
  analog of G-3A.9's T1 half — both are producer-reads-fixture-only-key
  gaps under G-3A.7's empty-source-side root cause).
- G-3A.7 Status block (this gap is the T4a half of the empty-source-side
  root cause; A2 closed the T1 half, this closes the T4a half).


## G-3A.12 — T4b producer/consumer subject-prefix mismatch (BLOCKED north-star flip; RESOLVED)

### Title

T4b codec-binding subject (`<codec><->{controller}`) did not match the
`T4b.codec.` gate prefix — pre-B3 the live producer could never open the codec
gate. RESOLVED by WP-SRC-B3: `_t4b_row` now emits `codec.<part>`.

### Discovered

2026-07-24, during WP-SRC-B1 B-3 (3a) investigation while driving the
production cross-verify seam over the real-Nord joint-flip fixture. Surfaced
by attempting to open both generators from `track_t4b` output rather than a
hand-authored `TrustedFacts` fixture.

### Problem (pre-B3)

Pre-B3, the T4b producer `_t4b_row` (`orchestrator/reasoning/crossverify.py`)
emitted `subject = f"{codec}<->{controller}"`, so `project_facts` keyed the row
as `"T4b.<codec><->{controller}"` (e.g. `T4b.ti,pcm1681<->i2s8`).

Both generators scan a *literal* prefix `"T4b.codec."`:

- `orchestrator/generation/machine_driver.py:240`
  — `codec_rows = _rows_with_prefix(facts, "T4b.codec.")` (Gate 3a
  disagreement scan + Gate 3b advisory-open requirement, `:252-258`).
- `orchestrator/generation/codec_stub.py:230`
  — same `_rows_with_prefix(facts, "T4b.codec.")` (Gate 3, `:250-256`).

`"T4b.<codec><->{controller}".startswith("T4b.codec.")` → **False** for every
real codec value. Therefore, **pre-B3 the live `track_t4b` producer could never
open the `T4b.codec.*` gate on a real codec value.** Before B3, the only
`T4b.codec.*` keys in the entire repo were hand-authored:

- `tests/fixtures/phase2b/nord_trusted_facts.json:132,152`
  (`subject: "codec.adau1979"`, `"codec.pcm1681"`).
- `tests/test_generation_machine.py` `_clean_nord_facts()` inline
  `_row("T4b", "codec.adau1979", ...)`.

Pre-B3, no producer emitted `codec.<part>` subjects. The mismatch was masked in
production ONLY because the un-provisioned Nord returns an empty snapshot, so
the T1 / T4a gates skip *first* (`authority_not_in_snapshot`) and control never
reaches the T4b gate. A populated snapshot (real IPCAT after WP-SRC-B2, or the
joint-flip test fixture) surfaced it immediately: T1 + T4a open, then both
generators skipped on `T4b.codec.*` with `authority_not_in_snapshot`.

### Impact — CRITICAL (pre-B3; now RESOLVED)

`machine_driver` AND `codec_stub` both hard-gate on a `T4b.codec.*`
advisory-open row. WP-SRC-B2 (real IPCAT QUP plumbing) fills the T1 + T4a
authority but does **nothing** for T4b. Pre-B3, this made the T4b subject
reconcile a **HARD PREREQUISITE** for the north-star flip: without it, both
generators skipped on `T4b.codec.*` even with fully populated T1 + T4a
authority. B3 removed that blocker — the producer now emits `codec.<part>`, so
the T4b advisory half of both gates opens on real codec values. The remaining
gate to the 1/4 → 3/4 flip is now solely WP-SRC-B2 (real T4a QUP endpoints);
see the Status block below.

### Resolution

Reconciled producer-side (WP-SRC-B3): `_t4b_row` now emits
`subject = f"codec.{_t4b_norm_part(codec)}"`, where `_t4b_norm_part` strips the
leading `vendor,` prefix and lowercases (`ti,pcm1681` → `pcm1681`,
`adi,adau1979` → `adau1979`, rule b). The row therefore keys as
`T4b.codec.<part>` and matches the `_rows_with_prefix(facts, "T4b.codec.")`
scan in both generators. No consumer change was needed; the generator gate
prefixes are unchanged. The residual `<->` in `crossverify.py` is only in the
`review_actions` human-message string (`"codec<->controller binding is not
IPCAT-checkable"`), not in any subject.

### Status

**CLOSED 2026-07-24** by WP-SRC-B3 (`fcf4268` red baseline, `9aa07ff` green).
`_t4b_row` now emits `codec.<part>` via `_t4b_norm_part` (rule b). Real-Nord
verified: driving the live production seam
(`profile.json` → `_t4b_project_source` → `track_t4b` → `TrustedFacts`), the
two Nord codec subjects resolve to `codec.pcm1681` and `codec.adau1979`, and
the T4b advisory half of **both** generator gates opens. The north-star
scorecard **stays 1/4** on real Nord — B3 does NOT flip it — because
`machine_driver` still closes on `T4a.qup.*` (Gate 2) and `codec_stub` closes
on `T4a.qup.*` (Gate 1); both need WP-SRC-B2's real IPCAT QUP endpoints. After
A2 (T1 pinmux) + B3 (T4b codec), **WP-SRC-B2 alone completes the 1/4 → 3/4
flip** — there is no fourth hidden gate (see the gate audit below).

Gate audit (2026-07-24, source: `machine_driver.py:217-272`,
`codec_stub.py:202-256`):

- `machine_driver` — 5 gates: G1 `T1.gpio.i2s.*` require-open (A2 ✓),
  G2 `T4a.qup.*` require-open (needs B2), G3a `T4b.codec.*` DISAGREE hard-skip
  (passes when no disagreement — default on Nord NCC rows), G3b `T4b.codec.*`
  advisory-open require (B3 ✓), G4 `T2.*` DISAGREE hard-skip (passes when no
  disagreement).
- `codec_stub` — 3 gates: G1 `T4a.qup.*` require-open (needs B2), G2
  `T4b.codec.*` DISAGREE hard-skip (passes by default), G3 `T4b.codec.*`
  advisory-open require (B3 ✓).
- The only REQUIRE-OPEN gate not yet satisfiable by real authority is
  `T4a.qup.*` (both generators). T1 is closed by A2; T4b by B3. The two
  DISAGREE gates (machine_driver G3a/G4, codec_stub G2) are hard-skip-on-
  disagreement — they pass by default and are not authority-open prerequisites.
  → **B2 alone completes the flip.**

### Cross-references

- `audio_bu_skill/orchestrator/reasoning/crossverify.py` `_t4b_row` — post-B3
  emits `subject = f"codec.{_t4b_norm_part(codec)}"` (pre-B3 it emitted
  `f"{codec}<->{controller}"`, the defect).
- `audio_bu_skill/orchestrator/generation/machine_driver.py:240,252-258`
  (Gate 3a / 3b `_rows_with_prefix(facts, "T4b.codec.")`).
- `audio_bu_skill/orchestrator/generation/codec_stub.py:230,250-256`
  (Gate 3 `_rows_with_prefix(facts, "T4b.codec.")`).
- `audio_bu_skill/tests/fixtures/phase2b/nord_trusted_facts.json:132,152`
  and `tests/test_generation_machine.py` `_clean_nord_facts()` (hand-authored
  `T4b.codec.*` keys; pre-B3 these were the only such keys and no producer
  emitted them — post-B3 `_t4b_row` emits the same `codec.<part>` shape).
- `audio_bu_skill/tests/test_source_ingest_endpoints.py`
  `TestJointFlipMachineDriverAndCodecStub` (B-3, 3b form — proves T1 + T4a
  open via the live seam; deliberately does NOT call the generators because,
  pre-B3, the T4b gate was unreachable — reconciled by B3).
- G-3A.7 / G-3A.11 (empty-source-side root cause; those close the T1 + T4a
  halves. G-3A.12 was the *third* gate — the codec-binding half — closed by
  WP-SRC-B3).

