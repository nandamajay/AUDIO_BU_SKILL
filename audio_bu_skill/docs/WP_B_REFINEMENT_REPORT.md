# WP-B Refinement Report — Confidence Ledger derivation/rendering fixes

**Scope:** A localized refinement pass on `orchestrator/reasoning/ledger.py` implementing the four defects identified in `docs/WP_B_POST_IMPLEMENTATION_REVIEW.md` §3.1–§3.4 (approved). **Architecture unchanged.** No schema, validator, report-structure, promotion, onboarding-decision, or gating change. The ledger remains additive and diagnostic-only — nothing in the decision/promotion path reads it.

**Explicitly NOT done (out of scope, per standing constraints):** WP-C / Cardinality Authority, Track D, IPCAT access, `catalog_count`, learn-loop automation, gating behavior, promotion logic, onboarding decisions. Nothing staged, committed, or pushed.

---

## 1. Files modified

| File | Change | Nature |
|------|--------|--------|
| `orchestrator/reasoning/ledger.py` | Fixes 1–4 (status derivation, evidence rendering, DSP mapping, N/A band) | Logic refinement |
| `tests/test_confidence_ledger.py` | +6 regression tests modeled on real Nord/Eliza data | Test |

`orchestrator/main.py` was **not** touched — its `_render_confidence_ledger` only joins the rows `build_ledger` returns, so all four fixes are contained in the pure ledger module. No KB file, schema, or runner changed.

Both files are still **untracked** (created during the WP-B implementation pass and never committed, consistent with the "nothing staged/committed" constraint).

---

## 2. Diff statistics

Relative to the pre-refinement in-session state of each file:

| File | Before (LOC) | After (LOC) | Δ |
|------|-------------:|------------:|---:|
| `orchestrator/reasoning/ledger.py` | 397 | 501 | +104 |
| `tests/test_confidence_ledger.py` | 178 | 320 | +142 |

The +104 in `ledger.py` is mostly comments + the new helper functions (`_governing_citations`, `_has_caveat`, `_non_caveat`, `_basename`, `_abbrev_one`) and the narrow caveat/path regexes; the behavioral core is ~15 lines across four functions. New standard-library import: `re`. No new third-party dependency.

---

## 3. Test results

| Suite | Result |
|-------|--------|
| `tests.test_confidence_ledger` (unit + ledger) | **17/17 pass** (11 original + 6 new regressions) |
| `tests.test_kb_value_lint` | 10/10 pass |
| `tests.test_target_onboarding` (header-set-diff additive proof) | pass |
| **Full suite (module-by-module)** | **21/21 modules pass, 0 fail** |
| Determinism | 5 identical `build_ledger` runs — byte-stable |

New regression tests (all passing), each pinned to a review finding:
- `test_nord_boolean_stack_not_corroborated` — §3.1 (Nord stack → NEEDS_REVIEW; real codec stays CORROBORATED)
- `test_boolean_only_domain_never_corroborated_on_count` — §3.1 (guard a)
- `test_caveated_citations_do_not_corroborate` — §3.1 (guard c)
- `test_eliza_dsp_inferred_from_q6_stack` — §3.3
- `test_not_applicable_band_is_dash` — §3.4
- `test_evidence_column_readable` — §3.2 (path / mixed / prose shapes)

---

## 4. Before / after — Nord (`targets/nord-iq10/case.generated.py`)

Rendered live over the target's real `audio_topology`.

| Domain | Band before → after | Status before → after | Evidence column |
|--------|---------------------|-----------------------|-----------------|
| power_model | low → low | NEEDS_REVIEW → NEEDS_REVIEW | garbled prose → readable (`…patch`, `rpmhpd.c:322-338…`) |
| **dsp_subsystem** | — → — | **CORROBORATED → NEEDS_REVIEW** ✅ | fragments → `CAVEAT: none of this exists…`, patch basenames |
| **lpass_macros** | — → — | **CORROBORATED → NEEDS_REVIEW** ✅ | same |
| **audioreach_ports** | — → — | **CORROBORATED → NEEDS_REVIEW** ✅ | same |
| **soundwire** | **medium → —** ✅ | NOT_APPLICABLE → NOT_APPLICABLE | readable basenames |
| codecs | high → high | **CORROBORATED → CORROBORATED** (preserved) ✅ | `…patch`, `pcm1681.c`, `adau1977.c` |
| clocks / dt_topology / sid_iommu | — → — | MISSING → MISSING (unchanged gauge) | — |

