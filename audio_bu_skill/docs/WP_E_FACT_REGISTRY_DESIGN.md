# WP-E Fact Registry Design

| Field | Value |
| --- | --- |
| **Title** | WP-E Fact Registry Design |
| **Status** | Design Approved For Implementation (2026-07-20) |
| **Phase** | Phase-3A |
| **Depends On** | WP-D |
| **Consumed By** | WP-F |
| **Review** | `WP_E_DESIGN_REVIEW.md` (Manual Verification Checkpoint E0) |

**Type:** Design document. No code, no commits, no behavior change.
**Purpose:** Capture the reviewed WP-E design so implementation can begin from
a stable spec rather than from a scrollback. Ground every choice in
`PHASE3_ARCHITECTURE.md` §4 and §8 and the committed WP-D public surface
(`audio_bu_skill.fact_requirements`).
**Non-goal:** This document does not authorize implementation. It records the
design as approved for review — implementation is a separate, later step.

---

## 1. Objectives

**Primary objective.** Provide a per-target, append-only fact store with a
small, testable API that WP-F (Coverage Engine) can consume and that any future
acquisition path (Phase-3B live IPCAT, backfill, or manual entry) can write
into — without any coupling to the current onboarding pipeline.

**Sub-objectives.**

1. **Storage.** Persist facts under
   `audio_bu_skill/state/fact_registry/<target>.json` as newline-delimited JSON,
   one FactKey per line, with the current `FactValue` and its full
   `provenance_chain`.
2. **Integrity.** Every write is atomic (temp-file + rename) and produces a
   sidecar hash (`<target>.registry.hash`). Corruption is detected at load and
   surfaces as `RegistryStatus.CORRUPT` rather than raising.
3. **Concurrency.** A POSIX advisory lock (`<target>.lock`) makes concurrent
   writers safe. Reads are lock-free.
4. **Append-only provenance.** Every re-acquisition pushes a new
   `FactProvenance` entry onto the chain. Top-of-chain fields on `FactValue`
   are re-derived from the new entry. Prior entries are never mutated.
5. **Manual-fact discipline.** `authority_class = MANUAL` demands a non-null,
   structurally-valid `ReviewRecord`. Manual facts without a review record are
   **rejected at load** (never surface to WP-F). Manual facts without a
   verifiable evidence pointer (`ticket_url`, `email_msgid`, `doc_ref`) are
   loaded but have `confidence` capped at 0.4.
6. **Registry-absent tolerance.** Missing registry file returns
   `RegistryStatus.ABSENT` with an empty fact map — never raises. WP-F depends
   on this to render the registry-absent stub (`PHASE3_ARCHITECTURE.md` §7.3).
7. **Advisory-only.** WP-E ships as a **standalone module** that is not
   imported by any runner, `main.py`, or promotion code. It exists purely so
   WP-F can consume it. This preserves the "zero behavior change on the
   existing pipeline" invariant in `PHASE3_ARCHITECTURE.md` §10.
8. **Zero dependency on WP-D internals.** WP-E imports only from
   `audio_bu_skill.fact_requirements`'s public surface. It does not inspect
   catalog internals; requirement matching (e.g., regex expansion of subject
   patterns) is the Coverage Engine's problem, not the Registry's.

**What WP-E does NOT do.**

- Does not decide whether a fact "counts" toward coverage — that is WP-F.
- Does not compute `freshness_state` — derived by WP-F using the
  `FreshnessPolicy` loaded by WP-D.
- Does not compute `conflict_state` — that is WP-F.
- Does not acquire facts (no MCP, no schematic parsing, no kernel scan). Writes
  come only from an external caller.
- Does not backfill legacy targets. Phase-3A ships empty registries.
- Does not migrate any existing state.

---

## 2. File Layout

All files new. Nothing modified. Nothing deleted.

```
audio_bu_skill/
  orchestrator/
    fact_registry/
      __init__.py                 # public surface: Registry, RegistryStatus, models, exceptions
      models.py                   # FactKey, FactValue, FactProvenance
      source_refs.py              # tagged-union dataclasses for SourceRef variants + parser
      review.py                   # ReviewRecord + review validation logic
      hash.py                     # sidecar hash compute + verify
      store.py                    # Registry class: load, save, append_provenance, get, iter
      locking.py                  # POSIX advisory-lock context manager
      errors.py                   # RegistryError, RegistryLoadError, RegistryLockError
      constants.py                # schema_version, path helpers, filename patterns
  state/
    fact_registry/
      README.md                   # explains the directory; ".json"/".hash" gitignored
      .gitignore                  # ignores *.json, *.hash, *.lock; keeps README + .gitignore
  tests/
    test_fact_registry_models.py       # T-E1..T-E10 model-level invariants
    test_fact_registry_store.py        # T-E11..T-E22 store-level roundtrip / append / lock
    test_fact_registry_review.py       # T-E23..T-E28 MANUAL-fact validation
    test_fact_registry_source_refs.py  # T-E29..T-E33 tagged-union parsing
    fixtures/
      fact_registry/
        golden_registry_v1.jsonl       # one-line-per-fact reference for round-trip test
        malformed_missing_review.jsonl # MANUAL without ReviewRecord → must be rejected
        conflict_chain.jsonl           # two provenance entries with different values
        stale_manual.jsonl             # expires_at in the past
        newer_schema.jsonl             # schema_version = 999 → loader must refuse
```

**Explicit exclusions.**

- No modification to `audio_bu_skill/orchestrator/main.py`.
- No modification to any runner under `audio_bu_skill/orchestrator/runners/`.
- No modification to `audio_bu_skill/fact_requirements/*` (WP-D is frozen).
- No modification to any `targets/*` file.
- No modification to `case.py` or `case.generated.py`.
- No modification to existing tests.

**`.gitignore` addition (targeted).** Only within
`audio_bu_skill/state/fact_registry/` — ignore `*.json`, `*.hash`, `*.lock`.
Keep the directory itself alive via a checked-in `README.md` and `.gitignore`.
Matches the pre-merge check in `PHASE3_ARCHITECTURE.md` §10 item 7.

---

## 3. Registry Schema (on-disk file shape)

**File:** `audio_bu_skill/state/fact_registry/<target>.json`
**Format:** JSON Lines (newline-delimited JSON). One line = one fact record.
Empty lines and lines starting with `#` are permitted and ignored on read
(reserved for future annotation; the writer never emits them).

**Rationale for JSONL over a single JSON document.**

- Append-friendly: adding a fact appends one line — no full-file rewrite needed
  for future high-write phases. Phase-3A writes full-file, but the format is
  chosen so Phase-3B does not have to migrate.
- Diff-friendly: git-diff and human review scan cleanly.
- Corruption-tolerant: a single bad line does not destroy the whole registry —
  bad lines are captured as `RegistryStatus.PARTIAL` with a `load_warnings`
  list.

**Per-line record shape.**

```json
{
  "fact_key": {
    "domain": "Audio",
    "family": "GPIO",
    "subject": "I2S8_SD0",
    "attribute": "pin_number"
  },
  "value": {
    "value": 74,
    "authority": "ipcat_cached",
    "authority_class": "primary",
    "captured_at": "2026-07-19T14:22:03Z",
    "source_ref": { "kind": "ipcat_cached", "path": ".../ipcat/tlmm.json", "sha256": "...", "line": 412 },
    "confidence": 0.95,
    "review": null,
    "notes": ""
  },
  "provenance_chain": [
    {
      "authority": "ipcat_cached",
      "authority_class": "primary",
      "source_ref": { "kind": "ipcat_cached", "path": ".../ipcat/tlmm.json", "sha256": "...", "line": 412 },
      "captured_at": "2026-07-09T11:03:11Z",
      "confidence": 0.90,
      "note": "initial capture",
      "value": 74,
      "review": null
    },
    {
      "authority": "ipcat_cached",
      "authority_class": "primary",
      "source_ref": { "kind": "ipcat_cached", "path": ".../ipcat/tlmm.json", "sha256": "...", "line": 412 },
      "captured_at": "2026-07-19T14:22:03Z",
      "confidence": 0.95,
      "note": "re-capture after tlmm.json refresh",
      "value": 74,
      "review": null
    }
  ]
}
```

**File-level frame.**

- First non-comment line MUST be a header record:
  `{"__type": "registry_header", "schema_version": "1.0.0", "target": "<target>", "written_at": "...", "writer": "wp-e/store.py"}`.
- Header validated at load; `schema_version` checked against a compile-time
  `constants.SUPPORTED_SCHEMA_VERSIONS`.
- Fact records follow, one per line. Order is arbitrary but the writer sorts
  by `(domain, family, subject, attribute)` for stable diffs.

**Deliberately-omitted fields (compared to §4.2 of the architecture doc).**

- `freshness_state` — derived at load by WP-F, never stored. Storing would
  age immediately.
- `coverage_state` — same reason.
- `conflict_state` — same reason.

Storing derivations would let stale/incorrect computations poison future runs.
Store what is authored; derive what is judged.

---

## 3.1 `RegistryStatus` Enum (B-1, resolved 2026-07-20)

Every `Registry` load produces exactly one `RegistryStatus`. The enum is a
first-class public artifact of the `fact_registry` package; every consumer
(WP-F, WP-G, future CLIs) branches on it explicitly.

```python
class RegistryStatus(str, Enum):
    OK = "ok"                                  # file present, header valid, all records parsed, hash matches
    ABSENT = "absent"                          # file does not exist; an empty registry is served
    PARTIAL = "partial"                        # some records failed to parse; others are served with warnings
    CORRUPT = "corrupt"                        # header missing/malformed; no records are served
    HASH_MISMATCH = "hash_mismatch"            # sidecar disagreement persists after the retry policy (see §9)
    UNSUPPORTED_SCHEMA = "unsupported_schema"  # schema_version outside SUPPORTED_SCHEMA_VERSIONS (see §11)
```

