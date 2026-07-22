# WP-F ESM-Integrity Addendum — DRAFT

**STATUS: DRAFT — NOT PROMOTED.**

This file is a *candidate* design revision for WP-F. It has **not** been
promoted into `WP_F_DESIGN_REVISION.md` and is **not** normative. It captures
a real hazard (ESM under-specification) and two candidate defenses, preserved
verbatim so a future author does not have to re-derive them.

**Why it is not promoted:** `PHASE3_ARCHITECTURE.md` §10 (committed at
`9a3f467`) gates all design past WP-G on real Coverage Reports from Nord and
Eliza — *"Do not proceed past WP-G until two independent onboarding runs on
Nord and one on Eliza have populated real Coverage sections and been
reviewed."* No such runs exist yet (no `expected_subjects.json` exists for
either target as of 2026-07-22). Hardening this design layer pre-emptively,
before WP-D/E/F/G ship, walks away from that evidence-first discipline. The
hazard is real; the priority to defend it *now* is not established.

**Promote this draft to a real revision ONLY IF** the failure mode surfaces
during the post-WP-G two-week evidence window (§10) OR during any Nord/Eliza
ESM authoring review. Do not promote pre-emptively. Tracked as **G-3A.2** in
`docs/PHASE3_KNOWN_GAPS.md`.

---

## STEP 0 verification result (so a future reader need not re-verify)

**CASE A confirmed: the schema invariant is a construction-time check.**

`fact_requirements/schema.py:234–241` lives inside
`FactFamilyDef.__post_init__` (method opens at schema.py:181; the next member,
the `qualified_name` property, begins at schema.py:244 — so 234–241 are
unambiguously inside `__post_init__`). `FactFamilyDef` is declared
`@dataclass(frozen=True)` (schema.py:156–157). A dataclass invokes
`__post_init__` automatically at the end of `__init__`, i.e. on every
instantiation. The block:

```python
# Critical families must have at least one MANDATORY subject — otherwise
# nothing keeps the family from PASSing with an empty registry.
if self.critical and not any(
    s.requiredness is Requiredness.MANDATORY for s in self.subject_requirements
):
    raise ValueError(
        f"FactFamilyDef {self.qualified_name!r} is critical but declares "
        f"zero MANDATORY subjects"
    )
```

**raises `ValueError` at model construction.** It is not a helper, not a
test-only assertion, not a docstring convention. A `critical=True` family with
zero MANDATORY subjects cannot be instantiated — the catalog module would fail
to import. This is what makes the §1.7.2 "theorem, not a heuristic" language
below hold: for a critical family, `required = {}` is structurally impossible
*unless the ESM is under-specified relative to the catalog*.

Incidental naming note for implementation time: the real accessor is
`FactFamilyDef.mandatory_requirements()` (schema.py:248), not the
`mandatory_subject_requirements()` used in the §1.7.3B pseudocode below —
cosmetic fix, not a rigor issue.

Catalog anchors confirmed the same session: `Audio.POWER` declares `VDD_LCX`
and `VDD_LMX` as **literal** (`is_regex=False`) MANDATORY subjects
(catalog/audio.py:170–178); `Audio.DSP_TOPOLOGY` / `Audio.MBHC_THRESHOLD` are
advisory-only (zero MANDATORY).

---

## Placement decision (as drafted)

Chosen at draft time: append a new **§1.7** to `WP_F_DESIGN_REVISION.md` (plus
surgical edits to §1.5, §6.2, §6.3, §7, §8), **not** a separate promoted file —
because the addendum must *edit* the §7 gate table and §6.2 test list in place,
and a separate file could only restate-and-fork them. (Moot while unpromoted;
recorded for whoever promotes it.)

## Contradictions with the committed revision (to resolve at promotion)

1. **Supersedes `WP_F_DESIGN_REVISION.md` §1.5** — the sentence mapping
   *"ESM_DECLARED_EMPTY for a **critical** family → treated as OBSERVED_GAP."*
   Under this draft a critical family can never reach `ESM_DECLARED_EMPTY`
   (schema invariant: always ≥1 MANDATORY subject); its empty/under-covered
   case is the stricter `ESM_UNDERSPECIFIED → OBSERVED_BLOCKED`.
