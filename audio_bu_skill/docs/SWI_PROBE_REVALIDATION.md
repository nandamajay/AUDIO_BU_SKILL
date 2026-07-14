# SWI Probe — Revalidation

**Milestone:** SWI Probe Revalidation (pre-Track-D) — *re-assessment against new evidence only.*
**Supersedes the assumptions of:** `docs/SWI_PROBE_PLAN.md` (original **No-Go**, dated one milestone earlier).
**Evidence basis:** `docs/IPCAT_MCP_ACCESS_SPEC.md` (verified working end-to-end 2026-07-13), cross-read with `docs/SWI_PROBE_PLAN.md`, `docs/SWI_ACCESS_REQUIREMENTS.md`, `docs/WP_C_IMPLEMENTATION_REPORT.md`, `docs/FIX_A_IMPLEMENTATION_REPORT.md`.
**Scope contract honored:** read-only re-assessment · no Track D · no schema change · no `catalog_count` population · no change to `cardinality.py` · no onboarding/promotion/gating/generation change · nothing committed · nothing pushed.

> **Evidence-provenance disclaimer (read first).** The IPCAT queries cited in this document were **run and recorded in `docs/IPCAT_MCP_ACCESS_SPEC.md` on 2026-07-13**; they were **not re-executed in this revalidation session.** A live re-run was attempted but could not proceed: the documented access path requires a bearer token, and the only sanctioned way to supply it (a user-provided `IPCAT_TOKEN` env var / handoff file) did not reach this session's shell, while reading the token from `auth.json` is prohibited by the standing "never scraped" boundary. Per instruction, this revalidation therefore relies on the **documented** evidence and **explicitly distinguishes** what is documented-and-verified from what is not-re-run / not-yet-obtained. **No count is claimed that was not actually recorded.**

---

## 1. Previous SWI Probe status

`docs/SWI_PROBE_PLAN.md` closed as **No-Go**, blocked at the access layer. Its central finding: the framework consumer (WP-C) was complete and waiting, but the SWI catalog was unreachable, its assumed client uninstalled, and no credentials configured. Critically, that plan assumed the access mechanism would be the **`ipcat_client` Python library** (the EVA / camera_dtsi prior-art path) — and it is precisely that assumption the new evidence overturns.

---

## 2. Original No-Go blockers vs. documented IPCAT evidence

The original gate had five items. The new evidence in `IPCAT_MCP_ACCESS_SPEC.md` addresses four of them through a **different access path than the plan assumed** — the QGenie **MCP Hub `ip_catalog` server over direct HTTP (JSON-RPC)**, not a local `ipcat_client` library import.

| # | Original blocker (SWI_PROBE_PLAN §4/§8) | Documented IPCAT evidence (IPCAT_MCP_ACCESS_SPEC) | Status |
|---|---|---|---|
| 1 | **Source exists** — passed even originally (prior art) | Confirmed: `ip_catalog` = 95 tools across chips/swi/gpio/clocks/irqs/buses/hpgs/… | ✅ **cleared** (was already pass) |
| 2 | **Reachable** — FAIL: only `HPG_DOCUMENTS` doc-search reachable, no chip-keyed API | Endpoint `https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`, state `connected`; §7 shows `chips_list_chips` → 732 chips (~182 KB) and a Nord SWI query returning live registers | ✅ **cleared** |
| 3 | **Client/tool available** — FAIL: `import ipcat_client` → ModuleNotFoundError; no pip package | The library was the *wrong* dependency to look for. The working client is the **MCP Hub over HTTP** (JSON-RPC `tools/call`), needing only `curl`/`python3` (both present). 95 tools enumerated incl. `swi_*` (9), `chips_*` (15), `clocks_*`, `irqs_*` | ✅ **cleared** (via a different, documented mechanism) |
| 4 | **Credentials/authentication** — FAIL: no IPCAT env vars, no token cache | Auth path exists and is documented: MCP Hub OAuth bearer token (RS256 JWT, scope `mcp offline_access`, ~1h lifetime, auto-refresh), identity derived from token by the gateway. Examples in §7 ran successfully with it. **In this session, however, the token could not be supplied to my shell** (see disclaimer) | ⚠️ **partially cleared** — auth *mechanism proven to work* (documented), but *not exercised by me this session*, and headless-token delivery to an automated run is unresolved |
| 5 | **Safe read-only query executable** — BLOCKED (depended on 3+4) | Documented safe read-only calls exist and ran 2026-07-13: `chips_list_chips` (no args), `swi_search_swi` (chip+query). These are strictly read/enumerate — no writes | ✅ **cleared in principle** (documented run) / ⚠️ **not re-run this session** |