**Precedence rule for compound conditions (approved Checkpoint E0, 2026-07-20).**

```
CORRUPT > UNSUPPORTED_SCHEMA > HASH_MISMATCH > PARTIAL > OK
```

The loader evaluates conditions in this order and returns the first that
applies. Rationale:

- `CORRUPT` (header missing/malformed) dominates because nothing else can be
  meaningfully evaluated on a file with no valid header.
- `UNSUPPORTED_SCHEMA` dominates `HASH_MISMATCH` because the loader must not
  attempt to serve records it does not understand, even if the bytes hash
  correctly.
- `HASH_MISMATCH` dominates `PARTIAL` because a hash mismatch means the
  operator cannot trust *any* of the loaded records, not just the malformed
  ones.
- `PARTIAL` dominates `OK` because a well-formed subset of records with
  a well-formed hash is still a load with warnings the operator must see.

Consumers must never observe more than one status per load call. The
`load_warnings: tuple[str, ...]` field carries the per-line diagnostics that
would otherwise be lost to the precedence collapse (e.g., which records were
dropped under `PARTIAL`, or which record types were unknown under
`UNSUPPORTED_SCHEMA`).

---

## 3.2 `Registry` Class API (B-2, resolved 2026-07-20)

`Registry` is **immutable**. Every state transition returns a fresh instance;
callers never observe in-place mutation. Rationale: matches the append-only
doctrine of the on-disk format, eliminates stale-in-memory drift when a
second reader holds an old view, and lets `Registry` be treated as a plain
value across function boundaries.

```python
@dataclass(frozen=True)
class Registry:
    target: str
    status: RegistryStatus
    load_warnings: tuple[str, ...]
    _facts: Mapping[FactKey, FactValue]  # not part of the public API

    @classmethod
    def load(cls, target: str, *, base_dir: Path | None = None) -> "Registry":
        """Load the registry for ``target`` from disk.

        Always returns a Registry; never raises for missing-file, corrupt-file,
        hash-mismatch, unsupported-schema, or partial-parse conditions — those
        surface via ``status``. Raises only on programmer errors (invalid
        ``target`` string, unwritable ``base_dir`` path).
        """

    def get(self, fact_key: FactKey) -> FactValue | None:
        """Return the current FactValue for ``fact_key`` or None.

        Returns None when the fact is absent OR when the fact's top-of-chain
        provenance entry has ``is_revocation=True`` (see §6 and §8). The
        underlying provenance chain remains on disk in either case.
        """

    def iter_facts(self) -> Iterator[tuple[FactKey, FactValue]]:
        """Iterate over all live (non-revoked) facts in a stable order.

        Order: sorted by (domain, family, subject, attribute). Revoked facts
        are omitted from iteration.
        """

    def append_provenance(
        self,
        fact_key: FactKey,
        provenance: FactProvenance,
    ) -> "Registry":
        """Append ``provenance`` to ``fact_key``'s chain and return a fresh Registry.

        Behavior:
        - Acquires the write lock internally (see §9). Callers do NOT hold locks.
        - Serializes to a temp file, fsyncs, updates the sidecar hash, and
          atomically renames — the writer flow in §9 is authoritative.
        - Returns a newly-loaded ``Registry`` reflecting the post-write state.
          The receiver instance is NOT mutated.
        - Raises ``RegistryLockError`` if the lock cannot be acquired within
          the timeout.
        - Raises ``RegistryWriteError`` on I/O failure or invariant violation.
          In particular, if the existing provenance chain for ``fact_key``
          already contains ``MAX_PROVENANCE_CHAIN_LEN`` entries (=100, defined
          in ``constants.py``), the append is refused with
          ``RegistryWriteError`` and the on-disk state — JSONL and sidecar
          — is left unchanged. See §11 for the MAJOR-bump requirement that
          governs raising this cap and §13 T-E22c/T-E22d for the boundary
          tests. (C-2, 2026-07-20)
        """
```

**No public `save()`.** Persistence is an implementation detail of
`append_provenance`. Callers that need to write must go through
`append_provenance`; there is no path that lets a caller construct an
arbitrary in-memory `Registry` and stamp it onto disk. This preserves the
append-only invariant at the API boundary, not just at the record boundary.

**Concurrency semantics.** Each `append_provenance` call is a full
lock–read–mutate–write–unlock cycle. Two concurrent `append_provenance` calls
against the same target serialize through the lock; the second caller sees
the first caller's write in its returned `Registry`. Two concurrent reads
(`load`, `get`, `iter_facts`) run without any lock and may observe an older
state than the most recent successful write — that is intentional and
acceptable for advisory-only Phase-3A use.

**Interaction with `RegistryStatus`.** `append_provenance` refuses to write
against a `Registry` whose `status` is `CORRUPT`, `UNSUPPORTED_SCHEMA`, or
`HASH_MISMATCH`. It raises `RegistryWriteError` in those cases with a
diagnostic that names the status. Writes are permitted against `OK`,
`ABSENT`, and `PARTIAL` — the `PARTIAL` case is deliberate: a partial-load
registry can still accept new writes for well-formed facts; the malformed
lines are preserved untouched so the operator can recover them offline.

---

## 4. FactKey Definition

```python
@dataclass(frozen=True)
class FactKey:
    domain: Domain            # imported from audio_bu_skill.fact_requirements
    family: str               # unqualified family name (matches FactFamilyDef.name)
    subject: str              # concrete subject identifier (e.g., "I2S8_SD0", "VDD_LCX")
    attribute: str            # attribute of the subject (e.g., "pin_number", "regulator_name")

    def __post_init__(self) -> None:
        # Validate: domain is Domain; family matches ^[A-Za-z][A-Za-z0-9_]*$;
        # subject non-empty; attribute non-empty and matches ^[a-z][a-z0-9_]*$
        # (attribute names are lowercase to make FactKey stringification predictable
        # for grep and golden-report matching in WP-G).
        ...

    @property
    def qualified_family(self) -> str:
        return f"{self.domain.value}.{self.family}"

    def as_string(self) -> str:
        # Canonical stringification for FactKey — matches §4.1 of PHASE3_ARCHITECTURE.md.
        # "<domain>.<family>/<subject>/<attribute>"
        return f"{self.qualified_family}/{self.subject}/{self.attribute}"

    @classmethod
    def parse(cls, s: str) -> "FactKey":
        # Inverse of as_string(); raises ValueError on malformed input.
        # Splits on '/' (exactly 2 splits after the "<domain>.<family>" prefix).
        ...
```

**Design notes.**

- FactKey is a **type-level identity**, not a scope. It does not carry
  `target`, `board`, `path`, or `chip` — those are captured by the file
  boundary or by `SourceRef` inside `FactValue`. Matches §4.1's rationale.
- `frozen=True` makes it hashable so it can be used as a dict key in the
  in-memory registry map.
- `parse()` and `as_string()` are round-trip inverses. WP-G renders
  `as_string()` in the report; WP-F and any future CLI (`--dump-registry`)
  parse it back.
- FactKey validation does **not** cross-check against the catalog. That is
  WP-F's job. WP-E accepts any well-formed FactKey; whether it matches a
  catalog subject-pattern is decided at coverage time. Rationale: registries
  populated by future authorities may legitimately store subjects not yet in
  the catalog, and the registry should not silently drop them.

---

## 5. FactValue Definition

```python
@dataclass(frozen=True)
class FactValue:
    value: JsonScalar | Mapping[str, Any] | Sequence[Any]  # JSON-serialisable
    authority: Authority                                    # from WP-D
    authority_class: AuthorityClass                         # from WP-D
    captured_at: datetime                                   # tz-aware UTC
    source_ref: SourceRef                                   # tagged union, §7
    confidence: float                                       # [0.0, 1.0]
    review: ReviewRecord | None                             # non-null iff MANUAL
    notes: str                                              # free-text; not indexed
    provenance_chain: tuple[FactProvenance, ...]            # append-only history

    def __post_init__(self) -> None:
        # 1. `value` is JSON-serialisable (round-trip through json.dumps/loads).
        # 2. `captured_at` is tz-aware UTC.
        # 3. `confidence` in closed interval [0.0, 1.0].
        # 4. `authority_class == MANUAL` iff `review is not None`.
        # 5. `authority_class == INFERRED` implies `authority == Authority.INFERRED`.
        # 6. `authority_class == MANUAL` implies `authority == Authority.MANUAL`.
        # 7. `provenance_chain` non-empty. Let `last = provenance_chain[-1]`.
        #    - If `last.is_revocation is False`, its (value, authority,
        #      authority_class, source_ref, captured_at, confidence, review)
        #      fields match this FactValue's top-of-chain fields byte-for-byte.
        #    - If `last.is_revocation is True`, this FactValue's top-of-chain
        #      fields describe the LAST non-revocation entry in the chain
        #      (the "live" value at the moment of revocation). `Registry.get()`
        #      returns None for a fact whose chain top is a revocation entry;
        #      the top-of-chain descriptor is preserved solely for audit and
        #      report rendering.
        #    See §6 for the append-only revocation model (B-4, 2026-07-20).
        # 8. Manual-fact confidence cap: if review is not None and
        #    review has no ticket_url/email_msgid/doc_ref → clamp confidence to
        #    min(confidence, 0.4). Cap is applied at construction, not on the
        #    provenance entry (the chain preserves the original).
        ...
```

**Deliberately absent from `FactValue`.**

- `freshness_state`, `coverage_state`, `conflict_state`: derived, not stored.
- `target`: implied by file boundary.
- `fact_key`: FactKey is the map key; storing it inside FactValue would
  duplicate. On disk, each JSONL record co-carries both because the record is
  self-contained.

