# Next Phase Recommendation — Audio BU Skill

**Status:** Architecture and roadmap review only. No code, DTS, YAML, or patches produced. No changes to Audio BU Skill. No Phase-2 work started.
**Question posed:** Do NOT assume `IPCAT Evidence Layer → Phase-2 Generation` is the correct order. Determine the highest-value path.
**Inputs reviewed:** `docs/IPCAT_EVIDENCE_LAYER_PLAN.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md`, EVA_QLI_DT_Generator, camera_dtsi, and the *actual* eliza / nord-iq10 onboarding reports (`targets/*/onboarding_report.md`, read this session).

> This report is grounded primarily in the **real onboarding outputs**, not just the two reference repos. The onboarding reports change the answer materially — see Finding #1.

---

## 1. Executive summary

The existing plan and the capability assessment both concluded "Audio BU Skill needs a deterministic IPCAT evidence layer, then Phase-2 generation." Reading the actual eliza and nord-iq10 onboarding reports refines that in one decisive way:

**The current IPCAT access is not just *prose-shaped* — it is pointed at the *wrong IPCAT surface entirely.*** Both onboarding runs queried `data_source=ipcat, project=HPG_DOCUMENTS` — a document store **organized by IP-block hardware version, not by target SoC**. nord-iq10's report states it plainly: *"IPCAT's HPG_DOCUMENTS project is organized by IP-block hardware version, not by target SoC, and structurally cannot answer SA8797P-specific register-base or power-domain questions."* It returned only generic QDSP6 guides for *other* SoC families. Eliza fared slightly better (one LPASS HPG names Eliza) but still got generic boilerplate for the register/master-count specifics that actually mattered.

Meanwhile, **both EVA and camera_dtsi do not use HPG_DOCUMENTS at all.** They hit the IPCAT **SWI/IRQ/clock catalog** via `swi.get_modules()` / `irqs.get_interrupts()` / `clocks.get_freqplan_release()` (EVA) or the equivalent `get_addresses`/`get_irqs`/`get_freq_plan` MCP tools backed by the same catalog (camera_dtsi). That surface is **keyed by chip** and is exactly where per-target register bases, IRQ numbers, clock freq plans, and instance counts live.

The concrete blockers in both onboarding runs are precisely SWI-catalog facts, not HPG-prose facts:

- **nord-iq10:** ADSP PAS register base is `0x30000000` (hand-copied from lemans) vs `0x07000000` (Nord boot logs) — **unresolved**, no evidence source reconciled it. This is a `swi.get_modules()`/`get_addresses` fact for SA8797P.
- **eliza:** SoundWire master_count is *"ambiguous: could be 1 or 2 physical master instances; not resolved,"* and the controller register base is *"unconfirmed."* This is a SWI-catalog *instance-count + base-address* fact — exactly camera_dtsi's "IPCAT is the authority for how many hardware instances exist" pattern.

So the highest-value IPCAT work is **not** "structure the prose we already get" — it is **"query the catalog surface EVA and camera already proved returns per-target register/instance facts."** That single change plausibly resolves the top blocker in *both* real targets.

But — and this is why the order is *not* simply "IPCAT layer, then generate" — several capabilities that require **no IPCAT access, no new dependency, and no auth work** would improve reviewer confidence and evidence quality *now*, and are prerequisites to trustworthy generation regardless of which IPCAT surface is used:

- An **Audio Knowledge Base** seeded from the facts eliza and nord *already resolved* (AudioReach port conventions, driver families, rpmhpd-vs-SCMI naming per SoC family).
- **Cardinality authority validation** (IPCAT/enumerated instance count vs. topology count) — directly targets eliza's unresolved SoundWire master_count.
- A **Confidence Ledger** per run — makes the reviewer's job tractable and is a hard prerequisite for ever trusting a generated patch.

