# Phase-1A Hardening — Validation

**Type:** Validation record for the pre-first-live-run hardening. **No commit, no stage, no push. Changes confined to `experiments/ipcat_probe/`.**
**Baseline:** Phase-1A committed at `91de143`. This work closes the three deferred SHOULD-FIX items from `docs/PHASE1A_REVIEW.md` (§Should fix #2, #3, #4).
**Files touched:** `experiments/ipcat_probe/probe.py` (hardened), `experiments/ipcat_probe/test_probe_hardening.py` (new), `experiments/ipcat_probe/PHASE1A_README.md` (updated). No production file touched.

---

## 1. Before / After Behavior

| Concern | Before (`91de143`) | After (hardening) |
|---|---|---|
| **Live-call failure** | `asyncio.run(_run())` / `fn()` uncaught → traceback to stderr, non-`{0,2,3}` exit; possible message content in traceback | Caught for both paths; mapped to `connected:false` → **exit 3** with a **redacted category** (`tls_verification_failed` / `dns_failure` / `connection_failed` / `http_error` / `mcp_error` / `timeout` / `call_failed`). Raw message never emitted. |
| **TLS verification failure** | Propagated as an unhandled exception | Categorized `tls_verification_failed`, exit 3. TLS still `verify=True` — failures are surfaced cleanly, not silenced. |
| **Timeout** | `timeout=None` → could hang indefinitely | Finite `PROBE_TIMEOUT_SECONDS` (env `IPCAT_PROBE_TIMEOUT`, default 30s). Path A: `asyncio.wait_for` + httpx client timeout; Path B: worker-thread `.result(timeout=...)`. Expiry → "timeout after Ns", exit 3. |
| **Chip matching** | `needle in json.dumps(row)` — JSON substring; false-positive/false-negative prone; returned bare `bool` | Exact (case-insensitive) match on named `IDENTIFIER_FIELDS` only; returns structured `{status, resolved, matched_field, candidates}`; ambiguity (>1 distinct row) → `AMBIGUOUS`, never auto-picked. |
| **Result payload** | `nord_resolved: bool` | `nord_resolved: bool` **plus** a `resolution` object (the Phase-1B foundation). Exit-code contract unchanged. |

Preserved unchanged: `--check` (no deps, no connection), lazy imports, `verify=True`, `auth.json` guard, `_require_readonly` (`-O`-safe), the 0/2/3 exit semantics.

---

## 2. Test Coverage

New offline suite `test_probe_hardening.py` — **22 tests, no network, no deps, passes under both `python` and `python -O`:**

- **Named-field resolution (8):** exact id match; substring **no longer** false-positives (`"775"` vs `sa8775p` → ABSENT); value in a non-identifier field → ABSENT; alias-list match; ambiguity detected (2 candidates); same row matched via 2 fields → not ambiguous; prose → UNSTRUCTURED; list-root enumeration.
- **Error classification (5):** TLS / DNS / connect categories; **no message leak** (`Bearer SECRET_TOKEN_123` absent from label); exception-chain walk surfaces both inner and outer types.
- **Timeout (2):** slow callable raises `TimeoutError`; fast callable returns.
- **Exit-code contract (5):** via an injected fake `ipcat_client` — success (connected+structured+resolved), partial-unresolved, partial-prose, exception caught (and secret `LEAKME` not in note), no-credential → not connected.
- **Guards still enforced (2):** `_require_readonly` rejects a non-allow-listed tool; `_assert_not_forbidden` rejects `auth.json`.

Result: `Ran 22 tests ... OK` (normal) and `Ran 22 tests ... OK` (`-O`).

---

## 3. Exit-Code Verification

| Scenario | Expected | Verified |
|---|---|---|
| `--check` (normal & `-O`) | 0 | ✅ 0 / 0 |
| No `--mechanism` | 3 | ✅ 3 |
| Unprovisioned Path B | 3 | ✅ 3 |
| Unprovisioned Path A | 3 | ✅ 3 |
| Live success (fake client) | connected+structured+resolved (→0) | ✅ (unit) |
| Live partial (unresolved / prose) | connected only (→2) | ✅ (unit) |
| Live failure (exception/timeout) | not connected (→3), redacted | ✅ (unit) |

The 0/2/3 contract from `PHASE1_IMPLEMENTATION_PLAN.md` §4 now covers **all** live outcomes, including the previously-uncaught error and timeout paths.

---

## 4. Boundary Verification

- **`auth.json`:** never opened — guard intact; `test_authjson_guard` passes; config read only from `~/.claude/.mcp.json` and env.
- **TLS:** only executable `verify=` is `verify=True` (line 303); the two `verify=False` occurrences are docstring/comment references to k-genesis. Confirmed by grep.
- **Read-only:** `_require_readonly` unchanged and unconditional (`-O`-safe); `test_guard_rejects` passes; no new tool names added to the allow-list.
- **Token leakage:** `_classify_error` emits only exception **type names** + a coarse category, never the raw message; `test_no_message_leak` / `test_failure_exception_caught` confirm a bearer-token-like string does not appear in output.
- **Production isolation:** `grep -rn ipcat_probe orchestrator/ skills/ tests/` → no references. Still imported by nothing in production.
- **No installs / no config changes / no `.mcp.json` / no staging / no commit.**

---

## 5. Success-Criteria Mapping

| Criterion | Status |
|---|---|
| No remaining SHOULD FIX items from `PHASE1A_REVIEW.md` | ✅ #2 (error handling), #3 (timeout), #4 (named-field) all closed |
| `auth.json` boundary preserved | ✅ |
| TLS verification preserved | ✅ `verify=True` |
| Read-only enforcement preserved | ✅ `-O`-safe guard, allow-list unchanged |
| Phase-1B design assumptions satisfied | ✅ named-field matching + structured `{status: RESOLVED/ABSENT/AMBIGUOUS}` = the resolution-contract foundation |
| Phase-1C design assumptions satisfied | ✅ deterministic, bounded, error-safe read-only access = the acquisition foundation; no cardinality wiring added |

---

*Validation only. No commit, no stage, no push. Phase-0 frozen; probe remains inert until operator provisioning.*
