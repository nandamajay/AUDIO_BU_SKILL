# Phase-1A — Commit Readiness Review

**Type:** Commit-readiness review. **Review only — nothing staged, committed, or pushed. No code modified.**
**Subject:** `experiments/ipcat_probe/probe.py`, `experiments/ipcat_probe/PHASE1A_README.md`.
**Against:** `docs/PHASE1_IMPLEMENTATION_PLAN.md` (Phase-1A), `docs/PHASE1A_REVIEW.md` (findings), post-remediation validation.
**Determination:** **READY TO COMMIT.**

---

## 1. MUST FIX closure

`PHASE1A_REVIEW.md` listed exactly **one** Must-fix:

> **#1 — Read-only enforcement via `assert` is bypassable under `python -O`.** Replace with an explicit runtime check that raises regardless of optimization flags.

**Status: RESOLVED — confirmed.**
- `_require_readonly(name, allow_list)` now raises `PermissionError` unconditionally; both call sites (`probe_path_a`, `probe_path_b`) use it instead of `assert`.
- **Verified:** guard raises on a non-allow-listed tool **under `python -O`** (`PASS: read-only guard survives -O`); the only remaining "assert" token in the file is a docstring word at line 89, not a statement; `py_compile` passes; `auth.json` guard and TLS `verify=True` unchanged; production isolation intact (`grep` → no references from `orchestrator/`, `skills/`, `tests/`); exit-code contract (0/2/3) preserved.

No other Must-fix items exist. **MUST FIX fully closed.**

---

## 2. SHOULD FIX evaluation

| # | SHOULD FIX | Classification | Justification |
|---|---|---|---|
| 2 | Unhandled live-call failures (connection/HTTP/**TLS**/timeout not caught → traceback instead of exit 3) | **Can be deferred** | Only reachable on a *live* run against a provisioned endpoint. No mechanism is provisioned (Gate-1 open), so this path is unreachable at commit time. It affects the first-live-run verdict, not the committed artifact's safety or isolation. Must be fixed **before** the first live run — but that is a pre-run gate, not a commit gate. |
| 3 | No request timeout (`timeout=None`) | **Can be deferred** | Same reasoning — only matters on a live connection, which cannot occur until provisioning. Pre-live-run gate, not commit blocker. |
| 4 | Substring chip matching in `_resolve_chip_in` | **Can be deferred** | Affects accuracy of the Nord-resolution verdict on live data only; degrades gracefully to "partial" (exit 2), never to an unsafe state. The plan (§3, 1A) treats a partial as a legitimate, recorded outcome. Refine once the real response shape is known (naturally in Phase-1B). |

**No SHOULD FIX item is a commit blocker.** All three are live-run-only concerns; the committed artifact is inert until provisioning, so none can manifest. They should be tracked as **pre-first-live-run gates** (record them in the README or a follow-up before any live invocation).

**Recommendation:** capture items 2–4 as an explicit "before first live run" checklist so deferral is deliberate, not forgotten.

---

## 3. Milestone completeness

| Phase-1A objective | Status | Evidence |
|---|---|---|
| Standalone probe | ✅ | `experiments/ipcat_probe/probe.py`, self-contained CLI |
| Read-only | ✅ | `_require_readonly` allow-list (enumerate/lookup only), `-O`-safe |
| Production isolated | ✅ | Not imported by `orchestrator/`/`skills/`/`tests/` (grep-verified); lazy imports |
| Supports Path A-Option-C | ✅ | `probe_path_a` — MCP over `StreamableHttpTransport`, TLS on |
| Supports Path B | ✅ | `probe_path_b` — lazy `ipcat_client.get_chips()` |
| Structured-response validation | ✅ | `_is_structured` (dict/list vs prose); question #2 |
| Nord resolution path | ✅ | `_resolve_chip_in` over structured enumeration; question #3 |
| Rollback path | ✅ | `rm -rf experiments/ipcat_probe/`; documented in README |

