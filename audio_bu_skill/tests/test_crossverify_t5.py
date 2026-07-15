"""Unit tests for Phase-2A WP6 — Track T5 (DTS Consistency Validation).

Pure tests over ``orchestrator.reasoning.crossverify.track_t5``. No IPCAT,
no collector, no network — snapshots are built inline as plain dicts
matching the WP1 collector's wire shape for ``chips_list_chips``:

    snapshot["tools"]["chips_list_chips"] = {
        "status":        "ok" | "unavailable",
        "payload":       [{"id": 781, "name": "SA8797P (NordAU) v2",
                           "alias": "nordschleife_2.0"}],
        "result_digest": <sha256|None>,
    }

Covers the nine required cases (WP6 requirement 9, a–i):

  a. Nord DTS with ``qcom,sa8775p-adsp-pas`` → DISAGREE (compatible), high
  b. Nord DTS with ``sa8775p/adsp.mbn``      → DISAGREE (firmware), high
  c. Nord DTS with ``&rpmhpd LCX/LMX``       → DISAGREE (power_domain), high
  d. DTS no donor + no board-id/msm-id       → NCC (revision_not_pinned)
  e. DTS valid board-id + no donor           → []  (fully cross-checkable)
  f. chips_list_chips unavailable + source
     family=sa8797p + sa8775p donor          → DISAGREE, medium
  g. chips_list_chips unavailable + no
     source family                           → NCC (authority_unavailable),
                                               donor rules skipped
  h. multi-file DTS list concatenation       → still matches after join
  i. determinism (byte-equal to_dict on
     repeated calls)

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t5``
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.crossverify import (
    _T5_AUTH_ORIGIN,
    _T5_META_RULES,
    track_t5,
)
from orchestrator.reasoning.crossverify_config import T5_DONOR_RULES
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Snapshot builders (pure helpers, no I/O) ────────────────────────────────


NORD_CHIP_NAME = "SA8797P (NordAU) v2"
NORD_CHIP_ROW = {"id": 781, "name": NORD_CHIP_NAME, "alias": "nordschleife_2.0"}


def _chips_ok(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Well-formed ``chips_list_chips`` tool entry populated by the collector."""
    return {
        "status": "ok",
        "payload": list(rows if rows is not None else [NORD_CHIP_ROW]),
        "result_digest": "deadbeef",
    }


def _chips_unavailable(error_class: str = "TimeoutError") -> dict[str, Any]:
    return {
        "status": "unavailable",
        "payload": None,
        "result_digest": None,
        "error_class": error_class,
    }


def _snap(chips_entry: dict[str, Any] | None) -> dict[str, Any]:
    """Build a minimal snapshot with only ``chips_list_chips`` populated.

    ``chips_entry=None`` produces a snapshot with no ``chips_list_chips`` tool
    entry at all — exercises the "missing entry" branch of the authority path
    (treated as unavailable by :func:`_t5_authority_family`).
    """
    tools: dict[str, Any] = {}
    if chips_entry is not None:
        tools["chips_list_chips"] = chips_entry
    return {
        "chip": "nordschleife_2.0",
        "provenance": {
            "tls": {"verify": True, "ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt"},
            "readonly_tools": ["chips_list_chips"],
        },
        "tools": tools,
    }


