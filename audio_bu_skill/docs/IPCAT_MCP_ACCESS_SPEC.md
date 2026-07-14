# IPCAT (IP Catalog) MCP — Access Specification

**Status:** ✅ Verified working end-to-end on 2026-07-13 against real chips (SA8797P/Nord, SA8775P/LeMans).
**Purpose:** Authoritative reference so any skill or agent can pull GPIO / clocks / SWI registers / IRQs / HPG / HSR / bus / chip data from Qualcomm's IP Catalog.

---

## 1. What this is

`ip_catalog` is an MCP server hosted on the **QGenie MCP Hub**. It is **not** wired into the Claude Code session as a native MCP tool, but it is fully reachable two ways:

1. **Direct HTTP** (JSON-RPC over the MCP `/connect/.../mcp` endpoint) — what the examples below use. Works today, no extra setup.
2. **Native MCP** — add it to `.mcp.json` so the 95 tools appear as `mcp__ip_catalog__*`. Cleaner for repeated use (see §6).

- **Server:** `ip_catalog`  — 95 tools, state `connected`, auth type `User Headers`
- **Endpoint:** `https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`
- **Hub base:** `https://qgenie-mcphub.qualcomm.com`

---

## 2. Authentication

Everything hangs off the QGenie CLI home and its stored MCP Hub OAuth token.

```sh
export QGENIE_CLI_HOME=/local/mnt/workspace/qgenie
```

- **Token file:** `$QGENIE_CLI_HOME/mcphub/auth.json`
  - Fields: `access_token` (Bearer, RS256 JWT), `refresh_token`, `expires_at` (epoch seconds), `base_url`, `client_id`.
  - Scope: `mcp offline_access`. Group membership includes `qgenie.mcphub.users`.
- **Lifetime:** access token ≈ 1 hour. `offline_access` means it auto-renews from the stored `refresh_token`.
- **Refresh:** the token rotates automatically. To force it:
  ```sh
  $QGENIE_CLI_HOME/bin/qgenie mcphub login      # re-auth if refresh token is dead
  $QGENIE_CLI_HOME/bin/qgenie mcphub me          # show current session + expiry
  ```
- **Extract the live token** (always read it fresh — do not hard-code):
  ```sh
  python3 -c "import json;print(json.load(open('$QGENIE_CLI_HOME/mcphub/auth.json'))['access_token'])"
  ```

**Identity is derived from the token by the gateway — never pass a username.**

---

## 3. The call recipe (copy/paste)

Every tool call is a JSON-RPC `tools/call` POST. Required headers:

- `Authorization: Bearer <token>`
- `Content-Type: application/json`
- `Accept: application/json, text/event-stream`  ← **both** required, or the hub rejects the request.

```sh
export QGENIE_CLI_HOME=/local/mnt/workspace/qgenie
TOKEN=$(python3 -c "import json;print(json.load(open('$QGENIE_CLI_HOME/mcphub/auth.json'))['access_token'])")
URL="https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp"

curl -sS -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"<TOOL_NAME>","arguments":{ ... }}}'
```

**List all tools** (schemas included): same call with `"method":"tools/list","params":{}`.

### Response envelope

```json
{ "jsonrpc":"2.0", "id":1,
  "result": { "content": [ { "type":"text", "text":"<JSON-encoded string>" } ] } }
```

⚠️ The payload is a **JSON string inside `result.content[0].text`** — you must `json.loads` it twice. Parse pattern:

```python
import sys, json
d = json.load(sys.stdin)
payload = json.loads(d["result"]["content"][0]["text"])   # <-- the real data
```

Errors come back as top-level `{"error":{...}}` instead of `result`.

---

## 4. Tool inventory (95 tools, by domain)

| Domain | Count | Key tools |
|---|---|---|
| **chips** | 15 | `chips_list_chips`, `chips_chip_details`, `chips_get_block_diagram`, `chips_get_chip_geometry`, `chips_lookup_jtag_id`, `chips_list_chip_versions` |
| **swi** | 9 | `swi_search_swi`, `swi_get_module_details[_by_chip]`, `swi_get_module_registers`, `swi_get_register_by_address`, `swi_list_registers_by_addresses`, `swi_get_submodules`, `swi_map_versions_by_chip`, **`swi_generate_hwio_c_header_file`** |
| **gpio** | 3 | `gpio_get_gpio_map`, `gpio_list_gpios_from_map`, `gpio_list_tlmm_gpios` |
| **clocks** | 3 | `clocks_list_frequency_plans`, `clocks_get_frequency_plan_release`, `clocks_get_merged_frequency_plan` |
| **irqs** | 6 | `irqs_list_interrupts`, `irqs_get_latest_interrupt_map`, `irqs_get_pdc_interrupts`, `irqs_get_mpm_interrupts`, `irqs_export_interrupts`, `irqs_list_interrupt_maps` |
| **buses** | 8 | `buses_list_buses`, `buses_get_bus_release[_file]`, `buses_list_bus_ports/connections/gateways`, `buses_list_bidpidmids` |
| **hpgs** | 2 | `hpgs_list_hpgs`, `hpgs_hpg_details` |
| **hsrs** (HSR — *not* HSG) | 2 | `hsrs_list_hsrs`, `hsrs_hsr_details` |
| **qdss** | 15 | `qdss_list_hw_events`, `qdss_generate_hw_events_qtf`, `qdss_get_cti_release`, `qdss_list_atb_topology_*`, ... |
| **cores** | 6 | `cores_list_cores`, `cores_list_core_instances`, `cores_list_core_design_elements`, `cores_list_core_generics` |
| **corners** | 5 | `corners_get_corners_table_data`, `corners_list_corners_*` |
| **pmic** | 4 | `pmic_list_pmics`, `pmic_list_pmic_peripherals[_types/_subtypes]` |
| **socinfo** | 8 | `socinfo_generate_cdt`, `socinfo_list_chipinfo_families/variants`, `socinfo_get_binning_info`, `socinfo_list_platforminfo_configs` |
| **smmuaperture** | 4 | `smmuaperture_list_aperture_specs`, `smmuaperture_get_aperture_spec_xml`, `..._sw_xml`, `..._list_aperture_granules` |
| **swattrs** | 2 | `swattrs_list_sw_attribute_types`, `swattrs_list_sw_attributes` |
| **chipio** | 1 | `chipio_get_qups` |
| **pga** | 2 | `pga_platforms_with_chipinfo`, `pga_ppa_dataset` |

