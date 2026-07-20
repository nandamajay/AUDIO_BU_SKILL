# Phase-3A Architecture Refinement — Fact Coverage Authority Framework

**Status:** Refined architecture proposal — implementation-ready for Phase-3A only.
**Date:** 2026-07-18
**Supersedes:** the prior Phase-3 architecture proposal (WP-D through WP-P) in this same file.
**Scope discipline:** design only. No file modifications outside this document. No promotion changes.

---

## 1. Executive verdict on the prior proposal

The prior proposal (WP-D → WP-P) was directionally correct but suffered from three overreach failures:

1. **Scope creep.** It planned WP-M (backfill), WP-N (enforcement), WP-O (live IPCAT), and WP-P (tri-state retirement) before we have even one line of registry code shipped. Phase-3A must land the smallest thing that gives real diagnostic value — everything past WP-G is speculation until we see a real Coverage Report on Nord, Eliza, and Shikra.
2. **Audio-shaped models.** Fact families were named `GPIO_PINMUX`, `POWER_DOMAIN`, `SMMU_SID` — flat, audio-first. This bakes an audio bias into the schema. Other domains (Camera, Display, PCIe) each have their own GPIO/Power/Clock/Bus fact classes with different semantics. The registry will collide on names or force domain-specific hacks within a year.
3. **Coverage-only quality signal.** The prior model treated coverage as a single number. But a family can be 100% "covered" by INFERRED facts with 0.3 confidence and a schematic/DTS conflict — and a naive gate would still call it PASS. Coverage, freshness, confidence, and conflict must be independent axes.

Additionally, the 100%-for-most-critical-families threshold table was not evidence-based — it was a plausible starting point stated as a policy. That commitment needs to be walked back before we ever wire enforcement.

**Verdict:** proceed with a substantially narrower Phase-3A. Keep WP-D through WP-G. Defer everything past WP-G until we have Nord/Eliza/Shikra evidence of what the numbers actually look like.

---

## 2. Key corrections / challenges

| # | Correction | Rationale |
|---|---|---|
| C1 | **Hierarchical fact families** (`Audio.GPIO`, `Camera.CCI`, `Display.DSI`) from day one | Cheap now, painful later. Domain scoping avoids namespace collision and lets each domain evolve its own subject shapes without cross-contamination |
| C2 | **Subject-level requiredness**, not family-level thresholds | A family like `Audio.GPIO` has ~4 hard-required subjects (I2S data/word/bit clk, MCLK) and several advisory ones (SPK PA enable, headset detect). Requiring 100% at family level either blocks legitimate targets or hides real gaps |
| C3 | **Confidence and conflict are first-class** independent of coverage | INFERRED facts, conflicts between authorities, and low-confidence values must be visible in the report and cannot silently satisfy a critical-family gate |
| C4 | **ManualFact / ExternalAuthorityFact is a wrapper**, not just an authority enum | Manual facts need reviewer, ticket, expiry, and evidence-of-review captured; a bare `authority=MANUAL` string invites laundering |
| C5 | **Phase-3A is advisory only** | No gates, no acquisition, no backfill. Ship the diagnostic; use two weeks of real reports to justify the next phase |
| C6 | **Registry-absent behavior** is a first-class state | Existing runs without a registry file must not error; report renders "coverage unknown — registry not populated" and legacy sections stay authoritative |
| C7 | **WP-C cardinality integration** deferred one phase | Coupling Coverage to WP-C's expected-subject counts now creates a hard dependency. Phase-3A enumerates expected subjects from the catalog only; WP-C comes in via a later phase |

---

## 3. Revised Phase-3A scope

**In scope (Phase-3A):**
- WP-D: Fact Family Catalog + Requirements Schema (hierarchical, subject-level)
- WP-E: Fact Registry storage + provenance chain (append-only, per target)
- WP-F: Coverage Engine — compute-only (4 axes: coverage, freshness, confidence, conflict)
- WP-G: Report renderer — `## Fact Coverage` section (advisory, additive)

**Out of scope (deferred to Phase-3B+):**
- Selective refresh / query planner / acquisition recipes
- Live IPCAT MCP acquisition
- Promotion gate enforcement (advisory dual-run also deferred)
- Registry backfill migration for existing targets
- Threshold tuning against real target history
- Any changes to `case.generated.py → case.py` promotion mechanics
- WP-C Cardinality Authority integration as an expected-subject source
- Tri-state IPCAT retirement (tri-state stays authoritative)
- Report grep-test churn — new section is purely additive

**Success criterion for Phase-3A:** running `--onboard nord-iq10 --kernel-source ...` produces an onboarding report that includes a `## Fact Coverage` section showing which fact families are covered, which are missing subjects, which have stale evidence, and which have inferred or conflicting values — **without changing** any promotion outcome, WP7 verdict, IPCAT tri-state, Confidence Ledger row, or Cardinality Authority row.

