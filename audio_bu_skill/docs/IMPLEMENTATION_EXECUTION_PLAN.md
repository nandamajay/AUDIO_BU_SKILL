# Implementation Execution Plan — Audio BU Skill Framework Artifacts

**Status:** Implementation *planning* only. No implementation, no code, no file creation, no DTS/YAML/patches, no Audio BU Skill changes, no IPCAT layer, no Phase-2. Nothing staged/committed/pushed.

**Baseline:** `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` (approved architecture). This document converts that baseline into work packages detailed enough to implement **without further architecture review**.

**Governance (unchanged):** shared framework = rules/patterns/validation/trust; target evidence = values/measurements/resolved facts; `provenance.md` is the root authority. Target-agnostic throughout; no target-specific value enters the KB.

**Codebase anchors identified this session (real integration points, so no rediscovery is needed later):**
- Schema: `orchestrator/reasoning/schemas.py` — `ANALYSIS_SCHEMA` (v`1.2.0`), `_CITED_FINDING` (`value/confidence/citations`), `_CODEC_ITEM`, `soundwire{present,master_count,confidence,citations}`, `audio_stack{lpass,…}`, `ipcat_findings{queried,returned_target_specific,returned_generic_only,notes,citations}`.
- Report renderer: `orchestrator/main.py` — `_render_onboarding_report()` @ `main.py:795`; existing section renderers `## Power Model Inspection` @707, `## Pin Cross-Check` @738, `## IPCAT Coverage` @769, `## NEEDS_REVIEW` @854, `## Cited evidence` @862; report written @ `main.py:581-582`.
- Validator: `skills/target_onboarding/validator.py` — `validate_output()` @25, `_findings_without_citations()` @123; schema `skills/target_onboarding/schema.json`.
- Analysis→envelope mapping: `orchestrator/runners/target_onboarding_runner.py` — `_map_analysis_to_envelope()` @340, `_build_audio_topology()` @487, `_ipcat_evidence_summary()` @529, `_collect_citations()` @590.

---

## 1. Executive summary

Three implementable work packages (WP-B, WP-A, WP-C) realize the approved Tracks B/A/C. All three are **additive, non-decision-changing, IPCAT-independent, and target-agnostic**. Track D (SWI probe) remains a separate externally-gated spike and is **not** part of this implementation plan except as a downstream consumer hook.

The approved order was B → A → C. **This plan challenges and refines it (see §7):** B and A have *no code dependency* on each other and should proceed **in parallel**; C depends *softly* on A (it cites KB rule IDs for the "legitimate divergence" registry) and *softly* on B (it emits into the same report region), so C goes last. The net recommendation keeps B and A concurrent, then C — a small but real improvement over strict serialization.

Each WP below specifies exact file modifications, reused vs new fields/mappings, flows, test plans, migration risk, rollback, and acceptance criteria. Rollback for all three is trivial because all three are additive: revert the diff, the report loses a section, nothing else changes.

---

## 2. Work packages

### WP-B — Confidence Ledger

1. **Exact file modifications required:**
   - `orchestrator/main.py`: add `_render_confidence_ledger(output) -> list[str]` (mirrors the shape of `_render_*` section builders around @707–@794); call it inside `_render_onboarding_report()` @795, inserted **before** `## NEEDS_REVIEW` @854 (ledger is the trust summary the reviewer reads first).
   - `orchestrator/reasoning/` (new small module, e.g. `ledger.py`): pure functions `map_fields_to_domains(analysis) -> dict[domain, list[field_conf]]`, `rollup(domain_fields) -> (band, status, sources, rule_ids)`. Keep logic out of `main.py` so it is unit-testable in isolation.
   - **No change to `ANALYSIS_SCHEMA`** — the ledger renders existing data.
