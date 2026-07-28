# Lane Parameterization Scope — Honest Classification

Status: ACTIVE — documents what is and is NOT parameterized across generators.

## Principle

Parameterize ONLY what can fire today. Do not wire dead code (template lookups
that will always return None on the only real target). Tag honestly-hardcoded
constants as Nord/lemans-scoped rather than pretending they are generic.

---

## dt_scaffolding

| Constant | Classification | Status |
|----------|---------------|--------|
| `pinctrl_state` label | TEMPLATE-DERIVABLE | **WIRED** — H-1 projects ATTESTED `i2s8_active` via A-narrow; dt_scaffolding consumes it. |
| `_ADSP_COMPATIBLE` | TEMPLATE-DERIVABLE (dormant) | Needs new projector derivation from T5.dts.compatible row. NOT wired — would be dead code on Nord. |
| `_ADSP_FIRMWARE` | TEMPLATE-DERIVABLE (dormant) | Needs new H-1 `firmware_path` field. NOT wired. |
| `_PIN_GPIO` (73/74/75) | TEMPLATE-DERIVABLE (dormant) | Requires enriched onboarding pinmux data. NOT wired. |
| `_PIN_FUNCTION` (aud_intfc8_*) | KERNEL-DERIVED | Belongs to WP-SRC-B kernel DT parser. NOT template material. |
| `_REQUIRED_I2S_PINS` (clk/ws/data) | HONESTLY-NORD-ONLY | Lemans-family I2S8 topology. Tagged, not parameterized. |
| `&tlmm` node ref | HONESTLY-NORD-ONLY | Lemans-family TLMM label. Tagged, not parameterized. |
| `drive-strength = <8>` | CURATION-ONLY | Board design decision. Needs G-3A.15 curated authority. |
| `bias-disable` | CURATION-ONLY | Board design decision. Needs G-3A.15 curated authority. |

---

## codec_stub

| Constant | Classification | Status |
|----------|---------------|--------|
| `_I2C_BUS_LABEL` (&i2c18) | TEMPLATE-DERIVABLE (dormant) | H-1 has `buses[].instance` slot, but empty on Nord. NOT wired. |
| `_NORD_CODECS` compatible strings | TEMPLATE-DERIVABLE (dormant) | H-1 has `codecs[].part_number` slot, but NOT_ATTESTED on Nord. NOT wired. |
| `_NORD_CODECS` I2C addresses | CURATION-ONLY | Board wiring — no automated source. Needs G-3A.15. |
| `_FIXME_SIGNALS` | CURATION-ONLY | Board-level signal routing. No authority exists. |
| Symbol prefix `nord_` | HONESTLY-NORD-ONLY | Target-scoped identifier. Tagged, not parameterized. |
| Output filename `nord_codec.c` | HONESTLY-NORD-ONLY | Target-scoped. Tagged. |
| DAI-cells `<0>` | HONESTLY-NORD-ONLY | Single-DAI assumption for these codecs. Tagged. |

---

## audioreach_topology

**Classification: KERNEL_DERIVED_NORD_ONLY (~95% of constants)**

The audioreach lane emits a verbatim DT subtree whose content is defined by
the upstream kernel DTS (`arch/arm64/boot/dts/qcom/sa8775p.dtsi`). This
includes: register bases, SMMU SIDs, IPCC client IDs, interrupt indices,
glink channels, VMIDs, GPR domain macros, and protection-domain strings.

**None of these are H-1 template material or curation candidates.** They are
kernel-source facts that would be extracted by a future WP-SRC-B kernel-DT
parser. Until that parser exists, the lane is honestly Nord-locked.

| Category | Count | Authority |
|----------|-------|-----------|
| KERNEL-DERIVED | ~14 items | WP-SRC-B (future) |
| CURATION-ONLY | 2 (intents, nsessions) | G-3A.15 (when curated) |
| HONESTLY-NORD-ONLY | 3 (target name/filename/comment) | Nord-scoped cosmetics |
| TEMPLATE-DERIVABLE | 1 (ADSP compatible) | Same as dt_scaffolding — dormant |

**Do NOT parameterize audioreach until WP-SRC-B kernel-DT parser exists.**
Wiring template lookups that return None on the only real target produces
dead code that costs maintenance without delivering value.

---

## Summary

- **Fires today (1):** dt_scaffolding `pinctrl_state` — H-1 attests, generator consumes.
- **Dormant template (6):** ADSP compatible/firmware, GPIO#, I2C bus, codec compatibles. Slots exist in H-1 but are NOT_ATTESTED on Nord. Will fire when onboarding enrichment populates them.
- **Blocked on WP-SRC-B (15+):** Audioreach kernel-DT material + pin functions. Needs a parser that doesn't exist.
- **Blocked on G-3A.15 curation (6):** Drive strength, bias, I2C addresses, signals, intents, nsessions. Human attestation required.
- **Honestly Nord-only (8):** Target names, filenames, pin topology. Tag them; don't abstract.
