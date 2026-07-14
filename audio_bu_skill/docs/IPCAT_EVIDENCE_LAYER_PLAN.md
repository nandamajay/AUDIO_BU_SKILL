# IPCAT Evidence Layer — Architecture Review & Plan

**Status:** Planning / architecture review only. No code, DTS, YAML, or patches produced.
**Reference studied:** `git@github.qualcomm.com:soumbane/EVA_QLI_DT_Generator.git` (single script `generate_cvp_dtsi.py`, ~2207 lines).
**Subject under review:** Audio BU Skill onboarding (`orchestrator/`, `skills/target_onboarding/`).
**Date:** 2026-07-13

> **Scope guard.** This document evaluates whether EVA's IPCAT/evidence-acquisition
> concepts (and any other transferable ideas) would strengthen Audio BU Skill
> onboarding. It is a *review and a plan*, not an implementation. EVA is Qualcomm
> internal and CVP/EVA-specific; **no EVA code is to be copied** — only its
> *architectural pattern* is evaluated for adaptation.

---

## 0. Executive summary

EVA and Audio BU Skill sit at opposite ends of the same spectrum.

- **EVA is evidence-first.** It fetches exact hardware facts from IPCAT
  deterministically *in Python* (register bases, IRQ numbers, clock freq plans),
  parses SID/power-domain/clock tables from source docs, and only *then* hands a
  structured, pre-computed, per-field-cited data bundle to QGenie — whose job is
  narrowed to *filling a fixed template*, never inventing values. Unknowns are
  flagged `[VERIFY]`/`[DEFAULT]`/`[INFO]`, never silently guessed.

- **Audio BU Skill is reasoning-first.** It resolves paths, does git archaeology,
  one rpmhpd source parse, and a pin cross-check — then delegates essentially *all*
  hardware-fact extraction (SoC/board, codecs, amps, mics, speakers, buses,
  SoundWire, LPASS/ADSP/AudioReach stack, clocks, IRQs, register bases, SID/IOMMU,
  remoteproc) to QGenie via `Read/Grep/Glob` + a live IPCAT MCP query the
  orchestrator **cannot observe** (it relies on QGenie's `ipcat_findings`
  self-report).

**The single most important finding:** Audio BU Skill has **no deterministic IPCAT
evidence layer**. IPCAT is reached only as (a) a pre-fetched offline file cache the
code merely globs, or (b) an LLM-issued MCP `search_content` over HPG *prose*
documents — which, per Eliza's own recorded `missing_evidence`, does **not** return
register/GPIO/power-domain/SID tables. This maps 1:1 onto the benchmark findings we
care about: poor IPCAT coverage, missing power-model evidence, missing clock
evidence, missing dependency evidence.

**Recommendation:** Adopt EVA's *evidence-first pattern* (deterministic
pre-computation with provenance + explicit unknown-flagging), but **not** its code
and **not** its CVP-specific extractors. Build a small, audio-shaped
`IpcatEvidenceProvider` that produces a structured, cited evidence bundle *before*
QGenie reasoning, narrowing QGenie's job from "find and infer everything" to
"corroborate, resolve, and rank against pre-computed facts." Stage it behind the
existing strict/no-fallback contract, and gate the deepest extraction work until
*after* Benchmark A/B has quantified where reasoning-only actually fails.

---

## 1. Current Audio BU Skill architecture

### 1.1 Onboarding data flow

`run_target_onboarding()` → `resolve_onboarding_task_spec()`
(`orchestrator/runners/target_onboarding_runner.py`):

1. Resolve kernel path.
2. `discover_evidence(...)` → evidence file list + IPCAT provenance sidecar
   (`source_intake_runner.py`; globs `evidence/ipcat/` and `evidence/offline/`).
3. Kernel commit hash.
4. `discover_kernel_history(...)` — FROMLIST/RFC git archaeology
   (`kernel_history_discovery.py`), read-only, now with candidate reduction
   (Commit B).
5. `_power_model_hint(...)` — `find_target_rpmhpd_compatible` +
   `inspect_power_model_source` (`power_model_inspection.py`), rpmhpd LCX/LMX parse.
