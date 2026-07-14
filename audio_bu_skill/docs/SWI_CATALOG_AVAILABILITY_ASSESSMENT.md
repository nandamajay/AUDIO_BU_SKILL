# SWI Catalog Availability Assessment

**Status:** Investigation only. No code modified. No IPCAT access implemented. No DTS/YAML/patches generated. No Audio BU Skill changes. Nothing staged/committed/pushed.
**Question:** Does the IPCAT SWI catalog actually contain the chips we care about — **SA8797P** (Nord IQ-10) and **Eliza / CQ7790** — well enough to solve the real onboarding blockers?
**Method:** Static analysis of how EVA and camera_dtsi identify and fetch chips via `ipcat_client`; extraction of the exact chip identifiers for our two targets; a host-capability check for whether a definitive live probe is even runnable here.

> **Headline result:** The definitive presence check (`chips.get_chips()`) **cannot be run from this host** — `ipcat_client` is not installed, there is no cached chip list, and the only wired IPCAT path (qgenie-chat MCP) exposes document search, not the chip API. **The gate check is itself the access work under evaluation.** What I *can* deliver is a rigorous risk assessment from the identification scheme + strong indirect evidence, plus the design of the one cheap, read-only probe that would convert this risk into fact.

---

## 1. How target chips are identified

Confirmed from both reference systems (`cam_dtsi_tool.py:get_chip`, `generate_cvp_dtsi.py:get_chip_name_for_swi`/`get_chip_candidates`). Both call the **same** primitive:

```python
from ipcat_client import chips
all_chips = chips.get_chips()   # → list of dicts
```

Each chip record has: **`alias`**, **`name`**, **`id`**, **`revision_number`**. Resolution is a 4-tier match with identical precedence in both repos:

1. exact `alias` == target
2. substring: target in `alias`
3. exact `name` == target
4. substring: target in `name`

Then all SWI/IRQ/clock/address/SID fetches are **keyed by `chip_id`** (and `chip_name` for IRQs). So *identification* = "does `get_chips()` return a record whose alias or name matches my target string?", and *usefulness* = "does that `chip_id` have populated module/IRQ/clock/address tables?" — **two separate questions.** A chip can be *present* (in the chip list) yet *unpopulated* (no module data) — see §5.

---

## 2. Does SA8797P appear as a supported chip?

**Cannot be confirmed from this host** (no `ipcat_client`, no cached list). Risk-assessed likelihood: **MODERATE, with high partial-coverage risk.**

