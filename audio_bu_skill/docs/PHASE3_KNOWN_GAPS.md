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
