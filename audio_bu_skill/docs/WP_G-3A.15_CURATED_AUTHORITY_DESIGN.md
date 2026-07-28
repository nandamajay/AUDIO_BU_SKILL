# WP G-3A.15 — Curated Human Authority Input Path

## Design Document — DESIGN ONLY (no implementation)

**Status:** DESIGN REVIEW  
**Author:** Ajay Kumar Nandam  
**Date:** 2026-07-28  
**Depends on:** A-narrow (landed), H-1 (landed), WP-64 (landed), WP-69 (design done)  
**Blocks:** WP-69 implementation, board_variant attestation, SCMI/OCTONARY curation

---

## The Load-Bearing Question

> How does a human-attested fact reach the generator WITHOUT adding a new
> authority-strength enum value, and WITHOUT feeding
> `gc["cross_verification"]["rows"]` or TrustedFacts?

**Answer:** Via a sidecar file (`curated_overrides.json`) that the projector
reads as a SECOND input alongside `gc`. Curated values flow into FactRecords
with `authority.strength = "KB_RULE"` (existing enum) and a NEW
`authority.origin = "reviewer_curated"`. The fact lands in the template with
`ncc_state = "ATTESTED"`, which `_template_value()` accepts. It NEVER enters
`gc["cross_verification"]["rows"]` or `TrustedFacts` — it bypasses
cross-verification entirely and enters the pipeline AFTER projection, as a
template-level overlay.

The critical insight: `authority.strength` is a closed enum governing
TRUST LEVEL. `authority.origin` is an open string describing WHERE the
authority came from. Adding a new origin does not violate the closed-enum
constraint because origins are not enumerated — they are provenance labels.

---

## §1 — Problem Framing: Facts That Require Curated Authority

### The four known cases

| Fact | Template path | Why NOT machine-discoverable |
|------|--------------|------------------------------|
| **board_variant** | `board_metadata.board_variant` | IPCAT has no concept of board variants (EVK/RRD/RIDE). Kernel DT `compatible` strings (`qcom,nord`, `qcom,iq10`) name the PLATFORM, not the BOARD VARIANT. Schematic PDFs name variants but require human interpretation. The only provenance for "this board is an EVK" is a human who looked at the silkscreen/schematic and attested it. |
| **SCMI power index** | `buses[].scmi_power_index` | SCMI power domain indices are assigned by firmware team at integration time. They do not appear in IPCAT, DT, or kernel source — they appear in firmware headers and SCMI transport tables that require human correlation to the audio subsystem. |
| **OCTONARY binding** | `codecs[].binding_type` | Whether a codec is wired as OCTONARY (8-channel TDM) or QUATERNARY depends on the board-level routing decision. IPCAT describes the codec's CAPABILITY; the actual binding choice is a board design decision attested by the schematic engineer. |
| **sndcard compatible** | `board_metadata.compatible` | The DT compatible string (`qcom,nord-iq10-sndcard`) is a NAMING CONVENTION, not a hardware fact. It's assigned by the BSP team and does not exist until someone writes the DTS. It cannot be derived from IPCAT, kernel source, or schematic — it's a human naming decision. |

### Common pattern

All four share the same structure: a fact whose VALUE is knowable to a human
with access to schematics/firmware/BSP decisions, but whose VALUE has no
automated provenance pipeline (no IPCAT API, no kernel DT node, no parser).

### Why existing authority strengths are insufficient alone

- `IPCAT_DIRECT` / `IPCAT_DERIVED` — requires an IPCAT MCP query that returns the value. These facts have no IPCAT representation.
- `KB_RULE` — a derived fact based on known inference rules (e.g. "SA8775P → sa8775p family"). Used pragmatically for human curation (see Appendix A): the origin field (`"reviewer_curated"`) carries the real trust distinction, while the strength satisfies the closed-enum validation. This is NOT a claim that human attestation is trust-equivalent to deterministic machine inference.
- `UNAVAILABLE` — means NO authority could be found. Once a reviewer attests, it's no longer UNAVAILABLE.

---

## §2 — Candidate Designs

### Option A: Sidecar Override File

**Mechanism:** A file `targets/<target>/curated_overrides.json` read by the
projector as a second input. Each entry is a FactRecord-shaped patch keyed
by template path (e.g. `"board_metadata.board_variant"`).

**Schema:**
```json
{
  "$schema_version": "1.0.0",
  "target": "nord-iq10",
  "overrides": {
    "board_metadata.board_variant": {
      "value": "IQ10-EVK",
      "authority": {
        "strength": "KB_RULE",
        "origin": "reviewer_curated"
      },
      "citations": [
        "Schematic LD20-94440 rev A, sheet 1, title block: 'IQ10-EVK'",
        "Attested by: ajay.nandam@oss.qualcomm.com, 2026-07-28"
      ],
      "attestation": {
        "attested_by": "ajay.nandam@oss.qualcomm.com",
        "timestamp": "2026-07-28T14:30:00+05:30",
        "evidence": "Schematic LD20-94440 rev A, IQ10_RRD_IO_Mapping.xlsx",
        "reviewed_by": null
      }
    }
  }
}
```

**Where it's read:** The projector's `project()` function gains an optional
`curated_overrides: dict | None` parameter. After building each FactRecord
via `_fact_from_row()` / `_derive_pinctrl_state()`, if a curated override
exists for that key path AND the automated result is NOT_ATTESTED, the
curated value replaces the FactRecord.

