# KB: audio_clocks (audio clock-controller conventions)

## Scope

Audio clock-controller conventions for **any** SoC, centred on the
anti-interpolation provenance rule. Contains no per-target rates or level sets —
those are target evidence.

## Rules

- **CLK-001 (anti-interpolation):** clock names and rates are per-silicon
  freq-plan facts. **Never** interpolate, average, or copy a rate or level-set
  from a nearest target — level counts and rate tables legitimately differ across
  SoCs. This is a specialization of `PROV-001`.

## Patterns

- **CLK-P1 (prose gives sequences, not rates):** when a prose surface yields
  clocking *sequences/topology* but not concrete rates, the rates remain
  `MISSING` (`PROV-003`); do not manufacture rates from the narrative.

## Distinctions

- **CLK-D1 (topology vs rate):** clock *topology/sequence* (may be prose-derived)
  is distinct from a clock *rate* (silicon freq-plan fact only).

## Provenance

- clock rates → freq-plan/catalog > boot/runtime evidence > `MISSING`, per
  `PROV-002`.

## Anti-patterns

- **Nearest-target rate copy:** importing a sibling's rate table or level set.
  Forbidden by CLK-001.
- **Rate-from-prose:** deriving a concrete rate from narrative clocking text.
  Forbidden by CLK-P1.

## Anonymized illustrations

- Two SoCs in the same family had different clock level counts; copying one's
  level-set to the other would have silently misconfigured clocking — hence
  CLK-001 as a hard anti-interpolation rule.

## Open questions

- Generalized "clock-controller family → expected rate-source" rules may be added
  over time; never raw rate tables.

## Change log

- (none yet.)