**Bottom line:** the recommended path is **Option D (a rescoped ordering)**, whose *immediate next step* is the Audio Knowledge Base + validator hygiene (cheapest, compounding, dependency-free), whose *highest-ceiling item before any generation* is a **rescoped IPCAT Evidence Layer pointed at the SWI catalog surface** (not HPG_DOCUMENTS), and where **Phase-2 generation is explicitly last** — because generating DTS/patches on top of unresolved register bases and instance counts would mass-produce confidently-wrong artifacts (nord patch 0003's `0x30000000` is the canonical example of exactly that failure, done by hand).

---

## 2. Top 10 findings

1. **Wrong IPCAT surface (the decisive finding).** Both runs queried `HPG_DOCUMENTS` (organized by IP version); EVA and camera query the SWI/IRQ/clock catalog (organized by chip). The blockers are catalog facts. Fixing the *surface* likely matters more than fixing the *shape* (prose→structured).
2. **Both real blockers are register/instance facts, not reasoning gaps.** nord's ADSP base and eliza's SWR master_count are deterministic hardware facts QGenie *cannot* infer from prose and *should not* be asked to. This is a data-access problem, not a smarter-prompt problem.
3. **Generation on today's evidence would be actively harmful.** nord patch 0003 already demonstrates the failure: a register base copied from the nearest target (lemans, `0x30000000`) that is wrong for the real silicon (`0x07000000`). A generation framework would reproduce this class of error at scale and with false confidence. Generation must come *after* deterministic register/instance evidence exists.
4. **The cheapest high-value wins need no IPCAT access at all.** An Audio KB seeded from eliza+nord's resolved facts, a cardinality validator, and a confidence ledger are all doc/validator work — no dependency, no auth risk, shippable in days, and they improve reviewer confidence immediately.
5. **eliza's SoundWire master_count is a textbook cardinality-authority case.** *"could be 1 or 2 physical master instances; not resolved"* — precisely the ambiguity camera_dtsi resolves with "enumerate IPCAT instances; IPCAT is the count authority." Cheap to add, directly on a real blocker.
6. **The power-model blocker is already mostly solved by source-tree evidence, and IPCAT won't finish it.** nord's report shows `power_model_inspection` correctly established rpmhpd excludes LCX/LMX and SCMI is used SoC-wide; the residual gap (exact `<&scmiN_pd idx>` for the ADSP path) is a DT-integration fact absent from *every* source including IPCAT. This bounds how much any IPCAT layer can help power-model — the win there is corroboration + a KB rule, not a magic table.
7. **AudioReach port mapping is a pure knowledge gap, not a data gap.** nord's I2S8→logical-port ambiguity (`q6dsp-lpass-ports.h` defines only PRIMARY..QUINARY) is exactly what a `references/kb/audioreach.md` entry would capture — no IPCAT call resolves it. This is the clearest argument that the KB and the IPCAT layer are *complementary*, not substitutes.
8. **The headless-auth risk is lower than the existing plan rates it.** EVA (`~/.ipcat_token` → env vars → getpass) and camera_dtsi (env-vars-first → keyring → mode-600 file, getpass only at install) independently converge on the same proven env-var-first pattern. This is a pattern to copy, not an open unknown — downgrade High→Medium.
9. **The learn loop is the only compounding capability, but it has no substrate yet.** camera_dtsi's `learn-cam-dtsi` grows a shared KB from each new (chipset, reference) pair. It is the highest long-term ceiling — but it requires a KB to grow (Finding #4's item) and resolved-target history to grow it from. Sequence it after the KB exists, not now.
10. **Confidence honesty is a shipped feature in both references and a gap here.** EVA's `TODO_confidence_status.md` and camera_dtsi's `warnings.txt`/`node_changes.json` both give reviewers a skimmable trust-per-field summary. Audio BU Skill's NEEDS_REVIEW prose is close but unstructured; a per-run ledger is a small, high-leverage reviewer-confidence win and a hard prerequisite for trusting generated output.

---

## 3. Recommended roadmap

Phases are future work; nothing here is authorized to start by this document. Ordered by the reasoning in §4.

