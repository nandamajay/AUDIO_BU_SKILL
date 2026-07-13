# KB: audioreach (AudioReach / GPR / q6apm / q6prm stack)

## Scope

AudioReach stack conventions (GPR, APM, q6apm, q6prm) for **any** SoC, and — the
highest-value item — the logical-port mapping ambiguity pattern that no catalog
resolves. Contains no per-target interface→macro assignments — those are target
evidence.

## Rules

- **AR-001 (flag, don't fabricate):** logical-port header macros are a *bounded,
  named set*. A hardware interface index with no matching macro in that set has
  **no** guaranteed 1:1 mapping → flag for human/DSP-team mapping. **Never invent
  or fabricate a logical-port macro to fill a gap.**
- **AR-002 (mapping authority):** the authoritative interface→port mapping lives
  with the DSP/firmware owner, not with device-tree inference (per `PROV-002`/
  `PROV-003`).

## Patterns

- **AR-P1 (unmatched interface → escalate):** an interface index with no matching
  logical-port macro → `NEEDS_REVIEW` + escalate to the DSP/firmware owner; do
  not proceed on a guessed macro.

## Distinctions

- **AR-D1 (placeholder vs confirmed):** a drafted placeholder port mapping is an
  *inference*; a mapping confirmed by the DSP/firmware owner is a resolved fact.
  Never treat a placeholder as truth (PROV-D1).

## Provenance

- port mapping → DSP/firmware owner > `MISSING` (never device-tree-guessed), per
  `PROV-002`.

## Anti-patterns

- **Macro fabrication:** synthesising a logical-port macro name to fill an
  unmatched interface. Forbidden by AR-001.
- **DT-inferred mapping-as-truth:** promoting a device-tree-derived guess to a
  confirmed mapping. Forbidden by AR-D1 / AR-002.

## Anonymized illustrations

- A target presented a hardware interface index outside the known macro set;
  fabricating a macro would have produced a plausible-but-wrong mapping — hence
  AR-001 (flag, never fabricate) as a permanent rule.

## Open questions

- A generalized "interface-class → typical-macro-family" heuristic table (with
  confidence and observation counts) may be accumulated over time; the
  flag-don't-fabricate rule remains permanent regardless.

## Change log

- (none yet.)
