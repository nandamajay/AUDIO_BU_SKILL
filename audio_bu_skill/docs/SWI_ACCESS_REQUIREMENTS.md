# SWI Access Requirements — Operator Readiness Package

**Purpose:** Give the operator everything needed to provision and *validate* SWI/IPCAT catalog access, so the SWI Probe can move from **No-Go** to **Go**. This is a checklist and decision guide — **not** an implementation. No Track D, no `catalog_count` population, no code.

**Companion:** `docs/SWI_PROBE_PLAN.md` (the pre-flight that produced the No-Go and the D1–D5 dependency list).

---

## 1. Executive Summary

**Why SWI is needed.** The Cardinality Authority (WP-C) cross-checks how many hardware instances of each audio element class exist, across independent enumeration lanes (`dt` / `evidence` / `proposal`). Pre-SWI, no lane is *authoritative* — when lanes are single or disagree, WP-C can only report `not_cross_checkable`. The SWI/IPCAT catalog is the one chip-keyed source that can enumerate real silicon instances and act as ground truth (the `catalog` lane).

**What capability it unlocks.** A populated `catalog` lane converts today's ambiguous verdicts into decisive ones:
- The `<ELIZA-SOC>` `soundwire_master` "1 or 2 masters" ambiguity (`evidence=3` vs `proposal=1`) becomes a settled integer with provenance.
- The `<NORD-SOC>` `dsp_subsystem_instance` enumeration gets an authoritative value instead of a nearest-target-copied one.
- Prior `not_cross_checkable` rows upgrade automatically to `agree` (lanes concur with authority) or `disagree_with_authority` (a review signal, never a hard failure).

**Why WP-C is already ready.** The consumer side is complete and committed (`28f2f07`, tag `foundation-complete-pre-swi`):
- The schema `catalog` lane already exists (schema 1.3.0 / Fix A), declared up front and emitted `null` pre-SWI so filling it is purely additive.
- WP-C's comparison core already branches on `catalog` presence and treats it as the authority; the rendering already handles the resulting verdicts.
- This is proven inert-but-ready by the committed tests `test_agree_with_authority_post_swi` and `test_disagree_with_authority_post_swi`.

**Net:** the *only* missing piece is host access. **No framework work, no schema change, and no `cardinality.py` change is required** to consume `catalog_count` once it can be produced.

---

## 2. Missing Dependencies (D1–D5)

Reproduced exactly as identified in the SWI Probe pre-flight:

| # | Dependency | Nature | Owner / how obtained |
|---|---|---|---|
| **D1** | `ipcat_client` library installed on the run host | Python package | Operator provisions (same library EVA/camera_dtsi use); do **not** speculatively pip-install without approval |
| **D2** | IPCAT credentials, **env-var-first** (`IPCAT_USER`/`IPCAT_PASSWORD` or `IPCAT_TOKEN`) | Secret/config | **User-provided only** — never scraped, never harvested from history/env dumps |
| **D3** | Network reachability from this host to the IPCAT backend | Ops/network | Operator confirms the run environment can reach the service |
| **D4** | Confirmation that `<NORD-SOC>` and `<ELIZA-SOC>` are **populated** in the SWI catalog | Empirical (one `chips.get_chips()` call) | Answerable only *after* D1–D3; the first read-only probe |
| **D5** | Approval to add a runtime dependency / access mode to the project | Decision | User — this is the Track-D-adjacent access-mechanism decision |

**Gating order:** D1–D3 are provisioning prerequisites; D4 is the empirical presence check that D1–D3 unlock; D5 is the go-ahead to actually build against it (Track D — out of scope here).

---

## 3. Access Validation Checklist

The operator confirms each item before declaring access ready. Each is a simple present/absent check — **no values, no secrets, no full-environment dumps.**

- [ ] **Client availability** — `ipcat_client` imports successfully on the run host (resolves D1).
- [ ] **Credential availability** — the env-var-first credentials are set in the run environment; confirm **presence only** (SET/unset), never print values (resolves D2).
- [ ] **Network reachability** — the host can reach the IPCAT backend endpoint (resolves D3).
- [ ] **Chip presence validation** — `<NORD-SOC>` and `<ELIZA-SOC>` each resolve to a catalog chip entry, and their audio blocks are enumerable (resolves D4).

A single unchecked box = **not ready** → No-Go remains in force.

---

## 4. Minimal Read-Only Probe Procedure (high-level only)

Non-mutating, chip-keyed lookups only. No writes, no side effects, no implementation detail, no credentials in any artifact.

