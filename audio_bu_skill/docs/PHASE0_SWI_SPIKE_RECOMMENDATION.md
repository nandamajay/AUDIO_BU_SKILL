# Phase 0 — SWI Catalog Capability Spike & Recommendation

**Status:** Investigation + architecture preparation only. No code, DTS, YAML, or patches produced. No IPCAT Evidence Layer implemented. No onboarding logic modified.
**Goal:** Validate the central hypothesis from `NEXT_PHASE_RECOMMENDATION.md` — *"we are querying the wrong IPCAT surface"* — and plan the Audio KB + two validators.
**Method:** Live inspection of the actual IPCAT access path wired into Audio BU Skill today (qgenie-chat MCP), the onboarding prompt, and the recorded eliza/nord onboarding reports — cross-referenced against EVA and camera_dtsi.

> **Headline result (empirically confirmed this session):** The hypothesis is **correct but sharper than stated.** We are not merely querying the wrong *project* within a reachable set of IPCAT surfaces — **the SWI/IRQ/clock/module catalog surface is not reachable at all through the IPCAT access path Audio BU Skill currently has.** The qgenie-chat `ipcat` data source exposes exactly one project, and it is `HPG_DOCUMENTS`. The SWI catalog lives behind a *different access mechanism* (the `ipcat_client` Python library, used directly by EVA and wrapped by camera_dtsi's dedicated MCP) that is **not currently wired into this project.**

---

## 1. SWI-catalog findings

### 1.1 What IPCAT access exists today (measured, not assumed)

The onboarding prompt (`client.py:build_prompt`) does **not** pin any IPCAT project. It says only:

> "…query IPCAT via the qgenie-chat MCP tools when available."

QGenie then chose `data_source=ipcat, project=HPG_DOCUMENTS` on its own — because, as I confirmed live this session:

- `list_data_sources()` → includes `ipcat` (among jira/confluence/sharepoint/etc.).
- `list_projects(data_source="ipcat")` → **`["HPG_DOCUMENTS"]`** — a single project, nothing else.

So QGenie did not pick the wrong project out of several; **`HPG_DOCUMENTS` is the only IPCAT project this MCP exposes.** There is no `SWI`, `MODULES`, `IRQ`, `CLOCKS`, or `FREQ_PLAN` project reachable via qgenie-chat. This is the true root cause behind both onboarding runs' IPCAT results.

### 1.2 What the reference systems use instead

- **EVA** imports `ipcat_client.base` / `ipcat_client.hsr` **directly as a Python library** and calls `swi.get_modules()`, `irqs.get_interrupts()`, `clocks.get_freqplan_release()`, `chips.get_chips()`. No MCP, no HPG documents. Chip-keyed structured tables.
- **camera_dtsi** runs a **dedicated local stdio MCP** (`camera-ipcat`) whose 6 tools (`get_chip_id`/`get_addresses`/`get_irqs`/`get_freq_plan`/`get_sids`/`get_clocks`) are thin wrappers that call the **same `ipcat_client` library** inside `cam_dtsi_tool.py`, shape the result into typed rows, filter, and cache. Again: chip-keyed SWI/IRQ/clock catalog, **not** HPG_DOCUMENTS.

**Both reference systems reach the SWI catalog through `ipcat_client`, not through a qgenie-chat-style document search.** The camera team specifically built a *separate MCP* to expose it — strong evidence that the SWI catalog is simply not available through the general qgenie-chat IPCAT surface, and must be accessed via the library (directly, or wrapped in a purpose-built MCP).

### 1.3 Answering the four Phase-0 sub-questions

**Q1 — Can the available access path retrieve chip-keyed `swi.get_modules()`/`get_addresses()`/`get_irqs()`/`get_freq_plan()`-style data?**
**No — not through the currently-wired path.** qgenie-chat `ipcat`/`HPG_DOCUMENTS` returns *documents* (HPG PDFs/JSON keyed by IP-block version), not chip-keyed module/IRQ/clock tables. To get catalog data, Audio BU Skill would need to adopt an `ipcat_client`-backed access mode (library or a camera_dtsi-style dedicated MCP) — which is exactly the not-yet-authorized IPCAT Evidence Layer. **The capability is real and proven (EVA, camera_dtsi), but it is not present in this project today.**

**Q2 — For Nord, can SA8797P module data theoretically provide the ADSP PAS base?**
**Theoretically yes — this is precisely a `swi.get_modules()` fact.** An ADSP/QDSP6 subsystem block would appear in the SWI catalog keyed to the SA8797P chip with a base address. The onboarding blocker (`0x30000000` from lemans vs `0x07000000` from Nord boot logs, unreconciled) is exactly the class of fact the SWI catalog exists to answer authoritatively — *if* the catalog has SA8797P populated (an availability question the spike cannot settle without library access; see §4).

**Q3 — For Eliza, can SWI/module catalogs provide the SoundWire controller base and master instance count?**
**Base address: yes** — a SoundWire-master block would carry a base in `get_modules()`/`get_addresses()`. **Instance count: yes, and this is the strongest case** — camera_dtsi's core doctrine is "IPCAT is the ground truth for how many hardware instances exist," derived by *counting* enumerated blocks matching a name pattern. Eliza's unresolved *"1 or 2 masters?"* is answerable by enumerating SoundWire-master blocks for Eliza's chip in the SWI catalog — the exact operation camera_dtsi performs for camera IP instances.

**Q4 — HPG_DOCUMENTS vs SWI/IRQ/Clock catalogs, for these specific blockers:** see §2.

---

## 2. HPG_DOCUMENTS vs SWI comparison

| Axis | HPG_DOCUMENTS (current, qgenie-chat MCP) | SWI/IRQ/Clock catalog (EVA + camera_dtsi, via `ipcat_client`) |
|---|---|---|
| Keyed by | **IP-block hardware version** (e.g. QDSP6 v69, v79; Soundwire_master HPG 2.1/4.0) | **Chip / SoC** (SA8797P, Eliza's CQ7790, honu, hawi…) |
| Returns | Documents (HPG PDFs/JSON) — prose, figures, programming sequences | Structured tables — module name, **base address**, size, IRQ name+number, clock name+rate |
| Answers "what is X's register base for *this* SoC?" | **No** — nord report: *"organized by IP-block hardware version, not by target SoC, and structurally cannot answer SA8797P-specific register-base…questions"* | **Yes** — this is its primary purpose (`swi.get_modules()` → `reg` base) |
| Answers "how many instances of block Y?" | No (generic architecture prose) | **Yes** — enumerate matching blocks (camera_dtsi's cardinality doctrine) |
| Answers "clock names + rates" | Weakly (prose sequences; eliza got boilerplate) | **Yes** — `get_freqplan_release()` → per-level rates |
| Reachable from Audio BU Skill today | **Yes** (wired) | **No** (requires `ipcat_client` library or a dedicated MCP — not present) |
| Best at | Topology narratives, part-family confirmation, programming guidance, "which codecs pair with this SoC" | Exact per-target register/IRQ/clock/instance facts |
| Observed value in real runs | eliza: 1 useful hit (LPASS HPG names Eliza, confirms WCD937x/WSA88x *families*); nord: **zero** target-specific hits | Not yet measured (not accessible) — but is the surface both reference systems rely on for exactly these facts |

**Conclusion:** the two surfaces are **complementary, not interchangeable.** HPG_DOCUMENTS is genuinely useful for what it is (part-family and topology confirmation — it *did* confirm Eliza's WCD937x/WSA88x families by name). It is simply the *wrong tool* for register bases and instance counts, which is what both real blockers need. The catalog surface is the right tool for those — and it is currently unreachable.

---

## 3. Eliza blocker analysis

**Blockers (from `targets/eliza/onboarding_report.md`):**
- SoundWire master_count *"ambiguous: could be 1 or 2 physical master instances; not resolved."*
- SoundWire controller register base *"unconfirmed from kernel-side evidence"* (no `qcom,soundwire-vX.Y.Z` node exists in the applied tree yet).

**Why HPG_DOCUMENTS could not resolve them:** the SoundWire-master HPG hits were *"generic multi-project boilerplate (Harmonium/Traverso/Tanggu/Djembe codecs…) with no Eliza-specific master instance count or register map."* The one Eliza-specific hit (LPASS HPG) gave topology narrative, not a master count or base.

**Why the SWI catalog would (if populated for Eliza's chip):**
- **Master count** → enumerate SoundWire-master blocks for the chip and count them (camera_dtsi instance-authority pattern). This converts *"1 or 2, unresolved"* into a deterministic integer with a citation.
- **Controller base** → the master block's base address from `get_modules()`/`get_addresses()`.

**Residual limit:** the SWI catalog answers *how many masters the silicon has* and *their bases*; it does **not** answer *how the board wires them* (the schematic's "dedicated SWR0 to WSA" question). That remains a schematic/DT fact. So the catalog resolves the *hardware-instance* half of eliza's ambiguity, not necessarily the *board-topology* half — an honest bound worth stating.

---

## 4. Nord blocker analysis

**Blocker (from `targets/nord-iq10/onboarding_report.md`):** ADSP PAS register base unresolved — patch 0003 drafts `0x30000000` (copied from lemans), its own comment notes Nord boot logs show `0x07000000`, and *"no source in this session's evidence (kernel tree, patches, or IPCAT) reconciles which base is correct for SA8797P silicon."*

**Why HPG_DOCUMENTS could not resolve it:** the query returned *"only generic multi-SoC Hexagon DSP subsystem programming guides (QDSP6 v69 for Waipio/Olympic, QDSP6 v79 for Pakala) — no SA8797P/Nord-specific document, register map, or power-domain enumeration."*

**Why the SWI catalog would (if populated for SA8797P):** the ADSP/QDSP6 subsystem block base for SA8797P is a canonical `swi.get_modules()` entry. This is the single clearest case in the whole assessment: a hand-copied-from-nearest-target register base (the exact anti-pattern EVA and camera_dtsi forbid — *"NEVER use addresses…from another chipset as fallback"*) that a chip-keyed catalog lookup is purpose-built to replace with the authoritative value.

**Two open availability caveats (cannot be settled without library access, and must not be assumed away):**
1. **Is SA8797P actually populated in the SWI catalog?** SA8797P/Nord is a newer/derivative part. If IPCAT's SWI catalog has no SA8797P entry (or only a proxy revision), the catalog surface would help nord no more than HPG_DOCUMENTS did. **This is the #1 thing the real Phase-0 spike must verify empirically** — via `ipcat_client` or the camera MCP against SA8797P — before committing to the layer for Nord's sake.
2. **`0x30000000` vs `0x07000000` may be a mapping-view difference** (e.g. a system-physical vs. subsystem-local address), not a simple right/wrong. The catalog gives *an* authoritative base; reconciling it against the boot-log value may still need power/DSP-team confirmation. The catalog narrows the gap; it may not fully close it single-handedly.

---

## 5. Audio KB proposal (design only — do NOT create files)

Seeded entirely from **already-known** eliza + nord facts (their `onboarding_report.md`, `qgenie_analysis.json`, and the confirmed memory note). Each file is markdown, loaded on demand, grown later by a learn-loop.

### `references/kb/adsp.md`
1. **Purpose:** ADSP/QDSP6 remoteproc (PAS) bring-up rules — compatible strings, register-base provenance discipline, power-domain wiring per SoC family.
2. **Example content:**
   - Compatible fallbacks observed: `qcom,sa8775p-adsp-pas`, `qcom,fastrpc`, `qcom,fastrpc-compute-cb`.
   - **Rule (from nord):** ADSP PAS base MUST come from the target's own SWI catalog / boot log — **never copied from the nearest target.** Record the nord `0x30000000`-from-lemans-vs-`0x07000000` incident as a named anti-pattern.
   - **Rule (from nord):** on SA87xx/SCMI-family SoCs, `rpmhpd` may exclude `RPMHPD_LCX`/`RPMHPD_LMX`; check `nord_rpmhpds[]`-style tables before drafting LCX/LMX power-domains.
3. **Evidence sources:** nord `case.py`/patches 0003, `rpmhpd.c` reads, `nord-sa8797p.dtsi` SCMI usage.
4. **Reduces repeated reasoning:** QGenie no longer re-derives "does rpmhpd have LCX/LMX here?" from scratch each run; the KB states the family rule and the check to perform.
5. **Improves onboarding quality:** turns the nord ADSP-base guess into a flagged, rule-governed lookup with a known anti-pattern.

### `references/kb/lpass.md`
1. **Purpose:** LPASS macro block conventions (WSA/VA/RX/TX macros) — presence, naming, base-address provenance.
2. **Example content:** LPASS macro node families; note that macro register bases are SWI-catalog facts (not inferable from prose HPG); eliza's LPASS HPG confirmed the *topology* but not bases.
3. **Evidence sources:** eliza LPASS_13.3.x_HPG hit; eliza missing_evidence (no LPASS macro nodes in tree yet).
4. **Reduces repeated reasoning:** codifies "LPASS macro bases come from SWI catalog, topology from HPG" so QGenie routes each question to the right surface.
5. **Improves onboarding quality:** prevents wasting the IPCAT query budget asking HPG for register bases it structurally lacks.

### `references/kb/audioreach.md`
1. **Purpose:** AudioReach/GPR/q6apm/q6prm stack + **logical-port macro mapping** (the nord I2S8 blocker).
2. **Example content:**
   - Stack compatibles: `qcom,gpr`, `qcom,q6apm`, `qcom,q6apm-lpass-dais`, `qcom,q6apm-dais`, `qcom,q6prm`, `qcom,q6prm-lpass-clocks`.
   - **Rule (from nord):** `q6dsp-lpass-ports.h` defines only `PRIMARY..QUINARY` — **there is no literal `I2S8` logical-port macro.** The I2S8→AudioReach-port mapping is a known-ambiguous placeholder (`QUATERNARY_TDM_RX_0/TX_0` was drafted); flag it for human resolution, do not invent a macro.
3. **Evidence sources:** nord patch 0004, `q6dsp-lpass-ports.h`.
4. **Reduces repeated reasoning:** this is a **pure knowledge gap no IPCAT surface resolves** — the KB is the *only* mechanism that helps here. Captures it once.
5. **Improves onboarding quality:** the next I2S8-style target inherits the caveat instead of rediscovering it.

### `references/kb/soundwire.md`
1. **Purpose:** SoundWire controller/master conventions — instance-count authority, controller base provenance, board-vs-silicon distinction.
2. **Example content:**
   - **Rule:** master *count* and controller *base* are SWI-catalog facts (enumerate + base); **board wiring** (which master drives WSA vs codec) is a schematic fact — keep them separate.
   - eliza case: single SWR_RX/TX to codec + "dedicated" SWR0 to WSA ⇒ count is 1-or-2 depending on whether "dedicated" = separate master; unresolved without catalog enumeration.
3. **Evidence sources:** eliza schematic findings, LPASS HPG "dedicated SoundWire" phrasing, missing_evidence master_count note.
4. **Reduces repeated reasoning:** codifies the count-vs-wiring split so future SoundWire targets don't re-litigate it.
5. **Improves onboarding quality:** directly feeds the cardinality-authority validator (§6).

### `references/kb/audio_clocks.md`
1. **Purpose:** Audio clock-controller (LPASS_CC / audio CC) conventions — where clock names+rates come from, anti-interpolation rule.
2. **Example content:**
   - **Rule (adopted from camera_dtsi):** clock names + rates come from the freq plan / SWI clock catalog; **never interpolate or map levels from a nearest target** — the level count may legitimately differ.
   - Note: HPG prose gave eliza only boilerplate here; clocks are a catalog fact.
3. **Evidence sources:** eliza IPCAT self-report (generic SWR HPG), camera_dtsi freq-plan hard constraints.
4. **Reduces repeated reasoning:** states the source-of-truth + the anti-interpolation rule once.
5. **Improves onboarding quality:** prevents nearest-target clock-rate copying (the audio analogue of the nord register-copy anti-pattern).

**KB is dependency-free, auth-free, and seedable today** — it delivers value even if the SWI-catalog access question (§4 caveat) comes back negative, because `audioreach.md`'s I2S8 rule and the anti-fallback rules help regardless of IPCAT.

---

## 6. Cardinality-authority proposal (design only)

**Rule:** when a deterministic enumeration source reports **N** instances of an audio block type and the proposed topology/nearest-target case reports **M**, and **N ≠ M**, raise a NEEDS_REVIEW warning (never a hard failure).

**Enumeration source (staged):**
- *Today (no IPCAT catalog):* the only enumeration sources are the kernel DT node counts and schematic-derived counts — so the validator can at least flag *topology-vs-DT* and *topology-vs-schematic* mismatches now.
- *After the IPCAT layer exists:* the SWI catalog becomes the authoritative **N** (camera_dtsi doctrine), the strongest form.

**How it helps eliza's SoundWire master count:** eliza's *"1 or 2, unresolved"* becomes an explicit, rendered signal: "topology proposes M masters; schematic implies 1 codec-path + 1 'dedicated' WSA-path (≈2); IPCAT catalog enumerates N — reconcile." Even before catalog access, it forces the ambiguity into a structured, visible cross-check rather than a buried prose note.

**Design constraints:** additive/diagnostic only; never auto-finalizes; consumes whatever enumeration sources exist; degrades gracefully (if only one count source exists, it reports "not cross-checkable" rather than failing).

---

## 7. Confidence-ledger proposal (design only)

**Shape:** a compact, per-domain trust table converging EVA's `TODO_confidence_status.md` and camera_dtsi's `warnings.txt`, rendered as a new section in `onboarding_report.md` (additive — sits alongside, does not replace, NEEDS_REVIEW).

**Proposed rendering:**

```
## Confidence Ledger
Per-domain confidence and evidence provenance. Diagnostic; does not change decisions.

| Domain        | Confidence | Evidence source                          | Status        |
|---------------|-----------|------------------------------------------|---------------|
| Power model   | 0.25      | rpmhpd.c (LCX/LMX absent) + SCMI in dtsi | NEEDS_REVIEW  |
| Clocks        | —         | not resolved (HPG boilerplate only)      | MISSING       |
| SoundWire      | 0.4       | schematic + LPASS HPG (count unresolved) | NEEDS_REVIEW  |
| SID / IOMMU   | —         | absent                                   | MISSING       |
| Codecs/amps   | 0.8       | schematic + LPASS HPG (family confirmed) | CORROBORATED  |
```

**Field derivation:** `confidence` and `citations` already exist per-field in `ANALYSIS_SCHEMA` — the ledger is a *rendering* of data QGenie already returns, plus the orchestrator's own signals (power_model always NEEDS_REVIEW; IPCAT coverage status). **No new evidence collection required.**

**Status vocabulary (mapped to existing concepts):** `CORROBORATED` (multiple sources agree), `NEEDS_REVIEW` (present but ungated/low-confidence), `MISSING` (no evidence — from `missing_evidence`), and later `[VERIFY]` for catalog-derived-but-unproven (SID). Maps cleanly onto EVA's `[VERIFY]`/`[DEFAULT]`/`[INFO]`.

**Why it matters:** it is the artifact that makes reviewer sign-off tractable and is a **hard prerequisite for ever trusting generated output** — you cannot responsibly generate a patch from a domain marked `MISSING`/`NEEDS_REVIEW`.

---

## 8. Recommended next implementation

Grounded in §1's measured result and the constraint that only non-perturbing, dependency-free work is safe now:

1. **Audio KB seeding (Phase 0.5)** — highest ROI, dependency-free, auth-free, seedable from facts already in hand. `audioreach.md`'s I2S8 rule alone captures a blocker no IPCAT surface can. **Do first.**
2. **Confidence ledger (report rendering)** — pure rendering of data QGenie already returns; large reviewer-confidence gain; a generation prerequisite. *Must be rendered as additive output that does not change onboarding decisions, to avoid perturbing the Benchmark A/B baseline.*
3. **Cardinality-authority validator (diagnostic form)** — start with the count sources available today (DT/schematic/topology); upgrade to SWI-catalog authority once §9's access work lands. Same additive-only constraint.

These three require **no IPCAT access, no new dependency, no auth work, and no onboarding-logic change** (they add report sections / a diagnostic cross-check, not new decisions).

---

## 9. What should wait

- **The IPCAT SWI-catalog access itself.** §1 proved it is unreachable via the current MCP; obtaining it means adopting `ipcat_client` (a dependency + the flagged, now-Medium auth question) or standing up a camera_dtsi-style dedicated audio MCP. **This is the IPCAT Evidence Layer — explicitly not authorized here.** But the *real* Phase-0 spike (with library access) must first answer the §4 caveat: **is SA8797P/Eliza's chip actually populated in the SWI catalog?** No catalog build should start before that empirical check.
- **Any DTS/YAML/patch generation** — waits until deterministic register/instance facts + cardinality authority + validator + ledger exist (see NEXT_PHASE_RECOMMENDATION.md).
- **SID/IOMMU extraction** — lowest confidence in both references; last, `[VERIFY]`-flagged.
- **Learn loop** — needs the KB + resolved-fact history first.
- **Making the validators *decision-changing*** (not just diagnostic) — wait until after the Benchmark A/B baseline, so they don't contaminate the comparison.

---

## 10. Final recommendation

### **PROCEED — with a corrected scope and one mandatory empirical gate.**

The hypothesis is **confirmed and sharpened.** We are querying the wrong IPCAT surface — and more precisely, **the right surface (SWI/IRQ/clock catalog) is not reachable through the access path Audio BU Skill currently has.** qgenie-chat's `ipcat` data source exposes only `HPG_DOCUMENTS`, which is keyed by IP-block version and structurally cannot answer the per-target register-base and instance-count questions that are the top blocker in *both* real targets. Both reference systems reach the correct surface via `ipcat_client` (EVA directly; camera_dtsi through a purpose-built MCP) — confirming the catalog surface exists, is the right tool, and requires a distinct access mechanism to reach.

**Why "proceed" and not "defer" or "change direction":**
- The evidence is now empirical, not speculative: a one-line `list_projects("ipcat")` call settled it.
- The two most valuable *immediate* actions (Audio KB + confidence ledger) are dependency-free, auth-free, non-perturbing, and seedable today — there is no reason to defer them.
- The direction (SWI catalog is the right surface) is validated by two independent production systems.

**The corrections to scope:**
1. **Reframe the IPCAT layer as an *access-mechanism* change, not a *query-tuning* change.** No amount of better prompting against `HPG_DOCUMENTS` reaches the catalog; it requires `ipcat_client` (library or dedicated MCP). This is a bigger, but well-precedented, piece of work than "point QGenie at a different project."
2. **Gate the IPCAT layer build on a mandatory empirical check:** does the SWI catalog actually contain **SA8797P** (and Eliza's chip)? If a newer/derivative part is unpopulated, the catalog helps eliza but not nord — that changes the cost/benefit and must be measured (via `ipcat_client`/camera MCP) *before* any layer is built.
3. **Sequence unchanged from NEXT_PHASE_RECOMMENDATION.md:** KB + ledger + cardinality now (dependency-free); SWI-catalog access next (gated on the empirical check); generation last.

**One-line justification:** the blockers are chip-keyed register/instance facts that live in a SWI catalog we cannot currently reach, so the right move is to adopt catalog access (after confirming it's populated for our chips) — while immediately shipping the dependency-free KB + ledger + validators that raise reviewer confidence and are prerequisites for ever trusting generated output.

---

## Appendix — Evidence sources

- **Live this session:** `list_data_sources()` → `ipcat` present; `list_projects("ipcat")` → **`["HPG_DOCUMENTS"]`** (the decisive measurement); `orchestrator/reasoning/client.py:build_prompt` (confirms no project is pinned by the prompt); `orchestrator/runners/source_intake_runner.py` (offline-glob + provenance path).
- **Onboarding reports:** `targets/eliza/onboarding_report.md`, `targets/nord-iq10/onboarding_report.md`.
- **Prior docs:** `docs/IPCAT_EVIDENCE_LAYER_PLAN.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md`, `docs/NEXT_PHASE_RECOMMENDATION.md`.
- **Reference repos:** EVA (`generate_cvp_dtsi.py` `ipcat_client` imports, `TODO_confidence_status.md`); camera_dtsi (`mcp/camera_ipcat_mcp/*`, `mcp/scripts/cam_dtsi_tool.py`, `references/kb/00_index.md`).
