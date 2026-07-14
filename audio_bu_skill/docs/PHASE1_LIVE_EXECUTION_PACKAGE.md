# Phase-1 Live Execution Package

**Type:** Consolidation only — the exact package to execute the instant IPCAT provisioning arrives. **No code, no `probe.py` changes, no design changes, no commits, no staging.**
**As of:** commit `2ba93b0` (Phase-1A hardened). Phase-0 frozen; Phase-1A committed + hardened; Phase-1B/1C designs frozen; provisioning **not yet available**.
**Sources (unchanged):** `docs/PROJECT_STATUS_EXECUTIVE.md`, `docs/PHASE1B_1C_DESIGN.md`, `docs/PHASE1A_HARDENING_VALIDATION.md`, `experiments/ipcat_probe/PHASE1A_README.md`.

> **Standing constraints carried into every step below:** read-only only; TLS `verify=True`; `auth.json` never opened (presence-check only); probe stays outside the production import path; no fabricated values — unknown is recorded as unknown. Every artifact is written under `experiments/ipcat_probe/artifacts/` and is discardable (rollback = delete).

---

## 1. Live Run Checklist

### 1.1 Provisioning prerequisites (Gate-1 — operator-owned)
- [ ] Access mechanism **chosen**: Path B (`ipcat_client` library) **or** Path A-Option-C (dedicated-token MCP).
- [ ] **(Path B)** `ipcat_client` dependency approved + importable in the working environment.
- [ ] **(Path A)** `~/.claude/.mcp.json` carries an `ipcat-mcp-server` entry with a `url` **and** an auth `headers` block.
- [ ] **(Path A)** token lifecycle confirmed (OAuth-derived vs long-lived service credential) — open k-genesis question.

### 1.2 Credential prerequisites
- [ ] **(Path B)** one of `IPCAT_TOKEN` / `QGENIE_TOKEN` / `IPCAT_CLIENT_TOKEN` set in the environment (env-var-first).
- [ ] **(Path A)** auth header present in the `.mcp.json` server entry.
- [ ] Credential is **boundary-safe**: presence-verifiable, never sourced from `auth.json`. The probe reads presence only, never logs the value.

### 1.3 Environment prerequisites
- [ ] Working dir: `audio_bu_skill/experiments/ipcat_probe/`.
- [ ] Python 3 interpreter available (probe + tests run under `python` and `python -O`).
- [ ] Network egress to the IPCAT endpoint (Path A) or the library's backend (Path B).
- [ ] `<NORD_ALIAS>` known at runtime (supplied via `--chip` / `IPCAT_PROBE_CHIP`; not stored in-repo).
- [ ] **(Optional)** `IPCAT_PROBE_TIMEOUT` set if the default 30 s is unsuitable.

### 1.4 Verification steps (pre-live, offline — safe now and after provisioning)
- [ ] `python test_probe_hardening.py` → `Ran 22 tests ... OK`.
- [ ] `python -O test_probe_hardening.py` → `Ran 22 tests ... OK`.
- [ ] `python probe.py --check` → intended mechanism shows **present**; `auth.json` untouched; `timeout_seconds` shown.

### 1.5 Expected outputs
- `--check`: JSON with `path_b_ipcat_client` / `path_a_mcp` presence booleans + `timeout_seconds`; **exit 0**.
- Live lookup: JSON result object with `connected` / `structured` / `nord_resolved` + `resolution{status,...}`; exit **0 / 2 / 3** per §2.5.

---

## 2. Phase-1A Live Runbook

**Preconditions:** §1.1–1.3 satisfied for the chosen mechanism; §1.4 offline verification green.

### 2.1 `--check` verification
```
python probe.py --check
```
- Confirm the provisioned mechanism reports `present: true` and the other reports absent (expected).
- Confirm `note` states `auth.json never accessed; TLS enforced when connecting`.
- **Exit 0** required to proceed.

### 2.2 First Nord lookup
```
python probe.py --mechanism <A|B> --chip <NORD_ALIAS>
```
(or `IPCAT_PROBE_MECHANISM=<A|B> IPCAT_PROBE_CHIP=<NORD_ALIAS> python probe.py`)

### 2.3 Success criteria
- **Exit 0** = `connected:true` **and** `structured:true` **and** `nord_resolved:true` (`resolution.status == RESOLVED`, single candidate on a named identifier field).

### 2.4 Failure criteria
- **Exit 2 (partial):** `connected:true` but `structured:false` (prose) **or** `nord_resolved:false` (`ABSENT`/`AMBIGUOUS`/`UNSTRUCTURED`). Investigate before 1B.
- **Exit 3 (failure):** `connected:false` — no connect, boundary-unsafe path required, live-call error (redacted category), or timeout. Stop; see §5.

### 2.5 Exit-code interpretation
| Exit | Meaning | Next |
|---|---|---|
| 0 | connected + structured + Nord resolved | **Advance to Phase-1B** |
| 2 | connected only (prose / unresolved / ambiguous) | Investigate; do **not** advance |
| 3 | not connected / boundary-unsafe / error / timeout | Troubleshoot (§5); do **not** advance |

