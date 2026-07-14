# Phase-1C — Live Count Collection, Classification & WP-C Cross-Check

**Type:** Live evidence record. **No probe.py changes, no architectural changes, WP-C lane unchanged, no commits.**
**Mechanism:** Read-only `tools/call` against live `ip_catalog` MCP. Counts fed as the `catalog` authority lane into the **committed, unmodified** WP-C `compare_element_counts` (`orchestrator/reasoning/cardinality.py`, `28f2f07`).
**Evidence timestamp (UTC):** 2026-07-14T12:07:13Z
**Artifacts:** `experiments/ipcat_probe/artifacts/phase1c_live.json` (combined), `…/phase1c_781.json` (Nord), `…/phase1c_693.json` (Eliza).

**Boundary compliance:** `auth.json`/`.credentials.json` not read · TLS `verify=True` · read-only allow-list · `probe.py` unmodified · WP-C lane unmodified · token by-reference only.

---

## 1. Tool mapping (authoritative source per element class)

| Element class | Live tool | How the count is obtained | Anti-`len()` guard |
|---|---|---|---|
| `soundwire_master` | `swi_search_swi` | Union of named `*_SOUNDWIRE_MASTER` register blocks over query terms `{SOUNDWIRE_MASTER, SWR_MSTR, SWR}`, set-stability verified | Counts *distinct named blocks* from the union, not `total_hits` (which returns 0 even with hits) and not `len()` of a mislabeled field |
| `dsp_subsystem_instance` | `cores_list_core_instances` | Count of distinct **audio** DSP subsystems on the chip | Real subsystem enumeration; audio subsystem identified by name/id |
| `lpass_macro_instance` | `swi_search_swi` | Union of named `LPASS_*_MACRO` blocks, set-stability verified | Distinct named macro blocks from union |

**Note on `swi_search_swi` exhaustiveness (recorded caveat):** it is a *capped, relevance-ranked* text search, **not** a guaranteed enumerator. Every count below was taken by (a) unioning multiple query terms, (b) confirming the returned set was below the cap (not truncated), and (c) confirming set stability across terms. This is why the counts are classified DIRECT: they are counts of a *real, stable, named-block enumeration*, not of a single mislabeled length field.

---

## 2. CountResults

### Nord — SA8797P (NordAU) v2 (chip_id 781)

| Element | Value | Classification | Method summary |
|---|---|---|---|
| soundwire_master | **0** | DIRECT | Zero named `*_SOUNDWIRE_MASTER` blocks; consistent with `profile.json` `soundwire.present=false, master_count=0` (I²S-only board). Catalog-authoritative absence. |
| dsp_subsystem_instance | **1** | DIRECT | `cores_list_core_instances` → one audio DSP subsystem: *High Performance Audio Subsystem* (id 43). |
| lpass_macro_instance | **0** | DIRECT | Zero `LPASS_*_MACRO` blocks (I²S-only). Catalog-authoritative absence. |

**On Nord's zeros (classification judgment):** classified **DIRECT = 0**, not UNAVAILABLE. The catalog SWI surface *does* answer the query — it authoritatively returns an empty named-block set — and this corroborates the independent repo evidence (I²S-only, no SoundWire/LPASS-macro). A `0` that the authority affirmatively reports and that the repo independently confirms is a *counted absence*, not *missing data*. (UNAVAILABLE is reserved for "the tool cannot answer," which is not the case here.)

### Eliza — SM7750 (Eliza) (chip_id 693)

| Element | Value | Classification | Method summary |
|---|---|---|---|
| soundwire_master | **4** | DIRECT | `{BT_SWR_SOUNDWIRE_MASTER, LPASS_RX_SWR_MSTR_RX_SOUNDWIRE_MASTER, LPASS_TX_SWR_MSTR_TX_SOUNDWIRE_MASTER, LPASS_WSA_SWR_MSTR_WSA_SOUNDWIRE_MASTER}` |
| dsp_subsystem_instance | **1** | DIRECT | One audio DSP subsystem: *Low Power Audio Subsystem* (id 5). |
| lpass_macro_instance | **4** | DIRECT | `{LPASS_RX_RX_MACRO, LPASS_TX_TX_MACRO, LPASS_VA_MACRO, LPASS_WSA_WSA_MACRO}` |

