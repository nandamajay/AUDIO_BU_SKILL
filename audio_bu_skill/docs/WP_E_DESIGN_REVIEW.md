| Field         | Value                                                                 |
| ------------- | --------------------------------------------------------------------- |
| Title         | WP-E Fact Registry Design Review                                      |
| Status        | Review Complete — Sections B + C Resolved at Checkpoints E0/E1 (2026-07-20). Implementation Authorised. |
| Phase         | Phase-3A                                                              |
| Reviews       | `WP_E_FACT_REGISTRY_DESIGN.md` (Design Approved For Implementation)   |
| Prerequisite  | Sections B and C closed. Implementation authorised.                   |
| Depends On    | WP-D (frozen public surface, commit `1afec36`)                        |
| Consumed By   | WP-E implementation, WP-F (Coverage Engine)                           |
| Verification  | See `WP_E_FACT_REGISTRY_DESIGN.md` §18 Manual Verification History     |

This document captures the line-by-line review findings against
`audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md`. It is authoritative
for the pre-implementation checklist. Sections B and C are closed at
Checkpoints E0 and E1 respectively (2026-07-20); implementation is
authorised. Section D polish items remain open as non-blocking
follow-up.

The review is grounded in:

- WP-D public surface frozen at commit `1afec36`
  (`audio_bu_skill/fact_requirements/__init__.py`).
- `audio_bu_skill/docs/PHASE3_ARCHITECTURE.md` §4/§6/§8/§10.
- `audio_bu_skill/docs/PHASE3_LANDSCAPE.md` §1 Trust Doctrine.
- Internal consistency of `WP_E_FACT_REGISTRY_DESIGN.md` §1–§16.

Verdict summary: **4 blockers**, **5 strongly-recommended fixes**,
**3 documentation-only polish items**. Core data model, storage
strategy, and manual-fact discipline are sound.

---

## 1. Strengths (preserve as-is)

1. **Three-layer MANUAL-fact defense.** §5 invariant 4 + §5 invariant 8
   + §8 `has_evidence` cap constitute genuine belt-and-braces defense
   against manual-fact laundering. §14 R-E3 correctly notes the
   residual limit (a reviewer can still supply a bogus ticket URL)
   rather than overclaiming.
2. **Tagged-union `SourceRef` with `InferredRef` added.** §7 adds a
   seventh variant beyond `PHASE3_ARCHITECTURE.md` §4.3's six.
   INFERRED without a `SourceRef` in the arch doc is a laundering
   path; the design correctly closes it. Note this expansion in the
   PR description when the design lands.
3. **Append-only chain with cross-check invariant 7.** §5 requires
   `FactValue` last-of-chain to byte-match top-of-chain. This makes
   audit-log integrity a construction-time property, not a
   review-time hope.
4. **Storing `FactKey` twice on disk.** §10 records carry the key at
   the record top-level *and* in the record self-description. Each
   JSONL line is self-contained for offline audit tooling and for
   `grep`-based debugging.
5. **Explicit refusal of newer MINOR versions.** §11 chose durability
   over stanard-semver additive-MINOR compatibility. This is correct
   for a write-through registry — an old loader silently rewriting a
   newer file would drop unknown fields.
6. **Advisory-only invariant.** §1.7 + §15.7 + §15.8 enforce
   "no runner imports WP-E in Phase-3A" via both a unit test and a
   `git grep` check — good defense-in-depth.

---

## 2. Blockers — MUST fix before implementation (Section B)

### B-1. `RegistryStatus` enum never defined as a first-class artifact

**Where.** §2 lists `RegistryStatus` in the public surface. §1.2,
§1.6, §3, §9, §10, §11, §12, and §15 reference specific variants
(`ABSENT`, `CORRUPT`, `PARTIAL`, `HASH_MISMATCH`,
`UNSUPPORTED_SCHEMA`, and implicitly `OK`). No section enumerates the
full set nor defines the semantics of each variant.

**Failure mode if not fixed.** Six variants are inferable from
context, but nothing says whether `OK` and `PARTIAL` are mutually
exclusive with `HASH_MISMATCH`, nor how they compose. Implementation
will invent the composition rule; tests will lock in whatever the
first author chooses.

**Required fix.** Add §3.1 (or a new §9.1) with:

```python
class RegistryStatus(str, Enum):
    OK = "ok"                                  # file present, header valid, all lines parsed, hash matches
    ABSENT = "absent"                          # file does not exist; empty registry served
    PARTIAL = "partial"                        # some records failed to parse; others served
    CORRUPT = "corrupt"                        # header missing/malformed; no records served
    HASH_MISMATCH = "hash_mismatch"            # sidecar disagreement after retry
    UNSUPPORTED_SCHEMA = "unsupported_schema"  # major/minor outside SUPPORTED_SCHEMA_VERSIONS
```

Precedence rule for compound conditions (recommendation):
`CORRUPT` > `UNSUPPORTED_SCHEMA` > `HASH_MISMATCH` > `PARTIAL` >
`OK`. Rationale: hash mismatches on a corrupt file don't matter;
schema mismatches on a hash-mismatched file don't matter.

### B-2. `Registry` class API not specified

**Where.** §2 lists
`store.py: Registry class: load, save, append_provenance, get, iter`
in the file layout comment. No section defines method signatures,
return types, exception contracts, or the load/save state model.

**Failure mode if not fixed.** The following behaviors are undefined
and will be invented at implementation time:

- Does `load()` return an instance or mutate state on an existing
  instance?
- Does `append_provenance()` acquire the lock internally or expect
  the caller to hold it?
- Does `save()` no-op when nothing changed, or always rewrite
  (matters for idempotence per T-E20)?
- After `append_provenance`, is the in-memory chain updated
  eagerly, or must the caller reload?
- Is `Registry` mutable during a single lock-hold, or does each
  mutation open+close its own lock?

Each has cascading test implications.

**Required fix.** Add §3.1 with a dataclass/API sketch:

```python
@dataclass
class Registry:
    target: str
    status: RegistryStatus
    load_warnings: tuple[str, ...]
    _facts: Mapping[FactKey, FactValue]  # not public

    @classmethod
    def load(cls, target: str, *, base_dir: Path | None = None) -> "Registry": ...
    def get(self, fact_key: FactKey) -> FactValue | None: ...
    def iter_facts(self) -> Iterator[tuple[FactKey, FactValue]]: ...
    def append_provenance(
        self, fact_key: FactKey, provenance: FactProvenance
    ) -> "Registry":
        """Acquires the write lock internally; writes atomically; returns fresh load."""
    # NOTE: no public save() — save is an implementation detail of append_provenance.
```

**Key design choice** to record explicitly in §3.1: immutable vs
mutable Registry.

- **Immutable** (recommended): each mutation returns a new
  `Registry`. Matches append-only doctrine; eliminates stale-in-memory
  bugs.
- **Mutable**: each mutation updates `self`. Matches Python idiom but
  risks stale-in-memory drift when a second reader holds an old view.

### B-3. `HASH_MISMATCH` read-retry policy inconsistent between §9 and R-E8

**Where.** §9 reader flow says "read never mutates state" and
describes no retry. §14 R-E8 says "1 retry with 50ms sleep". §15
exit criteria do not test retry behavior.

**Failure mode if not fixed.** Implementation will pick one. Tests
will encode whatever gets built. Currently the two sections
disagree on whether the retry exists.

**Required fix.** Consolidate in §9 reader flow. Accept R-E8's
version (1 retry, 50ms sleep, then surface `HASH_MISMATCH` if still
mismatched). Add to §13:

- **T-E14b**: a mid-write hash mismatch is transparently recovered by
  the retry (returns `OK`).
- **T-E14c**: a persistent hash mismatch after retry surfaces as
  `HASH_MISMATCH`.

### B-4. Revocation sentinel unresolved (§6 vs §8 vs §5 invariant 7)

**Where.** §6 uses the `note == "REVOCATION"` string sentinel. §8
introduces `ReviewDecision.REJECT`. §5 invariant 7 requires
last-of-chain to match top-of-chain — which cannot hold if
top-of-chain is a live `FactValue` but the chain tail is a revocation
entry. OQ-1 flags the collision but leaves it open.

**Failure mode if not fixed.** This is a data-model choice, not a
naming choice. Deferring it means implementation invents it. Options:

| Option | Consequence                                                                                            |
| ------ | ------------------------------------------------------------------------------------------------------ |
| A      | `FactProvenance.is_revocation: bool` — uniform record shape; invariant 7 relaxes to "matches iff not revocation"; recommended |
| B      | Separate `FactRevocation` JSONL record — two record types on-disk; more parser branching                |
| C      | `value == None` string sentinel — ambiguous with legitimate nullable values; not recommended            |

