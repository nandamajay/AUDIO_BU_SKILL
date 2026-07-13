# WP-C — Cardinality Authority: Implementation Report

**Milestone:** WP-C Complete (Track C, pre-SWI)
**Status:** implemented · validated · all tests green · **uncommitted** (awaiting approval)
**Scope contract honored:** additive rendering only · diagnostic-only · no promotion / onboarding-decision / gating / schema / SWI / catalog-population changes.

---

## 1. Pre-flight gate (re-verified before writing code)

Per the standing gate, all three docs were re-read and the blocker re-checked:

- `docs/WP_C_PREFLIGHT_GAP_ANALYSIS.md` — original blocker: no machine-countable
  `dt` / `evidence` / `proposal` counts on real data; list length ≠ instance
  count; `dt_count` structurally 0 (unapplied) with no field to record that fact
  → WP-C would have emitted false `disagree`.
- `docs/FIX_A_ELEMENT_COUNTS_SCHEMA_DESIGN.md` — the additive `element_counts`
  schema (1.3.0) designed to unblock exactly this.
- `docs/FIX_A_IMPLEMENTATION_REPORT.md` — Fix A implemented, validated, green;
  Nord run produced 6 element_counts rows, Eliza 8.

**Verification result: PASS.** The real, current artifacts carry trustworthy
typed integers on every lane WP-C needs, plus the two discriminators (`dt_applied`,
`ambiguous`) that resolve the original blocker:

| target | rows | discriminators observed |
|--------|------|-------------------------|
| nord-iq10 | 6 | every class `dt_applied:false` (unapplied at HEAD); `audioreach_port ambiguous:true` |
| eliza | 8 | `dsp_subsystem_instance dt:1/dt_applied:true` (applied — proves the discriminator works both directions); `soundwire_master evidence:3/proposal:1/ambiguous:true`; `dmic_line evidence:8` (≠ `len(mics)`=2); `amplifier evidence:2` (≠ `len(amplifiers)`=1) |

The instance-count-≠-part-count bug the pre-flight flagged is directly observable
in the real Eliza data and is now representable, so the gate is genuinely cleared,
not merely assumed.

---

## 2. Modified / added files

| file | change |
|------|--------|
| `orchestrator/reasoning/cardinality_config.py` | **new** — C.1/C.8 element-class config: 8 classes (6 spec-canonical + `amplifier`/`speaker` the real runs emit), each with `applicable_sources` (which lanes are a legitimate count) + `divergence_rule` (KB C.5 registry) + matcher-intent description. Pure accessors. |
| `orchestrator/reasoning/cardinality.py` | **new** — pure, deterministic comparison core. `compare_element_counts(gc)` → per-class `{element_class, counts, verdict, rule_id, ambiguous, ambiguity_note, warning, notes, citations}`. Verdict vocabulary agree / disagree / not_cross_checkable / benign_divergence / disagree_with_authority. |
| `orchestrator/main.py` | **+2 imports, +1 render fn, +1 wire-in.** `_render_cardinality_section(gc)` (additive, diagnostic-only, null-guarded, returns `[]` when no element_counts) inserted after `_render_confidence_ledger(gc)` and before `## Promotion`. |
| `tests/test_cardinality.py` | **new** — 20 pure-function tests (config integrity, full verdict truth table, both correctness rules, post-SWI authority path, sanitized Nord/Eliza regression fixtures, additive-only + ledger non-interference, determinism, config-order). |

**Not touched (scope compliance):** `schemas.py` (no schema change — WP-C consumes
1.3.0 as-is), the promotion path, `_run_target_onboarding` decision logic, any
gating predicate, IPCAT, the SWI/catalog lane (declared but never populated),
`ledger.py` (`element_counts` was already in `FIELD_DOMAIN_EXCLUDED`).

---

## 3. Design — how the two correctness rules are enforced

The two failure modes the pre-flight predicted are handled in `_usable_lanes` /
`_verdict` (both pure), before any comparison:

1. **`dt_applied:false` + `dt:0` is not a usable count.** Such a `dt` lane is
   dropped from the cross-check (with a transparent note), because 0-because-
   unapplied-at-HEAD is not the same claim as 0-instances-on-silicon. This is what
   keeps Nord — where *every* class is unapplied — at zero false warnings.
2. **`ambiguous:true` → `not_cross_checkable`**, evaluated first, regardless of
   the lane integers. A number the reasoning pass itself disowned must not be used
   to manufacture agreement *or* disagreement. (Test `test_ambiguity_beats_benign_divergence`
   proves ambiguity precedence even over a registered KB divergence rule.)

Two further doctrine points from the KB / spec:

- **`soundwire_master` excludes `dt`** as an authority (`soundwire.md` SWR-P1 /
  provenance: master count is *not* DT-inferred). A `dt` value present for that
  class is reported-but-excluded.
- **SWR-D1 legitimate divergence:** a genuine `evidence` vs `proposal` mismatch on
  `soundwire_master` (count vs routing) downgrades from a `disagree` warning to an
  informational `benign_divergence` citing `SWR-D1` — *unless* the row is also
  ambiguous, in which case ambiguity wins.

---

## 4. Test results

```
tests.test_cardinality ............................ 20/20 PASS
Full suite (22 modules) ........................... ALL GREEN
```

Every other module (confidence ledger, schema 1.1/1.3, onboarding wiring,
similarity, codegen, KB lint, etc.) still passes unchanged.

