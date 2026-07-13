# KB: adsp (audio DSP subsystem)

## Scope

Reusable reasoning for the audio DSP subsystem (remoteproc/PAS class) on **any**
SoC: base-address provenance discipline, the power-model decision procedure, and
generic compatible-derivation method. Contains no per-SoC bases, rail indices, or
verdicts — those are target evidence.

## Rules

- **ADSP-001 (base is silicon):** A DSP/PAS register base is a *silicon fact*;
  resolve it per `PROV-001`/`PROV-002`. Never inherit it from a nearest target.
- **ADSP-002 (power model before domains):** Determine the SoC's power-model
  *class* before drafting any power domains for the DSP. Do not assume a specific
  rail set or provider exists until the class is established.

## Patterns

- **ADSP-P1 (unconfirmed power → review):** nearest-target power domains drafted
  without confirming the SoC's own power model → `NEEDS_REVIEW`. The power model
  is never auto-finalized.
- **ADSP-P2 (compatible by method, not copy):** derive a DSP compatible string by
  the generic naming method for the SoC, not by copying a sibling's concrete
  compatible (which is a value — PROV-001).

## Distinctions

- **ADSP-D1 (image vs register/power):** DSP *firmware/image* facts (which image
  boots) and DSP *register/power* facts (base, domains) come from different
  sources and carry different confidence — do not conflate them.
- **ADSP-D2 (power-model class vs domain index):** the power-model *class*
  (rail-based vs abstraction-based) is a separate question from the *specific*
  domain index/provider a target uses.

## Provenance

- DSP register base → per `PROV-002` (catalog > boot > DT > MISSING).
- DSP power-domain model → determined per-SoC power-architecture evidence; never
  assumed (`ADSP-002`, defers to `provenance.md` power-domain row).

## Anti-patterns

- **Rail-set assumption:** assuming a specific rail/provider set exists before the
  power-model class is confirmed. Forbidden by ADSP-002.
- **Base inheritance:** copying a DSP base from a family sibling. Forbidden by
  ADSP-001 / PROV-001.

## Anonymized illustrations

- A target's nearest match used a rail-based power model, but the target itself
  used an abstraction-based one; drafting the neighbour's domains would have been
  wrong — hence ADSP-002 (confirm class first) and ADSP-P1 (`NEEDS_REVIEW`).

## Open questions

- A generalized "for SoCs of power-model class X, the DSP path tends to follow
  convention Y" rule requires ≥2 confirmed targets before promotion from
  illustration to rule.

## Change log

- (none yet.)
