# IPCAT Capability Assessment — Audio BU Skill vs. EVA_QLI_DT_Generator vs. camera_dtsi

**Status:** Architecture and evidence assessment only. No code, DTS, YAML, or patches produced. No changes to Audio BU Skill.
**Purpose:** Challenge the existing `docs/IPCAT_EVIDENCE_LAYER_PLAN.md` roadmap against a *second* reference system before any Phase-0/1 work starts.
**References studied:**
- `git@github.qualcomm.com:soumbane/EVA_QLI_DT_Generator.git` — `generate_cvp_dtsi.py` (2206 lines), `README.md`, `TODO_confidence_status.md`.
- `git@github.qualcomm.com:gjindal/camera_dtsi.git` — `SKILL.md` (409 lines), `learn/SKILL.md` (175 lines), `references/kb/*.md` (17 files), `references/bus_nodes_kb/bus_nodes_rules.md`, `mcp/camera_ipcat_mcp/` (server, auth, credentials, 6 tool modules), `mcp/scripts/cam_dtsi_tool.py`, `README.md`, `OVERVIEW.md`.
- Audio BU Skill: `docs/IPCAT_EVIDENCE_LAYER_PLAN.md` (the existing "current plan" being challenged here), plus its cited source files.

> **Scope guard, restated.** This document does not assume the existing plan is optimal. Where camera_dtsi contradicts or improves on the existing plan's assumptions, that is called out explicitly in §11 ("Challenge the current plan"). No implementation follows from this document.

---

## 1. Current Audio BU Skill IPCAT flow

