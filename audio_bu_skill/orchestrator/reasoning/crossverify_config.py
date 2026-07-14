"""KB rule data for Track T5 (DTS Consistency Validation).

Pure data — no imports outside the standard library, no functions, no I/O.
Read by ``orchestrator.reasoning.crossverify.track_t5`` at call time. The T5
track never hard-codes rule text or patterns; it only *reads* from this file.

Three tables are exported:

  * :data:`T5_TARGET_IDENTITY`
      Canonical target-identity metadata keyed by silicon family — what a
      well-formed DTS for that platform looks like (expected compatible
      prefix, expected firmware prefix, expected power-domain style).
      Used to phrase review-actions on donor disagreement.

  * :data:`T5_DONOR_RULES`
      Ordered list of donor-namespace patterns (donor = other-family
      fragments that must not appear in this platform's DTS). Each entry
      declares its :attr:`rule_id`, :attr:`family` (donor family the rule
      detects a leak of), :attr:`kind` (compatible / firmware / power_domain
      / reg / misc), :attr:`pattern` (regex applied to the DTS text), and a
      human-readable :attr:`description`.

  * :data:`T5_META_RULES`
      Synthetic rule ids for T5 rows that are not triggered by a specific
      donor pattern (silicon-identity NCC on authority_unavailable, and the
      revision-anchor NCC on revision_not_pinned). WP6 requirement 7 says
      every T5 row's citations must include ``kb.rule:<rule_id>``, so these
      meta rows carry a synthetic id from this table.
"""

from __future__ import annotations


T5_TARGET_IDENTITY: dict[str, dict[str, str]] = {
    # SA8797P (NordAU) — Nord's silicon. Everything downstream (DSP firmware,
    # ADSP-PAS compatible, power-domain style) lives under the sa8797p
    # namespace and uses SCMI power domains (scmiN_pd), not the LeMans-style
    # rpmhpd LCX/LMX refs.
    "sa8797p": {
        "expected_compatible_prefix": "qcom,sa8797p-",
        "expected_firmware_prefix":   "sa8797p/",
        "power_domain_style":         "scmi",
    },
    # Additional target families are added here as they get onboarded.
}


T5_DONOR_RULES: list[dict[str, str]] = [
    {
        "rule_id":     "t5.donor.compatible.sa8775p",
        "family":      "sa8775p",
        "kind":        "compatible",
        "pattern":     r"qcom,sa8775p-[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*",
        "description": "SA8775P (LeMans) compatible string — donor namespace",
    },
    {
        "rule_id":     "t5.donor.firmware.sa8775p",
        "family":      "sa8775p",
        "kind":        "firmware",
        "pattern":     r"sa8775p/[A-Za-z0-9._/-]+\.mbn",
        "description": "SA8775P (LeMans) firmware path — donor namespace",
    },
    {
        "rule_id":     "t5.donor.pd.lcx_lmx",
        "family":      "sa8775p",
        "kind":        "power_domain",
        "pattern":     r"&rpmhpd\s+(?:[A-Z_]*)(?:LCX|LMX)(?:_[A-Za-z0-9]+)?",
        "description": (
            "LCX/LMX rpmhpd power-domain reference — LeMans/SA8775P-specific; "
            "Nord uses SCMI power domains (scmiN_pd)"
        ),
    },
]


T5_META_RULES: dict[str, str] = {
    "silicon_identity":     "t5.meta.silicon.identity",
    "revision_not_pinned":  "t5.meta.revision.pin_required",
}
