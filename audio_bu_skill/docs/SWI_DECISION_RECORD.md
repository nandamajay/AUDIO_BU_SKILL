# SWI Decision Record

**Purpose:** Capture the final, consolidated decision state for the SWI / `catalog_count` initiative **before any future MCP wiring work begins.** This record supersedes nothing and re-investigates nothing — it freezes the conclusions of four completed milestones and names the one decision that gates all further progress.
**Type:** Documentation only — decision record.
**Sources (all accepted):** `docs/SWI_PROBE_PLAN.md`, `docs/SWI_PROBE_REVALIDATION.md`, `docs/SWI_LIVE_CONFIRMATION.md`, `docs/IPCAT_NATIVE_MCP_ASSESSMENT.md`, `docs/IPCAT_MCP_ACCESS_SPEC.md`, `docs/SWI_ACCESS_REQUIREMENTS.md`.
**Scope contract honored:** documentation only · no code · no `.mcp.json` change · no Track D · no source/schema/`cardinality.py` change · nothing committed · nothing pushed.

> **State in one line:** The access-layer dead-end the original No-Go feared is **gone**; the catalog is reachable and Nord is resolved. But **no authoritative count has ever been obtained**, Eliza is **unresolved**, and the path forward (native MCP wiring) is **blocked on a single unresolved decision: who owns the hourly token refresh, given the standing "never read `auth.json`" rule.** No Track D work begins until that decision is approved.

---

## 1. Timeline

| # | Milestone | Verdict | What it established |
|---|---|---|---|
| 1 | **SWI Probe** (`SWI_PROBE_PLAN.md`) | **NO-GO** | Pre-flight gate failed. Assumed access required the `ipcat_client` Python library, which was uninstalled; no credentials configured; catalog assumed unreachable. Consumer side (WP-C) already complete and waiting. |
| 2 | **SWI Probe Revalidation** (`SWI_PROBE_REVALIDATION.md`) | **PARTIAL-GO** | New evidence (`IPCAT_MCP_ACCESS_SPEC.md`) overturned the library assumption: catalog reachable via **MCP Hub HTTP (JSON-RPC)**, 95 tools, Nord resolved (`nordschleife_2.0`/781), LPASS queryable. 3 of 5 original blockers cleared; auth partially cleared; Eliza unresolved; **zero counts obtained.** |
| 3 | **SWI Live Confirmation** (`SWI_LIVE_CONFIRMATION.md`) | **INCONCLUSIVE** | Attempted live read-only queries. Script ran (`PHASE1_DONE`) but response files never reached the analysis environment. Root cause: **environment-isolation barrier** between operator `!` shell and analysis environment. No counts obtained; Eliza still unresolved. Status held at PARTIAL-GO, no regression. |
| 4 | **Native MCP Assessment** (`IPCAT_NATIVE_MCP_ASSESSMENT.md`) | **PARTIAL-GO** | Native MCP wiring is the **correct fix for the isolation blocker** (proven against already-native servers `qgenie-chat`/`logtalk`/`skillagent`). But requires a **token-refresh + credential-boundary decision** before wiring, and leaves Eliza + count extraction as executable-but-unfinished residuals. |

**Trajectory:** No-Go (dead end) → Partial-Go (access path found) → Inconclusive (transport failed) → Partial-Go (transport fix identified, gated on one decision).

---

## 2. Confirmed findings

Established by documented evidence and/or directly observed this session:

1. **The catalog is reachable.** `ip_catalog` MCP server on the QGenie MCP Hub, 95 tools, endpoint `connected` (`IPCAT_MCP_ACCESS_SPEC.md`, verified 2026-07-13).
2. **The access mechanism is MCP Hub HTTP (JSON-RPC), not the `ipcat_client` library.** The library was the wrong dependency; `curl`/`python3` suffice, or native MCP wiring.
3. **Nord is resolved and queryable.** SA8797P (NordAU) = alias `nordschleife_2.0` (id 781); a documented `swi_search_swi{query:"lpass"}` returned live LPASS registers.
4. **The consumer side (WP-C / Cardinality Authority) is complete and inert-ready.** Schema 1.3.0 `catalog` lane exists, always `null` pre-SWI; comparison core treats `catalog` as authority; proven by `test_agree_with_authority_post_swi` / `test_disagree_with_authority_post_swi`. Populating `catalog_count` is **purely additive data** — no schema/`cardinality.py`/gating change needed.
5. **Native MCP calls originate in the analysis environment.** Directly observed: `qgenie-chat`, `logtalk`, `skillagent` are wired natively and callable without any `!` shell or file handoff. This is the empirical basis that native wiring removes the transport barrier.
6. **The bearer token expires ~hourly** (`IPCAT_MCP_ACCESS_SPEC.md` §2), so any durable wiring needs refresh — a static header will 401 mid-session.

