# WP-H-1 — Audio Hardware Template Projector (DESIGN, projector-only)

**Status:** design package. No production code. No schema files emitted. No
generator consumption. No donor-diff. No board-variant authority track.
**Related WPs:** WP-64 (disclosure-only firewall — pre-condition; must hold
after H-1), WP-69 (board_variant NOT_ATTESTED disclosure — first concrete
NOT_ATTESTED fact the projector must carry), G-3B-gamma (Track T5 SoC-family
attestation — carried in `board_metadata`).
**Blocks:** H-2 (first consumer of the template — projector-only until then).

---

## 0. Non-negotiable architectural rules (restated, verbatim scope)

Every design decision below is subordinate to these eight rules. If any
review question asks "could the template do X", check the rules first — the
answer is "no" for anything conflicting.

1. **H-1 is projector-only.** It reads existing crossverified state and
   emits two JSON views. It never verifies, gates, or generates.
2. **H-1 must never become an authority source.** Downstream code that
   needs authority reads `gc["cross_verification"]["rows"]` (existing),
   not the template.
3. **H-1 must not modify generation behavior.** Zero edits to any
   `orchestrator/generation/*.py`.
4. **H-1 must not modify gate behavior.** Zero edits to
   `generation/model.py` `is_open()` / `_GATING_OPEN_VERDICTS`.
5. **H-1 must not consume candidate-derived values as authority.** Fields
   with `candidate_derived=true` render into the template but their
   `authority_strength` stays `UNAVAILABLE` — the candidate value goes
   into a separate `candidate_value` slot for reviewer display, never into
   the authority slot.
6. **H-1 must not reopen WP-69 or WP-64.** Those are settled; the
   template consumes their disclosures, does not re-derive them.
7. **H-1 must not introduce `SCHEMATIC_DIRECT` authority.** The closed
   enum stays `{IPCAT_DIRECT, IPCAT_DERIVED, KB_RULE, UNAVAILABLE}`.
   Schematic-attested facts render as `UNAVAILABLE` plus a
   `not_attested_disclosures[...]` entry.
8. **H-1 must not perform donor-diff logic yet.** No cross-target
   comparison; each target's template is a self-contained projection.

**Target architecture (the shape H-1 fits into):**

```
Evidence sources                   [existing]
  IPCAT + offline docs + kernel history + QGenie
       │
       ▼
Reasoning subsystem                [existing]
  crossverify / cardinality / ledger  →  gc["cross_verification"]["rows"]
       │
       ▼
─────────────────────────────────────────────────────────────
       │
       ▼
Hardware Understanding             [existing]
  TrustedFacts (rows_by_track_subject)
       │
       ▼
 ┌───────────────────────────────────────────────────────┐
 │  Audio Hardware Template     [NEW — H-1 projector]    │
 │   audio_hardware_template.json                        │
 │   gap_manifest.json                                   │
 └───────────────────────────────────────────────────────┘
       │  (leaf — never feeds back)
       ▼
Future consumers                   [H-2 and beyond]
  reviewer view / renderer / audit reports
```

**The projector is a data-flow leaf, exactly like `contributes_rows`.**
This is the same architectural pattern WP-64 pinned against regression:
the template file writes forward to reviewers only, never backward into
`gc["cross_verification"]["rows"]` or into `TrustedFacts`.

---

## 1. Confidence tags used in this document

Per session directive:
- **[Certain]** — supported by direct source read (file + line pointer
  provided in the citation table §4).
- **[Likely]** — inferred from adjacent read but not read directly.
- **[Guessing]** — reasoned position, not evidenced. Explicitly flagged.

---

## 2. Task A — Hardware knowledge inventory (4 generators)

Each generator today reconstructs hardware facts independently from
constants embedded in its source. **This duplication is what H-1 is
positioned to make visible — but H-1 does not remove it. It only
projects. Removing duplication is H-2/H-3 scope.**

### 2.1 `orchestrator/generation/machine_driver.py` [Certain]