---

## 4. Revised data model

### 4.1 FactKey — with domain scoping

```
FactKey := (domain, family, subject, attribute)
    domain    : Domain enum          # Audio | Camera | Display | PCIe | Generic
    family    : str                  # unqualified name within the domain
    subject   : str                  # concrete instance identifier
    attribute : str                  # what property of the subject

# canonical string form: "<domain>.<family>/<subject>/<attribute>"
# example: "Audio.GPIO/I2S8_SD0/pin_number"
```

Not included in FactKey: `chip`, `target`, `board`, `path`. Rationale: FactKey is a **type-level** identity, not a scope. The registry file itself is per-target (`state/fact_registry/<target>.json`), so chip/target scoping is enforced by the file boundary. Board and path variance is captured in `FactValue.source_ref` and `FactValue.value` respectively.

### 4.2 FactValue — with review + conflict state

```
FactValue :=
    value             : scalar | struct
    authority         : Authority enum
    authority_class   : PRIMARY | FALLBACK | INFERRED | MANUAL
    captured_at       : ISO8601 UTC
    source_ref        : SourceRef                # tagged union, see 4.3
    confidence        : float [0.0, 1.0]
    freshness_state   : FRESH | STALE | EXPIRED | UNKNOWN     # derived at load
    coverage_state    : PRESENT | PARTIAL | ABSENT | INVALIDATED
    conflict_state    : NONE | CONFLICT | RESOLVED             # see 4.4
    review            : ReviewRecord | null                     # required for MANUAL
    provenance_chain  : [FactProvenance, ...]                   # append-only history

Authority enum :=
    IPCAT_LIVE | IPCAT_CACHED | SCHEMATIC_PDF | KERNEL_DTS
    | KERNEL_BINDINGS | ACDB_EXPORT | MANUAL | INFERRED
```

Design notes:
- **`authority_class`** is a coarse axis independent of `authority`. `PRIMARY` means it came from the family's designated primary authority (per catalog); `FALLBACK` from a declared fallback; `INFERRED` was computed by the system; `MANUAL` came from a human/team. Coverage rules key off `authority_class`, not off individual authorities, so adding a new source doesn't fan out into every rule.
- **`provenance_chain`** is append-only from day one. Every re-acquisition pushes a `FactProvenance{authority, source_ref, captured_at, confidence, note}` and updates the top-of-chain fields. Never mutate in place.
- **`review`** is `null` unless `authority_class == MANUAL`. When set it is a `ReviewRecord` (see §6).

### 4.3 SourceRef — tagged union

```
SourceRef := IPCATLiveRef | IPCATCachedRef | KernelRef | SchematicRef | ACDBRef | ManualRef

IPCATLiveRef   : { kind: "ipcat_live",   tool: str, args: dict, query_id: str, ts: ISO8601 }
IPCATCachedRef : { kind: "ipcat_cached", path: str, sha256: str, line: int|null }
KernelRef      : { kind: "kernel",       repo: str, commit: str, path: str, line_start: int, line_end: int }
SchematicRef   : { kind: "schematic",    doc_id: str, revision: str, page: int, section: str|null }
ACDBRef        : { kind: "acdb",         export_id: str, path: str, key: str }
ManualRef      : { kind: "manual",       ticket_url: str|null, doc_ref: str|null, note: str }
```

Rationale: A tagged union enforces that MCP references carry `query_id + ts`, cached references carry `sha256`, and manual references carry a ticket or doc pointer. No source can slip in with an unverifiable "trust me" string.

### 4.4 Conflict semantics

A `conflict_state = CONFLICT` means: **two or more provenance entries in this fact's chain (or across facts sharing this FactKey.subject/attribute) disagree on the value**. The Coverage Engine detects this at load time by comparing `value` across the provenance chain and across facts.

- `RESOLVED` means the disagreement was reconciled by an explicit review (`ReviewRecord.decision = "resolve_conflict"`) with a chosen winner.
- `NONE` means no disagreement seen.

Conflicts never silently pick a winner. Until reviewed, a conflicting fact contributes `coverage_state=PARTIAL` regardless of the authority strengths — the operator must decide.

### 4.5 FamilyCoverage — with all four axes

