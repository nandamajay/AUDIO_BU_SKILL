# Bridge Provisioning Feasibility

**Type:** Decision support only. **No code, no `probe.py` changes, no new architecture, no implementation, no commits.**
**Question:** Can the recommended Phase-1 `.mcp.json` bridge (`QGENIE_MCP_ALIGNMENT_REVIEW.md` §4-B) actually be exercised in practice — boundary-safely?
**Sources:** `docs/IPCAT_EXECUTION_ENVIRONMENT.md`, `docs/QGENIE_MCP_ALIGNMENT_REVIEW.md`, `docs/PHASE1_LIVE_EXECUTION_PACKAGE.md`, plus a read-only re-inspection of the `ip_catalog` registration.

---

## 1. The Discovered Registration (re-examined)

The complete `ip_catalog` MCP entry, in `~/.claude.json` → `projects[/local/mnt/workspace/AURA_V1].mcpServers`:

```json
"ip_catalog": {
  "type": "http",
  "url":  "https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp"
}
```

**Only two keys — `type` and `url`. No `headers`, no `env`, no token, no auth field of any kind.** The sibling `qgenie_chat` server has the identical shape (`.../connect/qgenie_chat/mcp`), and `mcp-needs-auth-cache.json` lists `qgenie-chat` as requiring interactive auth. 

**What this proves:** authentication for these hub servers is performed **entirely by Claude's native MCP client via the QGenie gateway OAuth flow** — the bearer credential is *brokered at connect time* and is **never present in the registration file**. The config carries a URL; the gateway carries the identity.

---

## 2. Can a Temporary Bridge Be Created Without Violating the Boundaries?

The probe's Path A presence check requires an entry with a **truthy `headers` block** (`_mcp_config_present`: `has_auth = bool(entry.get("headers"))`) and then constructs its **own** `httpx` transport using those headers. So a working bridge must put an **inline auth header** into a `~/.claude/.mcp.json` `ipcat-mcp-server` entry. The question is *where that header value comes from*, and each source tests a different boundary:

| Bridge construction path | auth.json boundary | Gateway OAuth ownership | Read-only policy | Feasible? |
|---|---|---|---|---|
| **(a) Reuse the native brokered OAuth token** (extract the live session bearer and paste it as a header) | ❌ **Violates** — that token lives in the protected credential store (`.credentials.json`), which is exactly the file the boundary forbids reading (and which was correctly blocked during discovery) | ❌ **Violates** — duplicates/forwards a credential the gateway is meant to own and broker; probe would impersonate the brokered session | ⚠️ token scope unknown (may exceed read-only) | **NO** |
| **(b) Mint a NEW dedicated read-only token** for the hub (operator-issued, scoped to catalog reads) and place it as the header | ✅ **Honored** — a fresh token, never sourced from `auth.json`/`.credentials.json`; env-var-first | ✅ **Honored** — a *separate* credential, not the brokered session; doesn't usurp gateway ownership | ✅ if the operator scopes it read-only | **YES (operator-owned)** |
| **(c) Run the probe from AURA_V1 relying on the native client** (no header) | ✅ | ✅ | ✅ | **NO for the probe** — the probe does not use the native client; it builds its own transport and *requires* an inline header. Presence check fails with no `headers`. This path needs the native client, i.e. Option C alignment, not a bridge. |

**Conclusion:** a bridge is boundary-safe **only via path (b)** — a newly minted, operator-owned, read-only, dedicated token. Path (a) breaches both the `auth.json`/credential boundary *and* gateway OAuth ownership. Path (c) is not a bridge at all — it is the native-alignment destination (Option C), which the probe as-built cannot consume.

---

## 3. Operator Artifact, Ownership, Technical Feasibility

- **What artifact is needed:** a `~/.claude/.mcp.json` file containing an `ipcat-mcp-server` entry with:
  - `url` = `https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`
  - `headers` = `{ "<Authorization-style header>": "<dedicated read-only token>" }`
  - (and the probe run from a context where that file is what it reads — i.e. `~/.claude/.mcp.json` present for the invoking user)
- **Who owns it:** the **operator/platform team** — specifically whoever can **mint a dedicated read-only IPCAT/hub token**. This is *not* something automation can produce: the probe cannot read the brokered token (boundary), and cannot self-issue a new one.
- **Is bridge provisioning technically feasible?** **Yes — conditionally.** It is feasible **iff** the QGenie hub supports issuing a **dedicated, read-only, non-interactive token** that authorizes `connect/ip_catalog/mcp` outside the interactive OAuth flow. 
  - If the hub *only* accepts gateway-brokered interactive OAuth (no issuable standalone token), then **no boundary-safe header value exists**, and the bridge is **not feasible** — the only path forward is native Option C alignment.
  - This is precisely the **open Gate-1 token-lifecycle question** (`PHASE1_NEXT_STEPS.md` operator action #4), now sharpened to a yes/no: *can a dedicated read-only hub token be minted?*

---

## 4. Decision Table

| Condition | Bridge Possible? | Live Run Possible? |
|---|---|---|
| Operator can mint a **dedicated read-only** hub token (path b) | ✅ Yes (boundary-safe) | ✅ Yes — `.mcp.json` entry → `--check` present → §2 runbook exit-0 achievable |
| Only the **brokered OAuth session** token exists (path a) | ❌ No (breaches auth.json + gateway ownership) | ❌ Not via the probe/bridge — requires native alignment |
| Hub accepts **only interactive OAuth**, no standalone token | ❌ No boundary-safe header value exists | ❌ Not via the bridge — Option C only |
| Probe run in **AURA_V1** relying on native client (path c) | ➖ N/A (not a bridge) | ❌ Probe requires inline header; cannot use native client as-built |
| Native **Option C** alignment adopted (future) | ➖ N/A (bridge retired) | ✅ Yes (production path; out of scope for Phase-1) |

**Read:** the live run is possible **exactly when** the operator can mint a dedicated read-only token. Every other row is either boundary-unsafe or requires native alignment (a redesign, explicitly out of scope here).

---

## 5. Final Verdict

# READY FOR BRIDGE PROVISIONING — conditional on one operator artifact

The bridge **is technically feasible and boundary-safe**, via exactly one path: an **operator-minted, dedicated, read-only hub token** placed as the `headers` value in a `~/.claude/.mcp.json:ipcat-mcp-server` entry pointing at the discovered `ip_catalog` URL. With that artifact:

- `auth.json` boundary — **honored** (fresh token, never read from the credential store),
- gateway OAuth ownership — **honored** (a separate credential, not the brokered session),
- read-only policy — **honored** (operator scopes the token read-only; the probe's allow-list is unchanged),
- and the unmodified probe reaches exit-0, unblocking 1A → 1B → 1C.

**The single gating unknown** (which flips the verdict to *BRIDGE NOT FEASIBLE*): if the hub **cannot** issue a standalone read-only token and accepts **only** interactive gateway OAuth, then no boundary-safe header exists and the bridge is impossible — the only route is native Option-C alignment (out of Phase-1 scope). 

**Recommended operator action:** confirm with the QGenie hub team whether a **dedicated read-only `ip_catalog` token** can be minted. 
- **Yes →** provision the `.mcp.json` entry and execute `PHASE1_LIVE_EXECUTION_PACKAGE.md` §6 from step 5. 
- **No →** stop bridging; schedule native Option-C alignment for the production integration.

---

*Decision support only. No code, no probe changes, no new architecture, nothing committed. The probe stays correct and unchanged; feasibility rests entirely on whether a boundary-safe, dedicated read-only token can be operator-minted for the native `ip_catalog` hub endpoint.*