| Fact | Location | Value (Nord) |
| --- | --- | --- |
| `sound_card.compatible` | `_SNDCARD_COMPATIBLE:155` | `qcom,nord-iq10-sndcard` |
| `sound_card.model.board_variant` | `_MODEL_FIXME_LITERAL:156` | `FIXME(board_variant): NOT_ATTESTED` |
| pinctrl label reference | `_PINCTRL_LABEL:164` | `i2s8_active` |
| CPU DAI phandle | `_CPU_DAI_LABEL:169` | `q6apmbedai` |
| Platform DAI phandle | `_PLATFORM_DAI_LABEL:170` | `q6apm` |
| DAI-link[0] name | `_DAI_LINKS:185` | `I2S8 Playback` |
| DAI-link[0] codec ref | `_DAI_LINKS:185` | `pcm1681` |
| DAI-link[0] port macro | `_DAI_LINKS:185` | `QUATERNARY_TDM_RX_0` (value=72) |
| DAI-link[1] name | `_DAI_LINKS:198` | `I2S8 Capture` |
| DAI-link[1] codec ref | `_DAI_LINKS:198` | `adau1979` |
| DAI-link[1] port macro | `_DAI_LINKS:198` | `QUATERNARY_TDM_TX_0` (value=73) |

Gating rows: T1 pinctrl (any open), T4a QUP (strict), T4b codec (disagree
hard-skip + advisory carve-out), T2 SoundWire (DISAGREE hard-skip).

### 2.2 `orchestrator/generation/codec_stub.py` [Certain]

| Fact | Location | Value (Nord) |
| --- | --- | --- |
| I2C bus label | `_I2C_BUS_LABEL:143` | `&i2c18` (QUP2_SE4 on SA8797P) |
| Codec[0] compatible | `_NORD_CODECS:161` | `adi,adau1979` |
| Codec[0] I2C address | `_NORD_CODECS:161` | `0x31` |
| Codec[1] compatible | `_NORD_CODECS:162` | `ti,pcm1681` |
| Codec[1] I2C address | `_NORD_CODECS:162` | `0x4c` |
| DAI-cells contract | codec_stub emit | `#sound-dai-cells = <0>` per codec |
| FIXME signal `reset-gpios` | `_FIXME_SIGNALS:170` | schematic-only |
| FIXME signal `ADC_MCLK` | `_FIXME_SIGNALS:171` | schematic-only |
| FIXME signal `GLOBAL_MD_OE` | `_FIXME_SIGNALS:172` | schematic-only |

### 2.3 `orchestrator/generation/dt_scaffolding.py` [Certain]

| Fact | Location | Value (Nord) |
| --- | --- | --- |
| I2S8 pin GPIO clk | `_PIN_GPIO:122` | 73 |
| I2S8 pin GPIO ws | `_PIN_GPIO:122` | 74 |
| I2S8 pin GPIO data | `_PIN_GPIO:122` | 75 |
| Pinmux function clk | `_PIN_FUNCTION:128` | `aud_intfc8_clk` |
| Pinmux function ws | `_PIN_FUNCTION:128` | `aud_intfc8_ws` |
| Pinmux function data | `_PIN_FUNCTION:128` | `aud_intfc8_data` |
| ADSP compatible | `_ADSP_COMPATIBLE:140` | `qcom,sa8775p-adsp-pas` |
| ADSP firmware image | `_ADSP_FIRMWARE:141` | `qcom/sa8775p/adsp.mbn` |

### 2.4 `orchestrator/generation/audioreach_topology.py` [Certain]