**Summary of blocker movement:** three original blockers (2, 3, 5) are **cleared** by documented evidence; blocker 4 (credentials/auth) is **partially cleared** — the mechanism is proven, but live use from an automated session and durable headless token delivery remain open.

---

## 3. Re-evaluated SWI pre-flight gate

| # | Gate | Original | Revalidated | Basis |
|---|---|---|---|---|
| 1 | Source exists | ✅ | ✅ | 95-tool `ip_catalog` inventory |
| 2 | Source reachable | ❌ | ✅ | `connected` endpoint; documented `chips_list_chips` + Nord SWI hits |
| 3 | Client/tool available | ❌ | ✅ | MCP Hub HTTP path (curl/python3 only); no library needed |
| 4 | Credentials/authentication | ❌ | ⚠️ **partial** | Bearer-token mechanism documented & proven 2026-07-13; **not exercised this session**; headless delivery open |
| 5 | Safe read-only query executable | ❌ | ✅* | Documented read-only calls succeeded 2026-07-13 (*not re-run here) |

**Gate verdict:** 4 of 5 fully cleared; item 4 partial. The gate is **materially cleared** — the No-Go's foundational premise (catalog unreachable, no client, no credentials) no longer holds — with one honest caveat around automated-session authentication.

---

## 4. Documented query evidence vs. evidence not re-run this session

**A — Documented query evidence (ran & recorded 2026-07-13 in IPCAT_MCP_ACCESS_SPEC.md; NOT re-run this session):**
- `chips_list_chips` → **732 chips** returned (~182 KB payload). *(§7B, §5)*
- **Nord target resolution:** SA8797P (NordAU) present, alias **`nordschleife_2.0`**, id **781** (plus v1.1 `nordschleife_1.1`/908, v1.0 `nordschleife_1.0`/567). Control part SA8775P (LeMansAU) = `lemansau_1.0`/434. *(§5)*
- **Nord SWI query:** `swi_search_swi{chip:"nordschleife_2.0", query:"lpass"}` → returned a register list including a `DIE_0_LPASS_THROTTLE_..._RESET_CNTRL`-class register at an `0x2010B…` address. *(§7A)* — proves per-chip SWI/LPASS enumeration works for Nord.
- **Tool availability for enumeration:** `swi_*` group includes `swi_search_swi`, `swi_get_module_details[_by_chip]`, `swi_get_module_registers`, `swi_get_submodules`, `swi_map_versions_by_chip`, `swi_generate_hwio_c_header_file`. *(§4)*

**B — Evidence NOT re-run / NOT obtained this session (must not be asserted as fact):**
- No live `chips_list_chips` / `swi_*` call was executed by me this session (token unavailable to my shell).
- **No Eliza alias/id** appears anywhere in the documented evidence (see §6).
- **No instance count** for `soundwire_master`, `dsp_subsystem_instance`, or `lpass_macro_instance` has been obtained for any target — the documented Nord query was a `lpass` *register search*, not an instance enumeration. Countability is assessed as **feasible from documented capabilities** (§7), not demonstrated.

---

## 5. Nord resolution result