6. Candidate targets: local DB (`_candidate_targets`) + history-derived donors.
7. `_build_task_spec(...)` — assembles **paths and refs only, never file bytes**;
   sets `evidence["ipcat_mcp"] = True` when an offline IPCAT provenance sidecar
   exists.
8. **QGenie reasoning (mandatory):** `client.analyze(task_spec, ANALYSIS_SCHEMA)`.
9. `cross_check_pins(...)` — matches QGenie's `schematic_nets` GPIOs against
   candidate-patch DT diffs.
10. `_map_analysis_to_envelope(...)` — builds `generated_case`, `audio_topology`,
    NEEDS_REVIEW list, IPCAT summary.
11. Attach reasoning provenance + fingerprints.

### 1.2 What is deterministic today (the existing "evidence layer")

| Extractor | File | Produces |
|---|---|---|
| Evidence discovery + IPCAT provenance | `source_intake_runner.py` | file lists, `ipcat_mcp` flag |
| Kernel commit + per-file SHA256 | `target_onboarding_runner.py` | fingerprints |
| FROMLIST/RFC candidate series | `kernel_history_discovery.py` | patch candidates (sha, subject, files, donor hints) |
| rpmhpd power-model **hint** | `power_model_inspection.py` | LCX/LMX presence, graded status (corroborating only) |
| Candidate targets (local DB) | `_candidate_targets` | nearest-target seed list |
| Codec **verdict** (driver-on-disk) | `_derive_codec_verdicts` | `upstream_present`/`unresolved` (post-QGenie) |
| Pin cross-check | `pin_crosscheck.py` | GPIO ↔ DT verdicts (post-QGenie) |

### 1.3 What is delegated wholesale to QGenie

Via `build_prompt()` (`client.py:367-406`) + `ANALYSIS_SCHEMA`
(`schemas.py`, v1.2.0): SoC/board identity, all codecs/amps/mics/speakers, buses,
SoundWire present/master-count, LPASS/ADSP/AudioReach/GPR/APM/q6apm/q6prm booleans,
power-model *kind* (rpmhpd vs SCMI), nearest-target ranking, missing-evidence, and
the IPCAT self-report — all read/inferred by the model, then schema-validated.

### 1.4 Key properties (to preserve)

- **Strict, no silent fallback** — `ReasoningUnavailableError` with typed `.code`;
  local heuristic engine is test-gated only (`get_reasoning_client`).
- **`ANALYSIS_SCHEMA` is an *output contract*, not a pre-computed evidence store.**
  Every finding carries per-field `confidence` + `citations`.
- **`power_model` is never auto-finalized** — always `needs_review = true` (the
  Nord rpmhpd-vs-SCMI blocker class).
- **The orchestrator cannot observe QGenie's MCP calls** — `ipcat_findings` is a
  self-report, structurally unverifiable.

---

## 2. EVA architecture summary

EVA generates an upstream CVP/EVA DTSI (and optional YAML binding) for a new SoC.
Single script, staged pipeline:

1. **Chip resolution** — `get_chip_name_for_swi` / `get_chip_candidates` /
   `list_ipcat_targets` against the `ipcat_client` **Python library** (not MCP).
2. **Deterministic IPCAT fetch** (each written to a CSV/dict):
   - `swi.get_modules()` → `parse_eva_topology()` (MVS0C = controller → `reg` addr;
     MVS0 = core power domain; EVA_CC = clock controller; address-ordered fallbacks).
   - `irqs.get_interrupts()` → APPS-filtered, **−32 GIC SPI offset**, with
     chip-revision fallback (data split across silicon revs, e.g. `honu_1.0` vs `2.0`).
   - `clocks.get_freqplan_release()` → EVA_CC freq plan → OPP table via
     `build_opp_entries` (mvs0/mvs0c clock pairs).
3. **Source-doc parses** (non-IPCAT evidence):
   - `parse_iommus_from_sid_csv()` — 4 EVA SID slots by SID Name, filtered to
     `Client ∈ {EVA,CVP}`, `Translation Type = Nested`.
   - `parse_power_domains_from_hpg()` — `EVA_CC_*_GDSCR` from HPG HTML.
   - `parse_clocks_from_hpg()` — §3.3/3.4 CBCR `CLK_ENABLE` steps, infra/`_SRC`
     exclusion, clock-name normalization.
