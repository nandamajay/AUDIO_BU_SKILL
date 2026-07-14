# Phase-1A Hardening — Commit Readiness

**Type:** Commit-readiness assessment for the pre-first-live-run hardening pass. **Review only — nothing staged, committed, or pushed by this document.**
**Baseline:** Phase-1A milestone committed at `91de143`. This pass closes the three deferred SHOULD-FIX items from `docs/PHASE1A_REVIEW.md` (§Should fix #2 error handling, #3 timeout, #4 named-field matching).

---

## 1. SHOULD-FIX Closure — Verified

| # | Item | Closure | Evidence |
|---|---|---|---|
| #2 | **Live-call error handling** | ✅ CLOSED | `_classify_error` + `except BaseException` on both Path A and Path B map TLS/DNS/connect/HTTP/MCP/library failures → `connected:false` → exit 3 with a redacted category label. No traceback, no raw message emitted. Tests: `test_no_message_leak`, `test_failure_exception_caught` (secret string absent from output), `test_chain_walk`. |
| #3 | **Request timeout** | ✅ CLOSED | Finite, configurable `PROBE_TIMEOUT_SECONDS` (`IPCAT_PROBE_TIMEOUT`, default 30s). Path A: `asyncio.wait_for` + httpx client timeout; Path B: worker-thread `.result(timeout=...)`. Expiry → clean exit 3 with "timeout after Ns". Tests: `test_timeout_raises`, `test_fast_call_returns`. |
| #4 | **Named-field chip matching** | ✅ CLOSED | `_resolve_chip_in` rewritten: exact (case-insensitive) match on `IDENTIFIER_FIELDS` only, no JSON substring. Returns `{status, resolved, matched_field, candidates}`; >1 distinct row → AMBIGUOUS (never auto-picked). Tests: 8 in `TestNamedFieldResolution` incl. substring-false-positive guard and ambiguity. |

**No SHOULD-FIX items remain open** from `PHASE1A_REVIEW.md`.

---

## 2. Regression Safety — Verified

| Guarantee | Status | Evidence |
|---|---|---|
| `auth.json` never opened | ✅ | `FORBIDDEN_PATHS`/`_assert_not_forbidden` intact; `test_authjson_guard` passes. |
| TLS `verify=True` | ✅ | Only executable `verify=` is `verify=True` (line 303); lines 30–31, 301 are docstring/comment references to k-genesis. Confirmed by grep. |
| Read-only allow-list, `-O`-safe | ✅ | `_require_readonly` unconditional (raises `PermissionError`); no bare `assert` in probe.py (grep confirms none); `test_guard_rejects` passes under `-O`. |
| `python -O` behavior | ✅ | Full suite: `Ran 22 tests ... OK` under both `python` and `python -O`. |
| Production isolation | ✅ | `grep -rn ipcat_probe orchestrator/ skills/ tests/` → no references. |
| Exit-code contract 0/2/3 | ✅ | All live outcomes (success/partial/error/timeout) mapped; `TestExitCodeContract` (5 tests). |
| No installs / config / `.mcp.json` / `auth.json` writes | ✅ | None performed; lazy imports only. |

---

## 3. Phase-1B Compatibility — Verified

| Requirement | Status |
|---|---|
| RESOLVED / ABSENT / AMBIGUOUS model | ✅ `_resolve_chip_in` returns exactly this status vocabulary (+ UNSTRUCTURED for prose). |
| Identifier-based matching | ✅ Matches only named `IDENTIFIER_FIELDS`, exact case-insensitive. |
| Ambiguity detection | ✅ >1 distinct matching row → AMBIGUOUS, never auto-picked. |
| Structured resolution output | ✅ `{status, resolved, matched_field, candidates}` — the documented Phase-1B resolution-contract foundation. |

Matches `docs/PHASE1B_1C_DESIGN.md` resolution contract.

---

## 4. Phase-1C Compatibility — Verified

| Requirement | Status |
|---|---|
| Count-acquisition assumptions valid | ✅ Hardening adds no count logic; read-only enumerate path (`get_chips`) unchanged, remains the acquisition foundation for the three counts. |
| WP-C integration assumptions valid | ✅ No cardinality wiring added; committed WP-C lane (`28f2f07`) untouched; `element_counts` schema (`b151e26`) unchanged. |
| No schema changes required | ✅ Additive `resolution` field only; `nord_resolved` bool and 0/2/3 contract unchanged — no consumer breaks. |

---

## 5. Commit Recommendation

# READY TO COMMIT

The hardening closes all three pre-first-live-run gates, adds a 22-test offline suite (green under `-O`), and preserves every security and boundary guarantee. New risks are all Low/Info and documented (`docs/PHASE1A_HARDENING_REVIEW.md`); residual risks are provisioning-dependent (expected). No commit-blocking item remains.

### A. Commit title

```
feat(phase-1a): harden IPCAT probe — error handling, timeout, named-field matching
```

### B. Commit message

```
feat(phase-1a): harden IPCAT probe — error handling, timeout, named-field matching

Close the three deferred SHOULD-FIX items from docs/PHASE1A_REVIEW.md
(#2 error handling, #3 timeout, #4 named-field matching) — the
pre-first-live-run gates — with no regression to the security or
boundary guarantees. Probe remains read-only, standalone, inert until
operator provisioning.

- Live-call error handling: _classify_error + except BaseException on
  both Path A and Path B map TLS/DNS/connect/HTTP/MCP/library failures
  to the exit-3 contract with a redacted category label. No traceback
  and no raw exception message can escape (token-leak safe).
- Request timeout: finite, configurable PROBE_TIMEOUT_SECONDS
  (IPCAT_PROBE_TIMEOUT, default 30s). Path A via asyncio.wait_for +
  httpx client timeout; Path B via a worker-thread result timeout.
  Expiry maps to a clean exit-3 failure.
- Named-field chip matching: _resolve_chip_in rewritten to exact
  (case-insensitive) matching on named IDENTIFIER_FIELDS only — no JSON
  substring. Returns a structured {status: RESOLVED|ABSENT|AMBIGUOUS|
  UNSTRUCTURED, ...}; >1 distinct matching row is AMBIGUOUS and never
  auto-picked. This is the Phase-1B resolution-contract foundation.

Add test_probe_hardening.py: 22 offline tests (no network, no deps),
green under both python and python -O. Update PHASE1A_README.md.

Preserved: auth.json never opened, TLS verify=True, -O-safe read-only
allow-list, production isolation, the 0/2/3 exit-code contract. No
installs, no config/.mcp.json/auth.json changes, no production imports.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

### C. Exact file list (to commit)

```
audio_bu_skill/experiments/ipcat_probe/probe.py                 (modified)
audio_bu_skill/experiments/ipcat_probe/test_probe_hardening.py  (new)
audio_bu_skill/experiments/ipcat_probe/PHASE1A_README.md        (modified)
audio_bu_skill/docs/PHASE1A_HARDENING_VALIDATION.md             (new)
audio_bu_skill/docs/PHASE1A_HARDENING_REVIEW.md                 (new)
```

Five files, self-contained. `docs/PHASE1_NEXT_STEPS.md` and `docs/PHASE1B_1C_DESIGN.md` are optional companions from adjacent tasks — **include them only if you want them in this commit**; they are not part of the hardening change set and are listed separately below so the commit stays focused.

### D. Files that must NOT be committed

- `audio_bu_skill/experiments/ipcat_probe/__pycache__/` and any `*.pyc` (git-ignored; verified via `git check-ignore`).
- All unrelated working-tree changes: `README.md`, `audio_bu_skill/PLAYBOOK.md`.
- All unrelated untracked docs: `docs/EVA_IPCAT_ACCESS_ANALYSIS.md`, `FRAMEWORK_ARTIFACT_SPECIFICATION.md`, `IMPLEMENTATION_EXECUTION_PLAN.md`, `IPCAT_*`, `K_GENESIS_*`, `NEXT_*`, `PHASE0_*`, `PROJECT_STATUS_EXECUTIVE.md`, `SWI_*`, `phase2_foundation.md`.
- All Phase-2 scaffolding: `orchestrator/codegen/`, `orchestrator/runners/*_generation_runner.py`, `orchestrator/runners/dt_scaffolding_runner.py`, `skills/{audioreach_generation,codec_generation,dt_scaffolding,machine_driver_generation,patch_generation}/`, `tests/test_codegen_*.py`, `tests/test_phase2_skill_registry.py`.
- `prior_art/` and any other untracked path not in section C.

**Staging must be explicit and file-scoped** (`git add <the 5 paths>`) — do **not** use `git add -A`/`git add .`, which would sweep in the unrelated work above.

---

## 6. Verification Log (this assessment)

- `git diff --stat HEAD` on the probe dir: `probe.py` (+199/−32 region), `PHASE1A_README.md` (±10). ✅
- `python test_probe_hardening.py` → `Ran 22 tests ... OK`. ✅
- `python -O test_probe_hardening.py` → `Ran 22 tests ... OK`. ✅
- `git check-ignore …/__pycache__/probe.cpython-310.pyc` → ignored. ✅
- `grep -rn ipcat_probe orchestrator/ skills/ tests/` → no references. ✅
- `grep -n "verify=" probe.py` → only executable occurrence is `verify=True` (line 303). ✅
- `grep -n "^\s*assert " probe.py` → none. ✅

---

*Commit-readiness review only. Nothing staged, committed, or pushed. Phase-0 frozen; probe inert until operator provisioning. Commit to be executed only on explicit operator instruction.*