**Resolved (documented).** Nord = SA8797P (NordAU), catalog alias **`nordschleife_2.0`** (id 781), with v1.1 and v1.0 revisions also present. This directly retires the original plan's highest-rated risk — that Nord (a newer/derivative part) might be *unpopulated* in the catalog. It is populated, and a per-chip SWI query against it already returned live LPASS registers. *(Documented 2026-07-13; not re-run this session.)*

---

## 6. Eliza resolution result

**Not resolvable from available evidence.** `IPCAT_MCP_ACCESS_SPEC.md` enumerates Nord/LeMans/codec chips but contains **no Eliza alias or id**, and no other in-project document supplies a confirmed catalog alias for Eliza's SoC. Prior assessments only *speculated* Eliza is "likely present." Therefore:
- Eliza resolution is **UNKNOWN / pending** — it requires a live `chips_list_chips` filter on Eliza's alias candidates, which was not runnable this session.
- I make **no claim** that Eliza is present or absent. `<ELIZA-SOC>` remains a placeholder.

---

## 7. Per-class countability assessment (feasibility from documented capabilities — NO counts claimed)

Countability here means: *do the documented IPCAT tools expose a read-only path that could enumerate instances of this class for a resolved chip?* This is a **capability judgment**, not a measured count. **No count was obtained for any class.**

| Element class | Documented capability that would enumerate it | Feasibility | Basis / caveat |
|---|---|---|---|
| **`soundwire_master`** | `swi_search_swi{chip, query:"soundwire"/"swr"}` → module list; `swi_get_submodules` / `swi_get_module_details_by_chip` to enumerate master instances | **Appears feasible** (for a resolved chip) | Same tool family that returned Nord LPASS registers; SoundWire is an SWI-catalogued block. **Flagship need is on Eliza, whose chip is unresolved (§6)** → feasibility is contingent on resolving Eliza first. Not demonstrated. |
| **`dsp_subsystem_instance`** | `swi_search_swi{chip:"nordschleife_2.0", query:"lpass"/"adsp"/"q6"}` → module/submodule enumeration; `swi_get_module_registers` for base addresses | **Appears feasible for Nord** | Nord is resolved and its LPASS domain already returned live registers via the exact tool. ADSP/Q6 enumeration is the same mechanism. Actual instance count **not obtained**; whether the count is unambiguous from module naming is unverified. |
| **`lpass_macro_instance`** | `swi_search_swi{chip, query:"lpass"}` already returns LPASS-domain registers; `swi_get_submodules` to enumerate WSA/VA/RX/TX macro blocks | **Appears feasible for Nord** | Strongest documented signal — a real Nord `lpass` query returned LPASS-throttle registers, confirming the LPASS domain is catalogued and queryable. Enumerating *macro instances* specifically is the same path, but **not demonstrated** and macro-name→instance mapping is unverified. |

**Cross-cutting caveat:** a register/module *search* returning hits confirms the domain is queryable; it does **not** by itself yield a clean per-class *instance count*. Converting "these modules exist" into "N instances of class X" is a small mapping step (name-pattern enumeration, camera_dtsi-style) that has **not** been exercised and is not designed here (that is Track D). Feasibility ≠ obtained count.

---

## 8. Is `catalog_count` now feasible?

