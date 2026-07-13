# WP-B & WP-A Implementation Prep — Audio BU Skill

**Status:** Final implementation-preparation review. No implementation, no code edits, no file creation, nothing staged/committed/pushed. This document is detailed enough that coding can begin immediately after review.

**Approved scope & order (unchanged):** WP-B ∥ WP-A, then WP-C. This prep covers **WP-B and WP-A only**. Track D and WP-C are out of scope here except as named downstream hooks.

**Governance (unchanged):** shared framework = rules/patterns/validation/trust; target evidence = values/measurements/resolved facts; `provenance.md` is root authority; target-agnostic; no target value in the KB.

**Verified codebase facts (read this session — the basis for every instruction below):**
- `orchestrator/main.py`: report is assembled by `_render_onboarding_report(output)` @795. It reads `output["generated_case"]` (`gc`), `["similarity_report"]`, `["target_profile"]`. Additive sections are `_render_*_section(gc) -> list[str]`, each returning `[]` when data absent, chained @870–873:
  ```
  lines += _render_kernel_history_section(gc)
  lines += _render_power_model_inspection_section(gc)
  lines += _render_pin_crosscheck_section(gc)
  lines += _render_ipcat_findings_section(gc)
  ```
  followed by `## Promotion` @875. `## NEEDS_REVIEW` is rendered inline @854. Report written @581-582 via `write_text(_render_onboarding_report(output), …)`.
- Domain data the ledger reads already lives in `gc["audio_topology"]` (built by `target_onboarding_runner._build_audio_topology` @487): keys `soundwire` (`{present,master_count,confidence,citations}`), `power_model` (`{kind,confidence,citations,needs_review,inspection_hint}`), `audio_stack` (`{lpass,adsp,audioreach,gpr,apm,q6apm,q6prm,citations}`), `ipcat_findings`, `pin_crosschecks`, `citations`. Plus `gc["needs_review"]` (list of `"<field>: <note>"`), and `output["target_profile"]["cites"]`.
- `orchestrator/reasoning/schemas.py`: `ANALYSIS_SCHEMA` v`1.2.0`; per-field confidence/citations via `_CITED_FINDING` (soc/board), `_CODEC_ITEM` (codecs/amplifiers/mics/speakers), `soundwire`, `power_model`, plus `missing_evidence[]`, `overall_confidence`, `human_review_needed`.
- `skills/target_onboarding/validator.py`: `validate_output` @25 enforces power-model `needs_review` (@75) and citations (`_findings_without_citations` @123). Schema mirror: `skills/target_onboarding/schema.json`.
- `tests/test_target_onboarding.py`: `test_onboard_smoke` @100 runs onboarding on a fake kernel, asserts the rendered report contains `AUTO-GENERATED`/`NEEDS_REVIEW`, and (critically) asserts the **kernel sentinel is unmodified** and **no case.py / no .patch** is produced. `_render_and_exec` @86 execs the generated case.

---

# WP-B — Confidence Ledger

## 1. Exact functions to create
- **`orchestrator/reasoning/ledger.py`** (new module — pure, no I/O, unit-testable):
  - `FIELD_DOMAIN_MAP: dict[str, str]` — static field-path → domain-enum table (the one new mapping). Domains: `power_model, clocks, dsp_subsystem, lpass_macros, soundwire, codecs, dt_topology, audioreach_ports, sid_iommu`.
  - `def build_ledger(gc: dict, analysis: dict | None) -> list[dict]` — returns one row per domain: `{domain, band, status, sources, rule_ids}`. Uses min-confidence roll-up (spec B.4) and the deterministic status function.
  - `def _rollup(domain: str, contribs: list[dict]) -> tuple[str,str,list[str],list[str]]` — `(band, status, sources, rule_ids)`; band via `high≥0.75 / medium 0.4–0.75 / low<0.4 / —`; status via the B.4 truth table (`MISSING/NEEDS_REVIEW/CORROBORATED/VERIFY/NOT_APPLICABLE`).
  - `def _status_of(contribs, missing_evidence, needs_review_fields) -> str` — the pure status derivation.
- **`orchestrator/main.py`**: `def _render_confidence_ledger(gc: dict) -> list[str]` — mirrors the existing `_render_*_section` contract (returns `[]` only if `gc` has no analyzable domains, but by design renders all 9 rows for any real run). Calls `ledger.build_ledger`, formats the spec-B.5 table with the diagnostic disclaimer header.

