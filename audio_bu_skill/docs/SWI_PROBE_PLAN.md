# SWI Probe — Plan & Pre-flight (Read-only Investigation)

**Milestone:** SWI Probe (pre-Track-D) — *planning + pre-flight only.*
**Status:** pre-flight **FAILED** at the access gate → **No-Go** for implementation this session.
**Scope contract honored:** read-only investigation · no Track D · no DTS/patch generation · no promotion/gating change · no schema change · no confidential data committed · no target artifacts committed · no source files modified. Nothing was committed or pushed.

> **Headline:** The SWI/catalog source *exists* (two production systems reach it), but it is **not reachable, its client is not installed, and no credentials are configured on this host.** The mandatory pre-flight gate therefore fails at items 2/3/4/5. Per the standing rule, this document STOPS at a blocker report + missing-dependency list + recommended next action; it deliberately does **not** design `catalog_count` population details beyond the read-only mapping already fixed by WP-C.

---

## 1. Objective

Determine whether we can populate the WP-C `catalog` enumeration lane (`catalog_count`) from the SWI/IPCAT catalog in a **safe, read-only, additive** way — i.e. give the Cardinality Authority a genuine *authority* lane so that today's pre-SWI `not_cross_checkable` verdicts can upgrade to `agree` / `disagree_with_authority`.

This is *only* a feasibility probe. Success here = a proven, credentialed, read-only path to a chip-keyed enumeration for our two targets, plus a Go/No-Go recommendation. It is explicitly **not** the Track-D build.

---

## 2. Available inputs (what we already have)

| Input | State | Source |
|---|---|---|
| WP-C authority path | **Complete & committed** (`28f2f07`, tag `foundation-complete-pre-swi`) | `orchestrator/reasoning/cardinality.py` `_verdict()` already compares every lane against `catalog` when present |
| `element_counts` schema lane | **Complete** — `catalog` declared `["integer","null"], minimum:0`, always emitted `null` pre-SWI | schema 1.3.0 / Fix A (`docs/FIX_A_IMPLEMENTATION_REPORT.md`) |
| Real per-class counts on both targets | **Present** — Nord 6 rows, Eliza 8 rows (dt/evidence/proposal lanes populated) | live onboarding re-runs under 1.3.0 |
| Which classes most need authority | **Identified** (see §5) | `docs/WP_C_PREFLIGHT_GAP_ANALYSIS.md`, `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md` |
| Prior-art access pattern | **Documented** — EVA imports `ipcat_client` directly; camera_dtsi wraps the same library in a dedicated stdio MCP with env-var-first auth | `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md` |
| Target identifiers | Known to the operator; kept out of this doc as `<NORD-SOC>` / `<ELIZA-SOC>` placeholders | confidentiality constraint |

**Key point:** the *consumer* is entirely ready. WP-C already handles the authority lane end-to-end, proven by `test_disagree_with_authority_post_swi` / `test_agree_with_authority_post_swi`. The probe only needs to prove it can *produce* the lane. It cannot, yet — see §4.

---

## 3. What `catalog_count` means, and read-only query strategy (design intent only)

**Meaning.** `catalog_count` is the post-SWI **authoritative** enumeration lane in WP-C: the number of hardware instances of an element class that the chip-keyed SWI catalog enumerates for the target SoC. Per WP-C C.7, once `catalog` is present it becomes *N* and every other lane (`dt` / `evidence` / `proposal`) is compared against it — a match is `agree`, a divergence is `disagree_with_authority` (a warning). This is the camera_dtsi "IPCAT is ground truth for instance count" doctrine, adopted as a diagnostic (never a hard gate).

**Read-only query strategy (would-be, pending access).** Entirely non-mutating, chip-keyed lookups via `ipcat_client`, mirroring EVA/camera_dtsi:
1. `chips.get_chips()` once → resolve each target alias to a `chip_id` (4-tier alias/name match). **This single call is also the go/no-go presence probe** — if a target SoC is absent from the catalog, stop for that target.
2. Per resolved `chip_id`, read-only enumeration only: `swi.get_modules(chip_name)` (and `memmap.get_memory_maps(chip_id, group='HW')` if base-address corroboration is later wanted). **No writes, no side effects.**
3. Count blocks whose names match a per-class pattern (e.g. SoundWire-master blocks, LPASS-macro blocks, DSP-subsystem blocks) → that integer is `catalog_count` for the class.
4. Cache per-target to a job-scoped path; never emit raw catalog rows into a committed artifact.

This strategy is documented for completeness only. **It is not executable this session (§4) and no code implementing it is proposed here.**

---

## 4. Pre-flight gate — mandatory, re-verified live this session

Each gate item was checked with a **read-only** probe. Env-var checks reported presence (SET/unset) only — no values printed, no full environment dumped, no shell-history scan.

