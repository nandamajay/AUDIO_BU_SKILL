# Phase-2A Implementation Plan — Schematic ↔ IPCAT Cross-Verification Engine

**Type:** Implementation plan. **No code changes, no implementation, no commits — planning only.**
**Inputs read:** `docs/PHASE2A_SPECIFICATION_V2.md`, `docs/PHASE2A_AUTHORITY_DISCOVERY.md`.
**Reuses unchanged:** WP-C Cardinality Authority — `orchestrator/reasoning/cardinality.py`, `orchestrator/reasoning/cardinality_config.py` (committed `28f2f07`).
**Date:** 2026-07-14

---

## 0. Design anchors (from the existing repo — the plan conforms to these, does not invent)

| Anchor | Where it lives today | Phase-2A follows it by |
|---|---|---|
| Pure diagnostic reasoning module | `orchestrator/reasoning/cardinality.py` + `cardinality_config.py` | New pure core `crossverify.py` + `crossverify_config.py` in the same package, stdlib-only, `from __future__ import annotations`. |
| Diagnostic-only rendering contract | `main.py::_render_*_section(gc) -> list[str]`, appended in `_render_onboarding_report` | New `_render_crossverify_section(gc)`, null-guarded, additive, no gating. |
| Impure I/O runner (collector precedent) | `orchestrator/runners/pin_crosscheck.py` | New `crossverify_collector.py` runner — all live IPCAT I/O, freezes a snapshot, then hands a pure dict to the core. |
| Read-only IPCAT access + TLS + allow-list | `experiments/ipcat_probe/probe.py` (`READONLY_MCP_TOOLS`, `SSL_CERT_FILE`, `verify=True`, `FORBIDDEN_PATHS`) | Collector reuses the exact same read-only allow-list discipline and TLS handling. |
| Result dataclass w/ `to_dict()` | `orchestrator/reasoning/result.py` | `VerificationRow` dataclass, stdlib-only, `to_dict()`, deterministic ordering. |
| Test convention | `tests/test_*.py`, run `PYTHONPATH=audio_bu_skill python3 -m tests.test_<name>`; `test_cardinality.py` (pure) + `test_pin_crosscheck.py` (temp-git fixtures) | Pure-core tests against frozen fixtures; collector tests against a recorded snapshot + a fake transport. |
| WP-C reuse (regression anchor) | `compare_element_counts(gc)` reads `gc["audio_topology"]["element_counts"]` | T3 track calls it **UNCHANGED** and maps each row to a `VerificationRow`. |

**Package layout after Phase-2A (new files marked `+`):**

```
orchestrator/reasoning/
  cardinality.py            (unchanged, reused by T3)
  cardinality_config.py     (unchanged)
  crossverify.py            +  pure Comparison Core: tracks T1..T5, verdict model
  crossverify_config.py     +  track registry, verdict enums, coverage-gap reasons, KB rules
  crossverify_model.py      +  VerificationRow dataclass + to_dict()
orchestrator/runners/
  crossverify_collector.py  +  impure Collector: live IPCAT I/O → frozen snapshot dict
orchestrator/main.py           (modified: add _render_crossverify_section + one append line)
tests/
  test_crossverify_model.py     +
  test_crossverify_core.py      +  (T1/T2/T5/T4a/T4b pure verdicts)
  test_crossverify_t3.py        +  (WP-C reuse / regression anchor)
  test_crossverify_collector.py +  (snapshot freeze + replay, fake transport)
  test_crossverify_render.py    +
  fixtures/phase2a/             +  frozen IPCAT snapshots + expected rows
```

---

## 1. Work packages

Build order follows V2 §7: **WP1 → WP2 → WP3(T3) → WP4(T1) → WP5(T2) → WP6(T5) → WP7(T4a) → WP8**. WP8's renderer can start after WP2 but lands last so it renders the full row set.

---

### WP1 — Collector Framework

Impure boundary. All live IPCAT I/O lives here; it freezes a snapshot so the pure core never touches the network.

