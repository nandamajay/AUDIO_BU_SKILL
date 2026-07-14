# Phase-1B — Live Target Resolution Evidence

**Type:** Live evidence record. **No probe.py changes, no architectural changes, no commits.**
**Mechanism:** Read-only `tools/call` against the live `ip_catalog` MCP server (`qgenie-mcphub.qualcomm.com/connect/ip_catalog/mcp`) via an ad-hoc session helper. `probe.py` unmodified.
**Evidence timestamp (UTC):** 2026-07-14T12:07:13Z
**Artifact:** `experiments/ipcat_probe/artifacts/phase1b_live.json`

**Boundary compliance:** `auth.json` not read (presence-check only) · `.credentials.json` not read · TLS `verify=True` · read-only allow-list only · `probe.py` unmodified · live token handled by reference only (never echoed).

---

## 1. Resolution tool

`chips_list_chips` — the authoritative catalog enumerator (733 chips). This is the tool the probe's Path A *should* call (probe.py currently hardcodes the non-existent `get_chips` — a known, separately-tracked probe blocker; **not** patched here per constraint). Resolution is a filter over the full enumeration, then a ≥2-named-field re-confirm per the frozen `PHASE1B_1C_DESIGN.md` contract.

---

## 2. ResolutionResult — Target A: SA8797P (NordAU) v2

| Field | Value |
|---|---|
| target_label | `SA8797P (NordAU) v2` |
| **status** | **RESOLVED** |
| chip_id | **781** |
| canonical_name | `SA8797P (NordAU) v2` |
| alias | `nordschleife_2.0` |
| family | `Wildcat` (id 23) |
| source_tool | `chips_list_chips` |
| matched fields | `id=781`, `name`, `alias`, `family` — **4 named fields (≥2 required)** |

**Re-confirm (≥2 fields):** satisfied — id + name + alias + family all agree.
**Target basis:** repo pins SoC family SA8797P/NordAU (`targets/nord-iq10/profile.json:3,72`); v2 (id 781) is the latest catalog revision and the working alias per `docs/NORD_TARGET_IDENTIFICATION.md`. The exact silicon *revision* (v1.0/v1.1/v2) is not repo-pinned — family is fully resolved; v2 is the defensible "latest" default, recorded as such (not asserted as an evidenced revision).

---

## 3. ResolutionResult — Target B: SM7750 (Eliza)

| Field | Value |
|---|---|
| target_label | `SM7750 (Eliza)` |
| **status** | **RESOLVED** |
| chip_id | **693** |
| canonical_name | `SM7750 (Eliza)` |
| alias | `eliza_1.0` |
| family | `Wildcat` (id 23) |
| source_tool | `chips_list_chips` |
| matched fields | `id=693`, `name`, `alias`, `family` — **4 named fields** |

**Re-confirm (≥2 fields):** satisfied. Single unambiguous `Eliza` catalog row.

---

## 4. Verdict

| Target | chip_id | Status | Matched fields |
|---|---|---|---|
| SA8797P (NordAU) v2 | 781 | **RESOLVED** | id + name + alias + family |
| SM7750 (Eliza) | 693 | **RESOLVED** | id + name + alias + family |

**PHASE-1B = PASS.** Both targets RESOLVED; Nord re-confirmed on ≥2 named fields as required. No fabrication; all values read live from `chips_list_chips`.

---

*Live evidence only. No code changes, no probe changes, nothing committed.*
