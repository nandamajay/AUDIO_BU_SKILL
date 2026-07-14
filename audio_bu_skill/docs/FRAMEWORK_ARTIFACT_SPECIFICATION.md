# Framework Artifact Specification — Audio BU Skill

**Status:** Architecture and artifact design only. No implementation, no code, no DTS/YAML/patches, no Audio BU Skill changes, no IPCAT Evidence Layer, no Phase-2. Nothing staged/committed/pushed.

**Purpose of this document:** to be detailed enough that implementation of Tracks A, B, and C can begin later **without further architecture review**, while guaranteeing the design stays **target-agnostic**, makes **no DTS-generation assumptions**, and **admits no target-specific value into the KB**.

**Governing rule (applied to every artifact herein):**
> If something would still be useful for an **unknown future target**, it belongs in the **shared framework**.
> If something is only true for a **specific target**, it belongs in **target evidence** (`targets/<t>/`).

Shared framework = rules, patterns, validation, trust. Target evidence = values, measurements, resolved target facts. Nord (SA8797P) and Eliza (CQ7790) appear only as anonymized proof-of-value, never as design inputs; no artifact hardcodes them.

---

# TRACK A — Audio Knowledge Base

## A.0 Cross-cutting KB contract (applies to all six files)

**Directory:** `references/kb/`
**Format:** Markdown, human-authored and learn-loop-appended, loaded on demand by the reasoning layer.

**The four content types every KB file is built from:**
- **Rule** — a normative "always/never" statement about how to reason (e.g. "never copy a register base from a nearest target").
- **Pattern** — a recurring situation and its recommended handling (e.g. "an interface with no matching logical-port macro → flag for human mapping").
- **Distinction** — a conceptual separation that prevents category errors (e.g. "silicon instance count ≠ board wiring").
- **Provenance guidance** — for a class of fact, *which source is authoritative* and *in what order*.

**Universal FORBIDDEN content (all files):** any concrete register address, base, size, IRQ number, clock rate, instance count, GPIO number, part number, compatible string bound to one SoC, document ID, or any statement true of exactly one target. These are *values* and live only in `targets/<t>/evidence/`.

**Universal ALLOWED content (all files):** rules, patterns, distinctions, provenance guidance, decision procedures, named anti-patterns, and *anonymized* illustrations ("a target was observed to…") that demonstrate why a rule exists without naming the target or its value.

**Shared per-file template structure (every KB file uses this skeleton):**
```
# KB: <topic>
## Scope            — what class of audio hardware/reasoning this covers
## Rules            — normative always/never statements (numbered, stable IDs)
## Patterns         — recurring situations → recommended handling
## Distinctions     — category separations that prevent errors
## Provenance       — fact-class → authoritative-source order
## Anti-patterns    — named recurring failure modes
## Anonymized illustrations — "a target exhibited X" (no names, no values)
## Open questions   — known gaps this KB cannot yet answer
## Change log       — learn-loop appends, dated, with WARN: conflict flags
```

**Stable rule IDs:** each rule/pattern gets an immutable ID (e.g. `PROV-001`, `SWR-003`) so the ledger, the validator, and target evidence can *cite* a KB rule without copying its text. This is the mechanism that keeps values out of the KB: target evidence says "resolved per `PROV-001`," not the rule's content, and the KB never says "target X's value is…".

**Litmus test enforced at authoring and learn-loop time:** *"Would this still be useful for a future target that does not resemble any target seen so far?"* If no → reject from KB, route to target evidence.

---

## A.1 `references/kb/provenance.md` (NEW — the shared root)

1. **Purpose:** the single source of the cross-cutting *provenance and trust rules* that every other KB file references by ID. It answers, generically, "for any class of hardware fact, where does the authoritative value come from, and what must never be used as a substitute?" All other files defer here rather than restating provenance.

2. **Sections:** the shared skeleton (A.0). `Rules` and `Provenance` are the heart.

3. **Template structure:** shared skeleton.