4. **Structure-preserving prompt** — reference DTSI is the **sole structural
   authority**; `_build_*_prompt_section` emits per-field DATA blocks each carrying
   *explicit source provenance*. QGenie fills values into a fixed template; it does
   not choose structure and does not invent values.
5. **Self-verification** — `verify_output()`: section presence checks, inline-TODO
   scan, address zero-padding checks, and a byte-integrity check of the annotated
   provenance companion file.

### 2.1 EVA's governing principles

- **Never silently guess.** Every unknown is flagged `[VERIFY]` (unproven for this
  target), `[DEFAULT]` (carried from reference), or `[INFO]` — written to a log.
- **Provenance per field.** Each generated value knows where it came from (IPCAT SWI
  / IPCAT IRQ / EVA_CC freq plan / HPG HTML / SID CSV / reference default).
- **Deterministic first, reasoning last.** The LLM's surface area is minimized to
  template-filling over pre-computed, sourced data.
- **Confidence honesty.** `TODO_confidence_status.md` states plainly which fields
  are trustworthy (reg/IRQ/clock) vs. unproven (SID/iommus).

---

## 3. Gap analysis

Answering the review's 7 questions directly.

### Q1 — Which IPCAT artifacts does EVA collect?

Via the `ipcat_client` **library** (deterministic, structured):

| Artifact | IPCAT call | Field it feeds |
|---|---|---|
| HW modules (name, base addr, size) | `swi.get_modules()` | `reg` base address, node topology |
| Interrupt vectors | `irqs.get_interrupts()` / `get_latest_interrupt_map()` | `interrupts` (APPS-filtered, −32 offset) |
| Clock freq plans | `clocks.get_freqplan_release()` / `get_freqplan_data()` | OPP table, clock rates |
| Chip aliases / revisions | `chips.get_chips()` | chip resolution, revision fallback |

Plus **non-IPCAT** structured evidence: SID mapping CSV (iommus), EVA HPG HTML
(power-domain GDSCs, clock enable sequence).

### Q2 — Which artifacts would improve our discovery, per domain?

| Audio BU domain | EVA artifact that maps to it | Benefit |
|---|---|---|
| **Power model** | `swi.get_modules()` (LPASS/ADSP block presence + base) + HPG GDSC parse | Corroborates rpmhpd-vs-SCMI with *register-level evidence*, not just rpmhpd.c LCX/LMX presence. Directly attacks the Nord blocker. |
| **Topology** | `swi.get_modules()` (LPASS/WSA/VA/TX/RX macro block bases) | Deterministic "these audio HW blocks exist at these addresses" — a factual spine QGenie ranks codecs/buses against. |
| **AudioReach** | (weakly) module presence for LPASS DSP subsystem | Confirms the DSP/AudioReach substrate exists; the stack booleans stay reasoning-derived. |
| **Clocks** | `clocks.get_freqplan_release()` (LPASS_CC / audio clock controller) | The biggest single win: exact clock names + rates, which QGenie cannot reliably read from prose HPG today. |
| **remoteproc (ADSP)** | `swi.get_modules()` ADSP base + IRQ + HPG power-on sequence | Deterministic ADSP reg/IRQ/power-domain facts to anchor remoteproc config. |
| **SID / IOMMU** | SID CSV parse pattern (Client/Translation-Type filter) | A deterministic stream-ID extractor keyed to LPASS/ADSP clients — currently *entirely absent*. |

### Q3 — Which EVA concepts are generic and reusable?

- **The evidence-first pattern itself** (deterministic pre-compute → structured
  cited bundle → narrowed LLM job). This is the crown jewel and is domain-agnostic.
- **Per-field provenance tagging** (every value knows its source).
- **Explicit unknown-flagging vocabulary** (`[VERIFY]`/`[DEFAULT]`/`[INFO]`) — maps
  cleanly onto our existing `confidence` + `needs_review` + `missing_evidence`.
- **`ipcat_client` library access** (structured queries) vs. our MCP-prose search —
  a strictly better IPCAT access mode for factual tables.
- **Chip-revision fallback** logic (data split across silicon revisions).
- **APPS-filtering + GIC SPI −32 offset** convention for interrupts (a Qualcomm-wide
  fact, reusable verbatim as *knowledge*, not code).
