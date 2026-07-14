# k-genesis Prior-Art Analysis

**Type:** Investigation-only prior-art spike. **No implementation, no code changes, no staging, no commits, no pushes. No Phase-0 artifact modified. No qgenie/`.mcp.json`/`auth.json` touched.**
**Question:** Does the `k-genesis` repository (`git@github.qualcomm.com:LinuxKernel/k-genesis.git`) contain patterns — IPCat-driven DT/kernel bring-up generation, Claude plugin packaging, worker contracts — that Audio BU Skill can leverage, and does it change the accepted Phase-0 conclusion?
**Method:** Fresh shallow clone read as source-of-truth; three parallel source-grounded readers (structure/Claude, IPCat/DT, worker model); every claim cites `file:line` in the clone. The presentation deck was **not** used — all evidence is repository source.

> **Bottom line up front.** k-genesis is a **mature, directly-comparable prior art**: a Claude Code plugin that does exactly the analysis→generate→validate→commit bring-up loop Audio BU Skill is architecting, for *devicetree/driver* bring-up. Its single most decision-relevant contribution is empirical: **it reaches IPCat through a remote HTTP MCP server (`ipcat-mcp-server`, SSE) authenticated by a static token in `~/.claude/.mcp.json` — never `auth.json`, no hourly OAuth refresh — and receives structured JSON.** That is a *working, boundary-safe* instance of the access class Phase-0 left as an open operator decision. It **does not invalidate** the Phase-0 conclusion (short-term B / long-term C survive), but it **de-risks and makes concrete** a variant of Option A that Phase-0 rated "PARTIAL-GO, inherits the `auth.json`/refresh problem." Overall leverage: **MEDIUM–HIGH as pattern reference; LOW as directly-reusable code** (its logic is Qualcomm-DT-specific markdown prompt-contracts, and its transport disables TLS verification). Recommendation: **study further + adopt selected patterns later; do not reopen Phase-0; add a one-paragraph addendum noting the observed access mechanism as concrete evidence for the A-Option-C fallback.**

---

## 1. Executive Summary

k-genesis (`.claude-plugin/plugin.json:1-13`) is "Qualcomm SoC kernel bringup: generate devicetree, drivers, and build infrastructure for any Qualcomm kernel tree." It is 51 tracked files — 34 markdown, 6 JSON, 5 Python, 4 XML — i.e. a **prompt-contract / Claude-plugin repo**, not a code library. It packages, from one tree, both a **Claude Code plugin** (`/k-genesis:bringup`) and a **qgenie skill** (`bringup …`), sharing all logic and differing only in config (`docs/INSTALL.md:48-138`).

Five findings matter for Audio BU Skill:

1. **IPCat access is a remote HTTP MCP server with a static-token credential model** (`scripts/mcp_client.py:30-81`) — structurally close to Phase-0's Option A, but using a `.mcp.json` header token rather than the qgenie MCP Hub OAuth bearer in `auth.json`. This sidesteps *both* Phase-0 blockers (environment isolation + `auth.json`/hourly refresh) **and** returns structured JSON (`scripts/mcp_client.py:112-116`). It **also** uses the `ipcat_client` library directly for memory maps (`scripts/gen_reserved_memory.py:315-351`) — i.e. it is an A′+B hybrid.
2. **It is a full generation lane, not analysis-only** — it generates DTSI/DTS/DTSO, driver `.c`, bindings YAML, headers, Kconfig, build registration, and makes real git commits with checkpatch + dtbs_check gates (`drivers/TEMPLATE.md §4–§6`, `agents/verify_target.md:102-387`). This is the shape Audio BU Skill's *Phase-2 generation lane* (currently inert scaffolding) is heading toward — so its patterns are more relevant to Audio Phase-2 than to Phase-0/1.
3. **Determinism is enforced by an explicit rulebook** (`references/golden_rules.md`, 7 rules) + MCP-as-sole-authority-for-chip-values + "UNVERIFIED copies are bugs, not placeholders" — the same anti-fallback discipline Audio BU Skill adopted in WP-A/WP-C, here operationalized as load-bearing rules.
4. **A fresh-context sub-agent-per-unit model** (`skills/bringup/SKILL.md:66-72`) with a **declarative per-driver spec consumed by one generic executor** (`agents/add_driver.md:44-47`) — a strong packaging/isolation pattern.
5. **No confidence-ledger / per-value provenance mechanism** — the one Audio BU Skill capability (WP-B) that k-genesis *lacks*. Audio BU Skill is ahead of k-genesis here.

**Does it change Phase-0? No.** It confirms the access taxonomy, provides a concrete boundary-safe reference for the A-Option-C fallback, and strengthens (does not unseat) long-term C. It introduces no fourth *architecture*; the `.mcp.json`-token transport is best classified as a concrete instantiation of Option A's "dedicated read-only credential" sub-variant.

---

## 2. Source Access / Provenance