- **Phase 0 — Spike (rescoped): confirm the IPCAT catalog surface.** Verify whether the SWI/IRQ/clock catalog (the EVA/camera surface) resolves SA8797P (Nord) and Eliza's chip, and returns the ADSP block base and SWR-master instances that HPG_DOCUMENTS could not. Read-only investigation, no product code. **This is the single most important experiment**; it validates or kills the entire IPCAT-layer premise on the two real blockers. Also settle access mode (library vs. structured MCP tool) and the env-var-first auth pattern here.
- **Phase 0.5 — Seed the Audio Knowledge Base (parallel, dependency-free).** `references/kb/{lpass,adsp,audioreach,soundwire,audio_clocks}.md`, hand-seeded from eliza + nord's *already-resolved* facts and their `qgenie_analysis.json`. Documentation-only; touches no onboarding code path; safe before Benchmark A/B. Captures the AudioReach-port and rpmhpd-vs-SCMI-naming knowledge that no IPCAT call returns.
- **Phase 1 — Cardinality authority + Confidence ledger (cheap validators).** A validator rule ("enumerated instance count outranks nearest-target/topology count; flag mismatch") + a per-run confidence-ledger artifact rendered into `onboarding_report.md`. No IPCAT access required to build the machinery; it consumes whatever evidence exists. Directly targets eliza's SWR master_count.
- **Phase 2 — IPCAT Evidence Layer on the SWI catalog surface.** Deterministic per-chip extraction of audio HW module bases (LPASS/ADSP/WSA/VA/TX/RX/SWR-master) + IRQs + audio clock freq plan into a structured, cited bundle feeding the task spec. Filter+cache discipline (camera_dtsi pattern). Strict: unavailable ⇒ typed error/flagged gap, never a fabricated value. **This is the highest benchmark-impact item and the true prerequisite for generation.** Gated on Phase 0's surface confirmation.
- **Phase 3 — Post-analysis validator (EVA `verify_output` analogue).** Cross-check QGenie's claims against the Phase-2 bundle; downgrade confidence / raise needs_review on conflict; feed the Phase-1 ledger. Add the anti-fallback citation check (reject a citation pointing at a *different* target's evidence — nord's 0x30000000-from-lemans failure mode).
- **Phase 4 — SID/IOMMU (audio-shaped, `[VERIFY]`-by-default).** Both references rate this lowest-confidence; do it late.
- **Phase 5 — Dependency graph.** Modules + IRQs + power domains → anchor remoteproc/topology.
- **Phase 6 — Learn loop (longest horizon).** A maintainer skill that grows the Phase-0.5 KB from each newly-onboarded target, camera_dtsi-style, with `WARN:` conflict-flagging. Only worthwhile once Phases 0.5–3 have produced KB + resolved-fact history.
- **Phase 7 — Phase-2 Generation Framework (LAST).** DTS/patch generation, riding on top of deterministic register/instance evidence (Phase 2), cardinality authority (Phase 1), a validator (Phase 3), and a confidence ledger (Phase 1). Generation before these exist would mass-produce nord-0003-class errors.

---

## 4. Priority ranking

Ranked by (real-blocker impact × cheapness ÷ risk), with the reasoning made explicit:

| Rank | Capability | Why here |
|---|---|---|
| 1 | **Phase 0 spike (catalog surface)** | Near-zero risk/cost; validates the single most important hypothesis (does the SWI catalog answer the two real blockers?). Everything downstream depends on the answer. |
| 2 | **Audio KB (C) — Phase 0.5** | Highest production-quality-per-engineering-week. Dependency-free, auth-free, seedable today from resolved facts, and the *only* thing that addresses the AudioReach-port and driver-family knowledge gaps IPCAT structurally cannot. Also the learn-loop seed. |
| 3 | **Cardinality authority (C) + Confidence ledger (D) — Phase 1** | Cheap validator/report work; directly on eliza's SWR master_count; prerequisite for trusting any future generated output. |
| 4 | **IPCAT Evidence Layer, SWI surface (A/B) — Phase 2** | Highest benchmark-quality impact and the true generation prerequisite — but higher effort (access mode, auth ops, possibly a new dependency or a non-trivial MCP tool). Gated on Phase 0. |
| 5 | **Post-analysis validator — Phase 3** | High trust/quality per unit effort; protects against reasoning-only failure modes and the cross-target-citation error class. |
| 6 | **Dependency graph — Phase 5** | Medium impact; depends on Phase 2. |
| 7 | **SID/IOMMU — Phase 4** | Real gap, but both references rate it lowest-confidence; late + `[VERIFY]`. |
| 8 | **Learn loop (E) — Phase 6** | Best long-term compounding returns, but no substrate until KB + history exist. |
| 9 | **Phase-2 Generation (F) — Phase 7** | Explicitly last. Highest downside risk if done early (confidently-wrong artifacts at scale). |

---

## 5. Expected impact

