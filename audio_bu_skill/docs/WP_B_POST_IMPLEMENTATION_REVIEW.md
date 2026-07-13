# WP-B Post-Implementation Review — Confidence Ledger & Audio KB

**Status:** Usability / reviewer-value assessment only. Not an architecture review, not a code review. No code modified, nothing implemented, nothing staged/committed/pushed. Architecture remains frozen; WP-C, Track D, IPCAT access, `catalog_count`, and learn-loop automation are untouched and out of scope.

**Method:** Read the three approved design docs, the implemented `orchestrator/reasoning/ledger.py`, all seven KB files + `_index.md`, and — critically — **rendered the ledger over the two real stored onboarding outputs** (`targets/nord-iq10/case.generated.py`, `targets/eliza/case.generated.py`). The stored `onboarding_report.md` files predate WP-B, so the ledger was rendered fresh over their actual `audio_topology` data. Findings below cite what the real render produced, not hypotheticals.

---

## 1. Executive summary

The Confidence Ledger is **structurally sound and additive as designed** — 9 fixed domains, deterministic, diagnostic-only, correctly placed above `## Promotion`, and it degrades gracefully. As a *concept* it delivers on its promise: a single trust-summary table is genuinely easier to scan than the prose sections below it. The KB is clean, target-agnostic, well-cross-referenced, and `provenance.md` works as a real root authority.

**However, rendering the ledger over the two real targets exposed two defects that undercut its core purpose — trust visibility — and one narrower mapping gap:**

1. **CORROBORATED trust-inversion (severe).** For Nord, the ledger renders `dsp_subsystem`, `lpass_macros`, and `audioreach_ports` as **CORROBORATED**, even though the report's own `missing_evidence` says that entire scaffolding *does not exist at the designated kernel HEAD* and lives only in unapplied patches — and the governing citation literally begins with `CAVEAT: none of this exists…`. The ledger is telling the reviewer "these three domains are corroborated / need no action" for the exact domains that are most unresolved. This is the single most important finding.

2. **Evidence-source column is unreadable for prose citations (severe usability).** `_abbrev_citations` assumes citations are file paths and takes the basename after the last `/`. Real citations are long prose sentences, so the column renders fragments like `` `ADSP power-domain path specifically` `` and `` `TX_0 as an explicit placeholder port)` `` — noise that actively misleads rather than abbreviates.

3. **`dsp_subsystem` mapping miss (moderate).** For Eliza, `dsp_subsystem` renders **MISSING** despite a clearly present ADSP (remoteproc_adsp in the DTS), because the analysis used a different `audio_stack` key shape (`adsp` was `None`, not `True`). The row that should read "present, single-source" reads "MISSING."

None of these are architecture faults — the design is right. They are **derivation/rendering refinements** in `ledger.py` that materially change what a reviewer trusts. Because WP-C will emit into the same report region and lean on the same trust semantics (`CORROBORATED` = safe to skip), shipping WP-C on top of a ledger that mislabels non-existent domains as CORROBORATED would compound reviewer confusion.

**Final recommendation: Refine WP-B first (a small, contained pass on three functions), then start WP-C.** Justification in §7/§9.

---

## 2. What worked

- **The table-first trust summary is a real workflow win.** Both real renders put the whole trust picture in ~9 lines above `## Promotion`. Compared to reading four prose diagnostic sections + the NEEDS_REVIEW list, the ledger is the fastest "where do I look first" artifact in the report.
- **Fixed 9-domain enum as a gauge.** Every target shows every row; `clocks`, `dt_topology`, `sid_iommu` render `MISSING` consistently on both targets. A reviewer learns the shape once and reads it the same way every time. This is the strongest design decision.
- **Determinism & additivity are real.** Header-set diff proves section-only addition; the render is byte-stable. Rollback is trivial and verified.
- **`NOT_APPLICABLE` fired correctly.** Nord's SoundWire (`present: False`) rendered `NOT_APPLICABLE`, cleanly distinct from `MISSING` — exactly the B.2 distinction, and it worked on real data.
- **`codecs = high / CORROBORATED` is correct on both targets** — two independent citations (datasheet/patch + upstream driver). This row is trustworthy and useful as-is.
- **`power_model` NEEDS_REVIEW policy held.** Both targets show `power_model = NEEDS_REVIEW` regardless of band, honoring "never auto-finalized." Eliza rendered `high / NEEDS_REVIEW` (high confidence, still gated) — correct, if initially surprising (see §4).
- **KB is genuinely clean and target-agnostic.** `kb_lint` passes; no target names, no values. `provenance.md` is referenced by ID from every domain file rather than restated.

---

## 3. What did not work