---

## 3. Disproven assumptions

Assumptions that earlier milestones held and that later evidence **refuted**:

1. **"Access requires the `ipcat_client` Python library."** — FALSE. The working path is MCP Hub HTTP / native MCP. (Refuted at Revalidation.)
2. **"The catalog is unreachable / architecturally a dead end."** — FALSE. It is reachable, tool-rich, and chip-keyed. (Refuted at Revalidation.)
3. **"Nord (a newer/derivative part) might be unpopulated in the catalog."** — FALSE. Nord is present, resolved, and returns live registers. (Refuted at Revalidation.)
4. **"Cross-shell file/env handoff can move query results from the operator's shell to the analysis environment."** — FALSE. Three mechanisms (env var, token file, response files) all failed identically; the two environments have different filesystem/env views. (Refuted at Live Confirmation.)
5. **"The blocker is authentication."** — FALSE / mislabeled. The script reached `PHASE1_DONE`, so auth worked on the operator side. The blocker is **data transport across environment isolation**, not auth. (Clarified at Live Confirmation.)

---

## 4. Current project status

- **Access layer:** effectively **GO** (reachable, client path exists, Nord resolved) — documented.
- **Transport into the analysis environment:** **BLOCKED** via cross-shell handoff; **fixable** via native MCP wiring (not yet done, requires approval + token-refresh decision).
- **Eliza resolution:** **UNRESOLVED** — no alias in any in-repo doc; becomes a one-query lookup once native access exists.
- **Counts (`soundwire_master`, `dsp_subsystem_instance`, `lpass_macro_instance`):** **ZERO obtained.** Feasibility assessed only; module→instance mapping unverified.
- **Consumer (WP-C):** **READY and inert** — waiting on data only; no framework change required.
- **Overall readiness:** **PARTIAL-GO**, held steady across the last three milestones. No regression, no advance to full GO.

---

## 5. Blocking items

| # | Blocker | Nature | Blocks |
|---|---|---|---|
| **B1** | **Token-refresh ownership + credential boundary** | **Decision** (see §6) | Everything downstream. This is the single gating item. |
| B2 | Native MCP wiring not done | Config change (`.mcp.json`) — needs approval | Direct queries from analysis env |
| B3 | Eliza alias unresolved | Empirical — one query, gated on B1/B2 | `soundwire_master` flagship count |
| B4 | Zero counts obtained + module→instance mapping unverified | Empirical + Track-D design | Full GO for Track D |

B2–B4 are all **downstream of B1.** Resolving B1 unblocks the sequence; leaving B1 open freezes everything.

---

## 6. Decision required

**The one decision gating all further progress:**

> The bearer token expires ~hourly. A durable native MCP wiring needs a refresh mechanism. Any refresh mechanism reads the live token from `auth.json` — which **collides directly with the standing "never read `auth.json` / never scrape credentials" rule.** So the question is not *whether* to refresh, but **who performs the refresh and where the credential boundary sits.**

### Who owns token refresh?