**Interaction with WP-D.**

- `authority` and `authority_class` are typed with the WP-D enums directly.
  No shadow enums, no duck-typed strings.
- WP-E does not know whether a particular `Authority` is PRIMARY for a given
  family — that is a Catalog question decided by WP-F. So `authority_class` is
  authored by the writer (whoever produced the fact) and stored as-is. WP-E
  only validates class↔identity consistency for the two cases where they must
  match (MANUAL and INFERRED).

---

## 6. FactProvenance Definition

```python
@dataclass(frozen=True)
class FactProvenance:
    value: JsonScalar | Mapping[str, Any] | Sequence[Any]
    authority: Authority
    authority_class: AuthorityClass
    source_ref: SourceRef
    captured_at: datetime            # tz-aware UTC
    confidence: float                # [0.0, 1.0]
    note: str                        # brief human-authored context
    review: ReviewRecord | None      # non-null only when this entry supersedes via manual review
    is_revocation: bool              # True iff this entry withdraws a MANUAL fact (§8)

    def __post_init__(self) -> None:
        # Same constraints as FactValue for the fields it shares.
        # No append-only invariant: provenance is itself a leaf record.
        # If is_revocation is True:
        #   - authority_class MUST be MANUAL (only manual review can revoke)
        #   - review MUST be non-null with decision == REJECT
        #   - review.supersedes_provenance_index MUST be non-null and point
        #     to a prior entry in the chain being revoked
        ...
```

**Design notes.**

- Provenance entries **carry the value they saw**, not a pointer to
  `FactValue.value`. Rationale: the value can change across re-captures
  (SchematicRef says pin 74; IPCATLiveRef says pin 76 after a catalog update).
  Comparing values across the chain is how WP-F detects conflicts.
- `note` is a free-text field for the writer's context ("re-captured after
  IPCAT release r15", "manual override per JIRA-1234"). It is not indexed and
  not used by WP-F for verdicts.
- A provenance entry with `is_revocation=True` marks withdrawal of a MANUAL
  fact per `PHASE3_ARCHITECTURE.md` §6.4. The revocation entry is itself an
  append (not a mutation of prior entries), preserving the append-only
  doctrine. `Registry.get()` returns `None` when the chain top has
  `is_revocation=True`; `iter_facts()` skips the fact; the full chain is
  preserved on disk for audit. Prior to Checkpoint E0 (2026-07-20) this doc
  proposed a `note == "REVOCATION"` string sentinel; that sentinel is
  **removed** in favor of the explicit boolean field (see OQ-1 / B-4).

**Rationale for storing the full chain, not just the diff.** Facts are
low-cardinality (< 500 per target expected in Phase-3A) and human-readable
audit is a first-order requirement. Chain size is O(re-captures per subject),
typically 1–3. Storage cost is negligible; diff cost is the operator-visible
payoff.

---

## 7. SourceRef Tagged Union Design

**Discriminator.** `kind: Literal["ipcat_live", "ipcat_cached", "kernel", "schematic", "acdb", "manual", "inferred"]`.
`"inferred"` is added compared to `PHASE3_ARCHITECTURE.md` §4.3 to give
INFERRED facts a first-class SourceRef; §4.3 lists six variants and implies
INFERRED can slip in without one, which invites laundering. The design closes
that gap.

**Variants.**

```python
@dataclass(frozen=True)
class IPCATLiveRef:
    kind: Literal["ipcat_live"]      # discriminator
    tool: str                        # MCP tool name, e.g. "ip_catalog-chips_chip_details"
    args: Mapping[str, Any]          # arguments passed
    query_id: str                    # provider-issued or client-generated request id
    ts: datetime                     # tz-aware UTC of the MCP round-trip

@dataclass(frozen=True)
class IPCATCachedRef:
    kind: Literal["ipcat_cached"]
    path: str                        # repo-relative path under evidence/ipcat/
    sha256: str                      # 64 hex chars of the file at capture time
    line: int | None                 # line offset if applicable

@dataclass(frozen=True)
class KernelRef:
    kind: Literal["kernel"]
    kernel_ref_kind: Literal["dts", "bindings"]  # discriminator (C-3, 2026-07-20)
    repo: str                        # e.g., "linux-nord"
    commit: str                      # 40-hex commit SHA (pinned)
    path: str                        # repo-relative path
    line_start: int
    line_end: int

@dataclass(frozen=True)
class SchematicRef:
    kind: Literal["schematic"]
    doc_id: str                      # e.g., "LD20-94441"
    revision: str                    # e.g., "0010_17_02_2026"
    page: int
    section: str | None

@dataclass(frozen=True)
class ACDBRef:
    kind: Literal["acdb"]
    export_id: str
    path: str
    key: str

@dataclass(frozen=True)
class ManualRef:
    kind: Literal["manual"]
    ticket_url: str | None
    doc_ref: str | None
    note: str

@dataclass(frozen=True)
class InferredRef:
    kind: Literal["inferred"]
    inference_rule: str              # symbolic name, e.g., "gpio_from_pinctrl_group"
    inputs: Mapping[str, str]        # inputs (other FactKeys as strings) it derived from
    note: str
```

**Parser (`source_refs.parse`).**

```python
def parse(raw: Mapping[str, Any]) -> SourceRef:
    kind = raw.get("kind")
    if kind == "ipcat_live":   return IPCATLiveRef(**raw)
    if kind == "ipcat_cached": return IPCATCachedRef(**raw)
    if kind == "kernel":       return KernelRef(**raw)
    if kind == "schematic":    return SchematicRef(**raw)
    if kind == "acdb":         return ACDBRef(**raw)
    if kind == "manual":       return ManualRef(**raw)
    if kind == "inferred":     return InferredRef(**raw)
    raise ValueError(f"Unknown SourceRef.kind: {kind!r}")
```

**Cross-check invariant (validated in `FactValue.__post_init__`).**

| `authority` | required `source_ref.kind` |
| --- | --- |
| `IPCAT_LIVE` | `"ipcat_live"` |
| `IPCAT_CACHED` | `"ipcat_cached"` |
| `KERNEL_DTS` | `"kernel"` with `kernel_ref_kind == "dts"` (C-3, 2026-07-20) |
| `KERNEL_BINDINGS` | `"kernel"` with `kernel_ref_kind == "bindings"` (C-3, 2026-07-20) |
| `SCHEMATIC_PDF` | `"schematic"` |
| `ACDB_EXPORT` | `"acdb"` |
| `MANUAL` | `"manual"` |
| `INFERRED` | `"inferred"` |

Any mismatch → construction raises `ValueError`. This prevents a fact declared
as `IPCAT_LIVE` from silently carrying a `ManualRef`, which would be the most
direct laundering path.

**Why `KernelRef.kernel_ref_kind` (C-3 rationale, approved Checkpoint E1,
2026-07-20).** WP-D distinguishes `Authority.KERNEL_DTS` and
`Authority.KERNEL_BINDINGS` because their freshness policies differ
(`AuthorityTTL` in `FreshnessPolicy`). Without a discriminator on the
`KernelRef` variant, WP-F would have to re-derive DTS-vs-BINDINGS from the
`path` field (fragile: kernel trees relocate; a path-based heuristic could
misclassify a bindings header under `Documentation/devicetree/bindings/`
after a subtree move). The `kernel_ref_kind: Literal["dts", "bindings"]`
field is Option A from `WP_E_DESIGN_REVIEW.md` §3 C-3 — a single required
field on the existing variant is minimal and additive, whereas Option B
(split into `KernelDTSRef` and `KernelBindingsRef`) would double the parser
branches for no expressiveness gain. The discriminator is required (not
`None`-able) because a `KernelRef` that names neither DTS nor bindings has
no meaningful freshness contract with WP-D.

**Rationale for a tagged union over a free-form dict.** §4.3 already argues
this: "no source can slip in with an unverifiable 'trust me' string." The
stricter typing here (each variant is its own frozen dataclass with named
required fields) makes the constraint enforceable at construction rather than
at review time.

---

## 8. ReviewRecord Design

```python
class ReviewDecision(str, Enum):
    PROVIDE = "provide"                      # reviewer supplied a value where none existed
    RESOLVE_CONFLICT = "resolve_conflict"    # reviewer chose a winner among conflicting values
    OVERRIDE = "override"                    # reviewer replaced a non-conflicting existing value
    REJECT = "reject"                        # reviewer withdrew a previously accepted MANUAL fact

@dataclass(frozen=True)
class ReviewRecord:
    reviewer_id: str                         # e.g. "asmith@..." or "power-team"
    reviewer_role: str                       # e.g. "power-team-owner"
    requested_at: datetime                   # tz-aware UTC
    answered_at: datetime                    # tz-aware UTC; must be >= requested_at
    question: str                            # verbatim ask (why this manual fact is needed)
    answer: str                              # verbatim response
    ticket_url: str | None                   # tracker link (jira, etc.)
    email_msgid: str | None                  # RFC 5322 Message-ID (with angle brackets)
    doc_ref: str | None                      # design review / decision doc path or URL
    decision: ReviewDecision
    expires_at: datetime | None              # revalidation deadline; None = no expiry
    supersedes_provenance_index: int | None  # index into provenance_chain of what this replaces

    def __post_init__(self) -> None:
        # 1. reviewer_id, reviewer_role, question, answer non-empty.
        # 2. answered_at >= requested_at.
        # 3. expires_at, if set, > answered_at.
        # 4. supersedes_provenance_index, if set, is non-negative.
        # 5. decision == RESOLVE_CONFLICT implies supersedes_provenance_index is not None.
        # 6. decision == REJECT implies supersedes_provenance_index is not None.
        ...

    @property
    def has_evidence(self) -> bool:
        # Used by FactValue construction to decide whether to cap confidence
        # per PHASE3_ARCHITECTURE.md §6.2 rule "no ticket/email/doc → cap at 0.4".
        return any((self.ticket_url, self.email_msgid, self.doc_ref))

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at
```