```
FamilyCoverage :=
    family                  : str                      # domain-qualified
    domain                  : Domain enum
    required_subjects       : int                      # mandatory subjects per catalog
    optional_subjects       : int                      # advisory subjects (reported separately)
    present_subjects        : int                      # coverage_state=PRESENT and non-inferred
    partial_subjects        : int                      # coverage_state=PARTIAL (incl. conflicts)
    stale_subjects          : int                      # freshness_state in {STALE, EXPIRED}
    absent_subjects         : int                      # required but no fact recorded
    inferred_subjects       : int                      # authority_class=INFERRED
    manual_subjects         : int                      # authority_class=MANUAL
    conflicting_subjects    : int                      # conflict_state=CONFLICT (unresolved)
    coverage_pct            : float
    optional_coverage_pct   : float
    confidence_score        : float                    # weighted mean of subject confidences
    freshness_debt          : int                      # count of stale/expired critical subjects
    inferred_debt           : int                      # inferred_subjects in critical family
    conflict_debt           : int                      # conflicting_subjects
    verdict                 : PASS | WARN | FAIL       # Phase-3A: informational only
    threshold_used          : float
    critical                : bool
```

Debt fields are additive per-family metrics that make the "coverage isn't quality" story readable in the report. A family can be 100% covered with `inferred_debt = 3` and `conflict_debt = 1` — a very different position from 100% covered with all zeros.

---

## 5. Revised Coverage / Confidence / Conflict model

### 5.1 Four independent axes

| Axis | Question | Data source | Where it lives |
|---|---|---|---|
| **Coverage** | Do we have a value for every required subject? | `coverage_state` per subject | `FamilyCoverage.coverage_pct` |
| **Freshness** | Is the value we have still valid? | derived `freshness_state` from `captured_at` + TTL policy | `FamilyCoverage.stale_subjects` |
| **Confidence** | How strongly do we believe each value? | `FactValue.confidence` + `authority_class` | `FamilyCoverage.confidence_score`, `inferred_debt` |
| **Conflict** | Do authorities disagree? | `FactValue.conflict_state` per subject | `FamilyCoverage.conflict_debt` |

The four axes are surfaced separately in the report. Phase-3A **never** collapses them into a single "green/red" number.

### 5.2 INFERRED facts and critical families

- INFERRED facts **count toward coverage** for their subject (i.e., contribute to `present_subjects`), but only when no PRIMARY / FALLBACK / MANUAL fact is available.
- INFERRED facts in a **critical family** contribute to `inferred_debt` and the family verdict is capped at WARN, never PASS, until an authoritative fact replaces them.
- Design invariant: **INFERRED cannot alone satisfy a critical family's coverage requirement**. This is enforced in the Coverage Engine's family-verdict computation and covered by an explicit test in WP-F.

### 5.3 Confidence score computation

`confidence_score` for a family is the weighted mean of subject confidences, weighted by:

```
weight(subject) := 3.0 if authority_class == PRIMARY
                  2.0 if authority_class == FALLBACK
                  1.5 if authority_class == MANUAL (with valid review)
                  1.0 if authority_class == INFERRED
                  0.0 if conflicting/unresolved
```

Conflicting subjects contribute weight zero — they neither raise nor lower the mean; they show up separately as `conflict_debt`. This prevents a hot conflict from bumping the number.

### 5.4 Freshness policy for Phase-3A

Phase-3A ships **static freshness** only:
- `captured_at` is recorded.
- TTL policy is declared per authority in a config file (`fact_freshness.yaml`).
- `freshness_state` is computed at report render time.
- **No auto-refresh, no auto-invalidation events.** Upstream event tracking (IPCAT release-tag bumps, kernel commit advances) is Phase-3B.

### 5.5 Thresholds — revised, subject-level, advisory-only

Family-level percentage thresholds were wrong. Replace with **subject-level requiredness** declared in the catalog:

```
SubjectRequirement :=
    subject_pattern     : str                   # e.g. "I2S8_SD0" or regex "MI2S[0-9]+_BCLK"
    requiredness        : MANDATORY | ADVISORY | OPTIONAL
    promotion_relevant  : bool                  # does this subject gate promotion, eventually?
    generation_relevant : bool                  # does this subject gate code generation?
    notes               : str
```

**Family-level `threshold_used`** becomes `mandatory_subject_coverage_pct` — the fraction of MANDATORY subjects covered. It is reported but does not enforce anything in Phase-3A.

Revised per-family judgment (Phase-3A: advisory only; future-phase gate guidance in the last column):