**In principle: yes — feasibility is substantially higher than at No-Go.** The access layer that blocked the original plan is cleared by documented evidence: a reachable, tool-rich, chip-keyed catalog with working per-chip SWI enumeration, and Nord confirmed present and queryable. The consumer side has been ready all along (WP-C's `catalog` authority lane + schema 1.3.0 `catalog` field + rendering — see `WP_C_IMPLEMENTATION_REPORT.md` / `FIX_A_IMPLEMENTATION_REPORT.md`), so populating `catalog_count` remains **purely additive data** with no schema/`cardinality.py`/gating change.

**But feasibility is not yet demonstrated end-to-end**, for three honest reasons:
1. **No count has actually been obtained** for any class on any target (queries not re-run this session).
2. **Eliza is unresolved** (§6) — the flagship `soundwire_master` use-case cannot be confirmed feasible until Eliza's chip is resolved.
3. **Automated-session authentication is unresolved** (§3 item 4) — the bearer-token mechanism works interactively/as-documented, but durable headless token delivery to an automated onboarding run is an open ops question, and reading the token from `auth.json` is off-limits by policy.

So: `catalog_count` is feasible **as a design proposition and for Nord's DSP/LPASS classes specifically**, contingent on (a) resolving Eliza and (b) settling headless auth. It is **not** yet a proven, repeatable pipeline.

---

## 9. Updated Go / No-Go / Partial-Go decision

### **PARTIAL-GO** (upgraded from No-Go).

- **Access layer:** effectively **GO** — reachable, client path exists (MCP Hub HTTP), read-only queries documented-working, Nord resolved.
- **Blocking residuals that keep it short of full GO:**
  1. Automated-session auth not exercised (token delivery unresolved; `auth.json` read prohibited).
  2. Eliza SoC unresolved → flagship `soundwire_master` feasibility unconfirmed.
  3. Zero instance counts actually obtained → countability is assessed-feasible, not demonstrated.

This is a genuine PARTIAL-GO: the architectural dead-end the No-Go feared is gone, but a live, credentialed, per-class enumeration for **both** targets has not been demonstrated — so it is not a clean full GO either.

---

## 10. Recommendation for the next milestone

**Recommended: a short, bounded "SWI Live Confirmation" step before any Track D Plan — not Track D itself, and not remain-blocked.**

Ordered next actions (all read-only; no implementation):
1. **Settle headless auth cleanly** — establish a sanctioned way for an automated session to obtain the bearer token that does **not** read `auth.json` (e.g. an operator-run wrapper that refreshes and exports the token into the run environment, or wiring `ip_catalog` as a native MCP per `IPCAT_MCP_ACCESS_SPEC.md` §6 with a token-refresh wrapper). This is the single gating residual.
2. **Resolve Eliza** — one live `chips_list_chips` filtered on Eliza's alias candidates; record alias/id (sanitized) or a definitive "absent."
3. **Obtain the three counts read-only** — `swi_search_swi` + `swi_get_submodules` for `soundwire_master` (Eliza-first), `dsp_subsystem_instance` (Nord), `lpass_macro_instance` (Nord); record **sanitized** counts/evidence summaries only, raw output kept local/temporary, nothing committed.
4. **Then** decide Track D: with real counts in hand, upgrade `SWI_PROBE_PLAN.md` to a full GO and write the **exact Track D implementation plan for approval** (still no code until approved).

**Not recommended now:** jumping straight to a Track D Plan (counts unproven, Eliza unresolved, auth unsettled) — or declaring "remain blocked" (the access layer is demonstrably cleared). The measured position is PARTIAL-GO → do the bounded live confirmation next.

*"Access clean-up"* from the decision menu maps to action #1 above and is the highest-priority residual.

---

## 11. Confidentiality & scope compliance

- SoC identifiers: Nord's catalog **alias** (`nordschleife_2.0`) and ids are reproduced **only** because they are already documented non-confidentially in the in-repo `IPCAT_MCP_ACCESS_SPEC.md`; Eliza remains `<ELIZA-SOC>` (no confirmed alias exists to redact). No part-number↔schematic linkage, no firmware paths, no kernel hashes, no LD-series references, no IPCAT doc IDs.
- **No token was read, printed, cached, or scraped this session.** The token was never available to my shell; `auth.json` was **not** read; no environment dump or shell-history scan occurred. The transient token handoff file was confirmed **absent/removed** from job tmp before writing this report.
- **No count is asserted as fact** — every per-class statement is a feasibility judgment explicitly flagged as not-yet-obtained.
- No source code, schema, `cardinality.py`, onboarding/promotion/gating/generation behavior changed. Nothing committed, nothing pushed. No Track D implemented.

---

*Revalidation complete. Status: **PARTIAL-GO**. Access-layer blockers cleared on documented evidence; residuals = automated-session auth, Eliza resolution, and actually-obtained counts. Deliverable uncommitted per instruction.*