Evidence for/against:
- **For:** SA8797P is a real, taped-out automotive part in the same SA87xx family as SA8775P (lemans), which the onboarding used as nearest-target at 0.85 confidence — lemans is clearly well-populated. Families tend to get added together.
- **Against / risk:** SA8797P is the **newer, derivative** member. The nord onboarding's own HPG query for SA8797P returned **only** generic QDSP6 v69/v79 docs (Waipio/Olympic/Pakala) — *no SA8797P-specific content at all*. That was HPG_DOCUMENTS (wrong surface), so it does not prove SWI-catalog absence — but it does establish that SA8797P has thin IPCAT documentation coverage generally, which weakly correlates with catalog population lag for a new part.
- **Decisive risk signal (from camera_dtsi's own code):** `get_chip_candidates` docstring — *"Data for a new chip is sometimes split across silicon revisions (e.g. honu_2.0 has SWI modules/clocks but no interrupt map, while honu_1.0 has the interrupt maps)."* This is direct, in-production evidence that **newer parts routinely appear in the chip list but with partial/split SWI coverage.** SA8797P is exactly the "newer part" profile where this happens.

**Target identifier for the probe:** onboarding detected SoC = `SA8797P (Nord IQ-10 EVK/RRD)`. Probe aliases to try: `sa8797p`, `sa8797`, `8797`, `nord`. Nearest-target sanity check: `sa8775p` / `lemans` should resolve (validates the probe itself).

---

## 3. Does Eliza's chip appear?

**Cannot be confirmed from this host.** Risk-assessed likelihood: **MODERATE-HIGH — the stronger of the two cases.**

Evidence:
- **For (strong):** Eliza is **named by IPCAT itself.** The eliza onboarding's LPASS HPG hit (`ipcat/HPG_DOCUMENTS/674dd412a66dd46a38c52306.json`, "LPASS_13.3.x_HPG") *explicitly names "Eliza"* and describes its audio topology by name. A part with dedicated named HPG content is almost certainly a tracked entry in IPCAT's chip table.
- **For:** Eliza is an active upstream bring-up (eliza.dtsi, `qcom,eliza-*` compatibles, `sc8280xp.c` Eliza support, FROMLIST patches) — active parts correlate with IPCAT population.
- **For (coverage):** Eliza is a client/compute SoC with a mature LPASS block; SoundWire-master is a core LPASS module, so if Eliza is populated at all, SoundWire modules/addresses are very likely present (unlike a fringe peripheral).
- **Identifier nuance:** the codename is **Eliza**; the silicon part number is **CQ7790 / CQ7790S**. The alias/name matcher means *either* could be the catalog key. Probe both: `eliza`, `cq7790`, `cq7790s`, `7790`.

---

## 4. Do aliases exist?

**Yes — aliasing is a first-class, explicit part of the schema.** Every chip record carries both `alias` and `name` as distinct fields, and both reference systems try `alias` *before* `name`. Two consequences for us:

- **Eliza is the textbook alias case:** codename (`Eliza`) vs part number (`CQ7790`). One will be `name`, the other likely `alias` (or a similar-chip). The matcher's substring tiers make either resolvable.
- **Revision aliasing:** when a target matches multiple records (revisions), they differ by `revision_number`. **EVA and camera resolve this differently** — camera auto-selects the *lowest* revision; EVA sorts by name and takes the *last*. For us this matters because (per §2) **different revisions can hold different data** (modules on one, IRQ map on another). A correct audio layer must iterate candidates and take the first that has the needed data type — camera's `get_chip_candidates` pattern, not a single-pick.

---

## 5. Does the catalog contain modules / addresses / IRQs / clocks for these chips?

The **API surface** exists and is proven in production (per fetch functions below). Whether it is **populated for our two specific chips is the unverifiable-from-here gate.**

| Data type | API (via `ipcat_client`) | Used by | Answers which blocker |
|---|---|---|---|
| Modules (name/base/size) | `swi.get_modules(chip_name)` | EVA, camera | Nord ADSP PAS base; Eliza SoundWire base |
| Addresses / memory maps | `memmap.get_memory_maps(chip_id, group='HW')` | camera | register bases (cross-check) |
| IRQs | `irqs.get_interrupts()` / `irqs.get_latest_interrupt_map(chip_id)` | EVA, camera | (not a current audio blocker) |
| Clocks / freq plan | `clocks.get_freqplan_release(chip_id, <CC>, "")` | EVA, camera | audio clock rates (future) |
| SIDs | `fetch_sids_inmem(chip_id, target)` | camera | SID/IOMMU (future, `[VERIFY]`) |

**Population is per-chip AND per-data-type AND per-revision.** The honu precedent proves a chip can have `get_modules` + clocks but a *missing* IRQ map. So the correct probe checks each `(chip, data_type)` cell, not just chip presence.

---

## 6. Is the catalog complete enough to solve the three real blockers?

Conditional on population (the §2/§3 gate). Assuming the chips are present and modules populated:

| Blocker | Data type needed | If chip populated | Residual limit |
|---|---|---|---|
| **Nord ADSP PAS base** (`0x30000000` from lemans vs `0x07000000` real) | `swi.get_modules` → ADSP/QDSP6 base | **Solvable** — core subsystem, first to be populated if any modules exist | May be a physical-vs-subsystem-view difference; catalog gives authoritative base but power/DSP-team confirmation may still be needed |
| **Eliza SoundWire count** (1 or 2 masters?) | count of SoundWire-master modules matching pattern | **Solvable** — camera's cardinality doctrine (enumerate + count) | Answers *silicon instance count*, NOT *board wiring* (which master drives WSA) — that stays a schematic fact |
| **Eliza SoundWire base** (controller base unconfirmed) | `swi.get_modules`/`memmap` → master base | **Solvable** — core LPASS block | none material if present |

**Net:** all three blockers are the *right kind of fact* for the SWI catalog (this confirms the "wrong surface" thesis independently). Completeness hinges entirely on population, which is: **very likely for Eliza (named by IPCAT), uncertain for SA8797P (new derivative, documented partial-coverage risk).**

---

## 7. Risk assessment

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| **SA8797P absent from chip list** | Low-Moderate | High (Nord layer yields nothing) | New part; family sibling lemans present suggests inclusion, but no proof |
| **SA8797P present but modules unpopulated / split across revisions** | **Moderate-High** | High | The honu precedent — the single biggest risk for Nord |
| **Eliza absent from chip list** | Low | High | IPCAT names Eliza in HPG → very likely a tracked chip |
| **Eliza present but SoundWire modules unpopulated** | Low | Medium | SoundWire is core LPASS; unlikely to be missing if chip populated |
| **Alias mismatch (probe string wrong)** | Low | Low | Mitigated by trying codename + part-number + numeric substrings |
| **Board-wiring facts still unresolved after catalog** | Certain | Medium | Catalog gives silicon facts only; schematic gap remains for eliza SWR routing and nord I2S8 macro |
| **Access cost: `ipcat_client` dependency + headless auth** | Certain | Medium | Both reference repos solve it (env-var-first); Medium not High |
| **Cannot verify any of the above without building the access** | **Certain** | Process | The gate check needs the very library the layer needs — argues for a *minimal throwaway probe first*, not a full layer |

---

## 8. Recommendation

### **B — Proceed, but only for chips a minimal read-only probe confirms are populated. Do NOT commit to the full layer blind.**

Rationale:
- **Not A (full commitment for all chips):** the SA8797P partial-coverage risk is real and documented (honu precedent). Building the full layer on the assumption that Nord is populated could reproduce "queried IPCAT, got nothing" — the exact failure the layer is meant to fix. Committing to all chips before verifying is the mistake.
- **Not C (do not proceed):** the surface is provably the *right* one (all three blockers are SWI-catalog fact types, §6), Eliza is very likely present (named by IPCAT), and two independent production systems rely on this exact surface. Abandoning it would leave the real blockers permanently unsolvable by the current HPG_DOCUMENTS path.
- **B, gated on a probe:** the honest state is "surface correct, population unverified." The cost asymmetry is stark — a **one-time, read-only, ~30-line throwaway probe** (call `chips.get_chips()`, match our 2 targets + lemans control, and for each hit call `get_modules`/`get_memory_maps` and print whether the ADSP and SoundWire-master modules appear) converts the entire §2/§3/§5 uncertainty into fact for the price of one credentialed run. That probe is **strictly smaller** than the Evidence Layer and does not modify Audio BU Skill.

### The decisive process finding
**The presence gate cannot be answered by reasoning — only by one live call.** So the correct *next action* is not "build the IPCAT Evidence Layer" and not "abandon it," but:

1. **Run the minimal read-only probe** (needs `ipcat_client` installed + IPCAT credentials the user controls — env-var-first, per both reference repos). This is a throwaway spike, not the layer. It answers: is SA8797P present? populated? is Eliza/CQ7790 present? does it expose SoundWire-master + ADSP modules?
2. **Then** scope the Evidence Layer to whatever the probe confirms:
   - If **both** populated → build for both (approaches A).
   - If **Eliza only** → build for Eliza's blockers now; keep Nord ADSP base on the confidence-ledger `NEEDS_REVIEW` path with a DSP-team escalation (this is the likely outcome, hence **B**).
   - If **neither** → the SWI-catalog surface, though architecturally right, is not yet populated for our targets → **defer** the layer and lean entirely on the Audio KB + confidence ledger (from PHASE0_SWI_SPIKE_RECOMMENDATION.md), which need no IPCAT.
3. In **all** outcomes, the dependency-free work (Audio KB seeding, confidence ledger, cardinality-authority validator in diagnostic form) proceeds now regardless — it is never blocked by the probe result.

**One line:** the SWI catalog is the right surface and Eliza is very likely covered, but SA8797P coverage is genuinely uncertain and unverifiable from here — so proceed *conditionally*, gate the layer on a cheap read-only `chips.get_chips()` probe, and scope the build to the chips that probe proves are populated.

---

## Appendix — Evidence sources

- **Chip identification / API (static read this session):** `camera_dtsi/mcp/scripts/cam_dtsi_tool.py` (`get_chip` L117-204; `fetch_swi_modules`/`fetch_camera_addresses`/`fetch_camera_irqs`/`fetch_camera_clocks`); `EVA_QLI_DT_Generator/generate_cvp_dtsi.py` (`get_chip_name_for_swi` L881-918, `get_chip_candidates` L921-955 — **partial-coverage docstring**, `fetch_swi_modules` L981-1031, `_check_ipcat` L862-867).
- **Host capability check:** `python3 -c "import ipcat_client"` → `ModuleNotFoundError`; `pip3 show ipcatalog-client` → not found; no cached chip list in either repo. ⇒ no live probe possible from here without install + credentials.
- **Target identifiers:** `targets/nord-iq10/onboarding_report.md` (detected SoC `SA8797P`, nearest `SA8775P/lemans`, ADSP-base blocker L44); `targets/eliza/onboarding_report.md` (detected SoC `Eliza (CQ7790/CQ7790S)`, IPCAT-names-Eliza self-report L170, SoundWire count/base blockers L63).
- **Supported-chip precedent:** `camera_dtsi/references/kb/00_index.md`, `references/kb/cpas.md` (pakala/hawi/kaanapaliT/waipio populated with per-reg-name bases — shows what a fully-populated chip looks like).
- **Prior docs:** `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md`, `docs/NEXT_PHASE_RECOMMENDATION.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md`.
