# IPCAT Native MCP — Assessment

**Question:** Is wiring `ip_catalog` as a **native MCP** the correct solution to the environment-isolation blocker that left SWI Live Confirmation **INCONCLUSIVE**?
**Type:** Investigation only.
**Inputs:** `docs/SWI_PROBE_REVALIDATION.md`, `docs/SWI_LIVE_CONFIRMATION.md`, `docs/IPCAT_MCP_ACCESS_SPEC.md`.
**Scope contract honored:** investigation only · no implementation · no `.mcp.json` change · no Track D · no source change · no schema change · nothing committed · nothing pushed.

> **Recommendation up front: PARTIAL-GO.** Native MCP wiring is the **architecturally correct fix for the transport blocker** and would very likely eliminate the environment-isolation problem — because MCP servers are invoked as **native tool calls from the analysis environment itself**, not routed through the operator's `!` shell (this is directly observable: `qgenie-chat`, `logtalk`, and `skillagent` are already reachable this way in this session, while `ip_catalog` is not wired and is not). It is **PARTIAL-GO, not GO**, because native wiring is a `.mcp.json` change + a durable token-refresh mechanism (both currently out of scope and unbuilt), and two content residuals (Eliza resolution, actual count extraction) remain even after the transport is fixed. Native MCP removes the *transport* blocker; it does not by itself deliver the *counts*.

---

## 1. Current blocker summary

### 1.1 What specifically failed in SWI Live Confirmation
The read-only query script (`swi_phase1.sh`) was run by the operator via `!` and reported `PHASE1_DONE`, implying the token loaded and the `curl` calls returned **on the operator's side**. But **none of the response files** (`chips.json`, `nord_swi_*.json`) were visible to the analysis environment — only the script itself. With no response data reachable, no counts could be parsed, and per standing rules none were fabricated. Result: **INCONCLUSIVE**, readiness held at PARTIAL-GO.

### 1.2 Why repeated transport attempts failed
Three distinct handoff mechanisms failed **identically** this session:

| Handoff mechanism (via operator `!`) | Result seen by analysis environment |
|---|---|
| `IPCAT_TOKEN` env var (`setenv`) | **unset** |
| Token written to a file in job tmp | **absent** |
| Query responses written to job tmp | **absent** |

**Root cause:** the operator's interactive `!` shell and the analysis (Bash-tool) environment operate on **different filesystem / environment views**. A file or env var the `!` shell creates at path `X` does not appear at path `X` for the analysis environment. This is an **environment-isolation / data-transport barrier**, not an auth, catalog, or query failure — all three of which the revalidation established as working (from documented evidence). No additional scripting, env, or file handoff can cross that boundary; that class of fix is exhausted and closed.

---

## 2. Native MCP assessment

The decisive question is **which environment issues the catalog call**. The failed approach put the call in the operator's `!` shell and tried to move the *result* across the isolation boundary. Native MCP inverts this: the analysis environment issues the call itself.

**Directly observable in this session:** three MCP servers — `qgenie-chat`, `logtalk`, `skillagent` — are wired natively and are invoked as **tool calls from the analysis environment**, returning results directly into it with no `!` shell and no file handoff. `ip_catalog` is **not** wired, and is correspondingly **not** reachable as a native tool. This is the empirical basis for the assessment below.

| Question | Assessment | Basis |
|---|---|---|
| **Would native MCP eliminate the need for token/file handoffs?** | **Yes.** The analysis environment would call `mcp__ip_catalog__*` tools directly; there is no intermediate file or env var to transport, so the three failed handoff mechanisms become irrelevant. | Native MCP tools return results in-band to the caller; no cross-shell artifact exists to lose. |
| **Would native MCP allow direct read-only IPCAT queries from the analysis environment?** | **Yes, in principle.** The same read-only calls (`chips_list_chips`, `swi_search_swi`, `swi_get_submodules`, …) would be issued as native tool calls and their JSON returned directly — no double-decode-through-a-file, no `!` round-trip. | `IPCAT_MCP_ACCESS_SPEC.md` §6 documents the native wiring; §4 enumerates the 95 tools that would surface as `mcp__ip_catalog__*`. |
| **Would native MCP eliminate the environment-isolation blocker?** | **Yes for transport — this is the correct fix for *this* blocker.** The isolation barrier only bites when data must move *between* the two environments. Native MCP keeps both the call and its result inside the analysis environment, so the barrier is never crossed. | Confirmed by the working `qgenie-chat`/`logtalk`/`skillagent` native servers in this session. |

**Conclusion for §2:** native MCP **is** the right structural solution to the environment-isolation blocker. It does not "work around" the barrier — it removes the need to cross it at all.

---

## 3. Remaining blockers after native MCP

Fixing transport does **not** close the milestone. Residuals:

| Residual | Status after native MCP | Notes |
|---|---|---|
| **Eliza resolution** | **Still open — but becomes directly executable.** | No Eliza alias exists in any in-repo doc. With native access, a single `chips_list_chips` call + filter resolves it (or returns a definitive "absent"). The blocker changes from *impossible* to *one query away*. |
| **Count extraction** | **Still open — but becomes directly executable.** | The three per-class counts were never obtained. Native access makes `swi_search_swi` + `swi_get_submodules` runnable directly; converting module/register hits → a clean per-class integer is still a name-pattern enumeration step (unverified, and is Track-D design work — out of scope here). |
| **Auth / token-refresh** | **New operational concern introduced by native wiring.** | Bearer token ≈ 1h lifetime (`IPCAT_MCP_ACCESS_SPEC.md` §2). A static `Authorization: Bearer ${IPCAT_TOKEN}` header in `.mcp.json` (§6) **expires hourly** and would 401 mid-session. A durable setup needs a token-refresh wrapper that reads the live token from `auth.json` and re-logs-in on 401. **Critical boundary tension:** that wrapper reads `auth.json` — which collides with the standing "never read auth.json / never scrape credentials" rule. Who runs the refresh (operator-owned wrapper vs. analysis environment) must be settled before wiring, or the credential boundary is violated. |
| **Operational risks** | **Several, all manageable but real.** | (a) Credentials in `.mcp.json` — never commit a token; use an env-var/wrapper indirection and keep it uncommitted. (b) 95 tools surface natively — read-only discipline must be enforced by *which tools are called*, since the server itself is not read-only. (c) Confidentiality — raw catalog output must stay local/uncommitted; only sanitized counts/block-names may be recorded. (d) Session/host stability — a new persistent MCP connection on a shared host. |

