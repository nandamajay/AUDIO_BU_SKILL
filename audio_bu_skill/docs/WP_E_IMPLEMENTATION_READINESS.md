# WP-E Implementation Readiness Review

| Field | Value |
| --- | --- |
| **Title** | WP-E Implementation Readiness Review |
| **Status** | Preflight Complete (2026-07-20) |
| **Phase** | Phase-3A |
| **Prerequisite** | Checkpoint E1 complete; design approved for implementation |
| **Depends On** | WP_E_FACT_REGISTRY_DESIGN.md, WP_E_DESIGN_REVIEW.md |
| **Next Step** | Documentation checkpoint commit (C0), then implementation |

---

## 1. File Status Verification

### Design Documents — UNTRACKED (confirmed)

Both files are present and untracked in the `master` branch:

```
Untracked files:
  audio_bu_skill/docs/WP_E_DESIGN_REVIEW.md
  audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md
```

### Recommended Documentation Checkpoint Commit (C0)

**Do NOT commit automatically. Recommended commands:**

```bash
git add audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md \
        audio_bu_skill/docs/WP_E_DESIGN_REVIEW.md
git commit -m "docs(wp-e): add approved fact registry design + design review

WP_E_FACT_REGISTRY_DESIGN.md — canonical design spec, status
'Design Approved For Implementation (2026-07-20)'.
WP_E_DESIGN_REVIEW.md — review findings and resolution history.

B-1..B-4 blockers resolved at Checkpoint E0.
C-1..C-5 recommendations resolved at Checkpoint E1.
D-1..D-3 remain open (non-blocking).
Implementation authorised from this state.

No code, no behavior change, no test modifications."
```

**Rationale:** These documents are the authoritative spec for all implementation
work. Committing them before code begins creates a clean diff boundary —
reviewers can verify the implementation against a committed spec rather than an
ephemeral file.

---

## 2. Implementation Scope Verification

All files are **NEW** — nothing existing is modified:

| Module | Path | Status |
|--------|------|--------|
| `__init__.py` | `audio_bu_skill/orchestrator/fact_registry/__init__.py` | New file |
| `models.py` | `audio_bu_skill/orchestrator/fact_registry/models.py` | New file |
| `source_refs.py` | `audio_bu_skill/orchestrator/fact_registry/source_refs.py` | New file |
| `review.py` | `audio_bu_skill/orchestrator/fact_registry/review.py` | New file |
| `errors.py` | `audio_bu_skill/orchestrator/fact_registry/errors.py` | New file |
| `constants.py` | `audio_bu_skill/orchestrator/fact_registry/constants.py` | New file |
| `hash.py` | `audio_bu_skill/orchestrator/fact_registry/hash.py` | New file |
| `locking.py` | `audio_bu_skill/orchestrator/fact_registry/locking.py` | New file |
| `store.py` | `audio_bu_skill/orchestrator/fact_registry/store.py` | New file |

Plus:
- `audio_bu_skill/state/fact_registry/README.md` — New
- `audio_bu_skill/state/fact_registry/.gitignore` — New
- 4 test files + 5 fixtures under `audio_bu_skill/tests/` — All new

**Confirmed: zero modification to any existing file.**

---

## 3. Implementation Requirements Summary

### From WP_E_FACT_REGISTRY_DESIGN.md:

1. **Append-only JSONL store** — one file per target at `state/fact_registry/<target>.json`
2. **Integrity via sidecar hash** — `<target>.registry.hash` with sha256
3. **POSIX advisory locking** — `<target>.lock` for concurrent writer safety
4. **Immutable Registry class** — `load()` → get/iter; `append_provenance()` → new Registry
5. **RegistryStatus enum** with precedence: CORRUPT > UNSUPPORTED_SCHEMA > HASH_MISMATCH > PARTIAL > OK
6. **Tagged-union SourceRef** — 7 variants, parsed by `kind` discriminator
7. **ReviewRecord** — required for MANUAL facts, confidence cap without evidence
8. **Revocation** — `is_revocation: bool` on FactProvenance; `get()` returns None
9. **Provenance chain cap** — MAX_PROVENANCE_CHAIN_LEN = 100
10. **Writer flow** — stale-tmp cleanup → lock → read → mutate → serialize → sidecar-first → JSONL rename → dir fsync → unlock
11. **Reader retry** — 50ms single retry on hash mismatch
12. **Schema versioning** — `1.0.0`; MINOR-refuse policy
13. **Import-graph isolation** — no import from runners/main/targets