2. **Narrows (does not contradict) `PHASE3_ARCHITECTURE.md:613` / §5.5** —
   `ESM_DECLARED_EMPTY → OBSERVED_ADVISORY` is retained but scoped to
   advisory-only (zero-MANDATORY) families (`DSP_TOPOLOGY`/`MBHC_THRESHOLD`).
3. **Naming reconciliation** — revision §6.2 `T-F-ZERO-MANDATORY` and
   architecture-doc `T-F-DECLARED-EMPTY` are the same scenario. Canonical
   name: `T-F-DECLARED-EMPTY` (matches the normative sync target).

---

## §1.7 ESM under-specification and manifest integrity (draft text)

### 1.7.1 The failure mode: ESM under-specification

§1 makes the per-target Expected-Subject Manifest
(`targets/<t>/expected_subjects.json`) the sole source of the coverage
denominator. That correctly kills the vacuous-100% defect (M-1/F-1). But it
relocates the trust: the denominator is now only as honest as the hand-authored
ESM. A single authoring omission reopens the false-green:

> If the Nord ESM omits `VDD_LCX`/`VDD_LMX` from `Audio.POWER.expected_subjects`
> (copy-paste slip, incomplete authoring, or a stubbed-out entry), then
> `required(POWER, Nord) = {}`. Under the committed §5.5 mapping an empty
> `required` set renders `ESM_DECLARED_EMPTY → OBSERVED_ADVISORY` — a
> **non-gate green**. Gate 2 (§6.3), whose whole job is to catch
> `POWER`/`AUDIOREACH_PORT` reading complete on Nord, then **passes falsely**:
> the reviewer sees advisory-green, not a gap, because the gap was defined away
> before the engine ran.

This is **ESM under-specification**: the manifest declares (by omission or
empty stub) that a family needs fewer — or zero — MANDATORY subjects than the
catalog says it does. The engine is correct; the *denominator input* is
silently wrong. The committed design has no defense: it trusts the ESM's
`required` set unconditionally.

What makes Gate 2 **fail-silent**: Gate 2 inspects *rendered verdicts* for
known-incomplete families. Under-specification produces `OBSERVED_ADVISORY` (or
`OBSERVED_COMPLETE` at a fake 1/1 — see 1.7.5), indistinguishable on the report
surface from a legitimately-advisory or legitimately-complete family. The
reviewer has nothing to catch. The absence is not *rendered as* absence.

### 1.7.2 Why the catalog can adjudicate this (theorem, not heuristic)

`fact_requirements/schema.py` (`FactFamilyDef.__post_init__`, lines 234–241)
forbids a `critical=True` family from declaring zero MANDATORY subjects —
construction fails (verified CASE A, above). Two consequences make the defense
exact:

- Every critical family has a **non-empty, catalog-fixed set of MANDATORY
  subject patterns**. `Audio.POWER` ⊇ `{VDD_LCX, VDD_LMX}` (both literal,
  `is_regex=False`).
- Therefore, for a critical family, an empty or MANDATORY-incomplete
  `expected_subjects` is **not a lawful state** — it is provably a manifest
  defect, because the catalog asserts subjects the ESM fails to enumerate.

The catalog cannot enumerate *instances* (H-1 still holds — that is why we have
the ESM). But it *can* enumerate the MANDATORY *patterns* each family must
satisfy. The ESM must cover every such pattern; failing that is decidable
without knowing the board.

### 1.7.3 Two composing defenses

**(A) Process defense — the "ESM authoring review" gate (new, BLOCKING, fires
before Gate 2).** Before Gate 2 may be discharged for a target, a reviewer
signs, per target, that:
1. every catalog family with `critical=True` has a **non-empty**
   `expected_subjects` set (an advisory-only family may be empty **only** with a
   documented `basis`, per 1.7.6);
2. for every MANDATORY `SubjectRequirement` in the catalog, the ESM contains at
   least one `expected_subjects` entry that **matches its pattern** (literal
   equality when `is_regex=False`; `re.fullmatch` when `is_regex=True`);
3. the known **trap subjects** are present — Nord: `VDD_LCX`, `VDD_LMX`, the
   I2S8 logical port (`Audio.AUDIOREACH_PORT`), codec I2C + reset
   (`Audio.CODEC_BINDING`); Eliza: *to be enumerated at Eliza ESM authoring —
   placeholder, must be filled before Eliza's gate can sign*.