| Family | Domain | MANDATORY subjects (examples) | Advisory subjects | Future gate posture |
|---|---|---|---|---|
| `GPIO` | Audio | I2S data/word/bit clks in use, primary MCLK, codec reset | SPK PA enable, headset detect | 100% mandatory subjects; advisory reported separately |
| `QUP` | Audio | codec's I2C bus and address | unused QUPs | 100% mandatory |
| `CLOCK` | Audio | LPASS aud_ref_clk, MI2S BCLK/WCLK in use, codec MCLK | ancillary clocks | 100% mandatory; advisory reported |
| `POWER` | Audio | codec AVDD/DVDD, LPASS core rail (LCX/LMX) | secondary supplies | 100% mandatory |
| `SMMU_SID` | Audio | ADSP DMA carveout SID (if DMA in use) | offload SIDs | 100% mandatory when DMA is in use; N/A otherwise |
| `ADSP_REG_BASE` | Audio | PAS base, QDSP6SS base | subsystem sysmgr | 100% mandatory |
| `AUDIOREACH_PORT` | Audio | logical port IDs for the bring-up config | unused ports | 100% mandatory |
| `INTERCONNECT` | Audio | LPASS-CC path in use | ancillary hops | 100% of paths in use |
| `CODEC_BINDING` | Audio | regmap I2C addr, reset GPIO, primary supplies | secondary features | 100% mandatory |
| `DSP_TOPOLOGY` | Audio | (none MANDATORY at Phase-3A) | subgraphs, calibration keys | Advisory only; not a promotion gate |
| `MBHC_THRESHOLD` | Audio | (none) | detect trip points | Advisory only |

Key rule: **generation-relevant ≠ promotion-relevant.** DSP_TOPOLOGY and MBHC are generation-relevant (their absence produces stub code) but not promotion-relevant (their absence should not block promoting `case.generated.py` because generation can still emit reasonable stubs with FIXMEs).

**Phase-3A stance:** every threshold above is **informational only**. No gate reads it. The point of Phase-3A is to *observe* the numbers on Nord/Eliza/Shikra before committing to enforcement.

---

## 6. ManualFact / ExternalAuthorityFact design

### 6.1 Design decision: wrapper + authority, not new type

`MANUAL` is an `Authority` enum value AND `authority_class` = `MANUAL`. There is no separate `ManualFact` type — a manual fact is a `FactValue` with `authority_class == MANUAL` and a mandatory non-null `review` field.

Why not a separate type: keeping one storage shape means the Coverage Engine, report renderer, and provenance chain all work uniformly. Manual-ness is an attribute of the value, not of the fact identity.

### 6.2 ReviewRecord

```
ReviewRecord :=
    reviewer_id       : str                     # user id or team handle
    reviewer_role     : str                     # e.g. "power-team-owner"
    requested_at      : ISO8601 UTC
    answered_at       : ISO8601 UTC
    question          : str                     # what was asked
    answer            : str                     # verbatim answer
    ticket_url        : str | null              # tracker link (Jira, etc.)
    email_msgid       : str | null              # email evidence, if any
    doc_ref           : str | null              # design review, decision doc
    decision          : "provide" | "resolve_conflict" | "override" | "reject"
    expires_at        : ISO8601 UTC | null      # revalidation deadline
    supersedes        : FactProvenance ref | null    # what this replaces
```

Design invariants:
- `authority_class == MANUAL` and `review == null` → the fact is **rejected at registry load** as malformed. It cannot enter coverage. This is the primary defense against laundering weak manual guesses.
- `ticket_url == null AND email_msgid == null AND doc_ref == null` → the fact is loaded but `confidence` is capped at 0.4 (unverifiable manual). This shows up as low `confidence_score` and manual_subjects contributing to a debt line.
- `expires_at` in the past → `freshness_state = EXPIRED`; fact remains in registry but reports as stale-manual.

### 6.3 Manual facts in critical families

A manual fact **can** satisfy a critical-family subject's coverage, but:
- The family verdict is capped at WARN (never PASS) if `manual_subjects > 0` in Phase-3A.
- The report explicitly lists the reviewer and ticket for each manual fact in the critical family, so an operator sees exactly who owns each such claim.

Rationale: manual evidence is often the only path for team-owned facts (power-domain index, SMMU SID confirmation) but that path must be visible and revocable, not laundered as "just another authority."

### 6.4 Revocation and expiry

- A manual fact is revoked by appending a new `FactProvenance` with `decision = "reject"` and no `value` — effectively marking it withdrawn.
- Auto-expiry via `expires_at` is applied at registry load; the fact stays in the provenance chain (audit) but does not contribute to coverage.

### 6.5 Report rendering for manual facts

Manual facts appear both in their family's coverage row AND in a dedicated `### Manual / External Authority Facts` subsection listing `subject | reviewer | ticket | answered_at | expires_at | status`. Operators can audit these at a glance.

---

## 7. Report design for `## Fact Coverage`

### 7.1 Placement

The onboarding report currently contains, in order:
1. Inputs
2. Nearest-target
3. Proposed case fields
4. NEEDS_REVIEW
5. Cited evidence
6. Kernel History
7. Power Model
8. **IPCAT Coverage**  ← existing tri-state section
9. Confidence Ledger
10. Cardinality Authority
11. Schematic ↔ IPCAT Cross-Verification
12. Generation
13. Post-verification (WP7)
14. Promotion