- **Clone:** `git clone --depth=1 git@github.qualcomm.com:LinuxKernel/k-genesis.git prior_art/k-genesis` — **succeeded** (SSH auth confirmed: "Hi nandam! You've successfully authenticated"). No local pre-existing copy existed.
- **Provenance:** `origin git@github.qualcomm.com:LinuxKernel/k-genesis.git`; HEAD `4f6951b74abca723608c9ad8c8ac8e21755cd820` ("Merge pull request #10 from wasimn/unified-bringup"). Shallow depth-1.
- **Corpus:** 51 tracked files (34 `.md`, 6 `.json`, 5 `.py`, 4 `.xml`, 1 symlink `.claude/commands`).
- **Evidence discipline:** every claim below cites a file:line in `prior_art/k-genesis/`. The presentation deck was **not** consulted. Items not provable from source are marked **UNVERIFIED**. The clone lives under `prior_art/` (already git-ignored per `052af5c`); **no k-genesis file was copied into `audio_bu_skill/`**.

---

## 3. Repository Structure

| Dir | Purpose (source) | Runtime-critical | Reusable as *pattern* | k-genesis-specific (don't reuse verbatim) |
|---|---|---|---|---|
| `adapters/` | "ONLY entity that resolves filesystem paths"; emits `KERNEL_REPO`/`DT_REPO` (`docs/DESIGN.md:85-89`). kp/android/qclinux. | Yes | **Yes** — isolating path resolution from logic | Kernel-tree layouts are Qualcomm-specific |
| `agents/` | Fresh-context sub-agent executors: `init_target`, `add_driver`, `verify_target`, `eval_driver` (`agents/*.md:1-36` frontmatter) | Yes | **Yes** — phased scaffold→per-unit→verify | DT/driver generation content |
| `commands/` | Slash-command dispatchers `bringup.md`, `eval_driver.md` — thin, Read the SKILL and execute (`commands/bringup.md:44-46`) | Yes | **Yes** — "command = frontmatter + Read SKILL.md" | Content |
| `configs/` | Per-chip `<soc>-target.xml` + `reserved_memory_config.json`; the one hand-authored input (`configs/example-target.xml:7-8`) | Yes (input) | Partial — user-authored spec drives generation | XML schema is CPU/IP-enable specific |
| `docs/` | `INSTALL.md`, `DESIGN.md` | No | Yes — dual-runtime install doc | Content |
| `drivers/` | Declarative per-driver specs + `TEMPLATE.md` (`docs/DESIGN.md:97-102`) | Yes | **Yes** — *the* central pattern: data-driven specs run by one generic executor | Qualcomm DT drivers |
| `orchestrators/` | Per-`workspace_tree` dispatch (kp/android/qclinux) (`docs/DESIGN.md:82`) | Yes | Yes — per-mode orchestrator selection | Content |
| `references/` | `golden_rules.md`, `mcp_lookup_rules.md`, `external_skill_interface.md` | Yes (every agent reads golden_rules) | **Yes** — golden rules + external-skill contract broadly reusable | `mcp_lookup_rules.md` content is IPCat/Qualcomm-specific |
| `scripts/` | `gen_cpus.py`, `gen_reserved_memory.py`, `get_root_ip_name.py`, `mcp_client.py`, `undo_run.py` | Yes | Partial — `undo_run.py` (phase-granular undo) + venv-run convention | Content |
| `stages/` | `S0/S1/S2.json`: `ip_supported[]`, `drivers_used[]`, `INCLUDE:Sx` (`docs/DESIGN.md:104-108`) | Yes | **Yes** — JSON stage/scope files with include-expansion | Driver names |
| `.claude/` | `settings.json` (permissions + skills map + `KGENESIS_VENV`) + `commands` symlink (`.gitignore:11-14`) | Advisory | Yes — permission allow-list + env template | ~90 `mcp__ipcat-mcp-server__*` entries are IPCat-specific |
| `.claude-plugin/` | `plugin.json` manifest (`plugin.json:1-13`) | Yes (plugin mode) | **Yes** — standard manifest template | Metadata values only |

**Notable structural trick:** `.claude/commands` is a **symlink** to top-level `commands/` (git mode `120000`; `.gitignore:12-14` force-includes it). This is how one set of command files serves both plugin-install mode and repo-root "dev mode."

---

## 4. Claude Integration

**How it integrates:** packaged as a Claude Code **plugin** *and* a **qgenie skill** from one repo, keyed on `${CLAUDE_PLUGIN_ROOT}` with a git-root/file-relative fallback for dev/qgenie mode (`skills/bringup/SKILL.md:17-34`). Install: `claude plugin install k-genesis --path …` (`docs/INSTALL.md:52-55`).

**Uses standard Claude Code plugin conventions** (with one non-standard convenience):
- `.claude-plugin/plugin.json` — standard manifest: `name`, `description`, `version`, `author{name,email}`, `homepage`, `repository`, `license`, `keywords` (`plugin.json:1-13`). Relies on directory-convention discovery (`commands/`, `agents/`, `skills/`).
- `.claude/settings.json` — labeled "Recommended permissions for the kgenesis plugin": a `skills` name→path map, a `permissions.allow` list (Bash/Read/Edit/Write + ~90 `mcp__ipcat-mcp-server__*` tools, `settings.json:48-138`), and an `env` block (`KGENESIS_VENV`, `settings.json:142-144`). The `skills` map is non-standard (Claude discovers via `skills/**/SKILL.md` frontmatter) — a convenience.

**File-format contracts** (three distinct frontmatter schemas):
- **Command** (`commands/*.md`): frontmatter `description:` + `allowed-tools:` (list); body Reads the SKILL and executes it; sub-commands parsed from the token after a second colon, e.g. `/k-genesis:bringup:init_target` (`commands/bringup.md:1-46, 75-81`).
- **Agent** (`agents/*.md`): frontmatter `name:` + `description:` + `model:` (e.g. `claude-sonnet-4-5`) + `tools:` (list); body = role, "Parameters received from orchestrator," numbered Steps with pseudocode (`agents/add_driver.md:1-36`, `agents/eval_driver.md:1-29`).
- **Skill** (`skills/**/SKILL.md`): frontmatter `name:` + `description:` (with "Use when…"); body starts "Step 0 — Resolve PLUGIN_ROOT" then routing tables. Note `skills/preflight.md` is a *non-user-invocable* helper with **no** frontmatter (`skills/preflight.md:1-6`).

**Routing** is layered: command frontmatter → SKILL.md validation → `orchestrators/<workspace_tree>.md` (mode) → `stages/S*.json` (scope) → per-driver spec gating (`skills/bringup/SKILL.md:151-159`; `docs/DESIGN.md:26-30`).

**Verdict for Audio BU Skill:** `.claude-plugin/plugin.json` and `.claude/settings.json` are **reusable-as-pattern (templates)**, not reusable verbatim (names + IPCat tool allow-list are k-genesis-specific). The dual-runtime (plugin + qgenie) packaging and the symlink trick are genuinely better packaging than a plain python-orchestrator skill — see §8.

---

## 5. IPCat Usage

k-genesis reaches IPCat through **three channels**, all targeting a server named `ipcat-mcp-server` (or the `ipcat_client` library behind it):

**Channel 1 — `scripts/mcp_client.py` (remote HTTP MCP transport).** *This is the decision-relevant finding.*
- Connects via `StreamableHttpTransport` (type `sse`) to a URL + `headers` (token) read from `~/.claude/.mcp.json` — "same file Claude Code uses. The token is never hardcoded" (`scripts/mcp_client.py:13-14, 30-43, 50-81`).
- **Input:** tool name + JSON args (e.g. `call_tool("gpio_list_gpios_from_map", {"gpio_map_id": 42})`, `:9-11`). **Output: structured** — `_unwrap()` concatenates text pieces and `json.loads()` them (`:112-116`).
- **External tools:** `httpx`, `fastmcp`. **Credentials:** token from `.mcp.json`. **Security caveat:** TLS verification is **disabled** (`verify=False`, `:73`) — a real risk if copied.
- **Evidence-Layer mapping:** DIRECT — this is a working structured-per-target register/GPIO/IRQ fetch, boundary-safe w.r.t. `auth.json`.

**Channel 2 — `scripts/gen_reserved_memory.py` (direct `ipcat_client` library).** Imports `ipcat_client.memmap`, calls `get_memory_maps(chip=…, group="SW")`, `get_address_blocks()` (`:315-351, 398-407`); token reused from `.mcp.json` or `~/.config/qgenie-cli/agent/config.toml` (`:323-345`). Structured→transformed into `reserved-memory` DT nodes. This is Phase-0 **Option B**, live.

**Channel 3 — the driver-spec `ipcat_gen` catalogue (the dominant per-node path).** Every driver `.md` declares `data_sources.ipcat_gen:` — a *query catalogue* of `{id, tool, query, extracts, formula, used_for}` (`drivers/TEMPLATE.md:122-137`). `add_driver` runs each query **on-demand at generation time, never pre-fetched/cached**, extracting one scalar and discarding the rest (`agents/add_driver.md:278-296, 350`; `references/golden_rules.md:201-204`). Concrete: `drivers/pinctrl_qcom-soc-tlmm.md:40-68` fetches `tlmm_base`/`tlmm_size`/`tlmm_irq` (+ GIC_SPI/ESPI derivation formula) + `gpio_count`.

**The lookup rulebook** `references/mcp_lookup_rules.md` maps ~30 components → exact `swi_search_swi("MODULE", chip)` queries + extraction offsets (e.g. `gic`→`APSS_GIC700_GICD_APSS` + fixed offsets, `:8-10`; `ipcc`→`IPC_CORE`+0x6000, `:63-65`). Some data is explicitly **not** from IPCat (CPU topology from target.xml, reserved-memory from user XML, `:12-13, 120-121`).

| Property | k-genesis IPCat access | Maps to Audio BU Evidence-Layer need? |
|---|---|---|
| Mechanism | Remote HTTP MCP (`ipcat-mcp-server`, SSE) + `ipcat_client` lib | Yes — the structured typed-rows requirement |
| Auth | Static token in `~/.claude/.mcp.json` headers; **never `auth.json`**; no hourly OAuth refresh | **Yes — this is the boundary-safe model Phase-0 sought** |
| Output | Structured JSON (`json.loads`) | Yes — replaces prose |
| Credentials required | Yes (IPCat token) | Yes |
| Structured vs prose | Structured | Yes |
| Caching | None — on-demand, scalar-extracted, discarded | Contrast: Phase-0/camera_dtsi favored caching |
| Register bases / instance counts / GPIO / memmap | All present (`swi_search_swi`, `chipio_get_qups`, `gpio_list_tlmm_gpios`, `memmap`) | Yes — full coverage |

**UNVERIFIED:** whether the *same* `ipcat-mcp-server` is reachable from the Audio BU Skill environment, and whether its chip catalog includes Audio BU targets (Nord/`<ELIZA-SOC>`). Not tested — testing would require `.mcp.json` inspection, which is out of scope.

---

## 6. DT Generation Flow

**Artifacts generated:** SoC `<soc>.dtsi` audio/soc nodes, `<soc>-reserved-memory.dtsi`, per-board `.dts` (upstream) / `.dtso` overlays (downstream), `cpus{}` block, plus non-DT: bindings YAML, dt-bindings headers, driver `.c`, Kconfig, Makefile/`modules.bzl`/`perf.bzl`/defconfig (`drivers/TEMPLATE.md §4.1–4.7`; `scripts/gen_reserved_memory.py:20-27`; `agents/init_target.md:627`).

**Mechanism — hybrid, not a template engine and not pure-LLM:**
- **Deterministic Python** for a few blocks (`gen_cpus.py`, `gen_reserved_memory.py`).
- **External tools** for whole subsystems (`clockdrivergen` for clock controllers, `tlmm_mkdriver` for pinctrl — `drivers/clock-controller_qcom-soc-cc.md:14,438`, `drivers/pinctrl_qcom-soc-tlmm.md:70-120`).
- **LLM-agent reasoning** filling `dt_node` `how:` templates (with placeholders `<base_addr>`, `<size>`, `SOC_ADDR_CELLS`, `<irq_type>`) from IPCat-sourced scalars, dispatched by layer `type` (create/modify/reference/inbuilt/skip) and `source` (`agents/add_driver.md:441-536`; `drivers/TEMPLATE.md:462-515`).

**UNVERIFIED (important):** the bodies of `run_ipcat_query()`, `generate_from_ipcat()`, `substitute_chip_values()`, `read_reference()` are **pseudocode inside `agents/add_driver.md`**, not shipped `.py`. The only executable Python is the five `scripts/*.py`. Actual DT-node generation is the LLM interpreting markdown — there is **no compiled generator**. This mirrors camera_dtsi's "zero generation code" philosophy (Phase-0 `IPCAT_CAPABILITY_ASSESSMENT.md §3`).

**Anti-guessing / unsupported-value prevention (strong):** Golden Rule 1 "never invent structure from scratch" (`references/golden_rules.md:14-17`); chip values MCP-only, "never hardcode" (`drivers/pinctrl_qcom-soc-tlmm.md:245-246`); missing values kept from reference but marked `UNVERIFIED` — "unverified copies are bugs, not placeholders" (`golden_rules.md:57-66`); DATA MISMATCH must be fixed before commit (`:132-139`); unmapped properties get explicit `# FIXME` (`agents/eval_driver.md:519-524`).

**Validation / checkpatch / manifests / commits / traceability — all YES:**
- Per-driver `validation:` block (`checkpatch`, `dt_schema`, `build_check`, `integrity_checks[]`) executed in `add_driver` Step 5; any FAIL is a hard stop (`drivers/TEMPLATE.md:810-852`).
- `verify_target` runs checkpatch on every commit (STOP on ERROR) + defconfig build + DTB + `make dtbs_check DT_SCHEMA_FILES="qcom"` + phandle integrity (`agents/verify_target.md:102-387`).
- **Manifests:** per-phase `/tmp/.commit_log_<phase>_<soc>.json` (`agents/add_driver.md:766-785`).
- **Commits:** real git commits, structured subjects/bodies, `Assisted-by: <ai_model>` trailer on every commit; downstream adds `Change-Id` (`drivers/TEMPLATE.md:801-806`).
- **Traceability:** `/tmp/.run_report_<soc>.txt` records every substitution ("changed X→Y, verified via IPCat") and every UNVERIFIED value; `/tmp/.undo_anchor_<soc>.json` records pre-run HEADs (`golden_rules.md:62-66`; `scripts/undo_run.py:9-19`).

**Target-spec input** (`configs/*-target.xml`): the single hand-authored file — "source of truth for everything about a chip NOT available from IPCat" (`configs/example-target.xml:7-8`): CPU topology (Section A, → `gen_cpus.py`), per-IP `<ip enable=>` gates + optional `version=`/`instances=` (Section B), boards (Section C).

---

## 7. Worker / Agent Contract Model

**Two contract types:**
- **Agent contract** (executable worker): `agents/<name>.md`, frontmatter `name`/`description`/`model`/`tools` (`agents/eval_driver.md:1-29`). Four agents; `init_target`/`add_driver`/`verify_target` operative for bringup.
- **Driver contract** (declarative spec, *not code, not an agent*): `drivers/<name>.md` per `drivers/TEMPLATE.md`, six required sections — Identity, Dependencies, Data sources, Layers (7 sub-layers), Commit structure, Validation. `add_driver` is a **generic executor** that runs any spec: "One agent handles ALL drivers … This agent never changes" (`agents/add_driver.md:44-47`).

**Roles:** orchestrator (shapes output per `workspace_tree`) → adapter (only path-resolver) → agent (fresh-context executor) → driver (passive spec). **Routing:** 3-tier on `workspace_tree ∈ {kp,android,qclinux}` — literal string substitution into the orchestrator path (`skills/bringup/SKILL.md:151-159`); each orchestrator hard-codes its adapter and `KERNEL_VARIANT` (qclinux→upstream, android→downstream, `orchestrators/qclinux.md:56`).

**Stage ordering:** `stages/S*.json` define `drivers_used[]` (run list) + `ip_supported[]` (device gate) with recursive `INCLUDE:Sx` (S1⊃S0⊃…). For `full`: `init_target` → `add_driver` once per driver (sequential, fresh context) → `verify_target` (`orchestrators/qclinux.md:143-178`).

**Determinism:** `references/golden_rules.md` (R1 reference-first/IPCat-for-values, R2 post-output cross-verify, R3 context discipline, R4 step-scoped exit-early, R5 pass-scalars-keep-IPCat-local, R6 fail-fast, R7 verify-Kconfig-before-write) + MCP-only chip values + confirm-exists-or-fail for inbuilt layers.

**Isolation:** every phase is a **separate sub-agent with a fresh context window** marked `context: fresh`; only a compact scalar/path param dict crosses between them — "no file content, no accumulated context" (`skills/bringup/SKILL.md:66-72`; `orchestrators/qclinux.md:146-149, 234-281`).

**Manifest schema:** JSON commit-log written at `agents/add_driver.md:766-785`; consumed by orchestrator (phase-success check) and `undo_run.py`. Not centralized in one schema file — defined at the write site.

**Commit control:** spec-declared roles + per-commit checkpatch + R7 Kconfig gate + `Change-Id` (downstream) + `verify_target` STOP gates. **Human gate: UNVERIFIED / effectively absent** — commits are autonomous per phase; the only human touchpoints are preflight FAIL stops and a printed "run verify_target" advisory. *(Contrast: Audio BU Skill's design mandates explicit human gates — this is a divergence, not a pattern to copy.)*

**Rollback:** `scripts/undo_run.py` resets repos to `/tmp/.undo_anchor_<soc>.json` HEADs, scoped by `--phase`/`--driver`; **refuses to reset repos with foreign/local commits layered on top** (`skills/bringup/SKILL.md:195-219`).

**Mapping to Audio BU Skill workers:**

| Audio BU worker | Analog | Basis |
|---|---|---|
| IPCAT gather | **Direct** | `ipcat_gen` declarative `{tool,query,extracts,formula}`, on-demand, MCP-as-authority (`drivers/mailbox_qcom-ipcc.md:42-63`) |
| Audio KB | **Partial** | No live KB; knowledge encoded as static per-driver specs + `soc_ref` reference chip (R1). Audio BU's markdown KB (WP-A) is arguably *more* KB-like |
| SoundWire cardinality | **Partial** | Generic `active_devices` intersection + multi-instance detection + GPIO/IRQ count formulas — cardinality resolution exists but is not SoundWire-specific |
| DTSI generation | **Direct** | `dt_node` layer + `init_target` SoC-DTSI skeleton (`drivers/pinctrl_qcom-soc-tlmm.md:248-317`) |
| Validation | **Direct** | `verify_target` agent + per-driver `integrity_checks[]` + R2 cross-verify |
| Confidence ledger | **None** | Only FIXME markers + run-report text + `Assisted-by` trailer; **no per-value confidence/provenance ledger — Audio BU Skill (WP-B) is ahead here** |

---

## 8. `.claude` and `.claude-plugin` Assessment

| Asset | Classification | Justification |
|---|---|---|
| `.claude-plugin/plugin.json` | **Reusable as pattern (template)** | Standard manifest shape (`plugin.json:1-13`); copy structure, change metadata. Not verbatim (name/keywords specific). |
| `.claude/settings.json` (generic Bash/Read/Edit/Write allows + `env`) | **Reusable as pattern** | Permission allow-list + env + skills-map template (`settings.json:10-45, 142-144`). |
| `.claude/settings.json` (~90 `mcp__ipcat-mcp-server__*` allows) | **Not reusable** | IPCat-tool-specific (`settings.json:48-138`); Audio would list its own MCP tools. |
| `.claude/commands` symlink → `commands/` | **Reusable as pattern** | Dev-mode + plugin dual-availability trick; not a copyable artifact. |
| Command/agent/skill frontmatter conventions | **Reusable as pattern** | Three clean frontmatter schemas usable as-is for an audio plugin. |
| Dual-runtime (plugin + qgenie from one tree) | **Reusable as pattern** | `docs/INSTALL.md:48-138` — one artifact, two runtimes, no code fork. |

**Does it give a better packaging model?** Yes, for five source-proven reasons: (1) dual-runtime from one tree; (2) fresh-context sub-agent isolation (context discipline a monolithic python script can't get for free); (3) declarative capability extension (add a driver = write one spec, "this agent never changes"); (4) native integration with Claude Code permissions/tooling; (5) an explicit external-skill delegation contract (`references/external_skill_interface.md:37-141`). **Cost/caveat:** the "logic" is LLM-interpreted markdown prompt-pseudocode, with real determinism pushed into `scripts/*.py` — a packaging/orchestration win layered *on top of* python helpers, not a replacement for them.

**Relevance to the specific questions asked:**
- *Can `.claude` define reusable project commands?* — Yes (`commands/*.md`, **pattern**).
- *Can `.claude-plugin` package workflows?* — Yes (`plugin.json` + convention discovery, **pattern**).
- *Easier to run / avoid manual prompts / repeatable onboarding?* — Yes: `/k-genesis:bringup …` one-shot invocation with param validation replaces ad-hoc prompting (**pattern**, needs Audio-specific authoring).
- *Better boundary between prompt logic and source code?* — Partial: it separates *orchestration prompt* from *python helpers*, but the generation "logic" itself is prompt, not code — a different boundary than Audio BU Skill's python-orchestrator model, not strictly better.

---

## 9. Comparison with Audio BU Skill

| Area | Audio BU Skill Current Plan | k-genesis Pattern | Reusable? | Risk | Recommendation |
|---|---|---|---|---|---|
| **IPCat access** | Phase-0: A (native MCP Hub, `auth.json` OAuth) / B (`ipcat_client` lib) / C (local structured MCP); short-term B, long-term C; blocker = env-isolation + `auth.json`/refresh | Remote HTTP MCP `ipcat-mcp-server` (SSE) + static token in `.mcp.json` (no `auth.json`, no hourly refresh) + `ipcat_client` lib for memmap | Pattern | TLS `verify=False`; server may not host Audio targets (UNVERIFIED) | **Study further** — concrete evidence for A-Option-C; do not copy transport code |
| **Structured evidence extraction** | Typed rows required (Phase-0 gate 3) | `json.loads` structured output, scalar-extract-and-discard (`mcp_client.py:112-116`) | Pattern | On-demand no-cache (Phase-0/camera_dtsi preferred caching) | **Adopt later** — validates typed-rows feasibility |
| **Worker contracts** | Skill packages (skill.yaml+schema+validator); Phase-2 gen skills | Declarative driver spec + one generic executor + fresh-context sub-agents | Pattern | Prompt-as-logic reduces determinism | **Study further** for Phase-2 |
| **Claude plugin packaging** | Python-orchestrator skill | Dual-runtime plugin + qgenie, `.claude-plugin/plugin.json` | Pattern | Repackaging effort | **Adopt later** — if a plugin distribution is desired |
| **Staging model** | Phase-2: `artifacts/<run_id>/generated/`, never mutate tree in place | Generates directly into kernel tree + git commits (no separate staging dir) | No | Direct-mutate conflicts with Audio's staging invariant | **Do not adopt** — Audio's staging model is safer |
| **Manifest / run audit** | run_manifest + fingerprints | `/tmp/.commit_log_*.json` + run_report + undo_anchor | Pattern | `/tmp` volatility | **Study further** — undo_anchor idea is good |
| **Confidence / warnings** | WP-B Confidence Ledger + WP-C Cardinality (implemented, committed) | FIXME + run_report + `Assisted-by` trailer only | No (Audio ahead) | — | **Do not adopt** — keep Audio's ledger |
| **Commit discipline** | Human-gated (design invariant) | Autonomous per-phase commits; **no human gate** (UNVERIFIED) | No | Autonomy conflicts with Audio gates | **Do not adopt** the autonomy; keep gates |
| **Checkpatch discipline** | (future generation lane) | checkpatch per commit, STOP on ERROR (`verify_target.md:102-121`) | Pattern | — | **Adopt later** (Phase-2/3) |
| **DT generation** | Phase-2 inert (NullEngine); deferred until Eliza validates Phase-1 | Full hybrid python+external-tool+LLM generation, live | Pattern | Scope: onboarding stays analysis-only | **Study further** — reference for Phase-2 engine |
| **Rollback** | (not yet designed) | `undo_run.py` phase/driver-scoped, refuses foreign commits | Pattern | — | **Adopt later** — good rollback model |
| **Contributor onboarding** | Docs-heavy | `docs/INSTALL.md` dual-runtime + declarative specs lower the bar | Pattern | — | **Adopt later** |
| **Long-term production architecture** | Long-term C (local structured MCP) | Remote MCP + declarative specs, in production for DT | Pattern | Different (remote vs local MCP) | **Study further** — a data point, doesn't unseat C |

---

## 10. Reusable Patterns

Ranked by leverage × cheapness × source-proof:

1. **Declarative per-unit spec + one generic executor** (`agents/add_driver.md:44-47`; `drivers/TEMPLATE.md`). Directly informs Audio's Phase-2 generation-skill design. **Reusable as pattern. Adopt later (Phase-2).**
2. **Golden-rules rulebook as load-bearing determinism** (`references/golden_rules.md`) — anti-fallback, MCP-as-authority, "UNVERIFIED copies are bugs." Confirms Audio WP-A/WP-C direction. **Pattern. Study further** (Audio already has the principle; k-genesis shows the operationalized format).
3. **Fresh-context sub-agent-per-unit isolation** (`skills/bringup/SKILL.md:66-72`). **Pattern. Adopt later.**
4. **Phase-scoped rollback with an undo-anchor that refuses foreign commits** (`scripts/undo_run.py`). **Pattern. Adopt later** (Phase-2/3 generation lane).
5. **Boundary-safe structured MCP access via a `.mcp.json` static token** (`scripts/mcp_client.py:30-81`) — concrete evidence a boundary-safe structured IPCat path exists without `auth.json`. **Pattern. Study further** (do not copy `verify=False`).

Honorable mentions: dual-runtime plugin packaging; `stages/S*.json` include-expansion scope model; per-commit checkpatch + `dtbs_check` gate; `external_skill_interface.md` delegation contract.

---

## 11. Non-Reusable / Unsafe Patterns

1. **`verify=False` TLS-disabled transport** (`scripts/mcp_client.py:73`) — **unsafe**; must never be copied. If the MCP path is ever pursued, verification must be enabled.
2. **Autonomous per-phase git commits with no human gate** (§7, UNVERIFIED but no gate found) — conflicts with Audio BU Skill's explicit human-gate invariant. **Do not adopt.**
3. **Direct mutation of the kernel tree** (no separate staging dir) — Audio's Phase-2 `artifacts/<run_id>/generated/` staging model is safer. **Do not adopt.**
4. **IPCat/Qualcomm-DT-specific content** — `mcp_lookup_rules.md` module map, the ~90 `mcp__ipcat-mcp-server__*` allow-list, driver specs, target.xml schema — all domain-specific. **Pattern only, never verbatim.**
5. **Prompt-as-logic pseudocode** (`add_driver.md` "functions" that are not shipped code) — reduces determinism/testability vs Audio's tested python orchestrator. Adopt the *contract shape*, not the "logic lives in markdown" choice.
6. **`/tmp`-based manifests/anchors** — volatile; Audio's `artifacts/<run_id>/` is more durable.
7. **No caching of IPCat responses** — Phase-0 and camera_dtsi both favor caching; k-genesis's discard-after-scalar model is a deliberate context-discipline tradeoff, not a pattern to copy uncritically.

---

## 12. Roadmap Impact

Answering the explicit questions:

- **Does k-genesis change the Phase-0 conclusion?** **No.** Phase-0 evaluated the *access-architecture taxonomy* and concluded short-term B / long-term C, gated on an operator provisioning decision. k-genesis is a working instance within that taxonomy; it confirms rather than contradicts.
- **Does it change the short-term recommendation B vs A-Option-C?** **It strengthens A-Option-C's credibility.** Phase-0 rated plain A "PARTIAL-GO, inherits the `auth.json`/hourly-refresh problem." k-genesis demonstrates a **variant of A that avoids exactly that problem** by using a static `.mcp.json` header token instead of the qgenie OAuth bearer (`scripts/mcp_client.py:30-81`). This is concrete evidence that the "dedicated read-only credential + native wiring" fallback (`PHASE0_MECHANISM_DECISION.md:84`) is buildable and boundary-safe. It does **not** make A beat B; both remain viable, and the operator decision still stands.
- **Does it strengthen the long-term recommendation C?** **Neutral-to-slightly.** k-genesis uses a *remote* MCP, whereas C is a *local* structured MCP. It proves the "structured MCP tool returning typed rows + declarative specs + KB-of-rules" shape works in production for DT generation — which is the C-shaped end state — but via remote transport. A supporting data point, not a reason to re-rank.
- **Does it introduce a fourth architecture option?** **No new architecture class.** The `.mcp.json`-token remote MCP is best classified as a **concrete instantiation of Option A's dedicated-credential sub-variant**, plus Option B (it also uses `ipcat_client` directly). Worth *documenting* as "A′ (static-token remote MCP)" for precision, but it is not a fourth peer to A/B/C.
- **Does it affect Phase-1 entry?** **No gate changes.** Phase-1's first deliverables (typed rows, Eliza resolution, three counts) are unchanged. k-genesis offers a *reference implementation* for how to get typed rows, but Audio's Gate-1 (mechanism chosen + provisioned + boundary-safe creds) is unchanged and still unsatisfied.
- **Does it affect Phase-2 generation planning?** **Yes — most relevant here.** k-genesis is a mature reference for the exact lane Audio's Phase-2 foundation is scaffolding (currently inert NullEngine): declarative gen-specs, layer dispatch, checkpatch/dtbs_check validation, rollback, manifests. **Recommend folding k-genesis into Phase-2 design study** (not Phase-0/1).
- **Does it justify updating `PHASE0_FINALIZATION_PACKAGE.md`?** **No — do not modify it** (per constraint and because nothing invalidates it). At most, add a **new, separate addendum doc** noting the observed access mechanism as concrete evidence for A-Option-C. The finalization package's conclusion ("Phase 0 complete, awaiting operator decision") remains valid.

---

## 13. Recommendation

**Overall leverage: MEDIUM–HIGH as a pattern reference; LOW as directly-reusable code.**

- **Do not reopen Phase-0.** No source finding reveals a *materially better* access mechanism that invalidates current assumptions; k-genesis's access model is a concrete instance of an already-catalogued option, and it inherits its own risks (TLS-disabled transport, no caching).
- **Adopt now:** nothing (this is investigation-only; no implementation).
- **Adopt later (Phase-2 generation lane):** declarative-spec + generic-executor pattern; fresh-context sub-agent isolation; per-commit checkpatch/`dtbs_check` gate; phase-scoped rollback (undo-anchor). All gated behind Audio's existing "generation deferred until Eliza validates Phase-1" invariant.
- **Study further:** the `.mcp.json` static-token structured-MCP access model (as A-Option-C evidence); the dual-runtime plugin packaging; the golden-rules operationalization format.
- **Do not adopt:** `verify=False` transport; autonomous no-human-gate commits; direct kernel-tree mutation; `/tmp` manifests; any IPCat/DT-specific content verbatim.

**Per the "don't say adopt unless source proves it and it doesn't conflict with Phase-0" rule:** every "adopt later" above is source-proven and conflicts with no Phase-0 constraint (they concern Phase-2 generation, which Phase-0 explicitly scoped as a separate track).

---

## 14. Open Questions

1. **Is `ipcat-mcp-server` reachable from the Audio BU Skill environment, and does its catalog include Nord / `<ELIZA-SOC>`?** UNVERIFIED — would require `.mcp.json` inspection / a live call (out of scope). *This is the single highest-value follow-up if the operator leans toward the MCP access path.*
2. **Is the `.mcp.json` token a per-user OAuth-derived token or a long-lived service credential?** Determines whether k-genesis's model truly avoids the refresh problem or merely relocates it. Source shows the token is read from `.mcp.json` headers but does not show its lifecycle.
3. **Is there a compiled generator anywhere, or is all DT-node generation LLM-interpreted markdown?** Source shows only five `scripts/*.py`; `run_ipcat_query`/`generate_from_ipcat` are pseudocode. UNVERIFIED whether a private/uncommitted engine exists.
4. **How does k-genesis handle a human review gate** (if at all beyond the "run verify_target" advisory)? No pre-commit human gate found; confirm whether one exists elsewhere.
5. **Does the on-demand no-cache IPCat model cause latency/rate issues at scale?** Relevant if Audio adopts the query-catalogue pattern; not observable from source.

---

## Confidentiality & scope compliance

- **No implementation, no code changes, no DT patches, no production code.** Nothing staged, committed, or pushed. No Audio BU Skill source modified. No Phase-0 doc modified.
- **No qgenie config, `.mcp.json`, or `auth.json` accessed** — `scripts/mcp_client.py` was *read as k-genesis source*; the actual `~/.claude/.mcp.json` was not opened.
- **No k-genesis code copied into `audio_bu_skill/`.** Clone confined to `prior_art/k-genesis` (git-ignored). No dependencies installed.
- Every capability claim cites `file:line` in the clone; unproven items marked **UNVERIFIED**. The presentation deck was not used.
- Nord alias reproduced only from non-confidential in-repo docs; `<ELIZA-SOC>` unresolved. No count asserted.

---

## Final Output

**Overall leverage rating:** **MEDIUM–HIGH (pattern) / LOW (code).** A mature, directly-comparable prior art whose value is architectural patterns and one concrete access-model data point — not copyable code.

**Top 5 reusable patterns:**
1. Declarative per-unit spec + one generic executor agent (`agents/add_driver.md:44-47`).
2. Fresh-context sub-agent-per-phase isolation with scalar-only handoff (`skills/bringup/SKILL.md:66-72`).
3. Golden-rules rulebook enforcing MCP-as-authority + "UNVERIFIED copies are bugs" (`references/golden_rules.md`).
4. Phase-scoped rollback via undo-anchor that refuses foreign commits (`scripts/undo_run.py`).
5. Boundary-safe structured IPCat via `.mcp.json` static token, returning JSON (`scripts/mcp_client.py:30-116`).

**Top 5 risks:**
1. TLS verification disabled (`verify=False`, `scripts/mcp_client.py:73`) — never copy.
2. Autonomous commits with no human gate (§7) — conflicts with Audio's gate invariant.
3. Direct kernel-tree mutation (no staging) — conflicts with Audio Phase-2 staging model.
4. Prompt-as-logic (generation "code" is markdown pseudocode) — lower determinism/testability.
5. Unverified whether `ipcat-mcp-server` serves Audio targets — the MCP path may not transfer.

**Should Audio BU Skill update its roadmap?** **Only additively, and only for Phase-2.** Fold k-genesis into Phase-2 generation-lane design study; add a short addendum documenting the observed `.mcp.json`-token access model as concrete evidence for the A-Option-C fallback. **Do not** alter Phase-0/1 gates or the B-short-term/C-long-term decision.

**Does Phase-0 finalization remain valid?** **Yes.** Nothing in k-genesis source invalidates any Phase-0 assumption or conclusion. Phase 0 remains engineering-complete, awaiting the operator's mechanism + credential decision. `PHASE0_FINALIZATION_PACKAGE.md` should **not** be modified.

---

*k-genesis Prior-Art Analysis — investigation-only spike. Cloned, read, and cited from source at HEAD `4f6951b`. Overall: MEDIUM–HIGH pattern leverage, LOW code leverage; strongest relevance to Audio BU Skill's Phase-2 generation lane, not Phase-0/1. Phase-0 conclusion stands; do not reopen. Deliverable uncommitted per instruction.*
