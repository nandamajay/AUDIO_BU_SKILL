# Next Execution Plan — Audio BU Skill

**Status:** Planning and design only. No code, DTS, YAML, or patches. No IPCAT Evidence Layer. No onboarding-logic changes. Nothing staged/committed/pushed.

**Governing constraint (this plan's first principle):** every artifact below is designed to be **target-agnostic**. Nord (SA8797P) and Eliza (CQ7790) appear *only* as evidence that a capability is valuable and as validation walkthroughs — **never** as design inputs. No framework artifact hardcodes `SA8797P`, `CQ7790`, `Eliza`, or `Nord`. The litmus test applied to every proposed item:

> *Would this still be useful for a future target that does not resemble Nord or Eliza?*
> If **no** → it is target evidence, not shared framework. It is rejected from the KB/validator/ledger and pushed to `targets/<t>/evidence/`.

The goal is **onboarding intelligence**, not Nord intelligence or Eliza intelligence.

---

## 1. Executive summary

Four roadmap reviews (`IPCAT_CAPABILITY_ASSESSMENT`, `NEXT_PHASE_RECOMMENDATION`, `PHASE0_SWI_SPIKE_RECOMMENDATION`, `SWI_CATALOG_AVAILABILITY_ASSESSMENT`) converge on a stable conclusion:

1. **HPG_DOCUMENTS is the only IPCAT project reachable via the current qgenie-chat path.** It is keyed by IP-block version and answers topology/family prose — not per-target register bases or instance counts.
2. **The SWI catalog is the architecturally correct source** for the register/instance-count class of blocker, reached only via `ipcat_client` (as EVA and camera_dtsi do) — a *different access mechanism* not currently wired in.
3. **SWI population for our validation chips is unverified and unverifiable from this host** (`ipcat_client` not installed; no chips API over the current MCP).
4. **Three capabilities deliver value independent of IPCAT entirely:** an Audio KB (reusable rules), a Confidence Ledger (rendering of data QGenie already returns), and a Cardinality-Authority validator (cross-checks whatever count sources exist).

Therefore the plan splits into **IPCAT-independent work that starts now** (Tracks A–C, target-agnostic, dependency-free, non-perturbing) and **an IPCAT-gated decision** resolved by the smallest possible read-only probe (Track D). The probe — not reasoning — decides whether/for-whom an IPCAT layer is worth building.

---

## Track A — Audio KB Planning (design only)

**Reframed purpose of the KB:** a library of **reusable audio-subsystem knowledge** — block-class conventions, provenance rules, and known-ambiguity patterns — that reduces repeated LLM reasoning for *any* audio target. It is **not** a store of any target's resolved values.

**The target-agnostic partition rule (applies to every entry):**

| Belongs in shared KB (`references/kb/`) | Belongs in target evidence (`targets/<t>/evidence/`) |
|---|---|
| "An ADSP PAS base must come from the target's own authoritative source; never copy it from a nearest target." (a **rule**) | "This target's ADSP PAS base is `0x0…`." (a **value**) |
| "SoundWire *master count* is a silicon fact (enumerate instances); *which master drives which peripheral* is a board fact." (a **distinction**) | "This target has N masters; master 0 → speaker amp." (**values**) |
| "Logical-port headers commonly define only PRIMARY..QUINARY; interface names beyond that set have no guaranteed 1:1 macro — flag, don't invent." (a **pattern**) | "This target's I2S8 maps to `<macro>`." (a **mapping**) |
| Anti-pattern registry: named recurring failure modes (e.g. "nearest-target register copy") | The instance of the anti-pattern that occurred on a target |

Every entry is written as **rule / distinction / pattern / provenance-source**, phrased for an unknown SoC. Concrete target facts are only ever cited as *anonymized examples of the rule*, not as the rule's content.

For each proposed file:

### `references/kb/adsp.md`
1. **Purpose:** conventions for the audio DSP subsystem (remoteproc/PAS) applicable to any SoC — how to establish register-base provenance, how to reason about its power model, common compatible-string families.
2. **Initial content outline (all target-agnostic):**
   - *Provenance rule:* the DSP subsystem register base is a per-silicon fact; its authority order is (target's own authoritative catalog/boot evidence) > (never a nearest-target copy). Nearest-target copy is a named anti-pattern.
   - *Power-model rule:* audio-DSP power domains vary by SoC power architecture (rail-based vs. firmware/abstraction-based); the KB states "determine the SoC's power model *before* drafting domains; do not assume a specific rail set exists" — as a decision procedure, not a per-SoC answer.
   - *Compatible-string reasoning:* how to derive candidate compatibles from the SoC family generically (not a fixed list tied to one part).
3. **Facts available today (used only as anonymized rule-evidence):** Nord demonstrates the nearest-target-copy anti-pattern (a register base copied from a family sibling conflicted with the target's own boot evidence); Nord also demonstrates the "assumed rail set absent" failure (drafted rails that don't exist in that SoC's power model). These validate that the *rules* are worth stating — the specific addresses/rails stay in Nord's evidence.
4. **Facts that must NOT be added yet:** any concrete base address, any specific rail index, any one SoC's power-model verdict — all target-specific values.
5. **Learn-loop integration:** when onboarding resolves a DSP-subsystem provenance question and a reviewer confirms it, the loop may add a *generalized* rule ("for SoCs using power-model X, the DSP path follows convention Y") with a `WARN:` conflict flag if it contradicts an existing rule (camera_dtsi's `learn` pattern). It never writes a raw per-target value into the KB.

### `references/kb/lpass.md`
1. **Purpose:** LPASS macro-block conventions (the macro families, their role, and *which facts about them come from which surface*) for any LPASS-bearing SoC.
2. **Content outline:** macro-block taxonomy (generic); the routing rule "macro register bases are catalog/silicon facts; macro *presence and topology* may come from HPG prose — route each question to the right surface"; the caution that macro node absence in a kernel tree is not evidence of hardware absence.
3. **Facts available today (as rule-evidence):** Eliza showed HPG confirming macro topology *by name* while providing no register bases — evidence that the surface-routing rule is real. The specific document ID / Eliza's macro list stay in Eliza evidence.
4. **Not yet:** any target's concrete macro base or macro inventory.
5. **Learn-loop:** may add generalized "surface X answers question class Y for LPASS" refinements as they are confirmed across multiple targets (never after a single target).

### `references/kb/audioreach.md`
1. **Purpose:** AudioReach/GPR/q6apm/q6prm stack conventions and — most valuably — the **logical-port mapping ambiguity pattern** that no IPCAT surface resolves.
2. **Content outline:** the stack's generic compatible families; the rule "logical-port header macros are a bounded named set; a hardware interface index outside that set has no guaranteed macro — flag for human mapping, never fabricate a macro"; guidance on where the authoritative port mapping actually lives (DSP/firmware team, not DT inference).
3. **Facts available today (as rule-evidence):** Nord surfaced an interface (an I2S index) with no matching logical-port macro, and a placeholder was drafted — proof the *pattern* recurs and deserves a standing rule. The specific interface number / placeholder macro stay in Nord evidence.
4. **Not yet:** any target's specific port→macro assignment.
5. **Learn-loop:** accumulate a *generalized* catalog of "interface-class → typical macro-family" heuristics with confidence, plus a standing "unmappable ⇒ flag" rule. This is the KB entry with the **highest reuse value**, because it helps regardless of IPCAT and regardless of target family.

### `references/kb/soundwire.md`
1. **Purpose:** SoundWire controller/master conventions with a crisp, reusable **silicon-fact vs board-fact separation**.
2. **Content outline:** the count-vs-wiring distinction (master *count* = silicon/enumeration fact; *routing* = board/schematic fact — keep them in separate evidence classes); provenance for controller base (silicon fact); the rule that a missing controller node in DT is not proof of master count.
3. **Facts available today (as rule-evidence):** Eliza's "1 or 2 masters?" ambiguity is a clean demonstration that count and wiring are different questions and that conflating them causes unresolved blockers. The specific count/routing for Eliza stays in Eliza evidence.
4. **Not yet:** any target's resolved master count or base.
5. **Learn-loop:** feeds and is fed by the Cardinality-Authority validator (Track C) — as counts get resolved-and-confirmed, the loop may add generalized enumeration heuristics, never per-target counts.

### `references/kb/audio_clocks.md`
1. **Purpose:** audio clock-controller conventions and the **anti-interpolation provenance rule**.
2. **Content outline:** the rule "clock names and rates are per-silicon freq-plan facts; never interpolate or copy a rate/level-set from a nearest target — level counts legitimately differ across SoCs"; where rates authoritatively come from (freq-plan/catalog); the caution that HPG prose gives sequences, not rate tables.
3. **Facts available today (as rule-evidence):** Eliza's clock query returned only boilerplate — evidence that clocks are a catalog fact, not a prose fact, and that the anti-interpolation rule matters. No specific rates enter the KB.
4. **Not yet:** any target's clock rates or level set.
5. **Learn-loop:** may add generalized "clock-controller family → expected rate-source" rules; never raw rate tables.

**Track A verdict:** all five files survive the litmus test **once reframed as rules/patterns/provenance** rather than value stores. The single most valuable entry is `audioreach.md`'s logical-port rule (pure knowledge gap, IPCAT-independent, target-family-independent). The KB is dependency-free and seedable now from generalized rules; **it must be seeded with rules, and the validation that those rules matter comes from Nord/Eliza — but no Nord/Eliza value is written into it.**

---

## Track B — Confidence Ledger (design only)

**Reframed purpose:** a per-domain trust table rendered in *every* `onboarding_report.md` for *any* target — a generic rendering of confidence/provenance data QGenie already returns. It is target-agnostic by construction: the **domains** are fixed audio-subsystem categories; the **values** are whatever the current target produced.

### 1. Suggested schema (generic; domains are the audio subsystem taxonomy, not any target)
```
confidence_ledger:
  - domain: <one of a fixed audio-domain enum>   # power_model | clocks | soundwire | dsp_subsystem | codecs | dt_topology | sid_iommu
    confidence: <float 0..1 | null>
    status: <CORROBORATED | NEEDS_REVIEW | MISSING | VERIFY>
    evidence_sources: [<citation strings already emitted per field>]
```
The domain enum is the only fixed content; everything else is populated from the current run.

### 2. Confidence categories
- Numeric `confidence` in `[0,1]` (already present per-field in `ANALYSIS_SCHEMA`), or `null` when the domain produced no evidence. Rendered as a coarse band (high/medium/low) to avoid false precision.

### 3. Status categories (generic vocabulary, maps to EVA `[VERIFY]`/`[DEFAULT]`/`[INFO]`)
- `CORROBORATED` — multiple independent sources agree.
- `NEEDS_REVIEW` — present but ungated / low-confidence / single-source.
- `MISSING` — no evidence found (from `missing_evidence`).
- `VERIFY` — derived from a source that is structurally authoritative but not yet confirmed for this target (e.g. a catalog value pending human sign-off).

### 4. Example render (validation walkthroughs — these are *illustrations of the generic renderer*, not schema content)

*Illustration A (a DSP-heavy target, modeled on Nord's run):*
```
## Confidence Ledger
| Domain         | Confidence | Status       | Evidence source (abbrev)              |
|----------------|-----------|--------------|----------------------------------------|
| dsp_subsystem  | low       | NEEDS_REVIEW | nearest-target copy conflicts w/ boot  |
| power_model    | low       | NEEDS_REVIEW | rail set unconfirmed for this SoC       |
| clocks         | —         | MISSING      | no rate table found                     |
| codecs         | medium    | CORROBORATED | driver family + patch                   |
```
*Illustration B (a SoundWire target, modeled on Eliza's run):*
```
| soundwire      | low       | NEEDS_REVIEW | count ambiguous (enumeration missing)   |
| codecs         | high      | CORROBORATED | schematic + HPG family match            |
| dt_topology    | medium    | NEEDS_REVIEW | board DTS absent from tree              |
```
Both are the *same renderer* over different runs — demonstrating target-agnosticism.

### 5. Existing fields that already suffice
- Per-field `confidence` and `citations` in `ANALYSIS_SCHEMA`.
- `missing_evidence[]` → `MISSING` rows.
- Orchestrator-side signals already computed (e.g. power_model always flagged NEEDS_REVIEW; IPCAT coverage status). **No new evidence collection is required — the ledger is a rendering.**

### 6. New fields that would be needed
- A light **domain-tagging** of existing per-field confidences into the fixed domain enum (a mapping layer, not new data), so scattered field confidences roll up into the 6–7 domain rows.
- Optionally a `status` derivation function (pure function of existing confidence + source count + missing_evidence). No schema expansion of the evidence itself.

**Must-hold constraint:** the ledger is **additive and non-decision-changing** so it does not perturb any future Benchmark A/B baseline.

---

## Track C — Cardinality Authority (design only)

**Reframed purpose:** a generic validator — "when two independent sources disagree on *how many* of an enumerable audio element exist, surface it." It is defined over **element classes** (SoundWire masters, macro instances, DAI links, DMIC lines, AudioReach ports…), not over any specific target's numbers.

### 1. Counts comparable today (no IPCAT)
- **DT-derived count** (nodes present in the kernel tree).
- **Schematic/evidence-derived count** (from offline evidence extraction).
- **Topology/proposal count** (what the onboarding case proposes).
Cross-checking these three is possible **now** and is fully target-agnostic.

### 2. Counts available after SWI access
- **Catalog-enumerated count** (`swi.get_modules()` instances matching an element-class pattern) — becomes the *authoritative* N (camera_dtsi doctrine). This upgrades the validator from "sources disagree" to "sources disagree *with the authority*."

### 3. Which mismatches should be **warnings** (NEEDS_REVIEW, never hard-fail)
- Proposal count ≠ any independent count (topology claims a number no evidence supports).
- Two independent evidence sources disagree on a count.
- (Post-SWI) any source ≠ catalog authority.
These block auto-finalization signals but never crash the run.

### 4. Which mismatches should stay **informational**
- Only one count source exists (nothing to cross-check) → report "not cross-checkable," not a warning.
- A known, KB-documented legitimate divergence (e.g. board depopulates a silicon-present instance) → informational with a pointer to the KB rule.

### 5. Application (validation walkthroughs, generic mechanism)
- *SoundWire-count illustration (Eliza-shaped):* topology proposes M masters; schematic implies a codec path + a "dedicated" amp path; DT has no controller node. The validator emits: "master count not cross-checkable / sources diverge — NEEDS_REVIEW; silicon count requires enumeration authority." The mechanism knows nothing about Eliza — it operates on the element class "SoundWire master."
- *Future AudioReach-topology illustration:* the same validator compares proposed DAI-link/port counts against DT and (later) catalog enumeration for *any* future target — no new code per target, because it is keyed on element class.

**Design constraints:** additive/diagnostic only; degrades gracefully to "not cross-checkable"; element-class list is extensible config, not hardcoded targets; never auto-finalizes.

---

## Track D — SWI Probe Execution Plan (design only)

**Goal:** answer exactly two questions — *is our DSP-heavy validation chip populated?* and *is our SoundWire validation chip populated?* — at minimum cost, **without building an IPCAT layer.** (Even here the *probe design* is target-agnostic: it takes a list of `(target_string, expected_element_class)` pairs as input; the validation chips are merely the first list passed to it.)

### 1. Preconditions
- `ipcat_client` (`ipcatalog-client`) installed in the probe's Python env. **Currently not installed** — this is the gating precondition.
- IPCAT credentials available **env-var-first** (`IPCAT_USER`/`IPCAT_PASSWORD` or `IPCAT_TOKEN`), per both reference repos' headless model. **User-provided** — never scraped from history/env by me.

### 2. Access requirements
- Network reach to the IPCAT endpoint from the run host.
- Read-only. No writes, no caching into Audio BU Skill, no modification of onboarding.

### 3. Minimal calls (throwaway spike, not the layer)
```
chips.get_chips()                          # 1 call — resolve presence + candidates for each target string
for each resolved chip_id:
    swi.get_modules(chip_name)             # 1 call — check the expected element class appears
# optionally: memmap.get_memory_maps(chip_id,'HW') as a base cross-check
```
Plus a **known-good control** target string (a chip we're confident is populated) to prove the probe itself works before trusting negatives.

### 4. Success criteria
- Control target resolves AND returns modules (probe is trustworthy).
- For each validation target: resolved in `get_chips()` **and** `get_modules()` returns the expected element class (DSP subsystem / SoundWire master).

### 5. Failure criteria
- Auth/connection error → inconclusive (fix access, retry) — **not** a "not populated" verdict.
- Control target empty → probe untrustworthy; discard results.
- Target absent from `get_chips()` → **not present**.
- Target present but expected element class absent from modules (across all revision candidates) → **present-but-unpopulated** (the honu-precedent risk).

### 6. Decision tree → build recommendation
```
control OK?
 ├─ no  → INCONCLUSIVE: fix access; do not decide. (Tracks A–C proceed regardless.)
 └─ yes →
     both validation targets present AND expected element class populated?
      ├─ yes            → (A) Build IPCAT layer for both target classes.
      ├─ exactly one    → (B) Build IPCAT layer for the confirmed class only;
      │                        route the other's blocker to the Confidence Ledger
      │                        (NEEDS_REVIEW) + domain-team escalation.
      └─ neither         → (C) Do NOT build the IPCAT layer now; the surface is
                               architecturally right but unpopulated for our chips.
                               Lean entirely on Tracks A–C (all IPCAT-independent).
```
**Most-likely outcome (from the availability assessment): (B)** — the SoundWire-class validation chip is very likely populated (named by IPCAT), the DSP-class validation chip's coverage is genuinely uncertain (new derivative, documented partial-coverage risk).

---

## 2. Recommended next actions
1. **Seed the Audio KB with target-agnostic rules** (Track A) — dependency-free, IPCAT-independent, highest reuse.
2. **Render the Confidence Ledger** (Track B) — pure rendering of existing data; largest reviewer-confidence gain per unit effort.
3. **Add the Cardinality-Authority validator in diagnostic form** (Track C) — cross-checks the count sources that already exist.
4. **Run the SWI probe** (Track D) — only when the user can supply `ipcat_client` + credentials; resolves the build/no-build gate.

## 3. Parallelizable work
- Tracks A, B, C are **mutually independent** and **independent of D**. They can proceed concurrently and in any order.
- Track D is independent of A/B/C but **blocked on an external precondition** (library + credentials) the user controls.

## 4. Highest-ROI work
- **Track A `audioreach.md` logical-port rule** and **Track B Confidence Ledger.** Both are IPCAT-independent, target-agnostic, and address the failure modes seen across *both* validation targets — i.e. they generalize.

## 5. Lowest-risk work
- **Track B Confidence Ledger** (additive rendering; changes no decision; cannot perturb Benchmark A/B) and **Track A KB seeding** (documentation; no runtime effect). These carry essentially zero regression risk.

## 6. SWI probe gate criteria
- The layer is built **only** for target classes where the probe shows *present AND expected-element-class populated*, with a trustworthy control. Absent/unpopulated → no layer for that class; route to ledger + escalation. Inconclusive (auth/network) → no decision, retry. (Full tree in Track D §6.)

## 7. Recommended order of implementation
1. Track B (Confidence Ledger) — lowest risk, immediate reviewer value, unblocks trust for everything downstream.
2. Track A (KB rules) — in parallel; `audioreach.md` first.
3. Track C (Cardinality Authority, diagnostic form) — after/with A, since it references KB rules for "legitimate divergence."
4. Track D (probe) — as soon as access preconditions are met; its outcome scopes any later IPCAT layer.
5. IPCAT Evidence Layer — **only** post-probe, scoped by the decision tree. Not before.

## 8. What should explicitly wait
- **Any IPCAT Evidence Layer / SWI-catalog logic** — waits on Track D's outcome.
- **Writing target-specific values into the KB** — never; they belong in target evidence.
- **Making validators/ledger decision-changing** — waits until after the Benchmark A/B baseline (avoid contaminating the comparison).
- **SID/IOMMU extraction, learn-loop automation** — after KB + ledger + at least one resolved-and-confirmed cycle.
- **Phase-2 generation / DTS / YAML / patches** — unchanged: last, gated on deterministic facts + ledger + cardinality authority.

## 9. Readiness for future generation
Generation readiness is defined **target-agnostically** as: for a given target, every domain in the Confidence Ledger that a generated artifact would depend on is `CORROBORATED` (not `MISSING`/`NEEDS_REVIEW`/`VERIFY`), and all Cardinality-Authority checks for the elements to be generated are non-warning. Tracks A–C build exactly the instruments that make this readiness *measurable per target*; Track D determines whether the authoritative-fact source (SWI catalog) is available to raise specific domains to `CORROBORATED`. No target is generation-ready until its own ledger says so — the framework provides the gauge, not a per-chip verdict.

---

## Appendix — Target-agnostic partition summary

| Artifact | Reusable content (shared framework) | Target-specific content (target evidence only) |
|---|---|---|
| `adsp.md` | provenance/anti-copy rule, power-model decision procedure, compatible-derivation method | any base address, rail index, per-SoC power verdict |
| `lpass.md` | macro taxonomy, surface-routing rule | a target's macro bases/inventory |
| `audioreach.md` | stack families, logical-port "flag-don't-fabricate" rule | a target's port→macro assignment |
| `soundwire.md` | count-vs-wiring distinction, base-provenance rule | a target's master count/base/routing |
| `audio_clocks.md` | anti-interpolation rule, rate-source authority | a target's rates/level set |
| Confidence Ledger | domain enum, status vocabulary, renderer | the current run's confidences/citations |
| Cardinality Authority | element-class list, mismatch policy | the current run's counts |
| SWI probe | `(target_string, expected_element_class)` driven procedure | which targets are passed in |

**Evidence sources:** `docs/IPCAT_CAPABILITY_ASSESSMENT.md`, `docs/NEXT_PHASE_RECOMMENDATION.md`, `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md`, `docs/SWI_CATALOG_AVAILABILITY_ASSESSMENT.md`; reference systems EVA_QLI_DT_Generator (`get_chip_candidates` partial-coverage precedent, `TODO_confidence_status.md`) and camera_dtsi (`cam_dtsi_tool.py` chip resolution, `references/kb/` rule-style KB, instance-count authority doctrine). Nord and Eliza onboarding reports cited **only** as proof-of-value, never as design inputs.
