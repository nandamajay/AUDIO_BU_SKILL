# EVA IPCAT Access — Analysis

**Question:** How does **EVA** (`EVA_QLI_DT_Generator`) access IPCAT — and did it already solve the auth / token-refresh / environment-isolation problem the Audio BU Skill is now stuck on?
**Type:** Investigation only.
**Inputs:** `docs/IPCAT_MCP_ACCESS_SPEC.md`, prior EVA findings (`docs/IPCAT_CAPABILITY_ASSESSMENT.md` §2, `docs/SWI_PROBE_PLAN.md`), prior camera_dtsi findings (for contrast), prior SWI assessments (`SWI_PROBE_REVALIDATION.md`, `SWI_LIVE_CONFIRMATION.md`, `IPCAT_NATIVE_MCP_ASSESSMENT.md`, `SWI_DECISION_RECORD.md`).
**Scope contract honored:** investigation only · no code · no MCP wiring · no `.mcp.json` change · no Track D · no source/schema change · nothing committed · nothing pushed.

> **Provenance note (read first).** The EVA and camera_dtsi repositories are **not cloned into this session's workspace** (verified: `find` under the workspace returned no `eva`/`camera_dtsi` tree). This analysis synthesizes the **already-recorded** EVA findings from `docs/IPCAT_CAPABILITY_ASSESSMENT.md` (which documents a fresh-clone read of `generate_cvp_dtsi.py`, `TODO_confidence_status.md`, and camera_dtsi's `auth.py`/`credentials.py` in a prior session) and `docs/SWI_PROBE_PLAN.md`. **No EVA source was re-read this session; no EVA code is copied.** Where a detail is documented-but-not-re-verified, it is flagged.

> **Bottom line up front:** EVA solved a **different** problem than the one blocking us. EVA authenticates **in-process** via the **`ipcat_client` Python library** with an **env-var-first credential order** — and because everything runs in one process in one environment, **EVA never faces the operator-shell-vs-analysis-environment isolation barrier at all.** So: EVA proves a clean **headless-auth pattern** (env-var-first) that is reusable, but EVA does **not** use the MCP Hub, does **not** read QGenie's `auth.json`, and therefore did **not** "solve" our MCP-Hub token-refresh problem — it **sidesteps** it by using a different access mechanism entirely. That distinction is the whole finding.

---

## 1. The seven questions, answered directly

| # | Question | Answer | Basis |
|---|---|---|---|
| 1 | **How does EVA authenticate?** | Via the `ipcat_client` library's `setup_auth()`, which tries credentials in a fixed order (see §3). Identity is to the **IPCAT backend directly**, not the QGenie MCP Hub. | `IPCAT_CAPABILITY_ASSESSMENT.md` §2 (l.35) |
| 2 | **How does EVA refresh tokens?** | **It largely doesn't — it re-authenticates.** EVA relies on a cached token file (`~/.ipcat_token`, mode 600) or env-var creds; there is **no documented OAuth refresh-token rotation** like the MCP Hub's. If the cached token is stale, the credential order falls through to env-var user/pass or interactive `getpass`. | §2 (l.35); no refresh loop recorded |
| 3 | **Does EVA read `auth.json`?** | **No.** EVA reads `~/.ipcat_token` and/or `IPCAT_TOKEN` / `IPCAT_USER`+`IPCAT_PASSWORD` env vars. `auth.json` is the **QGenie MCP Hub** OAuth file — a *different auth system* EVA does not touch. | §2 (l.35); `IPCAT_MCP_ACCESS_SPEC.md` §2 |
| 4 | **Does EVA use the MCP Hub directly?** | **No.** EVA imports the `ipcat_client` **library** and calls it in-process (`swi.get_modules()`, `chips.get_chips()`, …). No HTTP JSON-RPC to `qgenie-mcphub.qualcomm.com`. | §2 (l.31); comparison table l.66 |
| 5 | **Does EVA use `ipcat_client`?** | **Yes — this is EVA's entire access mechanism.** EVA is a single Python script that imports `ipcat_client` and calls its domain objects directly. | §2 (l.31) |
| 6 | **Did EVA already solve the same problem we're discussing?** | **No — it avoids it.** Our blocker is (a) MCP-Hub token refresh under a "never read `auth.json`" rule and (b) environment isolation between the operator `!` shell and the analysis environment. EVA has **neither** problem because it doesn't use the Hub and runs single-process. It *does* solve a **related** problem — headless credential provisioning — with an env-var-first order. | §1.3 of `SWI_DECISION_RECORD.md`; §2 here |
| 7 | **What exact reusable pattern exists?** | The **env-var-first credential order** (`IPCAT_TOKEN` / `IPCAT_USER`+`IPCAT_PASSWORD` checked before any interactive fallback) as a **headless auth pattern**, and — more strategically — the **`ipcat_client`-library-in-process access mode itself** as an alternative to MCP-Hub HTTP that would sidestep *both* our blockers. Pattern, not code. | §6 here |