**Enforcement points.**

- `FactValue.__post_init__` rejects the value if
  `authority_class == MANUAL and review is None`.
- `FactValue.__post_init__` caps confidence at 0.4 if
  `review is not None and not review.has_evidence` —
  `PHASE3_ARCHITECTURE.md` §6.2 verbatim.
- `Registry.load()` treats a MANUAL fact whose `review.is_expired(now)` is
  True as still-loaded but tagged with a load warning; freshness/coverage
  handling is WP-F's problem.
- `Registry.get()` returns `None` for a fact whose top-of-chain provenance
  entry has `is_revocation=True` (a revoked fact). The chain remains in the
  file for audit; `iter_facts()` omits the fact; only the `FactValue`
  accessor path hides it. See §6 and B-4 (Checkpoint E0, 2026-07-20).

**Rationale for `supersedes_provenance_index` rather than a `FactProvenance`
reference.** The index makes the JSON self-contained (no cross-record
pointers). It is validated at load against the actual chain length — an
out-of-range index surfaces as `RegistryStatus.PARTIAL` with a load warning,
not a hard raise.

---

## 9. Locking Strategy

**Requirement.** Concurrent writers must not interleave writes and corrupt the
file. Readers must not block writers.

**Mechanism.** POSIX advisory file lock via `fcntl.flock(LOCK_EX | LOCK_NB)`
on `<target>.lock`. The lock file is a zero-byte sentinel created on first
write and never deleted (its presence carries no state; only the kernel-level
lock matters).

**API.**

```python
class locking:
    @contextmanager
    def registry_write_lock(target: str, *, timeout_s: float = 5.0) -> None:
        """Acquire an exclusive advisory lock on <target>.lock.

        Raises RegistryLockError if the lock cannot be acquired within timeout_s.
        The lock is released on context exit whether normally or on exception.
        """
```

**Writer flow (approved Checkpoint E1, 2026-07-20 — C-1 sidecar-first + C-5
stale-tmp step 0).**

0. **Stale-tmp cleanup (C-5).** Before acquiring the lock, remove any
   `<target>.json.tmp.*` and `<target>.registry.hash.tmp.*` under
   `audio_bu_skill/state/fact_registry/` whose mtime is older than
   `STALE_TMP_TTL_SEC` (60 seconds; defined in
   `orchestrator/fact_registry/constants.py`). Rationale: this step covers
   the leftover from a prior writer that crashed between steps 4 and 7
   (T-E19). 60s is longer than any legitimate write on any filesystem WP-E
   targets and shorter than any operator's patience. Removal is best-effort
   — an unremovable tmp file (permission denied) is logged to
   `load_warnings` on the resulting Registry but does not fail the write.
   Step 0 runs OUTSIDE the lock because the tmp files are per-process
   (named after `<pid>`) and no in-flight writer's own tmp file is old
   enough to hit the TTL. `STALE_TMP_TTL_SEC` is a compile-time constant;
   changing it requires a code review, not a config knob.
1. Enter `registry_write_lock(target)`.
2. Read current JSONL into memory (may fail with corrupt → writer still holds
   the lock and can decide policy).
3. Apply mutation (append/replace).
4. Serialise to `<target>.json.tmp.<pid>`; `fsync` the file descriptor. Do
   **not** rename yet.
5. Compute sha256 over the tmp file's bytes.
6. Write the sidecar contents to `<target>.registry.hash.tmp.<pid>`;
   `fsync`; `os.replace()` it over `<target>.registry.hash`. **Sidecar
   lands first (C-1).**
7. `os.replace()` `<target>.json.tmp.<pid>` over `<target>.json`.
8. `fsync` the containing directory (`audio_bu_skill/state/fact_registry/`)
   to make both renames durable across a crash.
9. Exit context → release lock.

**Why sidecar-first (C-1 rationale, approved Checkpoint E1, 2026-07-20).**
The prior order (JSONL first, sidecar second) opened R-E8's race window:
between steps 7 and 6-if-swapped, a reader would observe new JSONL + old
sidecar → the hash of the new bytes would not match the stale sidecar. With
sidecar-first, the failure mode inverts: a reader that lands between step 6
and step 7 sees new sidecar + old JSONL → hash of the old bytes does not
match the new sidecar → `HASH_MISMATCH` triggers the 50ms retry (see reader
flow below). The retry then observes the completed step 7 and succeeds
with `RegistryStatus.OK`. Strictly better than the prior ordering: the same
race that used to poison the load now self-heals via the retry.

**Reader flow.** No lock. `load()` reads `<target>.json` and its sidecar. If
the two are inconsistent (sidecar hash does not match the JSONL bytes), the
reader applies the **retry policy** (approved Checkpoint E0, 2026-07-20 — B-3):

1. On first observation of a hash mismatch, sleep 50 milliseconds.
2. Re-read `<target>.json` and its sidecar from disk.
3. Recompute the JSONL hash and compare against the freshly-read sidecar.
4. If the two agree, the load proceeds with `RegistryStatus.OK` (or whatever
   status the record-level parse produced — the retry only clears the
   hash-mismatch precedence tier).
5. If they still disagree, the load returns `RegistryStatus.HASH_MISMATCH`
   with the delta captured in `load_warnings`.

The retry is **strictly read-only** — no lock is acquired, no bytes are
written, no state on disk is mutated. Rationale: the common cause of a
transient mismatch is the ~microsecond window between the writer's sidecar
rename and JSONL rename (see §9 writer flow ordering and R-E8); one 50ms
sleep is longer than any such window on any filesystem WP-E targets. A
persistent mismatch after retry is a genuine coherence failure that the
operator must see, not a transient race the loader should paper over.

**Concurrency posture for Phase-3A.**

- The onboarding pipeline is single-writer at report render time. The lock is
  defense-in-depth against a test runner or an inadvertent parallel manual
  invocation.
- The 5s default timeout is long enough that a normal single-writer flow
  never times out but short enough that a wedged process surfaces quickly.
- No cross-host concurrency support. Single-machine only. Matches Phase-3A
  scope (`R-E1` in `PHASE3_ARCHITECTURE.md` §8).

**Rationale for advisory over mandatory locking.** POSIX mandatory locks
require filesystem support (`mand` mount option, often unavailable on NFS or
CI runners). Advisory locking is portable and, since all writers go through
the same `store.py` path, sufficient.

**What locking does not cover.**

- A process that crashes while holding the lock leaves a stale `.lock` file.
  Because it is only a sentinel and the actual lock is the kernel-level
  `flock`, no cleanup is needed — the kernel releases the lock when the file
  descriptor closes on process termination.
- Locking does not extend to the sidecar hash. Because sidecar writes are
  within the lock scope, they are transitively protected.

---

## 10. Serialization Format

**Choice.** JSON Lines (JSONL), UTF-8, LF line endings, one fact record per
line.

**Justification, briefly.**

| Option | Verdict |
| --- | --- |
| Single JSON document | Rejected. Whole-file rewrite on every append. Diff-unfriendly. Corruption of one byte kills the whole file. |
| **JSONL (chosen)** | Line-append friendly. One bad line = one bad fact, not a dead registry. Trivial to git-diff. Standard `json.dumps` per line. |
| YAML | Rejected. Human-editable, but ambiguous parsing (`no` as bool vs string), and slower. Manual edits should go through the API, not by hand. |
| SQLite | Rejected for Phase-3A. Overkill for < 500 rows per target. Binary format defeats git-diff review. Reconsider when we hit multi-target aggregation (Phase-3C). |
| Protobuf / MessagePack | Rejected. Machine-readable only. Bring-up review is human-first. |

**Header line (schema-version marker).** First non-comment line MUST be
`{"__type": "registry_header", "schema_version": "...", "target": "...", ...}`.
Rationale: co-locating schema version with the data (rather than a separate
metadata file) means a moved/copied registry can never end up without its
version.

**Encoding rules.**

- `datetime`: ISO 8601 with explicit `Z` suffix (UTC only). No naive
  timestamps, no local timezones.
- `Enum`: serialised as its `.value` (all WP-D enums are `str` subclasses,
  so this is a plain string).
- `SourceRef`: variant discriminated on `kind`.
- `None`: serialised as JSON `null`.
- `bytes`: forbidden. If a future value needs binary blob storage (unlikely
  in Phase-3A), it must be base64-wrapped in a struct with a discriminator.
- Sort order: writer sorts fact records by
  `(domain, family, subject, attribute)`. Within a record,
  `json.dumps(sort_keys=True)`. This makes byte-level diffs meaningful.

**Line length.** No hard cap. Facts with large provenance chains are
permitted; the human-review payoff outweighs any parser concern.

**Comments and blank lines on rewrite (C-4, approved Checkpoint E1, 2026-07-20).**
The reader (§3, §9) tolerates `#`-prefixed lines and blank lines and skips
them without emitting a warning. The writer never emits either and does not
preserve any across a load-then-save cycle. If an operator hand-edits the
JSONL to add a `#` comment or a blank line, the next `Registry.load()`
succeeds with status `OK`, but the following `append_provenance()` — which
rewrites the whole file per §9 — will drop those lines. Post-save, the
JSONL contains only the header line and one record per fact.

**Why forbid comment/blank-line round-trip.** Preserving a `#` comment
across a rewrite requires associating it with a following record and
regenerating it in the right slot after the writer's canonical sort. That
is a small feature with a disproportionate parser cost, and it would be
the first time the writer had to reason about non-record lines. The
weaker guarantee (comments survive load; not save) captures the whole
value the read-side rule was designed to provide — an operator can drop
a note next to a suspicious line before opening a ticket — without
saddling the writer with content it does not own. **T-E15b** in §13
locks the contract in.

