# Phase-1 Implementation Plan

**Type:** Planning only. **No code, no implementation, no config changes, no dependency installs, no provisioning, nothing staged/committed. No DTSI/driver/kernel generation. No Generation Engine. No Phase-2 concepts. No qgenie/`.mcp.json`/`auth.json` touched.**
**Objective:** Define the first executable Phase-1 work — the safest, smallest step to obtain (1) structured IPCAT data, (2) Eliza resolution, (3) Nord confirmation, (4) the three required counts — *after* the operator makes the provisioning decision Phase-0 identified.
**Sources:** `docs/PHASE0_FINALIZATION_PACKAGE.md` (§4 Phase-1 deliverables, §6 success criteria), `docs/K_GENESIS_PRIOR_ART_ANALYSIS.md` (access-mechanism evidence, `file:line` citations), `docs/K_GENESIS_PHASE0_ADDENDUM.md` (A-Option-C evidence).

> **Standing gate.** This plan is inert until Gate-1 closes (access mechanism chosen + provisioned + boundary-safe credentials present). Phase-0 remains frozen; nothing here reopens it. The three counts to obtain are `soundwire_master`, `dsp_subsystem_instance`, `lpass_macro_instance` (`PHASE0_FINALIZATION_PACKAGE.md §4`).

---

## 1. Review of Accepted Architecture — Path B vs Path A-Option-C

Phase-0 concluded **short-term B, long-term C, all PARTIAL-GO**, gated on one operator provisioning decision (`PHASE0_FINALIZATION_PACKAGE.md §7`). k-genesis provides fresh source evidence for **both** candidate first steps:

| Dimension | **Path B — `ipcat_client` library** | **Path A-Option-C — dedicated-token MCP** |
|---|---|---|
| Mechanism | In-process Python import; call library functions directly | Remote HTTP MCP server (SSE); JSON-RPC tool calls |
| k-genesis evidence | **Used live** for memory maps: `import ipcat_client.memmap`, `get_memory_maps(chip=…, group="SW")`, `get_address_blocks()` (`gen_reserved_memory.py:315-351, 398-407`) | **Used live** as primary channel: `StreamableHttpTransport` to `ipcat-mcp-server`, token from `~/.claude/.mcp.json` (`mcp_client.py:30-81`) |
| Output shape | Structured Python objects | Structured JSON (`_unwrap()` → `json.loads`, `mcp_client.py:112-116`) |
| Credential model | Env-var-first / config token; **never `auth.json`** (EVA pattern, `PHASE0_MECHANISM_DECISION.md`) | Static token in `.mcp.json` headers; **never `auth.json`**, no hourly OAuth refresh (`mcp_client.py:13-14`) |
| Boundary safety | Safe by design (env-var-first) | Safe *as observed* (static token, not `auth.json`); **UNVERIFIED** whether that token is OAuth-derived or long-lived service credential |
| Dependency cost | Requires approving `ipcat_client` as a runtime dependency (Phase-0 open decision D5) | No new Python dependency beyond an MCP client (k-genesis uses `httpx`+`fastmcp`) |
| Known risk from k-genesis | None specific | Transport sets `verify=False` — TLS off (`mcp_client.py:73`); **do not copy** |
| Coverage for our counts | memmap proven; instance-count / SoundWire coverage **UNVERIFIED** for our targets | `swi_search_swi`/`chipio_get_qups`/`gpio_*`/`memmap` tools present; coverage of Nord/`<ELIZA-SOC>` **UNVERIFIED** |

**Reading of the evidence.** k-genesis does **not** re-rank the two: it corroborates *both*. It uses `ipcat_client` (Path B) *and* a `.mcp.json`-token MCP (A-Option-C) in the same repo. Therefore the smallest first step should be **mechanism-agnostic where possible** and only bind to the mechanism the operator actually provisions. The plan below is written so Phase-1A adapts to whichever of B / A-Option-C is provisioned, without favoring one in code.

---

## 2. The Smallest Implementable Experiment

**Question:** what is the minimum change to obtain one structured response, one chip lookup, and one count, without affecting production code?

**Answer — a standalone, read-only probe script that lives outside the orchestrator import path.**

