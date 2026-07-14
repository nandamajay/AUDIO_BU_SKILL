# SWI Live Confirmation

**Milestone:** SWI Live Confirmation (pre-Track-D) — *live read-only verification of the revalidation's open items.*
**Follows:** `docs/SWI_PROBE_REVALIDATION.md` (status **PARTIAL-GO**).
**Scope contract honored:** read-only · no Track D · no code · no schema change · no `catalog_count` population · no `cardinality.py`/onboarding/promotion/gating/generation change · nothing committed · nothing pushed.

> **Outcome up front: INCONCLUSIVE — live data could not be retrieved into this session's environment.** The read-only query script (`swi_phase1.sh`) was executed by the operator and reported `PHASE1_DONE`, but **none of its response files (`chips.json`, `nord_swi_*.json`) are visible to the analysis environment.** This is an environment-isolation problem (below), not a catalog, auth, or query problem. No live counts were obtained; **no count is claimed.** Documented Nord resolution from `IPCAT_MCP_ACCESS_SPEC.md` is carried forward. Readiness remains **PARTIAL-GO** — unchanged, with no regression.

---

## 1. What was attempted

Per the milestone goal, a read-only query script (`$JOB_TMP/swi_phase1.sh`) was authored to:
1. `chips_list_chips` → full chip list, to **resolve Eliza's alias** and re-confirm Nord.
2. `swi_search_swi{chip:"nordschleife_2.0", query:…}` for `soundwire`, `swr`, `adsp`, `q6`, `lpass`, `audioreach` → Nord read-only SWI enumeration for the three element classes.

The script reads the bearer token from the operator's own `auth.json` **only when the operator runs it** (operator action, operator credential); the token stays inside the script process and is never echoed or written out. Only the read-only **response JSON** was to be dropped into job tmp for parsing here.

The operator ran it via `!` and reported `PHASE1_DONE`.

---

## 2. What actually happened — environment isolation

On attempting to parse, **the response files were not present** in job tmp or anywhere reachable by the analysis environment (verified by directory listing and `find`). Only `swi_phase1.sh` itself was visible.

This is the **third consecutive handoff** to fail the same way this session:

| Handoff mechanism (via operator `!`) | Result seen by analysis environment |
|---|---|
| `IPCAT_TOKEN` env var (`setenv`) | **unset** |
| Token written to a file in job tmp | **absent** |
| Query responses written to job tmp | **absent** |

**Root-cause conclusion:** the operator's interactive `!` shell and the analysis (Bash-tool) environment operate on **different filesystem / environment views** — the analysis environment is sandboxed separately. A file or env var produced by the `!` shell at path `X` does not appear at path `X` in the analysis environment, even though `PHASE1_DONE` confirms the `!` shell wrote it successfully on its side.

**Consequences:**
- This is **not** an authentication failure — the script completing to `PHASE1_DONE` implies the token loaded and the curl calls returned on the operator's side.
- This is **not** a catalog/reachability failure — the revalidation already established (via documented evidence) that the endpoint, tools, and Nord queries work.
- It **is** a data-transport barrier between the two environments that no additional scripting/env/file handoff can cross.
- Per standing guidance ("this is SWI Confirmation, not authentication/infra debugging"), no further handoff variants were attempted.

---

## 3. Nord results

**Resolved — carried forward from documented evidence (`IPCAT_MCP_ACCESS_SPEC.md`, verified 2026-07-13; NOT re-parsed this session because the response file is absent):**
- Nord = SA8797P (NordAU), alias **`nordschleife_2.0`** (id 781); revisions `nordschleife_1.1` (908), `nordschleife_1.0` (567) also present.
- A documented `swi_search_swi{chip:"nordschleife_2.0", query:"lpass"}` returned live LPASS registers (e.g. an `…LPASS_THROTTLE…RESET_CNTRL`-class register), proving Nord's LPASS SWI domain is present and queryable.

**Not obtained this session:** the six Nord `swi_search_swi` responses (`soundwire`/`swr`/`adsp`/`q6`/`lpass`/`audioreach`) — the files did not reach the analysis environment. **No Nord instance counts were obtained.**

---

## 4. Eliza results

**Unresolved.** Resolving Eliza required parsing the live `chips_list_chips` response to filter for Eliza's alias candidates. That response file (`chips.json`) is **not present** in the analysis environment, and no Eliza alias exists in any in-repo document. Therefore:
- Eliza alias: **UNKNOWN / pending** (unchanged from revalidation §6).
- Eliza catalog presence: **not confirmed and not refuted.**
- No claim is made either way. `<ELIZA-SOC>` remains a placeholder.

---

## 5. Countability assessment