**Sort-on-write and legacy files.** As noted above, the writer sorts
fact records by `(domain, family, subject, attribute)` on every save.
A legacy registry that loads without errors but was written out of
canonical order will be reordered on the next save. This is idempotent
thereafter and does not change fact identity, but the reorder shows up
in a git-diff and is expected.

**Sidecar hash.** `<target>.registry.hash` contains a single line:
`sha256:<64hex>  <target>.json`. Computed over the exact bytes of
`<target>.json`. A mismatch at load time surfaces as
`RegistryStatus.HASH_MISMATCH` — never a raise; WP-F treats this as evidence
to render "registry may be corrupt" in the report and to skip coverage
evaluation for that run.

---

## 11. Versioning Strategy

**Header field.** `schema_version` in the file header. String-typed,
semver-shaped: `"MAJOR.MINOR.PATCH"`.

**Compatibility policy.**

- **MAJOR bump.** Breaking change to the record shape or to a validator.
  Loaders refuse to open a MAJOR mismatch and return
  `RegistryStatus.UNSUPPORTED_SCHEMA`.
- **MINOR bump.** Additive change: a new optional field, a new SourceRef
  variant, a new AuthorityClass value. Loaders open older MINOR files and
  tolerate missing new fields (default them). Loaders **refuse** newer MINOR
  than they know about — this is deliberate; older code opening newer
  registries would silently drop fields it does not understand. The rule for
  MINOR is "loader knows exactly this version or lower".
- **PATCH bump.** Documentation-only or field renaming that preserves
  on-wire layout via aliases. Loaders open across PATCH freely.

**Phase-3A ships `schema_version = "1.0.0"`.**

**Supported set constant.**

```python
# audio_bu_skill/orchestrator/fact_registry/constants.py
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0.0"})
MIN_TOLERABLE_MINOR: str = "1.0"   # opens 1.0.x, refuses 1.1.x and 2.x.x
```

**Rejection surface.**

- Newer-than-known MAJOR or newer MINOR → `RegistryStatus.UNSUPPORTED_SCHEMA`
  at load. File is not modified. `Registry.get()` returns `None` for all keys.
- Unknown field within a known MINOR (should not happen; would indicate the
  file was hand-edited) → per-record warning captured in `load_warnings`,
  record dropped.

**Rationale.** Explicit refusal of newer versions is the load-time defense
against a Phase-3B-authored registry being opened by a Phase-3A binary that
would silently discard new fields (e.g., a Phase-3B "auto-refresh trigger"
field going missing on rewrite would break the acquisition invariant). Better
to refuse than to silently downgrade.

**MAJOR-bump note for the provenance-chain cap (C-2, approved Checkpoint
E1, 2026-07-20).** The provenance-chain length cap
`MAX_PROVENANCE_CHAIN_LEN = 100` (see §3.2 and `constants.py`) is a
version-bound invariant: raising it — say to 200 — requires a MAJOR
version bump, not a MINOR one. Reason: a MINOR raise would produce a
registry that older loaders would open (since MINOR is additive under
this policy) and would **still enforce the old 100-entry cap on
append**, so on the next write they would refuse chains that a newer
writer had legitimately produced. Worse, an older reader would happily
iterate a 150-entry chain without knowing the cap has moved — invariant
7 (last-of-chain match) still holds, but the operator-visible contract
"chains are bounded" silently shifts under them. A MAJOR bump forces
loaders that predate the change to return `UNSUPPORTED_SCHEMA` at load
time, which is the correct failure surface for a rule change that
readers cannot enforce transparently.

---

## 12. Migration Strategy

**Phase-3A stance: no migration.** Registries do not exist for legacy targets.
The registry-absent stub (`PHASE3_ARCHITECTURE.md` §7.3) is the correct
output.

**Future migrations are code, not data.**

- When a MAJOR bump happens, ship an explicit migration script
  (`audio_bu_skill/tools/migrate_registry_v1_to_v2.py`) that: reads the old
  registry, writes a new one under a `.v2.json` name, keeps the `.v1.json`
  for audit, and only replaces the canonical name after user confirmation.
- Migration scripts are **never** invoked implicitly by the runtime. A
  registry with an unsupported schema returns `UNSUPPORTED_SCHEMA` and the
  operator is directed by report text to run the migration tool.

**Backfill (Phase-3B scope, out of Phase-3A).** A future WP will populate
registries from existing evidence directories on demand. That work is
explicitly deferred (`PHASE3_ARCHITECTURE.md` §9 item 5). WP-E must be
**backfill-ready** — the `append_provenance` API is the same call path a
backfill would use — but ships nothing that runs backfill.

**What WP-E does at load for a corrupt / malformed file.**

- Corrupt JSONL (a single un-parseable line): load returns
  `RegistryStatus.PARTIAL`, `load_warnings` contains a per-line diagnostic,
  `get()` still serves the successfully-parsed facts.
- Missing header: load returns `RegistryStatus.CORRUPT`, `get()` returns
  `None` for all keys, file is **not** deleted or rewritten.
- Missing sidecar: load returns `RegistryStatus.HASH_MISMATCH` with a
  warning ("sidecar missing"). Recovery is a manual step (re-hash tool,
  deferred).

**Non-goal: automatic recovery.** WP-E does not truncate, quarantine, or
repair corrupt files. A registry that is broken enough to fail loads is a
matter for the operator; the diagnostic is what WP-E owes them.

---

## 13. Tests

Test IDs are declarative for review; the numbering below is the target set.

**`test_fact_registry_models.py` (T-E1 .. T-E10).**

- T-E1: `FactKey.parse(as_string(fk)) == fk` round-trip for a curated set.
- T-E2: FactKey validation rejects malformed inputs (empty parts, disallowed
  chars, wrong domain).
- T-E3: FactValue rejects `authority_class == MANUAL` when `review is None`.
- T-E4: FactValue rejects `authority_class == INFERRED` when
  `authority != Authority.INFERRED`.
- T-E5: FactValue rejects `authority_class == MANUAL` when
  `authority != Authority.MANUAL`.
- T-E6: FactValue caps confidence at 0.4 when `review.has_evidence is False`.
- T-E7: FactValue rejects a `captured_at` that is naive (no `tzinfo`).
- T-E8: FactValue rejects `confidence` outside `[0.0, 1.0]`.
- T-E9: FactValue rejects when the last provenance entry does not match
  top-of-chain fields.
- T-E10: FactValue enforces the `authority↔source_ref.kind` cross-check for
  all 8 authority values.

**`test_fact_registry_review.py` (T-E23 .. T-E28).**

- T-E23: ReviewRecord rejects `answered_at < requested_at`.
- T-E24: ReviewRecord rejects `expires_at <= answered_at`.
- T-E25: `ReviewRecord.has_evidence` is True iff any of the three evidence
  pointers is set.
- T-E26: `decision == RESOLVE_CONFLICT` requires
  `supersedes_provenance_index`.
- T-E27: `decision == REJECT` requires `supersedes_provenance_index`.
- T-E28: `is_expired(now)` respects a datetime `now` and returns False when
  `expires_at is None`.

**`test_fact_registry_source_refs.py` (T-E29 .. T-E33).**

- T-E29: Each of the 7 SourceRef variants round-trips through JSON.
- T-E30: `parse()` raises on unknown `kind`.
- T-E31: `parse()` raises on missing required fields per variant.
- T-E32: `IPCATCachedRef.sha256` rejects non-64-hex strings.
- T-E33: `KernelRef.commit` rejects non-40-hex strings; requires
  `line_start <= line_end`; requires `kernel_ref_kind` to be `"dts"` or
  `"bindings"` (rejects any other value including `None`) and asserts
  round-trip preservation of the discriminator through JSON. (C-3,
  2026-07-20)

**`test_fact_registry_store.py` (T-E11 .. T-E22).**

- T-E11: Empty registry file → `Registry.status == RegistryStatus.ABSENT`;
  `iter_facts()` yields nothing.
- T-E12: Write one fact, load it back, byte-identical.
- T-E13: Append a second provenance entry to an existing fact → chain length
  grows by one; top-of-chain fields update; earlier entries unchanged.
- T-E14: Sidecar hash matches after every write; mutating `<target>.json`
  externally → next load surfaces `RegistryStatus.HASH_MISMATCH`.
