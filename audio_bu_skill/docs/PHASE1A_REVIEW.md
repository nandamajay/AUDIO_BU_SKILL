# Phase-1A Probe — Code Review

**Type:** Senior-engineer review. **Review only — no code modified, no fixes implemented, nothing staged or committed.**
**Subject:** `experiments/ipcat_probe/probe.py`, `experiments/ipcat_probe/PHASE1A_README.md`.
**Against:** `docs/PHASE1_IMPLEMENTATION_PLAN.md` (Phase-1A objective/validation/rollback, §4 success criteria).
**Verdict:** Design is sound and the isolation/boundary posture is correct. Two defects should be resolved before the first live run — the read-only guard is bypassable and live-call failures are unhandled — but neither touches the credential boundary. Overall: **approve with required follow-ups.**

---

## 1. Security

| Area | Finding | Severity |
|---|---|---|
| **`auth.json` boundary** | Honored. `FORBIDDEN_PATHS`/`_assert_not_forbidden` guard, and no code path opens `auth.json`. Config comes only from `~/.claude/.mcp.json` and env. Correct. | ✅ |
| **TLS (Path A)** | `verify=True` in `_tls_on_factory` — deliberately *not* copying k-genesis `verify=False` (`mcp_client.py:73`). Correct and the key security win of this probe. | ✅ |
| **TLS (Path B)** | **Not controlled by the probe** — `ipcat_client` manages its own transport/TLS. The README's "TLS always on" claim is only strictly true for Path A. Not a probe defect, but the claim is over-broad. | Note |
| **Token leakage** | Strong. `_mcp_config_present`/`_lib_credential_present` return redacted summaries; the token value is never returned or logged; presence-only checks. Headers are passed to the transport but never printed. | ✅ |
| **Traceback leakage** | On unhandled live-call failure (see §2) the probe crashes with a traceback to stderr. httpx/ipcat tracebacks are **unlikely** to contain the token, but an uncaught exception path is an uncontrolled output surface — better to catch and emit a redacted verdict. | Should fix |
| **Credential presence vs use (Path B)** | `_lib_credential_present` checks `IPCAT_TOKEN`/`QGENIE_TOKEN`/`IPCAT_CLIENT_TOKEN`, but `probe_path_b` never passes a token to `ipcat_client` — it relies on the library reading the env itself. If the library expects a *different* var, presence could report `true` while the call fails. Cosmetic mismatch, not a leak. | Nice to have |

**Security bottom line:** the boundary (`auth.json` untouched, TLS-on for the path we control, no token logging) is correctly implemented. No credential-boundary defect found.

---

## 2. Correctness

**Read-only enforcement — the allow-list is bypassable.**
The invariant is enforced with `assert fn_name in READONLY_LIB_FUNCS` / `assert tool in READONLY_MCP_TOOLS`. Python `assert` statements are **stripped when the interpreter runs under `-O`** (`python -O probe.py …`). Under `-O` the read-only guard silently disappears. For the probe's single most important safety invariant, enforcement must not depend on `assert`. Today the tool name is a hardcoded literal (`"get_chips"`), so the practical exposure is low — but the guard is load-bearing for Phase-1B/1C when tool names become variable. **Must fix before those phases; recommend fixing now** (replace `assert` with an explicit `raise`/guard).

**Live-call failure modes are unhandled.**
Neither `probe_path_a` (`asyncio.run(_run())`) nor `probe_path_b` (`fn()`) wraps the actual call. A `ConnectError`, DNS failure, HTTP error, or — most relevantly — a **TLS certificate verification failure** (the exact outcome `verify=True` is designed to surface) propagates as an unhandled exception: the process exits with a traceback and a non-`{0,2,3}` code. The plan (§4) says failure → exit 3; this path violates that contract. Since a cert/connectivity failure is a *likely* first-live-run outcome, it should be caught and reported as `connected:false … exit 3`. **Should fix (arguably must) before first live run.**

**No request timeout.**
`timeout` is passed through as `None`, so a hung endpoint blocks indefinitely with no diagnostic. A probe should bound its wait. **Should fix before first live run.**

**Chip resolution is substring-based.**
`_resolve_chip_in` does `needle in json.dumps(row).lower()`. Two hazards: (a) **false positive** — a short Nord alias that is a substring of an unrelated chip/field matches; (b) **false negative** — if the enumeration nests chip identifiers under a key other than `chips`/`data`, resolution silently fails and the run degrades to "partial." Acceptable for a first probe, but the verdict it produces is only as trustworthy as the substring match. **Should fix / nice-to-have** (match on a specific identifier field once the response shape is known).

**Mechanism abstraction.** `probe_path_a` returns `{… "config": …}` while `probe_path_b` returns `{… "credential": …}` — divergent keys for the same concept. `main()` tolerates it via `.get()`, so it is correct today, but the asymmetric result schema is a maintainability smell (see §3). No functional defect.

**What is correct:** the `--check` path (no deps, no connection, no token read), the exit-code contract for the *handled* paths (0/2/3 mapping to plan §4), lazy imports (so `--check` and unprovisioned runs never trigger an install), and the guard/error paths — all verified during implementation.

---

## 3. Maintainability

