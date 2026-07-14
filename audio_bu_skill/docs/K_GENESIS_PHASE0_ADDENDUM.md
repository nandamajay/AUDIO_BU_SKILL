# k-genesis → Phase-0 Addendum

**Type:** Consolidation-only addendum. **No new investigation, no new cloning, no implementation, no code changes, no dependency install, no qgenie/`.mcp.json`/`auth.json` changes, no IPCAT wiring, nothing staged/committed/pushed.**
**Purpose:** Record the k-genesis prior-art finding against the accepted Phase-0 baseline **without changing that baseline.** Phase-0 remains frozen; this document is additive.
**Sources (all previously read this workstream):** `docs/K_GENESIS_PRIOR_ART_ANALYSIS.md` (the spike deliverable; all k-genesis `file:line` citations originate there), `docs/PHASE0_FINALIZATION_PACKAGE.md`, `docs/PHASE0_CLOSEOUT_REVIEW.md`, `docs/PHASE0_MECHANISM_DECISION.md`, `docs/PHASE0_GATE1_CLOSURE.md`.
**Evidence rule honored:** every k-genesis claim cites the `file:line` already captured in `K_GENESIS_PRIOR_ART_ANALYSIS.md`; unproven items are marked **UNVERIFIED**; the presentation deck is not cited.

---

## 1. Executive Summary

- **k-genesis is relevant prior art.** It is a mature Claude Code plugin performing the analysis→generate→validate→commit kernel/devicetree bring-up loop that Audio BU Skill is architecting (`K_GENESIS_PRIOR_ART_ANALYSIS.md §1`).
- **It does not invalidate Phase-0.** No source finding reveals a materially better access mechanism or packaging model that unseats current assumptions; Phase-0 remains engineering-complete (`K_GENESIS_PRIOR_ART_ANALYSIS.md §12–13`).
- **It strengthens the A-Option-C fallback with a concrete, source-backed example.** k-genesis reaches IPCat through a remote HTTP MCP server (`ipcat-mcp-server`, SSE) authenticated by a **static token in `~/.claude/.mcp.json` — never `auth.json`, no hourly OAuth refresh — returning structured JSON** (`scripts/mcp_client.py:30-116`, per `K_GENESIS_PRIOR_ART_ANALYSIS.md §5`). This is a working instance of Phase-0's "dedicated read-only credential + native wiring" sub-variant (`PHASE0_MECHANISM_DECISION.md:84`).
- **It is more relevant to Phase-2 generation-lane design than to Phase-1 access gating.** Its declarative gen-specs, layer dispatch, checkpatch/dtbs_check validation, rollback, and manifests map to the (currently inert) Phase-2 generation lane, not to Phase-1's typed-rows/Eliza/counts deliverables (`K_GENESIS_PRIOR_ART_ANALYSIS.md §12`).

---

## 2. What k-genesis Changes

| Question | Answer | Basis |
|---|---|---|
| Changes Phase-0 conclusion? | **No.** | k-genesis is an instance within the already-catalogued A/B/C taxonomy; nothing invalidates the finalization package (`K_GENESIS_PRIOR_ART_ANALYSIS.md §12`). |
| Changes short-term recommendation (B vs A-Option-C)? | **No — but strengthens A-Option-C as practical.** B remains viable; A-Option-C is now shown buildable and boundary-safe via a static-token remote MCP (`scripts/mcp_client.py:30-81`). |
| Changes long-term recommendation C? | **Strengthens it (does not re-rank).** k-genesis proves the "structured MCP + declarative specs + rules-KB" shape works in production for DT, but via *remote* transport where C is *local* (`K_GENESIS_PRIOR_ART_ANALYSIS.md §12`). |
| Introduces a fourth architecture? | **No.** The `.mcp.json`-token remote MCP is a concrete instantiation of Option A's dedicated-credential sub-variant (plus Option B via `ipcat_client` in `gen_reserved_memory.py:315-351`), not a fourth peer to A/B/C. |
| Changes Phase-1 entry? | **No.** Phase-1's first deliverables (typed rows, Eliza resolution, three counts) and Gate-1 (mechanism chosen + provisioned + boundary-safe creds) are unchanged and still unsatisfied. |
| Affects Phase-2 planning? | **Yes — additively.** Add a k-genesis generation-lane study item to Phase-2 design (§5). |

---

## 3. Reusable Patterns

Source-proven patterns from `K_GENESIS_PRIOR_ART_ANALYSIS.md`, each classified:

| Pattern | Source | Classification |
|---|---|---|
| **Declarative worker contracts** — per-driver `.md` spec run by a generic executor ("this agent never changes") | `agents/add_driver.md:44-47`; `drivers/TEMPLATE.md` | **Adopt later** (Phase-2) |
| **Generic executor / mode-stage routing** — orchestrator per `workspace_tree`, `stages/S*.json` scope with `INCLUDE:Sx` | `skills/bringup/SKILL.md:151-159`; `docs/DESIGN.md:104-108` | **Study further** (Phase-2) |
| **Sub-agent isolation for gather work** — fresh-context sub-agent per phase, scalar-only handoff | `skills/bringup/SKILL.md:66-72` | **Adopt later** (Phase-2) |
| **Manifest / run-audit discipline** — per-phase commit-log JSON + run-report of every substitution | `agents/add_driver.md:766-785`; `golden_rules.md:62-66` | **Study further** (undo-anchor idea is good; `/tmp` volatility a caveat) |
| **Rollback / undo discipline** — phase/driver-scoped reset that refuses foreign commits | `scripts/undo_run.py`; `skills/bringup/SKILL.md:195-219` | **Adopt later** (Phase-2/3) |
| **Golden-rules / anti-fallback rules** — MCP-as-authority, "UNVERIFIED copies are bugs, not placeholders" | `references/golden_rules.md:14-17, 57-66` | **Study further** (Audio WP-A/WP-C already hold the principle; k-genesis shows the operational format) |
| **Boundary-safe MCP token pattern** — structured JSON via a `.mcp.json` static token, no `auth.json` | `scripts/mcp_client.py:30-116` | **Study further** (evidence for A-Option-C; do **not** copy `verify=False`) |
| **DT generation worker model** — hybrid python + external-tool + LLM layer dispatch | `drivers/TEMPLATE.md §4.1–4.7`; `agents/add_driver.md:441-536` | **Study further** (Phase-2 engine reference) |

**Adopt now:** none — this workstream is investigation-only.

---

## 4. Non-Reusable / Unsafe Patterns

- **Do not copy k-genesis code** — its logic is Qualcomm-DT-specific markdown prompt-contracts (`K_GENESIS_PRIOR_ART_ANALYSIS.md §11`).
- **Do not copy `verify=False` TLS behavior** — transport disables TLS verification (`scripts/mcp_client.py:73`); **unsafe**, never copy.
- **Do not copy autonomous commits without a human gate** — commits are autonomous per phase; no pre-commit human gate found (§7, **UNVERIFIED** that one exists) — conflicts with Audio's human-gate invariant.
- **Do not mutate the kernel tree directly for Audio BU Skill Phase-1** — k-genesis writes into the kernel tree and commits; Audio's `artifacts/<run_id>/generated/` staging model is safer (`K_GENESIS_PRIOR_ART_ANALYSIS.md §9`, staging row).
- **Do not treat prompt-as-logic as a sufficient production validator** — generation "functions" are pseudocode in `agents/add_driver.md`, not shipped code (only five `scripts/*.py` are executable); lower determinism/testability than Audio's tested python orchestrator (§6, **UNVERIFIED** whether a compiled generator exists).
- **Do not assume k-genesis MCP covers Audio targets without live verification** — whether `ipcat-mcp-server` serves Nord / `<ELIZA-SOC>` is **UNVERIFIED** (out of scope; would require `.mcp.json` inspection / a live call).

---

## 5. Roadmap Impact (additive only)

- **Phase-0 remains frozen.** No Phase-0 artifact is modified; the finalization package's conclusion stands.
- **Phase-1 remains access / evidence only.** No gate changes; typed rows + Eliza resolution + three counts + boundary-safe credentials remain the entry work.
- **Phase-2 should include a k-genesis generation-lane study** — declarative gen-specs, layer dispatch, checkpatch/`dtbs_check` gating, rollback, and manifests as design references for the (currently inert) generation lane.
- **Long-term local structured MCP (C) remains valid** — k-genesis strengthens the target shape without re-ranking it.
- **Audio BU Skill's confidence/provenance ledger (WP-B) remains a differentiator** — k-genesis has no ledger analog, only FIXME markers + a run-report + an `Assisted-by` trailer (`K_GENESIS_PRIOR_ART_ANALYSIS.md §7`, confidence row).

---

## 6. Operator Decision Impact

- **If the operator prefers Path B** (`ipcat_client` library): k-genesis **does not block it** — indeed k-genesis itself uses `ipcat_client` directly for memory maps (`scripts/gen_reserved_memory.py:315-351`), so it is corroborating evidence that Path B is workable.
- **If the operator prefers Path A-Option-C** (dedicated read-only credential + native MCP wiring): k-genesis provides **useful evidence** that a dedicated-token MCP style works in an adjacent kernel-generation workflow, avoiding the `auth.json`/hourly-refresh problem by using a static `.mcp.json` header token (`scripts/mcp_client.py:30-81`).
- **Either way**, the next real project movement still requires the **operator provisioning decision** (access mechanism + credential model). k-genesis informs that decision; it does not make it. Gate-1 remains unsatisfied.

---

## 7. Commit Readiness

Documents that **should be included in the next Phase-0 documentation commit** (listed for readiness only — **do not stage or commit**):

- `PROJECT_STATUS_EXECUTIVE.md`
- `PHASE0_MECHANISM_DECISION.md`
- `PHASE0_GATE1_CLOSURE.md`
- `PHASE0_CLOSEOUT_REVIEW.md`
- `PHASE0_FINALIZATION_PACKAGE.md`
- `K_GENESIS_PRIOR_ART_ANALYSIS.md`
- `K_GENESIS_PHASE0_ADDENDUM.md`

Nothing has been staged, committed, or pushed by this addendum.

---

## 8. Final Statement

Phase-0 remains complete. k-genesis is additive prior art. Awaiting operator provisioning decision.