4. **Allowed content:**
   - **Rule PROV-001 (anti-copy):** a per-silicon value (register base, IRQ, clock rate, SID, instance count) must never be copied from a nearest/sibling target; absence of a target's own value is `MISSING`, not "reuse the neighbour's."
   - **Rule PROV-002 (authority order):** authoritative-source precedence for a per-silicon value is: the target's own catalog/enumeration source > the target's own boot/runtime evidence > the target's own kernel DT > (nothing — otherwise `MISSING`). Prose/family docs are never a source for a per-silicon *value* (only for topology/family).
   - **Rule PROV-003 (surface routing):** route each question to the surface that can answer it — instance/register/rate questions to enumeration/catalog; topology/family/"which-parts-pair" questions to prose docs. Do not ask a prose surface for a value or an enumeration surface for narrative.
   - **Distinction PROV-D1:** *silicon fact* (true of the chip) vs *board fact* (true of this board's wiring) vs *inference* (derived, unconfirmed). Every emitted fact must be classifiable into exactly one.
   - **Provenance guidance:** a table of fact-class → authoritative-source-order (generic classes only: register-base, IRQ, clock-rate, instance-count, SID, power-domain, routing).

5. **Forbidden content:** any actual source URL/endpoint credentials, any target's resolved value, any SoC-specific authority exception.

6. **Examples:**
   - *Rule:* "PROV-001: never substitute a sibling SoC's value for a missing per-silicon value."
   - *Pattern:* "value requested but no authoritative source available → emit `MISSING` + cite which source was tried."
   - *Distinction:* "PROV-D1: base address = silicon fact; which peripheral a bus drives = board fact."
   - *Provenance guidance:* "register-base: catalog > boot evidence > DT > MISSING."

7. **Must remain in `targets/<t>/` instead:** the resolved authority *outcome* for a target ("this target's base was taken from boot evidence at 0x…") — the citation of PROV-001/002 is what appears in evidence, not a new rule.

8. **Learn-loop model:** provenance rules are the **most stable** and change least; the learn-loop may add a new *generic* fact-class row or tighten authority order, always with a `WARN:` if it conflicts with an existing rule, and always subject to human confirmation. Never appends a target value.

---

## A.2 `references/kb/adsp.md`

1. **Purpose:** reusable reasoning for the audio DSP subsystem (remoteproc/PAS class) on *any* SoC — base-provenance discipline, power-model decision procedure, generic compatible-derivation method.
2. **Sections:** shared skeleton; emphasis on `Rules`, `Patterns`, `Anti-patterns`.
3. **Template structure:** shared skeleton.
4. **Allowed content:**
   - Rule: DSP-subsystem register base follows `PROV-001`/`PROV-002` (defer to provenance.md, don't restate).
   - Pattern: "determine the SoC's power-model *class* before drafting power domains; do not assume a specific rail set exists" — as a decision procedure keyed on power-model class, not on a rail list.
   - Distinction: DSP *firmware/image* facts vs DSP *register/power* facts (different sources, different confidence).
   - Provenance: DSP power-domain model → determined per-SoC power architecture; never assumed.
5. **Forbidden content:** any base address, any specific rail index/name, any per-SoC "the answer is SCMI/rpmhpd" verdict, any concrete compatible string.
6. **Examples:**
   - *Rule:* "A DSP PAS base is a silicon fact (PROV-001)."
   - *Pattern:* "nearest-target power domains drafted without confirming the SoC's power model → NEEDS_REVIEW."
   - *Distinction:* "power-model *class* (rail-based vs abstraction-based) vs the *specific* domain index."
   - *Provenance guidance:* "power-domain model: SoC power-architecture evidence > MISSING."
7. **Must remain in `targets/<t>/`:** the target's actual base, its actual power-model verdict, its rail/domain indices, its confirmed compatibles.
8. **Learn-loop model:** may add *generalized* "for SoCs of power-model class X, the DSP path tends to follow convention Y (confidence, N observations)" only after multiple confirmed targets; single-target observations stay anonymized illustrations, not rules.

---

## A.3 `references/kb/lpass.md`

1. **Purpose:** LPASS macro-block conventions and surface-routing for any LPASS-bearing SoC.
2. **Sections:** shared skeleton; emphasis on `Distinctions`, `Provenance`.
3. **Template:** shared skeleton.
4. **Allowed content:** generic macro taxonomy (macro *roles*, not per-SoC inventories); rule "macro register bases are silicon facts (PROV-002); macro presence/topology may come from prose (PROV-003)"; pattern "macro node absent in kernel tree ≠ hardware absent."
5. **Forbidden content:** any target's macro base, any target's macro inventory, any document ID.
6. **Examples:**
   - *Rule:* "macro base = silicon fact; route via PROV-002."
   - *Pattern:* "absence of macro node in DT → do not conclude hardware absence; mark inference."
   - *Distinction:* "macro *presence* (may be prose-confirmed) vs macro *base* (silicon-only)."
7. **Must remain in `targets/<t>/`:** which macros a target has and their bases.
8. **Learn-loop model:** may add generalized surface-routing refinements confirmed across targets; never an inventory.

---

## A.4 `references/kb/audioreach.md`

1. **Purpose:** AudioReach/GPR/q6apm/q6prm stack conventions and — highest-value — the **logical-port mapping ambiguity pattern** that no catalog resolves.
2. **Sections:** shared skeleton; emphasis on `Patterns`, `Open questions`.
3. **Template:** shared skeleton.
4. **Allowed content:** generic stack-layer taxonomy; **Pattern (flagship): "logical-port header macros are a bounded named set; a hardware interface index outside that set has no guaranteed 1:1 macro → flag for human/DSP-team mapping, never fabricate a macro"**; provenance guidance "authoritative port mapping lives with the DSP/firmware owner, not DT inference."
5. **Forbidden content:** any target's specific interface→macro assignment, any placeholder macro treated as truth.
6. **Examples:**
   - *Rule:* "never invent a logical-port macro to fill a gap."
   - *Pattern:* "interface index with no matching macro → NEEDS_REVIEW + escalate."
   - *Distinction:* "a drafted placeholder mapping vs a confirmed mapping."
   - *Provenance:* "port mapping: DSP/firmware owner > MISSING (never DT-guess)."
7. **Must remain in `targets/<t>/`:** the target's interface number and any proposed/confirmed macro.
8. **Learn-loop model:** accumulate a *generalized* "interface-class → typical-macro-family" heuristic table with confidence and observation counts; the "flag-don't-fabricate" rule is permanent. Highest reuse: helps every target regardless of IPCAT/family.

---

## A.5 `references/kb/soundwire.md`

1. **Purpose:** SoundWire controller/master conventions with the **silicon-vs-board separation**.
2. **Sections:** shared skeleton; emphasis on `Distinctions`.
3. **Template:** shared skeleton.
4. **Allowed content:** **Distinction (flagship): master *count* = silicon/enumeration fact; *which master drives which peripheral* = board fact — separate evidence classes"**; rule "controller base = silicon fact (PROV-002)"; pattern "missing controller node in DT ≠ proof of count."
5. **Forbidden content:** any target's master count, base, or routing.
6. **Examples:**
   - *Rule:* "controller base via PROV-002."
   - *Pattern:* "no controller node in DT → count not derivable from DT; seek enumeration."
   - *Distinction:* "count (silicon) vs routing (board)."
7. **Must remain in `targets/<t>/`:** the target's master count/base/routing.
8. **Learn-loop model:** paired with Track C; may add generalized enumeration heuristics; never a per-target count. Feeds the cardinality validator's "legitimate divergence" registry.

---

## A.6 `references/kb/audio_clocks.md`

1. **Purpose:** audio clock-controller conventions and the **anti-interpolation provenance rule**.
2. **Sections:** shared skeleton; emphasis on `Provenance`, `Anti-patterns`.
3. **Template:** shared skeleton.
4. **Allowed content:** rule "clock names/rates are per-silicon freq-plan facts; never interpolate or copy a rate/level-set from a nearest target — level counts legitimately differ" (PROV-001 specialization); provenance "rates: freq-plan/catalog > MISSING"; anti-pattern "nearest-target rate copy."
5. **Forbidden content:** any target's rates or level set.
6. **Examples:**
   - *Rule:* "never interpolate clock levels across SoCs."
   - *Pattern:* "prose gave sequences not rates → rates remain MISSING."
   - *Anti-pattern:* "nearest-target clock-rate copy."
7. **Must remain in `targets/<t>/`:** the target's actual rates/levels.
8. **Learn-loop model:** may add generalized "clock-controller family → expected rate-source" rules; never raw rate tables.

---

## A.7 KB learn-loop integration model (all files)

- **Trigger:** a domain resolved during onboarding **and** confirmed by a human reviewer.
- **Extraction:** the loop proposes a *generalized* rule/pattern (never a value). A value-shaped proposal is auto-rejected by a lint check (regex/heuristic for addresses, counts, part numbers, doc IDs).
- **Conflict handling:** if the proposal contradicts an existing rule ID, append with a `WARN:` marker in the change log and require human adjudication (camera_dtsi `learn` pattern).
- **Provenance of KB edits:** each change-log entry records the rule ID, date, and that it derived from N confirmed targets (anonymized). Rules promoted from "1 observation" to "rule" require ≥2 independent confirmed targets.
- **Never:** the loop never writes to `targets/<t>/`; it never promotes a single-target observation directly to a rule; it never stores a value.

---

# TRACK B — Confidence Ledger

## B.1 Domain enum (fixed audio-subsystem taxonomy — target-agnostic)
`power_model` · `clocks` · `dsp_subsystem` · `lpass_macros` · `soundwire` · `codecs` · `dt_topology` · `audioreach_ports` · `sid_iommu`

The enum is **framework-fixed**; it is the same set of rows for every target. A target that has no evidence for a domain still shows the row (as `MISSING`) — this is what makes the ledger a *gauge* rather than a per-target artifact.

## B.2 Status enum
- `CORROBORATED` — ≥2 independent sources agree.
- `NEEDS_REVIEW` — present but single-source, low-confidence, or ungated.
- `MISSING` — no evidence (from `missing_evidence`).
- `VERIFY` — from a structurally authoritative source but not yet confirmed for this target (e.g. catalog value pending sign-off).
- `NOT_APPLICABLE` — domain provably absent for this target class (e.g. no SoundWire on the target) — distinct from `MISSING` (which means "should exist, not found").

## B.3 Confidence model
- Numeric `confidence ∈ [0,1]` per domain, or `null`. Sourced from existing per-field `ANALYSIS_SCHEMA` confidences, rolled up (B.4). Rendered as coarse bands — `high ≥0.75` · `medium 0.4–0.75` · `low <0.4` · `—` (null) — to avoid false precision. **Bands are the display; the raw float is retained internally for the roll-up only.**

## B.4 Roll-up rules (per domain)
1. Map each per-field confidence/citation to its domain (a static field→domain table — the only new mapping needed).
2. Domain confidence = **min** of its contributing fields' confidences (conservative: a domain is only as trustworthy as its weakest required field). Rationale: prevents a well-known field from masking an unknown one.
3. Domain status derivation (pure function, deterministic):
   - any contributing field in `missing_evidence` and no positive evidence → `MISSING`;
   - ≥2 independent sources on the governing field → `CORROBORATED`;
   - single authoritative-but-unconfirmed source → `VERIFY`;
   - else → `NEEDS_REVIEW`;
   - domain marked absent-by-class → `NOT_APPLICABLE`.
4. Evidence sources = union of contributing fields' citations (deduped, abbreviated).

## B.5 Rendering layout (a new additive section in `onboarding_report.md`)
```
## Confidence Ledger
Per-domain confidence and provenance. Diagnostic; does not change onboarding decisions.

| Domain           | Confidence | Status         | Evidence source (abbrev)        | KB rule |
|------------------|-----------|----------------|----------------------------------|---------|
| <domain enum>    | <band>    | <status enum>  | <deduped citations>              | <IDs>   |
```
The `KB rule` column cites the governing KB rule ID(s) (e.g. `PROV-002`, `SWR-D1`) — linking trust to the rule that governs the domain without copying rule text.

## B.6 Example output (validation walkthroughs — illustrations of the *generic renderer*, not schema content)

*Illustration A — a DSP-heavy run (Nord-shaped, anonymized):*
```
| dsp_subsystem   | low    | NEEDS_REVIEW   | nearest-copy conflicts w/ boot | PROV-001 |
| power_model     | low    | NEEDS_REVIEW   | power model unconfirmed         | ADSP-P1  |
| clocks          | —      | MISSING        | no rate table                   | CLK-001  |
| codecs          | medium | CORROBORATED   | driver family + patch           | —        |
```
*Illustration B — a SoundWire run (Eliza-shaped, anonymized):*
```
| soundwire       | low    | NEEDS_REVIEW   | count ambiguous (no enumeration)| SWR-D1   |
| codecs          | high   | CORROBORATED   | schematic + family match        | —        |
| dt_topology     | medium | NEEDS_REVIEW   | board DTS absent                | —        |
```
Both are the **same renderer** over different runs — the proof of target-agnosticism.

## B.7 Reviewer workflow
1. Reviewer reads the ledger first — it is the report's trust summary.
2. `MISSING`/`NEEDS_REVIEW`/`VERIFY` rows are the work list; `CORROBORATED` rows need no action.
3. Reviewer confirms or corrects; a confirmation on a domain is the **learn-loop trigger** (Track A.7) and may raise status.
4. Reviewer sign-off is recorded per domain (in target evidence, not the KB).

## B.8 Generation readiness criteria (target-agnostic, no DTS assumptions)
A target is **generation-ready for a given artifact class** iff **every domain that artifact class depends on is `CORROBORATED`** (not `MISSING`/`NEEDS_REVIEW`/`VERIFY`) **and** all Track C checks for the involved elements are non-warning. The dependency map (artifact-class → required domains) is defined generically when generation is designed — **not now**; this spec only fixes the *readiness predicate*, not any generator. No target is ready until its own ledger says so.

## B.9 How the ledger stays target-agnostic
- Domains, statuses, bands, roll-up, and readiness predicate are **framework-fixed**; only the *cell values* come from the current run.
- The ledger stores no resolved value in the framework — it *renders* values that already live in the run's analysis output and cites KB rule IDs.
- The same code produces a ledger for any target, including one with an all-`MISSING` profile.

---

# TRACK C — Cardinality Authority

## C.1 Element classes (extensible config, not hardcoded targets)
Enumerable audio elements: `soundwire_master` · `lpass_macro_instance` · `dai_link` · `dmic_line` · `audioreach_port` · `dsp_subsystem_instance`. Defined as a config list keyed by *element class* with a matcher spec — new classes are added by config, never by per-target code.

## C.2 Enumeration sources
- `dt_count` — instances present in the kernel DT.
- `evidence_count` — from offline/schematic evidence extraction.
- `proposal_count` — what the onboarding case proposes.
- `catalog_count` — (post-SWI only) authoritative enumeration from the SWI catalog.

## C.3 Comparison model
For each element class present in a run, collect the available counts, then:
- **authority present (catalog_count exists):** every other source is compared against `catalog_count`; `catalog_count` is N (camera_dtsi doctrine).
- **no authority:** pairwise-compare the available sources for agreement; there is no ground truth, only agreement/disagreement.
Output per element class: `{class, counts:{source→n}, verdict}`.

## C.4 Warning policy (NEEDS_REVIEW; never hard-fail)
- `proposal_count` disagrees with any independent count.
- two independent evidence sources disagree.
- (post-SWI) any source disagrees with `catalog_count`.

## C.5 Informational policy (not a warning)
- only one count source exists → `not_cross_checkable` (report it; silence would falsely imply agreement).
- a divergence covered by a KB "legitimate divergence" rule (e.g. board depopulates a silicon-present instance) → informational, cite the KB rule ID.

## C.6 Before SWI
Operates on `dt_count` / `evidence_count` / `proposal_count` only — fully functional and target-agnostic today; catches proposal-vs-evidence and evidence-vs-evidence mismatches. No authority, so verdicts are "agree / disagree / not_cross_checkable."

## C.7 After SWI
`catalog_count` becomes authority; verdicts upgrade from "sources disagree" to "source disagrees with authority," and a matching authority resolves prior `not_cross_checkable` cases. Purely additive — no redesign.

## C.8 Future extensibility
- New element class = new config row (matcher + which sources apply). No core change.
- New enumeration source = new column in the comparison. No core change.
- The KB "legitimate divergence" registry grows via the learn-loop (generalized rules only).

## C.9 False-positive mitigation
- **Matcher precision:** each element class carries an explicit matcher spec; over-broad matchers (the main FP source) are unit-tested against fixtures, not tuned per target.
- **`not_cross_checkable` instead of silence or warning** when only one source exists — avoids both false alarms and false confidence.
- **Legitimate-divergence registry** downgrades known-benign mismatches to informational.
- **Diagnostic-only:** a false positive costs a reviewer glance, never a blocked pipeline — the asymmetry is deliberately safe.

---

# CRITICAL REVIEW

## 1. Hidden risks
- **Ledger min-roll-up can look punitive:** taking the min across a domain's fields means one weak field drives the whole domain to `low`. Correct for trust, but reviewers may perceive the tool as pessimistic and start ignoring it. *Mitigation:* show the governing (weakest) field inline so the low band is explainable, not mysterious.
- **KB rule IDs as an API:** once the ledger and evidence cite `PROV-002`, rule IDs become a contract. Renaming/renumbering later breaks citations. *Mitigation:* IDs are immutable once published; deprecate, never renumber.
- **Provenance.md centralization:** every file defers to it, so an error there propagates everywhere. *Mitigation:* it is the most-reviewed, slowest-changing file; changes require human sign-off.

## 2. Over-engineering risks
- **Nine domains / six element classes on day one** may exceed what two validation targets exercise. Building matchers/roll-ups for domains never yet seen risks speculative generality. *Mitigation:* ship the enum/class list as fixed (cheap, they're just labels) but only implement roll-up/matcher logic for domains that have appeared; others render `MISSING`/`not_cross_checkable` with zero logic.
- **`VERIFY` and `NOT_APPLICABLE` statuses** add nuance that may be unused pre-SWI. *Mitigation:* keep them in the enum spec but they cost nothing until a source produces them.

## 3. Maintenance risks
- **KB drift** (below) and **field→domain mapping table** (B.4) is the one piece of new coupling — if `ANALYSIS_SCHEMA` fields change, the mapping must track them. *Mitigation:* co-locate the mapping with the schema and add a test that every schema field maps to exactly one domain.

## 4. Learn-loop risks
- **Value leakage:** the loop's biggest hazard is smuggling a value into the KB disguised as a rule ("DSP base is typically 0x…"). *Mitigation:* the value-lint auto-reject (A.7) + human adjudication; never auto-merge.
- **Premature generalization:** promoting a 1-target observation to a rule creates a false "rule" that misguides future targets. *Mitigation:* ≥2 independent confirmed targets to promote; single observations stay anonymized illustrations.
- **Feedback contamination of the benchmark:** if the learn-loop runs *during* a Benchmark A/B window, the KB changes mid-comparison. *Mitigation:* freeze the KB during benchmark runs.

## 5. KB drift risks
- **Rule sprawl / contradiction:** unbounded appends produce overlapping or conflicting rules. *Mitigation:* `WARN:` conflict flagging on append; periodic human consolidation; stable IDs make contradictions detectable.
- **Staleness:** a rule true today may not hold for a future audio architecture. *Mitigation:* rules carry observation counts + dates; `Open questions` sections make gaps explicit rather than papered over.

## 6. Confidence-ledger pitfalls
- **False precision** from numeric confidences → mitigated by coarse bands.
- **Reviewer over-trust of `CORROBORATED`** ("two sources agreed" can still be two wrong sources) → status reflects agreement, not correctness; document this explicitly in the ledger header.
- **Additivity erosion:** pressure to let the ledger *gate* decisions would perturb the benchmark. *Mitigation:* hard rule — diagnostic-only until after the A/B baseline.

## 7. Cardinality-authority pitfalls
- **Matcher over-broadness** = the dominant false-positive source → fixture-tested matchers, not per-target tuning.
- **Treating pre-SWI agreement as truth:** three sources agreeing without an authority is still not ground truth. *Mitigation:* verdict vocabulary distinguishes "agree" from "authoritative."
- **Authority over-trust post-SWI:** a catalog value can itself be wrong/partial (the honu partial-coverage precedent). *Mitigation:* catalog authority still routes through the ledger as `VERIFY` until confirmed, not auto-`CORROBORATED`.

## 8. Valuable but should be postponed
- **SID/IOMMU domain logic** — lowest confidence in both reference systems; keep the enum row, defer the logic.
- **Learn-loop automation** — design now, automate only after the KB has manually-authored rules and ≥1 confirmed cycle.
- **Ledger-gated generation readiness** — define the predicate now (B.8), wire it to a generator only when Phase-2 is authorized.
- **Post-SWI catalog_count integration** — gated on the Track D probe outcome; do not build until a chip class is confirmed populated.
- **AudioReach-port and dmic_line matchers** — postpone until a run actually exercises them; the flagship `audioreach.md` *rule* is valuable now, the *cardinality matcher* is not yet.

---

## Implementation-readiness checklist (for the later build, not now)
- [ ] KB: create 6 files from the A.0 skeleton; seed only rules/patterns/distinctions/provenance with stable IDs; run value-lint.
- [ ] Ledger: add field→domain mapping table + deterministic status function + additive report section; no schema change to evidence.
- [ ] Cardinality: element-class config + matcher fixtures + comparison function emitting diagnostic verdicts.
- [ ] All three: additive, non-decision-changing, KB frozen during any benchmark.
- [ ] None of the above depends on IPCAT; Track D probe outcome only scopes a *later* `catalog_count` addition.

**Evidence sources:** `docs/IPCAT_CAPABILITY_ASSESSMENT.md`, `docs/NEXT_PHASE_RECOMMENDATION.md`, `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md`, `docs/SWI_CATALOG_AVAILABILITY_ASSESSMENT.md`, `docs/NEXT_EXECUTION_PLAN.md`; reference systems EVA_QLI_DT_Generator and camera_dtsi (rule-style KB, instance-count authority doctrine, `learn` conflict-flagging, partial-coverage precedent). Nord and Eliza cited only as anonymized proof-of-value.