- **Files to create:**
  - `orchestrator/runners/crossverify_collector.py` — `collect_snapshot(chip, *, transport=None) -> dict`. Calls only the verified read-only tools (§1.3 of V2): `chips_list_chips`, `cores_list_core_instances`, `swi_search_swi`, `gpio_get_gpio_map`, `gpio_list_gpios_from_map`, `gpio_list_tlmm_gpios`, `chipio_get_qups`, `buses_list_buses`/`_bus_gateways`/`_bidpidmids`. Each result stored under a stable key with a `result_digest` (sha256 of the canonicalised payload). Records `gpio_map` release provenance (`nordau_io v1.2 ECO F03`, map id 8240). On per-tool transport/auth failure, records `{"status":"unavailable","error_class":...}` for that key rather than raising — so a partial snapshot still drives partial verdicts.
- **Files to modify:** none (new runner; wired into a runner entrypoint only when Phase-2A is turned on — inert until then, like the Phase-1 probe).
- **Dependencies:** none (foundational). Reuses `probe.py`'s TLS factory pattern and read-only allow-list conceptually; a shared `READONLY_MCP_TOOLS` frozenset is defined in the collector (superset of probe's, since 2A needs the GPIO/QUP/bus tools).
- **Acceptance criteria:**
  - `collect_snapshot` calls **only** allow-listed `list_*`/`get_*`/`search_*` tools; any non-allow-listed name raises before I/O.
  - `SSL_CERT_FILE` defaulted to the system CA store; `verify=True` never weakened.
  - `auth.json` never opened (presence-check only); `.credentials.json` never read; token by reference only.
  - Output is a JSON-serialisable dict; every tool entry carries `result_digest` and either `data` or `status:"unavailable"`.
  - Re-running against the same frozen inputs yields byte-identical digests.

---

### WP2 — VerificationRow Model

The shared output dataclass; mirrors `result.py`.

- **Files to create:**
  - `orchestrator/reasoning/crossverify_model.py` — `@dataclass VerificationRow` with fields from V2 §4: `track` (`T1|T2|T3|T4a|T4b|T5`), `subject`, `source_value`, `ipcat_value`, `verdict` (`MATCH|PARTIAL_MATCH|DISAGREE_WITH_AUTHORITY|NOT_CROSS_CHECKABLE|REVIEW_REQUIRED`), `authority:{origin, strength}`, `confidence` (`high|medium|low|none`), `coverage_gap_reason` (nullable enum), `rule_id`, `notes:list`, `citations:list`, `reviewer_action`. `to_dict()` emits keys in fixed order. `from __future__ import annotations`, stdlib-only.
- **Files to modify:** none.
- **Dependencies:** WP1 (conceptual — rows describe snapshot facts), but implementable in parallel.
- **Acceptance criteria:**
  - `to_dict()` round-trips through `json.dumps` deterministically (sorted, stable).
  - Enum values validated on construction; illegal `verdict`/`track`/`reason` raise.
  - `coverage_gap_reason` is non-null **iff** `verdict == NOT_CROSS_CHECKABLE`.
  - `authority.strength` ∈ `{IPCAT_DIRECT, IPCAT_DERIVED, KB_RULE, UNAVAILABLE}`.

---

### WP3 — T3 Integration (WP-C reuse) — **regression anchor**

- **Files to create:**
  - In `crossverify.py`: `track_t3(snapshot, gc, kb) -> list[VerificationRow]`. Constructs `gc["audio_topology"]["element_counts"]` (injecting the live catalog counts from the snapshot as the `catalog` lane onto the real prior dt/evidence/proposal lanes, exactly as Phase-1C did) and calls `compare_element_counts(gc)` **UNCHANGED**. Maps each WP-C row → `VerificationRow` per V2 §3.5: `agree→MATCH`, `disagree_with_authority→DISAGREE_WITH_AUTHORITY`, `not_cross_checkable→NOT_CROSS_CHECKABLE (source_ambiguous | insufficient_lanes)`, `benign_divergence→PARTIAL_MATCH(+rule_id)`.
- **Files to modify:** none — `cardinality.py`/`cardinality_config.py` are **not touched** (commit `28f2f07` pinned in provenance).
- **Dependencies:** WP2.
- **Acceptance criteria:**
  - Given the frozen Phase-1C snapshot, T3 reproduces the **six** known verdicts exactly (Nord soundwire=0/dsp=1/lpass=0 → MATCH×3; Eliza soundwire=4 → NOT_CROSS_CHECKABLE(source_ambiguous), dsp=1 → MATCH, lpass=4 → DISAGREE_WITH_AUTHORITY).
  - No import of `cardinality` internals beyond the public `compare_element_counts`.
  - The mapping is total: every WP-C verdict has exactly one `VerificationRow` verdict.

