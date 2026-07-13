# KB: soundwire (SoundWire controller / master conventions)

## Scope

SoundWire controller/master conventions for **any** SoundWire-bearing SoC, with
the central silicon-vs-board separation. Contains no per-target master count,
base, or routing — those are target evidence.

## Rules

- **SWR-001 (controller base is silicon):** a SoundWire controller/master
  register base is a *silicon fact*; resolve it per `PROV-002`. Never inherit it.

## Patterns

- **SWR-P1 (DT is not a count source):** a missing controller node in the device
  tree does **not** prove the master count; the count is not derivable from DT
  absence — seek an enumeration surface (`PROV-003`).

## Distinctions

- **SWR-D1 (count vs routing — flagship):** the SoundWire master *count* is a
  silicon/enumeration fact; *which master drives which peripheral* is a board
  wiring fact. These are separate evidence classes and must never be conflated —
  a known count says nothing about routing, and known routing does not establish
  the count.

## Provenance

- controller base → `PROV-002` (catalog > boot > DT > MISSING).
- master count → enumeration/catalog surface per `PROV-003`; not DT-inferred.
- master→peripheral routing → board schematic evidence > `MISSING`.

## Anti-patterns

- **Count-from-DT:** inferring master count from the number (or absence) of DT
  nodes. Forbidden by SWR-P1.
- **Routing-implies-count:** assuming the number of wired peripherals equals the
  silicon master count. Forbidden by SWR-D1.

## Anonymized illustrations

- A target's master count was ambiguous with no enumeration surface available;
  the correct outcome was `MISSING` on the count while board routing (a separate
  class) remained a distinct, schematic-sourced question — the SWR-D1 separation
  in practice.

## Open questions

- Generalized enumeration heuristics for master count (feeds the Track C
  cardinality validator's legitimate-divergence registry); never a per-target
  count.

## Change log

- (none yet.)