### 3.1 CORROBORATED is awarded on citation *count*, ignoring citation *content* and `missing_evidence` (severe)

`_status_of` (ledger.py:182) resolves `CORROBORATED` when the governing field has ≥2 deduped citations (ledger.py:218). For `audio_stack` boolean domains, all contributing citations come from the single shared `audio_stack.citations` list. On Nord that list has 4 entries and its **first entry is**:

> `CAVEAT: none of this exists at the task's designated kernel HEAD … zero matches for adsp/audio/gpr/q6apm/q6prm/remoteproc…`

Yet the ledger renders:

```
| dsp_subsystem    | — | CORROBORATED | …caveat citations… | PROV-001, ADSP-001 |
| lpass_macros     | — | CORROBORATED | …                   | LPASS-001          |
| audioreach_ports | — | CORROBORATED | …                   | AR-001             |
```

Two compounding problems:
- **`missing_evidence` is silently overridden.** Nord's `missing_evidence` explicitly flags the ADSP PAS base, the power-domain path, and the I2S8 logical-port macro as unresolved. The status logic only honors a missing-evidence hit when there is *no positive evidence* (ledger.py: `domain_missing and not positive`); a `present: True` boolean counts as positive, so the missing-evidence signal is discarded.
- **"≥2 citations on a shared list" ≠ "≥2 independent sources agree."** Two lines describing the same unapplied patch are not corroboration. The spec's own header says "CORROBORATED = agreement, not correctness," but here it isn't even agreement — it's citation *quantity* on a boolean with no confidence.

**Reviewer impact:** the ledger points the reviewer *away* from the three domains that most need attention. This inverts the tool's purpose.

### 3.2 Evidence-source column is garbled for prose citations (severe usability)

`_abbrev_citations` (ledger.py:267) does `s.split("/")[-1]`. Real citations are prose. Actual Nord output:

```
| power_model | low | NEEDS_REVIEW | `…flag this as wrong for Nord`, `NSP0-3 -- RPMHPD_LCX and RPMHPD_LMX indices are absent, so the drafted power-domains reference cannot probe as written`, `ADSP power-domain path specifically`, `(+2 more)` |
```

The cells are sentence fragments chosen by "text after the last slash." This is worse than useless — it looks like structured evidence but is arbitrary substrings. The one case it handles well (real file paths, as in `codecs`) is the minority of citation shapes in practice.

### 3.3 `dsp_subsystem` maps MISSING when ADSP is present under a different key shape (moderate)

Eliza's ADSP is present (remoteproc_adsp in DTS, q6-stack drivers cited), but `audio_stack.adsp` was `None` rather than `True`, so `_collect_contribs` (which checks `stack.get("adsp") is True`) contributed nothing and the row rendered `MISSING`. Meanwhile `lpass_macros` and `audioreach_ports` — which *did* have `True` — rendered CORROBORATED off the same shared citation list. So on one target the DSP domain is wrongly MISSING and on the other it's wrongly CORROBORATED. The mapping is too brittle to the exact boolean shape QGenie emits.

### 3.4 Confidence band shown on a NOT_APPLICABLE row (minor)

Nord's `soundwire` rendered `medium / NOT_APPLICABLE`. A band on a not-applicable domain is contradictory noise — if it's N/A, the band should be `—`.

---

## 4. Usability findings

- **The disclaimer header is good but long.** Five sentences before the table. New reviewers will read it once and skip it forever; the critical clause ("CORROBORATED = agreement, not correctness") is buried mid-paragraph. Consider making that one clause bold/first.
- **`high / NEEDS_REVIEW` (Eliza power_model) reads as a contradiction to a new reviewer.** It's actually correct (confident detection, but policy forbids auto-finalizing power). The ledger doesn't explain *why* a high-confidence row still needs review. An expert gets it; a newcomer won't.
- **Band vs. status carry overlapping-but-not-identical meaning**, and the reviewer must hold both in mind. `low / NEEDS_REVIEW` and `high / NEEDS_REVIEW` demand different reviewer effort, but the *status* column alone (the "work list") doesn't distinguish them. This is fine once learned.
- **The evidence column (when working) is the most valuable column** — it's what lets a reviewer decide whether to trust a row without scrolling to the prose. That's precisely why §3.2 matters: the highest-value column is the most broken on real data.

---

## 5. Reviewer workflow findings

**Task 1 answers:**