The milestone asks each class be marked **directly countable / indirectly derivable / unavailable**. Because no live enumeration response reached the analysis environment, these can be given **only as capability judgments from documented tooling**, not as measured results. **No count was obtained for any class.**

| Element class | Documented path | This-session result | Countability (judgment only) |
|---|---|---|---|
| **`soundwire_master`** | `swi_search_swi` + `swi_get_submodules` on the resolved chip | **Not obtained** — Nord `soundwire`/`swr` responses absent; Eliza (the flagship) unresolved | **Indeterminate this session.** Mechanism plausibly *indirectly derivable* (search → enumerate submodules), but flagship target (Eliza) unresolved and no data parsed |
| **`dsp_subsystem_instance`** | `swi_search_swi{chip:"nordschleife_2.0", query:"adsp"/"q6"}` → module/submodule enumeration | **Not obtained** — `adsp`/`q6` responses absent | **Indeterminate this session.** Nord is resolved and LPASS-domain queryability is documented, but the DSP responses were not parsed; would likely be *indirectly derivable* |
| **`lpass_macro_instance`** | `swi_search_swi{chip, query:"lpass"}` → enumerate WSA/VA/RX/TX macro submodules | **Not obtained this session** — though documented evidence shows Nord `lpass` *registers* return | **Indeterminate this session.** Strongest documented signal (LPASS domain confirmed present), but macro→instance enumeration was not parsed here |

**Honest bound:** documented evidence confirms the LPASS domain is *queryable* on Nord; it does **not** establish a clean instance count for any of the three classes. Converting module/register hits into a per-class count (name-pattern enumeration via `swi_get_submodules`) was the whole point of this live step and **could not be completed** because the data did not cross into the analysis environment.

---

## 6. Updated readiness status

**PARTIAL-GO (unchanged from revalidation).** No regression, no advance:
- **Cleared and stable:** access layer (reachable, tool-rich, Nord resolved) — from documented evidence.
- **Still open (all three revalidation residuals remain):**
  1. Automated-session data path — **newly sharpened**: the blocker is not just token delivery but a full **environment-isolation barrier** between the operator `!` shell and the analysis environment; live response data cannot currently reach the analysis side.
  2. Eliza resolution — still unresolved (needed the `chips.json` that didn't arrive).
  3. Actual per-class counts — still zero obtained.

---

## 7. Recommendation

**PARTIAL-GO — hold before Track D. Do NOT declare GO; do NOT regress to NO-GO.**

The catalog is demonstrably usable (documented), but the milestone's purpose — obtaining authoritative counts and resolving Eliza — was **not** achieved this session due to environment isolation, so a GO for Track D would rest on unproven counts. The correct next action is an **access clean-up** targeting the transport barrier, not Track-D code:

**Ordered next actions (all read-only; no implementation):**
1. **Fix the data path (root blocker).** Establish a channel where read-only IPCAT responses produced by the operator's environment are actually **readable by the analysis environment.** Options, operator's choice:
   - (a) Run the query script so its output lands in a location **both** environments share (if any exists), and confirm the analysis side can list it;
   - (b) Wire `ip_catalog` as a **native MCP** in this project (`IPCAT_MCP_ACCESS_SPEC.md` §6) with a token-refresh wrapper, so the analysis environment calls the catalog directly (subject to the credential-boundary rules) rather than relying on cross-environment file handoff;
   - (c) Operator pastes back **sanitized** query summaries (counts + block names only, no raw dumps, no confidential identifiers) for parsing here.
2. **Then resolve Eliza** from a readable `chips_list_chips` response and record alias/id (sanitized) or a definitive "absent."
3. **Then obtain the three counts** read-only and mark each directly-countable / indirectly-derivable / unavailable from real data.
4. **Only then** re-decide GO vs. PARTIAL-GO for a Track D Plan (still no code until a plan is approved).

Until the data path is fixed, SWI Live Confirmation cannot be completed and Track D must not start.

---

## 8. Confidentiality & scope compliance

- **No token, `auth.json`, or token file was read this session.** Presence-only checks confirmed no token was reachable to the analysis environment; the credential remained entirely on the operator's side.
- **No credentials printed, no environment dumped, no shell history read.**
- Nord alias (`nordschleife_2.0`) is reproduced only because it is already documented non-confidentially in-repo; Eliza remains `<ELIZA-SOC>`.
- **No count asserted** — every per-class entry is explicitly "not obtained / indeterminate this session."
- No source, schema, `cardinality.py`, onboarding/promotion/gating/generation change. Nothing committed, nothing pushed. No Track D implemented.

---

*SWI Live Confirmation: INCONCLUSIVE (blocked by environment isolation between the operator shell and the analysis environment). Status held at PARTIAL-GO. Deliverable uncommitted per instruction.*