**How it flows to the generator:** The template JSON (output of projector)
carries the curated FactRecord. `_template_value()` sees
`ncc_state == "ATTESTED"` and returns the value. No change to generation
code.

**Disclosure-only guarantee:** The curated value enters the TEMPLATE
(post-projection artifact), never `gc["cross_verification"]["rows"]`. The
projector READS `gc["cross_verification"]["rows"]` but never writes them.
The curated_overrides.json is a PARALLEL input, not a modification of gc.

**Audit trail:** The `attestation` sub-object in the sidecar file IS the
audit record. Validated at load time (schema check).

**Failure/degradation:**
- File missing → no overrides applied → all automated results stand (silent NOT_ATTESTED).
- File malformed → loud error (projector raises ValueError, never fabricates).
- Override for a key that is NOT_ATTESTED by automation → curated fills (gap-fill).
- Override for a key that is ATTESTED by automation with SAME value → automation wins, agreement noted.
- Override for a key that is ATTESTED by automation with DIFFERENT value → CONTRADICTION: loud disclosure, reviewer_required=true, no value emitted (see §4).

**Hard constraint satisfaction:**
1. No new authority-strength: uses `KB_RULE` ✓
2. No cross_verification/TrustedFacts pollution: enters template only ✓
3. FactRecord shape: is a FactRecord ✓
4. Auditable: attestation sub-object ✓
5. Honest degradation: missing/malformed → NOT_ATTESTED ✓
6. Deterministic: same file + same gc → same template bytes ✓

### Option B: Reviewer-Signed FactRecord Patches (Merged at Projection)

**Mechanism:** Same as Option A in data flow, but the override file is
cryptographically signed (GPG or SSH signature) and the projector validates
the signature before applying. The override is a "FactRecord patch" rather
than a freeform JSON.

**Schema:** Same as Option A, plus:
```json
{
  "signature": {
    "method": "ssh-ed25519",
    "signer": "ajay.nandam@oss.qualcomm.com",
    "sig": "<base64-encoded-detached-signature>",
    "signed_payload_sha256": "<hex>"
  }
}
```

**Differences from Option A:**
- Adds a signature verification step at load time.
- Requires a key registry (which public keys are trusted for which targets).
- Higher implementation cost.
- Stronger non-repudiation (the attestor cannot deny having signed).

**Hard constraint satisfaction:** Same as A, plus stronger audit (signature).

**Risk:** Over-engineered for Phase-3A scope. Key management is a separate
infrastructure concern. The simpler audit-by-citation (Option A) is
sufficient when the user base is small (1-3 engineers per target).

### Option C: Direct Template JSON Edit

**Mechanism:** A human edits `audio_hardware_template.json` directly,
changing a FactRecord's `value` and `ncc_state` from NOT_ATTESTED to
ATTESTED.

**Why rejected:**
- Breaks the projector's pure-function invariant: template is a COMPUTED
  OUTPUT of `project(gc)`. If a human edits it, re-running the projector
  would OVERWRITE the curation.
- No separation of concerns: curated vs. automated facts are
  indistinguishable in the template JSON.
- No audit trail: git blame shows who edited, but not WHAT EVIDENCE
  justified the edit.
- Merge conflicts: projector re-runs conflict with hand edits.
- Violates "template is never authority" (H-1 architectural invariant).