2. **Existing schema fields reused:** `_CITED_FINDING.confidence/citations` (soc, board); `_CODEC_ITEM.confidence/citations` (codecs/amplifiers/mics/speakers); `soundwire.confidence/citations/master_count`; `audio_stack.*`; `ipcat_findings.*`; the envelope's existing `missing_evidence[]` and power-model NEEDS_REVIEW signal (already produced by `validate_output` @75 and `power_model_inspection`).
3. **New mappings required:** exactly one — a static **field→domain table** (schema field path → one of the 9 domain-enum values). Co-located with `ANALYSIS_SCHEMA` in `schemas.py` (or `ledger.py`) so drift is caught. Plus the deterministic status function (spec B.4). No new evidence fields.
4. **Rendering flow:** `_render_onboarding_report` → `_render_confidence_ledger` → `map_fields_to_domains` → per-domain `rollup` (min-confidence band + status derivation + citation union + governing KB rule IDs) → markdown table (spec B.5) → inserted as `## Confidence Ledger` section. Header carries the "diagnostic; does not change decisions; CORROBORATED = agreement not correctness" disclaimer.
5. **Dependency list:** none external. Depends only on data already in `output`. Soft-consumes KB rule IDs (WP-A) for the `KB rule` column — **degrades gracefully** to blank if a rule ID isn't yet published.
6. **Unit-test plan** (`tests/test_confidence_ledger.py`, new):
   - field→domain table total coverage (every `ANALYSIS_SCHEMA` leaf maps to exactly one domain or is explicitly excluded).
   - `rollup` min-semantics (weakest field drives band).
   - status derivation truth table: MISSING/NEEDS_REVIEW/CORROBORATED/VERIFY/NOT_APPLICABLE each hit by a crafted fixture.
   - all-`MISSING` target renders a full table (target-agnostic proof).
   - render is deterministic (same input → byte-identical section).
7. **Integration-test plan:** extend `tests/test_target_onboarding.py` — run the existing onboarding fixture(s) end-to-end, assert `## Confidence Ledger` appears, has all 9 rows, and that **no onboarding decision/field value changed** vs the pre-WP snapshot (diff only adds the section). Golden-file compare against a stored expected report.
8. **Migration risk:** low. Only risk is the field→domain table falling out of sync with `ANALYSIS_SCHEMA`; mitigated by the coverage test. No persisted-format change; older reports simply lack the section.
9. **Rollback plan:** revert the `main.py` call + delete `ledger.py` + test. Report reverts to prior form; zero data-model impact.
10. **Acceptance criteria:** ledger renders for every target incl. all-MISSING; 9 fixed domains always present; additive (golden diff = section-only); deterministic; disclaimer present; no decision path reads the ledger.

### WP-A — Audio KB

1. **Exact directory layout:**
   ```
   references/kb/
     provenance.md      # root authority (PROV-*)
     adsp.md            # ADSP-*
     lpass.md           # LPASS-*
     audioreach.md      # AR-*
     soundwire.md       # SWR-*
     audio_clocks.md    # CLK-*
     _schema/kb_entry.md   # the A.0 skeleton template (authoring reference)
     _index.md             # rule-ID registry (ID → file → one-line, immutable)
   ```
2. **File creation plan:** create the 6 KB files from the A.0 skeleton, seeded **only** with rules/patterns/distinctions/provenance carrying stable IDs; `provenance.md` first (others reference it). `_index.md` maintains the immutable ID registry. No target values.
3. **Rule-ID convention:** `<PREFIX>-<NNN>` for rules/patterns, `<PREFIX>-D<N>` for distinctions; prefixes `PROV/ADSP/LPASS/AR/SWR/CLK`; IDs **immutable once published** (deprecate, never renumber); registered in `_index.md`.
4. **Value-lint design** (`tests/test_kb_value_lint.py` + a reusable `kb_lint.py` checker): scan every KB file for forbidden value shapes — hex addresses (`0x[0-9a-fA-F]+`), bare register/size integers in rule context, clock rates (`\d+\s?[MkG]Hz`), part numbers (vendor-code patterns), SoC-specific compatible strings, document IDs. Any hit → lint failure with file:line. Allowlist for anonymized-illustration blocks is explicit and narrow. This is the mechanical guard that keeps values out of the KB.
5. **Learn-loop hooks:** define (not automate) the hook points — (a) reviewer-confirmation event (from WP-B workflow) is the trigger; (b) a proposal must pass value-lint; (c) contradiction with an existing ID → `WARN:` change-log entry + human adjudication; (d) promotion to a rule requires ≥2 independent confirmed targets. Implemented later; the hooks/pointers are documented now.
6. **Validation process:** value-lint runs in CI on every KB change; `_index.md` consistency check (every cited ID exists; no duplicate IDs); markdown-skeleton conformance check (required sections present).
7. **Ownership model:** `provenance.md` = highest-scrutiny, human-owned, slowest-changing (single owner sign-off required). Domain files = domain-reviewer owned. Learn-loop may *propose* but never *merge* without human adjudication. `_index.md` is append-mostly and owner-gated.
8. **Acceptance criteria:** 6 files + template + index exist from the skeleton; every rule has a unique immutable ID in `_index.md`; value-lint passes (zero values); no file names a target; every entry passes the litmus test; `provenance.md` rules referenced (not restated) by the others.
9. **Migration risk:** minimal — additive documentation; nothing consumes the KB at runtime yet except the (graceful-degrading) ledger `KB rule` column. Risk is authoring-quality (a value slips in) → caught by value-lint.
10. **Rollback plan:** delete `references/kb/` additions; ledger `KB rule` column goes blank (already graceful). No runtime impact.