- **One structured response:** a single read-only query returning typed data (not prose), parsed and printed as a typed object — proving the "structured evidence" gate (`PHASE0_FINALIZATION_PACKAGE.md §4.1`).
- **One chip lookup:** resolve exactly one known target (Nord) to confirm the catalog answers for a real chip we understand.
- **One count:** obtain a single per-element count (the cheapest of the three — chosen at runtime from what the mechanism exposes directly) and classify it directly-countable / indirectly-derivable / unavailable.

**Why this is the minimum, and why it is production-safe:**
- It is a **separate probe artifact** (e.g. a `probe/` or `experiments/` script), **not** wired into `orchestrator/`, `main.py`, or any skill/runner. The shipped `--target/--replay/--rerun/--onboard` flows stay byte-for-byte unchanged (consistent with how Phase-2 foundation was kept inert).
- It is **read-only**: enumerate/query calls only; no write-capable tools invoked (`PHASE0_FINALIZATION_PACKAGE.md §4`, read-only discipline).
- It does **not** touch the cardinality authority lane yet — that wiring is deferred to Phase-1C, after data is proven real.
- Rollback is trivial: **delete the probe file** (no production surface touched).

This maps cleanly to a three-step sequence: **1A prove access + one structured response**, **1B resolve chips (Eliza + Nord)**, **1C obtain + classify the three counts and feed the existing cardinality lane**.

---

## 3. Implementation Plan

> All three sub-phases are **post-provisioning**. None may run until Gate-1 is closed and boundary-safe credentials are presence-verified (never read from `auth.json`).

### Phase-1A — Prove access + one structured response

- **Objective:** Confirm the provisioned mechanism (B or A-Option-C) returns a **structured** (typed/JSON) read-only response for **one** chip lookup, from the working environment, boundary-safely.
- **Inputs:** Provisioned credential (env-var-first for B; `.mcp.json` token for A-Option-C — presence-verified only, not read by us). One known chip identifier (Nord alias, from non-confidential in-repo docs). A minimal read-only tool/function name (e.g. a chip/module enumeration query).
- **Outputs:** A standalone probe script (outside the orchestrator import path) + a captured, redacted structured response saved under a non-tracked `experiments/`/`artifacts/` path. A one-line PASS/FAIL note on: connectivity, structured-vs-prose, boundary-safety.
- **Validation:** Response parses as a typed object / JSON (not prose); no `auth.json` access occurred; TLS verification **on** (do **not** replicate k-genesis `verify=False`, `mcp_client.py:73`); read-only tool only.
- **Rollback:** Delete the probe script; no production code, config, or committed artifact touched.

### Phase-1B — Resolve Eliza + re-confirm Nord

- **Objective:** Resolve `<ELIZA-SOC>` to a definitive catalog alias/id **or** a definitive "absent"; independently re-confirm Nord from the same readable data (`PHASE0_FINALIZATION_PACKAGE.md §4.2`).
- **Inputs:** Phase-1A probe (proven working); candidate Eliza identifier(s); confirmed-working Nord lookup from 1A.
- **Outputs:** A resolution record: Eliza → {alias/id | absent (with the query that proved absence)}, Nord → confirmed identifier. Saved to the same non-tracked experiments path.
- **Validation:** Eliza result is unambiguous (a resolved id *or* an authoritative not-found — not an empty/ambiguous response mistaken for absence); Nord re-confirmed against a second field, not just name match. Any ambiguity is recorded as **UNVERIFIED**, not resolved by guessing (anti-fallback discipline, mirrors `golden_rules.md:57-66`).
- **Rollback:** Discard the resolution record; nothing production-facing changed.

### Phase-1C — Obtain + classify the three counts; feed the existing cardinality lane

- **Objective:** Obtain `soundwire_master`, `dsp_subsystem_instance`, `lpass_macro_instance` read-only for a resolved target; classify each **directly-countable / indirectly-derivable / unavailable**; feed them into the **already-built** cardinality authority lane (WP-C, committed at `28f2f07`) to observe the first live `agree`/`disagree_with_authority` verdicts (`PHASE0_FINALIZATION_PACKAGE.md §4.3–4.4`).
- **Inputs:** Phase-1B resolved target(s); the three count definitions; the existing `element_counts` schema 1.3.0 lane and cardinality module (no schema change — WP-C consumes it as-is).
- **Outputs:** A counts table (per target: value + classification + the query used); a first live cardinality-verdict observation. Still confined to a non-tracked experiments artifact — **not** wired into a production run.
- **Validation:** Each count is either directly countable, derivable via a documented formula, or explicitly marked unavailable (never fabricated); a count that is derivable-but-ambiguous is routed to the framework's `disagree_with_authority`/`not_cross_checkable` verdict rather than asserted; the cardinality lane produces a verdict without error on real data.
- **Rollback:** Discard the experiments artifact; the production cardinality lane is untouched (it was only exercised on probe data, not in a shipped run).

