# IPCAT Execution Environment — Discovery

**Type:** Read-only environment discovery. **No code changes, no probe changes, no new mechanisms, no commits.** The Phase-1A probe is assumed correct; the goal is only to locate where IPCAT is actually available and how the Audio BU Skill should execute there.
**Method:** Inspected MCP registrations, config files, env, and repo prior-art — presence/structure only; **no credential file was read** (the `.credentials.json` read was correctly blocked and is not needed).

---

## 1. Headline Finding

IPCAT access **does exist in this machine's Claude configuration** — but **not in the environment where the probe was run.**

- The probe runs from the **`NORD_BU`** workspace, whose registered MCP server list is **empty** (`projects[/local/mnt/workspace/NORD_BU].mcpServers = []`).
- The IPCAT server is registered under a **different workspace, `AURA_V1`**, as an MCP server named **`ip_catalog`**.
- That is why the live run returned exit 3 "config absent": the probe looked in the right *kind* of place but the current workspace has no IPCAT registration, and the actual registration lives elsewhere under a different key and auth model.

---

## 2. Where `ipcat_client` / IPCAT Access Actually Lives

| Signal | Observation |
|---|---|
| **`ipcat_client` library** | **Not importable** in this environment (`importlib.util.find_spec('ipcat_client')` → None). Path B is not provisioned here. |
| **IPCAT env tokens** | None of `IPCAT_TOKEN` / `QGENIE_TOKEN` / `IPCAT_CLIENT_TOKEN` set. |
| **`~/.claude/.mcp.json`** | Does **not exist** (the file the probe's Path A checks). |
| **`ip_catalog` MCP server** | **Registered** in `~/.claude.json` under `projects[/local/mnt/workspace/AURA_V1].mcpServers.ip_catalog`. |
| → type | `http` |
| → url | `https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp` |
| → inline auth | **none** — no `headers`/`env` in the entry; auth is **gateway-brokered** by the QGenie MCP Hub (same OAuth path as the `qgenie-chat` plugin; cf. `mcp-needs-auth-cache.json` listing `qgenie-chat`/`qgenie_chat`). |
| **Repo prior-art (`prior_art/k-genesis/`)** | References IPCat *conceptually* as the authority for chip-specific values (`ipcat_gen`, `chipio_get_qups(chip)`, "always fetch from IPCat"), but contains **no live client wiring** — it is documentation of intent, not an access mechanism. |

**Conclusion:** the working IPCAT mechanism on this machine is the **QGenie MCP Hub `ip_catalog` HTTP server** — Phase-0 **Option A (Native MCP Hub)**, gateway-brokered auth, **registered only in the AURA_V1 project scope.**

---

## 3. Access Mechanism — Classification

| Candidate mechanism | Present here? | Notes |
|---|---|---|
| **QGenie MCP Hub (`ip_catalog`, HTTP)** | ✅ **Yes** (AURA_V1 scope) | `qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`, gateway-brokered OAuth (no inline token). This is the live path. |
| `ipcat_client` library (Path B) | ❌ No | Not importable; no env token. |
| Dedicated-token MCP in `~/.claude/.mcp.json` (Path A-Option-C) | ❌ No | File absent; no `ipcat-mcp-server` key. |
| k-genesis-style `verify=False` remote MCP | ❌ No / not used | Prior-art only; not wired. |

So access is **through QGenie, exposed as a native MCP HTTP server** — *not* through `ipcat_client`, *not* through a dedicated-token `.mcp.json`, *not* through any other mechanism.

---

## 4. Environment Mapping

| Environment | IPCAT Access | Nord | Eliza | Mechanism |
|---|---|---|---|---|
| **`NORD_BU`** (probe runs here) | ❌ none registered (`mcpServers: []`) | — | — | — |
| **`AURA_V1`** | ✅ `ip_catalog` MCP server | operator-asserted available¹ | operator-asserted available¹ | QGenie MCP Hub, HTTP, gateway-brokered OAuth |
| bare shell / env | ❌ (no lib, no token, no `~/.claude/.mcp.json`) | — | — | — |

¹ **Nord/Eliza availability is operator-asserted, UNVERIFIED from here.** I did not query `ip_catalog` (the probe cannot reach it from the NORD_BU scope, and I will not fabricate a resolution). Confirmation happens when the probe runs in the environment where `ip_catalog` is reachable.

---

## 5. The Gap (why the probe reported "absent")

The Phase-1A probe's Path A is **correct**, but it targets a *specific* provisioning shape that does not match what exists:

| Probe expects (Path A-Option-C) | Reality on this machine |
|---|---|
| Config at `~/.claude/.mcp.json` | Registration is in `~/.claude.json` → `projects[AURA_V1].mcpServers` (project-scoped) |
| Server key `ipcat-mcp-server` | Key is `ip_catalog` |
| Entry carries `url` **+ inline `headers`** (dedicated token) | Entry carries `url` only; **auth is gateway-brokered**, no inline header |
| Current workspace = provisioning workspace | Probe runs in `NORD_BU`; IPCAT is registered in `AURA_V1` |

This is a **wiring/location mismatch, not a probe defect** — consistent with the standing note that provisioning is an operator action and the probe stays inert until it matches.

---

## 6. Minimum Change to Run the Existing Probe in the Working IPCAT Environment

**Do not redesign the probe. Do not add a mechanism.** The smallest operator-owned change that lets the *existing* probe reach the *existing* IPCAT server:

**Option 1 — Run/register where IPCAT already is (lowest friction, no secret handling):**
- Make the `ip_catalog` server visible to the workspace the probe runs in — either execute the probe from the **`AURA_V1`** workspace, or add the identical `ip_catalog` registration to the **`NORD_BU`** workspace's `mcpServers` in `~/.claude.json`.
- Then provide a Path-A `~/.claude/.mcp.json` entry keyed **`ipcat-mcp-server`** pointing at
  `https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`, matching what the probe reads.

**The one real obstacle:** the probe's Path A presence check requires an **inline auth `headers`** block, but the live server uses **gateway-brokered OAuth with no inline token**. So a 1:1 transcription of the URL alone will pass presence only if a header is supplied. Two boundary-safe ways to satisfy that **without changing the probe**:
   - **(a)** Operator provisions a **dedicated read-only token** as the `headers` value in the `ipcat-mcp-server` entry (this is exactly Phase-0 **Option A-Option-C**, the "dedicated read-only credential" fallback the plan already sanctions) — env-var-first, never from `auth.json`; **or**
   - **(b)** Operator confirms the hub accepts the gateway-brokered session such that a placeholder/forwarded header is valid, and supplies it in the same `headers` field.

Either way the change is **operator provisioning of a `~/.claude/.mcp.json` `ipcat-mcp-server` entry (url + auth header) pointing at the QGenie hub `ip_catalog` URL** — no probe edit, no new mechanism, no architecture change. Once present, `python probe.py --check` will show Path A present and the §2 live runbook proceeds unchanged.

> **Honest caveat:** because live auth is gateway-brokered rather than a dedicated inline token, the operator must decide whether to mint a dedicated read-only token (Option A-Option-C, clean) or to bridge the brokered session into a header. That decision is the residual Gate-1 item (`PHASE1_NEXT_STEPS.md` operator action #4: token nature/lifecycle) — it is unchanged by this discovery, only now pinned to a concrete URL and server.

---

## 7. What Did **Not** Change

- Phase-1A probe: untouched, still correct, still inert.
- No new mechanism introduced; the finding maps entirely onto Phase-0 **Option A / A-Option-C**.
- `auth.json` boundary honored — no credential file read (attempt blocked and abandoned; not required).
- Nord/Eliza resolution **not fabricated** — marked UNVERIFIED-from-here pending a run in the reachable environment.

---

## 8. Recommended Next Step

1. Operator provisions the `~/.claude/.mcp.json` `ipcat-mcp-server` entry (url = the hub `ip_catalog` URL + a read-only auth header per §6a/§6b), **or** runs the probe from the `AURA_V1` scope with an equivalent Path-A entry.
2. `python probe.py --check` → confirm Path A present.
3. Execute `docs/PHASE1_LIVE_EXECUTION_PACKAGE.md` §6 from step 5 (Nord lookup) — the live 1A→1B→1C sequence then runs with no further planning.

---

*Discovery only. No code, no probe changes, no new mechanism, nothing committed. The working IPCAT path is the QGenie MCP Hub `ip_catalog` HTTP server (Option A), currently registered in the AURA_V1 workspace and absent from NORD_BU; closing that wiring gap — an operator provisioning step — is all that stands between the committed probe and a live run.*