### WP-C — Cardinality Authority

1. **Config structure:** a declarative `element_classes` config (e.g. `orchestrator/reasoning/cardinality_config.py` or a data file) — list of `{class, matcher_spec, applicable_sources[], legitimate_divergence_rule_ids[]}`. New classes = new rows; no core change.
2. **Element-class registry:** seed rows for `soundwire_master`, `lpass_macro_instance`, `dai_link`, `dmic_line`, `dsp_subsystem_instance`, `audioreach_port` — but **implement matcher logic only for classes a current fixture exercises** (spec critical-review §2); others declared, inert. Each row cites KB divergence rule IDs (from WP-A) rather than embedding logic.
3. **Enumeration-source model:** pluggable source adapters returning `(class → count)`: `dt_count` (from kernel DT / analysis), `evidence_count` (offline/schematic extraction already in analysis), `proposal_count` (from the proposed case fields). `catalog_count` is a **declared-but-unimplemented** adapter (post-Track-D hook). Sources are columns; adding one doesn't change the comparison core.
4. **Validation flow:** new module `orchestrator/reasoning/cardinality.py`: `collect_counts(output, config) -> {class: {source: n}}` → `compare(counts) -> [verdict]`. Verdict vocabulary: `agree | disagree | not_cross_checkable | disagree_with_authority | benign_divergence`. Invoked from the runner's post-analysis path (near `_map_analysis_to_envelope` @340) and surfaced by a `_render_cardinality(output)` section in `main.py` (adjacent to the ledger).
5. **Warning-generation flow:** `disagree` / `disagree_with_authority` → emit a `NEEDS_REVIEW` line (reuses the existing `## NEEDS_REVIEW` @854 channel — no new gating). `not_cross_checkable` / `benign_divergence` → informational line only. **Never hard-fails**; never blocks promotion.
6. **Test strategy** (`tests/test_cardinality.py`, new): matcher fixtures (precision — the dominant FP source, spec C.9); comparison truth table across source combinations; single-source → `not_cross_checkable`; benign-divergence downgrade via a KB rule ID; a `catalog_count`-present fixture producing `disagree_with_authority` (validates the post-SWI path additively without needing IPCAT).
7. **False-positive protection:** fixture-tested matchers (no per-target tuning); `not_cross_checkable` instead of silence-or-warning; legitimate-divergence registry; diagnostic-only (a FP costs a reviewer glance, never a blocked pipeline).
8. **Acceptance criteria:** operates on dt/evidence/proposal counts today; emits diagnostic verdicts only; adding a class/source is config-only; matcher fixtures pass; `catalog_count` path proven by fixture but inert until Track D; no hard-fail path exists.
9. **Migration risk:** low-moderate — the only WP that reads/interprets analysis structure for counts, so matcher bugs could produce noisy warnings. Mitigated by diagnostic-only + fixture tests + starting with only exercised classes.
10. **Rollback plan:** revert the runner call + `_render_cardinality` + delete `cardinality.py`/config/test. Report loses the section; NEEDS_REVIEW reverts to prior contents; zero data-model impact.

---

## 3. Dependency graph
```
provenance.md (WP-A root)
        │  (rule IDs)
        ▼
   WP-A KB files ──(rule IDs, soft)──► WP-B KB-rule column (graceful if absent)
        │                                   │
        │(divergence rule IDs, soft)        │(shares report region + NEEDS_REVIEW channel)
        ▼                                   ▼
       WP-C  ◄───────────────────────── (soft ordering) ──────────────
```
- **Hard dependencies:** none between WPs. Each compiles and passes tests alone.
- **Soft dependencies:** WP-B's `KB rule` column and WP-C's divergence registry *cite* WP-A rule IDs (both degrade gracefully to blank if unpublished). WP-C shares the report region and the NEEDS_REVIEW channel with WP-B, so building C after B avoids merge churn.

