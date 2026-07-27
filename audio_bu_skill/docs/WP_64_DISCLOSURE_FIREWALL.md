# WP-64 — disclosure-only firewall

**Status:** implemented (tests added; existing generator + facts code
already conformant).
**Scope:** disclosure-only enforcement audit + tests. Design first, no
authority-track work, no board-authority-track (H-1) work.
**Related WPs:** WP-69 (board_variant NOT_ATTESTED disclosure — the concrete
disclosure family that exposed the four gaps below).

---

## 1. The firewall the user asked for, in one picture

```
                 ┌──────────────────────────────────────┐
                 │        Reasoning subsystem            │
                 │  (crossverify, cardinality, ledger)   │
                 └──────────────┬───────────────────────┘
                                │ writes ONCE, at main.py:1192
                                │   gc["cross_verification"] = {"rows": [...]}
                                ▼
      ─────────  A U T H O R I T Y   S T O R E  ─────────
                gc["cross_verification"]["rows"]
      ────────────────────────────────────────────────────
                                │
                                │ read via project_facts(rows)
                                │   (main.py:567)
                                ▼
                 ┌──────────────────────────────────────┐
                 │           TrustedFacts                │
                 │      rows_by_track_subject            │
                 └──────────────┬───────────────────────┘
                                │
                                │ passed to each generator lane
                                ▼
                 ┌──────────────────────────────────────┐
                 │            Generation                 │
                 │  (dt_scaffolding, machine_driver,     │
                 │   codec_stub, audioreach_topology)    │
                 └──────────────┬───────────────────────┘
                                │ emits
                                ▼
                 ┌──────────────────────────────────────┐
                 │        GeneratedArtifact              │
                 │  ├─ bytes_          (target file)     │
                 │  └─ contributes_rows                  │
                 │        list[VerificationRow]  ← disclosure only
                 └──────────────┬───────────────────────┘
                                │
                                │ post_verify may inspect these rows
                                │   for reviewer disclosure display
                                │   ONLY. Never merges them back into
                                │   the authority store.
                                ▼
                 ┌──────────────────────────────────────┐
                 │      TrustedFacts  (unchanged)        │
                 │      rows_by_track_subject            │
                 └──────────────────────────────────────┘
                                │
                                ▼
                          Reviewer + renderer
                          (main.py:1618 renderer consumes
                           contributes_rows for disclosure UI)
```

**Firewall = the arrow from `GeneratedArtifact.contributes_rows` back to
`TrustedFacts` does not exist.** The disclosure slot is a *leaf* in the
data-flow — it feeds the reviewer view and only the reviewer view.

### Why disclosure rows cannot cross the firewall

Four independent layers, any one of which is sufficient:

1. **Structural — VerificationRow itself.** Every disclosure row is built
   with `verdict="NOT_CROSS_CHECKABLE"` (NCC) and
   `coverage_gap_reason ∈ {authority_out_of_scope, …}`.
   `VerificationRow.__post_init__` enforces the biconditional
   `coverage_gap_reason ⇔ verdict==NCC`. An NCC row cannot be silently
   reshaped into a MATCH.

2. **Authority normalization.** Disclosure rows carry no live authority.
   The `authority=` kwarg defaults to `None`, which
   `VerificationRow.__post_init__` normalizes to
   `{"strength": "UNAVAILABLE", "origin": "none"}`. There is no candidate
   value in the authority slot to promote.

3. **Verdict gate.** The gating verdict set is
   `_GATING_OPEN_VERDICTS = frozenset({"MATCH", "PARTIAL_MATCH"})`
   (`generation/model.py:46`). NCC is not in the set, so
   `TrustedFacts.is_open()` cannot open a gate on a disclosure row even if
   the row were somehow injected into the authority store.

4. **Data-flow.** `project_facts` (`generation/facts.py:77`) reads a
   single list of `VerificationRow` objects and knows nothing about
   `contributes_rows`. There is no code path from
   `GeneratedArtifact.contributes_rows` back into
   `gc["cross_verification"]["rows"]` — the single writer of that key is
   `main.py:1192`, before generation runs.

Any single layer is enough. The four together make the firewall
overdetermined: three layers can rot simultaneously and the fourth still
holds.

---

## 2. What was audited (Turn 1)

Task #64 asked for a disclosure-only enforcement audit covering:
`NOT_ATTESTED`, `NOT_CROSS_CHECKABLE`, `authority_out_of_scope`, and the
WP-69 `sound_card.model.board_variant` row.

Five questions:

1. Can any disclosure-only row accidentally influence MATCH /
   PARTIAL_MATCH / gate opening / generation planning / crossverification
   authority?
2. Identify all disclosure-only row producers.
3. Trace all consumer paths.
4. Prove disclosures cannot become authority.
5. Identify any remaining violations.

Findings summary (evidence pointers, not repeated derivation):