**Gate to 1B:** only an **exit 0** live PASS opens Phase-1B.

---

## 3. Phase-1B Live Runbook — Eliza Resolution + Nord Re-Confirmation

**Preconditions:** Phase-1A live run returned **exit 0**.

### 3.1 Eliza resolution
- Query the structured enumeration (`get_chips` / `swi_search_swi`, read-only allow-list) for `<ELIZA-SOC>`.
- Produce a `ResolutionResult` with terminal `status` ∈ **RESOLVED / ABSENT / AMBIGUOUS** (never a bare bool):
  - **RESOLVED:** exactly one match on a **named identifier field** → populate `chip_id`, `matched_field`.
  - **ABSENT:** asserted **only** if the enumeration succeeded (structured, N>0 other chips) **and** no identifier-field match. An empty/error/prose response is **not** absent — it is a Phase-1A-class failure (exit-3 semantics).
  - **AMBIGUOUS:** >1 candidate → record **all** in `candidates[]`, pick none, mark UNVERIFIED, stop this target's progression to 1C.

### 3.2 Nord re-confirmation
- Re-confirm `<NORD_ALIAS>` on **≥2 identifier fields** (id + name/alias), not name alone — defeats the substring false-positive risk. Produce a `ResolutionResult`.

### 3.3 Evidence generation
Write one record: `experiments/ipcat_probe/artifacts/phase1b_<target>.json`
```
{ "phase":"1B", "mechanism":"A|B",
  "results":[ ResolutionResult, ... ],
  "boundary":{"auth_json_read":false,"tls_verify":true},
  "verdict":"PASS|PARTIAL|FAIL" }
```
No secrets, no token, no `auth.json` content.

### 3.4 PASS / PARTIAL / FAIL
- **PASS:** Eliza RESOLVED (or authoritative ABSENT) **and** Nord RESOLVED on ≥2 fields.
- **PARTIAL:** one target resolves; the other genuinely AMBIGUOUS (recorded).
- **FAIL:** neither resolves, or the catalog cannot answer identity queries.
- **Gate to 1C:** proceed only for targets with status **RESOLVED**. AMBIGUOUS/ABSENT-Eliza does **not** block a RESOLVED Nord (targets are independent).

---

## 4. Phase-1C Live Runbook — Count Acquisition

**Preconditions:** Phase-1B produced ≥1 **RESOLVED** target; the specific read-only count/enumerate tools added to the allow-list (still read-only; names known only at live time).

For each resolved `chip_id`, acquire the three counts via a **direct → derived → unavailable** cascade. Each `CountResult` carries `value`, `classification`, `method`, `query[]`, `ambiguous`.

### 4.1 `soundwire_master`
- **Direct:** read-only enumeration of SoundWire master instances → `value = len(instances)`, `DIRECT`.
- **Derived:** no direct list but a deterministic mapping exists (e.g. per-subsystem master presence) → compute via documented formula, `DERIVED` (formula in `method`).
- **Unavailable:** neither countable nor deterministically derivable → `value=null`, `UNAVAILABLE` (reason in `method`). Never inferred from prose.
- **WP-C note:** excludes dt in cross-check (SWR-P1); count-vs-routing mismatch → `benign_divergence` (SWR-D1), handled by the committed lane.

### 4.2 `dsp_subsystem_instance`
- **Direct:** enumerate DSP subsystem instances → `len(...)`, `DIRECT`.
- **Derived:** derive from a subsystem/topology descriptor if unambiguously implied → `DERIVED`.
- **Unavailable:** not listable and not unambiguously derivable → `UNAVAILABLE`.

### 4.3 `lpass_macro_instance`
- **Direct:** enumerate LPASS macro instances → `len(...)`, `DIRECT`.
- **Derived:** derive from LPASS macro configuration/registers via a deterministic rule → `DERIVED` (formula recorded).
- **Unavailable:** ambiguous or absent → `UNAVAILABLE`, or `ambiguous:true` → routed to `not_cross_checkable`.

### 4.4 Classification discipline
- `DIRECT` only when a real enumeration is counted (never `len()` of a mislabeled field — the Eliza `len()`-bug class fixed in WP-C).
- `DERIVED` requires a documented, deterministic formula; derivable-but-ambiguous → `ambiguous:true`, not a fabricated number.
- `UNAVAILABLE` is a legitimate recorded outcome — partial success, not failure.

### 4.5 Cardinality cross-check + evidence
- Assemble the `element_counts` schema-1.3.0 input from the `CountResult`s; apply the dt=0/`dt_applied=false` drop and `ambiguous` flags.
- Invoke the **committed** WP-C `compare_element_counts` (lane + schema unchanged) on the **experiments artifact only** — the sole sanctioned "probe touches WP-C" crossing.
- Verdict vocabulary: `agree` / `disagree` / `not_cross_checkable` / `benign_divergence` / `disagree_with_authority` (the last goes live for the first time when real catalog counts are supplied).
- Write: `experiments/ipcat_probe/artifacts/phase1c_<chip_id>.json`
```
{ "phase":"1C", "chip_id":..., "counts":[CountResult,...],
  "element_counts_input":{...schema-1.3.0...},
  "cardinality_verdicts":[{element_class,verdict,detail},...],
  "verdict":"PASS|PARTIAL|FAIL" }
```
- **PASS:** all three counted + classified & lane emits a verdict. **PARTIAL:** some UNAVAILABLE but correctly classified. **FAIL:** none obtainable/derivable, or lane errors.

