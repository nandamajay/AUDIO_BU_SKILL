# Phase-0 Gate 1 Closure — Investigation

**Question:** Can **Gate 1** of `docs/PHASE0_MECHANISM_DECISION.md` §6 be **closed** — i.e. "a mechanism is chosen and provisioning is complete"?
**Type:** Investigation only — empirical, boundary-safe presence checks. **No install, no wiring, no `auth.json`, no config change.**
**Gate 1 definition (verbatim from `PHASE0_MECHANISM_DECISION.md` §6.1):** *"A mechanism is chosen (B preferred, A fallback) and the corresponding provisioning is complete — for B: `ipcat_client` importable (D1) + dependency approval (D5); for A: the `SWI_DECISION_RECORD.md` §6 token-refresh/credential-boundary decision is approved."*
**Scope contract honored:** investigation only · no code · no implementation · no MCP wiring · no `.mcp.json` change · no dependency install · no `auth.json` access · no Track D · nothing staged/committed/pushed.

> **Verdict up front: Gate 1 CANNOT be closed today — it remains UNSATISFIED for every candidate mechanism.** Empirically, in the analysis environment: `ipcat_client` is **NOT importable** and is **not present anywhere on disk** (B's D1 fails); no dependency-approval decision is recorded (B's D5 fails); the env-var-first credentials are **all unset** (presence-only check — needed by B and by A's Option-C fallback); and `ip_catalog` is **not wired** as a native MCP (A's wiring prerequisite fails) with the token-refresh/credential-boundary decision still open (A's D6 fails). Gate 1 closure requires an **operator provisioning + decision action** that no read-only investigation can perform. What *is* now closed is the **ambiguity** about what's missing: this record pins each prerequisite to a measured state.

---

## 1. What Gate 1 requires, and the closure logic

Gate 1 is satisfiable by **either** mechanism path:

- **Path B (preferred):** `ipcat_client` importable **(D1)** **AND** dependency approval **(D5)**.
- **Path A (fallback):** `ip_catalog` wired as native MCP **AND** the `SWI_DECISION_RECORD.md` §6 token-refresh / credential-boundary decision approved **(D6)**.

Both paths additionally assume **env-var-first credentials are provisionable** (the boundary-safe auth model from `EVA_IPCAT_ACCESS_ANALYSIS.md` §6 / `SWI_DECISION_RECORD.md` §6 Option C), since neither path may read `auth.json`.

Gate 1 closes when **at least one full path** is provisioned. This investigation measures each prerequisite's actual state.

---

## 2. Measured state (this session, boundary-safe checks)

| ID | Prerequisite | Measured result | Method (read-only) |
|---|---|---|---|
| **D1** | `ipcat_client` importable in analysis env | **FAIL — NOT FOUND** | `importlib.util.find_spec('ipcat_client')` → None (Python 3.10.12) |
| **D1′** | `ipcat_client` present in any on-disk venv/site-packages | **FAIL — absent** | `find` over workspace venvs (`shikra_BU/.venv`, `patchwise/.venv`, …) + `/usr/lib/python3`; no `ipcat_client*` match |
| **D5** | Dependency-approval decision recorded | **FAIL — none recorded** | No approval in any in-repo doc; the standing rule is "do **not** pip-install speculatively without approval" (`SWI_PROBE_PLAN.md` D1) |
| **Cred** | Env-var-first creds present (presence only) | **FAIL — all unset** | `IPCAT_TOKEN` unset, `IPCAT_USER` unset, `IPCAT_PASSWORD` unset (values never read) |
| **A-wire** | `ip_catalog` wired as native MCP here | **FAIL — not wired** | Only `qgenie-chat` / `logtalk` / `skillagent` are connected this session; no `.mcp.json` exists |
| **D6** | Token-refresh / credential-boundary decision approved | **FAIL — still open** | `SWI_DECISION_RECORD.md` §6/§8 records it as the single gating open decision; no approval since |

**Every prerequisite of both paths is currently unmet.** No prerequisite is *blocked-forever* — each is an operator action away — but none is *done*.

---

## 3. Per-path closure assessment

**Path B (EVA-style library) — UNSATISFIED.**
- D1 fails: `ipcat_client` is neither importable nor on disk anywhere reachable. This is the *original No-Go blocker* (`ModuleNotFoundError`) still standing — unchanged since `SWI_PROBE_PLAN.md`.
- D5 fails: no approval to add the runtime dependency.
- To close: operator (i) provisions `ipcat_client` (install/approval — **out of scope here, and must not be done speculatively**), (ii) grants D5 dependency approval, (iii) provisions env-var creds. Then D1 re-checks importable.

**Path A (native MCP Hub) — UNSATISFIED.**
- A-wire fails: `ip_catalog` is not in `.mcp.json` (no `.mcp.json` exists); it is not callable as a native tool this session.
- D6 fails: the token-refresh/credential-boundary decision (`SWI_DECISION_RECORD.md` §6) is still open — and closing it via a refresh wrapper that reads `auth.json` would violate the standing rule unless policy is explicitly amended.
- To close: operator (i) approves the §6 decision (Option A operator-owned refresh, or Option C dedicated env-var creds — **not** Option B silent `auth.json` read), (ii) wires `ip_catalog` natively with that mechanism (**a `.mcp.json` change requiring approval — not done here**).

**Path A-fallback via Option C (dedicated read-only env-var credential) — UNSATISFIED but lowest-friction.**
- Needs only: provision a dedicated read-only IPCAT env-var credential (no `auth.json`, no library install) + wire `ip_catalog`. This is the single cheapest route to a *closed* Gate 1 because it sidesteps both the D1 library-install and the `auth.json` boundary — but it is still an operator provisioning action, not done today.

---

## 4. What this investigation *did* close

Gate 1 itself stays open, but two things are now settled and no longer need re-investigation:

1. **The missing pieces are pinned to measured facts**, not assumptions — D1 empirically absent (not merely "assumed uninstalled"), creds empirically unset, native MCP empirically not wired. The prior docs *inferred* these; this record *measured* them.
2. **The cheapest closure route is identified:** Option-C dedicated env-var credential + native wiring avoids *both* the library-install (D1/D5) *and* the `auth.json` boundary — a smaller operator action than either full Path B or Path A-with-refresh-wrapper.

Neither finding requires or implies any implementation.

---

## 5. Exact conditions to close Gate 1 (operator actions — no implementation proposed)

Gate 1 closes when **one** of these minimal sets is true and verified by a re-run of the §2 checks:

- **Via B:** `find_spec('ipcat_client')` is non-None in the analysis env **AND** D5 dependency approval is recorded **AND** env-var creds present (presence check).
- **Via A + Option C (recommended lowest-friction):** a dedicated read-only IPCAT env-var credential is present (presence check, no `auth.json`) **AND** `ip_catalog` is wired natively **AND** a read-only call returns from the analysis env.
- **Via A + Option A (operator-owned refresh):** operator refresh mechanism injects a fresh token without the analysis env reading `auth.json` **AND** `ip_catalog` wired **AND** read-only call returns.

Each is an **operator provisioning/decision step**. This session performs none of them (all are outside the investigation-only scope) and recommends none be done speculatively — the choice of *which* path is the operator's, informed by `PHASE0_MECHANISM_DECISION.md` §4 (short-term B, fallback A-Option-C).

---

## 6. Recommendation

**Gate 1 status: UNSATISFIED — hold. Do not start the IPCAT Evidence Layer (gate 1 is its explicit precondition).**

- **Single highest-confidence next action for the operator:** decide the **mechanism + credential model** — concretely, either (i) approve provisioning `ipcat_client` + D5 for Path B, or (ii) approve a **dedicated read-only env-var credential + native `ip_catalog` wiring** for Path A-Option-C. Option (ii) is the lowest-friction route to a *closed* gate because it avoids both the library install and the `auth.json` boundary.
- **Do not:** install `ipcat_client`, wire `.mcp.json`, read `auth.json`, or amend the never-read-`auth.json` rule — all are operator/policy actions, none is in scope, and none should happen speculatively.
- After the operator acts, a **single re-run of the §2 checks** (all boundary-safe) confirms closure; only then does Gate 1 close and the Evidence Layer become eligible to start — subject to the remaining §6 gates 3–5 (typed rows, Eliza, counts) still being unmet.

---

## 7. Confidentiality & scope compliance

- **No `auth.json`, token, or token file accessed.** Credential checks were **presence-only** (SET/unset) — no values read, printed, or logged.
- No environment dumped, no shell history read. `find_spec`/`find` are read-only availability probes; **no package was installed**, no `pip install` run.
- No `.mcp.json` created or modified; no MCP wired. No EVA/camera_dtsi source touched.
- Nord alias referenced only from non-confidential in-repo docs; Eliza remains `<ELIZA-SOC>`. No count asserted.
- Investigation only: no code, no implementation, no dependency install, no Track D. Nothing staged, committed, or pushed.

---

*Phase-0 Gate 1 Closure: **UNSATISFIED for all paths.** Measured — `ipcat_client` absent (D1 fail), no dependency approval (D5 fail), env-var creds all unset, `ip_catalog` not wired (A fail), token-refresh decision open (D6 fail). Gate 1 closure is an operator provisioning/decision action, not a read-only step; recommended lowest-friction route = dedicated read-only env-var credential + native wiring (avoids both library install and `auth.json`). Hold the Evidence Layer until a re-run of the §2 checks confirms closure. Deliverable uncommitted per instruction.*
