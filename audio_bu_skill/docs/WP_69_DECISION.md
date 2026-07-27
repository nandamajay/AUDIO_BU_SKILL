# WP-69 — Decision Record

**Task:** #69 — Board-variant authority reconciliation (EVK / RRD / RIDE).
**Date recorded:** 2026-07-27.
**Decision status:** APPROVED by user (advisor-persona review, Option C.1).
**Implementation status:** NOT STARTED. Documentation must land first.

---

## 1. The question

The `machine_driver` generator emits `model = "IQ10-EVK";` from a module-level constant. Should the skill:

- **A.** Preserve both EVK and RRD in the emit line (dual disclosure)?
- **B.** Replace EVK with RRD?
- **C.** Emit a NOT_ATTESTED disclosure (no board name)?
- **D.** Invent a new synthetic board_variant?

---

## 2. The decision

**Option C.1 — NOT_ATTESTED disclosure using the existing FIXME + `contributes_rows` convention.**

- Emit line becomes `model = "FIXME(board_variant): NOT_ATTESTED";`.
- One new `VerificationRow` appended to `contributes_rows` with:
  - `track = "T5"`
  - `subject = "sound_card.model.board_variant"`
  - `verdict = "NOT_CROSS_CHECKABLE"`
  - `coverage_gap_reason = "authority_out_of_scope"`
  - Notes enumerating (a) the EVK contamination path via candidate `5267b2e1`, (b) the RRD-naming schematic evidence in `evidence/offline/`, (c) reviewer_required=true, (d) pointer to the future board-authority track.
- No modification to `_GATING_ROW_NAMES` — this is a disclosure, not a gate.
- No modification to `is_open()`, `_GATING_OPEN_VERDICTS`, `_rows_with_prefix`.
- No modification to `crossverify.py`, `crossverify_config.py`, or profile.json.

---

## 3. Why (uncomfortable truth first)

1. **The current `IQ10-EVK` emission is candidate-derived.** It traces to commit `5267b2e1d7a5`. Under the standing PROVENANCE GUARD, no MATCH/PARTIAL_MATCH verdict may be authored on a value whose only source is that candidate. Today the emit line carries no verdict at all — it is a bare module constant — which is worse than a bad MATCH because there is no disclosure whatsoever.
2. **Schematic evidence names RRD, not EVK.** But no producer parses schematics into authority rows. Substituting RRD without wiring the authority track would trade one unattested value for another.
3. **We cannot conclusively count physical variants.** Even if IQ10-RRD is the true reference board, we lack evidence to rule out a distinct EVK variant. Committing either name silently authorizes a claim the skill cannot cite.
4. **The generator has a working convention for this exact case.** `machine_driver.py` already emits `FIXME(i2s8_port_id)` + `contributes_rows` for the port-ID uncertainty and `sound_card.driver_match.nord_iq10` for the driver-match uncertainty. Option C.1 mirrors that convention. Zero novelty in the fix.

---

## 4. Rejected options and why

- **A. Preserve both:** ambiguity in emitted DT; reviewer must still edit; no gain over C.
- **B. Flip to RRD:** silent substitution without authority. Fails provenance guard the same way EVK does — it just swaps which name is unattested.
- **D. Invent a new name:** fabrication; direct provenance-guard violation.

**Deferred (D.2, not this WP):** a future schematic-parse authority track (`T?.board.variant`, `SCHEMATIC_DIRECT` strength) that ingests the `evidence/offline/*.pdf|*.xlsx|*.pptm` files. That track sequences behind task #70 (WP_H-1 projector); it does not belong in Option C.

---

## 5. Non-negotiables from user directive (verbatim spirit)

- Do NOT replace EVK with RRD.
- Do NOT preserve both values.
- Do NOT invent a board variant.
- Preserve trust chain exactly.
- No candidate-derived PASS.
- No profile rewrite.
- No H-1 work yet.
- No G-3B-gamma reopen.
- Do not push `0b93a78`.
- Documentation must land before implementation.

---

## 6. Selected remediation summary (one-liner)

Emit `model = "FIXME(board_variant): NOT_ATTESTED";` from `machine_driver` and disclose the gap via a `T5.sound_card.model.board_variant` `NOT_CROSS_CHECKABLE` row. Mirror the existing FIXME + `contributes_rows` convention. No new authority tier. No gate change.

---

## 7. Future authority-track proposal (deferred — filed for tracking only)

Introduce a `T?.board.variant` producer that reads schematic evidence:

```
Source:       audio_bu_skill/targets/<target>/evidence/offline/*.{pdf,xlsx,pptm}
Producer:     new orchestrator module (parser + KB rules)
Authority:    SCHEMATIC_DIRECT (new authority strength tier)
Rule ids:     kb.rule:board.variant.schematic_direct.<subrule>
Consumer 1:   machine_driver.py — replaces the FIXME disclosure with a real value
Consumer 2:   H-1 projector — populates board_metadata.board_variant
```

**Sequencing:** does not begin until:
- WP-69 lands (this WP)
- Task #64 lands (disclosure-only enforcement)
- Task #70 lands (WP_H-1 projector)

Attempting the schematic-parse track earlier would either build a producer with no consumer, or invite H-1 to consume evidence directly (violating the layered-model rule that H-1 is projector-only, per [[h-1-architecture-decision]]).

---

## 8. Acceptance summary (see full plan in [WP_69_BOARD_VARIANT_AUTHORITY.md](WP_69_BOARD_VARIANT_AUTHORITY.md))

- 2 new docs: this file + WP_69_BOARD_VARIANT_AUTHORITY.md.
- 2 existing doc updates: PHASE3_KNOWN_GAPS.md (annotate G-3A.13 closure); MEMORY.md (add WP-69 index entry).
- Implementation (deferred to next authorized step): 1 file source change (machine_driver.py), 1 fixture, 6 new tests, 3 doc annotations.
- 7 no-touch files (SHA-256 byte-identity asserted): model.py, codec_stub.py, dt_scaffolding.py, audioreach_topology.py, post_verify.py, crossverify.py, crossverify_config.py.
- Provenance grep: 0 hits for `5267b2e1` in authority-carrying code post-fix.

**Stop before commit** — per user directive.