---

## 2. Architecture diagram

**EVA (library, single-process — the model that avoids our blocker):**

```
┌───────────────────────────────────────────────────────────────┐
│  ONE process, ONE environment (EVA run host)                   │
│                                                                │
│   generate_cvp_dtsi.py                                         │
│      │  import ipcat_client                                    │
│      │  setup_auth()  ──reads──►  IPCAT_TOKEN / USER+PASS env  │
│      │                            or ~/.ipcat_token (mode 600) │
│      ▼                                                          │
│   ipcat_client library ──HTTPS──►  IPCAT backend               │
│      swi.get_modules() / chips.get_chips() / irqs / clocks     │
│      ▼                                                          │
│   structured CSV/dict rows  ─►  prompt to QGenie (values only) │
│                                                                │
│   No second environment. No file handoff. No MCP Hub.          │
└───────────────────────────────────────────────────────────────┘
```

**Audio BU Skill's failed attempt (MCP Hub, two environments — where we got stuck):**

```
┌────────────────────────┐   file/env handoff   ┌────────────────────────┐
│ Operator `!` shell     │  ✗ BLOCKED (isolation)│ Analysis environment   │
│  reads auth.json       │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─► │  never sees the files  │
│  curl → MCP Hub        │   env var → unset     │  cannot parse results  │
│  writes *.json to tmp  │   token file → absent │                        │
│                        │   responses → absent  │                        │
└────────────────────────┘                       └────────────────────────┘
        the whole barrier only exists because access was split across
        two environments AND routed through the Hub's hourly bearer token
```

**Contrast — camera_dtsi (library-behind-a-local-MCP, single host):** wraps the same `ipcat_client`-style fetch inside a **local stdio MCP** whose tools do the Python fetch/shape/cache in-process; env-var-first creds (CI-first), keyring, then a mode-600 env file. Same single-host, in-process-fetch property as EVA — also does not face our two-environment split.

---

## 3. Auth flow (EVA)

Documented credential order in `setup_auth()` (`IPCAT_CAPABILITY_ASSESSMENT.md` l.35), tried top-to-bottom until one succeeds:

```
1. Cached token file   ~/.ipcat_token   (mode 600)      ← reused if still valid
2. IPCAT_TOKEN         env var                            ← headless override
3. IPCAT_USER + IPCAT_PASSWORD   env vars                 ← headless (CI) path
4. interactive getpass()                                  ← last-resort, blocks
```

Key properties:
- **Env-var-first for headless** (steps 2–3): a run host with `IPCAT_TOKEN` or user/pass set authenticates **non-interactively** — no prompt, no blocking. This is the "working headless path already exists" finding.
- **Interactive fallback exists** (step 4): confirms the original plan's flagged risk is real, but it is only reached if steps 1–3 all miss.
- **Credential target is the IPCAT backend**, authenticated by the library — **not** the MCP Hub gateway, **not** an OAuth bearer derived from `auth.json`.

camera_dtsi's order is the same spirit, CI-tuned: `IPCAT_USER`/`IPCAT_PASSWORD` "always checked first," then OS keyring, then a mode-600 env file written once by `install.sh`, with interactive `getpass` reserved for one-time setup only.

## 4. Query flow (EVA)

```
setup_auth()  →  ipcat_client domain objects  →  structured rows  →  QGenie prompt
                   swi.get_modules(chip)          CSV / dict          (values only;
                   chips.get_chips()              per-field DATA       reference DTSI
                   irqs.get_interrupts(chip)      blocks w/ provenance is the structural
                   clocks.get_freqplan_release()                       authority)
                                     │
                                     └─► verify_output(): section presence, inline-TODO
                                         scan, address padding, provenance-file integrity
```