## 4. Parallelization opportunities
- **WP-B and WP-A run fully in parallel** — no shared code (B touches `main.py`+`schemas.py`+new `ledger.py`; A touches `references/kb/`+lint). Different files, different reviewers.
- **WP-C starts once A's rule IDs exist and B's report-region shape is settled** — not because of a compile dependency, but to avoid rework in `main.py`'s report section and the NEEDS_REVIEW channel.
- Within WP-A, `provenance.md` is authored first; the other five can be authored in parallel by domain owners.

## 5. Acceptance criteria (roll-up)
Per-WP criteria are in §2 (item 10 each). Cross-cutting: all three are **additive** (golden report diff shows only new sections), **non-decision-changing** (no existing field/value/promotion path altered), **target-agnostic** (each runs on an all-MISSING/absent-class target), and **KB frozen during any benchmark window**.

## 6. Risks
- **Field→domain table drift** (WP-B) → coverage test. 
- **Value leakage into KB** (WP-A) → value-lint CI gate.
- **Noisy cardinality warnings** (WP-C) → diagnostic-only + fixture-tested matchers + exercised-classes-only.
- **Rule-ID churn** → immutable IDs, deprecate-never-renumber, `_index.md` registry.
- **Benchmark contamination** → freeze KB + keep all three diagnostic until after the A/B baseline.
- **Scope creep into IPCAT** → `catalog_count` stays a declared, inert adapter until Track D returns a positive, controlled result.

## 7. Recommended implementation order (challenge of B→A→C)

**Is B→A→C still optimal? Mostly — with one refinement: run B and A concurrently, then C.**

- **Dependencies:** no hard inter-WP dependency; soft citations flow A→B and A→C; report-region sharing flows B→C. So A is on the critical path for *citations* but not for *B's core*.
- **Parallel:** B ∥ A is safe and faster (disjoint files). 
- **Fastest value:** **WP-B** — reviewer-confidence gain the moment it renders, on existing data, zero new inputs. Ship first (or first-among-parallel).
- **Lowest risk:** **WP-B and WP-A** — B is additive rendering; A is documentation behind a lint gate. WP-C carries the only interpretation risk.

**Recommended order:**
1. **WP-B and WP-A in parallel** (B for immediate value; A because its rule IDs unblock B's `KB rule` column and C's registry). Author `provenance.md` first within A.
2. **WP-C last** — after A's IDs are published and B's report region is settled, to consume rule IDs and avoid report-section merge churn.
3. **Track D (SWI probe)** — independent, externally gated (needs `ipcat_client` + user credentials); scopes only the *future* `catalog_count` adapter. Not blocking WP-A/B/C.

## 8. Definition of done per track
- **WP-B done:** `## Confidence Ledger` renders 9 fixed domains for any target; unit+integration+golden tests green; additive-only proven by golden diff; disclaimer present; no decision reads it.
- **WP-A done:** 6 KB files + template + `_index.md` exist from the skeleton; every rule has an immutable registered ID; value-lint green (zero values, zero target names); skeleton-conformance + index-consistency checks green; `provenance.md` referenced not restated.
- **WP-C done:** cardinality section emits diagnostic verdicts on dt/evidence/proposal counts; matcher fixtures + comparison truth-table green; single-source→not_cross_checkable; benign-divergence downgrade works; `catalog_count` path fixture-proven but inert; no hard-fail path; config-only extensibility demonstrated by a test adding a dummy class.

## 9. Go / No-Go recommendation

**GO — for WP-B and WP-A now (in parallel), WP-C immediately after, Track D independently when access preconditions are met.**

Justification: all three WPs are additive, non-decision-changing, IPCAT-independent, target-agnostic, and individually rollback-trivial; the real codebase integration points are identified (no rediscovery needed); each has a concrete test and acceptance definition; and none makes any DTS-generation assumption or admits a target value into the KB. The only gated item (Track D → `catalog_count`) is correctly isolated as an inert, declared adapter. There is no remaining architecture question blocking implementation.

**Conditions on GO (carry-forward constraints):** implement additively only; keep all three diagnostic (non-gating) until after the Benchmark A/B baseline; freeze the KB during benchmark windows; do not implement the `catalog_count` adapter or any IPCAT access until Track D returns a positive, credentialed result; no staging/commit/push without explicit review.

---

**Evidence sources:** `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` (approved baseline) and the four prior review docs; live codebase anchors in `orchestrator/main.py`, `orchestrator/reasoning/schemas.py`, `orchestrator/runners/target_onboarding_runner.py`, `skills/target_onboarding/validator.py` + `schema.json`. Nord/Eliza referenced only as anonymized proof-of-value.