| Capability | Onboarding quality | Reviewer confidence | Production readiness | Evidence quality | Future DTS-gen quality |
|---|---|---|---|---|---|
| Audio KB (C) | Med (narrows QGenie's rediscovery; fixes AudioReach-port class) | Med | Med | Low-direct (knowledge, not per-target facts) | **High** (encodes the mapping rules a generator must follow) |
| Cardinality authority (C) | Med (catches count mismatches) | High (mechanical, explainable) | Med | Med | **High** (wrong instance count = wrong DTS) |
| Confidence ledger (D) | Low-direct | **High** (skimmable trust-per-field) | High (gates sign-off) | Med | High (reviewer can trust a patch only with this) |
| IPCAT Evidence Layer, SWI surface (A) | **High** (resolves nord ADSP base, eliza SWR base/count) | High | High | **High** (deterministic per-target register/clock/instance facts) | **High** (correct reg bases are non-negotiable for DTS) |
| Learn loop (E) | Med (compounds over targets) | Med | Med | Med (compounds) | High (compounds) |
| Phase-2 Generation (F) | — (consumes the above) | **Negative if premature** | **Negative if premature** | — | — |

---

## 6. High-value, low-effort opportunities

1. **Seed the Audio KB from facts already in hand.** eliza + nord's resolved facts (AudioReach ports, rpmhpd/SCMI naming, WCD/WSA driver families, PCM1681/ADAU1979 I2C pattern) are sitting in the onboarding artifacts right now. Transcribing them into `references/kb/*.md` is near-free and immediately reduces the per-run rediscovery burden. **Best ROI in the entire assessment.**
2. **Cardinality-authority validator rule.** A small, mechanical check ("if enumerated audio-block instance count ≠ topology count, flag") directly on eliza's real, unresolved SWR master_count ambiguity.
3. **Confidence-ledger artifact.** A report-rendering change converging EVA's `TODO_confidence_status.md` + camera's `warnings.txt` into a per-run trust-per-field table alongside the existing NEEDS_REVIEW.
4. **Anti-fallback citation check.** Reject/flag any citation whose evidence path belongs to a *different* target than the one being onboarded — mechanically catches the nord-0003 `0x30000000`-from-lemans failure class.
5. **Env-var-first auth pattern (knowledge, when Phase 2 comes).** Copy the proven pattern; do not re-spike it.

Items 1–4 require **no IPCAT access, no new dependency, and no auth work.** They are shippable before Benchmark A/B without perturbing the measured onboarding path *if* rendered as additive report/validator output — care is required so they don't change the A/B baseline (see §9).

---

## 7. Biggest missed opportunities

1. **Querying the wrong IPCAT surface has been the silent ceiling on IPCAT coverage all along.** The existing plan framed the problem as prose-vs-structured; the onboarding evidence shows it is *also* HPG-docs-vs-SWI-catalog. This is the biggest missed insight and it re-prioritizes Phase 0 from "decide library vs. MCP" to "confirm the catalog surface answers the real blockers."
2. **The learn loop** — no accumulation of hard-won per-target knowledge across eliza → nord → future targets. Absent from the existing roadmap end-to-end.
3. **Cardinality authority as a named rule** — a small, load-bearing idea from camera_dtsi, directly on a real eliza blocker, missing from the existing plan.
4. **Confidence ledger as a first-class artifact** — both references ship one; onboarding produces prose instead.
5. **Automated anti-fallback checks** — the existing plan states "never guess" as a principle; neither the plan nor the code enforces "never cite another target's evidence as this target's fact," which is exactly the nord-0003 failure.

---

## 8. What should be implemented next

**Immediately (dependency-free, highest ROI):**
- The **Audio Knowledge Base** (Phase 0.5), seeded from eliza + nord resolved facts.
- The **Phase 0 spike** on the IPCAT SWI catalog surface (read-only investigation) — run in parallel; it is the go/no-go for the whole IPCAT layer.

These two are the concrete "next." The KB delivers value even if the spike comes back negative; the spike de-risks the single largest downstream investment.

**Immediately after (cheap validators, still no IPCAT dependency):**
- **Cardinality authority** validation and the **Confidence ledger** (Phase 1).

---

## 9. What should explicitly wait until later

- **Phase-2 Generation Framework (F).** Wait until deterministic register/instance evidence (Phase 2), cardinality authority (Phase 1), a validator (Phase 3), and a confidence ledger (Phase 1) exist. Generating now reproduces nord-0003-class errors at scale.
- **SID/IOMMU (Phase 4).** Both references rate it lowest-confidence; do last, `[VERIFY]`-flagged.
- **Learn loop (Phase 6).** Needs a KB + resolved-fact history first.
- **The full IPCAT Evidence Layer build (Phase 2)** — waits on the Phase 0 surface confirmation; do not build extractors against `HPG_DOCUMENTS`.
- **Anything that perturbs the onboarding output path before Benchmark A/B.** The existing plan's §8/§9 discipline holds: only read-only spikes and *additive, non-behavior-changing* documentation/report output are safe pre-benchmark. If the cardinality/ledger work would alter what onboarding *decides* (not just what it *displays*), it waits until after the A/B baseline is captured.

---

## 10. Final recommendation

**Option D — a rescoped path, not a single-capability answer.**

Neither "Phase-2 first" (Option A), "IPCAT layer first" (Option B), nor "KB first" (Option C) is right as a monolith:

- **Not Option A (Phase-2 first).** Decisively rejected. Generation on today's evidence would mass-produce confidently-wrong artifacts. nord patch 0003's wrong ADSP base (`0x30000000` from lemans vs `0x07000000` real) is a hand-made preview of exactly what a premature generator would do at scale. Generation must be *last*.
- **Not Option B (IPCAT layer first) as literally scoped in the existing plan.** The plan's IPCAT layer is the highest-*benchmark*-impact item, but (a) it must first be **rescoped to the SWI catalog surface** — building it against `HPG_DOCUMENTS` would inherit the very ceiling that blocked both real targets; and (b) it is the highest-effort/-risk item, so it should not be the *first* thing built while cheaper wins sit on the table.
- **Not Option C (KB first) alone.** The KB is the best ROI and the right *immediate* step, but it structurally cannot resolve the register-base and instance-count blockers that are the top NEEDS_REVIEW items in both targets — those need the IPCAT catalog. KB and IPCAT layer are complementary, not competing.

**The recommended path (Option D):**

1. **Now:** Audio KB (Phase 0.5) + Phase 0 spike on the **IPCAT SWI catalog surface** (in parallel).
2. **Next:** Cardinality authority + Confidence ledger (Phase 1) — cheap, on real blockers, generation prerequisites.
3. **Then (the big one, before any generation):** rescoped IPCAT Evidence Layer on the SWI surface (Phase 2) + post-analysis validator (Phase 3).
4. **Later:** dependency graph, SID/IOMMU, learn loop.
5. **Last:** Phase-2 Generation Framework (Phase 7).

**Justification in one line:** the two real targets are blocked on *per-target register/instance facts that live in the IPCAT SWI catalog and nowhere in the HPG prose we've been querying* — so the highest-value technical move is switching IPCAT surfaces (validated cheaply by a Phase 0 spike), while the highest-value *this-week* move is the dependency-free KB + validators that raise reviewer confidence and are hard prerequisites for ever trusting generated output — and generation itself must wait until those facts are deterministic, because generating on today's evidence is not neutral, it is actively harmful.

**Ideas to adopt from EVA:** evidence-first pattern; per-field provenance; `[VERIFY]`/`[DEFAULT]`/`[INFO]` flagging (mapped to our confidence/needs_review); the **SWI/IRQ/clock catalog access surface** (the decisive one); APPS-filter + −32 GIC offset as knowledge; post-generation self-verification; the `TODO_confidence_status.md` ledger idea.

**Ideas to adopt from camera_dtsi:** the **markdown KB per IP block** + the **learn skill** that grows it; **IPCAT-as-instance-count-authority**; structured-MCP-tool-does-the-shaping (avoids a hard `ipcat_client` dependency); `filter=[...]` + per-target caching for response-size discipline; **hard STOP-and-ask** anti-guessing constraints as *operationalized* rules with fixed formats; env-var-first credential ordering.

**Ideas to NOT adopt:** EVA's MVS0C/MVS0/EVA_CC topology detection and 4-slot SID layout (CVP-specific); EVA's CVP OPP-pairing and HPG §3.3/3.4 parser; camera_dtsi's `TITAN_A_RT_*` block-name enumeration verbatim (camera-specific — adopt the *pattern*, not the names); and, for onboarding, **any DTSI/YAML structure-preserving generation** from either repo — onboarding stays analysis-only; generation is the separate, last Phase.

---

## Appendix — Evidence sources

- `targets/eliza/onboarding_report.md`, `targets/nord-iq10/onboarding_report.md` (read this session — the primary grounding for Findings #1–#7).
- `docs/IPCAT_EVIDENCE_LAYER_PLAN.md`, `docs/IPCAT_CAPABILITY_ASSESSMENT.md`.
- EVA_QLI_DT_Generator: `generate_cvp_dtsi.py`, `TODO_confidence_status.md`, `README.md`.
- camera_dtsi: `SKILL.md`, `learn/SKILL.md`, `references/kb/{00_index,cpas}.md`, `mcp/camera_ipcat_mcp/{server,auth,credentials}.py`, `mcp/camera_ipcat_mcp/tools/*.py`, `mcp/scripts/cam_dtsi_tool.py`, `OVERVIEW.md`.