1. **Confirm the client loads.** Verify `ipcat_client` is importable in the run environment.
2. **Confirm credentials are present.** Confirm the env-var-first credential path is populated (presence check only).
3. **Resolve chips.** Perform the one catalog listing that maps each target alias to a chip entry. This same call is the go/no-go presence probe — if a target SoC is absent, stop for that target.
4. **Enumerate audio blocks per resolved chip.** Read-only module enumeration for each present target; count blocks matching the relevant element-class name patterns (e.g. SoundWire-master, DSP-subsystem, LPASS-macro).
5. **Record counts + provenance tokens only.** Capture the integer per class and a non-confidential provenance reference — in a throwaway/job-scoped context, never a committed artifact.

> This procedure is descriptive. It is **not** to be implemented as project code in this task; when access is ready it is executed in a disposable context to answer D4, and only then (with D5 approval) does any implementation plan follow.

---

## 5. Expected Success Outputs (what proves access works)

Access is proven working when **all** of the following are observed:

- **Client import succeeds** — no `ModuleNotFoundError`.
- **Credentialed call returns without auth prompt** — the env-var-first path authenticates non-interactively (no `getpass` fallback triggered).
- **Chip resolution succeeds** — both `<NORD-SOC>` and `<ELIZA-SOC>` resolve to catalog chip entries (or a definitive "absent" answer for either).
- **Block enumeration returns typed rows** — a read-only module query yields structured entries (block name + count), not prose and not an error.
- **Countable result** — at least the flagship class (`soundwire_master`) yields a concrete integer for at least one target.

The minimal proof-of-life is: *client imports → credentialed chip listing succeeds → one target's audio blocks are enumerable and countable.*

---

## 6. Go / No-Go Decision Tree

```
Q1. Does ipcat_client import on the run host?            (D1)
    NO  → NO-GO. Provision the client. Stop.
    YES → continue.

Q2. Are env-var-first credentials present (presence only)? (D2)
    NO  → NO-GO. Operator supplies credentials (never scraped). Stop.
    YES → continue.

Q3. Does a credentialed chip listing succeed over the network? (D3)
    NO  → NO-GO. Resolve reachability/auth. Stop.
    YES → continue.

Q4. Are our SoCs populated in the catalog?                (D4)
    NEITHER present     → NO-GO. Catalog cannot help either target today.
    ELIZA only present  → PARTIAL-GO. soundwire_master authority for <ELIZA-SOC>;
                          <NORD-SOC> DSP-base gap stays a KB/reviewer concern.
    BOTH present        → GO (pending D5). Full authority path viable.

Q5. Is there approval to add the access mode / dependency? (D5)
    NO  → HOLD. Access validated, but do not build until approved.
    YES → Proceed to write the exact Track-D plan for approval (still no code
          until that plan is approved).
```

**Terminal states:**
- **NO-GO** — any of Q1–Q3 fails, or Q4 finds neither SoC. Access not usable; remain on current pre-SWI behavior.
- **PARTIAL-GO** — Q4 finds Eliza only. Scope any future work to `<ELIZA-SOC>`.
- **GO (pending approval)** — Q1–Q4 pass; awaiting D5 to author the Track-D plan.

---

## 7. Recommended Next Step

**Operator provisions and validates access — no project code changes involved.**

1. Provision **D1–D3**: install `ipcat_client`, set env-var-first IPCAT credentials (user-provided), confirm network reachability.
2. Run the **minimal read-only probe** (§4) in a disposable/job-scoped context to answer **D4** — are `<NORD-SOC>` and `<ELIZA-SOC>` populated, and are their audio blocks countable?
3. Walk the **§6 decision tree** with that result and **return here**:
   - **GO / PARTIAL-GO** → `docs/SWI_PROBE_PLAN.md` is upgraded to a Go and the *exact* Track-D implementation plan is written for approval (still no code until approved).
   - **NO-GO** → remain on current behavior; the catalog defers until the availability gap is resolved.

Until access is validated, the SWI Probe stays **No-Go** and no implementation proceeds.

---

## Confidentiality Safeguards

- SoC identifiers appear only as `<NORD-SOC>` / `<ELIZA-SOC>` placeholders. No part numbers, LD-series/schematic references, firmware paths, `/local/mnt` paths, kernel hashes, or IPCAT doc IDs.
- Credentials remain **env-var-first, user-provided, never scraped**; validation checks report **presence only** (SET/unset), never values, never the full environment, never shell history.
- Any future catalog output is target-artifact/confidential and stays uncommitted; only non-confidential provenance tokens would ever appear in citations.

---

*Documentation only. No code, no `catalog_count` population, no Track D, no source changes, no commits.*