**Required fix.** Adopt Option A. Mark OQ-1 resolved. Revise §5
invariant 7 to:

> If the last provenance entry has `is_revocation=False`, its fields
> match top-of-chain. If `is_revocation=True`, `Registry.get()` returns
> `None` and top-of-chain fields describe the last non-revocation entry.

---

## 3. Strongly recommended before implementation (Section C)

### C-1. Write order for atomic rename (OQ-3) affects durability

**Where.** §9 writer flow currently: serialise → temp file →
`os.replace()` (JSONL) → recompute sidecar hash → write sidecar via
temp+rename. **JSONL renames first, sidecar second.**

**Concern.** This creates R-E8's race window: a reader between the
two renames sees new JSONL + old sidecar → hash mismatch.

**Recommended fix.** Flip the order — sidecar first, JSONL last:

```
4. Serialise to <target>.json.tmp.<pid>; fsync it.
5. Compute sha256 of the tmp file bytes.
6. Write sha256 to <target>.registry.hash.tmp.<pid>; fsync;
   os.replace() to <target>.registry.hash.
7. os.replace() <target>.json.tmp.<pid> to <target>.json.
8. (Optional) fsync the containing directory.
```

Resulting failure mode: reader sees new sidecar + old JSONL → hash-check
fails → retry sees new JSONL → succeeds. Strictly better than current
design.

### C-2. Provenance-chain length cap (OQ-6)

**Concern.** No cap → a stuck acquisition loop produces unbounded
provenance growth.

**Recommended fix.** Cap chain length at 100 entries.
`append_provenance` on a full chain raises `RegistryWriteError`.
Add to §13:

- **T-E22c**: `append_provenance` on a chain of length 100 raises
  `RegistryWriteError`.
- **T-E22d**: chain of length 99 accepts one more append (boundary).

Add to §11: raising the cap requires a MAJOR version bump (existing
loaders would need to know the new limit).

### C-3. Kernel authority discrimination (`KERNEL_DTS` vs `KERNEL_BINDINGS`)

**Where.** §7 authority↔SourceRef table maps both `KERNEL_DTS` and
`KERNEL_BINDINGS` to `KernelRef`. `KernelRef` has no discriminator
field.

**Concern.** WP-D distinguishes these because their freshness
policies differ (`AuthorityTTL` in `FreshnessPolicy`). WP-F needs to
compute freshness per authority. With only `KernelRef` + no
discriminator, WP-F must re-derive DTS-vs-BINDINGS from the `path`
field. Fragile.

**Recommended fix.** Option A (minimal): add
`kernel_ref_kind: Literal["dts", "bindings"]` to `KernelRef`.
Option B (cleaner, more parser branches): split into `KernelDTSRef`
and `KernelBindingsRef` variants. Recommend Option A.

### C-4. Comment/blank lines in JSONL (§3 vs §10)

**Where.** §3 says empty lines and `#`-prefixed lines are permitted
and ignored on read. §10 says the writer never emits them but does
not forbid them.

**Concern.** A manual editor who adds a `#` comment loses it on the
next writer round-trip. Operator surprise.

**Recommended fix.** Forbid `#` comments on rewrite (§10). Manual
comments die on next save. Rationale: preserving comments would
require associating them with a following record — complexity not
worth it for Phase-3A. Add **T-E15b**: hand-editing a registry to add
a comment survives the next load (`OK` status) but does not survive
the next save.

### C-5. Stale tmp file cleanup contract missing from §9

**Where.** §13 T-E19 asserts "next writer removes stale tmp files
older than 60s". §9 writer flow does not describe this step.

**Concern.** T-E19 will fail without an implementation. Also 60s is
not a justified constant.

**Recommended fix.** Add step 0 to §9 writer flow:

> Before acquiring the lock, remove any `<target>.json.tmp.*` older
> than `STALE_TMP_TTL_SEC` (60s). This handles writer crashes that
> left tmp files behind.

