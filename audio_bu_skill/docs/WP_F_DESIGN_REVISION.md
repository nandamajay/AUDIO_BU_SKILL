# WP-F Coverage Engine — Design Revision

**Status:** design revision only. No code, no commits. Supersedes the parts of
`docs/PHASE3_ARCHITECTURE.md` §5/§8 that this document overrides; those sections
must be edited to match before WP-F implementation begins.
**Date:** 2026-07-22
**Responds to:** `docs/WP_F_DESIGN_REVIEW.md` (findings M-1/F-1/H-1, H-2, C-1,
M-2/M-3, F-2, F-3/F-4).
**Grounded in:** `fact_requirements/catalog/audio.py`, `fact_requirements/loader.py`,
`fact_requirements/schema.py`, `fact_requirements/fact_freshness.yaml`,
`orchestrator/fact_registry/models.py` (FactKey/FactValue/FactProvenance),
`docs/PHASE3_LANDSCAPE.md` §1/§4 (trust doctrine + 7-level emission hierarchy),
`docs/PHASE3_KNOWN_GAPS.md` G-3A.1, `targets/nord-iq10/phase1b_resolution.json`.

---

## 0. What this revision changes, and why it is required

The review returned one **blocking** finding, two **high** findings, and three
**medium** findings. The blocking finding (M-1/F-1/H-1) is a correctness defect:
the coverage denominator, as originally specified, can manufacture a `PASS` at
`100%` on trivial evidence. No amount of test coverage fixes this — it is a
model error, not a bug. This revision replaces the defective model.

The user requirement is explicit: **every blocking and high-severity finding
must be satisfied by the design before implementation begins.** The six required
outputs map onto the findings as follows, and each is delivered in its own
section below.

| Required output | Section | Findings closed |
|---|---|---|
| 1. Target-specific denominator model | §1 | **M-1 / F-1 / H-1 (blocking)**, H-2 (high), M-4, M-5 |
| 2. 7-trust-level → 4-axis mapping table | §2 | **C-1 (high)**, C-2, C-3 |
| 3. Registry provenance banner specification | §3 | F-2 (medium) |
| 4. Coverage/conflict/confidence rendering contract | §4 | M-2 / M-3 (medium), F-3 (medium) |
| 5. PASS/WARN/FAIL vocabulary recommendation | §5 | F-4 (medium) |
| 6. Validation plan proving no vacuous 100% | §6 | proves §1; strengthens T-F1/T-F11 |

§7 is a consolidated pre-merge gate list (which of the review's six manual gates
each section discharges). §8 states what remains explicitly out of scope.

---

## 1. Target-specific denominator model  (closes M-1/F-1/H-1, H-2)

### 1.1 The defect, restated precisely

`coverage_pct = present_subjects / required_subjects`. The original design
derived `required_subjects` from the catalog. But the catalog's subjects are
**regex patterns** — `MI2S[0-9]+_(SCK|WS|SD0|SD1|SD2|SD3)`, `AR_PORT_[A-Z0-9_]+`,
`ICC_[A-Z0-9_]+_TO_[A-Z0-9_]+` (`catalog/audio.py:47,277,302`). A pattern has no
cardinality. The catalog does not know Nord uses I2S8, or how many interconnect
paths are live. So the denominator collapses to either "count of matched facts"
(→ `present/present = 100%`, the false-PASS generator) or a static per-pattern
guess (→ undercount of absence). Both are numbers about the *shape of the
catalog*, not the *completeness of this board*.

### 1.2 The fix: an explicit per-target Expected-Subject Manifest (ESM)

The denominator must not be inferred. It must be **declared, per target, and
reviewed.** WP-F consumes a new artifact:

```
targets/<target>/expected_subjects.json
```

The ESM is the authoritative statement of *what concrete subjects THIS board is
expected to have*. It is the only legitimate source of the coverage denominator.
It is authored by a human during onboarding (or emitted by a future
manifest-builder WP, out of scope here) and reviewed — it is not machine-guessed
from patterns.