| # | Gate requirement | Result | Evidence (this session) |
|---|---|---|---|
| 1 | The required SWI/catalog **source exists** | ✅ **PASS** | Two independent production systems (EVA, camera_dtsi) read chip-keyed SWI enumeration from `ipcat_client`. Existence is not in doubt. |
| 2 | It is **reachable** from this environment | ❌ **FAIL** | The only IPCAT surface wired into this project is qgenie-chat MCP, which exposes a single project (`HPG_DOCUMENTS`) — *documents keyed by IP-block version*, not a chip-keyed enumeration API. No reachable chip/module catalog endpoint. (Confirmed in `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md` §1 via `list_projects("ipcat") → ["HPG_DOCUMENTS"]`.) |
| 3 | The required **client/tooling** is available | ❌ **FAIL** | `python3 -c "import ipcat_client"` → `ModuleNotFoundError: No module named 'ipcat_client'`. `pip3 show` finds none of `ipcatalog-client` / `ipcat-client` / `ipcat_client` / `ipcatalog`. |
| 4 | The required **credentials/config** exist | ❌ **FAIL** | `IPCAT_TOKEN`, `IPCAT_USER`, `IPCAT_PASSWORD`, `IPCAT_URL`, `IPCATALOG_URL` all **unset**; `~/.ipcat_token` **absent**. No credential material configured. |
| 5 | A concrete query can be **executed safely** | ❌ **BLOCKED** | The concrete safe query is identified (`chips.get_chips()` — §3 step 1, read-only), but it cannot run without gates 3 **and** 4. Not executable this session. |

**Gate outcome: FAIL (items 2, 3, 4, 5).** Per the standing instruction — *"If any of the above cannot be demonstrated: STOP. Do not design implementation details."* — this plan stops at the blocker analysis below.

---

## 5. Which element classes need catalog authority first (so a future Go is well-targeted)

Recorded now so that, *if* access is provisioned later, the probe is aimed correctly:

1. **`soundwire_master` — flagship.** The `<ELIZA-SOC>` master count is genuinely unresolved pre-SWI (`evidence=3` vs `proposal=1`, `ambiguous=true` → today correctly held at `not_cross_checkable`). The gap analysis states plainly the catalog is the *only* authority that can settle "1 or 2 masters." This is the single highest-value class for `catalog_count`.
2. **`dsp_subsystem_instance` — Nord.** The `<NORD-SOC>` ADSP subsystem base/enumeration is the canonical `swi.get_modules()` fact; the catalog is purpose-built to replace the nearest-target-copied value with an authoritative one. (Availability caveat below applies most sharply here.)
3. **`lpass_macro_instance`** — macro enumeration is a catalog fact; useful once #1/#2 land.

**Availability caveat (unresolvable without access):** `<NORD-SOC>` is a newer/derivative part; whether it is *populated* in the SWI catalog is itself unknown and can only be settled by the `chips.get_chips()` probe. `<ELIZA-SOC>` is more likely present (named by IPCAT in HPG). So even a future Go must treat "is our SoC in the catalog?" as the first empirical check, per `docs/PHASE0_SWI_SPIKE_RECOMMENDATION.md` §4.

---

## 6. Expected output shape (contract for a future implementation — not built)

When access exists, the probe would produce, **per target, per element class**, exactly one integer plus provenance — nothing more:

```
{ "element_class": "soundwire_master",
  "catalog": <int>,              # authoritative instance count
  "citations": ["<catalog-ref>"] # provenance token, non-confidential
}
```

This slots verbatim into the existing `element_counts` row (the `catalog` lane already exists in schema 1.3.0). **No schema change is required** — this was the deliberate purpose of declaring `catalog` up front in Fix A. Rendering is already handled by WP-C's `_render_cardinality_section`; no rendering change is required either.

---

## 7. How `catalog_count` maps into WP-C (already wired, zero redesign)

- WP-C `_usable_lanes` already includes `catalog` as an applicable source for the relevant classes.
- WP-C `_verdict` already branches on `catalog` presence: all lanes match → `agree`; any lane differs → `disagree_with_authority` (a warning).
- Therefore populating `catalog` is **purely additive data**: prior `not_cross_checkable` rows (Nord's three single-lane rows, Eliza's four) upgrade to `agree` / `disagree_with_authority` automatically, with **no change to `cardinality.py`, no schema bump, no gating/promotion change.**
- Proven inert-but-ready by `tests/test_cardinality.py::test_disagree_with_authority_post_swi` and `::test_agree_with_authority_post_swi`.

This is the strongest argument that the *only* missing piece is the access mechanism (§4), not any framework work.

---

## 8. Blocker analysis (STOP outcome)

The probe is blocked at the **access layer**, not the framework layer. Three independent blockers, all at gates 2–4:

1. **No reachable chip-keyed catalog API.** The wired qgenie-chat IPCAT surface is document search (`HPG_DOCUMENTS`), structurally incapable of returning a per-SoC instance enumeration. The catalog lives behind a *different* mechanism (`ipcat_client`) that is not wired into this project.
2. **Client library absent.** `ipcat_client` is not importable and not installed via any known package name on this host.
3. **No credentials/configuration.** No IPCAT env vars are set and no token cache exists. (Per standing rule, credentials must be **env-var-first and user-provided — never scraped**; they are simply not present.)

Because gate 1 passes (the source demonstrably exists in prior art) but 2–4 fail, this is a **provisioning gap, not an architectural dead end.** The consumer side (WP-C) is complete and waiting.

---

## 9. Missing dependency list (what a Go requires)

| # | Dependency | Nature | Owner / how obtained |
|---|---|---|---|
| D1 | `ipcat_client` library installed on the run host | Python package | User/operator provisions (same library EVA/camera_dtsi use); **do not** pip-install speculatively without approval |
| D2 | IPCAT credentials, **env-var-first** (`IPCAT_USER`/`IPCAT_PASSWORD` or `IPCAT_TOKEN`) | Secret/config | **User-provided only** — never scraped, never harvested from history/env dumps |
| D3 | Network reachability from this host to the IPCAT backend | Ops/network | Operator confirms the run environment can reach the service |
| D4 | Confirmation that `<NORD-SOC>` and `<ELIZA-SOC>` are **populated** in the SWI catalog | Empirical (one `chips.get_chips()` call) | Answerable only *after* D1–D3; this is the first read-only probe |
| D5 | Approval to add a runtime dependency / access mode to the project | Decision | User — this is the Track-D-adjacent decision the assessments flag as "not query-tuning but an access-mechanism change" |

Until **D1–D4** are satisfied, no `catalog_count` implementation can be written or tested.

---

## 10. Risks

- **Availability risk (highest):** even with access, `<NORD-SOC>` may be unpopulated (newer/derivative part). If so, the catalog helps `<ELIZA-SOC>` (soundwire_master) but not Nord's DSP base — changing the cost/benefit. Must be measured by the `chips.get_chips()` probe before any build.
- **Auth/headless risk (medium):** interactive `getpass` fallback exists in the reference tooling; a headless run must use the env-var-first path (proven pattern in both EVA and camera_dtsi) to avoid blocking.
- **Dependency risk (medium):** adopting `ipcat_client` adds a runtime dependency + an access mode; camera_dtsi shows a wrap-in-MCP alternative, but either is a real, sized piece of work (Track D), not a trivial wrapper.
- **View-mismatch risk (low-medium):** an authoritative catalog base/count may differ from a boot-log or DT value for legitimate reasons (mapping view, applied-vs-silicon). WP-C surfaces this as `disagree_with_authority` (a review signal), which is the correct, non-failing behavior — but reviewers must know a warning ≠ a defect.
- **Confidentiality risk (handled, §11):** catalog rows carry SoC-specific identifiers; they must never reach a committed artifact.

---

## 11. Confidentiality safeguards

- This document uses `<NORD-SOC>` / `<ELIZA-SOC>` placeholders; **no** SoC part numbers, no LD-series/schematic references, no firmware paths, no `/local/mnt` paths, no kernel hashes, no IPCAT doc IDs.
- Any future catalog output is **target-artifact/confidential** and stays uncommitted (same class as `targets/*/qgenie_analysis.json`); only non-confidential provenance *tokens* would appear in `citations`.
- Live host checks this session printed **only** env-var presence (SET/unset) and package presence — never any value, never the full environment, never shell history.
- Credentials remain **env-var-first, user-provided, never scraped.**

---

## 12. Go / No-Go recommendation

### **No-Go for implementation this session — STOP at the access gate.**

The framework is fully ready (WP-C authority path committed and tested), but the SWI catalog is **unreachable, its client uninstalled, and no credentials configured** on this host (gates 2/3/4/5 fail). Per the mandatory pre-flight rule, no implementation details are designed beyond the already-fixed read-only mapping above.

### Recommended next action (single, concrete, ordered)

1. **Operator provisions access** (dependencies D1–D3): install `ipcat_client`, set env-var-first IPCAT credentials (user-provided), confirm network reachability. *No project code changes involved.*
2. **Run the one read-only probe** (D4): a single `chips.get_chips()` + per-target `swi.get_modules()` for `<NORD-SOC>` and `<ELIZA-SOC>`, executed in a throwaway/job-scoped context, to answer empirically: *are our SoCs populated, and can we count `soundwire_master` / `dsp_subsystem_instance` blocks?*
3. **Return here with that result.** If populated → this document is upgraded to a Go and the *exact* Track-D implementation plan is written for approval (still no code until approved). If not populated → the catalog helps `<ELIZA-SOC>` only, and the Nord DSP-base gap stays a KB/reviewer concern.

**Do not proceed to Track D. Nothing committed. Nothing pushed.**

---

*Pre-flight complete. Access gate failed (items 2/3/4/5). No implementation performed. This deliverable is uncommitted per instruction.*
