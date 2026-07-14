# Phase-2A Authority Discovery Spike — T1 (GPIO/Pinmux) & T4 (Connectivity)

**Type:** Live evidence only. **No implementation, no code changes, no commits.**
**Question (A1 from `PHASE2A_SPECIFICATION.md` §6):** Does IPCAT already expose authority surfaces for Track T1 (GPIO/pinmux) and Track T4 (connectivity), or must Phase-2A launch with T2/T3/T5 only?
**Mechanism:** Read-only `tools/list` + `tools/call` against the live `ip_catalog` MCP (`qgenie-mcphub.qualcomm.com`), via the ad-hoc session helper. Probed against the resolved target **Nord — SA8797P (NordAU) v2, chip_id 781, alias `nordschleife_2.0`**.
**Evidence timestamp (UTC):** 2026-07-14T16:35:43Z

**Boundary compliance:** `auth.json`/`.credentials.json` never read · TLS `verify=True` · read-only allow-list (`list_*`/`get_*`/`search_*` only) · no probe/code changes · token by reference only.

---

## 1. Live IPCAT tool catalog (enumerated)

`tools/list` returned **95 tools** (unchanged from Phase-1). Grouping the candidates relevant to T1/T4:

**GPIO group (T1 candidates):**
`gpio_get_gpio_map`, `gpio_list_gpios_from_map`, `gpio_list_tlmm_gpios`

**Bus / IO / connectivity group (T4 candidates):**
`buses_list_buses`, `buses_list_bus_connections`, `buses_list_bus_ports`, `buses_list_bus_gateways`, `buses_list_bidpidmids`, `buses_get_bus_release`, `buses_list_bus_releases`, `chipio_get_qups`, `cores_list_core_instances`

**Keyword search result (against the 95 tool names):**

| Keyword | Direct tool-name hit? |
|---|---|
| GPIO | ✅ `gpio_get_gpio_map`, `gpio_list_gpios_from_map`, `gpio_list_tlmm_gpios` |
| PINMUX / MUX / FUNCTION | ⚠️ no tool named for it, but the concept is a **field** (`function`) inside the GPIO tools (see §2) |
| TLMM | ✅ `gpio_list_tlmm_gpios` (and `group=TLMM` in the GPIO map) |
| PAD | ⚠️ no tool; `pad` is a **field** in the TLMM GPIO rows (see §2) |
| DAI / I2S / TDM / PCM | ❌ **no tool** and **no field** exposes an I²S/TDM/PCM DAI-link endpoint |
| CODEC | ❌ **no tool** — codecs are board parts, not silicon catalog entities |
| PORT | ✅ `buses_list_bus_ports` / bus-gateway `source_port`/`target_port` — but these are **NoC fabric ports**, not audio DAI ports |
| CONTROLLER | ⚠️ indirect — `chipio_get_qups` (serial engines) and `cores_list_core_instances` (audio cores) |
| CONNECTIVITY | ⚠️ `buses_*` describe **NoC interconnect** connectivity, not codec↔SoC audio paths |

---

## 2. Candidate tool evaluation (live-probed)

### T1 candidates — GPIO / pinmux

#### `gpio_list_tlmm_gpios` — **the T1 authority**
- **Required params:** `chip`. Optional: `external`, `group`, `number`.
- **Live result (Nord):** a list of **1280 GPIO/pad rows**. Each row:
  `{id, name, pad:{id,name,wakeup}, function, number, gpio_map, direction, special_condition, clock, mpgis}`.
- **Audio evidence (decisive):** filtering for audio pin functions returned **77 rows**, including the exact I²S/audio-interface pins:
  - `aud_intfc0_clk` (GPIO 57, function 1), `aud_intfc0_ws` (GPIO 58, function 1), `aud_intfc0_data0..data5` (GPIO 59–64, function 1)
  - **Function-mux alternates on the same pad:** GPIO 61 = `aud_intfc0_data2` (function 1) **or** `aud_intfc10_clk` (function 2); GPIO 63 = `aud_intfc0_data4` (function 1) **or** `aud_intfc7_clk` (function 2).