**Insert `## Fact Coverage` immediately after `## IPCAT Coverage` (position 9), before `## Confidence Ledger`.** Rationale: it is a strict superset of what IPCAT Coverage answers, and adjacency helps operators compare the two while both exist in parallel.

### 7.2 Section structure

```
## Fact Coverage
Registry: audio_bu_skill/state/fact_registry/<target>.json  (loaded | absent | corrupt)
Total facts recorded: N   (PRIMARY=n1  FALLBACK=n2  MANUAL=n3  INFERRED=n4)
Overall (Phase-3A advisory): PROMOTE_READY | ADVISORY | BLOCKED

### Per-family coverage
| Family              | Domain | Mandatory | Present | Partial | Absent | Stale | Inferred | Manual | Conflict | Coverage | Confidence | Verdict |
|---------------------|--------|----------:|--------:|--------:|-------:|------:|---------:|-------:|---------:|---------:|-----------:|--------:|
| Audio.GPIO          | Audio  |        7  |      7  |      0  |     0  |    0  |      0   |     0  |       0  |    100%  |      0.92  |  PASS   |
| Audio.POWER         | Audio  |        5  |      2  |      1  |     2  |    0  |      1   |     0  |       0  |     40%  |      0.55  |  FAIL   |
| Audio.SMMU_SID      | Audio  |        1  |      0  |      0  |     1  |    0  |      0   |     0  |       0  |      0%  |      0.00  |  FAIL   |
| Audio.AUDIOREACH_PORT | Audio |      4  |      2  |      1  |     1  |    0  |      1   |     1  |       0  |     50%  |      0.60  |  WARN   |

### Missing facts (mandatory)
- Audio.POWER / VDD_LCX / regulator_name           (primary authority: IPCAT_LIVE or IPCAT_CACHED)
- Audio.POWER / VDD_LMX / regulator_name           (primary authority: IPCAT_LIVE or IPCAT_CACHED)
- Audio.SMMU_SID / adsp_dma_carveout / sid         (primary authority: IPCAT_LIVE or IPCAT_CACHED)
- Audio.AUDIOREACH_PORT / I2S8 / logical_port_id   (primary authority: IPCAT_LIVE or IPCAT_CACHED)

### Debt summary
- Freshness debt (stale/expired mandatory subjects): 0
- Inferred debt (INFERRED in critical family):        2
- Conflict debt (unresolved cross-authority):         0

### Manual / External Authority facts
| Subject | Reviewer | Ticket | Answered | Expires | Status |
|---------|----------|--------|----------|---------|--------|
| Audio.AUDIOREACH_PORT / I2S8 / logical_port_id | audioreach-owner@... | AR-1234 | 2026-07-10 | 2026-10-10 | valid |

### Conflicts (unresolved)
_none_

### Notes
- Advisory only in Phase-3A. Does not affect promotion, WP7 verdict, or IPCAT tri-state.
- See §Coverage rules and §Confidence weights for interpretation.
```

### 7.3 Registry-absent behavior

If `state/fact_registry/<target>.json` is missing or unreadable:

```
## Fact Coverage
Registry: audio_bu_skill/state/fact_registry/<target>.json  (absent)
No coverage evaluation performed. Existing IPCAT Coverage, Confidence Ledger, and Cardinality Authority sections remain authoritative.
```

- Legacy sections stay unchanged.
- Tests that grep for existing sections continue to pass.
- Operators are not spammed with empty tables.

### 7.4 Report backward compatibility

- Every existing section header is preserved verbatim.
- Existing grep patterns (`NEEDS_REVIEW`, `NO_IPCAT_EVIDENCE`, `no_source_facts_available`, `Overall verdict`) continue to match unchanged sections.
- New section uses unique anchors (`## Fact Coverage`, `### Per-family coverage`, etc.).
- The verdict word `Overall (Phase-3A advisory):` is deliberately distinct from WP7's `Overall verdict:` to prevent grep confusion.

---

## 8. Minimal work package plan — WP-D / WP-E / WP-F / WP-G

### WP-D — Fact Family Catalog + Requirements Schema

**Objective:** declare the fact families, subject requirements, and freshness policy as data.

**Files created:**
- `audio_bu_skill/fact_requirements/schema.py` — pydantic (or dataclass) models: `Domain`, `FactFamilyDef`, `SubjectRequirement`, `Requiredness`.
- `audio_bu_skill/fact_requirements/catalog/audio.py` — Audio.* family definitions.
- `audio_bu_skill/fact_requirements/catalog/generic.py` — placeholder for cross-domain families (empty in Phase-3A).
- `audio_bu_skill/fact_requirements/loader.py` — assemble the catalog, apply per-SoC overrides (SoC override files exist but empty in Phase-3A).
- `audio_bu_skill/fact_requirements/fact_freshness.yaml` — TTL policy per authority.
- `audio_bu_skill/tests/test_fact_requirements_catalog.py`

