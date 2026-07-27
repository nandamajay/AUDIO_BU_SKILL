# WP-69 — Board-Variant Authority Reconciliation (EVK vs RRD vs RIDE)

**Status:** DESIGN — approved (Option C.1). Implementation NOT started.
**Author track:** advisor-persona review + task #69 evidence audit (this session).
**Depends on:** G-3B-gamma (`0b93a78`, [[g-3b-gamma-committed]]) — SoC-family attestation MATCH is scoped to SoC-family only; board-level compatibles are explicitly out of scope of G-3B-gamma.
**Blocks:** task #64 (disclosure-only enforcement) reviews this WP's new `contributes_rows` shape; task #70 (WP_H-1 projector) consumes the disclosure via a `board_metadata` entity.
**Non-negotiables:** preserve trust chain exactly, no candidate-derived PASS, no profile rewrite, no H-1 work, no G-3B-gamma reopen, no push of `0b93a78`.

Confidence tags per claim: [Certain] = grep-proven / documented; [Likely] = design projection; [Guessing] = ungrounded.

---

## 1. Executive summary

The `machine_driver` lane currently emits `model = "IQ10-EVK";` from a hard-coded module-level constant. That string is not attested by any authority artifact in the skill. The only external source that ever named `IQ10-EVK` is the candidate patch at commit `5267b2e1d7a5` — which fails the standing PROVENANCE GUARD (authority for MATCH/PARTIAL_MATCH must be INDEPENDENT of `5267b2e1`). Meanwhile, the schematic evidence pack under `audio_bu_skill/targets/nord-iq10/evidence/offline/` names **IQ10-RRD**, not EVK. But no ingestion pipeline exists to promote schematic evidence into an authority row.

**Selected remediation:** Option C.1 — emit `model = "FIXME(board_variant): NOT_ATTESTED";` as a machine-parseable placeholder and attach a `T5.sound_card.model.board_variant` disclosure row (`verdict=NOT_CROSS_CHECKABLE`, `coverage_gap_reason=authority_out_of_scope`). This aligns with the existing FIXME + `contributes_rows` convention already in use for I2S8 port-ID (`machine_driver.py:322-346`) and the sound-card driver-match row (`machine_driver.py:365-380`).

**Future direction (deferred, not this WP):** a later board-authority track will introduce `T?.board.variant` rows with a new `SCHEMATIC_DIRECT` authority strength, sourced by parsing the schematic pack. That value then feeds H-1's `board_metadata` entity group once H-1 begins. Not in scope here.

---

## 2. Authority inventory (grep-proven, [Certain])

Every occurrence of `IQ10-EVK`, `IQ10-RRD`, or the module constant `_SNDCARD_MODEL` in the skill:

