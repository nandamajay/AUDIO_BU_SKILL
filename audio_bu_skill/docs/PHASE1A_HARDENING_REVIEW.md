# Phase-1A Hardening — Focused Review

**Type:** Focused review of **only** the hardening changes (not a re-review of the whole probe). **Review only — no further code changes, no commit, no stage.**
**Scope reviewed:** `_classify_error`, the per-path try/except + timeout wrapping, `_call_with_timeout`, the rewritten `_resolve_chip_in` (+ `_iter_rows`/`_field_values`), `PROBE_TIMEOUT_SECONDS`/`IDENTIFIER_FIELDS` constants, and `test_probe_hardening.py`.
**Verdict:** The three pre-first-live-run gates are correctly closed with no regression to the security/boundary guarantees. A few **residual** and **nice-to-have** items remain, none blocking. No new commit-blocking risk introduced.

---

## 1. New Risks (introduced by these changes)

| # | Risk | Severity | Assessment |
|---|---|---|---|
| N1 | **`except BaseException`** in both live paths is very broad — could mask `KeyboardInterrupt`/`SystemExit`. | Low | Deliberate: the probe must convert *any* live-call outcome into the exit-code contract with no traceback. Consequence is limited to a manual Ctrl-C being reported as a failure category rather than interrupting — acceptable for a short read-only probe. Documented in code. Could narrow to `Exception` if interruptibility is preferred (nice-to-have). |
| N2 | **Path B timeout abandons a worker thread** (daemon) rather than killing it — the blocked call keeps running until the process exits. | Low | Inherent to Python threads (no safe force-kill). For a read-only, short-lived probe this is harmless; noted in the `_call_with_timeout` docstring. |
| N3 | **`_classify_error` relies on exception type-name substrings** — a novel transport exception could fall through to the generic `call_failed`. | Low | Fail-safe by design: unknown → `call_failed`, still exit 3, still redacted. Categorization is advisory; correctness of the *verdict* does not depend on the label. |
| N4 | **`resolution` object added to the result payload** — a new output field. | Info | Additive; the `nord_resolved` bool and 0/2/3 contract are unchanged, so no consumer breaks. Intended Phase-1B foundation. |

No new risk rises above **Low**. None touches the credential boundary, TLS, or read-only enforcement.

---

## 2. Residual Risks (pre-existing, unchanged by this work)

| # | Residual | Status |
|---|---|---|
| R1 | **Live path unverified against a real endpoint.** All new handling is exercised via fakes/units; behavior against the actual `ipcat-mcp-server` / `ipcat_client` is still UNVERIFIED until provisioning. | Expected — this is the operator's first live run. The hardening ensures that run fails *cleanly* if it fails. |
| R2 | **`IDENTIFIER_FIELDS` is a best-guess field set.** If the real catalog names its identifier field something outside the list, a valid chip could read as ABSENT. | Mitigated, not eliminated: the list is central and easily extended once the real schema is seen (Phase-1B). Structured `status` makes an unexpected ABSENT visible rather than silent. |
| R3 | **Path B TLS is owned by `ipcat_client`**, not the probe. | Documented; `verify=True` guarantee is scoped to Path A (the transport we construct). |
| R4 | **Result-schema divergence** between Path A (`config`) and Path B (`credential`) keys. | Pre-existing; still tolerated by `main()`. Nice-to-have to unify. |

---

## 3. Remaining Nice-to-Have Items

1. **Unify the Path A / Path B result schema** (shared keys) — carried over from the original review; not required for a live run.
2. **Add the k-genesis `type=="sse"` config assertion** for a clearer early error on a misconfigured `.mcp.json`.
3. **Narrow `except BaseException` → `Exception`** if preserving Ctrl-C interruptibility is desired.
4. **Make `IDENTIFIER_FIELDS` extensible via env/config** so the field set can be tuned at first live run without a code edit.
5. **Remove/annotate the unused `swi_search_swi` allow-list entry** (still unused this phase).

None of these blocks the first live run; all are optional polish.

---

## 4. Regression Check (guarantees preserved)

| Guarantee | Result |
|---|---|
| `auth.json` never opened | ✅ guard intact + unit test |
| TLS `verify=True` | ✅ only executable `verify=` is True (line 303) |
| Read-only allow-list, `-O`-safe | ✅ `_require_readonly` unchanged; unit test passes under `-O` |
| No token leakage into output | ✅ `_classify_error` type-names only; leak tests pass |
| Production isolation | ✅ grep: no references from `orchestrator/`/`skills/`/`tests/` |
| Exit-code contract 0/2/3 | ✅ all live outcomes now mapped; verified |
| No installs / config / `.mcp.json` / commit | ✅ none performed |

---

## 5. SHOULD-FIX Closure Confirmation

- **#2 Live-call error handling** — CLOSED. TLS/DNS/connect/HTTP/MCP/library failures caught on both paths, mapped to exit 3, redacted (no traceback, no message leak).
- **#3 Request timeout** — CLOSED. Finite, configurable (`IPCAT_PROBE_TIMEOUT`, default 30s), enforced on both paths, mapped to a clean failure.
- **#4 Named-field chip matching** — CLOSED. Substring matching replaced by exact named-field matching with deterministic selection and ambiguity detection; returns the structured resolution the Phase-1B contract requires.

**No SHOULD-FIX items remain open** from `PHASE1A_REVIEW.md`.

---

## Conclusion

The hardening closes all three pre-first-live-run gates cleanly, adds a 22-test offline suite (green under `-O`), and preserves every security and boundary guarantee. New risks are all Low and documented; residual risks are provisioning-dependent (expected) or nice-to-have. The probe is now **first-live-run-ready** pending operator provisioning — no traceback can escape, no call can hang unbounded, and chip resolution is deterministic and ambiguity-aware.

*Review only. No code changed by this review, nothing staged or committed. Phase-0 frozen; probe inert until provisioning.*