No count classified DERIVED (no formula needed) or UNAVAILABLE (every class answered).

---

## 3. WP-C cross-check (committed lane, unchanged)

The live catalog counts were injected as the `catalog` authority lane onto the **real prior** `element_counts` (dt / evidence / proposal) from each target's committed `qgenie_analysis.json`, then run through `compare_element_counts`. The lane code was not touched. Observed behavior matches the frozen design (dt=0-under-dt_applied=false dropped as unapplied-at-HEAD; `ambiguous:true` → `not_cross_checkable`; catalog authority present → others compared against it).

**Lanes used per row (source → n):**

| Target | Element | dt | evidence | proposal | **catalog (live)** | Usable lanes | Verdict |
|---|---|---|---|---|---|---|---|
| Nord | soundwire_master | 0* | 0 | 0 | **0** | evidence, proposal, catalog | **agree** |
| Nord | lpass_macro_instance | 0* | 0 | 0 | **0** | evidence, proposal, catalog | **agree** |
| Nord | dsp_subsystem_instance | 0* | — | 1 | **1** | proposal, catalog | **agree** |
| Eliza | soundwire_master | 0* | 3 | 1 | **4** | (ambiguous:true) | **not_cross_checkable** |
| Eliza | lpass_macro_instance | 0* | — | 2 | **4** | proposal, catalog | **disagree_with_authority** ⚠ |
| Eliza | dsp_subsystem_instance | 1 | — | 1 | **1** | dt, proposal, catalog | **agree** |

`*` dt lane dropped from the cross-check (dt=0 with dt_applied=false → "audio scaffolding unapplied at pinned HEAD," not an instance count) — per WP-C correctness rule 1, reported as a note in the row.

**Reading the two non-`agree` Eliza rows:**
- **soundwire_master → `not_cross_checkable`:** the *prior reasoning pass itself* flagged this class `ambiguous:true` ("1 or 2 masters"). WP-C correctly refuses to manufacture agreement/disagreement from a number the source disowned — even though live catalog now gives a firm 4. This is the lane behaving as designed, not a defect.
- **lpass_macro_instance → `disagree_with_authority` ⚠ (NEEDS_REVIEW):** prior `proposal=2` vs **live catalog=4**. A genuine divergence the live authority surfaced — exactly WP-C's purpose. It maps to NEEDS_REVIEW, never a hard-fail (C.4/C.9 asymmetry).

---

## 4. Verdict table

| Target | Element | Count | Classification | WP-C Verdict |
|---|---|---|---|---|
| SA8797P (NordAU) v2 | soundwire_master | 0 | DIRECT | agree |
| SA8797P (NordAU) v2 | dsp_subsystem_instance | 1 | DIRECT | agree |
| SA8797P (NordAU) v2 | lpass_macro_instance | 0 | DIRECT | agree |
| SM7750 (Eliza) | soundwire_master | 4 | DIRECT | not_cross_checkable* |
| SM7750 (Eliza) | dsp_subsystem_instance | 1 | DIRECT | agree |
| SM7750 (Eliza) | lpass_macro_instance | 4 | DIRECT | disagree_with_authority ⚠ |

`*` not_cross_checkable is driven by the prior pass's own `ambiguous:true` on Eliza soundwire_master, not by any data gap in the live count.

---

## 5. Phase-1C outcome

**PHASE-1C = PASS.** All three element classes were counted (DIRECT) for both targets and the committed WP-C lane emitted a verdict for every class without error. The live catalog authority both **corroborated** the prior lanes (5 of 6 rows agree, or are correctly withheld) and **surfaced one genuine review item** (Eliza LPASS macros: proposal 2 vs catalog 4). No value was fabricated; no count required UNAVAILABLE; the WP-C lane was used exactly as committed.

---

*Live evidence only. No code changes, probe.py unmodified, WP-C lane unmodified, nothing committed.*
