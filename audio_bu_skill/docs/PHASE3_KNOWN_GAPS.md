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

