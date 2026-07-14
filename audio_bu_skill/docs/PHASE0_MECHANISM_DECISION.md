# Phase-0 IPCAT Mechanism Decision Record

**Question:** Which of three IPCAT access architectures should Audio BU Skill target — **A. Native MCP Hub**, **B. EVA-style `ipcat_client` library**, **C. camera_dtsi-style local structured MCP** — judged against Audio BU Skill's actual requirements?
**Type:** Decision-quality engineering review. **Investigation only.**
**Inputs (all read this session):** `docs/EVA_IPCAT_ACCESS_ANALYSIS.md`, `docs/SWI_DECISION_RECORD.md`, `docs/IPCAT_MCP_ACCESS_SPEC.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md`, `docs/SWI_PROBE_PLAN.md`, `docs/SWI_LIVE_CONFIRMATION.md`.
**Scope contract honored:** investigation only · no code · no implementation · no MCP wiring · no `.mcp.json` change · no dependency install · no `auth.json` access · no Track D · nothing staged/committed/pushed.

> **Decision up front.** No option is a clean GO today. **B (EVA-style library)** is the strongest *near-term* mechanism for the one thing Phase-0 must unblock — getting authoritative, deterministic counts into the analysis environment without cross-shell isolation and without touching `auth.json` — **conditional on provisioning `ipcat_client` (the old D1 blocker) and dependency approval (D5).** **C (local structured MCP)** is the strongest *long-term* production target because it is the only option whose data-shaping, caching, and filtering discipline aligns with all six Audio BU Skill subsystems — but it is the most engineering and should not be built before Phase-0 has proven counts are extractable at all. **A (native MCP Hub)** is a viable bridge that fixes isolation but inherits the hourly-token / `auth.json`-boundary problem unresolved in `SWI_DECISION_RECORD.md`. The assumption "C is the eventual production target" **survives** the disproof attempt (§5) — but only under stated conditions, and it is **not** the correct *first* step.

---

## 1. Architecture Comparison Matrix

Evidence tags: **[LC]** `SWI_LIVE_CONFIRMATION.md`, **[DR]** `SWI_DECISION_RECORD.md`, **[EVA]** `EVA_IPCAT_ACCESS_ANALYSIS.md`, **[CAP]** `IPCAT_CAPABILITY_ASSESSMENT.md`, **[SPEC]** `IPCAT_MCP_ACCESS_SPEC.md`, **[PLAN]** `SWI_PROBE_PLAN.md`.