---

## 4. Do the four operations become directly executable?

"Directly executable" = issuable as a native `mcp__ip_catalog__*` tool call from the analysis environment, **assuming native wiring + a working (refreshing) token are in place.**

| Operation | Directly executable after native MCP? | Qualifier |
|---|---|---|
| **Eliza resolution** | **Yes.** | One `chips_list_chips` call + alias filter. Definitive either way (resolved or absent). No dependency on the other three. |
| **`soundwire_master` enumeration** | **Yes, mechanism-wise** — becomes *runnable*; count is *derivable, not guaranteed clean*. | `swi_search_swi{chip, query:"soundwire"/"swr"}` → `swi_get_submodules`. Flagship need is on **Eliza**, so this is gated on Eliza resolving first. Module→instance mapping unverified. |
| **`dsp_subsystem_instance` enumeration** | **Yes, mechanism-wise** — runnable on Nord immediately (Nord resolved). | `swi_search_swi{chip:"nordschleife_2.0", query:"adsp"/"q6"}` → submodule enumeration. Whether the count is unambiguous from module naming is unverified. |
| **`lpass_macro_instance` enumeration** | **Yes, mechanism-wise** — strongest signal; runnable on Nord. | `swi_search_swi{query:"lpass"}` already documented to return LPASS registers on Nord; `swi_get_submodules` to enumerate WSA/VA/RX/TX macros. Macro-name→instance mapping unverified. |

**Honest bound:** native MCP makes all four **executable** (issuable and answerable). It does **not** guarantee the three enumerations yield a *clean, unambiguous per-class integer* on first pass — that conversion is exactly the unverified mapping step that belongs to a Track-D design, not to this assessment. Executable ≠ count-in-hand.

---

## 5. Recommendation

### **PARTIAL-GO — proceed toward native MCP wiring, but settle two prerequisites first.**

Native MCP is the **correct and recommended fix for the environment-isolation blocker** — it is not a workaround; it removes the cross-environment transport entirely, which the three failed handoffs proved is otherwise uncrossable. It is **PARTIAL-GO rather than GO** because two prerequisites must be resolved before wiring is sound, and two content residuals remain after:

**Prerequisites before wiring (both currently unbuilt / out of current scope):**
1. **Token-refresh mechanism + credential-boundary decision.** A static hourly-expiring bearer header is not durable. A refresh wrapper is needed — but it reads `auth.json`, which collides with the standing "never read auth.json" rule. **Decide explicitly** who owns the refresh (operator-run wrapper that injects a fresh token into the MCP config vs. analysis environment) so the credential boundary is honored. This is the single gating item.
2. **Read-only enforcement + confidentiality posture.** Wiring surfaces all 95 tools (not inherently read-only); enforce read-only by call discipline, keep the token and raw output uncommitted, record only sanitized counts/block-names.

**Content residuals that remain even after a clean wire (not solved by transport):**
- Eliza still needs one resolving query (becomes trivially executable).
- The three per-class counts still need extraction + a module→instance mapping whose cleanliness is unverified (Track-D design territory).

**Sequencing (all read-only; still no Track-D code):**
1. Settle prerequisite #1 (token refresh + credential boundary) → this is the decision to make next.
2. Wire `ip_catalog` per `IPCAT_MCP_ACCESS_SPEC.md` §6 with that refresh mechanism (a `.mcp.json` change — **requires explicit approval**, not done here).
3. Resolve Eliza; obtain the three counts read-only; mark each directly-countable / indirectly-derivable / unavailable from real data.
4. **Only then** re-decide GO vs. PARTIAL-GO for a Track-D Plan.

**Not GO:** because wiring + token-refresh are unbuilt and the credential-boundary question is unsettled — approving "GO" now would greenlight a config+credential change this assessment is scoped to *evaluate*, not perform.
**Not NO-GO:** because native MCP demonstrably *does* solve the stated blocker (the isolation barrier), as proven by the already-working native servers in this session.

---

## 6. Confidentiality & scope compliance

- **No token, `auth.json`, or token file was read.** The credential-boundary tension around a refresh wrapper is *flagged as a decision*, not acted on.
- No credentials printed, no environment dumped, no shell history read.
- Nord alias (`nordschleife_2.0`) reproduced only because already documented non-confidentially in-repo; Eliza remains `<ELIZA-SOC>`.
- **No count asserted** — all four operations assessed for *executability*, not results.
- Investigation only: no `.mcp.json` change, no source, schema, `cardinality.py`, onboarding/promotion/gating/generation change. Nothing committed, nothing pushed. No Track D.

---

*IPCAT Native MCP Assessment: **PARTIAL-GO.** Native MCP is the correct fix for the environment-isolation transport blocker (verified against the session's already-native MCP servers), but requires a token-refresh + credential-boundary decision before wiring, and leaves Eliza resolution and count extraction as executable-but-unfinished residuals. Deliverable uncommitted per instruction.*