### From WP_E_DESIGN_REVIEW.md (resolved items):

- **B-1:** RegistryStatus enum with precedence ✓
- **B-2:** Immutable Registry; append_provenance returns fresh instance ✓
- **B-3:** 1-retry, 50ms, read-only; persistent mismatch → HASH_MISMATCH ✓
- **B-4:** `is_revocation: bool` field, not a string sentinel ✓
- **C-1:** Sidecar-first write ordering ✓
- **C-2:** MAX_PROVENANCE_CHAIN_LEN = 100; MAJOR bump to raise ✓
- **C-3:** `KernelRef.kernel_ref_kind: Literal["dts", "bindings"]` ✓
- **C-4:** Comments/blanks survive load, not save ✓
- **C-5:** Stale-tmp cleanup step 0 with STALE_TMP_TTL_SEC=60 ✓

---

## 4. Work Breakdown Structure

### WP-E1: Models (`models.py`)

**Purpose:** Core data model — FactKey, FactValue, FactProvenance with all
validation invariants.

**Files:** `audio_bu_skill/orchestrator/fact_registry/models.py`

**Dependencies:** WP-D public surface (`Authority`, `AuthorityClass`, `Domain`);
WP-E errors, constants, source_refs, review modules.

**Test IDs:** T-E1 through T-E10

**Commit boundary:** Committed with errors.py + constants.py + source_refs.py +
review.py as a single atomic unit (models depend on all of these).

---

### WP-E2: SourceRef system (`source_refs.py`)

**Purpose:** 7 tagged-union dataclass variants + `parse()` dispatcher.

**Files:** `audio_bu_skill/orchestrator/fact_registry/source_refs.py`

**Dependencies:** None (standalone frozen dataclasses)

**Test IDs:** T-E29 through T-E33

**Commit boundary:** Part of models commit (models.py imports SourceRef types).

---

### WP-E3: Review system (`review.py`)

**Purpose:** ReviewDecision enum, ReviewRecord dataclass with validation.

**Files:** `audio_bu_skill/orchestrator/fact_registry/review.py`

**Dependencies:** None (standalone)

**Test IDs:** T-E23 through T-E28

**Commit boundary:** Part of models commit (FactValue.review field depends on this).

---

### WP-E4: RegistryStatus + errors + constants

**Purpose:** Enum, exception hierarchy, schema version constant, path helpers,
MAX_PROVENANCE_CHAIN_LEN, STALE_TMP_TTL_SEC.

**Files:**
- `audio_bu_skill/orchestrator/fact_registry/errors.py`
- `audio_bu_skill/orchestrator/fact_registry/constants.py`

**Dependencies:** None

**Test IDs:** Referenced by T-E11..T-E22 (status enum tested via store)

**Commit boundary:** Part of models commit.

---

### WP-E5: Hash subsystem (`hash.py`)

**Purpose:** Compute sha256 of a file's bytes; write/read sidecar; verify match.

**Files:** `audio_bu_skill/orchestrator/fact_registry/hash.py`

**Dependencies:** constants (for path helpers)

**Test IDs:** T-E14, T-E14b, T-E14c (tested via store)

**Commit boundary:** Part of store commit (or combined).

---

### WP-E6: Locking subsystem (`locking.py`)

**Purpose:** `registry_write_lock()` context manager using
`fcntl.flock(LOCK_EX)` with timeout.

**Files:** `audio_bu_skill/orchestrator/fact_registry/locking.py`