| Option | How it works | Pros | Cons / boundary implications |
|---|---|---|---|
| **(A) Operator-owned refresh** | An operator-run wrapper reads `auth.json`, refreshes on 401 (`qgenie mcphub login`), and injects a fresh token into the MCP config / an env var the native server consumes. The analysis environment **never** touches `auth.json`. | Honors "never read `auth.json`" cleanly — the credential stays entirely on the operator side. Matches the boundary respected all session. | Requires operator to keep the wrapper running / re-inject on expiry. Operational burden sits with the operator. Needs a channel to hand the *token* (not the file) to the native server without re-introducing the isolation barrier — must be validated. |
| **(B) Tool-owned refresh** | The native MCP layer (or a wrapper it calls) reads `auth.json` directly and refreshes autonomously. | Fully automated; no operator babysitting; most robust for repeated use. | **Directly violates the standing "never read `auth.json`" rule** unless that rule is explicitly amended for this wrapper. Requires the user to *change the credential-boundary policy* — a deliberate decision, not a default. |
| **(C) Alternative model** | e.g. a short-lived service token / dedicated read-only credential provisioned for the analysis environment; or wiring the hub such that identity is derived without the analysis env holding `auth.json`; or operator pastes sanitized results (no raw dumps) for the narrow one-time counts. | Can sidestep the `auth.json` collision entirely; can be scoped read-only. | Requires provisioning/ops work or accepts reduced automation. Feasibility depends on what the hub/ops actually supports. |

**This record does not choose for you.** The decision is the user's because it is a **credential-boundary policy decision**, not a technical default: Option A preserves the current boundary at operational cost; Option B is most automated but requires explicitly amending the "never read `auth.json`" rule; Option C trades automation for a cleaner boundary.

---

## 7. Recommendation

**Recommended: Option (A) — operator-owned refresh — as the default, with Option (C) as the fallback if (A)'s token-injection channel proves impractical.**

Rationale:
- **(A) honors the boundary that has governed this entire initiative** ("never read `auth.json`, never scrape credentials"). It keeps the credential on the operator side and asks the analysis environment only to *consume* an already-refreshed token — the minimal change that unblocks native wiring without amending policy.
- **(B) should not be adopted silently.** It is the most convenient but requires *explicitly amending* the never-read-`auth.json` rule. If the user wants full automation, that trade must be made consciously and recorded — not backed into.
- **(C) is the clean fallback** if operator-owned token injection can't cross to the native server without re-hitting the isolation barrier — a dedicated read-only/service credential or sanitized-result paste avoids the `auth.json` collision entirely.

Sequencing once B1 is decided (all read-only, still no Track-D code):
1. Approve the token-refresh ownership model (this record's open decision).
2. Wire `ip_catalog` natively per `IPCAT_MCP_ACCESS_SPEC.md` §6 with that refresh model — **requires explicit approval; a `.mcp.json` change, not done here.**
3. Resolve Eliza (one query); obtain the three counts read-only; mark each directly-countable / indirectly-derivable / unavailable from real data.
4. **Only then** re-decide GO vs. PARTIAL-GO for a Track-D Plan (still no code until that plan is separately approved).

**Overall verdict carried forward: PARTIAL-GO** — proceed toward native wiring, gated strictly on the B1 decision.

---

## 8. Explicit statement

> **No Track D work begins — no `catalog_count` population, no `.mcp.json` wiring, no source/schema/`cardinality.py` change, no generation/onboarding/promotion/gating change — until the token-refresh / credential-boundary decision (§6) is explicitly approved.**

Until then the project holds at **PARTIAL-GO**, the consumer side stays inert-ready, and `catalog_count` remains unpopulated (`null`), exactly as today. Nothing regresses; nothing advances without that approval.

---

## 9. Confidentiality & scope compliance

- No token, `auth.json`, or token file read this session. The `auth.json` collision is named as a **decision to make**, not acted on.
- No credentials printed, no environment dumped, no shell history read.
- Nord alias (`nordschleife_2.0`) reproduced only because already documented non-confidentially in-repo; Eliza remains `<ELIZA-SOC>`.
- No count asserted — zero counts have ever been obtained.
- Documentation only: no code, no `.mcp.json` change, no source/schema/`cardinality.py`/onboarding/promotion/gating/generation change. Nothing committed, nothing pushed. No Track D.

---

*SWI Decision Record: initiative held at **PARTIAL-GO**, gated on a single open decision — token-refresh ownership / credential boundary (§6). Recommended default: operator-owned refresh (Option A), fallback Option C; Option B only with an explicit policy amendment. No Track D until that decision is approved. Deliverable uncommitted per instruction.*