**Files NOT touched:** anything under `orchestrator/`, `skills/`, `targets/`, existing tests.

**Inputs:** none at runtime — this is static declaration.

**Outputs:** a loadable, validated Catalog object usable by WP-F.

**Tests:**
- Schema validation catches malformed catalog entries.
- Audio catalog loads.
- Every declared family has at least one MANDATORY or ADVISORY subject (or is explicitly marked optional).
- No duplicate `FactKey` prefixes across families.
- Freshness policy YAML parses and covers every `Authority` enum value.

**Exit criteria:**
- Catalog loads successfully in a test.
- `audio_bu_skill/fact_requirements/catalog/audio.py` declares at least the 11 families listed in §5.5.
- Schema documented at module top.

**Risks:**
- **R-D1:** Bikeshedding on family names → freeze naming in a PR-1 review, don't iterate.
- **R-D2:** Subject-pattern regexes drift from IPCAT/kernel reality → cover with unit tests using a curated fixture list of Nord subjects.

**What must not change:**
- No changes to `case.py`, `case.generated.py`, or promotion mechanics.
- No changes to existing report sections.
- No changes to `orchestrator.runners.*`.

---

### WP-E — Fact Registry storage + provenance chain

**Objective:** provide a per-target append-only fact store with a small, testable API.

**Files created:**
- `audio_bu_skill/orchestrator/fact_registry/__init__.py`
- `audio_bu_skill/orchestrator/fact_registry/models.py` — `FactKey`, `FactValue`, `FactProvenance`, `SourceRef` tagged union, `ReviewRecord`.
- `audio_bu_skill/orchestrator/fact_registry/store.py` — load, save (temp-file + rename), append_provenance, get_fact, iter_facts. Locking: filesystem lock file per registry path.
- `audio_bu_skill/orchestrator/fact_registry/hash.py` — sidecar hash computation.
- `audio_bu_skill/tests/test_fact_registry_models.py`
- `audio_bu_skill/tests/test_fact_registry_store.py`