**Dependencies:** constants, errors

**Test IDs:** T-E18

**Commit boundary:** Part of store commit.

---

### WP-E7: Registry/store (`store.py` + `__init__.py`)

**Purpose:** Registry class (load, get, iter_facts, append_provenance) plus the
full writer flow with sidecar-first ordering, stale-tmp cleanup, and retry.

**Files:**
- `audio_bu_skill/orchestrator/fact_registry/store.py`
- `audio_bu_skill/orchestrator/fact_registry/__init__.py`

**Dependencies:** All other WP-E modules

**Test IDs:** T-E11 through T-E22 (T-E22c, T-E22d)

**Commit boundary:** Second commit — models commit must land first.

---

### WP-E8: Test suite

**Purpose:** 33+ tests across 4 test files + 5 fixture files + state directory
scaffold.

**Files:**
- `audio_bu_skill/tests/test_fact_registry_models.py`
- `audio_bu_skill/tests/test_fact_registry_store.py`
- `audio_bu_skill/tests/test_fact_registry_review.py`
- `audio_bu_skill/tests/test_fact_registry_source_refs.py`
- `audio_bu_skill/tests/fixtures/fact_registry/golden_registry_v1.jsonl`
- `audio_bu_skill/tests/fixtures/fact_registry/malformed_missing_review.jsonl`
- `audio_bu_skill/tests/fixtures/fact_registry/conflict_chain.jsonl`
- `audio_bu_skill/tests/fixtures/fact_registry/stale_manual.jsonl`
- `audio_bu_skill/tests/fixtures/fact_registry/newer_schema.jsonl`
- `audio_bu_skill/state/fact_registry/README.md`
- `audio_bu_skill/state/fact_registry/.gitignore`

**Dependencies:** All WP-E modules

**Test IDs:** T-E1..T-E33 (all)

**Commit boundary:** Same commit as store (tests validate the code).

---

### WP-E9: Import-graph protection

**Purpose:** A test asserting `import audio_bu_skill.orchestrator.fact_registry`
does not pull in any runner, main.py, or targets module.

**Files:** Included in `test_fact_registry_store.py` (or a dedicated
`test_fact_registry_isolation.py`)

**Dependencies:** All WP-E modules (it imports them)

**Test IDs:** §15 exit criterion 6/7/8

**Commit boundary:** Part of test commit.

---

## 5. Commit Plan

| Commit | Content | Gate |
|--------|---------|------|
| **C0** | Documentation checkpoint (design + review docs) | Manual approval |
| **C1** | All WP-E source modules (errors, constants, source_refs, review, models, hash, locking, store, `__init__.py`) + state dir scaffold + all tests + fixtures | Full 38-module test suite green |

**Proposed C1 commit message:**

```
feat(wp-e): fact registry — append-only store with MANUAL-fact discipline

Implements the approved WP-E design (WP_E_FACT_REGISTRY_DESIGN.md):
- FactKey/FactValue/FactProvenance data model with validation
- 7-variant tagged-union SourceRef system
- ReviewRecord with confidence-cap enforcement
- Immutable Registry class (load/get/iter/append_provenance)
- POSIX advisory locking + sidecar-first atomic writes
- RegistryStatus enum with B-3 retry policy
- 33 tests (T-E1..T-E33) covering models, store, review, source_refs

Advisory-only: no runner/main/target imports. Zero behavior change
on existing pipeline.
```

---

## 6. Design Decision Cross-check