## 2. Exact functions to modify
- **`orchestrator/main.py` `_render_onboarding_report` @795**: insert `lines += _render_confidence_ledger(gc)` in the additive chain @870–873, positioned **immediately before `## Promotion`** (@875) and **after** the existing diagnostic sections — so the ledger is the trust summary just above promotion guidance. (Alternative: directly after `## NEEDS_REVIEW` @859; choose the pre-Promotion slot for reviewer flow. This is the only line added to the assembly.)
- **No other production function is modified.** No change to `schemas.py` data model, `validator.py`, or `target_onboarding_runner.py`. `FIELD_DOMAIN_MAP` lives in `ledger.py` (may import field names from `schemas.py` for the coverage test, read-only).

## 3. Expected diff footprint
- New file `orchestrator/reasoning/ledger.py`: ~120–160 LOC.
- `orchestrator/main.py`: +1 call line in `_render_onboarding_report`; +1 new `_render_confidence_ledger` (~30 LOC). No deletions, no signature changes.
- New test `tests/test_confidence_ledger.py`: ~150 LOC.
- Total: ~2 files touched/created in `orchestrator/`, 1 new test. Zero schema/validator churn.

## 4. Test files affected
- **New** `tests/test_confidence_ledger.py` (unit — see §5/§9).
- **Extended** `tests/test_target_onboarding.py`: add an assertion in `test_onboard_smoke` that the rendered report contains `## Confidence Ledger` and that the pre-existing assertions (kernel sentinel unmodified, no case.py, no .patch, `AUTO-GENERATED`/`NEEDS_REVIEW` present) **still pass** — proving additivity.

## 5. Golden-file strategy
- Store a **golden onboarding report** for the existing fake-kernel fixture under `tests/golden/onboarding_report.<fixture>.md` (or inline expected substring blocks if a full golden is too brittle).
- Test asserts: (a) the post-WP report equals the golden **with exactly one new contiguous `## Confidence Ledger` block added** and no other line changed — a structural diff check (split on `## ` headers; assert the set difference is exactly `{"Confidence Ledger"}`); (b) the ledger block is byte-deterministic across runs.
- Rationale: a header-set diff is robust to line-number drift while still proving additivity; full-byte golden is optional and can follow once the section stabilizes.

## 6. Backward compatibility analysis
- **Report consumers:** the report is human-facing Markdown; adding a section cannot break machine consumers (there are none parsing it — `main.py:508` only prints a hint). Older stored reports simply lack the section.
- **Data model:** unchanged. `ANALYSIS_SCHEMA` v1.2.0 untouched; no `schema.json` change; no new required fields. QGenie output contract identical.
- **`validate_output`:** unaffected — ledger is render-time only; it reads validated data, never gates it.
- **Absent-data behavior:** a pre-slice-6 `generated_case` without `audio_topology` still renders — every domain resolves to `MISSING`/`NOT_APPLICABLE` from `gc`/`analysis` fallbacks; `_render_confidence_ledger` must tolerate missing `audio_topology` exactly as the sibling `_render_*` sections do (`(gc.get("audio_topology") or {}).get(...)`).

## 7. Risks
- **FIELD_DOMAIN_MAP drift vs `ANALYSIS_SCHEMA`** → coverage unit test asserting every schema leaf maps to a domain or is explicitly excluded.
- **Min-roll-up perceived as pessimistic** → render the governing (weakest) field's citation inline so a `low` band is explainable.
- **Placement regressions** → the header-set diff test pins additivity.
- **Reading unvalidated shapes** → guard every `gc`/`analysis` access with `or {}` / `or []`, matching existing section code.
- **CORROBORATED misread as "correct"** → mandatory disclaimer line in the section header.

## 8. Recommended implementation sequence (WP-B)
1. Write `ledger.py` pure functions + `FIELD_DOMAIN_MAP`.
2. Write `tests/test_confidence_ledger.py` (unit) → green in isolation (no orchestrator run needed).
3. Add `_render_confidence_ledger` + the single call line in `main.py`.
4. Extend `test_target_onboarding.py` + add the golden/header-set diff assertion.
5. Run full suite; confirm additive-only diff and unchanged decisions.

## 9. Acceptance checklist (WP-B)
- [ ] `## Confidence Ledger` renders for every target, incl. an all-`MISSING` target and a target with no `audio_topology`.
- [ ] All 9 fixed domains always present (never fewer/more).
- [ ] Bands/statuses derived deterministically (same input → identical output).
- [ ] Min-roll-up semantics verified; governing weak field shown.
- [ ] Disclaimer header present ("diagnostic; does not change decisions; CORROBORATED = agreement not correctness").
- [ ] `KB rule` column degrades gracefully to blank when WP-A IDs absent.
- [ ] Header-set diff proves section-only addition; existing `test_onboard_smoke` assertions still pass.
- [ ] No `schemas.py` / `validator.py` / `schema.json` change.

