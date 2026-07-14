# Phase-1A — IPCAT Read-Only Access Probe

**Status:** Phase-1A implemented. **Read-only. Standalone. Non-production. Inert until operator provisions a mechanism.**
**Scope:** Only Phase-1A. Does **not** implement 1B (Eliza resolution), 1C (counts / cardinality wiring), DT generation, worker contracts, or plugin packaging.
**Location:** `audio_bu_skill/experiments/ipcat_probe/` — outside the orchestrator import path; imported by nothing in the Audio BU Skill runtime.
**Reference plan:** `docs/PHASE1_IMPLEMENTATION_PLAN.md` §3 (Phase-1A), §4 (success criteria).

---

## What this is

The smallest possible experiment that validates **structured** IPCAT access from the working environment. It answers exactly three questions and stops:

1. **Can we connect?** to the operator-provisioned mechanism.
2. **Is the response structured?** (typed / JSON) — not prose.
3. **Can Nord be resolved?** in a single read-only enumeration.

Everything else (Eliza, counts, verdicts, generation) is deliberately out of scope.

## Files created

| File | Purpose |
|---|---|
| `experiments/ipcat_probe/probe.py` | The standalone probe. `--check` (presence only, no deps) + `--mechanism A|B --chip <alias>` (live read-only lookup). |
| `experiments/ipcat_probe/PHASE1A_README.md` | This document. |

No production file was created or modified. No dependency was installed.

## Assumptions

- **Provisioning is an operator action** (Gate-1). Until the operator provisions Path B or Path A-Option-C, the probe reports "absent" and exits — by design; it never self-provisions.
- **Path B** = `ipcat_client` importable + an env-var-first token (`IPCAT_TOKEN` / `QGENIE_TOKEN` / `IPCAT_CLIENT_TOKEN`). Mirrors k-genesis `scripts/gen_reserved_memory.py:315-351`.
- **Path A-Option-C** = `~/.claude/.mcp.json` carries an `ipcat-mcp-server` entry with a URL + auth header. Mirrors the k-genesis transport shape (`scripts/mcp_client.py:30-116`) **minus** its `verify=False` (`:73`) — this probe keeps **TLS verification ON**.
- **Nord alias** is supplied at runtime (`--chip` / `IPCAT_PROBE_CHIP`); it is not stored in the repo. `<ELIZA-SOC>` is **not** used here (Phase-1B).
- Mechanism-specific deps (`ipcat_client`, `fastmcp`, `httpx`) are imported **lazily**, so `--check` runs on a bare interpreter and never triggers an install.

## Execution flow

```
python probe.py --check
    → presence-check both mechanisms (no connection, no deps, no token read)
    → exit 0

python probe.py --mechanism {A|B} --chip <NORD_ALIAS>
    ├─ presence-check the chosen mechanism's credential/config
    │     absent            → connected:false                 → exit 3
    ├─ lazy-import mechanism deps
    │     not importable    → connected:false (not provisioned)→ exit 3
    ├─ call ONE read-only enumerate tool (allow-list enforced)
    │     Path A: MCP get_chips over TLS-verified transport
    │     Path B: ipcat_client.get_chips()
    ├─ classify response: structured (dict/list) vs prose
    └─ search enumeration for the Nord alias
          connected + structured + nord_resolved → exit 0  (success)
          connected only                          → exit 2  (partial)
          not connected / boundary-unsafe          → exit 3  (failure)
```

Exit codes map to the plan's §4 success criteria: **0 = success**, **2 = partial success** (connected but prose/unresolved — the "provisioned-but-unusable" risk isolated here by design), **3 = failure**.

## Validation strategy

The probe *is* the validation instrument for Phase-1A. It reports three booleans — `connected`, `structured`, `nord_resolved` — and encodes the verdict in its exit code. To validate after provisioning:

1. `python probe.py --check` → confirm the intended mechanism shows present.
2. `python probe.py --mechanism <A|B> --chip <NORD_ALIAS>` → inspect JSON + exit code.
3. **Pass** (exit 0) advances the operator to Phase-1B planning. **Partial** (exit 2) means data is prose/unresolved — investigate before proceeding. **Fail** (exit 3) means not connected or the only path would breach the boundary — do not proceed.

Self-checks already run (no provisioning, no deps): `--check` → exit 0; missing `--mechanism` → exit 3; unprovisioned Path B → `connected:false`, exit 3; `grep` confirms **no** production module references the probe.

## Safety invariants (enforced in code)

- **TLS verification ALWAYS on** — `httpx.AsyncClient(..., verify=True)`; the k-genesis `verify=False` is explicitly *not* copied.
- **`auth.json` never opened** — `FORBIDDEN_PATHS`/`_assert_not_forbidden` guard; token/config come from `~/.claude/.mcp.json` or env, and the token value is never returned or logged (presence-checked only).
- **Read-only** — a hard allow-list (`READONLY_MCP_TOOLS` / `READONLY_LIB_FUNCS`) of enumerate/lookup names only; any other tool name raises before any call.
- **No write-capable operation. No DT/code generation. No production code modification. No dependency install.**

## Rollback procedure

Fully reversible by deletion — nothing production-facing was touched:

```
rm -rf audio_bu_skill/experiments/ipcat_probe/
```

No config, `.mcp.json`, `auth.json`, orchestrator, skill, runner, or committed artifact was changed. Nothing was staged, committed, or pushed. Removing the directory returns the tree to its pre-Phase-1A state.

---

*Phase-1A implemented as a standalone read-only probe. Inert until operator provisioning. Does not proceed to 1B/1C. Phase-0 remains frozen.*
