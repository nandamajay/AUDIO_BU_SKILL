# Nord Target Identification — Evidence Record

**Type:** Evidence only. **No code changes, no implementation, no probe changes, no commits.**
**Question:** Which live-catalog chip is the actual Audio BU Skill "Nord" target?
**Method:** Repository evidence + project docs + live `ip_catalog` cross-check. No guessing; every claim is cited.

---

## 0. Live catalog candidates (as enumerated 2026-07-14)

`chips_list_chips` returned 733 chips. The "Nord"-matching records:

| # | catalog `name` | catalog `alias` | catalog `id` |
|---|---|---|---|
| 1 | `AIC200 (NordDC)` | `nordschleife_ai200` | 927 |
| 2 | `NordDC_Q` | `norddc_q_1.0` | 1127 |
| 3 | `SA8797P (NordAU)` | `nordschleife_1.0` | 567 |
| 4 | `SA8797P (NordAU) v1.1` | `nordschleife_1.1` | 908 |
| 5 | `SA8797P (NordAU) v2` | `nordschleife_2.0` | 781 |

Eliza (the sibling target) resolves separately to `SM7750 (Eliza)` — not in scope here.

---

## 1. Candidate mapping table (candidate → target likelihood)

| Candidate | Product line | Is it the Audio BU "Nord" target? | Basis |
|---|---|---|---|
| **`SA8797P (NordAU)` family** (ids 567 / 908 / 781) | **NordAU** — Automotive; "NordAU" = **Nord A**uto**U**nit | ✅ **YES — this is the target SoC family** | Repo `targets/nord-iq10/profile.json:3,72` declares SoC = **"SA8797P (Nord / IQ-10 EVK/RRD)"**; all Nord DTS files are `nord-sa8797p.dtsi` |
| `AIC200 (NordDC)` (id 927) | **NordDC** — Data-Center AI accelerator (AIC = AI Card, "AIC200") | ❌ No | Different product (AI inference card, not an audio EVK); zero references anywhere in the repo |
| `NordDC_Q` (id 1127) | **NordDC** variant | ❌ No | Same NordDC data-center line; zero repo references |
| `SA8775P (LeMansAU)` (id 434) | LeMansAU — a **different** SoC | ❌ No (it is the **structural donor**, not the target) | Appears in repo only as the *reference* the unapplied ADSP patch was copied from — see §2.4 |

**The name collision is the whole trap:** "Nord" spans two unrelated Qualcomm product lines — **NordAU** (automotive, SA8797P) and **NordDC** (data-center AI, AIC200). The Audio BU Skill target is unambiguously **NordAU / SA8797P**.

---

## 2. Evidence for each candidate

### 2.1 `SA8797P (NordAU)` — **the target** (multiple independent citations)

- **Canonical target profile** — `targets/nord-iq10/profile.json`:
  - `:3`  → `"soc": "SA8797P (Nord / IQ-10 EVK/RRD)"`
  - `:72` → `soc.value = "SA8797P (Nord / IQ-10 EVK/RRD)"`
- **Device-tree files are SA8797P-named** — `profile.json:48,75`, `:169`:
  - `linux-nord/arch/arm64/boot/dts/qcom/nord-sa8797p.dtsi:1-16` (the SoC .dtsi)
  - `nord-iq10.dtsi`, `iq10-evk.dts` (board layer)
- **Task spec** — `targets/nord-iq10/qgenie_task_spec.json:3` → `"target": "nord-iq10"`; the audio commits target `nord-iq10.dtsi` / `iq10-evk.dts`.
- **Board** — `profile.json:80` board block ties SA8797P to the **IQ-10 EVK/RRD** with I²S codecs TI PCM1681 (DAC) + ADI ADAU1979 (ADC).
- **Prior IPCAT access spec already pinned it** — `docs/IPCAT_MCP_ACCESS_SPEC.md:129-131` lists the three SA8797P NordAU catalog rows and used `nordschleife_2.0` as the working Nord alias for live SWI queries on 2026-07-13.

### 2.2 `AIC200 (NordDC)` — not the target

- **Zero repository references.** A repo-wide grep for `aic200` / `norddc` returns no hits in any `targets/`, `docs/`, `state/`, or profile file (only appears now in the live catalog list).
- Product mismatch: AIC200 is a data-center AI inference card; the Audio BU Skill is a kernel-audio bring-up skill for an automotive audio EVK.

### 2.3 `NordDC_Q` — not the target

- Same NordDC data-center family; **zero repository references**. Ruled out on the same basis as 2.2.

### 2.4 `SA8775P (LeMansAU)` — the **donor**, explicitly *not* the target