- T-E14b: A **mid-write transient** hash mismatch (sidecar and JSONL briefly
  disagree during the writer's rename window) is transparently recovered by
  the reader's 50ms retry — the load returns `RegistryStatus.OK`, no
  warnings about hash mismatch, and no mutation to disk. (B-3, 2026-07-20)
- T-E14c: A **persistent** hash mismatch (sidecar and JSONL still disagree
  after the 50ms retry) surfaces as `RegistryStatus.HASH_MISMATCH` with the
  delta captured in `load_warnings`. The retry attempt itself performs no
  writes. (B-3, 2026-07-20)
- T-E15: Truncated JSONL (one line half-cut) → load returns
  `RegistryStatus.PARTIAL`; other records are served.
- T-E15b: Hand-editing the JSONL to add a `#` comment or a blank line
  survives the next load (status `OK` — the comment/blank line is
  skipped) but does not survive the next save — post-save the file
  contains no `#`-prefixed lines and no blank lines, only the header
  and one record per fact. (C-4, 2026-07-20)
- T-E16: Missing header → `RegistryStatus.CORRUPT`; file is not modified;
  `get()` returns `None` for all keys.
- T-E17: `schema_version = "999.0.0"` (unsupported) →
  `RegistryStatus.UNSUPPORTED_SCHEMA`; no writes possible.
- T-E18: Two writers acquire the lock sequentially; a third attempts with
  `timeout=0.1` → raises `RegistryLockError`.
- T-E19: Writer crash during temp-file write leaves
  `<target>.json.tmp.<pid>` behind but does not corrupt `<target>.json`; next
  writer removes stale tmp files older than 60s.
- T-E20: Records are sorted on write; two writes producing the same logical
  content yield byte-identical output.
- T-E21: MANUAL fact without review → rejected at save time (never
  persisted).
- T-E22: A revoked MANUAL fact (top-of-chain provenance entry has
  `is_revocation=True`; that entry's `review.decision == REJECT`) is loaded
  but `get()` returns `None`; `iter_facts()` omits it; the full chain
  (including the revocation entry and every prior non-revocation entry)
  remains in the file for audit. (B-4, 2026-07-20)
- T-E22c: `append_provenance()` on a chain of length
  `MAX_PROVENANCE_CHAIN_LEN` (= 100) raises `RegistryWriteError`; the
  chain, the JSONL file, and the sidecar hash are unchanged. The lock
  is released before the exception surfaces. (C-2, 2026-07-20)
- T-E22d: `append_provenance()` on a chain of length 99 accepts one
  more append; the resulting chain has length 100 and a subsequent
  `append_provenance()` on that chain raises `RegistryWriteError`
  (boundary — proves the cap is inclusive of 100, not exclusive).
  (C-2, 2026-07-20)

**Fixture registries under `tests/fixtures/fact_registry/`.**

- `golden_registry_v1.jsonl` — one line per fact, three authorities present,
  used by T-E12.
- `malformed_missing_review.jsonl` — used by T-E21.
- `conflict_chain.jsonl` — two provenance entries with divergent values;
  used by WP-F later, and by an in-WP-E test verifying that the chain is
  preserved untouched.
- `stale_manual.jsonl` — an expired review; used to prove WP-E does not
  filter expired facts (WP-F does).
- `newer_schema.jsonl` — `schema_version = "999.0.0"`; used by T-E17.

**Explicit non-tests (deferred to WP-F).**

- Coverage state, conflict state, freshness state — none of these are
  computed by WP-E and no WP-E test asserts on them.
- No test invokes `main.py`, no test runs the onboarding pipeline, no test
  writes into `targets/*`.

**Test count target.** ~33 tests; ~250–350 lines total; runs in under 500ms
wall-clock. Adds one module to the module-count sweep (currently 37; WP-E
raises it to 38).

---

## 14. Risks

**R-E1: Concurrent writers.** *Mitigation:* POSIX advisory lock. *Residual:*
NFS locking has known edge cases; Phase-3A does not commit to NFS. If a
future user hosts state on NFS, the lock will still be advisory-safe but may
exhibit slow-lock symptoms — the diagnostic is a lock timeout, not silent
corruption.

**R-E2: Storage schema drift.** *Mitigation:* explicit `schema_version` with
a supported-set constant; refusal of newer versions at load. *Residual:* a
future MAJOR bump requires an explicit migration tool; if that tool is not
shipped, older binaries will refuse newer registries — desired behavior, but
requires operator awareness.

**R-E3: Silent laundering of manual facts.** *Mitigation:* three-layer
defense — (1) MANUAL requires non-null review, (2) review without evidence
pointers caps confidence at 0.4, (3) review structure itself validated
(`answered_at >= requested_at`, decision↔supersedes coupling). *Residual:* a
reviewer can still supply a low-effort review with a bogus `ticket_url`.
WP-E cannot detect that; the report renders the `reviewer_id` + ticket for
operator audit (`PHASE3_ARCHITECTURE.md` §6.5).

**R-E4: Chain-value/top-of-chain drift.** *Mitigation:* T-E9 asserts
append-only invariant at every FactValue construction; the store enforces
via the model, not just by convention.

**R-E5: Corruption in the sidecar without corresponding corruption in the
JSONL.** *Mitigation:* load returns `HASH_MISMATCH` and refuses to serve;
operator has an explicit signal. *Residual:* recovery is manual (re-hash
tool) — acceptable in Phase-3A given the small state size.

**R-E6: Import-graph contamination.** *Mitigation:* WP-E imports nothing
from `audio_bu_skill.orchestrator.runners`, `audio_bu_skill.orchestrator.main`,
or `audio_bu_skill.targets`. Enforced by a dedicated test that asserts on
`sys.modules` after `import audio_bu_skill.orchestrator.fact_registry`.
Rationale: WP-E must remain landable without any runtime coupling per the
"advisory-only" invariant.

**R-E7: JSON `Mapping`/`Sequence` type of `value` field lets someone stash
arbitrary objects.** *Mitigation:* validate at construction that `value`
round-trips through `json.dumps` / `json.loads` without loss. *Residual:*
trivially bypassed by someone who inserts a dict that survives serialisation
but does not map to a real fact — this is out of scope; the schema is a data
contract, not a semantic gatekeeper.

**R-E8: Race between load-time sidecar check and next writer.** A read can
see a stale sidecar during the microseconds between JSONL rename and hash
rename. *Mitigation:* writer writes sidecar first, then renames JSONL;
loader always re-reads sidecar after reading JSONL; a `HASH_MISMATCH`
triggers a single retry with a 50ms sleep. *Residual:* very rare in
Phase-3A single-writer usage. Documented as a known artifact.

**R-E9: Tests slow.** *Mitigation:* fixtures live under
`tests/fixtures/fact_registry/`; tempdir usage instead of touching
`audio_bu_skill/state/`. Wall-clock target < 500ms.

**R-E10: Feature creep — pressure to inline WP-F reasoning ("just this one
derived field") into WP-E.** *Mitigation:* explicit non-goal in §1. If a
design conversation strays into `freshness_state` or `coverage_state` at
load, escalate to a design review rather than expanding scope.

---

## 15. Exit Criteria

Concrete, verifiable, tied to the `PHASE3_ARCHITECTURE.md` §10 pre-merge
checklist.

1. **Full test suite green.** All existing tests + all new WP-E tests pass.
   Module count sweep advances from 37 to 38 without regression elsewhere.
   No test under `orchestrator/`, `runners/`, `targets/`, or existing
   `tests/` files is modified.
2. **Round-trip test.** T-E12 shows a written fact reads back
   byte-identical.
3. **Append-only test.** T-E13 shows the chain grows on re-write and prior
   entries are preserved.
4. **MANUAL discipline tests.** T-E3, T-E6, T-E21 pass. A MANUAL fact
   without review cannot be persisted; one without evidence has confidence
   capped at 0.4; a revoked fact is not returned by `get()`.
5. **Lock test.** T-E18 shows the lock is honored; a second writer errors
   with `RegistryLockError`, not silent corruption.
6. **Corruption-tolerance tests.** T-E14, T-E15, T-E16, T-E17 all pass.
   Corrupt / partial / missing-header / unsupported-version registries
   surface via `RegistryStatus` — no test raises out of `Registry.load()`.
7. **Import-graph test.** WP-E imports nothing from
   `audio_bu_skill.orchestrator.runners`, `.main`, or
   `audio_bu_skill.targets`. Asserted via a dedicated test.
8. **Advisory-only invariant.**
   `git grep -l 'fact_registry' -- audio_bu_skill/orchestrator/main.py audio_bu_skill/orchestrator/runners/ audio_bu_skill/targets/ audio_bu_skill/skills/`
   returns nothing. WP-E is inert on the pipeline.
9. **`case.generated.py` NOT promoted** in any test or manual run. Verified
   by absence of the string `case.py` in any WP-E test's mutation surface
   and by explicit `git status` check post-merge.
10. **WP7 verdict on Nord unchanged.** No WP-E test writes into
    `state/fact_registry/nord-iq10.json`, so no Nord onboarding run is
    affected.
11. **IPCAT tri-state on Nord unchanged.** Same argument.
12. **Grep-parity check.**
    `grep -n "NEEDS_REVIEW\|NO_IPCAT_EVIDENCE\|no_source_facts_available\|Overall verdict"`
    on a rendered Nord report finds the same lines before and after WP-E
    lands.
13. **Registry gitignore in place.**
    `audio_bu_skill/state/fact_registry/.gitignore` ignores `*.json`,
    `*.hash`, `*.lock`; README and `.gitignore` themselves are checked in.
14. **Model documentation.** Each of `FactKey`, `FactValue`,
    `FactProvenance`, `SourceRef` variants, and `ReviewRecord` carries a
    module-level docstring cross-referencing the corresponding section of
    `PHASE3_ARCHITECTURE.md`.
15. **Nothing else changed.** Whitelist-staged commit; PR-diff review
    confirms no drift into unrelated files.

**Exit is not:**

- A WP-F integration demo — WP-F is a separate WP.
- A populated Nord registry — Phase-3A ships an empty state directory.
- Any change to `case.py`, `case.generated.py`, `main.py`, or any runner.

---

## 16. Open Questions

Items that surfaced during design and remain unresolved. None are blocking
review, but each should be closed before implementation begins.

**OQ-1 — Revocation sentinel for `FactProvenance.value`.** **RESOLVED via
B-4 at Checkpoint E0 (2026-07-20). See §6 (`FactProvenance.is_revocation:
bool`) and §5 invariant 7 (revocation branch).** — Original text preserved
for audit: §6 uses
`value == None` as the revocation sentinel, but `None` is also a valid
JSON-serialisable value (a nullable attribute). Alternatives: (a) reserve a
dedicated `is_revocation: bool` field on `FactProvenance`; (b) introduce a
distinct `FactRevocation` record type in the JSONL stream. Recommendation:
(a), because it keeps the on-disk record shape uniform. Decision needed.

**OQ-2 — SoC-aware catalog loading.** `load_catalog(soc_override=None)`
exists in WP-D but WP-E's `Registry` does not currently accept an `soc`
parameter. Should the registry file name embed the SoC
(`nord-iq10.sa8797p.json`) or should the SoC be a header field only?
Recommendation: header field only, keep the file name target-scoped.
Decision needed.

**OQ-3 — Cross-writer sidecar coherence.** **RESOLVED via C-1 at
Checkpoint E1 (2026-07-20). See §9 writer flow sidecar-first order
(steps 4–8) and §9 rationale paragraph "Why sidecar-first".** — Original
text preserved for audit: R-E8 documents a rare race
between sidecar and JSONL renames. Is a 50ms single-retry sufficient, or
should the writer flip the write order to "write JSONL last so a mismatch
window becomes zero"? Recommendation: keep hash-first, JSONL-last (a
mismatch then means the JSONL is genuinely stale, which is the safer
diagnostic). Decision needed.

**OQ-4 — Manual-fact ticket URL validation.** Should WP-E validate that
`ticket_url` matches an internal tracker regex, or accept any URL-shaped
string? Recommendation: any URL-shaped string; regex-locking to Jira
creates friction for docs/design-review pointers. Decision needed.

**OQ-5 — Concurrency scope beyond Phase-3A.** If Phase-3B moves to
multi-writer (e.g., a live IPCAT acquisition thread and a manual-review CLI
running simultaneously), does the current per-target advisory lock suffice
or do we need per-fact locking? Recommendation: defer until Phase-3B
surfaces a concrete concurrent-writer scenario. Decision needed at
Phase-3B design time, not now.

**OQ-6 — Line-length cap.** **RESOLVED via C-2 at Checkpoint E1
(2026-07-20). See §3.2 `append_provenance` docstring (names
`MAX_PROVENANCE_CHAIN_LEN = 100`), §11 MAJOR-bump note, and §13
T-E22c/T-E22d.** — Original text preserved for audit: §10 says "no hard
cap". Should there be a
soft warning at, e.g., 64 KiB per line to catch runaway provenance chains
(a stuck acquisition loop that appends the same entry N times)? WP-E can
also enforce a chain-length cap at write time. Recommendation: cap
provenance-chain length at 100 entries with a `RegistryWriteError` on
exceed; no cap on line length itself. Decision needed.

**OQ-7 — Test-fixture ownership of expired reviews.** T-E28 tests
`is_expired(now)` as a pure function. Should there additionally be a
store-level test asserting that expired MANUAL facts still appear in
`iter_facts()`? Recommendation: yes, add T-E22b — otherwise a future
"helpful" filter in `iter_facts()` could break WP-F's expected behavior
without any test noticing. Decision needed.

**OQ-8 — Documentation cross-linking.** Should this document be linked
from `PHASE3_ARCHITECTURE.md` §8 (WP-E section) as the canonical spec, or
should §8 remain the canonical spec and this document be marked
"informative"? Recommendation: link from §8 and make this document the
canonical spec — §8 is a landscape scan, not a component-level spec.
Documentation-only change, deferred to implementation-start commit.

---

## 17. Revised Ready-to-Implement Checklist

Revised at Manual Verification Checkpoint E0 (2026-07-20) and re-revised
at Checkpoint E1 (2026-07-20). All four Section B blockers and all five
Section C strongly-recommended items from `WP_E_DESIGN_REVIEW.md` §2/§3
are resolved and encoded in this document. Section D polish items remain
open as non-blocking follow-up.

| Item | Status                                    | Blocker for implementation? | Encoded in                                  |
| ---- | ----------------------------------------- | --------------------------- | ------------------------------------------- |
| B-1  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                | §3.1 (RegistryStatus enum + precedence rule) |
| B-2  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                | §3.2 (Registry class API — immutable)       |
| B-3  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                | §9 reader flow (1-retry / 50ms) + §13 T-E14b/T-E14c |
| B-4  | **Resolved (Checkpoint E0, 2026-07-20)**  | No (was Yes)                | §5 invariant 7 (revocation branch) + §6 `is_revocation: bool` + §8 revocation accessor + §13 T-E22 |
| C-1  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) | §9 writer flow steps 4–8 (sidecar-first) + §9 "Why sidecar-first" rationale + §16 OQ-3 (marked RESOLVED) |
| C-2  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) | §3.2 `append_provenance` docstring (names `MAX_PROVENANCE_CHAIN_LEN = 100`) + §11 MAJOR-bump note + §13 T-E22c/T-E22d + §16 OQ-6 (marked RESOLVED) |
| C-3  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) | §7 `KernelRef.kernel_ref_kind: Literal["dts", "bindings"]` discriminator + §7 authority↔SourceRef mapping table + §7 "Why `KernelRef.kernel_ref_kind`" rationale + §13 T-E33 (discriminator round-trip) |
| C-4  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) | §10 "Comments and blank lines on rewrite" rule + §10 "Why forbid comment/blank-line round-trip" rationale + §13 T-E15b |
| C-5  | **Resolved (Checkpoint E1, 2026-07-20)**  | No (was Strongly recommended) | §9 writer flow step 0 (stale-tmp cleanup with `STALE_TMP_TTL_SEC = 60`) — folded into the sidecar-first rewrite for C-1 |
| D-1  | Open                                      | No                          | (Deferred: IPCAT `query_id` origin)         |
| D-2  | Open                                      | No                          | (Deferred: §10 vs §12 sort-on-write note)   |
| D-3  | Open                                      | No                          | (Deferred: §15.14 depends on OQ-8)          |