- The **orchestrator observes every fetch** (it calls the library directly) — unlike Audio BU Skill's current LLM-issued, unobservable MCP prose search.
- Results are **typed rows**, not prose — the property both EVA and camera_dtsi converge on.
- `chips.get_chips()` is EVA's analogue of `chips_list_chips` — i.e. EVA has the exact call that would **resolve Eliza**, just via the library instead of the Hub.

## 5. Token lifecycle (EVA vs. MCP Hub)

| Property | EVA (`ipcat_client`) | MCP Hub (our path) |
|---|---|---|
| Credential store | `~/.ipcat_token` (mode 600) or env vars | `auth.json` (OAuth: access+refresh token, `expires_at`) |
| Lifetime | Cached token reused until stale; env-var creds are static | Access token **~1 hour** |
| Refresh | **No rotation loop** — falls through the credential order and re-auths (getpass at worst) | Auto-refresh from stored `refresh_token`; `qgenie mcphub login` on dead refresh |
| Boundary tension | **None** — env vars / a dedicated token file, not the QGenie OAuth file | Reading `auth.json` collides with the standing "never read `auth.json`" rule |

**Consequence:** EVA's lifecycle is *simpler* precisely because it doesn't ride the hourly-expiring Hub bearer. The token-refresh problem in `SWI_DECISION_RECORD.md` §6 is **specific to the MCP Hub path** and **does not exist** in EVA's model — because EVA's credential is not the Hub OAuth token.

---

## 6. Reusable components

**Reusable (as patterns, not code):**

1. **Env-var-first credential order** — `IPCAT_TOKEN` / `IPCAT_USER`+`IPCAT_PASSWORD` before any interactive fallback. This is the proven headless-auth pattern both EVA and camera_dtsi independently converge on. It maps to `SWI_DECISION_RECORD.md` §6 **Option (C) / alternative model**: provision env-var creds for the analysis environment and never touch `auth.json`.
2. **The `ipcat_client`-library-in-process access mode itself** — the single most strategically relevant reusable idea. If the **analysis environment** imported `ipcat_client` and read env-var creds, it would issue queries **in-process, in its own environment**, which simultaneously:
   - removes the **environment-isolation barrier** (no cross-shell handoff — the analysis env fetches directly), and
   - removes the **MCP-Hub token-refresh + `auth.json` tension** (different credential system; env-var-first, no OAuth bearer).