## 10. Review checklist (WP-B)
- [ ] No decision/gating path reads the ledger (grep for `build_ledger`/`_render_confidence_ledger` callers = render only).
- [ ] No target-specific literal in `ledger.py` (no SoC/part/address constants).
- [ ] `FIELD_DOMAIN_MAP` coverage test present and green.
- [ ] All `gc`/`analysis` accesses null-guarded like sibling sections.
- [ ] Placement matches approved slot; single assembly line added.
- [ ] Determinism test present.

---

# WP-A — Audio Knowledge Base

## 1. Exact file creation order
1. `references/kb/_schema/kb_entry.md` — the A.0 skeleton template (authoring reference; no rules).
2. `references/kb/provenance.md` — root authority; `PROV-*` IDs. **Must precede all others** (they reference it).
3. `references/kb/_index.md` — rule-ID registry, seeded with the `PROV-*` IDs.
4. `references/kb/soundwire.md`, `audioreach.md`, `audio_clocks.md`, `adsp.md`, `lpass.md` — in that value-priority order (SoundWire + AudioReach carry the flagship distinction/pattern; clocks/adsp/lpass follow). Each registers its IDs into `_index.md` as it lands.

## 2. `provenance.md` first-pass content plan (rules only — no values)
- **Scope:** provenance/trust rules for all per-silicon audio facts.
- **PROV-001 (anti-copy):** never substitute a nearest/sibling target's value for a missing per-silicon value; absence = `MISSING`.
- **PROV-002 (authority order):** per-silicon value precedence = target's own catalog/enumeration > target's own boot/runtime evidence > target's own kernel DT > `MISSING`. Prose/family docs are never a value source (topology/family only).
- **PROV-003 (surface routing):** value/instance/register/rate → enumeration/catalog; topology/family/"which-parts-pair" → prose. Never cross them.
- **PROV-D1 (distinction):** every emitted fact is exactly one of {silicon fact, board fact, inference}.
- **Provenance table:** generic fact-class → authoritative-source-order (register-base, IRQ, clock-rate, instance-count, SID, power-domain, routing). No addresses, no targets.
- **Change log:** empty, ready for dated learn-loop appends with `WARN:` conflict markers.

## 3. `_index.md` strategy
- A single registry table: `| Rule ID | File | One-line summary | Status(active/deprecated) | Added(date) | Confirmations(N) |`.
- Append-mostly; owner-gated. IDs immutable once published; supersession via a `deprecated` status + pointer, **never** renumber/reuse.
- Consistency check (CI): every ID cited anywhere (KB body, ledger `rule_ids`, target evidence) exists here; no duplicate IDs; every KB-file rule has an entry.