**Implementation gate.** Sections B and C are closed. This document was
retagged from **"Design Approved For Review — B-1..B-4 Resolved"** to
**"Design Approved For Implementation"** at Checkpoint E1 (2026-07-20;
line 6). Implementation begins from this state. Section D items may land
alongside or after implementation as separate polish commits and do not
gate the start of WP-E code work.

**Deferred-work discipline.** No C-item remains "Open". All five are
encoded either inline in the section they modify (§3.2, §7, §9, §10,
§11, §13) or in §16 Open Questions with a **RESOLVED** preamble
pointing at the encoded location (OQ-3 for C-1; OQ-6 for C-2). Only
D-1..D-3 remain deferred as non-blocking polish; each carries an inline
"Open" row in the checklist above and a footnote reference to
`WP_E_DESIGN_REVIEW.md` §4. A subsequent verification checkpoint (E-D,
tentative) may close them explicitly; they may also be picked up as
part of routine implementation touch-ups without a formal checkpoint,
at reviewer discretion.

---

## 18. Manual Verification History

Append-only record of manual verification decisions on this document. Each
checkpoint records: the decision made, the reviewer who authorised it, the
absolute date, and the rationale grounded in prior review findings. The
history is the audit trail for "why does this doc say what it says today".

### Checkpoint E0 — Section B Blocker Resolution (2026-07-20)

Scope: resolve the four Section B blockers from
`WP_E_DESIGN_REVIEW.md` §2. Documentation only. No code, no commits, no
pushes.

| Decision                        | Reviewer            | Date       | Rationale |
| ------------------------------- | ------------------- | ---------- | --------- |
| **B-1** — RegistryStatus precedence: `CORRUPT > UNSUPPORTED_SCHEMA > HASH_MISMATCH > PARTIAL > OK` | Ajay Kumar Nandam | 2026-07-20 | The six-variant enum was inferable but unspecified. Precedence matters because a compound condition (e.g., corrupt file with a valid sidecar hash, or an unsupported-schema file with a partial parse) needs one deterministic status. The chosen order puts non-recoverable conditions (`CORRUPT`, `UNSUPPORTED_SCHEMA`) above coherence conditions (`HASH_MISMATCH`) above per-record parse conditions (`PARTIAL`). Rationale: an operator cannot meaningfully act on a hash mismatch inside a file with no valid header; a partial-parse warning inside an unsupported-schema file is noise. Encoded in §3.1. |
| **B-2** — Registry is immutable; `append_provenance()` returns a new Registry instance | Ajay Kumar Nandam | 2026-07-20 | The pre-review §2 file-layout comment mentioned `load, save, append_provenance, get, iter` without specifying whether Registry mutates in place. Immutability was the recommended option in `WP_E_DESIGN_REVIEW.md` §2.B-2 because it (a) matches the append-only on-disk doctrine at the API boundary, (b) eliminates stale-in-memory-view bugs when a second reader holds an older Registry after another writer has appended, and (c) lets Registry be treated as a plain value across function boundaries. The `save()` method is intentionally not part of the public surface — persistence is an implementation detail of `append_provenance`. Encoded in §3.2. |
| **B-3** — HASH_MISMATCH retry: 1 retry, 50ms sleep, read-only; persistent mismatch surfaces as `HASH_MISMATCH` | Ajay Kumar Nandam | 2026-07-20 | §9 reader flow and §14 R-E8 disagreed on whether a retry existed at all. Adopted the R-E8 version verbatim. The 50ms figure is longer than any legitimate writer's sidecar-rename-then-JSONL-rename window on any filesystem WP-E targets, and shorter than any operator's patience; single retry (not exponential backoff) because a genuine persistent mismatch is a coherence failure that must reach the operator, not a race the loader should paper over. Retry is strictly read-only — no lock is acquired, no bytes are written. Encoded in §9 reader flow and §13 tests T-E14b (retry recovers) and T-E14c (persistent mismatch surfaces). |
| **B-4** — Revocation model: `FactProvenance.is_revocation: bool` | Ajay Kumar Nandam | 2026-07-20 | The prior design used a `note == "REVOCATION"` string sentinel that collided with §5 invariant 7 (last-of-chain must byte-match top-of-chain) and with §6's use of `note` as a free-text field. The `is_revocation: bool` field (`WP_E_DESIGN_REVIEW.md` §2.B-4 Option A) makes revocation a first-class boolean rather than an ambiguous string comparison, keeps the on-disk record shape uniform (no separate `FactRevocation` record type), and lets §5 invariant 7 branch cleanly between the non-revocation case (byte-for-byte match) and the revocation case (top-of-chain describes the last non-revocation entry, and `Registry.get()` returns `None`). Encoded in §5 invariant 7 (revocation branch), §6 (`is_revocation` field + `__post_init__` constraints + retrospective note), §8 (revocation accessor wording), and §13 T-E22 revision. |