Add `STALE_TMP_TTL_SEC: int = 60` to `constants.py` with a footnote
justifying the value (longer than any legitimate write, shorter than
any operator's patience).

---

## 4. Documentation polish (Section D — safe to defer)

### D-1. §7 IPCAT `query_id` origin

**Concern.** §7 says `IPCATLiveRef.query_id: str  # provider-issued
or client-generated request id`. "Provider-issued or client-generated"
is ambiguous.

**Recommendation.** Clarify the fallback rule: if the MCP tool does
not issue an id, generate a deterministic id
`sha256(tool + json.dumps(args, sort_keys=True))[:16]`. Deterministic
ids let the same query round-trip to the same id — useful for
provenance-chain dedup.

### D-2. §12 vs §10 sort-on-write

**Concern.** §10 says the writer sorts records on write. §12 says
corrupt files are not rewritten. A successful load-then-save on a
well-formed but unsorted legacy file will silently reorder it
(visible in git diff). Not a bug — arguably desired — but worth
stating.

**Recommendation.** Add to §10:

> Legacy registries loaded without errors will be reordered on the
> next save. This is idempotent thereafter and does not change fact
> identity.

### D-3. §15 exit item 14 depends on OQ-8

**Concern.** §15.14 says each dataclass carries a module-level
docstring cross-referencing `PHASE3_ARCHITECTURE.md`. OQ-8 asks
whether `PHASE3_ARCHITECTURE.md` §8 or `WP_E_FACT_REGISTRY_DESIGN.md`
is the canonical spec.

**Recommendation.** Resolve OQ-8 first: this doc
(`WP_E_FACT_REGISTRY_DESIGN.md`) is canonical for WP-E;
`PHASE3_ARCHITECTURE.md` §8 becomes a pointer. Then §15.14 revises to:

> Each dataclass module-docstring cross-references the corresponding
> section of `WP_E_FACT_REGISTRY_DESIGN.md`.

---

## 5. Cross-check against upstream contracts

### 5.1 WP-D public surface — clean

`audio_bu_skill/fact_requirements/__init__.py` exports:
`Authority`, `AuthorityClass`, `Domain`, `FactFamilyDef`,
`FreshnessPolicy`, `Requiredness`, `SubjectRequirement`,
`load_catalog`, `load_freshness_policy`.

WP-E uses only: `Authority`, `AuthorityClass`, `Domain`. Zero use of
`FactFamilyDef`, `SubjectRequirement`, `FreshnessPolicy`, `Catalog`,
`load_catalog`, `load_freshness_policy`. Consistent with §1.8
("Zero dependency on WP-D internals"). No WP-D internals leak into
WP-E. **PASS.**

### 5.2 Trust Doctrine (PHASE3_LANDSCAPE.md §1) — consistent

Three tiers (IPCAT-only, IPCAT+schematic, schematic-only) are
enforced by the `authority` + `authority_class` pair on `FactValue`,
plus the SourceRef cross-check in §7. Nothing in the design allows a
fact to skip a tier. **PASS.**

### 5.3 PHASE3_ARCHITECTURE.md §4.3 SourceRef variants — expanded

Arch doc lists six variants (IPCATLive/Cached, Kernel, Schematic,
ACDB, Manual). WP-E adds `InferredRef` (seven variants). Deliberate
strengthening of the arch doc; the arch doc's silence on INFERRED
SourceRefs was a laundering path. **Note in PR description when
design lands.**

### 5.4 PHASE3_ARCHITECTURE.md §6 ManualFact discipline — captured

- Arch §6.2 ("no ticket/email/doc → cap at 0.4") → §5 invariant 8 +
  §8 `has_evidence`. **PASS.**
- Arch §6.4 (revocation via `decision == REJECT`) → §8. **PASS
  modulo B-4.**
- Arch §6.5 (report renders `reviewer_id` + ticket) → out of WP-E
  scope, deferred to WP-G. **PASS.**

### 5.5 PHASE3_ARCHITECTURE.md §10 pre-merge checklist — mapped 1:1

Cross-checked all seven pre-merge items in arch §10 against exit
criteria §15.1–§15.15. Coverage complete. Two exit items (§15.14
dataclass docstrings, §15.15 whitelist stage) go beyond arch §10 —
additive, not conflicting. **PASS.**

---

## 6. Ready-to-implement checklist

Sections B and C are both closed. Implementation is authorised.
Section D may remain open as follow-up polish and does not gate the
start of WP-E code work.

| Item | Status                                    | Blocker for implementation? |
| ---- | ----------------------------------------- | --------------------------- |
| B-1  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                |
| B-2  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                |
| B-3  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                |
| B-4  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                |
| C-1  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) |
| C-2  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) |
| C-3  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) |
| C-4  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) |
| C-5  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) |
| D-1  | Open                                      | No                          |
| D-2  | Open                                      | No                          |
| D-3  | Open                                      | No                          |