| Category | A. Native MCP Hub | B. EVA Library (`ipcat_client`) | C. Local Structured MCP (camera_dtsi-style) |
|---|---|---|---|
| **1. Environment-isolation risk** | **Resolved.** Calls originate in the analysis env (proven: `qgenie-chat`/`logtalk`/`skillagent` are native there) — no cross-shell handoff **[DR §2]** | **Resolved.** Single-process, in-analysis-env library import; no second environment **[EVA §7]** | **Resolved.** Local stdio server co-located with the caller; in-process fetch **[CAP §3]** |
| **2. Authentication model** | Hub OAuth **bearer**, identity derived by gateway; token in `auth.json` **[SPEC §2]** | `setup_auth()` env-var-first → IPCAT backend directly; **never `auth.json`** **[EVA §3]** | Env-var-first (CI-first) → keyring → mode-600 file; setup-time getpass only **[CAP §3, l.56]** |
| **3. Token-refresh behavior** | ~1h expiry, needs refresh loop; static header 401s mid-session **[SPEC §2][DR §6]** | No OAuth rotation — cached token/env creds; re-auth on staleness **[EVA §5]** | Same as B (env creds are static; no hourly bearer) **[CAP §3]** |
| **4. Headless suitability** | Conditional — needs a boundary-safe refresh mechanism (the open **[DR §6]** decision) | **Strong** — env-var-first is the proven headless path **[EVA §3][CAP l.35]** | **Strong** — env-var-first "always checked first…explicitly for CI" **[CAP l.56]** |
| **5. CI/CD suitability** | Weakest — hourly refresh + `auth.json` boundary is a standing CI hazard **[DR §6]** | Good — static env-var creds fit CI secrets | **Best** — designed CI-first; deterministic cached rows **[CAP l.56,73]** |
| **6. Structured-data support** | Tool-dependent; Hub returns JSON but shaping/filtering is not guaranteed typed **[SPEC §3]** | **Yes** — `swi.get_modules()`/`chips.get_chips()` return CSV/dict rows **[CAP l.31,66]** | **Yes, best** — tools shape/filter/cache typed rows before returning **[CAP l.45,67]** |
| **7. Deterministic evidence extraction** | Possible but orchestrator issues each call; shaping is ad hoc | **Yes** — orchestrator observes every fetch, pre-computes rows **[CAP l.66]** | **Yes** — deterministic fetch-shape-cache inside each tool **[CAP l.45]** |
| **8. IPCAT cardinality support** | Feasible — `swi_search_swi`+`swi_get_submodules` reachable **[SPEC §4]** | Feasible — `swi.get_modules()` enumerates; name-pattern count **[EVA §6]** | **Best-fit** — camera_dtsi already does name-pattern enumeration as cardinality authority **[CAP l.54,72]** |
| **9. SWI catalog compatibility** | **Direct** — SWI is a first-class Hub domain (9 `swi_*` tools) **[SPEC §4]** | Depends on `ipcat_client` exposing SWI (EVA used `swi.get_modules()` — yes) **[CAP l.31]** | Depends on wrapping SWI fetch in a local tool (buildable, not built) |
| **10. Eliza/Nord onboarding applicability** | Nord resolved **[SPEC §5]**; Eliza = one `chips_list_chips` call away **[DR §5]** | Nord resolvable via `chips.get_chips()`; Eliza same **[EVA §4]** | Same reach, once the chip-list tool is wrapped |
| **11. Long-term maintainability** | Medium — depends on Hub stability + refresh wrapper upkeep | Medium — a runtime dependency + EVA-CVP-specific code must be *not* copied **[EVA §6]** | **Highest ceiling / highest cost** — owns 1200+ lines of fetch-shape logic **[CAP l.152]** |
| **12. Production-readiness** | Partial — blocked on **[DR §6]** decision | Partial — blocked on D1 provision + D5 approval **[PLAN §D]** | Lowest today (unbuilt) but the intended production shape **[CAP §8]** |
| **13. External-dependency risk** | Low new code; **high external coupling** to Hub uptime/token infra | **Medium** — adds `ipcat_client` package (old D1 `ModuleNotFoundError`) **[PLAN][EVA §6]** | Medium — same library behind the tool + server maintenance debt **[CAP l.152]** |
| **14. Reviewer confidence** | Medium — opaque token flow, isolation history **[LC]** | **High** — observable, typed rows, proven auth pattern **[CAP l.66]** | **High** — typed rows + caching + explicit anti-guess rules **[CAP l.49-54]** |
| **15. Confidence-ledger alignment** | Neutral — feeds ledger if rows are typed | **Good** — EVA's `TODO_confidence_status.md` is the ledger prior art **[CAP l.33]** | **Good** — `warnings.txt`/`node_changes.json` per-run trust artifacts **[CAP l.58]** |
| **16. Future DTSI-generation alignment** | Neutral | Partial — EVA *is* a generator, but its code isn't reusable **[EVA §6]** | **Best** — camera_dtsi is a zero-code LLM generator with MCP evidence **[CAP l.43]** |
| **17. Future learn-loop / KB alignment** | Neutral | None — EVA knowledge is hard-coded constants **[CAP l.69]** | **Best** — `learn-cam-dtsi` KB-growth loop is the only prior art **[CAP l.47,87]** |

**Matrix reading:** B wins the *near-term* rows (2–7, 13–15 at acceptable cost); C wins the *architecture-ceiling* rows (5–8, 16–17); A wins only isolation (1) and native SWI reach (9) while losing the auth/refresh rows (3–5).

---

## 2. Blocker Analysis

**A. Native MCP Hub**
- *Resolved:* environment isolation **[DR §2]**; SWI reachability + tool inventory **[SPEC §4]**; Nord resolution **[SPEC §5]**.
- *Remaining:* hourly token refresh; the `auth.json` credential-boundary decision (**[DR §6]**, still open); Eliza resolution; actual counts.
- *New introduced:* a refresh-wrapper that reads `auth.json` would **violate the standing "never read `auth.json`" rule** unless policy is explicitly amended **[DR §6 Option B]**; ongoing external coupling to Hub token infra.

**B. EVA Library**
- *Resolved:* environment isolation (single-process) **[EVA §7]**; token-refresh tension (no hourly bearer) **[EVA §5]**; `auth.json` boundary (env-var-first, never touched) **[EVA §3]**; headless auth (proven pattern) **[CAP l.35]**.
- *Remaining:* Eliza resolution; actual counts; SWI-specific enumeration must be confirmed exposed by the installed `ipcat_client`.
- *New introduced:* **old D1** — `ipcat_client` must be provisioned (was `ModuleNotFoundError`) **[PLAN]**; **old D5** — runtime-dependency approval; risk of accidentally copying EVA-CVP-specific code (must author audio extractors fresh) **[EVA §6]**.