**Hard constraint satisfaction:**
1. No new authority-strength: could use KB_RULE ✓
2. No cross_verification pollution: ✓ (template doesn't feed back)
3. FactRecord shape: ✓
4. Auditable: ✗ (git blame is weak evidence; no structured attestation)
5. Honest degradation: ✗ (projector re-run would silently overwrite)
6. Deterministic: ✗ (result depends on whether human edit happened before
   or after projector run — race condition)

**REJECTED.**

---

## §3 — The Origin-vs-Strength Distinction

### Structural analysis

```
authority: {
    "strength": "KB_RULE",       ← CLOSED enum (4 values). Governs TRUST LEVEL.
    "origin":   "reviewer_curated"  ← OPEN string. Governs PROVENANCE SOURCE.
}
```

**`strength`** answers: "How much should I trust this fact?"
- `IPCAT_DIRECT` — tool returned it directly
- `IPCAT_DERIVED` — inferred from tool output
- `KB_RULE` — derived by a knowledge-base inference rule
- `UNAVAILABLE` — no authority could be found

**`origin`** answers: "Where did the authority come from?"
- `"ipcat_swi"` — from SWI register lookup
- `"ipcat_gpio"` — from GPIO map lookup
- `"kernel_dt"` — from kernel device-tree parser (A-narrow)
- `"reviewer_curated"` — from a human reviewer's attestation (G-3A.15)
- `"none"` — no origin (UNAVAILABLE strength)

The key insight: **KB_RULE is a pragmatic reuse, not a trust equivalence
claim** (see Appendix A for the full argument). A human schematic-read is
NOT equivalent in trust to a deterministic software rule — but the closed
enum forces us to pick from `{IPCAT_DIRECT, IPCAT_DERIVED, KB_RULE,
UNAVAILABLE}`. KB_RULE is the least-wrong fit: it covers "derived from a
knowledge source" and the `authority.origin = "reviewer_curated"` field
carries the real trust discriminator. Every reviewer-facing surface MUST
display the origin tag (Appendix B) so no one mistakes it for machine
inference.

### How gates treat a reviewer_curated fact

1. **`is_open(track, subject)`** (`model.py:213-237`): reads
   `_GATING_OPEN_VERDICTS = {"MATCH", "PARTIAL_MATCH"}` from
   `TrustedFacts.rows`. A curated fact NEVER enters `TrustedFacts.rows`
   (it enters the template, not gc). Therefore `is_open()` CANNOT see it.
   Gate behavior is UNCHANGED.

2. **WP-64 firewall**: the firewall guarantees that `contributes_rows`
   (generation-time disclosures) do not feed back into
   `gc["cross_verification"]["rows"]`. A curated fact follows a DIFFERENT
   path entirely: `curated_overrides.json` → projector → template →
   `_template_value()` → emitted bytes. It never touches
   `contributes_rows` either (it's not a disclosure — it's a value).

3. **Cross-verification**: the crossverify pass runs BEFORE projection.
   `gc["cross_verification"]["rows"]` is already finalized when the
   projector reads them. The curated_overrides.json is read at projection
   time — it is structurally impossible for its contents to flow backward
   into `gc["cross_verification"]["rows"]`.

### Proof: a curated fact CANNOT open a cross-verification gate

```
Data flow (time-ordered):

  1. Onboarding → gc["cross_verification"]["rows"]  (FROZEN after step 1)
  2. Projector reads gc + curated_overrides.json → template
  3. Generation reads template via _template_value()
  4. Generation reads TrustedFacts (from gc["cross_verification"]["rows"])
     for is_open() gate decisions

curated_overrides.json enters at step 2.
TrustedFacts is constructed from step 1's output.
There is NO path from step 2 → step 1 or step 2 → step 4's input.
```

QED: a curated value cannot influence `is_open()` because it never enters
the data structure that `is_open()` reads.

---

## §4 — Audit + Trust Model

### Audit record structure

Every override entry carries an `attestation` sub-object:

```json
{
  "attested_by": "ajay.nandam@oss.qualcomm.com",
  "timestamp": "2026-07-28T14:30:00+05:30",
  "evidence": "Schematic LD20-94440 rev A, title block; IQ10_RRD_IO_Mapping.xlsx row 14",
  "target": "nord-iq10",
  "reviewed_by": "second.reviewer@oss.qualcomm.com",
  "review_date": "2026-07-29T10:00:00+05:30"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `attested_by` | yes | Email of the person who asserted the value |
| `timestamp` | yes | ISO-8601 datetime of attestation |
| `evidence` | yes | Human-readable citation (schematic, spec, email, ticket) |
| `target` | yes | Must match the target directory name |
| `reviewed_by` | no | Second-party reviewer (for dual-attestation workflow) |
| `review_date` | no | When the second reviewer confirmed |

### How a reviewer marks a fact

1. Reviewer creates/edits `targets/<target>/curated_overrides.json`.
2. Fills in `value`, `authority` (`KB_RULE` / `reviewer_curated`), `citations`, and `attestation`.
3. Commits the file with DCO sign-off (git provenance).
4. On next projector run: override is loaded, validated, applied.

### Validation at load time

The projector validates:
- `$schema_version` is known.
- `target` matches the projector's `target_name` argument.
- Every override key is a legal template path.
- `authority.strength` is in `AUTHORITY_STRENGTHS` (must be `KB_RULE` for curated).
- `attestation.attested_by` is non-empty.
- `attestation.timestamp` parses as ISO-8601.
- `attestation.evidence` is non-empty.
- `value` is not None (a curated override with null value is nonsensical).

Failure on any check: `ValueError` with the specific violation. The
projector does NOT degrade silently.

### Conflict resolution: GAP-FILL vs AGREEMENT vs CONTRADICTION

Three cases arise when a curated override targets a template path that
automation ALSO populated. The resolution depends on whether automation
left the slot empty (NOT_ATTESTED) or filled it (ATTESTED):

#### Case 1 — GAP-FILL (automation NOT_ATTESTED, curated provides value)

Curated value fills the gap. The FactRecord is created with:
- `value` = curated value
- `ncc_state` = `"ATTESTED"`
- `authority` = `{"strength": "KB_RULE", "origin": "reviewer_curated"}`
- `citations` = curated citations
- `reviewer_required` = `false`

This is the primary use case: curation exists to fill what automation
cannot reach.

#### Case 2 — AGREEMENT (automation ATTESTED value X, curated value X, X == X)

Automation wins (it is the fresher, re-derivable source). The curated
override is noted as an AGREEMENT disclosure in `not_attested_disclosures`:

```json
{
  "reason": "curated_agrees_with_automation",
  "curated_value": "IQ10-EVK",
  "curated_origin": "reviewer_curated",
  "curated_attestation": { ... }
}
```

No behavioral change — the automated FactRecord stands. The agreement
disclosure is informational: it means a human independently confirmed the
automated result (positive signal for confidence).

#### Case 3 — CONTRADICTION (automation ATTESTED value X, curated value Y, X != Y)

**Neither silently wins.** A contradiction between a cited human
schematic-read and an automated parser is exactly the silent-wrong-output
failure mode this system is designed to catch. Resolution:

The FactRecord is emitted with:
- `value` = `None` (NO value chosen — conflict is unresolved)
- `ncc_state` = `"NOT_ATTESTED"` (degradation: conflict = no attestation)
- `reviewer_required` = `true`
- `not_attested_disclosures` = a CONFLICT disclosure:

```json
{
  "reason": "CONFLICT_AUTOMATION_VS_CURATED",
  "automated_value": "IQ10-RRD",
  "automated_origin": "ipcat_swi",
  "automated_citations": ["..."],
  "curated_value": "IQ10-EVK",
  "curated_origin": "reviewer_curated",
  "curated_citations": ["Schematic LD20-94440 rev A"],
  "curated_attestation": { ... },
  "resolution": "UNRESOLVED — requires human triage"
}
```

**Behavioral effect:** Because `ncc_state = "NOT_ATTESTED"` and
`value = None`, `_template_value()` returns None → the generator falls
back to the FIXME literal. The conflict is LOUD: `reviewer_required=true`
surfaces in any H-2 dashboard or review pass, and the disclosure carries
both values with citations for triage.

**Why not let automation win silently:** A contradiction means one of two
things: (a) the automated parser has a bug, or (b) the human read the
schematic wrong. Both demand investigation. Silently picking automation
and burying the curated value in a disclosure risks exactly the failure
mode we designed provenance tracking to prevent — wrong output with no
visible signal.

#### Summary table

| Automation state | Curated state | Values | Resolution |
|-----------------|---------------|--------|------------|
| NOT_ATTESTED | provides value | — | **GAP-FILL**: curated fills |
| ATTESTED (X) | provides X | X == X | **AGREEMENT**: automation wins, curated noted |
| ATTESTED (X) | provides Y | X != Y | **CONTRADICTION**: loud, reviewer_required, no value emitted |

Curation is a FALLBACK for gaps and a SIGNAL for contradictions — never
a silent override.

#### CONTRADICTION implies intentional FIXME regression

A field that previously emitted a real value (via GAP-FILL curation) MAY
regress to a FIXME literal once automation lands a CONTRADICTING ATTESTED
value. This is **INTENDED**, not a bug:

- A contradicted fact has NO trustworthy value. Emitting either the
  automated or the curated side would be GUESSING — and guessing wrong
  silently is the failure mode this entire provenance system exists to
  prevent.
- The FIXME regression IS the loud signal. It makes the contradiction
  visible in generated output, in CI diffs, and in review passes.
- This regression MUST NOT be "fixed" later by auto-preferring automation
  or auto-preferring curation. The ONLY resolution is human triage: a
  reviewer investigates, determines which value is correct, and either
  (a) updates the curation to match automation (removes contradiction), or
  (b) files a bug against the automated parser. Until triage completes,
  the field stays FIXME.

**Lifecycle example:**
1. Automation leaves `board_variant` NOT_ATTESTED (no parser can derive it).
2. Reviewer curates `board_variant = "IQ10-EVK"` (GAP-FILL) → emits `model = "IQ10-EVK"`.
3. Later, an improved parser ATTESTS `board_variant = "IQ10-RRD"` (contradicts curation).
4. CONTRADICTION fires → `board_variant` regresses to NOT_ATTESTED → emits `model = "FIXME(board_variant): NOT_ATTESTED"`.
5. Reviewer triages: discovers the parser was reading a stale DT node. Updates curation to match. Contradiction resolves → GAP-FILL fires again → `model = "IQ10-EVK"`.

The regression at step 4 is the system working correctly: it refused to
guess when two authorities disagreed.

---

## §5 — Firewall Regression Test Design

### Test 1: Curated value never enters cross_verification.rows

```python
def test_curated_value_never_in_cross_verification_rows():
    """A curated override MUST NOT appear in gc['cross_verification']['rows']."""
    gc = {"cross_verification": {"rows": []}}
    overrides = {
        "board_metadata.board_variant": {
            "value": "IQ10-EVK",
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            ...
        }
    }
    result = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    # gc MUST be unchanged — no new rows
    assert gc["cross_verification"]["rows"] == []
    # The curated value IS in the template
    assert result.template.board_metadata["board_variant"].value == "IQ10-EVK"
```

### Test 2: Curated value never enters TrustedFacts

```python
def test_curated_value_never_in_trusted_facts():
    """A curated override in the template MUST NOT influence TrustedFacts."""
    template = load_nord_template_with_curated_board_variant()
    facts = build_trusted_facts_from_gc(gc)
    # TrustedFacts built from gc only — template not consulted
    assert not any(
        r.subject == "board_variant" and r.verdict == "MATCH"
        for r in facts.rows
    )
```

### Test 3: No new authority-strength enum value

```python
def test_authority_strength_enum_unchanged():
    """AUTHORITY_STRENGTHS must contain exactly 4 values (closed)."""
    from orchestrator.reasoning.crossverify_model import AUTHORITY_STRENGTHS
    assert AUTHORITY_STRENGTHS == frozenset(
        {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
    )
```

### Test 4: Missing/malformed asymmetry (overview)

See Tests 9 and 10 for the detailed implementations.
- Missing file → silent NOT_ATTESTED (honest degradation, not an error).
- Malformed file → loud ValueError (bug in curation process, never fabricate).
- Rationale: see Appendix C.

### Test 5: Byte-determinism with curated input

```python
def test_byte_determinism_with_curation():
    """Same curated input + same gc → same template bytes."""
    gc = {"cross_verification": {"rows": []}}
    overrides = {...}  # fixed curated data
    r1 = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    r2 = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    assert r1.template.to_dict() == r2.template.to_dict()
```

### Test 6: Curated override is visibly tagged reviewer_curated

```python
def test_curated_origin_tagged_in_template():
    """A curated fact's authority.origin MUST be 'reviewer_curated'."""
    gc = {"cross_verification": {"rows": []}}
    overrides = {...}
    result = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    bv = result.template.board_metadata["board_variant"]
    assert bv.authority["origin"] == "reviewer_curated"
    assert bv.authority["strength"] == "KB_RULE"
```

### Test 7 (NEGATIVE): Attempted cross-verification poisoning

```python
def test_negative_curated_cannot_poison_cross_verification():
    """NEGATIVE FIXTURE: a malicious override targeting cross_verification.rows.

    Even if someone crafts overrides with 'inject_into_rows: true' or any
    other creative field, it MUST NOT appear in gc['cross_verification']['rows'].
    """
    gc = {"cross_verification": {"rows": [{"track": "T1", "subject": "existing"}]}}
    # Malicious override: attempts to inject a row
    overrides = {
        "board_metadata.board_variant": {
            "value": "MALICIOUS",
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            "inject_into_rows": True,  # <- creative attack vector
            "row_to_inject": {"track": "T5", "subject": "board_variant", "verdict": "MATCH"},
            ...
        }
    }
    result = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    # gc STILL has only the original row
    assert len(gc["cross_verification"]["rows"]) == 1
    assert gc["cross_verification"]["rows"][0]["subject"] == "existing"
```

### Test 8: CONTRADICTION — automation and curation disagree

```python
def test_contradiction_emits_loud_conflict():
    """When automation ATTESTED X and curation provides Y (X != Y),
    the result MUST be NOT_ATTESTED with reviewer_required=true and
    a CONFLICT disclosure carrying both values.
    """
    gc = {
        "cross_verification": {
            "rows": [
                # Automation ATTESTED board_variant = "IQ10-RRD"
                {"track": "T5", "subject": "board_variant", "verdict": "MATCH",
                 "value": "IQ10-RRD", "origin": "ipcat_swi"}
            ]
        }
    }
    overrides = {
        "board_metadata.board_variant": {
            "value": "IQ10-EVK",  # DIFFERENT from automation's "IQ10-RRD"
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            "citations": ["Schematic LD20-94440 rev A"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T14:30:00+05:30",
                "evidence": "Schematic LD20-94440 rev A",
                "target": "test"
            }
        }
    }
    result = project(gc, target_name="test", run_id="r", curated_overrides=overrides)
    bv = result.template.board_metadata["board_variant"]

    # NOT_ATTESTED — conflict is unresolved
    assert bv.ncc_state == "NOT_ATTESTED"
    assert bv.value is None
    assert bv.reviewer_required is True

    # Disclosure carries BOTH values
    assert len(bv.not_attested_disclosures) >= 1
    conflict = bv.not_attested_disclosures[0]
    assert conflict["reason"] == "CONFLICT_AUTOMATION_VS_CURATED"
    assert conflict["automated_value"] == "IQ10-RRD"
    assert conflict["curated_value"] == "IQ10-EVK"
```

### Test 9: Missing curated_overrides.json → silent NOT_ATTESTED

```python
def test_missing_curation_file_yields_not_attested():
    """No curated_overrides.json file → board_variant stays NOT_ATTESTED.
    This is the honest degradation path: absent curation is not an error.
    """
    gc = {"cross_verification": {"rows": []}}
    result = project(gc, target_name="test", run_id="r", curated_overrides=None)
    bv = result.template.board_metadata["board_variant"]
    assert bv.ncc_state == "NOT_ATTESTED"
    assert bv.value is None
    # No error raised — silent degradation is correct for MISSING file
```

### Test 10: Malformed curated_overrides.json → loud ValueError

```python
def test_malformed_curation_raises_valueerror():
    """Malformed curated_overrides raises ValueError immediately.
    Never fabricates, never silently degrades.
    """
    gc = {"cross_verification": {"rows": []}}

    # Case A: null value (nonsensical)
    overrides_null = {"board_metadata.board_variant": {
        "value": None,
        "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
        "attestation": {"attested_by": "x", "timestamp": "2026-01-01", "evidence": "e", "target": "test"}
    }}
    with pytest.raises(ValueError, match="null value"):
        project(gc, target_name="test", run_id="r", curated_overrides=overrides_null)

    # Case B: missing attestation.evidence
    overrides_no_evidence = {"board_metadata.board_variant": {
        "value": "IQ10-EVK",
        "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
        "attestation": {"attested_by": "x", "timestamp": "2026-01-01", "evidence": "", "target": "test"}
    }}
    with pytest.raises(ValueError, match="evidence"):
        project(gc, target_name="test", run_id="r", curated_overrides=overrides_no_evidence)

    # Case C: wrong target
    overrides_wrong_target = {"board_metadata.board_variant": {
        "value": "IQ10-EVK",
        "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
        "attestation": {"attested_by": "x", "timestamp": "2026-01-01", "evidence": "e", "target": "WRONG"}
    }}
    with pytest.raises(ValueError, match="target"):
        project(gc, target_name="test", run_id="r", curated_overrides=overrides_wrong_target)
```

### Test 11: WP-69 curated board_variant changes ONLY the model line

```python
def test_wp69_curated_board_variant_changes_only_model_line():
    """When board_variant is curated to 'IQ10-EVK', the emitted DTSI changes
    ONLY the 'model = ...' line. No other bytes move.

    Proves the curated value's blast radius is precisely one interpolation point.
    """
    facts = _clean_nord_facts()

    # Baseline: NOT_ATTESTED template → FIXME literal in model line
    template_not_attested = load_nord_template()
    result_baseline = generate_machine_driver(facts, template=template_not_attested)

    # Curated: ATTESTED template → "IQ10-EVK" in model line
    template_curated = load_nord_template_with_curated_board_variant("IQ10-EVK")
    result_curated = generate_machine_driver(facts, template=template_curated)

    # Diff: only the model line differs
    baseline_lines = result_baseline.bytes_.decode("utf-8").splitlines()
    curated_lines = result_curated.bytes_.decode("utf-8").splitlines()

    diffs = [
        (i, bl, cl)
        for i, (bl, cl) in enumerate(zip(baseline_lines, curated_lines))
        if bl != cl
    ]
    assert len(diffs) == 1, f"Expected exactly 1 changed line, got {len(diffs)}: {diffs}"
    idx, old_line, new_line = diffs[0]
    assert 'FIXME(board_variant)' in old_line
    assert 'IQ10-EVK' in new_line
    assert 'model =' in new_line or 'model=' in new_line
```

### Test 12: reviewer_curated tag visible in generated-artifact comments

```python
def test_reviewer_curated_visible_in_contributes_rows():
    """When a curated value flows to the generator, the contributes_rows
    disclosure MUST visibly tag origin='reviewer_curated' so that any
    reviewer-facing surface can distinguish human-attested from machine-derived.
    """
    facts = _clean_nord_facts()
    template = load_nord_template_with_curated_board_variant("IQ10-EVK")
    result = generate_machine_driver(facts, template=template)

    # Find the contributes_row for board_variant
    bv_rows = [r for r in result.contributes_rows if "board_variant" in r.subject]
    assert len(bv_rows) >= 1
    bv_row = bv_rows[0]
    assert "reviewer_curated" in bv_row.notes or "reviewer_curated" in str(bv_row)
```

### Test 13: CONTRADICTION regresses a previously-emitting field to FIXME

```python
def test_contradiction_regresses_curated_field_to_fixme():
    """A field that emitted a curated value under GAP-FILL regresses to
    FIXME + reviewer_required=true once automation lands a CONTRADICTING
    ATTESTED value.

    This proves the system refuses to guess when two authorities disagree.
    The FIXME regression IS the loud signal — it must NOT be 'fixed' by
    auto-preferring either side.
    """
    facts = _clean_nord_facts()
    curated_overrides = {
        "board_metadata.board_variant": {
            "value": "IQ10-EVK",
            "authority": {"strength": "KB_RULE", "origin": "reviewer_curated"},
            "citations": ["Schematic LD20-94440 rev A"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T14:30:00+05:30",
                "evidence": "Schematic LD20-94440 rev A",
                "target": "test"
            }
        }
    }

    # Phase 1: GAP-FILL — automation has no board_variant, curation fills
    gc_no_automation = {"cross_verification": {"rows": []}}
    result_gap_fill = project(
        gc_no_automation, target_name="test", run_id="r",
        curated_overrides=curated_overrides
    )
    bv_gap = result_gap_fill.template.board_metadata["board_variant"]
    assert bv_gap.ncc_state == "ATTESTED"
    assert bv_gap.value == "IQ10-EVK"

    # Generator emits the curated value (not FIXME)
    output_gap = generate_machine_driver(facts, template=result_gap_fill.template.to_dict())
    assert b"IQ10-EVK" in output_gap.bytes_
    assert b"FIXME(board_variant)" not in output_gap.bytes_

    # Phase 2: CONTRADICTION — automation now ATTESTS a DIFFERENT value
    gc_with_contradiction = {
        "cross_verification": {
            "rows": [
                {"track": "T5", "subject": "board_variant", "verdict": "MATCH",
                 "value": "IQ10-RRD", "origin": "ipcat_swi"}
            ]
        }
    }
    result_contradiction = project(
        gc_with_contradiction, target_name="test", run_id="r",
        curated_overrides=curated_overrides
    )
    bv_conflict = result_contradiction.template.board_metadata["board_variant"]
    assert bv_conflict.ncc_state == "NOT_ATTESTED"  # REGRESSED
    assert bv_conflict.value is None
    assert bv_conflict.reviewer_required is True

    # Generator emits FIXME (regression from "IQ10-EVK")
    output_conflict = generate_machine_driver(
        facts, template=result_contradiction.template.to_dict()
    )
    assert b"FIXME(board_variant)" in output_conflict.bytes_
    assert b"IQ10-EVK" not in output_conflict.bytes_
    assert b"IQ10-RRD" not in output_conflict.bytes_  # neither side wins
```

---

## §6 — First Consumer + Migration

### WP-69 board_variant as first consumer

Current state (WP-69 design, committed):
- `machine_driver.py:488` reads `_template_value(template, "board_metadata", "board_variant")`.
- Template currently has `board_variant` as NOT_ATTESTED → `_template_value()` returns None → fallback to `_MODEL_FIXME_LITERAL` ("FIXME(board_variant): NOT_ATTESTED").

With G-3A.15:
1. Reviewer creates `targets/nord-iq10/curated_overrides.json` with `board_metadata.board_variant = "IQ10-EVK"`.
2. Projector re-runs → template now has `board_variant.ncc_state = "ATTESTED"`, `value = "IQ10-EVK"`.
3. Generator reads template → `_template_value()` returns `"IQ10-EVK"` → emitted as `model = "IQ10-EVK"`.
4. The FIXME literal disappears from output. The `contributes_rows` disclosure changes from NOT_ATTESTED to ATTESTED (but still never enters cross_verification.rows — it's a contributes_row disclosure, WP-64 compliant).

> **CAUTION (Slice 2 test fixture vs real attestation):** The Slice 2 tests use "IQ10-EVK" to prove the MECHANISM only. The real curated value for Nord MUST be "IQ10-RRD" — schematic LD20-94440 attests RRD; EVK is candidate-derived per G-3A.13/WP-69 and fails the provenance guard. Do not let the test value become the real attestation template.

### Lane-by-lane rollout

| Priority | Fact | Consumer | Complexity |
|----------|------|----------|------------|
| **1** | board_variant | machine_driver `model =` | Trivial — `_template_value` already reads it |
| **2** | compatible | machine_driver `compatible =` | Needs template path design (`board_metadata.compatible`) |
| **3** | SCMI power index | dt_scaffolding / audioreach | Needs `buses[].scmi_power_index` template path |
| **4** | OCTONARY binding | machine_driver DAI link config | Needs `codecs[].binding_type` template path |

### Where it stops

Even with full curation:
- `_CPU_DAI_LABEL` / `_PLATFORM_DAI_LABEL` — these are AudioReach platform identifiers, NOT board-specific. They come from the kernel's AudioReach driver and should be auto-derived from kernel source (future WP-SRC-B territory). Curation is wrong here.
- `_DAI_LINKS[].codec_label` (pcm1681/adau1979) — codec phandle labels. These SHOULD be derivable from the codec DT binding + board DT node (future dt_scaffolding + codec_stub lanes). Curation is a stopgap, not the north-star path.
- Per-pin pinmux — already solved by A-narrow (automated). No curation needed.

---

## §7 — Risks + Recommendation

### Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Laundering**: curated value used to bypass provenance guard | High | Structural: curated_overrides NEVER enters gc["cross_verification"] (proven in §3). Test 7 (negative fixture) catches any regression. |
| **Stale curation**: reviewer attests "EVK" but automation later derives "RRD" | Medium | CONTRADICTION resolution (§4): neither wins silently, reviewer_required=true, both values exposed. Timestamps enable staleness detection. Future: expiry TTL on attestations. |
| **Reviewer error**: wrong value attested | Medium | Dual-attestation (`reviewed_by` field). Citations required — the evidence can be independently checked. |
| **Audit gap**: who curated what, when | Low | Attestation sub-object + git blame + DCO sign-off = three independent audit trails. |
| **Proliferation**: too many curated facts, maintenance burden | Low | Curation is the FALLBACK path. As automated derivation improves (more source ingest parsers), curated overrides become unnecessary and can be deleted. Tests verify automation-wins-over-curation. |

### Recommendation: Option A (Sidecar Override File)

**Justification:**
- Simplest implementation that satisfies all 6 hard constraints.
- No infrastructure dependencies (no key management, no signature verification).
- Structurally correct: curated_overrides is a parallel input to the projector, not a modification of gc or template.
- Auditable by git (commit provenance) + attestation sub-object (structured provenance).
- Option B (signed patches) is over-engineered for 1-3 engineers per target. Can be added as a future hardening layer if the user base grows.
- Option C is rejected (breaks pure-projection invariant).

### Acceptance criteria for implementation

1. `curated_overrides.json` schema defined and validated at load.
2. Projector gains `curated_overrides` parameter; applies overrides ONLY to NOT_ATTESTED facts (gap-fill).
3. Three-way conflict resolution enforced: gap-fill / agreement / contradiction (§4).
4. CONTRADICTION case: `ncc_state="NOT_ATTESTED"`, `reviewer_required=true`, loud disclosure with both values.
5. All 12 firewall tests pass (including negative fixture + contradiction + visual tag).
6. WP-69 board_variant emits `"IQ10-EVK"` when curated — ONLY the `model =` line changes, no other bytes (Test 11).
7. Full existing test suite stays green (66+ projector/Phase-A tests).
8. No new value in `AUTHORITY_STRENGTHS` frozenset.
9. No write to `gc["cross_verification"]["rows"]` from projector (existing firewall test covers this).
10. Every reviewer-facing surface visibly tags `reviewer_curated` facts as human-attested (Appendix B).
11. Missing curated file → silent NOT_ATTESTED (Test 9). Malformed → loud ValueError (Test 10).
12. `contributes_rows` for curated values carry `origin: reviewer_curated` in notes (Test 12).

---

## Appendix A: Why KB_RULE — Pragmatic Reuse, Not Trust Equivalence

### The honest statement

KB_RULE is a **pragmatic reuse** of an existing enum value. It is NOT a
claim that a human schematic-read is equivalent in trustworthiness to a
deterministic software rule.

The trust-level distinction:
- **Deterministic KB rule** (e.g. "SA8775P → sa8775p family"): repeatable,
  auditable, never wrong if the input is correct. Can be re-derived at will.
- **Human schematic-read** (e.g. "title block says EVK"): non-repeatable
  without re-accessing the evidence, subject to human error, cannot be
  automatically re-derived.

These are NOT the same trust level. A human assertion is weaker than a
deterministic rule because it cannot be mechanically verified.

### Why we reuse KB_RULE anyway

1. **The closed-enum constraint is non-negotiable.** `AUTHORITY_STRENGTHS`
   is enforced at `FactRecord.__post_init__`. Adding a value requires
   touching every consumer of the frozenset — a project-wide change that
   is disproportionate to the problem.

2. **The origin field IS the real trust discriminator.** Since
   `authority.origin = "reviewer_curated"` is ALWAYS set (validated at
   load time), any consumer that needs to distinguish "machine KB rule" from
   "human attestation" can branch on `origin`. The `strength` field alone
   is insufficient for this distinction — and it has ALWAYS been
   insufficient (two IPCAT_DERIVED facts from different origins already
   have different trust profiles, distinguished only by origin).

3. **No existing consumer discriminates by strength for template values.**
   `_template_value()` gates on `ncc_state == "ATTESTED"` only. It does
   not read `authority.strength` at all. Neither does `is_open()` (it reads
   verdicts from cross-verification rows, not template strengths). There is
   no code path where KB_RULE-for-curation produces different behavior than
   a hypothetical REVIEWER_ATTESTED would.

4. **The visual-tag mandate (see §Appendix B) compensates.** Since the
   origin field carries the human-attestation provenance, and all
   reviewer-facing surfaces MUST display it (acceptance criterion), no
   reviewer can mistake a curated fact for a machine inference.

### Summary

KB_RULE is the VEHICLE (passes validation). `authority.origin` is the
SIGNAL (carries trust semantics). Consumers that need trust discrimination
read origin, not strength. This is documented as a pragmatic constraint
workaround, not as a semantic equivalence claim.

---

## Appendix B: Visual Tag Mandate for reviewer_curated Facts

### Problem

Since `authority.strength = "KB_RULE"` is shared between deterministic
machine rules and human attestations, strength alone cannot distinguish
them. A reviewer looking at a template dump or generation output must
NEVER mistake a human-attested fact for a machine-derived one.

### Mandate

Every reviewer-facing surface that displays a FactRecord MUST visibly tag
facts with `authority.origin == "reviewer_curated"` as human-attested.
Surfaces include:

| Surface | Tag format |
|---------|-----------|
| Template JSON render (H-2 dashboard) | `[HUMAN ATTESTED]` badge next to value |
| `not_attested_disclosures` in template | `"origin": "reviewer_curated"` field present |
| `contributes_rows` in generated artifacts | `notes` field includes `"source: reviewer_curated"` |
| Generated DTSI comments (if emitted) | `/* CURATED: attested by <email> */` above the value |
| H-2 review dashboard (future) | Distinct color/icon for reviewer_curated vs KB_RULE |

### Implementation rule

Any code that renders or logs a FactRecord's authority MUST check
`authority.get("origin") == "reviewer_curated"` and emit the tag. This is
NOT optional styling — it is a correctness requirement. A curated fact
rendered without the tag is a bug.

### Acceptance criterion

- Test 12 (§5) asserts the tag is present in `contributes_rows`.
- Future H-2 dashboard tests will assert visual distinction.
- Template JSON serialization MUST preserve `authority.origin` verbatim (it
  already does — no change needed, but the round-trip is tested).

---

## Appendix C: Missing-vs-Malformed Asymmetry

### Design rationale

The system treats MISSING and MALFORMED curated input differently:

| Condition | Behavior | Rationale |
|-----------|----------|-----------|
| `curated_overrides.json` does not exist | Silent NOT_ATTESTED for all curated-eligible fields | A target that hasn't been curated yet is normal — not an error. The system degrades honestly. |
| `curated_overrides.json` exists but is malformed | Loud `ValueError` — projector ABORTS | A file that exists but violates the schema is a bug in the curation process. Silent degradation here would mask reviewer errors. |

### Why the asymmetry is correct

- **Missing = not-yet-curated.** Most targets start without curation. The
  system must work without it (all fields NOT_ATTESTED, FIXMEs emitted).
  Raising an error for a missing file would block every uncurated target.

- **Malformed = curation-in-progress went wrong.** If a reviewer wrote a
  file with `value: null`, wrong target, empty evidence, or invalid
  strength, something went wrong in their curation process. Silently
  ignoring the file would mean the reviewer THINKS they curated but the
  system ignored their input — a dangerous silent failure.

### Pinned by tests

- Test 9 (§5): missing file → NOT_ATTESTED, no error.
- Test 10 (§5): malformed file → ValueError with specific message.

These two tests together prove the asymmetry is deliberate and preserved
across refactors.