---

### WP4 — T1 GPIO Validation (DIRECT authority)

- **Files to create:**
  - In `crossverify.py`: `track_t1(snapshot, source, kb) -> list[VerificationRow]`. Preferred path `gpio_get_gpio_map → gpio_list_gpios_from_map(function=…)`; fallback full `gpio_list_tlmm_gpios`. Verdict rules per V2 §2/T1: pin exists + claimed function is a valid mux alternate → MATCH; secondary attr (dir/drive/bias) differs → PARTIAL_MATCH; muxable-function absent → DISAGREE_WITH_AUTHORITY(+worklist); pin number absent → DISAGREE_WITH_AUTHORITY→REVIEW_REQUIRED; tool unavailable in snapshot → NOT_CROSS_CHECKABLE(authority_unavailable).
- **Files to modify:** none.
- **Dependencies:** WP1, WP2.
- **Acceptance criteria:**
  - Against the Nord snapshot, `aud_intfc0_clk`(57)/`ws`(58)/`data0..5`(59–64) at function 1 → MATCH.
  - A function-mux alternate case (GPIO 61 `aud_intfc0_data2` fn1 vs `aud_intfc10_clk` fn2) resolves by the `function` index, not name heuristics; confidence `high` on a DIRECT `function`-field lookup, `medium` on name-heuristic fallback.
  - A synthesised bad pin (number not on silicon) → DISAGREE_WITH_AUTHORITY → REVIEW_REQUIRED.
  - `gpio_map` release id recorded in row citations/provenance.

---

### WP5 — T2 Bus Validation

- **Files to create:**
  - In `crossverify.py`: `track_t2(snapshot, source, kb) -> list[VerificationRow]`. Declared bus topology (I²S-only vs SoundWire; master count) vs the SWI surface via `swi_search_swi` **union+stability** over `{SOUNDWIRE_MASTER, SWR_MSTR, SWR}` (the W4 discipline — never `total_hits`, confirm below cap, verify set-stability). 0=0 → MATCH; equal counts → MATCH; differ → DISAGREE_WITH_AUTHORITY; source self-flagged `ambiguous` → NOT_CROSS_CHECKABLE(source_ambiguous); result at/above cap → *provisional* (confidence downgraded, caveat recorded).
- **Files to modify:** none.
- **Dependencies:** WP1, WP2.
- **Acceptance criteria:**
  - Nord I²S-only → MATCH (0=0).
  - Eliza soundwire count carries the union-derived catalog value; the ambiguity path yields NOT_CROSS_CHECKABLE(source_ambiguous).
  - A snapshot at the search cap sets `confidence != high` and records the exhaustiveness caveat.

---

### WP6 — T5 DTS Consistency Validation

- **Files to create:**
  - In `crossverify.py`: `track_t5(snapshot, dts, kb) -> list[VerificationRow]`. `chips_list_chips` silicon identity (SA8797P) + a KB namespace rule. Catches the donor bug (`qcom,sa8775p-adsp-pas` + `sa8775p/adsp.mbn` + LCX/LMX on an SA8797P DTS) → DISAGREE_WITH_AUTHORITY. Absent `qcom,board-id`/`msm-id` → revision sub-check NOT_CROSS_CHECKABLE(revision_not_pinned).
  - KB rule entries in `crossverify_config.py` (donor namespace patterns, expected SA8797P compatible/firmware namespace).
- **Files to modify:** none.
- **Dependencies:** WP1, WP2.
- **Acceptance criteria:**
  - The repo's own `FIXME(sa8797p-audio)` donor case → DISAGREE_WITH_AUTHORITY with a reviewer action pointing at the compatible/firmware/power-domain namespace.
  - A DTS with no revision pin → the revision sub-check emits NOT_CROSS_CHECKABLE(revision_not_pinned) without hard-failing.
  - KB rules are data in config, not hard-coded in the track function.

---

### WP7 — T4a Endpoint Validation + T4b diagnostic stub