**Shape (illustrative — the schema is defined in WP-F's spec, not here):**

```
{
  "target": "nord-iq10",
  "resolved_chip": "nordschleife_2.0",          # cross-checked vs phase1b_resolution.json
  "manifest_provenance": "reviewer|derived|seed",
  "families": {
    "Audio.GPIO": {
      "expected_subjects": ["MI2S8_SCK", "MI2S8_WS", "MI2S8_SD0", ...],
      "basis": "Nord IQ-10 I2S8 pinmux (nord-iq10-audio-facts)"
    },
    "Audio.POWER": {
      "expected_subjects": ["VDD_LCX", "VDD_LMX"],   # the trap: still-open FIXMEs
      "basis": "LPASS core+mem rails; FIXME open"
    },
    ...
  }
}
```

### 1.3 Denominator rule (normative)

For a family `F` on target `T`:

- **`required(F,T)` = the set of ESM `expected_subjects` for `F` whose catalog
  `Requiredness` is `MANDATORY`.** Each ESM subject is matched against the
  family's `SubjectRequirement`s (literal equality, or `is_regex` match) to
  determine its requiredness. ADVISORY/OPTIONAL ESM subjects are counted
  separately and never enter the mandatory denominator.
- **`present(F,T)` = the subset of `required(F,T)` for which the registry holds a
  live (non-revoked) FactValue.** Present is always a subset of required — a fact
  whose subject is *not* in the ESM is **surplus**, reported on its own line, and
  **never inflates `coverage_pct`** (this is what kills Option A's `present/present`).
- `absent(F,T) = required(F,T) \ present(F,T)`.
- `mandatory_subject_coverage_pct = |present| / |required|`, **defined only when
  `|required| > 0`.** When `|required| == 0` the percentage is `undefined` and
  MUST render as `n/a`, never `100%` (this is the F-3 fix, §4.4).

Consequence: a family with an unknown expected set has **no ESM entry**, so
`required` is undefined, so it **cannot report 100%**. It reports
`ESM_MISSING` (§1.5) — an explicit gap, not a silent pass. The empty-set-is-
trivially-satisfied hazard is structurally impossible.

### 1.4 H-2: `soc_override` no-op is quarantined

`loader.load_catalog(soc_override=None)` is a documented no-op — Nord and Eliza
share one catalog (`loader.py:36-46`). That is acceptable **for the catalog**
(it defines fact *shape*), but it is the reason a shared denominator would
cross-contaminate targets. The ESM removes the dependency: the denominator now
comes from `targets/<target>/expected_subjects.json`, which is per-target by
construction. The catalog stays shared; the *cardinality* is per-target. WP-F
MUST refuse to compute `coverage_pct` from the catalog alone even if an ESM is
absent — see §1.5.

### 1.5 What WP-F does when the ESM is absent or partial

Registry-absent must never raise (existing contract), and the same floor applies
to the ESM:

- **No ESM file for `T`** → every family reports `coverage_state = ESM_MISSING`,
  `coverage_pct = n/a`, verdict `OBSERVED_GAP` (§5). The report is still produced.
- **ESM present but a family has no entry** → that family reports `ESM_MISSING`
  for its denominator; other families compute normally.
- **ESM entry present but `expected_subjects` empty for a critical family** → this
  is a *declared* empty set, distinct from an *unknown* one. It renders as
  `ESM_DECLARED_EMPTY` and, for a critical family, is treated as `OBSERVED_GAP`
  (a critical family is not expected to have zero mandatory subjects; a declared
  empty set is a manifest smell, surfaced not hidden).

The distinction `ESM_MISSING` (we don't know) vs `ESM_DECLARED_EMPTY` (a human
said zero) vs `n/a` for genuinely advisory families (§4.4) is deliberate and must
be visible in the report.

### 1.6 M-4 and M-5 fall out of §1.3

- **M-4** (`mandatory_subject_coverage_pct` inherits the denominator problem): it
  now shares the ESM denominator, so it is target-specific and honest, or `n/a`.
- **M-5** (monotonicity is necessary but not sufficient): with a fixed ESM
  denominator, adding a PRIMARY fact for an ESM subject raises `present` by one
  against a **stable** denominator, so coverage rises *from below 100%* on a
  genuine-gap fixture. T-F11 is strengthened accordingly in §6.

---

## 2. 7-trust-level → 4-axis mapping table  (closes C-1, C-2, C-3)

The confidence weights key off the coarse `AuthorityClass`
(`schema.py`: PRIMARY/FALLBACK/MANUAL/INFERRED), while the locked doctrine ranks
seven **concrete emission authorities** (`PHASE3_LANDSCAPE.md` §4). The two tables
were never reconciled; C-1 requires that every emission level have a defined home
in the four axes. Here is the normative mapping.

| # | Emission trust level (doctrine) | Coverage axis | Confidence weight | Freshness axis | Conflict axis |
|---|---|---|---|---|---|
| 1 | REVIEWER-INPUT (resolved FIXME) | PRESENT (counts toward `present`) | MANUAL weight **1.5**; capped 0.4 if `!has_evidence` (`models.py:568`) | `manual` TTL | may participate in CONFLICT like any fact |
| 2 | IPCAT-DIRECT | PRESENT | PRIMARY **3.0** | `ipcat_live` / `ipcat_cached` TTL | — |
| 3 | IPCAT-DIRECT+MISMATCH | PRESENT **+ `corroboration_state = MISMATCH`** (see §2.2) | PRIMARY **3.0** (value = IPCAT's; IPCAT wins) | IPCAT TTL | **NOT** folded into `conflict_debt`; carried as a distinct non-blocking flag |
| 4 | UPSTREAM-BINDING | PRESENT | FALLBACK **2.0** | `kernel_bindings` TTL | — |
| 5 | NORD-PATCH corroboration | PRESENT **+ `corroboration_state = CORROBORATED`** | FALLBACK **2.0** | `kernel_dts` TTL | — |
| 6 | FIXME-REVIEWER (unresolved) | **ABSENT** (an open FIXME is not a present fact) | n/a (no fact) | n/a | n/a |
| 7 | INFERRED-ARCH | PRESENT, but **caps family at WARN/`OBSERVED_PARTIAL`** | INFERRED **1.0** | `inferred` TTL (`fresh_seconds:0`) | — |

### 2.1 The MANUAL/FALLBACK weight inversion is deliberate — stated, not accidental

The doctrine ranks REVIEWER-INPUT as the **highest** emission authority, yet its
confidence weight (1.5) sits **below** FALLBACK (2.0). This is intentional and
must be documented as such: **authority ≠ confidence.** Authority answers "who
gets to decide the value" (a reviewer's resolved FIXME is final for emission).
Confidence answers "how independently verifiable is this datum" — an
unverifiable human assertion is, by the WP-E cap (`models.py:568`), clamped to
≤0.4. The two axes measure different things; the inversion is the correct
expression of that. WP-F's spec must carry this sentence verbatim so a future
reader does not "fix" the table into agreement.

### 2.2 MISMATCH gets a home: `corroboration_state`, not `conflict_debt` (C-1, C-2)

The doctrine's Tier-2 `IPCAT-DIRECT+MISMATCH` (IPCAT and schematic disagree,
IPCAT wins, **non-blocking**) had no representation in the four axes. Folding it
into `conflict_debt` over-escalates a non-blocking flag; ignoring it loses the
signal. Resolution: add a **per-subject `corroboration_state`** enum, orthogonal
to the conflict axis:

- `SOLE` — one authority, no corroborator.
- `CORROBORATED` — a second, lower-or-equal authority agrees on the value
  (doctrine level 5; this is the C-2 fix — corroboration was previously invisible,
  both states collapsing to "PRESENT").
- `MISMATCH` — a corroborator disagrees, but the higher authority's value stands
  (doctrine level 3). Rendered as a **non-blocking flag**, never as conflict.

`conflict_debt` remains reserved for **same-authority-tier disagreement on the
identical `FactKey`** (`models.py` FactProvenance chain comparison), which *is*
blocking-relevant. MISMATCH and CONFLICT are now distinct and cannot be confused.

### 2.3 MANUAL-satisfied critical family capped at WARN (C-3) — with an expiry

§6.3/T-F5's rule (a manual-only critical family caps at WARN/`OBSERVED_PARTIAL`)
stands for Phase-3A and is now stated as a **deliberate, expiring** choice, not an
implicit one: a reviewed fact earns full `OBSERVED_COMPLETE` only once the gap
"when does REVIEWER-INPUT earn PASS?" is answered by the WP that closes G-3A.1
(live acquisition), because only then can a reviewer's value be corroborated
against a live authority. Until then, conservatism holds. This expiry condition
is recorded in `PHASE3_KNOWN_GAPS.md` as a cross-reference.

---

## 3. Registry provenance banner specification  (closes F-2)

G-3A.1 means the registry is **not populated from live IPCAT** in Phase-3A — the
first real WP-F run executes against an empty or hand-seeded registry
(`PHASE3_KNOWN_GAPS.md`). The danger is the *middle* state: a partially seeded
registry that lights up a few PASS families and reads as "coverage works" when it
is measuring a stub. Every report MUST carry an unmissable banner.

### 3.1 Banner is mandatory, top-of-report, and computed — not decorative

The banner is the **first** element of every CoverageReport, before any family
line. It is computed from the registry + ESM, never hand-set. It states three
provenance facts:

```
╔═══════════════════════════════════════════════════════════════════════╗
║ REGISTRY PROVENANCE — read before trusting any number below            ║
║   Population:   HAND_SEEDED         (3 of 11 families have any fact)    ║
║   Live IPCAT:   NOT ACQUIRED        (G-3A.1 open — no LIVE_IPCAT_VERIFIED)║
║   Denominator:  ESM present         (targets/nord-iq10/expected_subjects)║
║   ⇒ Coverage numbers describe a PARTIAL registry. Absence of a fact     ║
║     here means "not yet recorded", NOT "confirmed absent in hardware".  ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### 3.2 Population-state enum (normative)

Computed over the target's families:

- `EMPTY` — no facts for any family. All families → `OBSERVED_GAP`/BLOCKED floor.
- `HAND_SEEDED` — some facts exist, but **zero** carry an `IPCATLiveRef`
  (`models.py` source_refs). This is the Phase-3A default and MUST be labelled so.
- `IPCAT_POPULATED` — at least one fact carries `LIVE_IPCAT_VERIFIED` provenance.
  Unreachable in Phase-3A (G-3A.1); the enum value exists so the banner does not
  need a schema change when the gap closes.

### 3.3 Live-IPCAT line ties to the WP7 tri-state

The banner's "Live IPCAT" line reads the same tri-state WP7 already renders
(`LIVE_IPCAT_VERIFIED` / `CACHED_IPCAT_ONLY` / `NO_IPCAT_EVIDENCE`,
`PHASE3_KNOWN_GAPS.md:123`). In Phase-3A it will read `NOT ACQUIRED` /
`CACHED_IPCAT_ONLY`. WP-F does not invent a new state; it surfaces the existing
one at the top of the report.

### 3.4 Gate

The banner rendering is a **BLOCKING gate for any external sharing** (review gate
§7.4): a reviewer confirms the banner renders and reads correctly on an
`EMPTY`, a `HAND_SEEDED`, and (fixture-simulated) an `IPCAT_POPULATED` registry
before any WP-F output leaves the team.

---

## 4. Coverage / conflict / confidence rendering contract  (closes M-2/M-3, F-3)

The four axes must never collapse to one badge, and confidence must never paper
over absence. This section is the normative rendering contract WP-G MUST honor;
it is stated here because the defect (M-2/M-3) is a *presentation* hazard that
originates in how WP-F emits the numbers.

### 4.1 Coverage and confidence are bound on one line, always

A family line renders all three quantities **adjacently and inseparably**:

```
Audio.GPIO   coverage 4/6 (67%)   confidence 0.71 [of the 4 present]   conflict 0   corrob 3✓/1?
                       ▲ denominator from ESM        ▲ present-only, stated explicitly
```

- `coverage` shows `present/required` as a **fraction first**, percentage second.
  The fraction makes absence visible in a way a bare percentage hides.
- `confidence` carries the qualifier `[of the N present]` **in the line itself**,
  not a footnote. This is the M-2 fix: the number's scope is inseparable from the
  number. A high confidence over one present subject can never read as "this
  family is complete" when `coverage 1/6` sits immediately to its left.
- A renderer MUST NOT emit `confidence` without the adjacent `coverage` fraction.
  This is a hard constraint restated in WP-G's spec (per review C-4).

### 4.2 M-3: conflict is visible independently of confidence

Zeroing a conflicting subject's weight (§5.3) correctly stops a hot conflict from
bumping the confidence mean — but then a disputed subject contributes nothing in
either direction, so a family with three conflicts can show a confidence
identical to one with zero. Fix: **`conflict` is its own always-present column**,
never inferable from confidence. A subject in dispute increments the `conflict`
count *and* is listed by name in the family's detail block. Confidence and
conflict are read together or the report is malformed.

### 4.3 Corroboration column (from §2.2)

`corrob N✓/M?` shows corroborated vs mismatched present subjects. This is where
Tier-2 MISMATCH and Tier-2 CORROBORATION become visible (C-2). MISMATCH renders
as a non-blocking `?`, never as a conflict `✗`.

### 4.4 F-3: advisory and zero-mandatory families render distinctly

`DSP_TOPOLOGY` and `MBHC_THRESHOLD` are `critical=False`
(`catalog/audio.py:364,389`) with zero MANDATORY subjects. They MUST NOT render
green next to earned green:

- Advisory families render with an explicit `advisory — not gated` tag and
  `coverage n/a` (never `100%`).
- Any critical family whose ESM `required` set is empty renders `ESM_DECLARED_EMPTY`
  (§1.5), not `100%`.
- The verdict column for advisory families reads `OBSERVED_ADVISORY`, a fourth
  vocabulary term (§5) that is visually distinct from `OBSERVED_COMPLETE`.

No green in the report is unearned: every green traces to a non-empty ESM
denominator fully covered by present facts.

---

## 5. PASS / WARN / FAIL vocabulary recommendation  (closes F-4)

Phase-3A is informational-only, yet `PASS` in a report is behaviorally an
authorization signal to a human skimming it. **Recommendation: adopt observation
vocabulary now, and reserve PASS/WARN/FAIL for the day a gate actually consumes
the verdict.**

| Old (enforcement) | New (observation) — Phase-3A | Meaning |
|---|---|---|
| PASS | `OBSERVED_COMPLETE` | every MANDATORY ESM subject present; not capped |
| WARN | `OBSERVED_PARTIAL` | some present, some absent; or capped by INFERRED/MANUAL rule |
| FAIL | `OBSERVED_GAP` | no MANDATORY present, or ESM missing for a critical family |
| (none) | `OBSERVED_ADVISORY` | advisory family; never gated (§4.4) |
| BLOCKED | `OBSERVED_BLOCKED` | registry empty → cannot observe (existing floor) |

Rationale: the words describe *what was seen*, not *what is permitted*. When a
future gate consumes coverage, it can map `OBSERVED_COMPLETE → PASS` explicitly at
the gate boundary — the observation vocabulary makes that mapping a deliberate,
reviewable act rather than an implicit inheritance. This is the review's F-4
recommendation adopted as the default rather than deferred.

This is a **non-blocking, recommended** change per the review, but adopting it now
is materially cheaper than renaming after downstream code reads the word `PASS`.

---

## 6. Validation plan — proving vacuous 100% cannot occur  (proves §1)

Monotonicity (old T-F11) is necessary but not sufficient (M-5): if the
denominator equalled matched-fact count, adding a fact keeps coverage at 100% the
whole way — monotonic and meaningless. The validation plan is rebuilt around the
ESM denominator so the false-PASS generator is provably dead.

### 6.1 The anti-vacuity theorem (the one that must hold)

> **T-F-DENOM (blocking).** For every critical family `F` and target `T`,
> `coverage_pct(F,T)` is either `n/a` (when `required(F,T)` is undefined —
> ESM missing) or a fraction `|present| / |required|` where `required` is the
> ESM-declared MANDATORY set, **independent of `present`**. There exists **no**
> code path where the denominator is derived from, or varies with, the count of
> matched facts.

This is proven by construction (§1.3: `required` reads only the ESM; `present` is
`required ∩ registry`) and pinned by the tests below.

### 6.2 Rewritten / new tests (the T-F* suite)

- **T-F1 (rewritten).** `OBSERVED_COMPLETE`/100% is asserted **only** on a fixture
  whose ESM declares a **non-vacuous** MANDATORY set (≥2 subjects) that is fully
  present. The old "all-mandatory-present → PASS" wording is deleted because it
  encoded the hazard when "all mandatory" was pattern-derived.
- **T-F-VACUOUS (new, blocking).** A fixture with **one** GPIO fact whose subject
  is **surplus** (not in the ESM) MUST report `coverage 0/6` (or the ESM count),
  **never `1/1`**. This is the direct false-PASS regression test.
- **T-F-ESM-MISSING (new).** No ESM for the target → every critical family reports
  `coverage n/a`, verdict `OBSERVED_GAP`; the run does not raise.
- **T-F-SURPLUS (new).** A fact for a subject outside the ESM increments the
  `surplus` line and does **not** change `coverage_pct`.
- **T-F11 (strengthened).** Adding a PRIMARY fact for an ESM MANDATORY subject
  raises coverage **from below 100% toward 100%** on a genuine-gap fixture, and
  the denominator is **byte-stable** across the addition (asserted explicitly).
- **T-F-ZERO-MANDATORY (new, F-3).** `DSP_TOPOLOGY`/`MBHC_THRESHOLD` and any
  `ESM_DECLARED_EMPTY` critical family report `coverage n/a`, verdict
  `OBSERVED_ADVISORY`/`OBSERVED_GAP` respectively — **never `100%`**.
- **T-F-MISMATCH (new, C-2).** A subject with an IPCAT value and a disagreeing
  schematic value reports `corroboration_state = MISMATCH`, `conflict_debt`
  **unchanged** (non-blocking), verdict not escalated.
- **T-F-CORROBORATED (new, C-2).** IPCAT + agreeing NORD-PATCH → `CORROBORATED`,
  distinct from `SOLE`.

### 6.3 The two real-run inspection gates (BLOCKING, human, not automated)

The review is explicit that the automated suite is necessary but not sufficient.
Two human gates block merge:

1. **Denominator provenance sign-off.** A reviewer confirms on paper, for
   `Audio.GPIO` on Nord specifically, that `required` comes from
   `targets/nord-iq10/expected_subjects.json` and **not** from matched-fact count.
   If the answer is "matched-fact count," WP-F does not merge.
2. **Nord + Eliza trap-case inspection.** Run `evaluate()` against both targets'
   registries and read the full report. Nord's open `VDD_LCX`/`VDD_LMX`
   (`catalog/audio.py:170,177`) and the I2S8 logical-port FIXME
   (`catalog/audio.py:285`) are built-in traps: `Audio.POWER` and
   `Audio.AUDIOREACH_PORT` MUST **not** read `OBSERVED_COMPLETE` on Nord. A
   reviewer signs that no critical family shows complete-coverage that they know
   to be incomplete.

---

## 7. Consolidated pre-merge gate discharge

Mapping the review's six manual gates (WP_F_DESIGN_REVIEW §5) to this revision:

| Review gate | Discharged by | Blocking? |
|---|---|---|
| 1. Denominator provenance sign-off | §1 (ESM) + §6.3 gate 1 | **Blocking** |
| 2. Nord + Eliza real-run inspection | §6.3 gate 2 | **Blocking** |
| 3. Golden confidence-table review | §2 table frozen as golden values in T-F suite | Blocking on regression |
| 4. Registry-population disclosure | §3 banner + §3.4 gate | **Blocking for external sharing** |
| 5. Verdict-vocabulary review | §5 (adopted now) | Non-blocking (recommended, adopted) |
| 6. Doctrine-mapping walkthrough | §2 table (all 7 levels have a home; MISMATCH → §2.2; inversion → §2.1) | **Blocking** |

Every blocking and high-severity finding has a corresponding normative section
and at least one blocking gate or test. Implementation may begin **only after**
this revision is reviewed and `PHASE3_ARCHITECTURE.md` §5/§8 are edited to match.

---

## 8. Explicitly out of scope for this revision

- **The ESM builder.** How `expected_subjects.json` gets authored (reviewer by
  hand vs a future manifest-derivation WP) is not specified here. WP-F **consumes**
  the ESM; it does not produce it. Producing it is a candidate follow-on WP.
- **Live IPCAT acquisition.** G-3A.1 stays open. This revision makes the registry's
  unpopulated state honest (§3), it does not close the gap.
- **Gate enforcement.** The observation vocabulary (§5) is deliberately not wired
  to any gate. The day a gate consumes coverage is a separate WP with its own spec.
- **Code.** No code was written and nothing was committed. This is a design
  revision only.