| Decision | Implementation Mapping | Ambiguity? |
|----------|----------------------|------------|
| **B-1** RegistryStatus | `constants.py` or top of `store.py`: 6-variant `str, Enum` | None |
| **B-2** Immutable Registry | `@dataclass(frozen=True)` on Registry; `append_provenance` returns new instance | None |
| **B-3** Retry policy | In `store.py` `load()`: single 50ms sleep + re-read on hash mismatch | None |
| **B-4** Revocation model | `FactProvenance.is_revocation: bool`; `get()` checks chain top | None |
| **C-1** Sidecar-first | Writer steps: serialize → hash tmp → rename hash → rename JSONL → dir fsync | None |
| **C-2** Chain cap | `MAX_PROVENANCE_CHAIN_LEN = 100` in constants; checked in `append_provenance` | None |
| **C-3** KernelRef discriminator | `kernel_ref_kind: Literal["dts", "bindings"]` field | None |
| **C-4** Comment handling | Reader skips `#`/blank; writer never emits them; not preserved on save | None |
| **C-5** Stale-tmp cleanup | Step 0: glob + mtime check + unlink before lock | None |

**Unresolved but non-blocking (D-items):**

- D-1: `query_id` generation rule for IPCATLiveRef — implement as `str` field,
  no fallback generation in Phase-3A (no live IPCAT acquisition happens)
- D-2: Sort-on-write note — implement sort; the git-diff reorder is expected
  behavior
- D-3: Module docstring cross-ref target — reference
  `WP_E_FACT_REGISTRY_DESIGN.md` (this is canonical)

**One minor implementation question (OQ-4):** `ticket_url` validation. Design
says "any URL-shaped string." Implementation: validate via simple
`urllib.parse.urlparse` check (scheme + netloc present) — not a regex lock to
any tracker.

---

## 7. Exclusion Verification

| Exclusion | Verified |
|-----------|----------|
| No runner modifications | `audio_bu_skill/orchestrator/runners/` untouched |
| No main.py modifications | `audio_bu_skill/orchestrator/main.py` untouched |
| No target modifications | `audio_bu_skill/targets/` untouched |
| No case.py changes | Not touched |
| No case.generated.py changes | Not touched |
| No promotion-path changes | Not in scope |
| No onboarding-flow changes | Not in scope |
| No IPCAT acquisition work | WP-E provides substrate only |
| No WP-F work | Coverage engine is separate WP |
| No report-generation work | WP-G is separate WP |

---

## 8. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Import-graph contamination | HIGH | Dedicated isolation test; WP-E imports only `fact_requirements` public surface |
| Accidental `case.py` promotion | HIGH | No test writes to `state/fact_registry/<real-target>.json`; tempdir only |
| `fcntl.flock` portability | LOW | Phase-3A is Linux-only; NFS explicitly out of scope |
| Schema evolution pressure | MEDIUM | Ship `1.0.0`; SUPPORTED_SCHEMA_VERSIONS frozenset gates loader |
| Test time regression | LOW | Target < 500ms; tempdir fixtures; no subprocess calls |

---

## 9. Recommended First Coding Package

**Start with leaf modules (zero internal deps):**

1. `errors.py` — 3 exception classes (~15 lines)
2. `constants.py` — schema version, paths, MAX_PROVENANCE_CHAIN_LEN, STALE_TMP_TTL_SEC (~30 lines)
3. `source_refs.py` — 7 dataclasses + parse() (~120 lines)
4. `review.py` — ReviewDecision enum + ReviewRecord dataclass (~80 lines)

**Then layer on:**

5. `models.py` — FactKey, FactValue, FactProvenance (~180 lines)

**Then:**

6. `hash.py` + `locking.py` + `store.py` + `__init__.py` (~250 lines)

**Finally:**

7. All 4 test files + 5 fixtures + state dir scaffold (~350 lines)

**Total estimate:** ~1000-1200 lines of new code across all files.

---

## 10. Verdict

**READY FOR IMPLEMENTATION.**

- No unresolved blockers.
- Scope is clean — all new files, zero modification to existing code.
- WP-D public surface is frozen at commit `1afec36` and sufficient.
- Design is fully specified down to method signatures, validation rules,
  and test IDs.
- All B-section blockers resolved and encoded.
- All C-section recommendations resolved and encoded.
- D-section items are non-blocking polish.

**Recommended next action:** Commit the design docs (C0), then begin
implementation starting with leaf modules (errors → constants → source_refs →
review → models → hash → locking → store → tests).