- **Returned entities:** per-pin name, pad, **function index (the pinmux alternate)**, number, direction. This is precisely a pinmux/function-mux table.
- **Suitability for T1:** ✅ **DIRECT.** It answers "does the silicon expose this pin, and can it mux the claimed audio function?" — the exact T1 question. The `function` field distinguishing `aud_intfc0_*` from `aud_intfc7/10_*` on a shared pad **is** the mux authority.
- **Suitability for T4:** ➖ marginal — gives pins, not codec↔controller paths.

#### `gpio_get_gpio_map` — **T1 support (map resolver)**
- **Required params:** `chip`. Optional: `group`, `tag`, `unpublished`.
- **Live result (Nord):** `{id: 8240, group:{id:1, name:"TLMM", expression:"(?<!BT_)(?<!SSC_)(?<!LPI_)GPIO.*?(\d+)", function_group:"GPIO Interface"}, chipio_release:{id:3584, name:"nordau_io v1.2 ECO F03 Release", chip:{id:781, name:"SA8797P (NordAU) v2", alias:"nordschleife_2.0"}}, gpios:[...]}`.
- **Returned entities:** the GPIO map id (8240), TLMM group definition, and the ChipIO **release provenance** (`nordau_io v1.2 ECO F03`) — valuable for replay/freshness (§ maps directly to the spec's `provenance` block).
- **Suitability for T1:** ✅ DIRECT support — resolves the `gpio_map_id` and pins the release. Pairs with the next tool.
- **Suitability for T4:** ➖ none.

#### `gpio_list_gpios_from_map` — **T1 support (filtered enumerate)**
- **Required params:** `gpio_map_id`. Optional filters: `function`, `name`, `number`, `special_condition`, `external`.
- **Live result (Nord, map 8240):** same 1280-row shape as `gpio_list_tlmm_gpios`. The **`function` and `name` filter params** let T1 query a specific audio pin/function directly instead of client-side filtering.
- **Suitability for T1:** ✅ DIRECT — the parameterized query form. **T1's cleanest path is `gpio_get_gpio_map` → `gpio_list_gpios_from_map(function=…)`.**
- **Suitability for T4:** ➖ none.

### T4 candidates — connectivity

#### `chipio_get_qups` — controller (serial-engine) authority
- **Required params:** `chip`.
- **Live result (Nord):** **27 QUP rows**, each `{group, instance, se_number, wrapper_id, i2c, uart, spi, i3c, q2spi, quad_spi, spi_slave, gpios, irqs, clk, swi, use_cases, …}`.
- **Capabilities present:** `i2c`, `uart`, `spi`, `i3c`, `quad_spi`, `spi_slave`, `hs_uart`. **All 27 are I²C-capable** (candidate codec-*control* buses).
- **Critical negative:** **no `i2s`/`audio`/`tdm`/`pcm` capability flag exists** in the QUP schema. QUPs are the serial-control fabric (I²C/SPI/UART), not the audio-*data* path.
- **Suitability for T1:** ➖ none.
- **Suitability for T4:** ⚠️ **PARTIAL.** It authoritatively enumerates the **codec control-bus** side (which I²C engine a codec could hang off), but **not** the I²S/audio-data DAI path.

#### `buses_list_buses` / `buses_list_bus_gateways` / `buses_list_bidpidmids` — NoC fabric authority
- **Params:** `buses_list_buses` → optional `chip`; gateways/bidpidmids → required `chip`.
- **Live results (Nord):**
  - `buses_list_buses` → **50 buses**; audio-related = `audio_core_noc`, `hpass_audio` (plus `hpass_ag_noc`, `hpass_adas`). Shape `{id, name, description}`.
  - `buses_list_bus_gateways` → **110 rows** `{id, chip, source_bus, source_port, target_bus, target_port}` — inter-**NoC** connections.
  - `buses_list_bidpidmids` → **3678 rows** `{target_bus, bid, pid, mid, initiator_bus, initiator_port, master_name, core_instance, …}` — NoC master/initiator IDs.
- **What these describe:** the **Network-on-Chip interconnect topology** (who talks to whom on the AXI/AHB fabric), not codec↔I²S audio wiring.
- **Suitability for T1:** ➖ none.
- **Suitability for T4:** ⚠️ **PARTIAL/INDIRECT.** Confirms the audio subsystem's **fabric attachment** (`audio_core_noc`, `hpass_audio` exist and are gatewayed), but does not express the codec-facing DAI path T4 targets.

#### `cores_list_core_instances` — audio-core existence authority
- **Params:** `chip`.
- **Live result (Nord):** **175 audio-related core instances** under `u_hpass_wrapper` (e.g. `Audio - QAIF`, `audio_core_noc`, multiple `qdsp6ss` DSP wrappers). Already the verified authority for T3's `dsp_subsystem_instance`.
- **Suitability for T4:** ⚠️ **PARTIAL** — proves the SoC-side audio controllers/cores **exist** (the endpoint T4 would check a codec connects *to*), but not the codec binding.

---

## 3. Classification

| Track | Tool | Classification | Rationale |
|---|---|---|---|
| **T1** | `gpio_list_tlmm_gpios` | **DIRECT_AUTHORITY** | 1280 real pins with pad + **function-mux** field; audio interface pins (`aud_intfc*`) present with alternates. Answers the exact T1 question. |
| **T1** | `gpio_get_gpio_map` + `gpio_list_gpios_from_map` | **DIRECT_AUTHORITY** | Parameterized (`function`/`name`) query path + release provenance. Preferred production form. |
| **T4** | `chipio_get_qups` | **POSSIBLE_AUTHORITY** | Enumerates codec **control** engines (I²C), not the I²S **data** path. Covers half of T4. |
| **T4** | `cores_list_core_instances` | **POSSIBLE_AUTHORITY** | Proves SoC-side audio controller/core **existence** (the endpoint), not the codec binding. |
| **T4** | `buses_list_buses` / `bus_gateways` / `bidpidmids` | **POSSIBLE_AUTHORITY (indirect)** | NoC fabric topology; confirms audio subsystem fabric attachment, not codec↔DAI wiring. |
| **T4** | I²S/TDM/PCM DAI · codec part · DAI-link endpoint | **INSUFFICIENT** | **No tool and no field** in the 95-tool catalog exposes these. Codecs (PCM1681/ADAU1979) are **board parts**; the codec↔controller binding is a **schematic fact IPCAT does not hold.** |

---

## 4. Answers

### Can T1 be implemented now? — **YES.**
IPCAT exposes a **DIRECT** GPIO/pinmux authority today (`gpio_list_tlmm_gpios`, and the `gpio_get_gpio_map` → `gpio_list_gpios_from_map(function=…)` pair). It returns per-pin name, pad, direction, and the **function-mux index** — everything T1's verdict rules in `PHASE2A_SPECIFICATION.md §2/T1` require. The `aud_intfc0_*` pins with function alternates on shared pads are live-confirmed on Nord. **A1 is satisfied for T1; T1 can lift out of `NOT_CROSS_CHECKABLE (authority_tool_unverified)`.**

### Can T4 be implemented now? — **PARTIALLY — not for its core claim.**
IPCAT authoritatively answers the **SoC-side half** of T4:
- codec **control** engines exist (`chipio_get_qups` → I²C), and
- audio **controllers/cores** exist (`cores_list_core_instances`, `buses_list_buses` → `audio_core_noc`/`hpass_audio`).

But T4's defining check — **codec ↔ SoC audio-data path consistency** (does PCM1681 hang off a DAI/port the silicon can drive; is any codec orphaned) — requires the **codec-to-controller binding**, which is a **board/schematic fact IPCAT does not carry.** There is **no I²S/TDM/PCM DAI-link, codec-part, or audio-port tool or field** in the catalog. IPCAT can validate that the SoC endpoint *exists and is capable*; it cannot validate the *binding* to a board codec.

**Consequence for T4:** T4 splits into two sub-checks:
- **T4a — SoC-endpoint existence/capability:** implementable now (POSSIBLE_AUTHORITY via QUP + cores + buses). Verdict `MATCH`/`DISAGREE_WITH_AUTHORITY` on "does the controller the design names actually exist on silicon."
- **T4b — codec↔controller binding correctness:** **INSUFFICIENT authority** → stays `NOT_CROSS_CHECKABLE`, but with a **more precise reason than before:** not `authority_tool_unverified`, rather `authority_out_of_scope` (the binding is board data IPCAT structurally does not hold — the schematic/DTS is the only source). This is a *permanent* gap for IPCAT, not a pending discovery.

### Or must Phase-2A launch with T2/T3/T5 only? — **No. Launch with T1 + T2 + T3 + T5, plus T4a.**

**Recommended launch set:**

| Track | Launch status | Authority |
|---|---|---|
| **T1 — GPIO/pinmux** | ✅ **Implement now (DIRECT)** | `gpio_list_tlmm_gpios` / `gpio_list_gpios_from_map` |
| **T2 — Bus** | ✅ Implement now (verified P1) | `swi_search_swi` union+stability |
| **T3 — Audio resource** | ✅ Implement now (live in Phase-1C) | WP-C over `cores_list_core_instances` + `swi_search_swi` |
| **T4a — SoC audio-endpoint existence** | ✅ Implement now (POSSIBLE) | `chipio_get_qups` + `cores_list_core_instances` + `buses_*` |
| **T4b — codec↔controller binding** | ⛔ `NOT_CROSS_CHECKABLE (authority_out_of_scope)` | none — board/schematic-only fact |
| **T5 — DTS consistency** | ✅ Implement now (verified) | `chips_list_chips` + KB rule |

**Net:** the earlier spec's assumption that T1 and T4 were equally gated by A1 is **now corrected by evidence.** T1 is fully unblocked (DIRECT). T4 is *partially* unblocked: its endpoint-existence half (T4a) is implementable now; its codec-binding half (T4b) is not a discovery gap but a **structural scope boundary of IPCAT** and should be recorded as permanently `NOT_CROSS_CHECKABLE` with reason `authority_out_of_scope`, deferring codec-binding validation to a schematic/DTS-internal check (a future track, not an IPCAT authority).

---

## 5. Suggested spec amendments (evidence-driven; not applied here)

1. **`PHASE2A_SPECIFICATION.md §1.3`** — promote `gpio_list_tlmm_gpios`, `gpio_get_gpio_map`, `gpio_list_gpios_from_map` from "unverified" to **verified live-DIRECT** authorities.
2. **§2/T1** — remove the `authority_tool_unverified` gate; T1 emits real verdicts.
3. **§2/T4** — split into T4a (SoC-endpoint, POSSIBLE_AUTHORITY, implement now) and T4b (codec-binding, INSUFFICIENT → `authority_out_of_scope`).
4. **§4 schema** — add `authority_out_of_scope` to `confidence_report.coverage_gaps[].reason` enum (distinct from `authority_tool_unverified`).
5. **§6 A1** — mark **A1 resolved for T1**; re-scope A1's T4 clause to "T4a resolved; T4b is a structural IPCAT boundary, not a discovery item."
6. **§7 build order** — T1 and T4a join the "implement now" set; only T4b remains gated (permanently, by scope).

---

*Evidence only. No implementation, no code changes, no commits. All tool results read read-only from the live `ip_catalog` MCP; every count/field is live-observed against Nord (chip_id 781). No value fabricated; the T4b gap is recorded as a structural authority boundary, not assumed away.*
