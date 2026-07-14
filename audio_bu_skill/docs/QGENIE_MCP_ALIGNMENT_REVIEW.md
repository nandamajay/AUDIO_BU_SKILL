# Native QGenie MCP Alignment Review

**Type:** Architecture review only. **No code, no `probe.py` changes, no implementation, no commits.**
**Question:** Should the Audio BU Skill align to the **native QGenie MCP registration model**, or keep the probe's `~/.claude/.mcp.json` + `ipcat-mcp-server` + inline-header assumptions?
**Sources:** `docs/IPCAT_EXECUTION_ENVIRONMENT.md`, `docs/PROJECT_STATUS_EXECUTIVE.md`, `docs/PHASE1_LIVE_EXECUTION_PACKAGE.md`, plus a read-only re-confirmation of the registration model in `~/.claude.json`.

---

## 1. Probe Assumptions vs Actual QGenie MCP Deployment

| Dimension | Phase-1A probe assumes (Path A-Option-C) | Actual QGenie deployment (observed) |
|---|---|---|
| **Config location** | `~/.claude/.mcp.json` (a standalone file) | `~/.claude.json` → `projects[<workspace>].mcpServers` (**project-scoped**, per-workspace) |
| **Server key** | `ipcat-mcp-server` | `ip_catalog` |
| **Transport type** | StreamableHttp (fastmcp client the probe constructs) | `type: http` MCP server, hosted on the **QGenie MCP Hub** (`qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`) |
| **Auth model** | **Inline** `headers` block (dedicated token) read from config | **Gateway-brokered OAuth** — no inline token in the entry; the hub brokers identity (same path as `qgenie-chat`; cf. `mcp-needs-auth-cache.json`) |
| **Client ownership** | Probe **builds** its own transport (`httpx` factory, `verify=True`) | Claude's **native MCP client** owns the connection; servers are registered, not hand-constructed |
| **Discovery scope** | Current workspace | Registered in **AURA_V1**; NORD_BU has none |
| **Delivery** | Standalone script + config | qgenie capabilities arrive via the **plugin marketplace** (`qgenie-chat/-debug/-quartz/…`) |

**Reading:** the probe models a *self-contained, dedicated-token, single-file* MCP client. The platform actually offers a *registered, gateway-brokered, project-scoped, natively-clienced* MCP server. These are two different integration philosophies — Phase-0 **Option A-Option-C** (dedicated token) vs Phase-0 **Option A proper** (Native MCP Hub). The probe was built to the fallback; the environment ships the mainline.

---

## 2. Gaps

### 2.1 Temporary compatibility gaps (closable by provisioning, no redesign)
- **G-T1 Location/key mismatch:** probe reads `~/.claude/.mcp.json:ipcat-mcp-server`; reality is `~/.claude.json:projects[…].ip_catalog`. Bridged by writing a matching `.mcp.json` entry.
- **G-T2 Missing inline header:** the native entry has no token; the probe's presence check requires a `headers` block. Bridged by an operator-provisioned read-only header (dedicated token, or a forwarded/brokered header).
- **G-T3 Workspace scope:** IPCAT registered in AURA_V1, probe runs in NORD_BU. Bridged by running in AURA_V1 or replicating the registration.

All three are **provisioning/wiring**, not code — the probe is correct; the environment simply hasn't been pointed at it.

### 2.2 Long-term architectural gaps (not closable by provisioning)
- **G-L1 Auth ownership:** the probe wants to *hold* a credential (inline header); the platform wants the *gateway to broker* it. A bridged inline token duplicates an auth path the hub already owns → a second credential to mint, rotate, and secure. Divergent from the platform direction.
- **G-L2 Client ownership:** the probe hand-builds an `httpx`/fastmcp transport. The native model has Claude's MCP client manage the session (retries, auth refresh, lifecycle). The probe re-implements what the hub client already does — the `verify=True` guarantee it protects is, natively, the hub's responsibility.
- **G-L3 Registration model:** project-scoped `mcpServers` + marketplace plugins is how every other qgenie capability (chat, debug, quartz) is delivered. A standalone script + `.mcp.json` is outside that model — it won't be discovered, shared, or governed the way plugins are.
- **G-L4 Token lifecycle (the open Gate-1 item):** a dedicated inline token re-introduces exactly the refresh/expiry problem the k-genesis analysis flagged; the brokered model was the thing that avoided it.

---

## 3. Is a local `.mcp.json` bridge merely a temporary workaround?

**Yes — unambiguously a temporary workaround, not a destination.**

