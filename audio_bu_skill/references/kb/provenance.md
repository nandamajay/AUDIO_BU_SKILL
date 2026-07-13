# KB: provenance (root authority)

## Scope

Cross-cutting provenance and trust rules for **every** per-silicon and per-board
audio fact the onboarding reasoner may emit. This file is the root authority: all
other KB files defer here by rule ID rather than restating provenance. It answers,
generically, "for any class of hardware fact, where does the authoritative value
come from, and what must never be substituted for it?" — never what any specific
target's value is.

## Rules

- **PROV-001 (anti-copy):** A per-silicon value (register base, IRQ number,
  clock rate, SID, instance count) must **never** be copied or interpolated from
  a nearest, sibling, or family-member target. The absence of a target's own
  value is `MISSING` — never "reuse the neighbour's."
- **PROV-002 (authority order):** Authoritative-source precedence for a
  per-silicon value is, in order: the target's own catalog/enumeration source >
  the target's own boot/runtime evidence > the target's own kernel device tree >
  (nothing — otherwise `MISSING`). Prose and family documentation are **never** a
  source for a per-silicon *value* — only for topology/family relationships.
- **PROV-003 (surface routing):** Route each question to the surface that can
  answer it. Instance/register/rate/count questions go to an enumeration/catalog
  surface; topology/family/"which-parts-pair" questions go to a prose surface. Do
  not ask a prose surface for a value, nor an enumeration surface for narrative.
- **PROV-004 (cite-the-attempt):** When a requested value has no authoritative
  source available, emit `MISSING` **and** record which source(s) were tried, so
  absence is auditable rather than silent.

## Patterns

- **PROV-P1 (missing-with-trail):** value requested → no authoritative source
  available → emit `MISSING` and cite the surfaces attempted (per PROV-004),
  never a guessed or inherited value.
- **PROV-P2 (authority-but-unconfirmed):** a value obtained from a structurally
  authoritative source that has not yet been confirmed for *this* target is
  `VERIFY`, not `CORROBORATED` — authority is not the same as confirmation.

## Distinctions

- **PROV-D1 (fact-class distinction):** every emitted fact is exactly one of:
  a *silicon fact* (true of the chip), a *board fact* (true of this board's
  wiring), or an *inference* (derived, unconfirmed). A fact that cannot be placed
  in exactly one class is not ready to emit.

## Provenance

Generic fact-class → authoritative-source order (no addresses, no targets):

| Fact class      | Authoritative-source order                                   |
|-----------------|--------------------------------------------------------------|
| register-base   | catalog/enumeration > boot/runtime evidence > kernel DT > MISSING |
| IRQ             | catalog/enumeration > boot/runtime evidence > kernel DT > MISSING |
| clock-rate      | freq-plan/catalog > boot/runtime evidence > MISSING          |
| instance-count  | enumeration/catalog > boot/runtime evidence > MISSING        |
| SID / stream-id | catalog/enumeration > boot/runtime evidence > MISSING        |
| power-domain    | SoC power-architecture evidence > MISSING (never assumed)    |
| routing         | board schematic/wiring evidence > MISSING (never DT-inferred)|

## Anti-patterns

- **Sibling substitution:** filling a `MISSING` per-silicon value with a family
  member's value "because they are close." Forbidden by PROV-001.
- **Prose-as-value:** treating a narrative/family document as the source of a
  register base, rate, or count. Forbidden by PROV-002/PROV-003.
- **Silent MISSING:** emitting `MISSING` without recording which surfaces were
  tried. Forbidden by PROV-004.

## Anonymized illustrations

- A target was observed to have a nearest-target match at high similarity, yet
  its own subsystem base differed from that neighbour's — confirming that a
  register base is a silicon fact (PROV-001) and must never be inherited.
- A target's value request for a per-silicon rate returned only family-level
  prose; the correct outcome was `MISSING` with the attempted surface cited
  (PROV-004), not an interpolated rate.

## Open questions

- The precise ordering of authority between two independent enumeration surfaces
  when they disagree (partial-coverage / split-across-revisions case) — deferred
  until a second enumeration surface exists to compare against.

## Change log

- (none yet — provenance rules are the most stable in the KB; learn-loop appends
  here are rare, dated, and require human sign-off. WARN: on any conflict.)
