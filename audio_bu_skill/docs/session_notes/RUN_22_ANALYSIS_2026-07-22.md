# Run-22 Analysis — 2026-07-22

**Session focus:** Root-cause the north-star gap (only 1/4 artifacts generated)
and produce the Phase-3A implementation plan.
**HEAD:** d8edec2 · **Targets inspected:** nord-iq10, eliza · **MCP:** down this run.

---

## 1. What was measured

| Run | MCP | Result |
|---|---|---|
| 21 | up | 3× GeneratorSkipped + 1× GeneratedArtifact |
| 22 | down | 3× GeneratorSkipped + 1× GeneratedArtifact |

Identical outcome regardless of MCP state → **MCP is not the blocker.**

## 2. Root cause (confirmed by reading code, not inferred)

The four generation skills:

| Generator | File:line | is_open gate | Source channel |
|---|---|---|---|
| machine_driver | machine_driver.py:217-226 | `T1.gpio.i2s.*` | `audio_topology.pinmux` |
| codec_stub | codec_stub.py:214-222 | `T4a.qup.*` | `audio_topology.endpoints` |
| dt_scaffolding | dt_scaffolding.py:205-243 | `T5.dts.firmware` | `targets/<t>/dts/` |
| audioreach_topology | — | *(none)* | — → always produces |

- `is_open()` (reasoning/model.py:213-237) is **fail-closed**: OPEN iff row
  exists AND `warning=False` AND verdict ∈ {MATCH, PARTIAL_MATCH}. Missing row
  → not open.
- Rows go missing at the **source** step. `_crossverify_source_facts`
  (main.py:1099-1113) reads pinmux/endpoints; `_load_dts_files`
  (main.py:1118-1137) reads the DTS dir; `track_t1`/`track_t4a`/`track_t5`
  return `[]` on empty source (crossverify.py:416-417, 1816-1817) **before**
  MCP is consulted.

**Empirical confirmation (this session):**
- Nord `profile.json`: `audio_topology.pinmux=None`, `.endpoints=None`, no
  `targets/nord-iq10/dts/`.
- Eliza `profile.json`: same; no `targets/eliza/dts/`.

→ **Root cause: empty profile source side.** Not MCP, not IPCAT acquisition.

## 3. Correction to prior framing

- **WP-D and WP-E are NOT "uncommitted partial work"** (as the task premise
  stated). They are COMMITTED and substantial:
  - WP-D: `1afec36` (catalog + requirements schema, ~1079 LOC + ~479 test LOC).
  - WP-E: `4af8bdd` (advisory provenance registry, ~2688 LOC + ~1186 test LOC).
  - Both **inert by design** (not imported by main.py or the onboarding runner).
- Remaining Phase-3A effort is therefore **WP-MCP-BANNER + WP-SRC + WP-F + WP-G**,
  not "finish WP-D/WP-E."
- **G-3A.1 was mis-scoped:** it attributed the generation gap to missing live
  IPCAT acquisition. The gap precedes IPCAT entirely (empty source). G-3A.1
  Status block corrected; new **G-3A.7** tracks the true root cause.

## 4. Decisions

- **Sequencing: Option B** — insert WP-SRC into Phase-3A.
  Order: **WP-MCP-BANNER → WP-SRC → WP-F → WP-G** (WP-D/WP-E already landed).
- **WP-SRC is the only WP that moves the north star.** WP-D/E/F/G are
  diagnostic/advisory and, by their own architecture, cannot flip an is_open
  gate. Shipping Phase-3A without WP-SRC would leave the GOAL definitionally
  unreachable.
- WP-SRC feeds the *existing* plumbing (`_crossverify_source_facts` +
  `_load_dts_files`) — **no new pipeline seam**.
- The codegen engine seam (orchestrator/codegen/, untracked, NullEngine default;
  ClaudeCodeEngine/QGenieEngine raise NotImplementedError) is **not** touched by
  WP-SRC — engine activation is deferred to Phase-3B.

## 5. STOP condition recorded

> If WP-SRC lands and Nord is still 1/4, the source→gate causal model is
> falsified — halt and re-diagnose the specific is_open row that did not open.
> If any 3 WPs land and Nord is still 1/4, the plan's central thesis is wrong —
> halt and re-plan.

## 6. Artifacts written this session

- `docs/PHASE3A_IMPLEMENTATION_PLAN.md` (§1–§9 full plan; recommends Option B;
  specifies WP-SRC, WP-MCP-BANNER, WP-F, WP-G).
- `docs/PHASE3_KNOWN_GAPS.md`: added G-3A.6 (silent MCP degradation), G-3A.7
  (empty source root cause); corrected G-3A.1 Status.
- This note.

**No code modified. Nothing staged or committed.** (Standing constraints:
do not modify hydrate_venv.sh / main.py / skill code; do not stage or commit;
do not delete .venv.)

## 7. Confirmed-vs-inferred ledger

- **Confirmed by reading code:** gate lines, is_open() semantics, source
  short-circuit lines, silent try/except points, NullEngine default.
- **Confirmed by reading data:** Nord/Eliza profile.json empty pinmux/endpoints,
  absent dts/ dirs, run-21/22 outputs.
- **Inferred (marked):** that WP-SRC will move Nord to ≥3/4 — this is the
  *hypothesis* the STOP condition guards, not yet an observed fact.