Section B resolution recorded in
`WP_E_FACT_REGISTRY_DESIGN.md` §18 (Manual Verification History,
Checkpoint E0, 2026-07-20). Encoding of each resolved blocker:

- **B-1** → §3.1 (RegistryStatus enum + precedence rule)
- **B-2** → §3.2 (Registry class API — immutable)
- **B-3** → §9 reader flow (1-retry / 50ms) + §13 T-E14b/T-E14c
- **B-4** → §5 invariant 7 + §6 `is_revocation: bool` + §8 revocation accessor + §13 T-E22

Section C resolution recorded in `WP_E_FACT_REGISTRY_DESIGN.md` §18
(Manual Verification History, Checkpoint E1, 2026-07-20). Encoding of
each resolved strongly-recommended item:

- **C-1** → §9 writer flow steps 4–8 (sidecar-first) + §9 "Why sidecar-first" rationale + §16 OQ-3 (marked RESOLVED)
- **C-2** → §3.2 `append_provenance` docstring (names `MAX_PROVENANCE_CHAIN_LEN = 100`) + §11 MAJOR-bump note + §13 T-E22c/T-E22d + §16 OQ-6 (marked RESOLVED)
- **C-3** → §7 `KernelRef.kernel_ref_kind: Literal["dts", "bindings"]` discriminator + §7 authority↔SourceRef mapping table + §7 "Why `KernelRef.kernel_ref_kind`" rationale + §13 T-E33 (discriminator round-trip)
- **C-4** → §10 "Comments and blank lines on rewrite" rule + §10 "Why forbid comment/blank-line round-trip" rationale + §13 T-E15b
- **C-5** → §9 writer flow step 0 (stale-tmp cleanup with `STALE_TMP_TTL_SEC = 60`) — folded into the sidecar-first rewrite for C-1

Retag applied at Checkpoint E1: `WP_E_FACT_REGISTRY_DESIGN.md` line 6
advanced from **"Design Approved For Review — B-1..B-4 Resolved"** to
**"Design Approved For Implementation"**. See
`WP_E_FACT_REGISTRY_DESIGN.md` §18 "Checkpoint E1 — Section C
Disposition (2026-07-20)" for the authoritative decision record.

Estimated post-revision implementation effort: ~1 day for
`store.py`/`models.py`/`review.py`/`locking.py`/`hash.py`/
`source_refs.py`/`errors.py` + 33 tests + import-graph guard test.
Full 38-module sweep must remain green.

---

## 7. Cross-references

- `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md` §1–§18 (design
  under review; §17 Revised Ready-to-Implement Checklist and §18 Manual
  Verification History added at Checkpoint E0, 2026-07-20; §17
  re-revised and §18 Checkpoint E1 subsection appended at Checkpoint
  E1, 2026-07-20).
- `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md` §18 —
  authoritative record of Checkpoint E0 (2026-07-20) B-1..B-4
  resolution: reviewer, date, and rationale per decision.
- `audio_bu_skill/docs/WP_E_FACT_REGISTRY_DESIGN.md` §18 —
  authoritative record of Checkpoint E1 (2026-07-20) C-1..C-5
  disposition and the retag from "Design Approved For Review —
  B-1..B-4 Resolved" to "Design Approved For Implementation":
  reviewer, date, and rationale per decision.
- `audio_bu_skill/docs/PHASE3_ARCHITECTURE.md` §4.3 (SourceRef
  variants), §6 (ManualFact discipline), §8 (WP-E/WP-F/WP-G specs),
  §10 (pre-merge checklist).
- `audio_bu_skill/docs/PHASE3_LANDSCAPE.md` §1 (Trust Doctrine
  three-tier model).
- `audio_bu_skill/docs/PHASE3_KNOWN_GAPS.md` G-3A.1 (IPCAT Acquisition
  Lifecycle — deferred, not in scope of WP-E).
- `audio_bu_skill/fact_requirements/__init__.py` (WP-D frozen public
  surface, commit `1afec36`).
- `audio_bu_skill/docs/WP_B_POST_IMPLEMENTATION_REVIEW.md` (prior
  review-doc template).