| Fact | Emission | Value (Nord) |
| --- | --- | --- |
| ADSP PAS reg base | remoteproc@ | `0x30000000` **[FIXME — downstream Nord shows 0x07000000]** |
| ADSP PAS compatible | `compatible=` | `qcom,sa8775p-adsp-pas` |
| Power-domains | `power-domains=` | `<&rpmhpd RPMHPD_LCX>, <&rpmhpd RPMHPD_LMX>` **[FIXME — WRONG on Nord: SCMI, not rpmhpd]** |
| Interrupts (5) | `interrupts-extended=` | `&pdc 6` + `&smp2p_adsp_in 0-3` |
| Clocks | `clocks=` | `<&rpmhcc RPMH_CXO_CLK>` ("xo") |
| Memory region | `memory-region=` | `<&hpass_dsp0_mem>` |
| QMP phandle | `qcom,qmp=` | `<&aoss_qmp>` |
| Glink-edge label | `label=` | `lpass` (`qcom,remote-pid=<2>`) |
| fastrpc label | `label=` | `adsp` |
| fastrpc compute-cb SIDs | `iommus=` | `0x3003 / 0x3004 / 0x3005` (apps_smmu_0) |
| GPR service `q6apm` | `compatible=` | `qcom,q6apm` |
| GPR service `q6prm` | `compatible=` | `qcom,q6prm` |
| BE-DAIS phandle name | node label | `q6apmbedai` (compatible `qcom,q6apm-lpass-dais`) |

Contributes rows: `audioreach.topology_blob.nord_iq10` — single T5 NCC row
(firmware-bundle out-of-scope marker).

### 2.5 Reuse map (Task E answer)

Facts used by ≥ 2 generators — the **structural argument for H-1** and the
list H-2 will consume from the template:

| Fact | Consumers |
| --- | --- |
| `qcom,sa8775p-adsp-pas` compatible | `dt_scaffolding` + `audioreach_topology` |
| ADSP firmware `qcom/sa8775p/adsp.mbn` | `dt_scaffolding` (emit) + implicit in `audioreach_topology` (SoC family) |
| Codec label `adau1979` | `machine_driver` (DAI-link codec ref) + `codec_stub` (i2c device) |
| Codec label `pcm1681` | `machine_driver` (DAI-link codec ref) + `codec_stub` (i2c device) |
| Phandle `q6apmbedai` | `machine_driver` (CPU DAI) + `audioreach_topology` (defines the node) |
| Phandle `q6apm` | `machine_driver` (platform DAI) + `audioreach_topology` (defines the node) |
| Pinctrl label `i2s8_active` | `machine_driver` (references) + `dt_scaffolding` (defines) |
| I2S8 pin GPIOs 73/74/75 | `dt_scaffolding` (pinmux node) + implicit in `machine_driver` (DAI-link routing) |
| Power model `rpmhpd` | `audioreach_topology` (emit) + profile.json `power_model.kind` |
| SoC family (Nord ↔ sa8775p lineage) | all 4 generators via module-level constants (Nord-family scope admission, G-3A.13) |

**11 reused facts across ≥2 generators.** This is the concrete
duplication surface. The template projects each one once with a single
authority origin. H-2 later replaces the per-generator constants with
template reads — but that is not this WP.

---

## 3. Task B — Proposed schema

Two JSON files, both projector-only outputs. **No JSON Schema formalism
yet** — YAML-comment style below is the design contract; formalization is
part of H-2 acceptance work.

### 3.1 `audio_hardware_template.json`