(Unchanged from the existing plan's §1 — re-summarized here for a self-contained three-way comparison.)

IPCAT is reached in exactly two ways today, neither deterministic:

1. **Offline file cache glob.** `source_intake_runner.py` globs `evidence/ipcat/` and `evidence/offline/` for whatever files were pre-dropped into the target's evidence folder, and sets a boolean `evidence["ipcat_mcp"] = True` when a provenance sidecar exists. No parsing of register/clock/SID content happens here — it is a file-presence check.
2. **QGenie-issued MCP prose search.** The orchestrator hands QGenie a task spec and lets it call an IPCAT MCP tool (`search_content`-shaped) on its own initiative. The orchestrator **cannot observe the call** — it only sees QGenie's self-reported `ipcat_findings` (schema v1.2.0: `queried`, `returned_target_specific`, `returned_generic_only`, `notes`, `citations`). Per Eliza's own recorded `missing_evidence`, this path does not reliably return register/GPIO/power-domain/SID tables — it returns prose that QGenie must further interpret.

Everything else deterministic today (kernel history, rpmhpd hint, pin cross-check, codec verdict) is **not** IPCAT — it is git/source-tree archaeology. There is no code path in Audio BU Skill that fetches a structured IPCAT table and hands rows to QGenie or a validator. This is the finding the existing plan already reached; nothing found this session changes it.

---

## 2. EVA IPCAT flow

(Confirmed again this session via `TODO_confidence_status.md`, no material change from the existing plan's §2.)

EVA is a **single Python script** that calls the `ipcat_client` **library** directly — `swi.get_modules()`, `irqs.get_interrupts()`, `clocks.get_freqplan_release()`, `chips.get_chips()` — writes each result to CSV/dict, layers non-IPCAT source-doc parses (SID CSV, HPG HTML) on top, then hands QGenie a **structure-preserving prompt**: the reference DTSI is the sole structural authority, and per-field DATA blocks carry explicit provenance. QGenie fills a fixed template; it does not choose structure or invent values. `verify_output()` performs post-generation self-checks (section presence, inline-TODO scan, address padding, byte-integrity of the provenance companion file).

`TODO_confidence_status.md` (read this session) is a small but important artifact: it is a **human-readable confidence ledger**, hand-maintained, stating flatly which fields are trustworthy (`reg`/`interrupts`/clock names — IPCAT-sourced) vs. unproven (`iommus`/SID — copied from reference, never validated against a real SID sheet for the new target). This is EVA's confidence-honesty principle made concrete as a *document*, not just a code convention — a lightweight artifact Audio BU Skill does not currently produce per target.

Auth: `setup_auth()` in the underlying tool tries, in order, a cached token file (`~/.ipcat_token`, mode 600), then `IPCAT_TOKEN` env var, then `IPCAT_USER`/`IPCAT_PASSWORD` env vars, then falls back to interactive `getpass`. **This confirms the existing plan's flagged risk is real** (interactive fallback exists) but also confirms a **working headless path already exists in EVA's own code**: env-var override is suffuncitonal today, not hypothetical.

---

## 3. camera_dtsi IPCAT flow

This is the new system studied this session, and it is architecturally the **opposite** of EVA on one axis while converging with it on another.

**Opposite axis — code generation.** camera_dtsi's `SKILL.md` states as a *hard constraint*: "NEVER write a Python script, shell script, or any code to generate or fix the DTSI... The entire generation is LLM reasoning + MCP tool calls + writing the output file. Nothing else." Where EVA writes a 2200-line generator script, camera_dtsi writes zero generation code — the LLM does 100% of the DTSI authorship, guided by markdown rules.

**Converging axis — IPCAT access is still deterministic and structured, just via MCP instead of a library.** The `camera-ipcat` MCP (`mcp/camera_ipcat_mcp/`) is a local stdio server with 6 tools (`get_chip_id`, `get_irqs`, `get_addresses`, `get_freq_plan`, `get_sids`, `get_clocks`). Critically, **each tool itself does the deterministic fetch-and-shape work in Python** (`cam_dtsi_tool.py`, 1216 lines, plus `trim_freq_plan.py`) — downloading, filtering to camera-relevant block prefixes (`TITAN`, `RPMH_PDC_CAM`), trimming XLSM freq-plan sheets to CSV rows, and caching per-target results to disk (`~/.cache/cam-dtsi-skill/<target>/*.csv`) and in-process. The LLM never gets raw IPCAT prose or an unbounded dump — it gets **typed rows** (`{"Block Name":..., "Base Address":..., "Size":...}`, per-clock dicts with per-level rate columns) it can filter further via a `filter`/`clocks` MCP argument. So: same "structured facts before reasoning" principle as EVA, delivered through an MCP tool boundary instead of a Python library import into the orchestrator.

**The knowledge base (`references/kb/`) is the real innovation relative to both EVA and the existing plan.** It is 17 markdown files (one per camera IP block: cpas, csiphy, cci, csid, csid_lite, vfe, vfe_lite, rt_cdm, icp, ipe, ofe, jpeg_enc, jpeg_dma, csiphy_tpg, sfe, bps) plus a global `00_index.md`. Each file encodes, in prose+tables, **how a raw IPCAT block name maps to a DTSI field** for each of 4 reference chipsets already learned (pakala/SM8750, hawi/SM8975, kaanapaliT/SM8850, waipio/SM8450) — e.g. `cpas.md`'s per-chipset table of `reg-name → IPCAT block → secure_offset → cam_base`. This is not a data cache; it is a **hand/LLM-curated rulebook** that the generation skill re-reads every run. It is populated and grown by a **separate maintainer skill** (`learn/SKILL.md`): given a new (chipset, reference-DTSI) pair, the LLM fetches IPCAT for that chipset, diffs it node-by-node against the DTSI, derives the block→field mapping and IRQ-offset/secure-offset rules, and **writes updates back into the KB files**, flagging contradictions with existing chipsets as `WARN:` rather than overwriting. The maintainer then commits/pushes; users pull via `update.sh`. This learn-then-persist-then-share loop has no analogue in EVA (whose "knowledge" is hard-coded Python constants) or in the existing Audio BU Skill plan (which proposes hand-authored extractors, not a growing shared rulebook).

**Explicit anti-guessing constraints, written as hard rules, not narrative principles:**
- "NEVER map or interpolate freq plan levels to match base DTSI levels — the number of levels in the output DTSI WILL differ from the base DTSI and that is correct and expected."
- "NEVER use addresses or IRQs from another chipset as fallback — these MUST come from IPCAT for the actual target."
- `reg_format` (2-cell vs 4-cell) is declared **mandatory user input, never inferred** — "STOP immediately and ask" if not given in the prompt, with the exact question text specified in `SKILL.md`.
- `get_chip_id` failure → "STOP immediately... DO NOT guess other aliases... DO NOT try kera, niobe, pineapple..." (a real historical mistake, evidently, now codified as a rule).
- **Instance-count authority:** "IPCAT is the ground truth for how many hardware instances exist. The base DTSI is only a structural template — never use its node count as the target count." IPCAT block-name patterns (e.g. `TITAN_A_RT_0_IFE_<N>`) are enumerated first; the base DTSI is cloned/trimmed to match, never trusted for cardinality.

**Credentials/auth (`credentials.py`, `auth.py`):** priority order is (1) `IPCAT_USER`/`IPCAT_PASSWORD` env vars — "always checked first", explicitly for CI; (2) OS keyring; (3) a dedicated mode-600 env file (`~/.config/cam-dtsi-skill/ipcat_env`) written once by an interactive `install.sh` step, sourced by `run_server.sh` instead of `~/.bashrc` "to avoid slow bashrc sourcing." Interactive `getpass` (`store_interactive()`) exists only for the one-time setup flow, not for per-invocation auth.

**Session logging:** every generation writes `session.json` (target, base_dtsi, timestamp, success, nodes_updated, warnings_count), `node_changes.json` (per-node old→new for reg/irq/compatible), and `warnings.txt` to `~/.config/cam-dtsi-skill/logs/<target>_<timestamp>/`. `OVERVIEW.md` frames this explicitly as "a ground truth database — future generations for similar targets can reference past sessions to improve accuracy," though nothing in the reviewed code currently *reads* those logs back in — the framing is aspirational/documented intent, not yet a closed loop.

---

## 4. Comparison table

| Dimension | Audio BU Skill (today) | EVA_QLI_DT_Generator | camera_dtsi |
|---|---|---|---|
| IPCAT access mechanism | LLM-issued MCP prose search (unobservable) + offline file glob | Python `ipcat_client` library, called directly in a script | Local stdio MCP, but each tool internally does deterministic fetch+shape (Python) before returning to the LLM |
| Data returned to the LLM | Free-text search results | Structured CSV/dict, pre-computed | Structured typed rows (dicts), filterable, cached |
| Who writes the DTSI/output | N/A (onboarding is analysis-only) | The Python script (template-fill via LLM narrowed to values only) | The LLM itself (zero generation code) |
| Domain mapping knowledge | Implicit — QGenie infers ad hoc each run | Hard-coded Python constants (MVS0C/MVS0/EVA_CC, 4-slot SID layout) | Explicit markdown KB, one file per IP block, grown across chipsets |
| Knowledge growth mechanism | None | None (constants edited by whoever maintains the script) | Dedicated maintainer skill (`learn-cam-dtsi`) that updates KB from new (chipset, reference) pairs, with conflict flags |
| Unknown-value policy | `confidence` + `needs_review` + `missing_evidence` (schema fields); power_model never auto-finalized | `[VERIFY]`/`[DEFAULT]`/`[INFO]` log tags + `TODO_confidence_status.md` ledger | Hard STOP-and-ask for un-inferable inputs (`reg_format`, chip alias); `/* TODO: verify */` inline markers; per-run `warnings.txt` |
| Cardinality authority | N/A | Reference DTSI implicitly authoritative (topology detection has fallbacks) | IPCAT explicitly authoritative over the base DTSI — codified as a named rule |
| Caching | None for IPCAT (none exists) | None observed (script re-fetches per run) | Disk (`~/.cache/cam-dtsi-skill/<target>/*.csv`) + in-process, per target |
| Auth model | N/A (delegated to QGenie's MCP call, opaque) | Token cache file → env vars → interactive getpass | Env vars (CI-first) → OS keyring → mode-600 file → (setup-time only) interactive getpass |
| Response-size control | N/A | N/A (script controls its own fetch) | `filter=[...]` MCP argument on `get_addresses`/`get_freq_plan`, explicitly to avoid "full response too large" |
| Post-hoc validation | None automated (human review via NEEDS_REVIEW) | `verify_output()`: structural + TODO-scan + integrity checks | None automated beyond inline warnings; relies on KB rules being followed by the LLM at generation time |
| Session artifacts as corpus | Onboarding attempt artifacts exist but aren't deliberately reused as a corroboration corpus | Not really (per-run only) | `session.json`/`node_changes.json`/`warnings.txt` explicitly framed as future ground truth (not yet read back by anything) |

---

## 5. Gaps

Relative to **both** reference systems, Audio BU Skill is missing the same thing the existing plan already identified: **a deterministic, structured IPCAT evidence step before QGenie reasoning.** camera_dtsi does not change that conclusion — it changes *how cheaply and by what mechanism* that step could be delivered:

- Gap 1 (shared with existing plan): No structured IPCAT fetch at all — prose only.
- Gap 2 (new, from camera_dtsi): No **explicit mapping-rule knowledge base**. Even if IPCAT facts were fetched structurally tomorrow, nothing today encodes "this IPCAT block name / clock name corresponds to this audio schema field for chipset family X" the way `references/kb/*.md` does for camera blocks. QGenie currently has to *rediscover* this mapping from scratch every onboarding run, from prose.
- Gap 3 (new, from camera_dtsi): No **cross-run knowledge accumulation loop**. Neither EVA nor the existing plan has one; camera_dtsi's `learn-cam-dtsi` maintainer skill is a working example of turning "we onboarded chipset X and learned its IPCAT-to-DTS mapping" into a durable, shared artifact instead of a one-off analysis.
- Gap 4 (new, from camera_dtsi): No **codified cardinality-authority rule**. Nothing in Audio BU Skill's schema or validators currently states "IPCAT's enumerated instance count for a given audio block type outranks whatever the nearest-target case implies" — a cheap, high-value invariant camera_dtsi states as a named rule.
- Gap 5 (new, from camera_dtsi + EVA convergence): No **per-target confidence ledger artifact**. `TODO_confidence_status.md` (EVA) and `warnings.txt`/`node_changes.json` (camera_dtsi) both produce a small, human-skimmable "what's trustworthy vs. not" summary per generation run. Audio BU Skill's `onboarding_report.md` NEEDS_REVIEW section is close to this in spirit but is not framed as a per-field trust ledger.
- Gap 6 (existing plan, reconfirmed): No response-size/caching discipline for whatever IPCAT access *does* exist — moot today since there is no structured access, but relevant the moment any provider is built.

---

## 6. High-value IPCAT capabilities (candidates to adopt)

Ranked by (benchmark impact × cheapness × how directly it is evidenced by a working reference implementation):

1. **A markdown knowledge base per audio domain** (camera_dtsi pattern), e.g. `references/kb/lpass.md`, `adsp.md`, `soundwire.md`, `audio_clocks.md` — hand-seeded from already-onboarded targets (eliza, nord-iq10) the same way camera_dtsi seeded from 4 reference chipsets. **No new dependency, no auth risk, does not require the Phase-0 access-mode decision to be settled first.**
2. **Structured (not prose) MCP tool responses.** camera_dtsi proves this doesn't require abandoning MCP for a Python-library dependency — it requires the *tool implementation* to fetch/shape/cache/filter before returning to the LLM, exactly the way `get_addresses`/`get_freq_plan` do. This directly targets the actual observed failure (`missing_evidence` citing untabulated register/GPIO/power/SID data) without EVA's headless-auth risk profile.
3. **Cardinality/instance-count authority as a validator rule.** Cheap, mechanical, and camera_dtsi shows the exact shape: enumerate IPCAT block-name patterns for a domain, compare count against whatever QGenie/the nearest-target implies, flag mismatch.
4. **Anti-fallback rules stated as literal, checkable constraints** ("never use another target's clock rate/address as a substitute," "never interpolate missing levels") rather than only narrative principles — both EVA and camera_dtsi encode these; Audio BU Skill's schema/validator layer could check for them mechanically (e.g. reject a `citations` entry that points at a different target's evidence file).
5. **A confidence ledger artifact per onboarding run** — a small, skimmable "what's IPCAT-corroborated vs. reasoning-only vs. unresolved" summary, converging EVA's `TODO_confidence_status.md` and camera_dtsi's `warnings.txt` into something that augments (not replaces) the existing NEEDS_REVIEW section.
6. **Env-var-first credential ordering for any future IPCAT access**, regardless of which access mode (library vs. structured-MCP-tool) is chosen — both reference systems converge on the same pattern (env vars checked first for CI/headless, keyring/interactive only for local dev setup). This closes the existing plan's "High" auth risk with a proven pattern rather than an open question.
7. **The learn-loop as a longer-horizon idea** — higher effort (needs a maintainer skill + a place to persist/share the KB), but the only capability here that produces compounding returns across chipsets rather than a one-time build.

---

## 7. Recommended Phase-0 IPCAT spike (revised)

The existing plan's Phase 0 frames the central open question as *"structured `ipcat_client` library vs. staying on MCP."* Having now seen camera_dtsi, that framing is too narrow — camera_dtsi demonstrates a third, cheaper option that answers the same underlying question ("can we get typed rows instead of prose?") without taking on `ipcat_client` as an orchestrator-level dependency or its interactive-auth profile.

**Revised Phase-0 spike scope:**

1. Determine whether the *existing* audio IPCAT MCP tool(s) can be queried in a way that returns structured rows (block name/address/size, clock name/rate, IRQ name/number) rather than prose — i.e., is the tool itself capable of shaping data, or does it only expose a `search_content`-style free-text interface? This is answerable by inspection/testing of the current MCP tool schema, no new code.
2. If the current MCP tool is prose-only: evaluate the cost of adding one or two audio-shaped structured tools (mirroring `get_addresses`/`get_irqs`/`get_freq_plan`'s filter+cache pattern) vs. adopting `ipcat_client` directly in the orchestrator (EVA's path). camera_dtsi's tool-implementation-does-the-shaping approach avoids the headless-auth objection entirely if the MCP server can be run with env-var credentials (proven pattern in both reference repos).
3. Separately, and in parallel (no dependency on #1/#2): seed a minimal audio KB (`references/kb/lpass.md` etc.) from the two already-onboarded targets' resolved facts, as a documentation-only exercise — this is a spike deliverable in its own right and de-risks Gap 2 regardless of which access mode wins.
4. Output: a decision note (as the existing plan already specifies) — but now covering three options (library / structured-MCP-tool / KB-only-no-new-access) instead of two, with the KB-only option flagged as the lowest-risk, lowest-effort, partial-benefit choice that could ship before or independent of the other two.

This remains non-invasive, read-only investigation, outside the onboarding path, changing no behavior — consistent with the existing plan's constraint that only the Phase-0 spike may run before Benchmark A/B.

---

## 8. Recommended implementation roadmap (revised)

The existing plan's Phase 1→5 sequence (modules+IRQs skeleton → clocks → validator → SID → dependency graph) is still directionally sound, but camera_dtsi motivates re-ordering and one insertion:

1. **Phase 0 spike (revised, §7 above).** Unchanged priority — do first.
2. **NEW — Phase 0.5: seed the audio KB.** Documentation-only; can run in parallel with Phase 0's access-mode investigation, and delivers value (narrower QGenie mapping burden) even if the access-mode question stalls. Lowest risk in the entire roadmap.
3. **Phase 1 — structured evidence skeleton (modules + IRQs)**, as before, but now informed by whichever access mode Phase 0 selects (library, structured MCP tool, or KB-only-deferred).
4. **Phase 2 — clock evidence.** Unchanged: highest single-field benchmark impact.
5. **Phase 3 — post-analysis validator, expanded scope.** In addition to the existing plan's "cross-check QGenie claims vs. deterministic bundle," add the **cardinality-authority check** (§6.3) and an **anti-fallback citation check** (§6.4) — both cheap, mechanical, and directly evidenced by camera_dtsi's hard constraints. Also add the **confidence-ledger artifact** (§6.5) as a validator output, not a separate phase.
6. **Phase 4 — SID/IOMMU.** Unchanged: lowest confidence, do last, `[VERIFY]`-flagged by default.
7. **Phase 5 — dependency graph.** Unchanged.
8. **NEW — Phase 6 (post-Benchmark, longer horizon): learn-loop feasibility.** Only after Phases 1-3 have run against real targets and produced resolved-fact history, evaluate whether a maintainer skill that grows the Phase-0.5 KB from each new onboarded target (mirroring `learn-cam-dtsi`) is worth building. This is explicitly the highest-effort, compounding-return item and should not compete with Phases 1-5 for priority.

The existing plan's §8/§9 split (nothing but the spike before Benchmark A/B; real extraction after) still holds, with Phase 0.5 added to the pre-benchmark-safe list since it is documentation-only and touches no onboarding code path.

---

## 9. Risk assessment (revised)

| Risk | Severity (existing plan) | Severity (revised) | Why revised |
|---|---|---|---|
| IPCAT auth/access in headless runs | High | **Medium** | Both EVA and camera_dtsi independently converge on the same working pattern: env vars checked first, keyring/interactive only for local one-time setup. This is a proven, copyable *pattern* (not code) that resolves the access question for either library or MCP-tool implementations. Residual risk is now "does our environment support setting service-account env vars for onboarding runs," an ops question, not an open architecture question. |
| Adding a hardware dependency (`ipcat_client`) | Med | Med (unchanged) — but now optional. camera_dtsi shows a path that avoids this dependency entirely (structured MCP tool instead of library import), so this risk is avoidable, not just mitigable. |
| Over-trusting deterministic values | Med | Med (unchanged), reinforced — both EVA (`[VERIFY]` for SID) and camera_dtsi (`/* TODO: verify */`, `warnings.txt`) treat SID/IOMMU as the one domain neither system trusts; corroborates keeping Phase 4 last and `[VERIFY]`-flagged. |
| Scope creep toward DTSI/YAML generation | Med | Med (unchanged) — camera_dtsi is a generation skill, not an onboarding/analysis skill; its patterns transfer, its purpose does not. Reinforces the existing invariant that onboarding stays analysis-only. |
| Silent regression of the strict contract | High | High (unchanged) — no reference system changes this; it's an Audio BU Skill-internal invariant. |
| Building against unmeasured failures | Med | Med (unchanged). |
| CVP-specific / camera-specific mis-adaptation | Med | Med (unchanged) — applies equally to camera_dtsi: its topology enumeration patterns (`TITAN_A_RT_0_IFE_<N>` etc.) are camera-block-specific and must not be copied verbatim, only the *pattern* of "enumerate by name-pattern, use as cardinality authority." |
| **NEW — KB staleness/drift** | — | Med | A hand/LLM-maintained markdown KB (Phase 0.5/6) can silently go stale if a chipset family's IPCAT naming changes and nobody re-runs a learn step. camera_dtsi mitigates this with `WARN:` conflict-flagging on contradiction rather than silent overwrite — worth adopting verbatim as a policy if Phase 0.5/6 proceeds. |
| **NEW — MCP tool implementation debt** | — | Low-Med | If Phase 0 selects "structured MCP tool" over "library," someone owns writing/maintaining the fetch-shape-cache logic *inside* the tool (camera_dtsi's `cam_dtsi_tool.py` is 1216 lines) — not a trivial wrapper. Should be sized honestly in Phase 1, not assumed cheap just because it avoids a new orchestrator dependency. |

---

## 10. Estimated improvement areas

| Domain | Current state | Improvement if §6 capabilities adopted |
|---|---|---|
| **Power model** | rpmhpd LCX/LMX presence only, from git/source-tree parse; never auto-finalized (nord-iq10 blocked NEEDS_REVIEW) | Structured LPASS/ADSP module + GDSC evidence (existing plan) **plus** an audio KB entry documenting known power-domain naming conventions per chipset family (camera_dtsi-style) — gives the human reviewer a written rule to check nord-iq10's rpmhpd-vs-SCMI decision against, not just raw IPCAT facts |
| **Clocks** | QGenie reads prose HPG/MCP search, unreliable per Eliza's `missing_evidence` | Structured freq-plan extraction (existing plan, highest single-field impact) **plus** cardinality/anti-interpolation validator rules (new, from camera_dtsi's "never interpolate missing levels" constraint) |
| **Topology** | Reasoning-only; QGenie infers codec/amp/mic/speaker/bus presence from prose | Deterministic module-presence facts (existing plan) **plus** cardinality-authority validator (new): if IPCAT enumerates N instances of an audio macro block, cross-check against QGenie's topology count |
| **Dependencies (remoteproc/ADSP)** | Reasoning-only | Existing plan's Phase 5 dependency graph, unchanged priority, but now informed by a KB entry documenting known ADSP IRQ/power-domain naming per chipset family |
| **SID/IOMMU** | Entirely absent | Existing plan's Phase 4, unchanged — both reference systems agree this is the lowest-confidence domain; no new argument for raising its priority |
| **Confidence communication to reviewer** | NEEDS_REVIEW list only | New: per-run confidence ledger (§6.5), giving the human reviewer an EVA/camera_dtsi-style skimmable trust summary alongside NEEDS_REVIEW |

---

## 11. Challenge the current plan

### What surprised me

1. **The two reference systems sit at opposite philosophical poles — deterministic-script-generation (EVA) vs. zero-code pure-LLM-generation (camera_dtsi) — yet converge on the identical underlying discipline**: fetch IPCAT facts as typed/structured data *before* the LLM reasons over them, cache them, filter them to avoid overwhelming context, and never let the LLM silently guess a value it can't source. The existing plan drew its "evidence-first" conclusion from EVA alone; seeing camera_dtsi reach the same conclusion by a completely different implementation route is a stronger validation of that conclusion than either system alone provides — but it also means the existing plan's implicit framing of "adopt EVA's library-based determinism" as *the* way to get there is too narrow. The convergence is on *structured-before-reasoning*, not on *any particular access mechanism*.
2. **The flagged "High" headless-auth risk is less open than the existing plan treats it.** Both systems independently arrived at "env vars checked first, keyring/interactive only for setup" — this isn't a risk requiring a Phase-0 spike to *discover*, it's a pattern to *copy*. The existing plan's Phase 0 spends effort re-deriving something two independent prior-art systems already solved the same way.
3. **camera_dtsi's KB-as-markdown is a strikingly cheap idea that the existing plan's roadmap has no equivalent of anywhere in Phases 0-5.** It requires no new runtime dependency, no auth work, and can be hand-seeded today from the two targets already onboarded (eliza, nord-iq10) — yet it directly attacks the same "QGenie has to rediscover mapping rules from scratch every time" problem that motivates the entire evidence-layer effort.
4. **The hard "STOP and ask, never guess" constraints in camera_dtsi's `SKILL.md` are more forceful and more specific than Audio BU Skill's current strict-no-fallback culture** — e.g. the exact question text to show the user when `reg_format` is missing, and the explicit "DO NOT try kera, niobe, pineapple" anti-pattern (clearly a codified lesson from a real past mistake). Audio BU Skill has the *principle* (no silent fallback) but not this level of *operationalized specificity* at decision points beyond power_model.
5. **Neither reference system actually closes its own "ground truth corpus" loop yet.** camera_dtsi's `OVERVIEW.md` claims session logs serve as "a ground truth database" for future generations, but nothing in the reviewed code reads those logs back — it's an aspiration, not a working feature. This tempered my initial read of it as a bigger win than it currently is in practice; it's a good *idea* to borrow, not a proven mechanism to copy.

### What I would change

1. **Reframe Phase 0's central question.** Not "library vs. MCP" but "does our IPCAT access return typed rows or prose, and if prose, is it cheaper to fix the tool or add a KB layer that reduces reliance on the tool being fixed." camera_dtsi proves the MCP path is not inherently the prose-returning path — that's an implementation choice, not an architectural constraint of MCP itself.
2. **Insert Phase 0.5 (audio KB) ahead of Phase 1**, not after it, and don't gate it on Phase 0's outcome. It is the single cheapest, lowest-risk, dependency-free item in this entire assessment, and it starts paying down Gap 2 immediately.
3. **Downgrade the headless-auth risk from High to Medium** in the risk register (§9) — the *pattern* is proven; what remains is an operational question (can we provision a service-account env var for onboarding CI runs), not an architectural unknown requiring a spike to resolve.
4. **Add explicit, mechanically-checkable anti-fallback rules to the Phase 3 validator scope**, not just "cross-check QGenie's claims" in the abstract — specifically the cardinality-authority check and a check that no cited evidence file belongs to a different target than the one being onboarded (guards against the exact "another chipset's addresses as fallback" failure mode both reference systems explicitly forbid).
5. **Add a confidence-ledger artifact as a Phase 3 deliverable**, converging EVA's `TODO_confidence_status.md` and camera_dtsi's `warnings.txt`/`node_changes.json` into a single small per-run summary — cheap relative to the validator logic it rides alongside, and directly improves what the human reviewer sees beyond the existing NEEDS_REVIEW list.

### Missed Opportunities

1. **The learn-loop.** Neither EVA nor the existing plan considers *growing* domain knowledge from successfully-onboarded targets over time. camera_dtsi's `learn-cam-dtsi` maintainer skill is a working, if unclosed-loop, example of turning each new (chipset, reference) analysis into durable shared knowledge instead of a one-off. This is the highest-ceiling idea in this assessment and the one most clearly absent from the existing roadmap end-to-end (not even mentioned as a "later" phase). Flagged here as Phase 6 (§8) rather than left out entirely.
2. **Per-run confidence ledgers as a first-class artifact**, not just an internal validator signal. Both reference systems produce one; Audio BU Skill produces NEEDS_REVIEW prose but not a structured, skimmable trust-per-field summary.
3. **Codifying anti-fallback rules as automated checks**, not just prose principles in a plan document. The existing plan states "never guess" as a design invariant; camera_dtsi shows what it looks like as an *enforceable* rule (STOP-and-ask, `/* TODO: verify */` markers with a defined trigger list, `warnings.txt` with a fixed format `WARNING: <node> <field> — <reason> — VERIFY MANUALLY`). Worth adapting the *format discipline*, not just the sentiment.
4. **Cardinality authority as a named, general rule** — "the deterministic evidence source outranks the structural template for counting instances" — is a small idea with outsized defect-catching value (it would catch, mechanically, a nearest-target case that under- or over-counts audio macro blocks relative to what IPCAT actually enumerates for the real target). Not present in the existing plan at all; present in camera_dtsi as a load-bearing rule.
5. **Response-size discipline (filter params + caching) as infrastructure hygiene**, independent of which access mode wins Phase 0 — this is a "do it either way" item the existing plan doesn't call out because it wasn't visible from EVA (which controls its own fetch scope in Python and doesn't face an LLM-context-size constraint the way an MCP tool call does).

---

## Appendix — Evidence sources for this review

- Audio BU Skill: `docs/IPCAT_EVIDENCE_LAYER_PLAN.md` (baseline plan under challenge).
- EVA_QLI_DT_Generator: `generate_cvp_dtsi.py` (grep-verified `[VERIFY]`/`[DEFAULT]`/`[INFO]`/`verify_output` usage), `TODO_confidence_status.md` (read in full this session).
- camera_dtsi: `README.md`, `OVERVIEW.md`, `SKILL.md`, `learn/SKILL.md`, `references/kb/00_index.md`, `references/kb/cpas.md`, `mcp/camera_ipcat_mcp/server.py`, `mcp/camera_ipcat_mcp/auth.py`, `mcp/camera_ipcat_mcp/credentials.py`, `mcp/camera_ipcat_mcp/tools/{chip,irqs,addresses,freq_plan,clocks,sids}.py`, `mcp/scripts/cam_dtsi_tool.py` (auth/setup_auth section, grep-verified function inventory) — all read this session from a fresh clone at a job-scoped temp directory, not committed to this repository.