**What this checkpoint did not authorise.** Implementation. Commits.
Pushes. Any change to code, tests, runners, `main.py`, `targets/*`,
`case.py`, `case.generated.py`, promotion logic, onboarding flow, IPCAT
tri-state, WP7 post-verify, or report rendering. All Section C
strongly-recommended items and Section D polish items remain open.

### Checkpoint E1 — Section C Disposition (2026-07-20)

Scope: review and disposition all five Section C strongly-recommended
items from `WP_E_DESIGN_REVIEW.md` §3. For each: accept-with-fix or
explicitly defer, with rationale and encoded-in pointers. On full
closure, retag this document's status from **"Design Approved For
Review — B-1..B-4 Resolved"** to **"Design Approved For
Implementation"**. Documentation only. No code, no commits, no pushes.

| Decision                        | Reviewer            | Date       | Rationale |
| ------------------------------- | ------------------- | ---------- | --------- |
| **C-1** — Accept-with-fix: sidecar-first writer order (sidecar rename precedes JSONL rename); §9 writer flow steps 4–8 rewritten accordingly, and a step 0 stale-tmp cleanup with `STALE_TMP_TTL_SEC = 60` (also C-5) added ahead of lock acquisition | Ajay Kumar Nandam | 2026-07-20 | The pre-review §9 order (JSONL renamed first, sidecar recomputed and renamed second) opened R-E8's window: a reader between the two renames sees new JSONL + old sidecar → hash mismatch. Flipping the order makes the failure mode strictly better: a reader between the two renames sees new sidecar + old JSONL → hash mismatch → the 1-retry (B-3) either sees the new JSONL and succeeds, or (if the writer aborted between renames) reports a genuine coherence failure the operator must resolve. The 100ms-order write cost is negligible against the R-E8 correctness win. `STALE_TMP_TTL_SEC` is a first-class named constant (not a magic number) with a footnote justifying "longer than any legitimate write, shorter than any operator's patience". Encoded in §9 writer flow (steps 0, 4–8), §9 "Why sidecar-first" rationale, §16 OQ-3 (marked RESOLVED). |
| **C-2** — Accept-with-fix: `MAX_PROVENANCE_CHAIN_LEN = 100` cap enforced in `append_provenance`; raising the cap requires a MAJOR schema bump | Ajay Kumar Nandam | 2026-07-20 | An unbounded provenance chain would let a stuck acquisition loop grow one target's registry without bound, undermining the "advisory-only, cheap to load" premise of Phase-3A WP-E. 100 is a round order-of-magnitude ceiling well above the largest plausible legitimate chain (a single subject reviewed by three parties across five refreshes is <20 entries). The MAJOR-bump requirement for raising the cap is the correctness point: a MINOR raise would produce registries that older loaders open successfully but enforce the old cap against, so older readers would iterate longer chains without enforcing the new cap on the write path — exactly the kind of silent drift MINOR-refuse policy exists to prevent. `RegistryWriteError` (not a silent truncation, not a warning) is the correct surface because reaching the cap means an upstream loop is misbehaving. Encoded in §3.2 `append_provenance` docstring (names the constant), §11 MAJOR-bump note, §13 T-E22c (raises at cap) and T-E22d (boundary: 99 accepts, 100 rejects), §16 OQ-6 (marked RESOLVED). |
| **C-3** — Accept-with-fix: add `KernelRef.kernel_ref_kind: Literal["dts", "bindings"]` discriminator (Option A from `WP_E_DESIGN_REVIEW.md` §3.C-3) | Ajay Kumar Nandam | 2026-07-20 | WP-D's `FreshnessPolicy` distinguishes `KERNEL_DTS` from `KERNEL_BINDINGS` because their TTLs differ (a DTS pin can rot when a schematic revs; a bindings entry rots when the kernel version does). Without a discriminator on the SourceRef, WP-F would have to re-derive DTS-vs-BINDINGS by string-inspecting `KernelRef.path` — fragile against path renames, invisible to serialization, and impossible to unit-test as a pure function. Option B (splitting into two variants) was rejected as more parser branches and a wider public surface for a distinction that is fundamentally a two-valued tag. The `Literal["dts", "bindings"]` type both documents and constrains the field at construction time. Encoded in §7 `KernelRef` dataclass (`kernel_ref_kind` field), §7 authority↔SourceRef mapping table (both `KERNEL_DTS` and `KERNEL_BINDINGS` rows point at the same dataclass with a distinguishing tag column), §7 "Why `KernelRef.kernel_ref_kind`" rationale, §13 T-E33 (discriminator round-trip). |
| **C-4** — Accept-with-fix: writer never emits `#` comments or blank lines; reader tolerates hand-edited comments/blanks (status `OK`) but they do not survive the next save | Ajay Kumar Nandam | 2026-07-20 | The pre-review §3/§10 split (reader tolerates `#` and blank; writer's behavior unspecified) invited operator surprise: someone hand-edits a registry to add a `# added by ops 2026-06-01` comment and loses it silently on the next `append_provenance`. Preserving comments through a canonical-sort-on-write would require associating each comment with a following record and regenerating post-sort — a disproportionate parser cost for a Phase-3A feature nobody has asked for. The chosen contract keeps the read path forgiving (hand-editing survives long enough to be useful for triage) but makes the death of the comment fully deterministic (the next save wipes it, `git diff` shows the removal). T-E15b locks the contract in the test suite. Encoded in §10 "Comments and blank lines on rewrite" rule, §10 "Why forbid comment/blank-line round-trip" rationale, §13 T-E15b. |
| **C-5** — Accept-with-fix: stale tmp file cleanup added as step 0 of §9 writer flow, using `STALE_TMP_TTL_SEC = 60` from `constants.py` | Ajay Kumar Nandam | 2026-07-20 | §13 T-E19 asserts "next writer removes stale tmp files older than 60s" but §9 writer flow did not describe the corresponding step, so T-E19 would have failed against a spec-compliant implementation. Folding cleanup into step 0 (before lock acquisition) makes it cheap: any leftover `<target>.json.tmp.*` from a crashed prior writer is unlinked before any coordination-sensitive work begins. 60s is not a magic number; it is the same `STALE_TMP_TTL_SEC` used by C-1's sidecar-first flow, defined in `constants.py`, footnoted as "longer than any legitimate write, shorter than any operator's patience". Making cleanup part of the C-1 rewrite (not a separate step 0 for C-5 alone) keeps §9 to one canonical flow rather than two overlapping ones. Encoded in §9 writer flow step 0 (folded into the sidecar-first rewrite for C-1); no new §13 test needed beyond the existing T-E19 which now has a spec to point at. |

**What this checkpoint did not authorise.** Implementation. Commits.
Pushes. Any change to code, tests, runners, `main.py`, `targets/*`,
`case.py`, `case.generated.py`, promotion logic, onboarding flow, IPCAT
tri-state, WP7 post-verify, or report rendering. Section D polish items
(D-1..D-3) remain open as non-blocking follow-up.

**Retag effected at this checkpoint.** Line 6 of this document advanced
from **"Design Approved For Review — B-1..B-4 Resolved (2026-07-20)"**
to **"Design Approved For Implementation (2026-07-20)"**. WP-E code
work is authorised to begin from this state, subject to the usual
Phase-3A discipline (no code touches promotion, onboarding, IPCAT
tri-state, WP7 post-verify, or report rendering; whitelist staging on
commit; full 38-module sweep must remain green).

**Next checkpoint (E2, tentative).** Implementation start. When the
first code lands (`store.py`/`models.py`/`review.py`/`locking.py`/
`hash.py`/`source_refs.py`/`errors.py` + 33 tests + import-graph guard
test), this history records the transition from "Design Approved For
Implementation" to a to-be-named post-implementation status.

---

## Cross-references

- `PHASE3_ARCHITECTURE.md` §4 (Data Model), §6 (ManualFact discipline), §7
  (Report design), §8 (WP-E section), §9 (Out-of-scope), §10 (Pre-merge
  checklist)
- `PHASE3_LANDSCAPE.md` §1 (Trust Doctrine), §2 Group E (Meta-project
  concerns), §4 (What "IPCAT is source of truth" means)
- `audio_bu_skill/docs/WP_E_DESIGN_REVIEW.md` — Line-by-line design review;
  Section B blockers resolved at Checkpoint E0 (2026-07-20) and encoded in
  §3.1 / §3.2 / §5 / §6 / §8 / §9 / §13 / §16 / §17 / §18 of this document.
- `audio_bu_skill/docs/PHASE3_KNOWN_GAPS.md` §G-3A.1 — IPCAT Acquisition
  Lifecycle. Accepted architectural gap; out of WP-E scope. WP-E provides
  the substrate (`Registry.append_provenance()` + `IPCATLiveRef`) that a
  later WP-H selective-acquisition path will write into; WP-E itself
  performs no acquisition.
- `audio_bu_skill/fact_requirements/__init__.py` (WP-D public surface —
  the only upstream contract for WP-E)
- `audio_bu_skill/fact_requirements/schema.py` (`Domain`, `Authority`,
  `AuthorityClass`, `Requiredness`, `SubjectRequirement`, `FactFamilyDef`,
  `AuthorityTTL`, `FreshnessPolicy`, `Catalog`)
- `audio_bu_skill/fact_requirements/catalog/audio.py` (11 audio families —
  informs the expected FactKey shape but does not constrain the registry)