**(B) Engineering defense — ESM-vs-catalog cross-reference in the loader.**
`orchestrator/coverage/esm.py` (the pure loader/validator,
`PHASE3_ARCHITECTURE.md:593`) gains a catalog cross-reference at load time,
*before* any coverage arithmetic. For each family:

```
mand := catalog MANDATORY SubjectRequirements for this family      # non-empty iff critical
covered(r) := ∃ s ∈ esm.expected_subjects .
                (r.is_regex ? re.fullmatch(r.subject_pattern, s) : s == r.subject_pattern)

if mand ≠ ∅ and ¬∀ r ∈ mand : covered(r):
    esm_state := ESM_UNDERSPECIFIED
    uncovered := [ r.subject_pattern for r ∈ mand if ¬covered(r) ]
    note      := "ESM does not cover MANDATORY subject pattern(s): " + uncovered
    verdict   := OBSERVED_BLOCKED           # coverage n/a; never ADVISORY, never COMPLETE
```

The cross-reference runs **before** `present`/`required` are formed, so an
under-specified family never reaches the arithmetic that could render it green.
This is the backstop for a process-gate miss, and the machine record that makes
the process gate auditable.

### 1.7.4 New ESM state: `ESM_UNDERSPECIFIED`

Enum grows from `PRESENT | ESM_MISSING | ESM_DECLARED_EMPTY` to
`PRESENT | ESM_MISSING | ESM_DECLARED_EMPTY | ESM_UNDERSPECIFIED`. Distinct
from both neighbors:

- **≠ `ESM_MISSING`.** `ESM_MISSING` is *file-level* absence — no
  `expected_subjects.json` at all → the whole target is un-evaluable.
  `ESM_UNDERSPECIFIED` is a *family-level* defect in a **present** file.
  Folding them would tell an operator who *did* write a manifest that they wrote
  none, and hide *which* family is the problem.
- **≠ `ESM_DECLARED_EMPTY`.** `ESM_DECLARED_EMPTY` is a *lawful, justified*
  claim that a family legitimately needs nothing (only possible for a
  zero-MANDATORY advisory family, with a `basis`). `ESM_UNDERSPECIFIED` is
  *unlawful or unaudited* emptiness. Folding them lets the false-green back in.
  The two states must diverge at the verdict — `DECLARED_EMPTY →
  OBSERVED_ADVISORY`, `UNDERSPECIFIED → OBSERVED_BLOCKED`.

`ESM_UNDERSPECIFIED` **always** renders `OBSERVED_BLOCKED`;
`mandatory_subject_coverage_pct` is `null` (n/a). It is a **manifest-integrity
block, not a coverage gate** — see 1.7.7.

### 1.7.5 The partial-underspec trap (why "1/1 = 100%" must not win)

Subtler variant: ESM lists `Audio.POWER.expected_subjects = ["VDD_LCX"]`,
omitting `VDD_LMX`. Naïve arithmetic sees `present = {VDD_LCX}`,
`required = {VDD_LCX}`, `1/1 = 100% → OBSERVED_COMPLETE` — the vacuous-100%
defect resurrected through a *shrunken* denominator. The cross-reference
(1.7.3B) fires **first**: `VDD_LMX ∈ mand` uncovered →
`ESM_UNDERSPECIFIED → OBSERVED_BLOCKED`, note `"…VDD_LMX"`. The family never
reaches the `1/1` arithmetic. T-F11 (monotonicity) does not cover this, because
a shrunken-but-full denominator is monotone and still wrong.

### 1.7.6 The `basis` discipline