All eight objectives met. Verdict semantics (0 success / 2 partial / 3 failure) align with plan §4. **Milestone complete.**

---

## 4. Roadmap alignment

- **Phase-0 unchanged** — no Phase-0 artifact modified; baseline frozen. ✅
- **k-genesis conclusions unchanged** — `K_GENESIS_PRIOR_ART_ANALYSIS.md` / `_ADDENDUM.md` untouched; probe consumes (does not alter) their findings. ✅
- **No Phase-2 functionality added** — no generation engine, no worker contracts, no plugin packaging; the probe neither imports nor touches the inert Phase-2 scaffolding. ✅
- **No generation features added** — read-only enumerate/lookup only; no DTSI/driver/kernel/code generation; write-capable tools rejected by the allow-list. ✅

**Roadmap alignment confirmed.**

---

## 5. Commit Recommendation

# READY TO COMMIT

### A. Recommended commit title

```
feat(phase-1a): add read-only IPCAT access probe (experiments, inert)
```

### B. Commit message body

```
Add the Phase-1A IPCAT access probe: the smallest read-only experiment
that validates structured catalog access before any Phase-1B/1C work.

The probe answers exactly three questions — can we connect, is the
response structured, can Nord be resolved — and encodes the verdict in
its exit code (0 success / 2 partial / 3 failure), per
docs/PHASE1_IMPLEMENTATION_PLAN.md §4. It does not resolve Eliza (1B),
obtain counts (1C), or generate anything.

Design:
- Standalone under experiments/ipcat_probe/; imported by no production
  module (orchestrator/skills/tests) — verified.
- Supports both operator-provisioned mechanisms: Path B (ipcat_client)
  and Path A-Option-C (dedicated-token MCP over StreamableHttpTransport).
- Mechanism deps imported lazily, so --check runs with no dependencies
  and never triggers an install.

Safety:
- Read-only allow-list enforced via an explicit runtime guard that
  raises regardless of `python -O` (no assert-based enforcement).
- TLS verification always on (verify=True); the k-genesis reference
  transport's verify=False is deliberately not copied.
- auth.json is never opened; config/token are presence-checked only and
  the token value is never returned or logged.

Inert until the operator provisions a mechanism (Gate-1). Phase-0
remains frozen. Rollback: remove experiments/ipcat_probe/.

Known pre-first-live-run follow-ups (SHOULD FIX, deferred; live-run-only,
unreachable until provisioning): wrap live calls to report connection/
TLS/timeout errors as exit 3; add a request timeout; tighten Nord
substring matching to a named-field match.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

### C. Files that should be included

**Include (the Phase-1A milestone):**
- `experiments/ipcat_probe/probe.py`
- `experiments/ipcat_probe/PHASE1A_README.md`

**Optionally include (supporting docs, if committing the doc set together):**
- `docs/PHASE1_IMPLEMENTATION_PLAN.md`
- `docs/PHASE1A_REVIEW.md`
- `docs/PHASE1A_COMMIT_READINESS.md` (this file)

**Must NOT include:**
- `experiments/ipcat_probe/__pycache__/` (build artifact — `*.pyc`). Not currently git-ignored; exclude explicitly or add an ignore rule so it is never staged.

*Note:* `experiments/` is **not** gitignored (verified), so the probe files are tracked-able as-is. Standing milestone rule applies — commit only on explicit operator instruction. This review does not stage or commit.

---

## Summary

The single MUST FIX is fully resolved and revalidated (including the `-O` case). All three SHOULD FIX items are live-run-only and unreachable while unprovisioned, so none blocks the commit — they are pre-first-live-run gates. All eight Phase-1A objectives are met, and the change adds no Phase-2/generation functionality and alters no Phase-0 or k-genesis artifact.

**READY TO COMMIT** — pending the operator's explicit go, excluding `__pycache__`.

*Review only. Nothing staged, committed, or pushed. Phase-0 remains frozen; the probe remains inert until operator provisioning.*