This is the source of the `sa8775p` string in prior memory, and must be read correctly:

- `profile.json:155-160` names **"SA8775P (lemans)"** as the *"Direct structural donor"*: the unapplied Nord ADSP patch **reuses lemans'** compatible `qcom,sa8775p-adsp-pas` and firmware `qcom/sa8775p/adsp.mbn`.
- `profile.json:39,146` — the draft `RPMHPD_LCX/LMX` power-domains were *"copied structurally from the SA8775P lemans reference,"* and the patch's **own `FIXME(sa8797p-audio)` comment flags this as WRONG for Nord.**
- **Reading:** `sa8775p` is the compatible/firmware string *borrowed* by the port. The **silicon** is SA8797P. Querying the catalog for `sa8775p` would return the LeMans donor, not the Nord target.

> This reconciles the memory note [[nord-iq10-audio-facts]] ("firmware `sa8775p/adsp.mbn`"): that firmware name is the **donor artifact reused in the draft patch**, not the identity of the target chip. Target chip = SA8797P; donor firmware string = sa8775p.

---

## 3. Confidence assessment

| Claim | Confidence | Why |
|---|---|---|
| Target SoC is **SA8797P (NordAU)**, not NordDC/AIC200 | **Very High (≥0.98)** | Direct, repeated repo declaration (`profile.json:3,72`), SA8797P-named DTS files, IQ-10 EVK board evidence, and the prior access spec all agree. NordDC candidates have zero repo footprint. |
| SA8775P is the **donor**, not the target | **Very High (≥0.95)** | Profile explicitly labels it "structural donor" with a patch-internal FIXME warning it is wrong for Nord. |
| Which **catalog version** (v1.0 `567` / v1.1 `908` / v2 `781`) is the exact silicon | **Low–Medium (~0.5)** | The repo pins the SoC *family* ("SA8797P") but **never records a silicon revision**. Prior spec used `nordschleife_2.0` (v2) as a working default, not as an evidenced revision pin. |

---

## 4. Recommended canonical Nord chip

**Canonical target SoC: `SA8797P (NordAU)`.**

For live `ip_catalog` queries, the `chip` argument should be a NordAU alias:

- **Default working alias (recommended): `nordschleife_2.0`** — catalog id **781**, catalog name `SA8797P (NordAU) v2`.
  - Rationale: it is the **latest** SA8797P NordAU revision in the catalog and is the alias the prior access spec (`IPCAT_MCP_ACCESS_SPEC.md`) already exercised successfully. Absent a repo-pinned revision, "latest silicon revision of the confirmed SoC family" is the defensible default.
- **Family fallback for Phase-1B resolution:** treat all three (`nordschleife_1.0` / `_1.1` / `_2.0`) as the **NordAU SA8797P family**. The ≥2-field Nord re-confirm should assert `family = SA8797P / NordAU`, and record which specific revision answered — not hard-fail on a version that has no repo evidence.

**Explicitly excluded:** `AIC200 (NordDC)` (id 927) and `NordDC_Q` (id 1127) — different (data-center) product line. `SA8775P` — donor, not target.

---

## 5. Insufficient-evidence statement (what would pin the exact revision)

The **SoC family is fully resolved**; only the **exact silicon revision** (v1.0 vs v1.1 vs v2) is not pinned by current repo evidence. To close that last gap, one of the following is required — none of which can be guessed:

1. **A board/silicon revision marker** for the physical IQ-10 EVK/RRD unit under bring-up (e.g. an EVK BOM/rev sticker, a `qcom,board-id`/`msm-id` in an applied DTS, or a `socinfo` fuse readout). None is present in the repo.
2. **A downstream/program statement** naming the taped-out SA8797P revision for the IQ-10 audio program (e.g. a JIRA/HPG reference; the existing `QSTABILITY-24906579` note in memory concerns ADSP boot logs, not silicon rev).
3. **A live `socinfo`/`chips_get_latest_chip_version` correlation** tying the EVK's reported chip version to one of catalog ids 567 / 908 / 781.

Until one of those exists, **use `nordschleife_2.0` (v2, latest) as the working default and record the family as SA8797P/NordAU** — do not assert a specific revision as evidenced.

---

## 6. One-line verdict

**The Audio BU "Nord" target is `SA8797P (NordAU)` — catalog family ids 567/908/781, working alias `nordschleife_2.0` (id 781, latest). `AIC200/NordDC_Q` are a different data-center product; `SA8775P` is the donor, not the target. Only the exact silicon revision remains unpinned by repo evidence.**

---

*Evidence only. No code, no probe changes, no implementation, nothing committed. Live catalog values were read read-only via `chips_list_chips`; all repository claims are cited to file:line.*