| # | Location | Line | Value/purpose | Authority class |
|---|---|---|---|---|
| 1 | `orchestrator/generation/machine_driver.py` | 21 | Docstring: `_SNDCARD_MODEL ... at :131/132/135` | Code (docstring) |
| 2 | `orchestrator/generation/machine_driver.py` | 23 | Docstring: `qcom,nord-iq10-sndcard / IQ10-EVK / i2s8_active — a silent wrong-output` | Code (docstring) |
| 3 | `orchestrator/generation/machine_driver.py` | 34 | Docstring: `with model = "IQ10-EVK"` | Code (docstring) |
| 4 | `orchestrator/generation/machine_driver.py` | **144** | `_SNDCARD_MODEL: str = "IQ10-EVK"` | **ACTIVE — module constant** |
| 5 | `orchestrator/generation/machine_driver.py` | **303** | `lines.append(f"\t\tmodel = \"{_SNDCARD_MODEL}\";")` | **ACTIVE — emission site** |
| 6 | `tests/fixtures/phase2b/nord_machine_driver_expected.dtsi` | 14 | `model = "IQ10-EVK";` | Golden fixture (asserts current emit) |
| 7 | `generated/nord-iq10-onboarding-38/machine_driver/nord_sound.dtsi` | 14 | `model = "IQ10-EVK";` | Regenerated artifact (downstream of #4/#5) |
| 8 | `docs/PHASE2B_NORD_PROVENANCE_TABLE.md` | 107, 222 | Historical provenance row | Doc |
| 9 | `docs/PHASE3_KNOWN_GAPS.md` | 838, 888 | Open gap entries — G-3A.13 generality audit | Doc |
| 10 | `docs/PHASE3A_IMPLEMENTATION_PLAN.md` | 59, 69 | Historical plan references | Doc |
| 11 | `targets/nord-iq10/evidence/offline/LD20-94440-0010_17_02_2026 1.pdf` | — | Schematic naming **IQ10-RRD** | Schematic (unwired) |
| 12 | `targets/nord-iq10/evidence/offline/LD20-94441-0010_17_02_2026 1.pdf` | — | Schematic naming **IQ10-RRD** | Schematic (unwired) |
| 13 | `targets/nord-iq10/evidence/offline/IQ10_RRD_IO_Mapping.xlsx` | — | I/O map naming **IQ10-RRD** | Schematic (unwired) |
| 14 | `targets/nord-iq10/evidence/offline/IQ10_Reference_Design_SYSIO_Review_v4.pptm` | — | Reference-design SYSIO review naming **IQ10-RRD** | Schematic (unwired) |
| 15 | `targets/nord-iq10/profile.json` | 73 | Candidate-derived `IQ10-EVK` (passive record) | Passive record (not consumed by generator) |
| 16 | `targets/nord-iq10/qgenie_analysis.json` | 13 | Candidate-derived `IQ10-EVK` (passive record) | Passive record |
| 17 | `targets/nord-iq10/onboarding_report.md` | 77 | Candidate-derived `IQ10-EVK` (passive record) | Passive record |

**Load-bearing sites:** #4 + #5 (source constant + emission). Everything else is either downstream of them (#6, #7) or a passive record (#8-#10, #15-#17), or unwired evidence (#11-#14).

**Authority strengths present today:**
- `IPCAT_DIRECT` — via `chips_list_chips` (SoC-family only). Does NOT attest board variant.
- `KB_RULE` — T5 KB rules (see `crossverify_config.py`). Does NOT attest board variant.
- **No authority tier exists for board-variant identity** (this is the gap).

---

## 3. EVK contamination path (candidate-derived, fails provenance guard)

[Certain — trace grep-proven]

```
candidate commit 5267b2e1d7a5 (arch/arm64/boot/dts/qcom/iq10-evk.dts)
    │
    ├──[PASSIVE]──▶ targets/nord-iq10/onboarding_report.md:77
    │                    │
    │                    └──▶ targets/nord-iq10/qgenie_analysis.json:13
    │                              │
    │                              └──▶ targets/nord-iq10/profile.json:73
    │                                   (passive record — NOT consumed by machine_driver;
    │                                    left untouched by this WP)
    │
    └──[ACTIVE]──▶ developer inlined "IQ10-EVK" into machine_driver.py:144
                     │
                     └──▶ machine_driver.py:303 emit
                              │
                              └──▶ generated/nord-iq10-onboarding-38/
                                    machine_driver/nord_sound.dtsi:14
                                    (the sole load-bearing wrong-output)
```

**Provenance-guard verdict:** the ACTIVE path traces every attested-in-DT string back to `5267b2e1d7a5`. Under the standing PROVENANCE GUARD, this value **cannot** support any MATCH/PARTIAL_MATCH verdict. It must not carry any authority label. Today it carries none (the string is a bare module constant), but it also carries no disclosure — that is the defect this WP closes.

---

## 4. RRD authority path (schematic evidence, unwired)

[Certain — file names verified via `ls`]

Schematic pack at `audio_bu_skill/targets/nord-iq10/evidence/offline/` names **IQ10-RRD**:

- `LD20-94440-0010_17_02_2026 1.pdf` — schematic PDF (LD20-94440)
- `LD20-94441-0010_17_02_2026 1.pdf` — schematic PDF (LD20-94441)
- `IQ10_RRD_IO_Mapping.xlsx` — I/O mapping spreadsheet
- `IQ10_Reference_Design_SYSIO_Review_v4.pptm` — reference-design SYSIO review

**Wiring status:** no ingestion. No parser. No `T?.board.*` producer. No `SCHEMATIC_DIRECT` authority strength in the trust chain. RRD is authoritatively named by schematic evidence but **currently unusable** to open any generator gate.

**Why not just "flip EVK to RRD":** because RRD's route into the trust chain does not yet exist. Substituting the string without wiring the authority producer would swap one unattested value for another. That is out of scope of Option C.1 (and rejected explicitly under Option B in §7).

---

## 5. Four-way conclusion (from the evidence audit)

[Likely for D.1, Certain for D.4]

| Statement | Verdict | Rationale |
|---|---|---|
| **D.1** — One physical board, EVK label is wrong for authorization purposes | **[Likely]** | Schematic pack (4 artifacts) uniformly names RRD; candidate commit is a downstream/derivative artifact; no source outside the candidate commit uses EVK |
| **D.2** — Two physical boards (EVK and RRD both exist) | **[Guessing]** | No evidence of an EVK schematic; possible but unsupported |
| **D.3** — RIDE variant present | **[Guessing]** | Named only in G-3B-gamma design commentary as a "family third label"; no artifact |
| **D.4** — Insufficient evidence for physical variant count | **[Certain]** | Even accepting D.1, we cannot rule out D.2 without further disclosure from Nord silicon owners |

**Best-supported reading:** D.1 + D.4. Even if a reviewer *knows* the board is RRD, the skill itself does not — the authority track is absent. Therefore the correct emission is **not-attested**, not "flip to RRD."

---

## 6. Impact locations (what changes when Option C.1 lands)

[Certain — enumerated by grep]

**Code (1 file):**
- `orchestrator/generation/machine_driver.py` — delete constant `_SNDCARD_MODEL` (line 144); replace with `_MODEL_FIXME_LITERAL = "FIXME(board_variant): NOT_ATTESTED"` and `_BOARD_VARIANT_CONTRIB_SUBJECT = "sound_card.model.board_variant"`. Change emit line 303. Append one new `VerificationRow` to `contributes_rows` in the sound-card block (mirroring the existing `sound_card.driver_match.nord_iq10` row at line 365-380). Rewrite the three docstring references (lines 21, 23, 34).

**Test fixture (1 file):**
- `tests/fixtures/phase2b/nord_machine_driver_expected.dtsi:14` — update golden to `model = "FIXME(board_variant): NOT_ATTESTED";`.

**Existing test files (0-2 files):**
- Any test asserting the exact `IQ10-EVK` literal must be updated. Grep confirms fixture #6 is the primary asserting site; module-level generator tests will be re-run under the new expectation. Full sweep required.

**New test file (1 file):**
- `tests/test_machine_driver_board_variant_not_attested.py` — 6 tests (see §10).

**Generated artifact (1 file, regenerated on next real-Nord run):**
- `generated/nord-iq10-onboarding-38/machine_driver/nord_sound.dtsi:14` — new line contains FIXME literal, plus the disclosure row appears in serialized `contributes_rows`.

**Doc edits (3 files):**
- `docs/PHASE2B_NORD_PROVENANCE_TABLE.md:107,222` — rewrite EVK provenance row from "AGREE" to "NOT_ATTESTED per WP-69."
- `docs/PHASE3_KNOWN_GAPS.md:838,888` — mark the two `_SNDCARD_MODEL = "IQ10-EVK"` gap entries as **RESOLVED-BY-WP-69** with cross-reference to task #70 (H-1) for the long-term authority track. Add a new §G-3A.13.WP-69 sub-heading recording the closure.
- `docs/PHASE3A_IMPLEMENTATION_PLAN.md:59,69` — mark EVK references as historical, point to WP-69.

**New docs (2 files — this WP):**
- `docs/WP_69_BOARD_VARIANT_AUTHORITY.md` (this file)
- `docs/WP_69_DECISION.md` — short-form decision record

**Memory index update (1 file):**
- `MEMORY.md` — add `[WP-69 designed]` entry pointing at a new memory file.

**Not touched (explicitly):**
- `targets/nord-iq10/profile.json` — passive record. Untouched.
- `targets/nord-iq10/qgenie_analysis.json` — passive record. Untouched.
- `targets/nord-iq10/onboarding_report.md` — historical report. Untouched.
- `targets/nord-iq10/profile.json.baseline` — legacy fossil, governed by task #63.
- `orchestrator/reasoning/crossverify.py` — G-3B-gamma stays closed.
- `orchestrator/reasoning/crossverify_config.py` — T5_TARGET_IDENTITY / T5_META_RULES unchanged; scope-exclusion comment at 82-86 remains accurate.
- `orchestrator/generation/model.py` — `is_open()`, `_GATING_OPEN_VERDICTS` untouched.
- `orchestrator/generation/codec_stub.py` — `_rows_with_prefix` untouched.
- `orchestrator/generation/{dt_scaffolding,audioreach_topology,post_verify}.py` — no code change.
- Any Pipeline-2 (`orchestrator/codegen/`) module.
- Any H-1 file (H-1 not yet started per [[h-1-architecture-decision]]).

---

## 7. Rejected options (A, B, D) and why

### Option A — Preserve both EVK and RRD (dual-emit)

**Rejected.** Emits ambiguity into the DT artifact (`model = "IQ10-EVK | IQ10-RRD";` or a comment listing both). Downstream tooling has no rule to disambiguate. Reviewer must still edit before bring-up, so this offers nothing over Option C.1 except added noise. Violates the "no candidate-derived PASS" spirit by keeping EVK in the emitted string.

### Option B — Replace EVK with RRD ("flip the string")

**Rejected.** Two independent failures:

1. **No authority track for the substitution.** Substituting RRD in `_SNDCARD_MODEL` without wiring a `SCHEMATIC_DIRECT` producer trades one unattested value for another. Trust chain is not improved.
2. **Ambiguity vs. count.** Even if D.1 is likely, D.4 remains [Certain]: we do not conclusively know a second physical variant does not exist. Committing RRD would silently authorize a board name the skill cannot cite.

The refutation quoted verbatim to user in the prior turn was accepted: "flip to RRD" is a silent authorization the skill cannot back up.

### Option D — Invent a new board_variant / synthetic name

**Rejected.** Fabricates a value that no authority attests. Directly violates provenance guard.

### Option D.2 (long-term, deferred — NOT this WP)

Introduce a new authority track:

```
T?.board.variant  →  authority_strength = "SCHEMATIC_DIRECT"
                     source = evidence/offline/*.pdf|*.xlsx|*.pptm
                     verdict on match  = MATCH
                     verdict on absent = NCC(authority_out_of_scope)
```

This future WP requires: (a) a schematic parser (PDF/XLSX/PPTX extraction), (b) a KB rule table for board-name shapes, (c) a producer emitting `T?.board.*` rows, (d) integration with `_GATING_ROW_NAMES` for machine_driver's `sound_card.model.board_variant` subject. It is filed as follow-up, sequenced after task #70 (WP_H-1 projector) so that the H-1 `board_metadata` entity group has a real authority feed instead of an eternal disclosure.

**Explicit sequencing:** Option D.2 must NOT begin until #71 (this WP) + #64 (disclosure enforcement) + #70 (H-1) close. Attempting D.2 earlier would either (a) build an authority producer with no downstream consumer, or (b) invite H-1 to consume evidence directly, violating the layered-model rule that H-1 is projector-only [[h-1-architecture-decision]].

---

## 8. Selected option — C.1 (disclosure-first, mirror existing convention)

**Design surface:**

1. **Emit line changes** (`machine_driver.py:303`):
   ```
   lines.append(f'\t\tmodel = "{_MODEL_FIXME_LITERAL}";')
   ```
   where `_MODEL_FIXME_LITERAL = "FIXME(board_variant): NOT_ATTESTED"`.

   The emitted DT string is syntactically legal DT and machine-parseable — any bring-up flow that grep-checks `model = ` finds a FIXME token that cannot be interpreted as a real board name. Reviewer must edit before bring-up.

2. **`contributes_rows` addition** — new `VerificationRow` appended in the same block that emits `sound_card.driver_match.nord_iq10` today:
   ```
   VerificationRow(
       track="T5",
       subject="sound_card.model.board_variant",
       verdict="NOT_CROSS_CHECKABLE",
       coverage_gap_reason="authority_out_of_scope",
       notes=[
           "machine_driver: sound-card `model` field emitted as verbatim "
           "FIXME literal 'FIXME(board_variant): NOT_ATTESTED' because no "
           "independent authority attests the board variant name.",
           "SCOPE: board-variant name (the string that populates `model =`).",
           "NOT_ATTESTED: board_variant. reviewer_required=true.",
           "Candidates present in evidence: (a) IQ10-EVK — appears only in "
           "candidate DTS at commit 5267b2e1d7a5 and downstream records; "
           "fails provenance guard. (b) IQ10-RRD — attested by schematic "
           "PDFs LD20-94440/94441 and IQ10_RRD_IO_Mapping.xlsx in "
           "audio_bu_skill/targets/nord-iq10/evidence/offline/, but no "
           "ingestion pipeline exists to promote schematic evidence into "
           "an authority row.",
           "Reviewer must edit `model =` before bring-up. Follow-up "
           "authority track queued behind WP_H-1_AUDIO_HARDWARE_TEMPLATE_"
           "PROJECTOR (task #70) and a later board-metadata authority WP.",
       ],
   )
   ```

3. **Docstring update** — machine_driver.py header (lines 21, 23, 34) rewritten to describe the NOT_ATTESTED emission and remove `IQ10-EVK` references.

**Invariants preserved [Certain]:**
- No `MATCH` / `PARTIAL_MATCH` verdict introduced anywhere.
- No entry added to `_GATING_OPEN_VERDICTS` or `_GATING_ROW_NAMES`.
- No change to `is_open()` predicate.
- No change to `_rows_with_prefix`.
- New row is disclosure-only per DISCLOSURE-ONLY RULE (task #64 will validate).
- `5267b2e1` appears only inside `notes` prose (descriptive citation), not in `authority`.
- No profile.json rewrite.
- No candidate-derived PASS anywhere.

---

## 9. Trust-chain impact

[Certain]

**Positive changes:**
- Removes the sole active unattested emission from machine_driver output.
- Adds one machine-parseable disclosure that post-verify (WP7) and downstream projector (H-1) can consume.
- Aligns board-variant provenance with existing FIXME conventions already used for I2S8 port-ID (line 322-346) and sound_card.driver_match (line 365-380).

**No changes to:**
- Gating semantics — `is_open()`, `_GATING_OPEN_VERDICTS`, `_GATING_ROW_NAMES` untouched.
- T5 producer — G-3B-gamma's MATCH branch untouched. Board-level compatibles remain out of T5's scope per the KB comment at `crossverify_config.py:82-86`.
- Provenance guard — no new authority claim, no citation of `5267b2e1` as authority.
- Any Pipeline-2 output — `orchestrator/codegen/` remains inert.

**Signal to downstream consumers:**
- machine_driver lane still **EMIT** (not SKIP) — deliberate distinction from the rejected C.2 sub-option that would skip the lane entirely. The pin/DAI-link content of the artifact has real authority and should ship.
- Reviewer disclosure surfaces as a `NOT_CROSS_CHECKABLE` row with `reviewer_required=true` in the disclosure notes.

---

## 10. Acceptance criteria

Before any commit is proposed (commit is out of scope for this WP's *design* stage):

- [ ] `WP_69_BOARD_VARIANT_AUTHORITY.md` (this file) authored and saved. **This WP.**
- [ ] `WP_69_DECISION.md` authored and saved. **This WP.**
- [ ] `PHASE3_KNOWN_GAPS.md` §G-3A.13 entries at lines 838, 888 annotated with WP-69 closure pointer. **This WP.**
- [ ] `MEMORY.md` updated with WP-69 index entry. **This WP.**
- [ ] User signoff on this design before implementation begins.
- [ ] Implementation: 6 new tests in `tests/test_machine_driver_board_variant_not_attested.py`:
  1. `test_model_line_emits_fixme_literal` — output contains `model = "FIXME(board_variant): NOT_ATTESTED";` and does NOT contain `IQ10-EVK` or `IQ10-RRD`.
  2. `test_contributes_rows_carries_board_variant_disclosure` — exactly one row with `subject="sound_card.model.board_variant"`, `verdict="NOT_CROSS_CHECKABLE"`, `coverage_gap_reason="authority_out_of_scope"`.
  3. `test_disclosure_notes_enumerate_candidates_and_evidence` — each of the five load-bearing note lines present verbatim.
  4. `test_disclosure_row_authority_is_absent_or_empty` — `authority is None` or empty on the NOT_CROSS_CHECKABLE row.
  5. `test_generator_does_not_gate_on_board_variant` — Facts bundle without the new subject still emits the artifact (regression: subject NOT added to `_GATING_ROW_NAMES`).
  6. `test_provenance_guard_clean_in_machine_driver` — `5267b2e1` never appears in any authority-constructing string literal in machine_driver.py.
- [ ] Existing generator-machine tests updated to expect the new emit literal.
- [ ] Fixture `tests/fixtures/phase2b/nord_machine_driver_expected.dtsi:14` updated.
- [ ] Byte-identity SHA-256 unchanged for these no-touch files (asserted in `test_no_touch_bytes_identity`):
  - `orchestrator/generation/model.py`
  - `orchestrator/generation/codec_stub.py`
  - `orchestrator/generation/dt_scaffolding.py`
  - `orchestrator/generation/audioreach_topology.py`
  - `orchestrator/generation/post_verify.py`
  - `orchestrator/reasoning/crossverify.py`
  - `orchestrator/reasoning/crossverify_config.py`
- [ ] Provenance-guard grep `grep -n "5267b2e1\|candidate_derived" audio_bu_skill/orchestrator/generation/machine_driver.py` — zero hits in authority-carrying contexts (prose in `notes=` allowed).
- [ ] Full test sweep green (188+ tests + 6 new).
- [ ] Real-Nord run-N smoke: `generated/nord-iq10-onboarding-N/machine_driver/nord_sound.dtsi:14` shows FIXME literal; `contributes_rows` carries the disclosure; machine_driver lane still shows EMIT on scorecard.
- [ ] Post-fix grep `grep -rn "IQ10-EVK" audio_bu_skill/orchestrator/ generated/ audio_bu_skill/tests/fixtures/` returns zero hits.

---

## 11. Validation plan

[Certain — all executable pre-commit]

### 11.1 Unit tests (as files, per [[record-tests-in-tests-folder]])

- **New file:** `tests/test_machine_driver_board_variant_not_attested.py` — 6 tests listed in §10.
- **Existing file:** `tests/test_generation_machine.py` — update whichever tests assert the exact `IQ10-EVK` literal.

### 11.2 Fixture update

- `tests/fixtures/phase2b/nord_machine_driver_expected.dtsi:14` — new golden.
- Grep after change: `grep -n "IQ10-EVK\|IQ10-RRD" tests/fixtures/` → zero hits.

### 11.3 Regression sweep

- Full 188+ module test suite. Expected: all green except the pre-known assertions on the EVK literal, which are updated in this WP.
- T5 producer tests (`test_crossverify_t5.py`, `test_crossverify_t5_positive_attestation.py`) — untouched code, expected 100% pass.
- dt_scaffolding tests (`test_dt_scaffolding_positive_gate.py`) — untouched producer, expected 100% pass.
- codec_stub / audioreach / post_verify tests — untouched code, byte-identity check confirms.

### 11.4 Byte-identity checks

SHA-256 pre- and post-implementation on the 7 files in §10's checklist. Any diff fails the WP.

### 11.5 Real-Nord run-N smoke

Post-implementation, run onboarding-N and verify:
- `generated/nord-iq10-onboarding-N/machine_driver/nord_sound.dtsi:14` line is `model = "FIXME(board_variant): NOT_ATTESTED";`.
- Serialized `contributes_rows` includes the new `sound_card.model.board_variant` row.
- Scorecard shows machine_driver as **EMIT** (not SKIP).
- Post-verify `skip_validity` for the new subject: N/A (not a skip).
- `grep -rn "IQ10-EVK" generated/nord-iq10-onboarding-N/` returns zero hits.

### 11.6 Provenance-guard grep

```
grep -n "5267b2e1\|candidate_derived" audio_bu_skill/orchestrator/generation/machine_driver.py
```

Expected: zero hits in authority context. Any citation of `5267b2e1` inside `notes=[…]` prose is a descriptive reviewer note, not an authority claim; test #6 in §10 validates this.

---

## 12. Sequencing & follow-ups

[Likely — proposed ordering, awaiting user confirmation]

1. **This WP (#71 / #69 remediation) — DESIGN done, implementation queued.** Land the FIXME + disclosure. Immediate provenance win.
2. **Task #64 — disclosure-only enforcement.** Validates that the new row does not round-trip into `cross_verification.rows`. Must complete before H-1.
3. **Task #70 — WP_H-1_AUDIO_HARDWARE_TEMPLATE_PROJECTOR.** Projector emits `board_variant: {value: null, disclosure: "NOT_ATTESTED", reviewer_required: true}` in the `board_metadata` entity group. Still projector-only, still no authority. Blocked behind #64 and this WP.
4. **Future WP (Option D.2) — schematic-parse board authority track.** Reads schematic pack, emits `T?.board.variant` rows with `SCHEMATIC_DIRECT` authority strength. Under that track, RRD gains real authority; H-1's projector then carries the attested value. Filed as follow-up in the WP-69 tracker; no task number yet.

---

## 13. Related memory / cross-references

- [[g-3b-gamma-committed]] — SoC-family attestation MATCH scope; board-level compatibles explicitly out of scope of G-3B-gamma
- [[h-1-architecture-decision]] — Display-team layered model; H-1 is projector-only, template never becomes authority
- [[record-tests-in-tests-folder]] — user preference: tests as files, not ad-hoc
- [[advisor-persona-directive]] — standing behavioural directive
- `docs/WP_G-3B-gamma_DT_SCAFFOLDING_DESIGN.md` §5 — hard-coded non-authorization disclosure line for board-level compatibles

---

**End of design.** Awaiting user signoff before implementation.