**Files NOT touched:** existing runners, main.py, targets/*, existing tests.

**Storage layout:**
- `audio_bu_skill/state/fact_registry/<target>.json`  (newline-JSON: one FactKey per line, with `FactValue` + `provenance_chain`)
- `audio_bu_skill/state/fact_registry/<target>.registry.hash`
- `audio_bu_skill/state/fact_registry/<target>.lock` (POSIX advisory lock)

**Inputs:** target name.

**Outputs:** a Registry object with the API surface above.

**Tests:**
- Round-trip: write a fact, read it back byte-identical.
- Append-only: mutating an existing fact adds to `provenance_chain`, never overwrites the earlier entry.
- Sidecar hash matches after every write; mismatch surfaces cleanly as a load-time warning.
- Manual facts without `review` are rejected.
- Manual facts with unreachable ticket/email/doc are stored with capped confidence.
- Corrupt or truncated JSON on load returns `Registry.status = corrupt`, does not raise, and does not delete the file.

**Exit criteria:**
- Store round-trips all authority classes.
- 100% branch coverage on the reject/cap rules for MANUAL.
- The lock file is honored — a second writer errors cleanly.

**Risks:**
- **R-E1:** Concurrent writers from parallel test runs → per-target lock is sufficient because Phase-3A writes only happen at report render time (single-writer).
- **R-E2:** Storage schema drift → include `schema_version` field; loader tolerates known-older versions but not newer.

**What must not change:**
- Nothing in `orchestrator/main.py`, `orchestrator/runners/`, or `targets/`.
- WP-E ships as an unused module until WP-F consumes it.

---

### WP-F — Coverage Engine (compute-only)

**Objective:** given a Catalog (WP-D) and a Registry (WP-E), produce a `CoverageReport` object. No I/O beyond reads. No side effects.

**Files created:**
- `audio_bu_skill/orchestrator/coverage/__init__.py`
- `audio_bu_skill/orchestrator/coverage/engine.py` — `evaluate(catalog, registry) -> CoverageReport`.
- `audio_bu_skill/orchestrator/coverage/models.py` — `CoverageReport`, `FamilyCoverage`, `SubjectCoverage`, `DebtSummary`, `ConflictRow`, `ManualRow`.
- `audio_bu_skill/orchestrator/coverage/freshness.py` — pure functions computing `freshness_state` from `captured_at` + policy.
- `audio_bu_skill/orchestrator/coverage/conflict.py` — pure functions detecting conflicts across provenance chains.
- `audio_bu_skill/orchestrator/coverage/confidence.py` — weighted-mean confidence per family.
- `audio_bu_skill/tests/test_coverage_engine.py`
- `audio_bu_skill/tests/test_coverage_freshness.py`
- `audio_bu_skill/tests/test_coverage_conflict.py`
- `audio_bu_skill/tests/test_coverage_confidence.py`
- `audio_bu_skill/tests/fixtures/coverage/` — curated registry fixtures (all-present, missing-power, inferred-only, conflict, manual, stale).

**Files NOT touched:** everything outside `coverage/` and its tests.

**Inputs:** Catalog, Registry.

**Outputs:** `CoverageReport` — pure data.

**Tests (critical invariants):**
- **T-F1:** All-mandatory-present → `verdict=PASS`, `coverage_pct=100%`.
- **T-F2:** One mandatory missing → `verdict=FAIL` for critical family.
- **T-F3:** All mandatory present with INFERRED-only → `verdict=WARN`, `inferred_debt > 0`. Critical families with only INFERRED evidence must **not** be PASS.
- **T-F4:** Conflict on any subject → subject's `coverage_state=PARTIAL`, family `conflict_debt >= 1`, family verdict at most WARN.
- **T-F5:** Manual fact with valid `review` → contributes to coverage, family verdict at most WARN in Phase-3A, `manual_subjects >= 1`.
- **T-F6:** Manual fact without review → rejected at store layer (WP-E test); Coverage Engine never sees it.
- **T-F7:** Stale fact → `stale_subjects >= 1`, contributes to coverage, family verdict at most WARN.
- **T-F8:** Expired fact → same as stale but shows in `expired_facts` list.
- **T-F9:** Empty registry → all families report `absent_subjects = required_subjects`, `verdict=FAIL` for critical, `overall_verdict=BLOCKED`.
- **T-F10:** Missing registry file → engine returns a `CoverageReport(status='registry_absent')` — never raises.
- **T-F11:** Monotonicity: adding a PRIMARY fact for a currently-absent subject can only increase (never decrease) `coverage_pct` and can only decrease (never increase) any debt count. Property-tested with a random-order fixture generator.

**Exit criteria:**
- All T-F* pass.
- Coverage engine has no dependency on `orchestrator/runners/*` (import-graph test).
- Coverage engine has no dependency on `targets/*` (import-graph test).
- Engine returns in <100ms for a fully-populated Nord registry (perf test with fixture).

**Risks:**
- **R-F1:** Silent downgrade — engine mis-labels PARTIAL as PRESENT under some corner. Mitigated by T-F3, T-F4, T-F11.
- **R-F2:** Confidence-weight regression — a change to the weight table silently shifts `confidence_score`. Mitigated by golden-value tests on curated fixtures.

**What must not change:**
- No changes to any existing runner, report renderer, or promotion logic.
- WP-F does not import `orchestrator.main`.

---

### WP-G — Report renderer: `## Fact Coverage` section

**Objective:** render a `## Fact Coverage` section from a `CoverageReport`, inserted into `onboarding_report.md` after `## IPCAT Coverage`. Additive only — no changes to any other section.

**Files created:**
- `audio_bu_skill/orchestrator/coverage/render.py` — `render_fact_coverage_section(report: CoverageReport) -> str`.
- `audio_bu_skill/tests/test_coverage_render.py`
- `audio_bu_skill/tests/fixtures/coverage/golden_reports/` — golden Markdown snapshots per fixture scenario.

**Files modified (minimally):**
- `audio_bu_skill/orchestrator/main.py` — one insertion point: after the call that emits `## IPCAT Coverage`, call `render_fact_coverage_section(evaluate(catalog, registry))` and append the returned string. Guarded so that a missing registry / catalog load failure produces the registry-absent stub (§7.3), never raises.

**Files NOT touched:** any existing section renderer, runner, WP7 module, tri-state IPCAT module.

**Inputs:** `CoverageReport`.

**Outputs:** Markdown string appended to the report.

**Tests:**
- **T-G1:** Golden render for the `all-present` fixture matches the checked-in golden file byte-for-byte.
- **T-G2:** Golden render for `missing-power` fixture matches.
- **T-G3:** Golden render for `manual-with-review` fixture matches.
- **T-G4:** Golden render for `conflict` fixture matches.
- **T-G5:** Golden render for `registry-absent` produces the exact stub in §7.3.
- **T-G6:** Existing greps still pass — `grep -n "NEEDS_REVIEW\|NO_IPCAT_EVIDENCE\|no_source_facts_available\|Overall verdict"` on a rendered report finds the same lines as before, plus no extras (the new section uses `Overall (Phase-3A advisory):` deliberately).
- **T-G7:** Nord onboarding smoke test: full `--onboard nord-iq10 --generate` run completes; report contains `## Fact Coverage`; no other section is altered; IPCAT tri-state is unchanged; WP7 verdict is unchanged; promotion is unchanged; `case.generated.py` is NOT promoted.

**Exit criteria:**
- Rendered section matches golden files for all fixtures.
- Nord report grows exactly one new section; no other diffs.
- Existing test suites remain green (36-module sweep or its current equivalent).
- Test running full onboarding-then-render on Nord takes <1s more wall time than baseline.

**Risks:**
- **R-G1:** Insertion point in `main.py` accidentally rearranges other sections. Mitigated by golden-report diffing pre/post.
- **R-G2:** Registry load raises during a Nord run → report generation aborts. Mitigated by an explicit try/except around the insertion; failure falls back to the registry-absent stub with a note captured in the section body.
- **R-G3:** Byte-identical golden matching is brittle to trivial format changes. Mitigated by pinning the golden output at the WP-G merge and treating any diff as a review checkpoint.

**What must not change:**
- No other section header, ordering, or content.
- No change to IPCAT tri-state semantics.
- No change to promotion or WP7 logic.
- Existing grep-based tests continue to pass.

---

## 9. Explicit out-of-scope list (Phase-3A)

The following are deliberately excluded and must not appear in Phase-3A PRs:

1. **Selective refresh / query planner / acquisition recipes.** Deferred to Phase-3B.
2. **Live IPCAT MCP acquisition.** Depends on Phase-1A provisioning; deferred to Phase-3C or later.
3. **Promotion gate enforcement.** Coverage is advisory only; the existing gate reads only what it reads today.
4. **Advisory dual-run promotion gate.** Even the read-only dual-run is deferred to Phase-3B once we have real coverage numbers on Nord/Eliza/Shikra.
5. **Registry backfill migration** for existing targets. Phase-3A registries are empty for legacy targets and the report renders the registry-absent stub.
6. **Threshold tuning against real target history.** Phase-3A reports the numbers; tuning is data-driven in a later phase.
7. **Changes to `case.py`, `case.generated.py`, or promotion mechanics.** Zero touching.
8. **WP-C Cardinality Authority integration.** Expected-subject counts come from the catalog only in Phase-3A. Consuming WP-C output is a Phase-3B step.
9. **Tri-state IPCAT retirement.** Tri-state stays authoritative.
10. **Confidence Ledger merger.** The Ledger remains its own section. Fact Coverage's confidence score is independent; a future phase can consider unifying them.
11. **Auto-invalidation on upstream events.** IPCAT release-tag bumps, kernel commits, schematic revision changes — all deferred. Phase-3A uses static TTL only.
12. **Multi-target aggregation reports.** One target per registry; no cross-target rollups.
13. **UI, dashboards, or web rendering.** Markdown in `onboarding_report.md` only.

---

## 10. Final recommendation

**Proceed with Phase-3A as scoped above (WP-D → WP-G, advisory-only).**

Rationale:
- The scope is small enough to land in one focused effort.
- Every piece is testable in isolation (pure data, pure engine, pure renderer).
- Zero behavior change on the existing pipeline; the worst-case regression is a missing new section, which is safe.
- Two-week evidence gathering after landing gives real data for the Phase-3B threshold and enforcement decisions — no premature commitment.
- All evidence-first principles preserved:
  - **No fact manufacturing.** MANUAL requires a review record; INFERRED is labeled; conflicts are surfaced.
  - **No silent downgrade.** INFERRED-only cannot make a critical family PASS; conflicts cap verdicts at WARN.
  - **No cached-is-complete assumption.** Coverage measures against the required subject list, not cache size.
  - **No live-is-automatic assumption.** LIVE facts still show `confidence` and `authority_class`; a low-confidence live fact still shows up as WARN.
  - **No manual-as-truth assumption.** Manual facts without valid review are rejected at load.
  - **Blocked-truthful acceptable.** Registry with real gaps produces a blocked-looking Coverage section, which is the correct signal.

**Do not proceed** past WP-G until two independent onboarding runs on Nord and one on Eliza have populated real Coverage sections and been reviewed. That evidence is required before we design WP-H+.

**Non-negotiable pre-merge checks for Phase-3A:**
1. Full existing test suite green (whatever the current "36+ module" number is at merge time).
2. Nord onboarding run produces a report containing `## Fact Coverage` and no other section changed.
3. `case.generated.py` is NOT promoted in any test or manual run.
4. WP7 verdict on Nord unchanged from pre-Phase-3A baseline.
5. IPCAT tri-state on Nord unchanged from pre-Phase-3A baseline.
6. Grep for `NEEDS_REVIEW`, `NO_IPCAT_EVIDENCE`, `no_source_facts_available`, `Overall verdict` finds the same lines as pre-Phase-3A.
7. Registry files under `audio_bu_skill/state/fact_registry/` are gitignored.