```jsonc
{
  "$schema_version": "0.1.0-design",       // draft schema id; not stable
  "target_name": "nord-iq10",              // must match targets/<name>/
  "run_id": "<same run_id as case>",       // provenance pin to the case
  "generated_from": {
    "cross_verification_rows_hash": "sha256:...",  // pins the projection
    "case_bringup_id": "<from BringupCase>",
    "profile_snapshot": "targets/<name>/profile.json"
  },

  "board_metadata": {
    "sound_card_compatible": { <FactRecord> },
    "board_variant":         { <FactRecord> },  // WP-69: NOT_ATTESTED
    "soc_family":            { <FactRecord> },  // G-3B-gamma T5 attestation
    "board_revision":        { <FactRecord> }
  },

  "codecs": [
    {
      "role":       "playback" | "capture" | "combined",
      "compatible": { <FactRecord> },
      "i2c_bus":    { <FactRecord> },
      "i2c_addr":   { <FactRecord> },
      "dai_cells":  { <FactRecord> },
      "reset_gpio": { <FactRecord> },        // WP-69-style disclosure allowed
      "clock_source": { <FactRecord> }
    }
  ],

  "amplifiers": [
    {
      "part":       { <FactRecord> },
      "role":       { <FactRecord> },
      "bus":        { <FactRecord> },        // "soundwire" | "i2c" | "i2s"
      "port":       { <FactRecord> }
    }
  ],

  "buses": [
    {
      "kind":       "soundwire" | "i2c" | "i2s" | "dmic" | "spi",
      "master_id":  { <FactRecord> },        // e.g. "swr0", "i2s8"
      "present":    { <FactRecord> },        // bool as FactRecord
      "master_count": { <FactRecord> }
    }
  ],

  "clocks": [
    {
      "name":       "MCLK0" | "MCLK1" | ...,
      "gpio":       { <FactRecord> },
      "tlmm_function": { <FactRecord> },
      "consumers":  [{ <FactRecord> }, ...]
    }
  ],

  "audio_links": [
    {
      "name":       "I2S8 Playback",
      "cpu_dai":    { <FactRecord> },        // phandle string
      "platform_dai": { <FactRecord> },
      "codec_dai":  { <FactRecord> },
      "port_macro": { <FactRecord> },
      "port_value": { <FactRecord> },
      "direction":  "playback" | "capture"
    }
  ]
}
```

### 3.2 `FactRecord` (the mandatory per-field envelope)

Every leaf value in `audio_hardware_template.json` is wrapped in this
envelope. Same schema for every field type. **This envelope IS the
provenance guarantee.**

```jsonc
{
  "value": <any>,                     // scalar or null; null = no evidence
  "authority": {
    "strength": "IPCAT_DIRECT" | "IPCAT_DERIVED" | "KB_RULE" | "UNAVAILABLE",
    "origin":   "<origin id string>"  // matches VerificationRow.authority.origin
  },
  "citations": ["<file:line>", ...],  // 0+ evidence pointers
  "row_ref": {                        // pointer back to authoritative row
    "track":   "T1" | "T2" | "T3" | "T4a" | "T4b" | "T5" | null,
    "subject": "<subject string>",
    "verdict": "MATCH" | "PARTIAL_MATCH" | "NOT_CROSS_CHECKABLE" | ...
  },
  "independently_verified": true | false,
  "candidate_derived": true | false,        // if true, value is candidate,
                                            // authority MUST be UNAVAILABLE
  "candidate_value": <any> | null,          // populated iff candidate_derived
  "reviewer_required": true | false,        // ⇔ any not_attested_disclosures
  "ncc_state":
        "ATTESTED"           // MATCH/PARTIAL_MATCH row, no gaps
      | "NOT_ATTESTED"       // authority exists but no evidence — WP-69
      | "NOT_CROSS_CHECKABLE",  // NCC verdict per crossverify_model
  "not_attested_disclosures": [
    {
      "reason": "board_variant" | "schematic_only" | "authority_out_of_scope"
              | "revision_not_pinned" | "insufficient_lanes",
      "detail": "<free text>",
      "citation": "<file:line>" | null
    }
  ]
}
```

### 3.3 `gap_manifest.json`

Companion file — enumerates every field whose `ncc_state` is not
`ATTESTED`. Not a duplicate of the template; it is the flattened,
sorted, reviewer-oriented view.

```jsonc
{
  "target_name": "nord-iq10",
  "gap_count_by_reason": {
    "board_variant": 1,
    "schematic_only": 3,
    "authority_out_of_scope": 1,
    "revision_not_pinned": 1,
    "insufficient_lanes": 0
  },
  "gaps": [
    {
      "field_path": "board_metadata.board_variant",
      "ncc_state":  "NOT_ATTESTED",
      "reason":     "board_variant",
      "reviewer_required": true,
      "detail":     "WP-69: NOT_ATTESTED FIXME literal in emit",
      "citation":   "orchestrator/generation/machine_driver.py:156",
      "row_ref":    { "track": null, "subject": "sound_card.model.board_variant", "verdict": null }
    },
    // ... one entry per unattested field, sorted by (reason, field_path)
  ]
}
```

---

## 4. Task C — Authority mapping (every field → its authority source)