- **Files to create:**
  - In `crossverify.py`: `track_t4a(snapshot, source, kb) -> list[VerificationRow]` — SoC-endpoint existence/capability via `chipio_get_qups` (27 QUPs, I²C control path) + `cores_list_core_instances` (175 audio cores) + `buses_*` (indirect, *supporting* confidence). Named control engine/audio core exists → MATCH; named engine absent → DISAGREE_WITH_AUTHORITY(+worklist); capability differs (present but not I²C-capable) → PARTIAL_MATCH.
  - `track_t4b(source, kb) -> list[VerificationRow]` — **deterministic diagnostic-only**: always NOT_CROSS_CHECKABLE with `coverage_gap_reason = authority_out_of_scope`, `authority.strength = UNAVAILABLE`, `confidence = none`, reviewer action = "validate codec↔controller binding against schematic/DTS DAI-links directly." No snapshot dependency.
- **Files to modify:** none.
- **Dependencies:** WP1, WP2 (T4a). T4b depends only on WP2.
- **Acceptance criteria:**
  - A design-named I²C QUP / audio core present on Nord → MATCH; NoC-fabric corroboration marked `medium` (supporting), never the primary verdict.
  - T4b emits one honest coverage-gap row per codec binding, `authority_out_of_scope`, **independent of any snapshot** (replayable with no IPCAT data).
  - A run whose only gaps are T4b `authority_out_of_scope` rows does **not** degrade the top-level verdict below PASS/PASS_WITH_REVIEW (V2 §4).

---

### WP8 — Renderer / Worklist / Confidence Report

- **Files to create:**
  - In `crossverify.py`: `run_crossverify(gc) -> dict` — orchestrates T1..T5, returns `{rows, worklist, confidence_report, provenance}` and the top-level verdict (`PASS|PASS_WITH_REVIEW|PARTIAL|FAIL`). `provenance.wp_c_commit = "28f2f07"`.
  - Evidence writer: emit `phase2a_verification.json` (V2 §4 schema) to `experiments/ipcat_probe/artifacts/`.
- **Files to modify:**
  - `orchestrator/main.py` — add `_render_crossverify_section(gc) -> list[str]` (mirrors `_render_cardinality_section`: null-guarded, returns `[]` when no rows, additive, no gating) and one append line in `_render_onboarding_report` after `_render_cardinality_section`.
- **Dependencies:** WP2..WP7.
- **Acceptance criteria:**
  - Worklist contains only `DISAGREE_WITH_AUTHORITY` and hard-mismatch `REVIEW_REQUIRED` rows; everything else informational.
  - `confidence_report.coverage_gaps[].reason` enum = `{source_ambiguous, authority_unavailable, authority_out_of_scope, insufficient_lanes, revision_not_pinned}`.
  - Top-level verdict: `authority_unavailable` → PARTIAL; `authority_out_of_scope`-only → not below PASS/PASS_WITH_REVIEW.
  - Rendering a case with no snapshot yields no section (older reports byte-unchanged), matching the cardinality-section behaviour.

---

## 2. Replayability implementation

- **Collector freezes; core replays.** `collect_snapshot` writes a snapshot dict where every tool result carries a `result_digest` (sha256 of canonical JSON). The pure core (`crossverify.py`) takes that dict as input and performs **zero** I/O.
- **Byte-identical offline replay.** `run_crossverify(gc)` over a frozen snapshot produces identical `phase2a_verification.json` on every run (deterministic ordering from `crossverify_config` track/class order; `VerificationRow.to_dict()` stable key order). No `Date.now()`/wall-clock in the core; any timestamp lives only in the collector's snapshot metadata.
- **Provenance pinning.** `provenance` records: `wp_c_commit=28f2f07`, `gpio_map` release id (8240 / `nordau_io v1.2 ECO F03`), each tool `result_digest`, and the snapshot UTC timestamp. Replay re-verifies digests before trusting a snapshot.
- **T4b is trivially replayable** — deterministic `authority_out_of_scope` output independent of any snapshot.

---

## 3. Unit-test strategy (pure core — no network)

Run: `PYTHONPATH=audio_bu_skill python3 -m tests.test_<name>` (matches existing convention).