3. **Observable, orchestrator-issued fetch** returning **typed rows** (not LLM-issued prose) — the discipline that makes counts extractable at all.
4. **`chips.get_chips()` as the Eliza-resolution call** and `swi.get_modules(chip)` as the enumeration call — the exact library-level analogues of the Hub tools we wanted.
5. **`verify_output()`-style post-fetch self-check** and the `TODO_confidence_status.md` **confidence-ledger** discipline (already partially adopted in Audio BU Skill's WP-B ledger).

**What can be reused in Audio BU Skill:**
- The **env-var-first auth *pattern*** — directly, as the credential model for whichever access mode is chosen (it satisfies the "never scraped / never read `auth.json`" boundary by construction).
- The **library-in-process access *option*** — as a serious alternative to native MCP wiring, evaluated below.
- The **typed-rows + observable-fetch + confidence-ledger** disciplines — already the direction WP-B/WP-C took.

**What cannot be reused:**
- **No EVA code** — it is CVP/EVA-specific and internal (per the standing "no EVA code is to be copied" rule from `IPCAT_EVIDENCE_LAYER_PLAN.md`).
- **EVA's hard-coded domain maps** (MVS0C/MVS0/EVA_CC constants, 4-slot SID layout, EVA/CVP `Client` filters) — camera-of-audio mismatch; audio extractors must be authored fresh.
- **EVA's `~/.ipcat_token` cache file mechanics** — an implementation detail, not a boundary-safe pattern to copy verbatim; the reusable part is *env-var-first*, not the specific dotfile.
- **The assumption that `ipcat_client` is installed** — it was the original No-Go blocker D1 (`ModuleNotFoundError`); reusing the library mode requires provisioning the package first (an ops/approval step, not free).

---

## 7. Did EVA solve our problem? — the precise answer

**No — and understanding *why not* is the point.** Our blocker (`SWI_LIVE_CONFIRMATION.md` / `SWI_DECISION_RECORD.md`) has two parts:

1. **Environment isolation** — operator `!` shell and analysis environment have different filesystem/env views, so cross-shell handoff of Hub query results fails.
2. **MCP-Hub token refresh under a credential boundary** — the hourly bearer needs refresh, but refresh reads `auth.json`, which policy forbids.

EVA has **neither** problem, for one structural reason: **EVA does not use the MCP Hub and does not split work across two environments.** It imports a library and authenticates with env-var/dotfile creds in a single process. So EVA is not a *solution* to our blocker — it is an example of an **architecture that never incurs the blocker.**

That reframes the choice in `SWI_DECISION_RECORD.md`:
- The **native-MCP path** (that record's subject) fixes environment isolation but *inherits* the Hub token-refresh + `auth.json` tension (its gating decision).
- The **EVA-style library path** would fix environment isolation **and** avoid the `auth.json` tension (env-var-first, different credential system) — at the cost of provisioning `ipcat_client` (the old D1) and taking a runtime dependency.

Neither is free; they trade different costs. EVA's evidence says the library path's *auth* is a solved, copyable pattern — which materially de-risks that option.

---

## 8. Recommendation

**PARTIAL-GO on adopting EVA's pattern — specifically: adopt the env-var-first auth pattern now (as policy), and formally add "EVA-style `ipcat_client` library access" as a second candidate alongside native MCP in the `SWI_DECISION_RECORD.md` §6 decision.**

Rationale:
- **Adopt immediately (pattern-only, no code):** the **env-var-first credential order** as the sanctioned headless-auth model for *any* future IPCAT access. It is proven by two independent prior-art systems, satisfies the never-read-`auth.json` boundary by construction, and directly instantiates the decision record's Option (C). This costs nothing and closes the "how do we auth headlessly without scraping" question.
- **Elevate to a decision candidate:** the EVA-style **library-in-process** access mode deserves to sit beside native-MCP wiring in the pending decision, because it addresses **both** blockers at once, whereas native MCP addresses one and inherits the other. The honest trade: library mode needs `ipcat_client` provisioned (old blocker D1) + a runtime dependency + approval (old D5); native MCP needs the token-refresh/credential-boundary decision resolved.
- **Do not adopt now / not GO:** any implementation, `.mcp.json` wiring, dependency install, or Track-D work — all remain gated, exactly as `SWI_DECISION_RECORD.md` §8 states.
- **Not NO-GO:** EVA genuinely contributes a reusable, boundary-safe auth pattern and a viable alternative access architecture; it is not a dead end.

**Suggested next decision (for the operator, no code):** choose the access **mechanism** —
- **(i) Native MCP Hub** — fixes isolation; must resolve token-refresh/`auth.json` boundary (Option A/B/C from the decision record).
- **(ii) EVA-style `ipcat_client` library in the analysis environment** — fixes isolation *and* avoids `auth.json`; must provision the library + accept a dependency (old D1/D5).
- **(iii) camera_dtsi-style local structured MCP** — a hybrid (library behind a local stdio MCP with env-var-first creds); most engineering but best structured-rows + caching discipline.

All three are compatible with the env-var-first auth pattern recommended for immediate adoption. **No Track D, no wiring, no install proceeds until the operator picks a mechanism and (for i) resolves the token-refresh/credential-boundary decision.**

---

## 9. Confidentiality & scope compliance

- **No `auth.json`, token, or token file read this session.** EVA's credential order is described from documented findings; the `auth.json` tension is discussed as a *decision*, not acted on.
- No credentials printed, no environment dumped, no shell history read.
- **No EVA/camera_dtsi source re-read or copied** this session — synthesis is from in-repo `IPCAT_CAPABILITY_ASSESSMENT.md` / `SWI_PROBE_PLAN.md`; the repos are not in this workspace.
- Nord alias reproduced only from non-confidential in-repo docs; Eliza remains `<ELIZA-SOC>`.
- No count asserted. Investigation only: no code, no `.mcp.json` change, no MCP wiring, no source/schema change, no Track D. Nothing committed, nothing pushed.

---

*EVA IPCAT Access Analysis: EVA authenticates in-process via the `ipcat_client` library with an env-var-first credential order; it does **not** use the MCP Hub, does **not** read `auth.json`, and therefore **avoids** — rather than solves — our environment-isolation + Hub-token-refresh blocker. Reusable now: the env-var-first auth pattern. Reusable as a decision option: EVA-style library access, which would address both blockers at the cost of provisioning `ipcat_client`. **PARTIAL-GO** — adopt the pattern, add the option to the pending decision; no implementation until a mechanism is chosen. Deliverable uncommitted per instruction.*