Legend for `authority.strength` origin column:
- **IPCAT_DIRECT** — value read verbatim from IPCAT MCP call (chip-specific).
- **IPCAT_DERIVED** — computed from IPCAT data (e.g. GPIO # + function → pinmux label).
- **KB_RULE** — audio KB rule fired (rule id in origin).
- **UNAVAILABLE** — no authoritative source; value is either candidate-derived or
  schematic-only or absent.

| Template field | Nord authority strength | Origin (design) | ncc_state (Nord) | Rule-7 note |
| --- | --- | --- | --- | --- |
| `board_metadata.sound_card_compatible` | UNAVAILABLE | none (candidate: kernel commit 5267b2e1) | NOT_ATTESTED | candidate_derived=true |
| `board_metadata.board_variant` | UNAVAILABLE | none | NOT_ATTESTED | WP-69 disclosure |
| `board_metadata.soc_family` | IPCAT_DIRECT | `ipcat.chips_chip_details.nordschleife_2.0` | ATTESTED | G-3B-gamma T5 |
| `board_metadata.board_revision` | UNAVAILABLE | none | NOT_ATTESTED | schematic-only |
| `codecs[*].compatible` (adau1979, pcm1681) | UNAVAILABLE | none (candidate: kernel commit 5267b2e1) | NOT_CROSS_CHECKABLE | authority_out_of_scope; forbidden to promote |
| `codecs[*].i2c_bus` (`&i2c18`) | IPCAT_DERIVED | `ipcat.qup.wrapper2.se4` [Likely] | ATTESTED | derived; not raw string |
| `codecs[*].i2c_addr` | UNAVAILABLE | none | NOT_ATTESTED | schematic-only; **no SCHEMATIC_DIRECT** |
| `codecs[*].dai_cells` | KB_RULE | `kb.dai_cells.linear_codec_rule` [Likely] | ATTESTED | KB rule |
| `codecs[*].reset_gpio` | UNAVAILABLE | none | NOT_ATTESTED | schematic-only FIXME |
| `codecs[*].clock_source` | UNAVAILABLE | none | NOT_ATTESTED | schematic-only FIXME (ADC_MCLK) |
| `amplifiers[]` (Nord = empty) | — | — | — | Eliza: WSA8845×2 |
| `buses[soundwire].present` | IPCAT_DIRECT | `ipcat.swi_search.SOUNDWIRE_MASTER` (0 hits) | ATTESTED | zero-hit is an attestation |
| `buses[i2c].master_id` | IPCAT_DIRECT | `ipcat.chipio_get_qups` | ATTESTED | |
| `buses[i2s].master_id` (`i2s8`) | IPCAT_DERIVED | `ipcat.gpio_map.aud_intfc8_*` | ATTESTED | |
| `clocks[MCLK0].gpio` (99) | IPCAT_DIRECT | `ipcat.gpio.aud_mclk0_mira` | ATTESTED | |
| `clocks[MCLK1].gpio` (100) | IPCAT_DIRECT | `ipcat.gpio.aud_mclk1_mira` | ATTESTED | |
| `audio_links[*].cpu_dai` (`q6apmbedai`) | KB_RULE | `kb.audioreach.cpu_dai_phandle` [Likely] | ATTESTED | |
| `audio_links[*].platform_dai` (`q6apm`) | KB_RULE | `kb.audioreach.platform_dai_phandle` [Likely] | ATTESTED | |
| `audio_links[*].port_macro` | UNAVAILABLE | none (candidate: kernel commit 5267b2e1) | NOT_CROSS_CHECKABLE | authority_out_of_scope |
| `audio_links[*].port_value` (72, 73) | IPCAT_DERIVED | `ipcat.audioreach.tdm_port_ids` [Guessing — needs Track T3 confirmation] | NOT_CROSS_CHECKABLE | flag for H-2 |

**Compliance check against Rule 5 & 7:** every schematic-only or
candidate-derived value maps to `UNAVAILABLE`. None can round-trip
into MATCH via the template because the template never lands in
`gc["cross_verification"]["rows"]` (WP-64 firewall — layers 3 and 4).

---

## 5. Task D — ATTESTED / NOT_ATTESTED / NOT_CROSS_CHECKABLE definitions

The three-state ledger is a strict function of the source row:

| ncc_state | Trigger | authority.strength | Reviewer required |
| --- | --- | --- | --- |
| `ATTESTED` | verdict ∈ {MATCH, PARTIAL_MATCH} AND authority.strength ≠ UNAVAILABLE | any of the 3 non-UNAVAILABLE | no (unless PARTIAL_MATCH warning) |
| `NOT_ATTESTED` | no authoritative row exists at all — field is schematic-derived, candidate-derived, or WP-69-style projected FIXME | UNAVAILABLE | **yes** (every NOT_ATTESTED field triggers `reviewer_required=true` and appends a `not_attested_disclosures` entry) |
| `NOT_CROSS_CHECKABLE` | verdict = NOT_CROSS_CHECKABLE (a row exists and it explicitly says the cross-check cannot be performed — coverage_gap_reason is populated) | UNAVAILABLE | yes if row's `warning` field is true |

**Distinction between NOT_ATTESTED and NOT_CROSS_CHECKABLE:**
- NOT_CROSS_CHECKABLE = we tried, we produced a row, the row's
  `coverage_gap_reason` explains why we can't compare. Example: T5
  audioreach topology blob (`authority_out_of_scope`).
- NOT_ATTESTED = no row exists in the crossverification store at all.
  The field is projected from a candidate or a schematic, and no
  authority ever spoke to it. Example: WP-69 board_variant, codec I2C
  address, reset-gpios.

**Why the distinction matters for the firewall:** NOT_CROSS_CHECKABLE
fields are backed by an actual `VerificationRow` in
`gc["cross_verification"]["rows"]`. NOT_ATTESTED fields are not.
Injecting a NOT_ATTESTED field back into the authority store would
create an untracked row — which is exactly the vector WP-64 test C
guards against (single-writer rule at `main.py:1192`).

---

## 6. Task E — Reusable facts (see §2.5 table above)

11 facts reused across ≥2 generators. **Restated as an inventory
finding, not an implementation plan.** The H-1 projector emits each of
these once; consumers reading the template (H-2 onwards) get a single
authoritative value per fact instead of four separately-embedded
constants.

**Structural implication:** the Nord-family scope admission (G-3A.13)
that every generator hard-codes Nord identity from module-level
constants is the exact anti-pattern H-1's reuse map targets — but H-1
does not remove those constants (that violates Rule 3). It only
documents them.

---

## 7. Validation plan — **THIS SECTION FLAGS A BLOCKER**

### 7.1 The uncomfortable truth (Rule directive: uncomfortable-first)

**Only 2 real onboarded targets exist as of 2026-07-22:**
- `audio_bu_skill/targets/nord-iq10/` — IPCAT-attested SA8797P
- `audio_bu_skill/targets/eliza/` — file-attested SM7750

`ls audio_bu_skill/targets/` confirms this. The design directive asks
for validation against "Nord + Eliza + at least 2 additional targets".
**Two additional real targets do not exist**. The requirement is
architecturally blocked until either (a) additional real targets are
onboarded, or (b) the validation plan accepts fixture-derived
substitutes with explicit provenance labeling.

### 7.2 Three candidate mitigations (recommend option C for H-1 acceptance)

**Option A — Wait for real onboarding.** Blocks H-1 acceptance
indefinitely on a task outside its scope. Reject.

**Option B — Mine `BringupCase.donor_targets`.** Both Nord and Eliza
carry a `donor_targets: dict[str, str]` field
(`bringup_walk.py:52`) populated from QGenie's `nearest_targets`.
Eliza's `nearest_targets` names `sm8550`, `sc8280xp`, `sm8450`;
Nord's names `SA8775P (lemans)`, `QCS9100`, `sc8280xp`. These are
**not onboarded targets** — they are string labels on donor citations.
Projecting a template for `sm8550` would require synthesizing a fake
`gc["cross_verification"]["rows"]` — a fixture. Same limitation as
Option C but disguised as real.

**Option C — Two explicit synthetic fixtures (RECOMMENDED).** Author
two minimal `targets/<synthetic-N>/profile.json` fixtures plus a
minimal synthesized `gc["cross_verification"]["rows"]` payload each,
one modeled after Nord (I2S/i2c codec) and one after Eliza (SoundWire
amp path). **Label every projected FactRecord `citations: ["<fixture:
NOT_REAL_TARGET>"]`** so downstream consumers cannot mistake fixture
data for onboarded data. This preserves the design intent (validate
that the schema and projector accommodate both audio-path families
without collapsing) while making the fixture nature auditable.

The choice belongs to the user. This design proceeds under Option C
by default with the acceptance test flag `H1_VALIDATION_ALLOWS_FIXTURES=1`
so the fixture-derived pass is opt-in.

### 7.3 Validation pass matrix

| Target | Real / Fixture | audio path | Purpose | Expected reviewer-required count |
| --- | --- | --- | --- | --- |
| `nord-iq10` | real | I2S-attached i2c codecs, no SoundWire | Baseline — must produce the WP-69 board_variant + FIXME_SIGNALS gaps | ≥ 4 (board_variant + 3 FIXMEs) |
| `eliza` | real | SoundWire WSA8845×2 + WCD9378 headset | Exercise SoundWire buses[] projection, amplifiers[] population | ≥ 2 (WCD9378 uninstantiated + SoundWire version discrepancy) |
| `synthetic-i2s-min` | fixture (opt-in) | one codec on i2c, one I2S port, no amps | Validate the "no amplifier" empty-list branch matches Nord's shape | 0 (clean fixture) |
| `synthetic-swr-min` | fixture (opt-in) | one WSA-class amp on swr0, no codec | Validate the "no codec" empty-list branch does not crash the projector | 0 (clean fixture) |

**Stability finding (predicted):**
- Nord: `board_metadata.board_variant` + `codecs[*].reset_gpio` +
  `codecs[*].clock_source` (ADC_MCLK) + `codecs[*].compatible` (candidate
  from 5267b2e1) all render NOT_ATTESTED / NOT_CROSS_CHECKABLE. Expected.
- Eliza: `codecs[WCD9378].*` fields all NOT_ATTESTED (no DT patch
  applied yet); `buses[soundwire].version` NOT_CROSS_CHECKABLE
  (v2.2.0-vs-v2.1.0 discrepancy per profile).

### 7.4 Firewall regression tests (mandatory for H-1 acceptance)

Two new tests, both structural — no runtime coupling to real targets:

1. **`test_h1_projector_is_data_flow_leaf.py`** — AST scan every module
   under `orchestrator/` for assignments into
   `gc["cross_verification"]["rows"]`. Must equal exactly ONE
   (`main.py:1192`, existing). H-1 must not add a second writer.
2. **`test_h1_projector_never_promotes_candidate.py`** — for every
   FactRecord in the projector output, assert
   `candidate_derived=true ⇒ authority.strength == "UNAVAILABLE"`.
   Guards Rule 5.

Existing WP-64 tests must remain green:
`tests/test_disclosure_firewall.py` (5 tests) and
`tests/test_generator_import_guards.py` (5 tests).

---

## 8. Acceptance criteria

H-1 implementation ships if and only if:

1. Two new files exist:
   - `audio_bu_skill/orchestrator/hw_template/projector.py` (new
     subsystem — projector-only, imports crossverify_model for
     `VerificationRow` type reads and nothing else from reasoning).
   - `audio_bu_skill/orchestrator/hw_template/model.py`
     (`FactRecord`, `AudioHardwareTemplate`, `GapManifest` dataclasses).
2. Runner writes two JSON files per target:
   - `targets/<name>/audio_hardware_template.json`
   - `targets/<name>/gap_manifest.json`
3. **Firewall proof (non-negotiable):**
   - `test_h1_projector_is_data_flow_leaf.py` — writer count of
     `gc["cross_verification"]["rows"]` unchanged at 1.
   - `test_h1_projector_never_promotes_candidate.py` — candidate
     values never carry non-UNAVAILABLE authority.
   - All WP-64 tests remain green (regression check).
4. **Runtime pass on both real targets:**
   - `python3 -m orchestrator.hw_template.projector --target nord-iq10`
     produces the two JSON files and predicted gap counts (see §7.3).
   - Same for `eliza`.
5. **Fixture opt-in pass** (only under `H1_VALIDATION_ALLOWS_FIXTURES=1`):
   - Two synthetic targets produce valid template JSON without crash;
     citations correctly labeled as `NOT_REAL_TARGET`.
6. **No modification** of any file under
   `orchestrator/generation/` or `orchestrator/reasoning/`. Verified by
   `git diff --name-only master` post-implementation.
7. **No SCHEMATIC_DIRECT authority.** No `authority.strength` value,
   enum entry, constant, fixture value, or projector output may carry
   the token `SCHEMATIC_DIRECT` as a string literal. Forbidding-language
   mentions (docstrings, design-doc rules, discipline clauses that name
   the forbidden token in order to prohibit it) are not violations.
   Verified by scanning code, tests, and fixtures — the runtime surfaces
   — for the quoted-string form an authority introduction would take.
   The design doc itself is excluded from the scope because it is a
   discipline artifact, not a runtime input:

   ```
   grep -RnE '"SCHEMATIC_DIRECT"' \
     orchestrator/hw_template tests targets/synthetic-*
   ```

   Expected: no hits.

---

## 9. Recommended H-2 scope (what H-1 unlocks, but H-1 does NOT do)

H-1 makes the template exist. H-2 is the first consumer. Suggested
minimum surface, in priority order:

1. **Reviewer HTML report** — render the gap_manifest as a per-target
   review checklist. Purely additive; zero touch on generators. Lowest
   risk; validates that the template shape is the right shape for
   humans.
2. **Cross-generator constant deduplication** — replace the module-level
   Nord constants in the four generators (`_SNDCARD_COMPATIBLE`,
   `_NORD_CODECS`, `_PIN_GPIO`, `_ADSP_COMPATIBLE`, `_ADSP_FIRMWARE`,
   `_CPU_DAI_LABEL`, `_PLATFORM_DAI_LABEL`) with template reads. This
   is the payoff of §2.5 reuse map, but it modifies generators (H-1
   Rule 3 forbade it; H-2 does not have that rule). Requires careful
   preservation of the Nord-family scope admission (G-3A.13).
3. **Donor-diff** — compare a target's template against its
   `donor_targets` templates and surface deltas. This is the H-2/H-3
   boundary and would open a separate design cycle.
4. **NOT considered for H-2:** board-variant authority (queued behind
   #64 / #69 disclosure track; would open Rule 7 constraint for
   re-litigation).

---

## 10. Non-goals (explicit, restated)

* H-1 does not verify anything.
* H-1 does not open any gate.
* H-1 does not feed any row into `gc["cross_verification"]["rows"]`.
* H-1 does not introduce SCHEMATIC_DIRECT.
* H-1 does not diff donors.
* H-1 does not perform board-variant authority.
* H-1 does not modify any generator.
* H-1 does not modify any reasoning module.
* H-1 does not reopen WP-64 or WP-69.

---

## 11. Stopping condition

Design package complete. Two follow-on decisions require user
confirmation before implementation begins:

1. **Validation blocker resolution** (§7.2) — Option A (block), B
   (donor citations), or C (recommended: two synthetic fixtures with
   `NOT_REAL_TARGET` citation labeling)?
2. **Schema-versioning stance** — should
   `$schema_version: "0.1.0-design"` be pinned in a JSON Schema file
   at implementation time, or deferred to H-2 acceptance?

Stop before implementation per Turn B directive: "Do NOT write
production code yet. Do NOT implement generator consumption. Do NOT
implement donor-diff. Do NOT implement board-variant authority.
Deliver: H-1 design package, schema proposal, validation plan,
acceptance criteria. Stop before implementation."