`ESM_DECLARED_EMPTY` is valid **only** when the ESM entry explicitly sets
`expected_subjects: []` **and** provides a non-empty `basis` string **and** the
family has zero catalog MANDATORY subjects. A basis-less empty (or a family
absent from an otherwise-present ESM) is **`ESM_UNDERSPECIFIED`, not
`ESM_DECLARED_EMPTY`** — an empty set is a *claim* ("this family lawfully needs
nothing"), and an unaudited claim is not a denominator we trust. For a
MANDATORY-bearing family the `basis` cannot rescue emptiness at all: the catalog
outranks the manifest (1.7.2).

### 1.7.7 Reconciling with advisory-never-gates (locked doctrine C-4 / F-3)

One deliberate divergence from the reviewer's literal framing. Blocking an
*advisory-only* family on a basis-less empty could read as gating an advisory
family — which the doctrine forbids. It does not, because
`ESM_UNDERSPECIFIED → OBSERVED_BLOCKED` here is a **block on the manifest, not
on coverage**: it says "this ESM entry is not trustworthy enough to evaluate —
add a `basis`," discharged by a one-line manifest edit. Advisory-never-gates
governs a family's *coverage verdict*, downstream of a valid manifest; the
integrity block sits *upstream* of coverage. Once the `basis` is present, the
advisory family renders `OBSERVED_ADVISORY` and gates nothing. Both rules hold,
at different layers.

---

## Surgical edits to existing sections (draft — apply at promotion)

- **§1.5** — append supersede pointer: *"(Superseded by §1.7: a `critical=True`
  family cannot be `ESM_DECLARED_EMPTY`; its empty/under-covered case is
  `ESM_UNDERSPECIFIED → OBSERVED_BLOCKED`, stricter than OBSERVED_GAP.)"*
- **§6.2** — add three tests (design only; land as `tests/test_*.py` at
  implementation, per project discipline):
  - `T-F-ESM-UNDERSPECIFIED` (new, blocking): Nord ESM present; `Audio.POWER`
    `expected_subjects: []`, no `basis`; catalog MANDATORY `{VDD_LCX, VDD_LMX}`.
    Assert `esm_state == ESM_UNDERSPECIFIED`, `verdict == OBSERVED_BLOCKED`,
    `mandatory_subject_coverage_pct is None`, note names both patterns, never
    ADVISORY, never COMPLETE. Companion: same entry *with* `basis` is still
    `ESM_UNDERSPECIFIED` (catalog outranks basis).
  - `T-F-ESM-UNDERSPEC-CATALOG-CROSSREF` (new, blocking): `Audio.POWER
    expected_subjects = ["VDD_LCX"]` (LMX omitted), `basis` present. Assert
    `esm_state == ESM_UNDERSPECIFIED`, note `"…VDD_LMX"`, `verdict ==
    OBSERVED_BLOCKED`; never `OBSERVED_COMPLETE` despite a computable 1/1.
  - `T-F-DECLARED-EMPTY` (extended, blocking; absorbs `T-F-ZERO-MANDATORY`):
    advisory-only family (`Audio.DSP_TOPOLOGY`). (a) `[]` **with** basis →
    `ESM_DECLARED_EMPTY → OBSERVED_ADVISORY`; (b) `[]` **without** basis →
    `ESM_UNDERSPECIFIED → OBSERVED_BLOCKED`.
- **§6.3 / §7** — new gate row `1b. ESM authoring review` (blocking, before
  Gate 2); Gate 2 annotated "conditional on gate 1b having fired first."
- **§8** — clarify: ESM *authoring* (who writes the file) stays out-of-scope;
  ESM *integrity checking* (process gate + engine cross-reference) is in-scope
  for Phase-3A. "Who writes the ESM" (out) vs "does WP-F trust the ESM blindly"
  (in — it does not).
- **`PHASE3_ARCHITECTURE.md` sync** — enum (line 174), state defs (204–210),
  esm.py note (593), test names (613).

---

## Diff-style summary (if promoted)

- **ADDED:** §1.7 (1.7.1–1.7.7); `T-F-ESM-UNDERSPECIFIED`,
  `T-F-ESM-UNDERSPEC-CATALOG-CROSSREF`; §7 gate row 1b.
- **MODIFIED:** §1.5 supersede line; §6.2 `T-F-ZERO-MANDATORY` → extended
  `T-F-DECLARED-EMPTY` (basis required); §6.3 Gate 2 conditional; §7 Gate 2
  annotation; §8 scope paragraph; `PHASE3_ARCHITECTURE.md` enum/defs/notes.
- **UNCHANGED:** ESM-as-denominator model, `present ⊆ required`, surplus rule,
  null-when-empty pct, §2 mapping, §2.2 corroboration, §3 banner, §4 rendering,
  §5 vocabulary, §6.1 T-F-DENOM theorem.
- **No implementation.** State, cross-reference, and tests are designed, not
  written.