**C. Local Structured MCP**
- *Resolved (by design, once built):* isolation; auth (env-var-first CI); structured rows; caching; cardinality-by-name-pattern **[CAP l.45,54]**.
- *Remaining:* everything is **unbuilt** — no server, no audio-shaped tools; Eliza/counts still pending.
- *New introduced:* largest engineering surface (fetch-shape-cache logic ~1200 lines analogue) **[CAP l.152]**; server lifecycle/maintenance; still depends on `ipcat_client`-class access underneath (inherits B's D1).

---

## 3. Audio BU Skill Alignment

| Subsystem | A. Native MCP | B. EVA Library | C. Local Structured MCP |
|---|---|---|---|
| **Knowledge Base** (audio KB, camera_dtsi Gap 2 **[CAP l.86]**) | Neutral — data source only | Neutral — constants don't transfer | **Aligned** — KB-growth pattern is camera_dtsi-native **[CAP l.47]** |
| **Cardinality Validator** (WP-C `catalog` lane authority) | Feeds it if counts obtained | Feeds it (enumerate + count) | **Best** — name-pattern → count is the exact camera_dtsi rule **[CAP l.54,72]** |
| **Confidence Ledger** (WP-B, implemented) | Neutral | **Aligned** — EVA ledger prior art **[CAP l.33]** | **Aligned** — per-run warnings/trust artifacts **[CAP l.58]** |
| **IPCAT Evidence Layer** (`IPCAT_EVIDENCE_LAYER_PLAN`) | Partial — prose-risk unless tool typed | **Aligned** — typed rows, observable fetch **[CAP l.66]** | **Best** — typed+cached+filtered **[CAP l.45]** |
| **Post-analysis Validator** (EVA `verify_output` analogue) | Neutral | **Aligned** — `verify_output()` is EVA's **[CAP l.31]** | Aligned — inline warnings, less automated post-check **[CAP l.76]** |
| **Future Generation Engine** | Neutral | Partial (EVA is a generator; code not reusable) | **Best** — zero-code LLM generation model **[CAP l.43]** |

**Alignment reading:** For the subsystems that exist **today** (Confidence Ledger, Evidence Layer, Cardinality Validator, Post-analysis Validator), **B and C both align; A is mostly neutral**. For subsystems that are **future** (Generation Engine, learn-loop/KB), **C is uniquely aligned**.

---

## 4. Recommendation

| Option | Verdict | Why |
|---|---|---|
| **A. Native MCP Hub** | **PARTIAL-GO** | Fixes isolation and has native SWI reach, but inherits the unresolved hourly-token/`auth.json` boundary decision **[DR §6]**. Usable as a *bridge*, not a production target. |
| **B. EVA Library** | **PARTIAL-GO (preferred near-term)** | Addresses *both* standing blockers (isolation + `auth.json`) at the cost of provisioning `ipcat_client` (D1) and dependency approval (D5). Best fit for existing subsystems. |
| **C. Local Structured MCP** | **PARTIAL-GO (preferred long-term)** | Uniquely aligned with all six subsystems incl. future generation + learn-loop, but wholly unbuilt and highest-cost; premature as a first step. |

**No option is GO** (all have an unresolved provisioning or policy prerequisite). **No option is NO-GO** (each is viable under stated conditions).

- **Recommended short-term path:** Pursue **B (EVA-style library)** to answer the outstanding empirical questions (resolve Eliza, obtain the three counts) *once `ipcat_client` is provisioned and dependency approval is granted* — because it clears both blockers with the least policy friction and feeds today's Confidence Ledger / Cardinality Validator directly. If provisioning `ipcat_client` is refused or slow, fall back to **A** with `SWI_DECISION_RECORD.md` §6 **Option C** (dedicated read-only env-var credential, no `auth.json`).
- **Recommended long-term path:** Converge on **C (local structured MCP)** as the production evidence layer — but only *after* Phase-0 (via B or A) has proven counts are extractable and the audio KB is seeded. C is where cardinality authority, caching/filtering, confidence artifacts, and the future generation + learn-loop all land coherently.

---

## 5. Challenge: "camera_dtsi-style local structured MCP is the eventual production target"

**Attempted disproof — four lines of attack:**

1. *"Native MCP is simpler, so it should be the production target."* — **Fails.** A fixes isolation but its hourly-token refresh + `auth.json` boundary is a *standing* CI hazard **[DR §6]**; simplicity at call-time is bought with an unresolved credential-policy problem C avoids. Simplicity ≠ production-fit here.
2. *"EVA library is proven in production, so it's the target."* — **Partially lands, doesn't win.** EVA is production-proven for *auth and structured fetch* **[CAP l.31,35]**, and B is the right *near-term* tool. But EVA's knowledge is hard-coded constants with **no KB, no learn-loop, no cardinality-authority rule** **[CAP l.69,88]** — it cannot host the future subsystems. EVA is a great *stepping stone*, not the ceiling.
3. *"C is unbuilt and expensive (1200+ lines), so it can't be the target."* — **Fails as a disproof.** Cost is a *sequencing* argument (don't build it first), not an *architecture* argument (it's the wrong end state). Effort high ≠ target wrong.
4. *"A future generation engine might not need structured MCP at all."* — **Fails.** camera_dtsi is the *only* prior art that unifies structured evidence + zero-code LLM generation + KB growth **[CAP l.43,47]**; nothing in the evidence suggests a cheaper architecture reaches the same end state.

**Conclusion: the assumption survives — I cannot disprove it.** *Why:* C is the **only** candidate simultaneously aligned with all six Audio BU Skill subsystems, including the two future ones (generation engine, learn-loop/KB) that A and B cannot host **[§3]**. Its costs are real but are *sequencing* costs, not *correctness* costs. The honest caveat: the assumption is proven only as an **end state**, and only **conditional** on (i) `ipcat_client`-class access being provisionable and (ii) the audio KB proving valuable when seeded. It is emphatically **not** the correct *first* step — that is B (or A as fallback).

---

## 6. Exit Criteria (engineering gates — no implementation proposed)

**Before the IPCAT Evidence Layer starts:**
1. A mechanism is chosen (B preferred, A fallback) and the corresponding provisioning is complete — for B: `ipcat_client` importable (D1) + dependency approval (D5); for A: the `SWI_DECISION_RECORD.md` §6 token-refresh/credential-boundary decision is approved.
2. Auth is **env-var-first and boundary-safe** — no `auth.json` read, presence-checked only.
3. A read-only call returns **typed rows** (block/address/size, clock/rate, IRQ) — not prose — verified against one real target.
4. **Eliza is resolved** (alias/id or definitive "absent") and **Nord re-confirmed**, from readable data in the analysis environment.
5. The three counts (`soundwire_master`, `dsp_subsystem_instance`, `lpass_macro_instance`) are **obtained read-only** and each marked directly-countable / indirectly-derivable / unavailable — replacing today's "no count obtained" **[LC §5]**.

**Before DTSI Generation starts (additional):**
6. Evidence Layer has run against ≥2 real targets (Eliza, Nord) producing stable typed evidence + a per-run confidence ledger.
7. An audio KB (`lpass`/`adsp`/`soundwire`/`clocks`) is seeded and validated against those targets **[CAP §7 Phase-0.5]**.
8. Cardinality authority is wired into WP-C from **real** catalog counts (not inert `null`), with `agree`/`disagree_with_authority` verdicts observed on live data.
9. A structural authority (reference-artifact template) and an anti-fallback rule set (no cross-target substitution) are defined **[CAP l.51,101]**.

**Before Automatic code generation starts (additional):**
10. A `verify_output`-style post-generation validator exists (structure presence, TODO scan, provenance integrity) **[CAP l.31]**.
11. Generation is gated to **never emit an unsourced value** — every field cites target-specific evidence or is flagged, never guessed **[CAP l.49-54]**.
12. Explicit scope invariant confirmed: onboarding stays analysis-only; generation is a separate, separately-approved track (Track D) **[CAP l.147,360]**.

Each gate is a *precondition to start*, not a design. None is satisfied today; the nearest-term unlock is gate 1 (mechanism + provisioning) → gates 3–5 (typed rows, Eliza, counts).

---

## 7. Confidentiality & scope compliance

- No `auth.json`, token, or token file accessed. The `auth.json` boundary is treated as a *decision input*, not exercised.
- No credentials printed, no environment dumped, no shell history read. No EVA/camera_dtsi source re-read or copied (repos not in workspace; synthesis from in-repo assessments).
- Nord alias reproduced only from non-confidential in-repo docs; Eliza remains `<ELIZA-SOC>`. No count asserted.
- Investigation only: no code, no implementation, no MCP wiring, no `.mcp.json` change, no dependency install, no Track D. Nothing staged, committed, or pushed.

---

*Phase-0 Mechanism Decision Record: all three options PARTIAL-GO. **Short-term: B (EVA-style library)** — clears both standing blockers, feeds existing subsystems, gated on `ipcat_client` provisioning + approval; **A** as fallback via §6-Option-C creds. **Long-term: C (local structured MCP)** — the assumption that it is the eventual production target survives disproof, conditional and as an end-state only, not the first step. No work proceeds past the §6 exit gates, which are unmet today. Deliverable uncommitted per instruction.*