**Result:** the three trust-inverted rows — which the report's own `missing_evidence` and the leading `CAVEAT: none of this exists at the designated kernel HEAD…` citation flag as non-existent — no longer read CORROBORATED. The one genuinely corroborated row (codecs: unapplied DT patch **+** present upstream driver) is preserved. The NOT_APPLICABLE SoundWire row no longer carries a contradictory band.

---

## 5. Before / after — Eliza (`targets/eliza/case.generated.py`)

| Domain | Band before → after | Status before → after | Note |
|--------|---------------------|-----------------------|------|
| **dsp_subsystem** | — → — | **MISSING → NEEDS_REVIEW** ✅ | ADSP inferred from `gpr`/`q6apm`/`q6prm` stack (no explicit `adsp` key) |
| lpass_macros | — → — | CORROBORATED → NEEDS_REVIEW | boolean-only domain, now honestly single-trust |
| audioreach_ports | — → — | CORROBORATED → NEEDS_REVIEW | same |
| power_model | high → high | NEEDS_REVIEW → NEEDS_REVIEW | policy gate held |
| soundwire | medium → medium | CORROBORATED → CORROBORATED | numeric conf 0.55, ≥2 non-caveated cites — **correctly unchanged** (count ambiguity is WP-C's concern, not this pass) |
| codecs | medium → medium | NEEDS_REVIEW → NEEDS_REVIEW | unchanged |

**Result:** the DSP domain that was wrongly MISSING is now classified. The boolean stack domains drop from misleading CORROBORATED to honest NEEDS_REVIEW. Eliza `soundwire` (a real numeric-confidence, multi-source domain) is deliberately left CORROBORATED — its master-count question is WP-C territory and was explicitly not touched.

---

## 6. Verification of each fix

### Fix 1 — CORROBORATED trust-inversion (§3.1)
`_status_of` now enforces three guards before awarding CORROBORATED:
- **(a) boolean-only domains** (no contributor carries numeric confidence) can be at most `NEEDS_REVIEW` — citation count on a single shared list is not corroboration;
- **(b) missing_evidence** naming a boolean-only domain downgrades it to `NEEDS_REVIEW` (no longer silently overridden by a `present:True` boolean);
- **(c) caveated citations** (narrow marker set: "caveat", "none of this exists", "does not exist", "no such", "placeholder", "fabricated", "wrong for") are excluded from the corroboration count.

The "≥2 sources" test now counts only **non-caveated** citations **and** requires numeric confidence. Verified: Nord's three boolean domains flip to NEEDS_REVIEW; Nord `codecs` (numeric, two non-caveated sources) stays CORROBORATED. **Requirements met:** missing_evidence influences status; caveated evidence cannot become CORROBORATED; boolean-only domains are not promoted on count.

> **Interpretation flagged for the reviewer:** §8.1's "never CORROBORATED regardless of positive booleans" is scoped to **boolean-only** domains (guard b applies only when `not has_numeric`). Nord's `codecs` domain *is* matched by a `missing_evidence` note (the "no amplifier/discrete mic/codec I2C nodes" line hits the codec keyword), so a blanket missing_evidence veto would have wrongly downgraded the exact row the review calls correct and valuable (§10.4 of the review). Scoping the veto to boolean-only domains preserves the genuinely-corroborated codec while still flipping the three offending stack rows. This is the smallest change that satisfies all three stated requirements without regressing a known-good row.

### Fix 2 — Evidence column rendering (§3.2)
`_abbrev_citations`/`_abbrev_one` no longer do `split("/")[-1]` on every citation. A path-token regex collapses only genuine path tokens (`a/b/c.c:603` → `c.c:603`) wherever they appear — including embedded mid-sentence absolute paths — and everything else is clipped to a 60-char word-boundary lead with an ellipsis. Verified on all three real shapes: bare path, mixed path-in-prose, and pure prose. No more arbitrary sentence fragments.

### Fix 3 — DSP domain mapping (§3.3)
`_collect_contribs` now accepts any **truthy** `audio_stack` flag (not strictly `is True`) and infers a present `dsp_subsystem` from any DSP-indicating signal (`adsp` **or** the Q6/APR stack `gpr`/`apm`/`q6apm`/`q6prm` — which run on the ADSP). Eliza's ADSP (no explicit `adsp` key) is now classified instead of rendered MISSING. Nord (explicit `adsp: True`) is unaffected.

### Fix 4 — NOT_APPLICABLE band (§3.4)
`_rollup` forces `band = "—"` whenever `status == NOT_APPLICABLE`. Verified: Nord `soundwire` renders `— / NOT_APPLICABLE` instead of `medium / NOT_APPLICABLE`.

---

## 7. Acceptance checklist

- [x] `missing_evidence` influences status (boolean-only domains)
- [x] Caveated evidence cannot become CORROBORATED
- [x] Boolean-only domains not promoted to CORROBORATED on citation count
- [x] No false CORROBORATED domains on Nord (3 rows flipped to NEEDS_REVIEW)
- [x] Genuinely-corroborated row preserved (Nord codecs stays CORROBORATED/high)
- [x] Path citations abbreviated correctly (basename)
- [x] Prose citations rendered cleanly (word-boundary clip + ellipsis)
- [x] Mixed path+prose citations readable (path collapsed, note clipped)
- [x] DSP domain robust to real emitted shapes (Eliza classified, not MISSING)
- [x] NOT_APPLICABLE renders band `—`
- [x] Unit tests pass (17/17 ledger)
- [x] Full suite pass (21/21 modules)
- [x] Nord ledger render verified
- [x] Eliza ledger render verified
- [x] Deterministic / byte-stable (5 identical runs)
- [x] Additive/diagnostic-only preserved (no decision/promotion/gating change)
- [x] Architecture unchanged; no schema/validator/report-structure change
- [x] Nothing staged / committed / pushed

---

## 8. Remaining concerns

1. **Caveat detection is lexical, not semantic.** The marker set is deliberately narrow ("caveat", "none of this exists", "placeholder", etc.) to avoid downgrading real evidence (e.g. "unapplied at HEAD" is intentionally *not* a caveat). A caveat phrased differently would be missed; a benign sentence containing "placeholder" would be a false positive. This is acceptable for a diagnostic aid — worst case is an over- or under-conservative NEEDS_REVIEW, never a decision change — but it is not a robust NLP classifier. The KB anti-pattern noted in review §6.5 ("citation-count ≠ corroboration") would be the durable home for this rule; not added here (KB pass is out of scope).
2. **`dsp_subsystem` inference is heuristic.** Inferring DSP presence from the Q6/APR stack is correct in practice (that stack runs on the ADSP) but is an inference, not a direct ADSP fact. It yields NEEDS_REVIEW, not CORROBORATED, so it is appropriately conservative.
3. **Disclaimer wording (review §8.5) not changed.** The current instruction set covered Fixes 1–4 only; the disclaimer-tightening (§8.5) was not requested, so I left it — "smallest change necessary." Worth a one-line follow-up if desired.
4. **`dt_topology`/`clocks`/`sid_iommu` still always-MISSING.** Unchanged and out of scope — they remain honest gauge rows (no source threaded to the renderer). A known, documented deviation, not a regression.
5. **Eliza `soundwire` remains CORROBORATED.** Correct for this pass — the master-count ambiguity is WP-C's cardinality problem. Flagged so it is not mistaken for a missed §3.1 case: it is numeric-confidence + multi-source, so the §3.1 guards (which target boolean-only domains) correctly do not touch it.

---

## 9. Recommendation

### ✅ Proceed to WP-C.

**Justification:**
- All four review-identified defects are fixed, verified on both real targets, and covered by regression tests pinned to the exact findings. The trust-inversion that would have propagated into WP-C's shared report region and `CORROBORATED`-means-safe semantic is resolved.
- The refinement delivered the shared abstraction WP-C wanted (review §7.3): a real "is this genuinely corroborated?" predicate (numeric confidence + non-caveated multi-source + missing_evidence awareness) now lives in `_status_of`, so WP-C's cardinality verdicts can build on a correct `CORROBORATED` rather than re-deriving one.
- Everything stayed inside the frozen architecture: pure module, additive/diagnostic-only, deterministic, full suite green, nothing committed. There is no residual WP-B risk on the critical path.
- The remaining concerns (§8) are all soft, out-of-scope, or appropriately conservative — none blocks WP-C.

**One-line:** WP-B is now trustworthy on real data; the ledger no longer mislabels non-existent domains, its evidence column is readable, and WP-C can build on a correct trust vocabulary — proceed.

---

**Evidence:** live `build_ledger` render over `targets/nord-iq10/case.generated.py` and `targets/eliza/case.generated.py` (real `audio_topology`); `tests/test_confidence_ledger.py` (17/17); full suite 21/21 modules; 5-run determinism check. Nord/Eliza used strictly as validation examples — no target-specific logic introduced.
