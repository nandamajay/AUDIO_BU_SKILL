# KB: lpass (low-power audio subsystem macros)

## Scope

LPASS macro-block conventions and surface-routing for **any** LPASS-bearing SoC:
generic macro *roles* and the presence-vs-base distinction. Contains no per-SoC
macro inventory, bases, or document IDs — those are target evidence.

## Rules

- **LPASS-001 (macro base is silicon):** an LPASS macro register base is a
  *silicon fact*; resolve it per `PROV-002`. Never inherit it from a sibling.
- **LPASS-002 (presence surface):** macro *presence/topology* may be established
  from prose per `PROV-003`; a macro *base* may not — route each to its surface.

## Patterns

- **LPASS-P1 (absence is not proof):** a macro node absent from the kernel device
  tree does **not** prove the hardware macro is absent; mark it an inference, not
  a silicon fact.

## Distinctions

- **LPASS-D1 (presence vs base):** macro *presence* (may be prose-confirmed) is a
  distinct question from macro *base* (silicon-only, per PROV-002).

## Provenance

- macro base → `PROV-002` (catalog > boot > DT > MISSING).
- macro presence/topology → prose surface per `PROV-003`.

## Anti-patterns

- **DT-absence-as-hardware-absence:** concluding a macro does not exist because
  its DT node is missing. Forbidden by LPASS-P1.
- **Inventory copy:** importing a sibling's macro inventory as this target's.
  Forbidden by PROV-001.

## Anonymized illustrations

- A target's kernel tree lacked a macro node that its hardware in fact provided;
  treating the DT gap as hardware absence would have dropped a real block — hence
  LPASS-P1.

## Open questions

- Generalized surface-routing refinements for macro roles across families — added
  only after confirmation across multiple targets; never an inventory.

## Change log

- (none yet.)