| Test file | Covers | Fixtures |
|---|---|---|
| `test_crossverify_model.py` | `VerificationRow` construction, enum validation, `to_dict()` determinism, the `coverage_gap_reason ⇔ NOT_CROSS_CHECKABLE` invariant. | none (constructed inline). |
| `test_crossverify_t3.py` | **Regression anchor** — T3 reproduces the six Phase-1C verdicts exactly; WP-C called unchanged. | `fixtures/phase2a/phase1c_snapshot.json` + prior element_counts. |
| `test_crossverify_core.py` | T1 (MATCH / mux-alternate / bad-pin→REVIEW_REQUIRED), T2 (0=0 MATCH / ambiguous / at-cap provisional), T5 (donor bug DISAGREE / revision_not_pinned), T4a (QUP/core MATCH / absent-engine DISAGREE / capability PARTIAL), T4b (always authority_out_of_scope, snapshot-independent). | frozen Nord snapshot + hand-authored bad-input variants. |
| `test_crossverify_render.py` | `_render_crossverify_section` returns `[]` with no rows (older reports unchanged); renders worklist + confidence report; top-level verdict rules (out_of_scope not below PASS; unavailable → PARTIAL). | small synthetic row sets. |

Principle (from `test_cardinality.py`): pure functions, frozen inputs → asserted exact rows. **No live IPCAT calls in unit tests.**

---

## 4. Integration-test strategy (collector — recorded, not live-in-CI)

- **`test_crossverify_collector.py`** — drives `collect_snapshot` with a **fake transport** that replays recorded SSE payloads (the Phase-1B/1C artifacts), asserting: only allow-listed tools are called; `SSL_CERT_FILE`/`verify=True` set; `auth.json`/`.credentials.json` never opened; per-tool `unavailable` on injected transport error; digest stability. Pattern mirrors `test_pin_crosscheck.py`'s temp-fixture approach.
- **End-to-end (attended, out of CI):** a documented manual run against live IPCAT (two-layer auth completed interactively, per D3) that produces a real `phase2a_verification.json`, then feeds that frozen snapshot back through the pure core to prove live-run == replay. This is the same attended posture Phase-1C used; **headless CI remains blocked on D3** and is not a Phase-2A deliverable.
- **No secondary-auth automation** — the collector never self-serves the interactive `kind=headers` flow.

---

## 5. Recommended commit boundaries

Each commit is independently green (`python3 -m tests.test_*`) and leaves the engine inert until WP8 wires rendering.

| # | Scope | Commit message (suggested) | Green gate |
|---|---|---|---|
| 1 | WP2 | `feat(2a): VerificationRow model + enums` | `test_crossverify_model` |
| 2 | WP1 | `feat(2a): read-only IPCAT collector + snapshot freeze` | `test_crossverify_collector` |
| 3 | WP3 | `feat(2a): T3 track via unchanged WP-C lane (regression anchor)` | `test_crossverify_t3` reproduces 6 verdicts |
| 4 | WP4 | `feat(2a): T1 GPIO validation (DIRECT authority)` | T1 cases in `test_crossverify_core` |
| 5 | WP5 | `feat(2a): T2 bus validation (swi union+stability)` | T2 cases |
| 6 | WP6 | `feat(2a): T5 DTS consistency (donor-bug KB rule)` | T5 cases |
| 7 | WP7 | `feat(2a): T4a endpoint validation + T4b out-of-scope stub` | T4a/T4b cases |
| 8 | WP8 | `feat(2a): renderer + worklist + confidence report + report section` | `test_crossverify_render`; full suite green |

**Rationale:** model → collector → **regression anchor first** (nothing trusted until T3 reproduces Phase-1C), then tracks in V2 priority order, renderer last so it renders the complete row set. The WP-C lane is untouched across all eight commits; `main.py` is touched only in commit 8, and only additively.

---

## 6. Constraints honoured

- **WP-C lane unchanged** — `cardinality.py`/`cardinality_config.py` not modified; used via public `compare_element_counts` only; `28f2f07` pinned in provenance.
- **Additive, diagnostic-only** — no onboarding decision, promotion, or gating path reads Phase-2A output; `main.py` gains one null-guarded section, matching the Confidence Ledger / Cardinality Authority contract.
- **Security envelope** — read-only allow-list; TLS `verify=True` (`SSL_CERT_FILE` → system CA store); `auth.json` presence-check only; `.credentials.json` never read; token by reference; no fabricated values (unknown → recorded `unavailable`).
- **Headless CI** stays out of scope pending D3; attended runs proceed as in Phase-1C.

---

*Implementation plan only. No code, no implementation, no probe changes, WP-C lane referenced as unchanged (`28f2f07`), nothing committed. All file names and integration points trace to the existing repo layout (`orchestrator/reasoning/`, `orchestrator/runners/`, `main.py` render hooks, `tests/`).*