- It exists only to satisfy the probe's *presence-check shape* (G-T1/G-T2) so Phase-1A can return exit 0 against the real hub.
- It **re-creates** an auth surface (inline token) that the native model deliberately **removed** (gateway brokering) — so it moves *away* from the platform direction to unblock a measurement.
- It is justified **only** as the fastest way to obtain the **first live PASS + the three counts** (the Phase-1 evidence goal), on the explicit understanding that production integration later aligns to native registration.
- Nothing about the bridge is load-bearing for 1B/1C *logic* — those consume structured JSON regardless of how the transport was established. So discarding the bridge later costs nothing in resolution/count code.

**Verdict:** acceptable as a **time-boxed Phase-1 evidence bridge**; **not** acceptable as the Phase-2 production access path.

---

## 4. Recommendation

**Sequenced: B now, C as the target — explicitly not A.**

- **(A) Keep the probe exactly as-is — NO (as a permanent stance).** The probe is *correct* and should not change to chase this; but "as-is" implies the inline-token `.mcp.json` model is the plan, and it is not. Keep the probe unchanged *for Phase-1 measurement only*.
- **(B) Add a compatibility layer later — YES, as the immediate step.** For Phase-1, use the **operator-provisioned `.mcp.json` bridge** (§3) to reach the native `ip_catalog` hub with the *unmodified* probe. This is the minimum-change path already identified in `IPCAT_EXECUTION_ENVIRONMENT.md` §6 and costs no redesign. Treat it as disposable.
- **(C) Align directly to native QGenie MCP registration — YES, as the destination.** For production (Phase-2 and the shipped skill), the Audio BU Skill should consume IPCAT via the **native project-scoped `ip_catalog` MCP registration + gateway-brokered auth**, exactly like the other qgenie plugins — no self-held token, no hand-built transport, delivered through the marketplace/registration model.

**One-line:** *Bridge now with the unchanged probe to get the evidence (B); align to native registration for production (C); never adopt the inline-token single-file model as the end state (not A).*

This is fully consistent with the frozen Phase-0 direction (short-term Option B/A-Option-C to unblock; long-term the native/structured model) — the discovery just replaced "long-term Option C (local structured MCP)" specifics with the concrete **QGenie MCP Hub** as the realized native Option A.

---

## 5. Phase Impact

| Phase | Impact of choosing **B-now / C-target** |
|---|---|
| **Phase-1A** | **No probe change.** Operator provisions the `.mcp.json` bridge (url = hub `ip_catalog` + read-only header) → `--check` shows Path A present → live lookup runs unchanged. Only residual: decide bridge-token nature (dedicated vs forwarded) — the standing Gate-1 token-lifecycle item, now pinned to a concrete URL. Exit-0 PASS is achievable via the bridge. |
| **Phase-1B** | **Unaffected by transport choice.** Eliza/Nord resolution consumes structured JSON from the hub identically whether reached via bridge or native client. The RESOLVED/ABSENT/AMBIGUOUS contract, ≥2-field Nord re-confirm, and evidence artifact are transport-agnostic. Bridge is sufficient for 1B evidence. |
| **Phase-1C** | **Unaffected for measurement.** The three counts + WP-C cross-check run on structured hub responses regardless of transport. Note: 1C still needs the specific read-only enumerate tools added to the allow-list (unchanged, transport-independent). Bridge is sufficient for first live cardinality verdicts. |
| **Phase-2** | **This is where alignment matters.** The shipped generation lane must **not** carry a self-held IPCAT token or a bespoke transport. It should consume IPCAT via **native `ip_catalog` MCP registration + gateway auth**, packaged like the qgenie plugins. Adopting C here avoids G-L1..L4 (duplicate credential, duplicate client, off-model delivery, refresh problem). The Phase-1 bridge is retired at this boundary. |

---

## 6. Summary

- The probe's assumptions (single-file `.mcp.json`, `ipcat-mcp-server`, inline header) describe Phase-0 **Option A-Option-C**; the environment ships Phase-0 **Option A proper** (Native QGenie MCP Hub, project-scoped, gateway-brokered).
- The gaps split cleanly: **temporary** (location/key/header/scope — closable by provisioning) vs **long-term** (auth ownership, client ownership, registration model, token lifecycle — closable only by native alignment).
- The local `.mcp.json` bridge **is** a temporary workaround — fine to get Phase-1 evidence with the unchanged probe, wrong as an end state.
- **Recommendation: B now (bridge, no probe change), C as the target (native registration for Phase-2); do not enshrine A.**
- Phases 1A/1B/1C are unblocked by the bridge; **Phase-2 is where native alignment must land.**

---

*Architecture review only. No code, no probe changes, no new mechanism, nothing committed. The probe stays correct and unchanged; the recommendation is a provisioning sequence (bridge → native), consistent with the frozen Phase-0 direction.*