---

## 4. Success Criteria

| Phase | **Success** | **Partial success** | **Failure** |
|---|---|---|---|
| **1A** | One read-only lookup returns a **structured** response for a known chip, boundary-safe, TLS on | Connects but returns prose / partial data (the "provisioned-but-unusable" risk, `PHASE0_CLOSEOUT_REVIEW.md §3`) — caught here, by design | Cannot connect, or only usable path violates the boundary (would require `auth.json`) |
| **1B** | Eliza definitively resolved (id **or** authoritative absent) **and** Nord re-confirmed | One of the two resolves; the other stays genuinely ambiguous (recorded UNVERIFIED) | Neither resolves, or catalog cannot answer chip-identity queries |
| **1C** | All three counts obtained + classified; cardinality lane emits a live verdict | Some counts obtained/derivable, others unavailable but correctly classified; lane runs on the available subset | No count obtainable/derivable, or the lane errors on real data |

**Cross-phase gate:** a phase's *failure* blocks the next phase; a phase's *partial success* may proceed with the ambiguity explicitly recorded (never silently filled).

---

## 5. Challenge — Is the sequence wrong?

**Attempt to disprove 1A → 1B → 1C:**

1. *"Resolve chips (1B) before proving access (1A)."* — **Rejected.** Chip resolution *is* a structured lookup; you cannot resolve Eliza without first proving the mechanism returns structured data at all. 1A is the strictly smaller precondition.
2. *"Get counts (1C) directly, skip resolution (1B)."* — **Rejected.** Counts are per-target; without a confirmed target id, a count is unattributable and a wrong-chip count would produce a false cardinality verdict. Resolution must precede counts.
3. *"Do all three in one probe to save round-trips."* — **Rejected.** Collapsing them loses the diagnostic value of the staged gates: the "provisioned-but-unusable / prose-not-typed" failure (`PHASE0_CLOSEOUT_REVIEW.md §3`) is exactly what 1A is designed to isolate. A monolithic probe would surface it tangled with resolution/count failures.
4. *"Pick the mechanism (B vs A-Option-C) first, then plan."* — **Considered; deferred to the operator.** The plan is deliberately mechanism-agnostic through 1A so it survives whichever the operator provisions. Binding the sequence to one mechanism now would pre-empt the single gating decision Phase-0 reserved for the operator.
5. *"Wire the cardinality lane in 1A for end-to-end proof."* — **Rejected.** Feeding unproven data into the production lane risks a misleading first verdict. The lane is fed only in 1C, after data is confirmed real — keeping the production surface untouched until the last step.

**Conclusion:** the sequence is minimal and correctly ordered. 1A is the smallest precondition; 1B is a prerequisite of 1C; each gate isolates a distinct, pre-identified failure mode. **No better sequence found.** The only genuinely open choice — B vs A-Option-C — is intentionally left to the operator, and the plan is written to not depend on it before 1A.

---

## Recommended first implementation after operator provisioning

**Phase-1A: a standalone, read-only probe script — outside the orchestrator import path — that performs one boundary-safe chip lookup (Nord) via the provisioned mechanism and confirms the response is structured, with TLS verification enabled and no `auth.json` access.** Nothing else is implemented until 1A passes. If the operator provisions **Path B**, the probe imports `ipcat_client` and calls one read-only function (as k-genesis does in `gen_reserved_memory.py:315-351`); if **Path A-Option-C**, it opens one MCP session with TLS **on** and calls one read-only tool (the k-genesis transport shape in `mcp_client.py:30-116`, **minus** `verify=False`). Either way it touches no production code, installs nothing beyond what provisioning provided, and rolls back by file deletion.

---

*Phase-1 Implementation Plan — planning only; no code, config, dependencies, provisioning, or commits. Inert until Gate-1 closes. Phase-0 remains frozen. Awaiting operator provisioning decision.*
