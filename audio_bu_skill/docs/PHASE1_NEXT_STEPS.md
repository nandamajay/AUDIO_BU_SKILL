# Phase-1 Next Steps — Post-Commit Status (SHA 91de143)

**Type:** Status analysis only. **No code changes, no commits, no implementation.**
**Anchor:** Phase-1A committed at `91de143` ("feat(phase-1a): add read-only IPCAT access probe (experiments, inert)").
**Sources:** `docs/PHASE1_IMPLEMENTATION_PLAN.md`, `docs/PHASE1A_REVIEW.md`, `docs/PHASE1A_COMMIT_READINESS.md`.

---

## 1. Current Project Status

- **Phase-0:** complete and frozen. Awaiting one operator provisioning decision (access mechanism + credential model). Unchanged by all Phase-1 work.
- **Phase-1A:** **committed** (`91de143`, 5 files, 763 insertions, not pushed). The read-only IPCAT probe exists, is production-isolated (grep-verified), supports both mechanisms (Path B `ipcat_client`, Path A-Option-C dedicated-token MCP), enforces read-only via an `-O`-safe guard, keeps TLS `verify=True`, and never opens `auth.json`.
- **Phase-1A execution:** **not yet run against a live endpoint** — no mechanism is provisioned, so only `--check` and guard/error paths have been exercised. The connect / structured / Nord-resolvable verdict is code-complete but **UNVERIFIED** against real IPCAT.
- **Phase-1B / 1C:** not started (correctly — gated on 1A's live result).
- **Phase-2:** foundation scaffolding remains inert/uncommitted; untouched by Phase-1A.

**One-line status:** the Phase-1A instrument is built and committed but inert; the project is blocked at the same single gate Phase-0 identified — the operator provisioning decision.

---

## 2. Remaining Gates Before Phase-1B Can Begin

Phase-1B (resolve Eliza + re-confirm Nord) cannot start until **all** of the following close, in order:

1. **Gate-1 (provisioning):** operator chooses and provisions a mechanism (Path B or Path A-Option-C) + boundary-safe, env-var-first credentials (presence-verified, never `auth.json`). *Currently OPEN.*
2. **Pre-first-live-run remediation (the deferred SHOULD-FIX gate):** before the probe touches a real endpoint, resolve the three live-run-only items from `PHASE1A_REVIEW.md`:
   - wrap live calls so connection / TLS-verification / timeout errors report `exit 3` instead of crashing;
   - add a request timeout;
   - tighten Nord matching from substring to a named-field match.
   *These are not commit blockers, but they ARE first-live-run gates.*
3. **Phase-1A live PASS:** run the probe post-provisioning and obtain **exit 0** (connected + structured + Nord resolved). A partial (exit 2) or failure (exit 3) must be investigated and cleared before 1B.

Only after gate 3 yields a clean structured Nord resolution does Phase-1B have the proven access + confirmed-target foundation it depends on.

---

## 3. Operator Actions Required

All are operator-owned; none can be performed by automation without breaching the standing boundary:

1. **Decide the access mechanism** — Path B (approve `ipcat_client` as a runtime dependency) **or** Path A-Option-C (dedicated read-only credential + native MCP wiring). *This is the single gating decision.*
2. **Provision credentials** — env-var-first for Path B, or a dedicated-token `~/.claude/.mcp.json` entry for Path A-Option-C. Presence-verifiable; the protected credential file is never read by automation.
3. **(Path B only)** approve/install the `ipcat_client` dependency.
4. **(Path A only)** confirm the token's nature/lifecycle (OAuth-derived vs long-lived service credential) — this determines whether A-Option-C truly avoids the refresh problem (open question from the k-genesis analysis).
5. **Authorize the first live probe run** once provisioned.

---

## 4. Work Performable While Waiting for Provisioning

None of these require a provisioned endpoint, and all are safe under the current constraints:

- **Pre-first-live-run remediation** of the deferred SHOULD-FIX items (§2.2) — error handling, timeout, tightened matching. Fully testable offline via `--check`, guard paths, and mocked responses; makes the probe first-run-ready so provisioning is followed immediately by a clean run.
- **Phase-1B design** — specify the Eliza-resolution contract: how `_resolve_chip_in` evolves from a bool to returning `{id | definitive-absent}`, and how "authoritative not-found" is distinguished from an empty/ambiguous response. No access needed.
- **Phase-1C design** — specify how the three counts (`soundwire_master`, `dsp_subsystem_instance`, `lpass_macro_instance`) will be obtained and classified (directly-countable / indirectly-derivable / unavailable), and how they feed the already-committed WP-C cardinality lane on experiments data.
- **`__pycache__` hygiene** — add an ignore rule so build artifacts can never be staged (flagged at commit time).
- **Offline test scaffolding** — mocked structured/prose fixtures to exercise the probe's structured-vs-prose and resolution logic without a live call.
- **Optional `git push`** of `91de143` — a publishing action; operator's call, not blocked by provisioning.

---

## 5. Blocked vs Not Blocked by Provisioning

| Item | Classification |
|---|---|
| Phase-1A **live run** (connect / structured / Nord verdict) | **Blocked by provisioning** |
| Phase-1B (Eliza resolution + Nord re-confirm) — *execution* | **Blocked by provisioning** (needs 1A live PASS) |
| Phase-1C (counts + cardinality verdicts) — *execution* | **Blocked by provisioning** |
| Access-mechanism + credential decision | **Blocked** (operator-owned, gating) |
| Path-A token lifecycle confirmation | **Blocked** (operator-owned) |
| Pre-first-live-run remediation (error handling / timeout / matching) | **Not blocked** — offline-testable now |
| Phase-1B / 1C **design** (contracts, classification rules) | **Not blocked** |
| Offline test scaffolding / mocked fixtures | **Not blocked** |
| `__pycache__` ignore hygiene | **Not blocked** |
| `git push` of the committed milestone | **Not blocked** (operator publishing choice) |

**Reading:** every *execution* step of Phase-1 is blocked on the one operator provisioning decision; all *preparation* (remediation, design, test scaffolding, hygiene) is unblocked and can proceed now to make provisioning immediately actionable.

---

## Summary

`91de143` completes and freezes the Phase-1A instrument. The project sits at the single Phase-0-identified gate: the operator's access-mechanism + credential decision. Three ordered gates stand before Phase-1B (provisioning → pre-live remediation → live PASS). While waiting, the highest-value unblocked work is the pre-first-live-run remediation plus Phase-1B/1C design — so that the moment provisioning lands, a clean live run and immediate progression are possible.

*Status analysis only. No code changed, nothing committed. Phase-0 frozen; probe inert until operator provisioning.*