### Coverage vs. the original ask
| Asked | Status | Notes |
|---|---|---|
| GPIO | ✅ | `gpio_*` (3) |
| Clocks | ✅ | `clocks_*` (3) — frequency plans |
| Resets | ⚠️ | **No `resets_*` group.** Reset control is register-level: read GCC/reset registers via `swi_*`. |
| SWI | ✅ | 9 tools incl. HWIO C-header generation |
| HPG | ✅ | `hpgs_*` (2) |
| HSG | ✅ as **HSR** | catalog uses "HSR"; confirm this is the intended artifact |

---

## 5. Chip identifiers (the `chip` argument)

Most tools take `chip` = **alias** (preferred) or numeric id. From `chips_list_chips` (732 chips total). Relevant to Nord/audio work:

| Chip | alias | id |
|---|---|---|
| **SA8797P (NordAU)** v2 | `nordschleife_2.0` | 781 |
| SA8797P (NordAU) v1.1 | `nordschleife_1.1` | 908 |
| SA8797P (NordAU) | `nordschleife_1.0` | 567 |
| **SA8775P (LeMansAU)** | `lemansau_1.0` | 434 |
| SA8775P (LeMansAU) r2 | `lemansau_2.0` | 520 |
| SA8650P (LeMansAU) | `lemansau_sa8650p` | 540 |
| SA8255P (LeMansAU) | `lemansau_sa8255p` | 539 |
| QCS9075 (LeMansAU) | `lemansau_QCS9075` | 825 |
| WSA8840 (Kundu) codec | `kundu_1.0` | 457 |
| WSA885X (Pandeiro) codec | `pandeiro_1.0` / `_2.0` | 795 / 896 |

To resolve any other part: `chips_list_chips` (no args) → filter by `name`/`alias`.

---

## 6. Optional: wire as native MCP (`mcp__ip_catalog__*`)

Add to project `.mcp.json` so tools appear natively (auth via Bearer header):

```json
{
  "mcpServers": {
    "ip_catalog": {
      "type": "http",
      "url": "https://qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp",
      "headers": { "Authorization": "Bearer ${IPCAT_TOKEN}" }
    }
  }
}
```

Caveat: the Bearer token expires hourly. For a durable native setup, a small wrapper that reads the live token from `mcphub/auth.json` (and runs `qgenie mcphub login` on 401) is more robust than a static header. Until then, **direct HTTP (§3) is the reliable path** because the token is read fresh on every call.

---

## 7. Verified examples (ran successfully 2026-07-13)

**A. SWI register search — LPASS on Nord:**
```sh
... "params":{"name":"swi_search_swi",
              "arguments":{"chip":"nordschleife_2.0","query":"lpass"}}
```
→ returned register list incl. `DIE_0_LPASS_THROTTLE_THROTTLE_0_RESET_CNTRL` @ 0x2010B... etc.

**B. List chips:**
```sh
... "params":{"name":"chips_list_chips","arguments":{}}
```
→ 732 chips, ~182 KB.

**C. Generate HWIO C header** (authoritative register defs — unblocks I2S8/LPASS FIXMEs):
```sh
... "params":{"name":"swi_generate_hwio_c_header_file",
              "arguments":{"chip":"nordschleife_2.0","module":"<MODULE>"}}
```
(Discover `<MODULE>` via `swi_search_swi` / `swi_get_submodules` first.)

---

## 8. Gotchas / rules for skills

1. **Always read the token fresh** from `auth.json` at call time — never cache/hard-code it (hourly expiry).
2. **Both `Accept` values** (`application/json, text/event-stream`) are mandatory.
3. **Double-decode** the response (`result.content[0].text` is a JSON string).
4. Use **alias**, not marketing name, for the `chip` arg.
5. **No resets API** — go through `swi_*` register reads.
6. **HSR ≠ HSG** — confirm terminology before relying on `hsrs_*`.
7. On `401`/expired token: run `qgenie mcphub login` (or `mcphub me` to inspect), then retry.
8. Discovery-first for SWI: `swi_search_swi` → get module/register names → `swi_get_module_registers` / `swi_get_register_by_address`.