def _by_rule(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    """Index rows by the ``kb.rule:<id>`` citation each carries (unique per rule)."""
    out: dict[str, VerificationRow] = {}
    for r in rows:
        for c in r.citations:
            if c.startswith("kb.rule:"):
                out[c[len("kb.rule:"):]] = r
                break
    return out


def _rule_ids(rows: list[VerificationRow]) -> set[str]:
    return set(_by_rule(rows))


# Sanity: pull the three donor rule ids from the KB so tests don't hard-code them.
_RULE_COMPAT = next(r for r in T5_DONOR_RULES if r["kind"] == "compatible")["rule_id"]
_RULE_FW = next(r for r in T5_DONOR_RULES if r["kind"] == "firmware")["rule_id"]
_RULE_PD = next(r for r in T5_DONOR_RULES if r["kind"] == "power_domain")["rule_id"]


# ── (a) Nord + sa8775p compatible → DISAGREE (compatible), high ─────────────


def test_nord_donor_compatible_leak_is_disagree_high() -> None:
    """Nord DTS carries ``qcom,sa8775p-adsp-pas`` — the LeMans compatible.

    Authority (chips_list_chips) says sa8797p; donor rule fires. Expect one
    DISAGREE_WITH_AUTHORITY row, confidence=high (authority is DIRECT), and
    the citations must carry both ``chips_list_chips:<chip_name>`` and
    ``kb.rule:t5.donor.compatible.sa8775p``.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8775p-adsp-pas";
        qcom,board-id = <0x01 0x00>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {[r.verdict for r in rows]}"
    row = rows[0]
    assert row.track == "T5"
    assert row.subject == "dts.compatible"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True  # DISAGREE_WITH_AUTHORITY warns by default
    assert row.coverage_gap_reason is None
    assert row.confidence == "high"
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == _T5_AUTH_ORIGIN
    assert row.authority["value"]["canonical_family"] == "sa8797p"
    assert row.authority["value"]["chip_name"] == NORD_CHIP_NAME
    # WP6 requirement 7 — both citations required
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in row.citations
    assert f"kb.rule:{_RULE_COMPAT}" in row.citations
    # review action names the target family and the offending fragment
    assert row.review_actions, "DISAGREE must record a review action"
    assert "SA8797P" in row.review_actions[0]
    assert "qcom,sa8775p-adsp-pas" in row.review_actions[0]
    print("PASS: Nord + qcom,sa8775p-adsp-pas → DISAGREE_WITH_AUTHORITY (compatible), high")


# ── (b) Nord + sa8775p firmware → DISAGREE (firmware), high ─────────────────


def test_nord_donor_firmware_leak_is_disagree_high() -> None:
    """Nord DTS carries a ``sa8775p/adsp.mbn`` firmware path → DISAGREE."""
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        firmware-name = "sa8775p/adsp.mbn";
        qcom,board-id = <0x01 0x00>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "dts.firmware"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True
    assert row.confidence == "high"
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert f"kb.rule:{_RULE_FW}" in row.citations
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in row.citations
    assert row.review_actions and "sa8775p/adsp.mbn" in row.review_actions[0]
    assert "sa8797p/" in row.review_actions[0]
    print("PASS: Nord + sa8775p/adsp.mbn → DISAGREE_WITH_AUTHORITY (firmware), high")


# ── (c) Nord + rpmhpd LCX/LMX power domain → DISAGREE (power_domain), high ──


def test_nord_donor_power_domain_leak_is_disagree_high() -> None:
    """Nord DTS references LCX/LMX rpmhpd power domains → DISAGREE."""
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        power-domains = <&rpmhpd LCX_INDEX>, <&rpmhpd LMX_INDEX>;
        qcom,board-id = <0x01 0x00>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    # LCX and LMX both match — but the KB rule is one entry with a single
    # pattern, so both hits belong to the same rule → still one row (with the
    # two matched fragments recorded on source.dts_fragments).
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {[r.subject for r in rows]}"
    row = rows[0]
    assert row.subject == "dts.power_domain"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True
    assert row.confidence == "high"
    assert f"kb.rule:{_RULE_PD}" in row.citations
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in row.citations
    # both LCX and LMX must be surfaced on the source side
    frags = row.source.get("dts_fragments") if isinstance(row.source, dict) else []
    assert any("LCX" in f for f in frags), f"LCX not in {frags}"
    assert any("LMX" in f for f in frags), f"LMX not in {frags}"
    assert row.review_actions and "scmi" in row.review_actions[0].lower()
    print("PASS: Nord + &rpmhpd LCX/LMX → DISAGREE_WITH_AUTHORITY (power_domain), high")


# ── (d) No donor + no board-id/msm-id → NCC (revision_not_pinned) ──────────


def test_no_donor_no_revision_pin_is_not_cross_checkable() -> None:
    """A well-formed sa8797p DTS with no pins → single NCC(revision_not_pinned)."""
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        firmware-name = "sa8797p/adsp.mbn";
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "dts.revision_anchor"
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "revision_not_pinned"
    assert row.warning is False
    assert row.confidence == "none"
    assert row.authority["strength"] == "IPCAT_DIRECT"  # authority itself is present
    assert (
        f"kb.rule:{_T5_META_RULES['revision_not_pinned']}" in row.citations
    ), row.citations
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in row.citations
    assert row.review_actions and "qcom,board-id" in row.review_actions[0]
    print("PASS: no donor + no board-id/msm-id → NCC (revision_not_pinned)")


# ── (e) Valid board-id + no donor → [] ─────────────────────────────────────


def test_valid_revision_pin_and_no_donor_is_empty() -> None:
    """A DTS that both pins the revision AND avoids donor namespaces → []."""
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        firmware-name = "sa8797p/adsp.mbn";
        qcom,board-id = <0x01 0x01>;
        qcom,msm-id   = <0x1AB 0x20000>;
        power-domains = <&scmi5_pd 0>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert rows == [], f"expected [] (nothing to flag), got {[r.verdict for r in rows]}"
    print("PASS: valid revision pin + no donor namespace → [] (fully cross-checkable)")


# ── (f) Authority unavailable + source family=sa8797p + sa8775p donor →
#       DISAGREE medium ─────────────────────────────────────────────────────


def test_authority_unavailable_source_family_present_donor_leaks_medium() -> None:
    """chips_list_chips unavailable but source declares family → DISAGREE medium."""
    dts = {
        "family": "sa8797p",
        "text": (
            "remoteproc_adsp: remoteproc@30000000 {\n"
            '    compatible = "qcom,sa8775p-adsp-pas";\n'
            "    qcom,board-id = <0x01 0x00>;\n"
            "};\n"
        ),
    }
    rows = track_t5(snapshot=_snap(_chips_unavailable()), dts=dts, kb=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject == "dts.compatible"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert row.warning is True
    assert row.confidence == "medium", (
        f"expected medium under KB-only authority, got {row.confidence!r}"
    )
    assert row.authority["strength"] == "KB_RULE"
    assert row.authority["value"]["canonical_family"] == "sa8797p"
    assert row.authority["value"]["chip_name"] == "<unavailable>"
    # citations still carry both required tokens (chip_name → "<unavailable>")
    assert "chips_list_chips:<unavailable>" in row.citations
    assert f"kb.rule:{_RULE_COMPAT}" in row.citations
    # notes must record the downgrade rationale
    assert any("chips_list_chips unavailable" in n for n in row.notes), row.notes
    assert any("medium" in n for n in row.notes), row.notes
    print(
        "PASS: authority unavailable + source family=sa8797p + sa8775p donor "
        "→ DISAGREE_WITH_AUTHORITY, confidence=medium"
    )


# ── (g) Authority unavailable + no source family → NCC(authority_unavailable) ─


def test_authority_unavailable_no_source_family_is_single_ncc() -> None:
    """No authority AND no source family → one NCC(authority_unavailable); donor rules skipped."""
    dts = (
        # Contains a donor pattern that WOULD fire — but must be skipped since
        # we have no way to establish the target family without cheating.
        'compatible = "qcom,sa8775p-adsp-pas";\n'
    )
    rows = track_t5(snapshot=_snap(_chips_unavailable()), dts=dts, kb=None)
    assert len(rows) == 1, (
        f"expected exactly 1 row (donor rules must be skipped), got {len(rows)}: "
        f"{[r.subject for r in rows]}"
    )
    row = rows[0]
    assert row.subject == "silicon_identity"
    assert row.verdict == "NOT_CROSS_CHECKABLE"
    assert row.coverage_gap_reason == "authority_unavailable"
    assert row.warning is False
    assert row.confidence == "none"
    assert row.authority["strength"] == "UNAVAILABLE"
    assert row.authority["origin"] == "none"
    # provenance still recorded, with placeholder chip name
    assert "chips_list_chips:<unavailable>" in row.citations
    assert f"kb.rule:{_T5_META_RULES['silicon_identity']}" in row.citations
    assert row.review_actions, "NCC must carry a review action even here"
    print(
        "PASS: authority unavailable + no source family → single NCC "
        "(authority_unavailable), donor rules skipped"
    )


# ── (g2) Empty DTS + authority ok → NCC(revision_not_pinned), empty-DTS note ─


def test_empty_dts_authority_ok_is_revision_not_pinned_ncc() -> None:
    """Fix 3 — when authority is present but the target provided NO DTS files,
    T5 must still emit a single NCC row so Nord (which has DTS but no pin) and
    Eliza (which has no DTS at all) both surface a T5 verdict in the report.

    Empty DTS lands in the ``revision_not_pinned`` bucket — semantically:
    without a DTS you cannot pin a revision. The row's ``notes`` distinguish
    the empty-DTS case ("no DTS files were provided") from the populated-but-
    unpinned case ("declares neither qcom,board-id nor qcom,msm-id").

    Donor rules cannot fire against empty text, so the row count stays at 1.
    """
    # dts=None simulates the "no DTS files provided" case; dts="" is the
    # equivalent explicit-empty case that also passes through _t5_flatten_dts.
    for empty in (None, ""):
        rows = track_t5(snapshot=_snap(_chips_ok()), dts=empty, kb=None)
        assert len(rows) == 1, (
            f"expected 1 row (revision-anchor NCC), got {len(rows)} for dts={empty!r}: "
            f"{[(r.subject, r.verdict) for r in rows]}"
        )
        row = rows[0]
        assert row.track == "T5"
        assert row.subject == "dts.revision_anchor"
        assert row.verdict == "NOT_CROSS_CHECKABLE"
        assert row.coverage_gap_reason == "revision_not_pinned"
        assert row.warning is False
        assert row.confidence == "none"
        # authority is IPCAT_DIRECT (chips_list_chips was ok) — the row still
        # cites the target chip and the revision-not-pinned meta rule.
        assert row.authority["strength"] == "IPCAT_DIRECT"
        assert row.authority["value"]["canonical_family"] == "sa8797p"
        assert f"chips_list_chips:{NORD_CHIP_NAME}" in row.citations
        assert (
            f"kb.rule:{_T5_META_RULES['revision_not_pinned']}" in row.citations
        ), row.citations
        # note branch distinguishes empty DTS from populated-but-unpinned
        assert any("no DTS files were provided" in n for n in row.notes), (
            f"expected empty-DTS note, got notes={row.notes!r}"
        )
        # and the populated-but-unpinned note must NOT appear here
        assert not any(
            "declares neither qcom,board-id nor qcom,msm-id" in n for n in row.notes
        ), row.notes
    print("PASS: empty DTS + authority ok → NCC(revision_not_pinned), empty-DTS note")


# ── (h) Multi-file DTS list is concatenated ────────────────────────────────


def test_multi_file_dts_list_concatenation() -> None:
    """A list of ``[{text: part1}, {text: part2}]`` — matches across files."""
    dts = [
        {"text": 'compatible = "qcom,sa8797p-adsp-pas";\nqcom,board-id = <0x01 0x00>;\n'},
        # sa8775p compatible in the second file — must still hit after join
        {"text": 'firmware-name = "sa8775p/adsp.mbn";\n'},
    ]
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    rule_ids = _rule_ids(rows)
    assert _RULE_FW in rule_ids, (
        f"multi-file join failed: {_RULE_FW} not found; rows={[(r.subject, r.verdict) for r in rows]}"
    )
    fw_row = _by_rule(rows)[_RULE_FW]
    assert fw_row.verdict == "DISAGREE_WITH_AUTHORITY"
    assert fw_row.confidence == "high"
    # ensure the compatible rule did NOT fire against the target's own sa8797p
    # namespace in file 1 (only donor-family rules should ever hit — sa8797p is
    # the target family, and _T5_DONOR_RULES has no sa8797p rule anyway).
    for r in rows:
        for c in r.citations:
            if c.startswith("kb.rule:t5.donor.") and c.endswith("sa8797p"):
                raise AssertionError(f"unexpected target-family rule fired: {c}")
    print("PASS: multi-file DTS list concatenated (sa8775p firmware in file 2 matched)")


# ── (i) Determinism ────────────────────────────────────────────────────────


def test_deterministic_across_calls() -> None:
    """T5 is a pure function: identical input → byte-equal ``to_dict()`` output."""
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8775p-adsp-pas";
        firmware-name = "sa8775p/adsp.mbn";
        power-domains = <&rpmhpd LCX_INDEX>, <&rpmhpd LMX_INDEX>;
    };
    """
    snap = _snap(_chips_ok())
    a = [r.to_dict() for r in track_t5(snapshot=snap, dts=dts, kb=None)]
    b = [r.to_dict() for r in track_t5(snapshot=snap, dts=dts, kb=None)]
    assert a == b, "T5 must be deterministic across repeated calls"
    # sanity: this input hits all three donor rules AND the revision-anchor NCC
    # (no board-id/msm-id). Guard against determinism-on-empty-output.
    rule_ids = {c[len("kb.rule:"):] for row in a for c in row["citations"]
                if c.startswith("kb.rule:")}
    assert _RULE_COMPAT in rule_ids
    assert _RULE_FW in rule_ids
    assert _RULE_PD in rule_ids
    assert _T5_META_RULES["revision_not_pinned"] in rule_ids
    print("PASS: T5 is deterministic across repeated calls (4 rows, all rule ids present)")


def main() -> None:
    # WP6 requirement 9 — tests a–i, plus g2 (Fix 3)
    test_nord_donor_compatible_leak_is_disagree_high()               # a
    test_nord_donor_firmware_leak_is_disagree_high()                 # b
    test_nord_donor_power_domain_leak_is_disagree_high()             # c
    test_no_donor_no_revision_pin_is_not_cross_checkable()           # d
    test_valid_revision_pin_and_no_donor_is_empty()                  # e
    test_authority_unavailable_source_family_present_donor_leaks_medium()  # f
    test_authority_unavailable_no_source_family_is_single_ncc()      # g
    test_empty_dts_authority_ok_is_revision_not_pinned_ncc()         # g2 (Fix 3)
    test_multi_file_dts_list_concatenation()                         # h
    test_deterministic_across_calls()                                # i
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