## 4. Rule-ID allocation plan
- Convention: `<PREFIX>-<NNN>` (rules/patterns), `<PREFIX>-D<N>` (distinctions). Prefixes: `PROV, SWR, AR, CLK, ADSP, LPASS`.
- Allocate sequentially per file at authoring; reserve no gaps (immutability handles evolution). Flagships to allocate first: `SWR-D1` (count-vs-wiring), `AR-001` (flag-don't-fabricate logical port), `CLK-001` (anti-interpolation), `PROV-001/002/003/D1`.

## 5. Value-lint implementation plan
- **`orchestrator/kb_lint.py`** (or `tools/kb_lint.py`) — a standalone checker, no orchestrator import:
  - Scan `references/kb/**/*.md`. Flag forbidden value shapes: hex literals `0x[0-9A-Fa-f]{3,}`; standalone register/size integers in a rule line; clock rates `\d+\s?(Hz|kHz|MHz|GHz)`; vendor part-number patterns; SoC-specific compatible strings `qcom,[a-z0-9]+-...` bound to one SoC; document IDs `[0-9a-f]{24}` / `LD\d+`.
  - **Allowlist:** only within an explicit `## Anonymized illustrations` block AND only when no target name is present; everything else is a hard failure with `file:line`.
  - Also flag any target codename/part token from a small denylist seed (extensible) — enforces "no target names."
  - Exit non-zero on any hit; print offending lines.
- **`tests/test_kb_value_lint.py`** — asserts `kb_lint` passes on the committed KB and fails on crafted bad fixtures (address, rate, part number, target name).

## 6. CI integration points
- Add `kb_lint` + `_index.md` consistency + skeleton-conformance to the existing test entrypoint (same runner as `tests/test_*`). These run on every change to `references/kb/**`.
- Gate: KB changes cannot merge with a lint/consistency failure. (Mechanically: a new test module the existing suite already discovers — no CI infra change needed if tests are run as a suite.)

## 7. Ownership workflow
- `provenance.md`: single named owner; highest scrutiny; slowest change; human sign-off mandatory.
- Domain files: domain-reviewer owned.
- `_index.md`: owner-gated, append-mostly.
- Learn-loop: may **propose** (a diff + candidate ID) but **never merge**; human adjudicates, especially on `WARN:` conflicts.

## 8. Review workflow
- Every KB PR: value-lint green, `_index.md` updated + consistent, skeleton sections present, litmus test stated in the PR ("useful for an unknown future target because…"), no target name, `provenance.md` referenced (by ID) not restated.
- Promotion of an observation to a rule requires ≥2 independent confirmed targets cited (anonymized) in the change log.

## 9. Acceptance checklist (WP-A)
- [ ] Creation order honored; `provenance.md` before dependents; `_schema/kb_entry.md` present.
- [ ] 6 KB files exist from the skeleton; each required section present.
- [ ] Every rule has a unique immutable ID registered in `_index.md`.
- [ ] `kb_lint` green: zero values, zero target names.
- [ ] Flagship IDs present: `PROV-001/002/003/D1`, `SWR-D1`, `AR-001`, `CLK-001`.
- [ ] Other files reference `provenance.md` rules by ID (not restated).
- [ ] `_index.md` consistency + skeleton-conformance tests green.
- [ ] Nothing at runtime hard-depends on the KB (ledger column degrades gracefully).

## 10. Review checklist (WP-A)
- [ ] Litmus test passes for every entry (no target-only content).
- [ ] No value shapes (addresses/rates/counts/part numbers/doc IDs) anywhere outside allowlisted anonymized illustrations.
- [ ] No target codename/part number anywhere.
- [ ] IDs immutable, no reuse, deprecation-by-status only.
- [ ] `provenance.md` is authoritative and not duplicated.
- [ ] Change-log ready for dated `WARN:`-flagged learn-loop appends.

---

# Execution readiness

**1. Is WP-B implementation-ready?** **Yes.** Integration point (`_render_onboarding_report` @795, additive chain @870–873), data source (`gc["audio_topology"]` + `analysis` + `gc["needs_review"]`), renderer contract (`_render_*_section -> list[str]`), and test harness (`test_target_onboarding.py`) are all identified. The only new artifact is a pure module + one call line + tests. No schema/validator change.

**2. Is WP-A implementation-ready?** **Yes.** Layout, creation order, ID convention, lint design (concrete regex set + allowlist), CI hook (existing suite), and ownership/review workflows are fully specified. It is authoring + a lint script; no orchestrator coupling except the graceful-degrading ledger column.

**3. Remaining unknowns:**
- WP-B: whether to ship a **full-byte golden** vs the **header-set diff** check first — recommend header-set diff first (robust), full golden optional later. Minor, non-blocking.
- WP-B: exact `FIELD_DOMAIN_MAP` entries for domains with no current schema field (`clocks`, `sid_iommu`, `audioreach_ports`, `dsp_subsystem`, `lpass_macros`) — these map from `audio_stack` booleans / `missing_evidence` / absence, rendering `MISSING`/`NOT_APPLICABLE`. Resolvable during coding from the schema; no design gap.
- WP-A: the target-name denylist seed contents — trivially editable; start minimal.

**4. Any blocker preventing implementation?** **None.** Both WPs are additive, IPCAT-independent, target-agnostic, and rollback-trivial. No architecture question remains. (Standing process constraints still apply: additive/diagnostic only, no gating until after Benchmark A/B, KB frozen during benchmark windows, no staging/commit/push without review.)

**5. What should be implemented first?** **WP-B and WP-A in parallel.** Within them: WP-B `ledger.py`+unit tests first (immediate, isolated value); WP-A `provenance.md`+`_index.md`+`kb_lint` first (unblocks WP-B's `KB rule` column and WP-C's registry). They touch disjoint files (`orchestrator/` vs `references/kb/`) — zero merge contention.

**6. What should NOT be implemented yet?**
- WP-C (cardinality) — after A's IDs + B's report region settle.
- The `catalog_count` adapter / any IPCAT access — gated on Track D positive result.
- Any **gating** behavior for ledger or cardinality — diagnostic-only until after the Benchmark A/B baseline.
- Learn-loop **automation** — hooks documented now; automated merge later, after manual rules + ≥1 confirmed cycle.
- SID/IOMMU domain **logic** — row exists, logic deferred.

---

**Evidence sources:** approved baselines `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md`, `docs/IMPLEMENTATION_EXECUTION_PLAN.md`; live code read this session — `orchestrator/main.py` (`_render_onboarding_report` @795, section renderers @661–792, chain @870–873, write @581), `orchestrator/reasoning/schemas.py` (`ANALYSIS_SCHEMA` v1.2.0 @109–175), `orchestrator/runners/target_onboarding_runner.py` (`_build_audio_topology` @487, `_ipcat_evidence_summary` @529), `skills/target_onboarding/validator.py` (@25/@123), `tests/test_target_onboarding.py` (@86/@100). Nord/Eliza referenced only as anonymized proof-of-value.