---

## 5. Nord before/after

- **Before:** no `## Cardinality Authority` section in the onboarding report.
- **After:** 6 rows, **0 warnings**.

| class | usable counts | verdict |
|-------|---------------|---------|
| soundwire_master | evidence=0, proposal=0 | agree |
| lpass_macro_instance | evidence=0, proposal=0 | agree |
| dai_link | proposal=2 | not_cross_checkable |
| audioreach_port | proposal=2 | not_cross_checkable |
| dsp_subsystem_instance | proposal=1 | not_cross_checkable |
| amplifier | evidence=0, proposal=0 | agree |

All `dt` lanes (0/unapplied) correctly excluded → no spurious `disagree`. The
three `not_cross_checkable` rows are exactly the classes with only a single usable
lane — reported honestly rather than silently implying agreement.

---

## 6. Eliza before/after

- **Before:** no section.
- **After:** 8 rows, **0 warnings**.

| class | usable counts | verdict |
|-------|---------------|---------|
| soundwire_master | evidence=3, proposal=1 | not_cross_checkable (ambiguous) |
| lpass_macro_instance | proposal=2 | not_cross_checkable |
| dai_link | proposal=2 | not_cross_checkable |
| dmic_line | evidence=8, proposal=8 | **agree** |
| audioreach_port | proposal=2 | not_cross_checkable |
| dsp_subsystem_instance | dt=1, proposal=1 | **agree** |
| amplifier | evidence=2, proposal=2 | **agree** |
| speaker | evidence=2, proposal=2 | **agree** |

This is the payoff case: `dmic_line` cross-checks 8-vs-8 (a fact invisible to the
old `len(mics)`=2 list length), `amplifier` 2-vs-2 (invisible to `len(amplifiers)`
=1), and the applied `dsp_subsystem_instance` (`dt:1`) legitimately participates
because `dt_applied:true`. The ambiguous `soundwire_master` is held at
`not_cross_checkable` rather than firing a false `disagree` on 3-vs-1.

---

## 7. Rendered example (sanitized — all five verdicts)

```
| Element class | Counts (lane→n) | Verdict | KB rule | Notes |
|---------------|-----------------|---------|---------|-------|
| soundwire_master | evidence_count=3, proposal_count=1 | ℹ️ not_cross_checkable | — | ambiguous: 1 or 2 masters; dt_count=0 present but not an authority for this class |
| dai_link | proposal_count=2 | ℹ️ not_cross_checkable | — | dt_count=0 is unapplied-at-HEAD (dt_applied=false), not an instance count |
| dmic_line | evidence_count=8, proposal_count=8 | ✅ agree | — | dt_count=0 present but not an authority for this class |
| amplifier | dt_count=2, evidence_count=3, proposal_count=2 | ⚠️ disagree | — | — |
```

(A `benign_divergence` row appears when a non-ambiguous `soundwire_master` has
`evidence≠proposal`; a `disagree_with_authority` row appears once a post-SWI
`catalog` count differs — both proven in the test suite.)

---

## 8. Additive-only / non-interference proof

- **Section omitted when absent:** `compare_element_counts` returns `[]` for any
  case with no `element_counts` (pre-1.3.0), so `_render_cardinality_section`
  returns `[]` and the report is byte-unchanged for older runs.
- **Confidence ledger byte-identical:** verified on both real targets and in a
  unit test — adding `element_counts` leaves every ledger row unchanged
  (`element_counts` stays in `FIELD_DOMAIN_EXCLUDED`).
- **Determinism:** identical input → identical rows; rows always emitted in
  config order regardless of the order the reasoning pass listed them.
- **No decision/promotion/gating reader:** nothing outside the render path calls
  into `cardinality.py`.

---

## 9. Risks & limitations

- **Pre-SWI has no ground truth (by design).** `agree` means lanes *concur*, never
  that the count is *correct*; two lanes can agree and both be wrong. The wording
  in the rendered header states this explicitly.
- **Matcher precision is inherited, not re-derived.** WP-C consumes the reasoning
  pass's pre-computed lane counts rather than running its own DT/evidence
  extractors (per spec §7, the `dmic_line`/`audioreach_port` *matchers* are
  postponed until a run exercises them). A miscount upstream is faithfully
  cross-checked, not corrected — the divergence surfaces only if a *second* lane
  disagrees.
- **`catalog` lane is inert.** Declared and handled end-to-end (tests prove the
  authority path), but never populated until Track D / SWI. No behavior today.
- **Two extra classes (`amplifier`, `speaker`)** were added to the config because
  the real runs emit them; they are plain config rows and the spec's C.8
  extensibility contract explicitly anticipates this.

---

## 10. Recommendation for next milestone

WP-C is the last pre-SWI Track C step. The natural next checkpoints, in order:

1. **SWI Probe** (Track D lane 1): populate `catalog_count` from the SWI catalog.
   WP-C already handles the authority path — this is purely additive data, no
   redesign. Expect prior `not_cross_checkable` rows (Nord's three, Eliza's four)
   to upgrade to `agree` / `disagree_with_authority` as authority arrives.
2. **Ledger-gated readiness predicate** (spec line 240): only after SWI, when a
   real authority can make a domain genuinely CORROBORATED. Explicitly *not now*.

**Do not commit automatically** — awaiting approval. Proposed commit grouping is
shown alongside `git status` below.