* **Producers.** Four generator lanes, all under
  `orchestrator/generation/`:
  - `machine_driver.py:363,416,440` — I2S8 port placeholders + WP-69
    board_variant + missing driver_match row.
  - `audioreach_topology.py:340-395` — single unconditional T5
    topology_blob row.
  - `codec_stub.py:260-385` — one row per unknown codec.
  - `dt_scaffolding.py:270-350` — one row per missing pin.
  All rows share the shape `NCC + authority_out_of_scope` +
  no live authority.

* **Consumers.** `contributes_rows` is read exclusively at
  `main.py:1618` (reviewer renderer). It is never assigned back into
  `gc["cross_verification"]["rows"]`.

* **Firewall proof.** Four-layer stack in §1 above.

* **Four remaining violations / gaps** (α, β, γ, δ):

  | id | gap | disposition |
  | --- | --- | --- |
  | α | No contract test asserts `project_facts` is blind to `contributes_rows`. Silent regression risk. | **Closed** — `test_disclosure_firewall.py::test_project_facts_source_ast_free_of_contributes_rows` |
  | β | Reverse-import asymmetry — no guard on generators importing verifier modules. | **Closed** — `test_disclosure_firewall.py::test_reasoning_subsystem_free_of_disclosure_and_generation_imports` + `test_generator_import_guards.py` (per-lane) |
  | γ | `VerificationRow.from_dict` rehydrates `contributes_rows` as `[]` — round-trip loses disclosures. | **Deferred to WP-64.2** — read-side impact only, no authority risk |
  | δ | `board_variant` subject is a free-form string, not in a closed enum. Typos would silently forge new subjects. | **Deferred to WP-64.2** — cosmetic today, requires enum design |

---

## 3. What WP-64.1 (this WP) ships

Two new test files, one new doc file. No production code change:

* **`tests/test_disclosure_firewall.py`** — 5 tests
  * (A) AST scan of `generation/facts.py` for `.contributes_rows`
    attribute access → must be zero.
  * (B) grep + AST scan of every `orchestrator/reasoning/*.py` for
    `contributes_rows` literals and `orchestrator.generation` imports →
    both must be zero.
  * (C) AST scan of `orchestrator/main.py` for
    `gc["cross_verification"]["rows"] = ...` assignments → must be
    exactly one.
  * (D) runtime idempotence — `project_facts(rows)` after generation
    still equals `project_facts(rows)`; disclosures don't re-enter
    authority.
  * (E) negative fixture — a poisoned rows list DOES land the fake row
    in the projection, so tests A-D measure a real invariant, not
    vacuous behavior.

* **`tests/test_generator_import_guards.py`** — 5 tests (4 per-lane +
  1 parametrized redundancy). Each generator lane's reasoning imports
  MUST be the single-member set `{orchestrator.reasoning.crossverify_model}`.

* **`docs/WP_64_DISCLOSURE_FIREWALL.md`** — this file.

---

## 4. Test acceptance criteria (approved, unchanged)

1. `tests/test_disclosure_firewall.py` — 4 tests minimum. All pass on
   master HEAD without any production code change. (Ship as 5: 4 core
   + 1 negative-fixture proof.)
2. Per-lane import guard test asserting no generator imports
   `orchestrator.reasoning.crossverify` module. (Ship as
   `tests/test_generator_import_guards.py`.)
3. Negative-fixture regression proving contamination WOULD be detectable
   if the firewall broke. (Ship as
   `test_negative_fixture_contamination_would_be_detectable` in the
   disclosure firewall file — inline with the positive tests rather than
   in a separate file, so the two invariants are read together.)
4. Documentation: `WP_64_DISCLOSURE_FIREWALL.md` with the four-layer
   firewall, four gaps, and ASCII flow diagram. (This file.)
5. Existing test suite still green.

---

## 5. Non-goals (explicit)

* No H-1 (audio hardware template) work.
* No board-variant authority track (that is WP-69's follow-up, blocked
  behind H-1).
* No production code change to `generation/facts.py`, generators, or
  the reasoning subsystem. WP-64.1 is a test-and-audit WP — the
  firewall was already correct; this WP proves it and pins it against
  regression.
* Gaps γ (`from_dict` round-trip) and δ (subject enum) are explicitly
  deferred to WP-64.2. Both are read-side / cosmetic; neither can turn
  a disclosure into authority under the current architecture.

---

## 6. If the firewall ever fails

The most likely regression path is: a well-meaning contributor sees
`GeneratedArtifact.contributes_rows` and thinks "let me feed these back
into `gc["cross_verification"]["rows"]` so downstream stages see the
disclosures." That single line — anywhere in `main.py` or any generator
runner — turns a disclosure into authority.

Detection:

* Test A catches it if the writer lives in `facts.py`.
* Test B catches it if a reasoning module tries to read
  `contributes_rows`.
* Test C catches it if a new writer of `gc["cross_verification"]["rows"]`
  appears in `main.py`.
* Test D catches it at runtime — the idempotence claim fails.
* The negative-fixture test (E) proves D is not vacuous.

Together: the firewall is defended structurally, statically, and at
runtime, and the runtime check is proven to be measuring the real
invariant.