1. **Does the ledger improve reviewer workflow?** Yes in principle and yes for `codecs`/`power_model`/`soundwire`/the MISSING rows — a reviewer immediately sees the work list. **But** the CORROBORATED rows (§3.1) actively misdirect on real data, so today the improvement is partial and, for the DSP/AudioReach/LPASS domains, net-negative on a Nord-shaped target.
2. **Any redundant row?** No row is redundant. `clocks`, `dt_topology`, `sid_iommu` are always-MISSING today (no source), but they earn their place as a gauge (they tell the reviewer "the tool knows this is unknown," not "the tool forgot").
3. **Any domain missing?** No missing domain for the audio scope. The 9 cover the space. (`dt_topology` under-fires because the raw analysis envelope isn't threaded to the renderer — a known, documented deviation, not a missing domain.)
4. **Are confidence bands useful?** Yes where a numeric confidence exists (codecs, power_model, soundwire). **Not useful for the boolean stack domains**, which have no confidence and render `—` while still showing a status — so band and status disagree on where the uncertainty is.
5. **Is the status vocabulary useful?** The vocabulary (5 states) is well-chosen. The *derivation* of `CORROBORATED` is the problem, not the vocabulary.
6. **Does the reviewer immediately know what needs action?** For MISSING/NEEDS_REVIEW/NOT_APPLICABLE: yes. For CORROBORATED: **misleadingly yes** — they'll skip rows they shouldn't (§3.1).
7. **Too verbose?** The table is not; the disclaimer is borderline; the evidence column is over-long and garbled (§3.2).
8. **What confuses a new reviewer?** `high / NEEDS_REVIEW`; the garbled evidence fragments; why three "CORROBORATED" domains are also in the NEEDS_REVIEW prose below.
9. **What confuses an expert reviewer?** The CORROBORATED-vs-`missing_evidence` contradiction — an expert will *immediately* distrust the whole ledger the first time they see a caveated, unapplied-patch domain labeled CORROBORATED. This is a credibility risk for the tool.
10. **Which rows provide the most value?** `codecs` (trustworthy CORROBORATED), `power_model` (correctly gated on both targets), and the honest `MISSING` rows (`clocks`, `sid_iommu`, `dt_topology`). These four are the ledger working exactly as intended.

---

## 6. KB findings

**Task 2 answers:**

1. **Does `provenance.md` act as root authority?** Yes. Every domain file defers to `PROV-00x` by ID rather than restating, and the ledger's `DOMAIN_RULE_MAP` cites `PROV-*` for cross-cutting domains. It is functioning as the single source of provenance truth.
2. **Duplicated rules?** None found. `ADSP-001`, `LPASS-001`, `SWR-001` each say "base is a silicon fact, resolve per PROV-002" — this is *deliberate specialization*, not duplication (each names the specific block and defers to PROV-002). Acceptable and correct.
3. **Rule overlap?** Mild, intentional: the "base is silicon" family (ADSP-001/LPASS-001/SWR-001) all specialize PROV-001/002. This is the KB's cross-reference design, not accidental overlap.
4. **Unclear wording?** `PROV-002`'s "prose/family docs are never a source for a value (only topology/family)" is dense; otherwise wording is clear and imperative.
5. **Missing anti-patterns?** One worth adding later: a **"citation-count ≠ corroboration" anti-pattern** — precisely the failure §3.1 exhibits. It belongs in `provenance.md` and would directly govern the ledger's status derivation. (Noting for a future KB pass, not implementing now.)
6. **Missing provenance guidance?** The provenance table lacks a row for **logical-port / interface-mapping authority** (DSP/firmware owner), even though `AR-002` states it. Folding that into the `provenance.md` table would let the ledger cite it uniformly. Minor.
7. **Highest long-term value KB entries?** `AR-001` (flag-don't-fabricate logical port), `SWR-D1` (count vs routing), `CLK-001` (anti-interpolation), and `PROV-001` (anti-copy). These encode the non-obvious, target-independent traps that recur on every bring-up. They are the reason the KB exists.
8. **Lowest-value entries?** `LPASS-002` and `CLK-D1` are correct but thin — they restate a PROV distinction with little added specificity. Not harmful; just lower reuse than the flagships.

---

## 7. Readiness for WP-C

**Task 3 answers:**

1. **Enough infrastructure to start Cardinality Authority?** Structurally, yes — the report region, the NEEDS_REVIEW channel, the KB rule-ID registry, and the `soundwire`/`audio_stack` data WP-C needs are all present. WP-C is not *blocked*.
2. **Which KB rules WP-C will depend on?** `SWR-D1` (master count vs routing — the core cardinality distinction), `SWR-P1` (DT is not a count source), `SWR-001`, and `PROV-001` (anti-copy for counts). These exist and are registered. Eliza's data (`master_count cannot be confirmed from kernel DT`, possible count of 2) is the exact case WP-C's `soundwire_master` class targets — the KB rule to cite already exists.
3. **Missing abstractions?** One that both WP-B and WP-C need: **a shared "does this domain have real, non-caveated, multi-source support?" predicate.** WP-B's §3.1 defect and WP-C's verdict logic (`agree`/`disagree`/`not_cross_checkable`) both hinge on the same "is this actually corroborated" judgment. If WP-B ships with the naive count-based rule, WP-C will either duplicate a better one or inherit the bad one.
4. **Gaps discovered while reviewing the ledger?** The three in §3 — CORROBORATED derivation, prose-citation rendering, and the `dsp_subsystem` mapping brittleness. All are in `ledger.py`, all pre-date any WP-C work.
5. **Reason to postpone WP-C further?** Only a soft one: WP-C emits into the same report region and reuses the trust vocabulary. Refining WP-B's status derivation first (a small pass) gives WP-C a correct `CORROBORATED` semantic to build on and avoids re-litigating "what counts as corroborated" inside cardinality logic.

---

## 8. Recommended adjustments

All are **small, contained refinements to `ledger.py`** (no schema, validator, or report-structure change; still additive/diagnostic-only). Listed by priority; **not implemented here** — this is a review.

1. **Fix CORROBORATED derivation (§3.1).** Require corroboration to mean genuinely independent sources, and let a `missing_evidence` hit downgrade a `present:True` boolean domain to `NEEDS_REVIEW` rather than being overridden. Simplest correct behavior: a boolean-only domain (no numeric confidence) can be at most `NEEDS_REVIEW`, never `CORROBORATED`; and a domain named in `missing_evidence` is never `CORROBORATED` regardless of positive booleans. This alone flips Nord's three misleading rows to the honest `NEEDS_REVIEW`.
2. **Fix the evidence column (§3.2).** Detect path-shaped vs prose citations; for prose, truncate to first N chars with an ellipsis rather than splitting on `/`. Keep basename abbreviation only for actual paths.
3. **Broaden the `dsp_subsystem` mapping (§3.3).** Treat truthy (not strictly `is True`) or contribute from any DSP-indicating signal, so a present ADSP under a slightly different key shape isn't rendered MISSING.
4. **Suppress the band on `NOT_APPLICABLE` rows (§3.4).** Force `—`.
5. **Tighten the disclaimer (§4).** Lead with the "CORROBORATED = agreement, not correctness" clause; move the rest to one trailing sentence.
6. **(KB, future pass — not now)** add a "citation-count ≠ corroboration" anti-pattern to `provenance.md` and a logical-port authority row to the provenance table (§6.5/§6.6).

---

## 9. Final recommendation

### Refine WP-B first (items §8.1–§8.4), then start WP-C.

**Justification:**

- The ledger's **entire value proposition is trust visibility**, and on a real Nord-shaped target it currently labels the three most-unresolved domains `CORROBORATED` while its own report prose says they don't exist. An expert reviewer who sees that once will stop trusting the ledger — the credibility cost is high and the fix is small.
- The broken evidence column means the ledger's highest-value column is noise on the majority of real (prose) citations.
- These are **not architecture changes** — the design in FRAMEWORK_ARTIFACT_SPECIFICATION.md is correct (min-roll-up, 9 domains, status vocabulary). They are localized derivation/rendering bugs in three `ledger.py` functions, fixable in a single focused pass with the existing unit-test harness (`tests/test_confidence_ledger.py`) extended by fixtures modeled on the real Nord/Eliza data.
- **WP-C should follow, not precede, this refinement**, because WP-C emits into the same report region and reuses the `CORROBORATED`-means-safe semantic. Building cardinality verdicts atop a mislabeling ledger would propagate the confusion into a second surface and force WP-C to re-derive "what counts as corroborated." The refinement is the shared abstraction WP-C wants (§7.3).
- This is a **refine, not a rebuild**: the concept is validated, the KB is ready, WP-C's dependencies (`SWR-D1` et al.) exist. Estimated refinement scope is far smaller than WP-C itself, and it is strictly on the critical path to WP-C being trustworthy.

**One-line:** the Confidence Ledger and KB are the right design and are 80% of the way to real reviewer value — but a real-data render shows the status-derivation and evidence-rendering must be corrected before the ledger can be trusted, and before WP-C builds on its trust vocabulary.

---

**Evidence sources:** `docs/FRAMEWORK_ARTIFACT_SPECIFICATION.md` (Track B §B.1–B.8, Track A §A.0–A.7); `orchestrator/reasoning/ledger.py` (`_status_of` @182, `_abbrev_citations` @267, `_collect_contribs`, `build_ledger`); `references/kb/*` + `_index.md` (27 registered IDs); live ledger render over `targets/nord-iq10/case.generated.py` and `targets/eliza/case.generated.py` (real `audio_topology` data). Nord and Eliza used strictly as validation examples; no target-specific design introduced.