**Phase-1B (Eliza resolution + Nord re-confirm) compatibility — partial.**
- `_resolve_chip_in` returns a **bool**, not the resolved identifier. Phase-1B must capture Eliza's alias/id (or a definitive "absent"), so this function must evolve from "found?" to "resolve → {id | absent}". Plan for that signature change now.
- Eliza's **definitive-absent** requirement (distinguish authoritative not-found from an empty/ambiguous response) has no scaffolding yet — expected (out of 1A scope), but the current bool cannot express it.
- The read-only allow-list is a clean extension point for 1B's resolution tools.

**Phase-1C (counts + cardinality lane) compatibility — good boundaries, additive work.**
- The allow-list holds only `get_chips`/`get_modules`/`swi_search_swi`; 1C's count tools (e.g. QUP/GPIO enumeration) are absent — correct, additive when needed.
- The probe deliberately does **not** import the production cardinality lane (WP-C). That is right for 1A isolation, but 1C requires feeding that lane — so 1C will cross the "no production import" line by design. The review flags this as an *expected* future boundary change, not a flaw: 1C should keep exercising the lane on probe/experiments data only, never inside a shipped run (consistent with the plan).

**General maintainability.**
- Unify the Path A/Path B result dicts into one schema (`mechanism`/`source`/`connected`/`structured`/`resolved`/`note`) so callers and future phases read one shape.
- `swi_search_swi` is in the allow-list but unused this phase — harmless dead entry; remove or document.
- `tuple[bool, str]` annotations assume Python ≥3.9. Fine for the target env; worth a one-line note in the README.

---

## 4. k-genesis Alignment

**Patterns matched (intentionally):**
- Remote MCP transport shape — `StreamableHttpTransport`, URL + `headers` token read from `~/.claude/.mcp.json`, text-parts concatenated then `json.loads` (`mcp_client.py:30-116`).
- `ipcat_client` library use for Path B (`gen_reserved_memory.py:315-351`).
- Token-from-`.mcp.json`, never `auth.json` (`mcp_client.py:13-14`).
- Structured-JSON-as-contract (`_unwrap` → `json.loads`, `mcp_client.py:112-116`).

**Patterns intentionally differing (correctly):**
- **TLS on.** `verify=True` vs k-genesis `verify=False` (`mcp_client.py:73`) — the deliberate safety divergence.
- **Read-only allow-list.** k-genesis has no such guard (it is a generation tool); the probe adds one. Good — though see §2 on `assert`.
- **Presence-check only.** The probe never reads the token value; k-genesis reads and uses it. Boundary-tighter.
- **No `type=="sse"` assertion.** k-genesis rejects non-`sse` configs (`mcp_client.py:53-57`); the probe omits this. Minor robustness gap — a misconfigured entry would fail later rather than with a clear message. Nice-to-have to add.
- **No caching** — both k-genesis and the probe are cache-free here; consistent.

**Alignment verdict:** the probe borrows k-genesis's proven transport/library shape and correctly diverges on exactly the two axes that matter for Audio BU Skill — TLS verification and read-only discipline.

---

## 5. Risks & Classification

### Must fix before first live run
1. **Read-only enforcement via `assert` is bypassable under `python -O`** (`probe.py` Path A/B guard `assert … in READONLY_*`). Replace with an explicit runtime check that raises regardless of optimization flags. The probe's core safety invariant must not evaporate under `-O`.

### Should fix
2. **Unhandled live-call failures** (`asyncio.run(_run())`, `fn()`): catch connection/HTTP/**TLS-verification**/timeout errors and return `connected:false` → exit 3, per plan §4. A cert failure is a probable first-run outcome and must report cleanly, not crash.
3. **No request timeout** (`timeout=None`): bound the wait so a hung endpoint yields a diagnostic, not a hang.
4. **Substring chip matching** (`_resolve_chip_in`): risk of false positive (alias-as-substring) and structure-dependent false negative; tighten to a named-field match once the response shape is confirmed.

### Nice to have
5. **Unify the Path A/Path B result schema** (`config` vs `credential`; add a shared shape) for caller and future-phase clarity.
6. **Evolve `_resolve_chip_in` to return the resolved id** (not just bool) ahead of Phase-1B's Eliza-resolution / definitive-absent need.
7. **Add the k-genesis `type=="sse"` config assertion** for a clear early error on a misconfigured `.mcp.json`.
8. **Remove/annotate the unused `swi_search_swi` allow-list entry.**
9. **Note the Python ≥3.9 requirement** (`tuple[...]` annotations) in the README.
10. **Scope the README "TLS always on" claim to Path A** (Path B TLS is owned by `ipcat_client`).

---

## Summary

The Phase-1A probe meets its objective and — most importantly — gets the security posture right: `auth.json` is never touched, TLS verification is enabled on the path the probe controls, the token is presence-checked but never logged, and the artifact is fully isolated from production (grep-verified). The design is a faithful, safety-hardened adaptation of the k-genesis access shape.

Before the first live run, one defect is **required** (the `assert`-based read-only guard, bypassable under `-O`) and three are **strongly recommended** (unhandled live-call failures incl. TLS errors, missing timeout, substring chip matching). None of these affect the credential boundary; they affect the *robustness and trustworthiness of the verdict* the probe produces. With the Must-fix applied, the probe is safe to run against a real endpoint once the operator provisions a mechanism.

*Review only. No code changed, nothing staged or committed. Phase-0 remains frozen; the probe remains inert until operator provisioning.*