- **Post-generation self-verification** (`verify_output`) — analogous to a
  post-analysis validator we could add.

### Q4 — Which EVA concepts are CVP/EVA-specific and should NOT be reused?

- MVS0C/MVS0/EVA_CC topology detection and its address-ordered fallbacks.
- The 4-slot EVA SID layout and EVA/CVP `Client` filter values.
- The CVP OPP-pairing (`mvs0`/`mvs0c`) logic.
- DTSI/YAML structure-preserving generation and the reference-DTSI-as-authority
  model — **we are onboarding/analysis, not DTSI generation.** (Relevant later to
  the Phase-2 generation framework, *not* to onboarding.)
- The HPG §3.3/3.4 clock-sequence parser (CVP HPG document shape).
- All hard-coded EVA register/GDSC/clock name maps.

### Q5 — Does EVA have an "evidence layer" we're missing?

**Yes — unambiguously.** EVA has a deterministic, structured, per-field-cited
evidence layer computed *before* the LLM ever runs. Audio BU Skill has only
scattered corroborators (rpmhpd hint, kernel history, pin cross-check) and no
IPCAT-fact extraction at all. Our `ANALYSIS_SCHEMA` is an *output contract*; EVA's
CSV/dict bundle is an *input evidence store*. That input evidence store is the
missing layer.

### Q6 — Would adopting it improve nord-iq10 and eliza results?

- **nord-iq10:** Directly. The open blocker is rpmhpd-vs-SCMI + logical-port
  ambiguity (see memory: `nord-iq10-audio-facts`). Deterministic LPASS/ADSP module
  bases, ADSP IRQs, and clock names give QGenie factual anchors instead of
  prose-inference, and give the human reviewer register-level corroboration for the
  power-model decision that is currently forced to NEEDS_REVIEW with weak evidence.
- **eliza:** Directly. Eliza's recorded `missing_evidence` explicitly lists
  register/GPIO/power-domain/SID tables that the MCP prose search failed to return.
  A structured IPCAT provider would supply exactly those.

### Q7 — Which benchmark findings would it address?

| Benchmark finding | Addressed by |
|---|---|
| Poor IPCAT coverage | Structured `ipcat_client`-style provider replacing prose MCP search |
| Missing power-model evidence | Deterministic LPASS/ADSP module + GDSC extraction |
| Missing clock evidence | Deterministic audio clock-controller freq-plan extraction |
| Missing dependency evidence | Module/IRQ/power-domain graph feeding remoteproc + topology anchors |

All four map directly. This is the strongest argument for the layer.

---

## 4. Recommended Audio BU Skill architecture

Adopt EVA's *pattern*, adapted to audio and to our existing strict contract.
**Do not** copy EVA code; **do not** turn onboarding into a generator.

```
resolve_onboarding_task_spec()
  ├─ discover_evidence            (existing)
  ├─ discover_kernel_history      (existing, Commit B)
  ├─ _power_model_hint            (existing rpmhpd parse)
  ├─ candidate targets            (existing)
  ├─ NEW: IpcatEvidenceProvider ──────────────────────────┐
  │     deterministic pre-compute, structured + cited:     │
  │       • audio HW modules (LPASS/WSA/VA/TX/RX/ADSP)      │
  │         → name, base addr, size                          │
  │       • ADSP/LPASS interrupts (APPS-filtered, −32)       │
  │       • audio clock-controller freq plan (names+rates)   │
  │       • (later) SID/IOMMU stream IDs for LPASS clients   │
  │     → writes evidence/ipcat/derived/*.json + provenance  │
  │     → strict: unavailable ⇒ typed error OR flagged gap,  │
  │       never a fabricated value                           │
  └─ _build_task_spec  ── now carries a PRE-COMPUTED, CITED  │
                          ipcat_evidence bundle ◄────────────┘
                                    │
                          QGenie reasoning (narrowed):
                          "corroborate & resolve against these
                           facts; rank nearest targets; flag
                           conflicts" — not "find everything"
                                    │
                          _map_analysis_to_envelope
                          + NEW post-analysis validator:
                            cross-check QGenie claims vs. the
                            deterministic bundle; downgrade
                            confidence / raise needs_review on
                            conflict (EVA verify_output analogue)
```

Design invariants:

- **The evidence provider is additive.** It feeds QGenie better inputs; it never
  replaces the reasoning step and never auto-finalizes anything.
- **Preserve strict no-fallback.** If IPCAT access fails, emit a typed error or a
  clearly-flagged gap in the bundle — never a guessed value (EVA's "never silently
  guess", expressed in our `confidence`/`missing_evidence`/`needs_review` vocabulary).
- **Provenance carries through.** Each derived fact records its IPCAT source; the
  post-analysis validator uses it to detect QGenie/evidence conflicts.
- **`power_model` stays `needs_review`.** The new evidence *strengthens* the human's
  decision; it does not remove the gate.
- **Access-mode decision (open):** structured `ipcat_client` library vs. staying on
  MCP. Library gives structured tables (EVA's advantage) but adds a dependency +
  interactive auth; MCP is already wired but returns prose. This is the key design
  fork — resolve it in Phase 1 with a spike, informed by benchmark data.

---

## 5. Implementation phases

> All phases are *future* work. Nothing here is authorized to start by this document.

**Phase 0 — Spike & decide access mode (small, no product code).**
Evaluate `ipcat_client` structured queries vs. MCP for the audio clock controller
and LPASS/ADSP module tables on one known SoC. Output: a decision note on which
access mode returns register/clock/SID tables reliably. Non-invasive.

**Phase 1 — `IpcatEvidenceProvider` skeleton (modules + IRQs).**
Deterministic extraction of audio HW module bases and ADSP/LPASS interrupts into a
structured, cited `evidence/ipcat/derived/*.json`, plus provenance sidecar. Wire
into `_build_task_spec` as an *additive* bundle. Strict error on unavailability.
Fully unit-tested with recorded IPCAT fixtures (no live calls in tests).

**Phase 2 — Clock evidence.**
Add audio clock-controller freq-plan extraction (names + rates). This is the
highest-value single field per Q7.

**Phase 3 — Post-analysis validator (EVA `verify_output` analogue).**
Cross-check QGenie's returned analysis against the deterministic bundle; on
conflict, downgrade `confidence` and/or raise `needs_review` and record it in
`missing_evidence`. Purely defensive; cannot fabricate.

**Phase 4 — SID/IOMMU extraction (audio-shaped).**
A deterministic stream-ID extractor for LPASS/ADSP clients, adapting EVA's
Client/Translation-Type *filter idea* (not its EVA slot layout). Lowest confidence
domain in EVA; treat outputs as `[VERIFY]`-equivalent by default.

**Phase 5 — Dependency graph.**
Combine modules + IRQs + power domains into a small dependency map to anchor
remoteproc/topology reasoning.

Each phase ships behind the strict contract, with fixtures, and leaves QGenie as the
decision-maker.

---

## 6. Priority ranking

Ranked by (benchmark impact × feasibility ÷ risk):

1. **Phase 0 spike (access mode).** Unblocks everything; near-zero risk. **Do first.**
2. **Phase 2 clock evidence** *(after Phase 1 skeleton exists).* Highest single-field
   benchmark impact (missing clock evidence); QGenie is weakest here from prose.
3. **Phase 1 modules + IRQs skeleton.** The structural prerequisite; medium impact,
   medium effort. Enables 2–5.
4. **Phase 3 post-analysis validator.** High trust/quality impact, low risk, and it
   protects against the reasoning-only failure modes the benchmark will expose.
5. **Phase 5 dependency graph.** Medium impact; depends on 1.
6. **Phase 4 SID/IOMMU.** Real gap, but EVA itself rates it lowest-confidence; do
   last and keep it `[VERIFY]`-flagged.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **IPCAT auth / access in headless runs** — `ipcat_client` uses interactive getpass + keyring; onboarding runs headless. | High | Phase 0 must confirm a non-interactive auth path (pre-seeded keyring / service cred) before committing to the library mode. If none, stay on MCP + structured prompting. **Do not** scan env/history for creds — ask the user. |
| **Adding a hardware dependency** (`ipcat_client`) to a currently-thin orchestrator. | Med | Keep the provider isolated behind an interface; fall back to MCP; test with fixtures only. |
| **Over-trusting deterministic values** — EVA itself flags SID as unproven. | Med | Carry provenance + confidence; never auto-finalize; validator downgrades on conflict; keep `power_model` NEEDS_REVIEW. |
| **Scope creep toward DTSI/YAML generation** (EVA's actual job). | Med | Explicit invariant: onboarding stays analysis-only; generation is the separate Phase-2 framework. |
| **Silent regression of the strict contract.** | High | New provider must raise `ReasoningUnavailableError`-style typed errors, never substitute heuristics; covered by tests mirroring the existing no-fallback tests. |
| **Building against unmeasured failures.** | Med | Sequence real extraction *after* Benchmark A/B quantifies where reasoning-only fails (see §8/§9). |
| **CVP-specific mis-adaptation** (copying EVA topology/SID logic verbatim). | Med | §4 Q4 exclusion list; adapt *patterns*, author audio-specific extractors fresh. |

---

## 8. What to implement BEFORE Benchmark A/B

**Rationale:** only work that *does not perturb the measured system* and that makes
the benchmark itself more informative.

- **Phase 0 spike only** (access-mode decision note) — read-only investigation,
  outside the onboarding path, changes no behavior.
- **Instrumentation, not extraction:** ensure the current runs *record* what IPCAT
  MCP returned vs. what was missing (Eliza already does via `missing_evidence` /
  `ipcat_findings`) so Benchmark A/B produces a clean baseline of the exact gaps the
  evidence layer would fill. If any gap in that logging exists, closing it is
  in-scope pre-benchmark (diagnostic only).

**Do NOT** build the `IpcatEvidenceProvider` or any extractor before the benchmark —
that would change onboarding outputs and contaminate the A/B comparison.

## 9. What to implement AFTER Benchmark A/B

Once the benchmark has quantified where reasoning-only actually fails:

- **Phase 1–2** (modules/IRQs skeleton + clock evidence) — targeted at the domains
  the benchmark shows QGenie missing.
- **Phase 3** post-analysis validator.
- **Phase 4–5** (SID/IOMMU, dependency graph) — lowest priority, benchmark-justified.

The evidence layer becomes "Benchmark C": re-run the same targets with the provider
enabled and measure the delta in IPCAT coverage, power-model evidence, clock
evidence, and dependency evidence — the four findings from Q7.

---

## Appendix A — Concept adoption matrix

| EVA concept | Adopt? | As |
|---|---|---|
| Evidence-first pattern (pre-compute → cite → narrow LLM) | ✅ | Core architecture (§4) |
| Per-field provenance | ✅ | Bundle metadata + validator |
| `[VERIFY]`/`[DEFAULT]`/`[INFO]` flagging | ✅ (mapped) | Existing `confidence`/`needs_review`/`missing_evidence` |
| `ipcat_client` structured access | 🔶 pending | Phase 0 decision (auth risk) |
| Interrupt APPS-filter + −32 GIC offset | ✅ (knowledge) | Phase 1 IRQ extractor |
| Chip-revision fallback | ✅ (knowledge) | Phase 1 chip resolution |
| Post-gen self-verification | ✅ (adapted) | Phase 3 validator |
| SID Client/Translation-Type filter idea | 🔶 | Phase 4, audio-shaped |
| MVS0C/MVS0/EVA_CC topology | ❌ | CVP-specific |
| CVP OPP pairing | ❌ | CVP-specific |
| DTSI/YAML structure-preserving generation | ❌ (here) | Onboarding is analysis-only; relevant to Phase-2 generation, not this layer |
| HPG §3.3/3.4 parser | ❌ | CVP HPG-doc-specific |

## Appendix B — Evidence sources for this review

- Audio BU Skill: `orchestrator/reasoning/client.py`, `orchestrator/reasoning/schemas.py`,
  `orchestrator/runners/target_onboarding_runner.py`,
  `orchestrator/runners/source_intake_runner.py`,
  `orchestrator/runners/kernel_history_discovery.py`,
  `orchestrator/runners/power_model_inspection.py`,
  `orchestrator/runners/pin_crosscheck.py`, `targets/eliza/qgenie_analysis.json`,
  `targets/nord-iq10/case.py`.
- EVA_QLI_DT_Generator: `generate_cvp_dtsi.py` (full), `README.md`,
  `reference_cvp/README.md`, `sid_sheets/README.md`, `TODO_confidence_status.md`.