---

## 5. Troubleshooting Guide

Every live-call fault is caught and mapped to **exit 3** with a **redacted category label** (`_classify_error` — type names + category only, never the raw message/token). No traceback escapes.

| Symptom (`note` category) | Likely cause | Operator action |
|---|---|---|
| `timeout after Ns` | Endpoint slow/hung; timeout too low | Confirm endpoint reachable; raise `IPCAT_PROBE_TIMEOUT`; retry. Path B worker thread is abandoned (daemon) — harmless for a read-only probe. |
| `tls_verification_failed (...)` | Server cert not trusted; MITM/proxy | **Do NOT disable TLS** (`verify=True` is a hard invariant). Fix the trust store / proxy CA; re-run. |
| `dns_failure (...)` | Hostname unresolvable | Check the URL host in `.mcp.json`; verify DNS/VPN; retry. |
| `connection_failed (...)` | Host down / port blocked / network | Verify egress + endpoint availability; retry. |
| `http_error (...)` | Non-2xx / auth rejected / bad response | Verify token validity + URL path; check server-side auth; **exit 3**. |
| `mcp_error (...)` | MCP transport/tool-layer error | Verify `ipcat-mcp-server` entry (`type`, `url`, `headers`); confirm the tool name is enumeration-only + allow-listed. |
| `call_failed (...)` | Novel/unclassified exception | Fail-safe generic; still redacted, still exit 3. Inspect category chain; extend `_classify_error` mapping later if a pattern emerges (nice-to-have, not now). |
| **Missing credentials** (`credential absent` / `config/token absent`) | Path B env var unset / Path A `.mcp.json` incomplete | Provision per §1.2; re-run `--check` to confirm present. Not an error — the probe reports absent and exits 3 by design. |
| **AMBIGUOUS** (`resolution.status`) | >1 identifier-field match | First-class terminal state: do **not** pick one; record all candidates; mark target UNVERIFIED; stop its 1C progression. Nord ambiguity ≠ Eliza ambiguity (independent). |
| **ABSENT** (`resolution.status`) | No identifier-field match on a **successful** enumeration | Legitimate only if the query was authoritative (N>0 other chips returned). If the enumeration failed/was prose, treat as exit-3 failure, **not** absent. Consider extending `IDENTIFIER_FIELDS` if the real schema names identifiers differently. |
| `UNSTRUCTURED` / exit 2 with `structured:false` | Response was prose, not JSON | Provisioned-but-unusable: investigate the tool/endpoint returning prose; do not advance to 1B. |

---

## 6. Final Operational Checklist (execute immediately after provisioning)

```
[ ]  0. Confirm mechanism chosen + provisioned (Path B or Path A-Option-C)   → §1.1
[ ]  1. Confirm credentials present (env var, or .mcp.json header)           → §1.2
[ ]  2. cd audio_bu_skill/experiments/ipcat_probe/                            → §1.3
[ ]  3. python test_probe_hardening.py            → Ran 22 tests ... OK       → §1.4
[ ]  4. python -O test_probe_hardening.py         → Ran 22 tests ... OK       → §1.4
[ ]  5. python probe.py --check                   → mechanism present, exit 0 → §2.1
[ ]  6. python probe.py --mechanism <A|B> --chip <NORD_ALIAS>                 → §2.2
        → exit 0 ? ── no ─→ STOP: §2.4 / §5, do not advance
              │ yes
[ ]  7. Phase-1A live PASS recorded (connected+structured+resolved)          → §2.3
[ ]  8. Phase-1B: resolve Eliza + re-confirm Nord (≥2 fields)                 → §3
[ ]  9. Write phase1b_<target>.json ; assign PASS/PARTIAL/FAIL               → §3.3–3.4
        → ≥1 target RESOLVED ? ── no ─→ STOP: record verdict, investigate
              │ yes
[ ] 10. Phase-1C: acquire 3 counts (direct→derived→unavailable)              → §4.1–4.4
[ ] 11. Run committed WP-C compare_element_counts on experiments input       → §4.5
[ ] 12. Write phase1c_<chip_id>.json ; record cardinality verdicts + verdict → §4.5
[ ] 13. Report: Phase-1A/1B/1C verdicts + first live cardinality result
```

**Boundary re-assertions true at every step:** `auth.json` never opened · TLS `verify=True` · read-only allow-list only · artifacts under `experiments/` only · no fabricated values · rollback = delete artifacts.

---

*Consolidation only. No code, no probe changes, no design changes, nothing committed or staged. Phase-0 frozen; probe inert until operator provisioning. The instant provisioning arrives, execute §6 top-to-bottom — no further planning required.*
