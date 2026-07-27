"""Unit tests for WP G-3B-gamma — Track T5 positive SoC-family attestation.

Pure tests over ``orchestrator.reasoning.crossverify.track_t5``. Companion
to ``tests/test_crossverify_t5.py`` (which covers donor-leak DISAGREE cases
a-i). This module isolates the WP G-3B-gamma additive branch:

  On Path 1 (IPCAT authority available), ``track_t5`` emits a ``MATCH`` row
  per kind ``in {compatible, firmware}`` when ALL four hold:

    (a) IPCAT authority (chips_list_chips) confirms the target family.
    (b) The donor rule for that kind did NOT fire (mutual exclusivity per
        kind — a donor leak already produced DISAGREE, so no MATCH).
    (c) ``T5_TARGET_IDENTITY[target]`` supplies an expected prefix for
        that kind.
    (d) The DTS text contains that expected prefix as a substring.

  The MATCH row is authority-anchored (IPCAT_DIRECT), warning=False (opens
  ``is_open()`` gates downstream), confidence=high, and its ``notes`` carry
  the Turn-3 tightened disclosure contract:

    * ``SCOPE: SoC-family attestation only`` (both kinds)
    * ``NOT_ATTESTED: board_variant`` (compatible ONLY)
    * explicit non-authorization of qcom,iq10-rrd / qcom,iq10-evk (compatible ONLY)
    * ``SCOPE: SoC-family firmware-path prefix only`` (firmware ONLY)
    * ``does NOT authorize any specific firmware binary`` (firmware ONLY)

Nine tests per design doc §6.1 + §7 (Turn-3 disclosure contract):

  1. positive compatible MATCH when authority + prefix
  2. positive firmware MATCH when authority + prefix
  3. both kinds MATCH together (real-Nord case-e text)
  4. no positive MATCH when donor kind fired (mutual exclusivity per kind)
  5. no positive MATCH when DTS missing prefix
  6. no positive MATCH when authority unavailable (Path 2 has no positive branch)
  7. MATCH row citations contain IPCAT anchor AND kb.rule meta id
  8. MATCH row warning flag is False (opens the downstream is_open gate)
  9. MATCH row notes carry the SCOPE + NOT_ATTESTED disclosure (Turn 3)

Provenance guard [Certain]: no test in this file uses candidate commit
``5267b2e1`` as an authority anchor. The authority object on every MATCH
row is IPCAT (``chips_list_chips``); the DTS text is a *second* condition,
not the anchor.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_t5_positive_attestation``
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
#
# Duplicated from tests/test_crossverify_t5.py so this test file is
# self-contained — cross-test-file imports of test helpers are a smell we
# avoid on principle (a rename in the sibling file should not break this
# file's tests).


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
    """Build a minimal snapshot with only ``chips_list_chips`` populated."""
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


def _by_subject(rows: list[VerificationRow]) -> dict[str, VerificationRow]:
    """Index rows by ``subject`` — each subject expected at most once per input.

    A duplicate subject would violate the per-kind mutual exclusivity contract
    (donor DISAGREE and positive MATCH for the same kind cannot coexist).
    """
    out: dict[str, VerificationRow] = {}
    for r in rows:
        assert r.subject not in out, (
            f"unexpected duplicate subject {r.subject!r}: "
            f"{[(x.subject, x.verdict) for x in rows]!r}"
        )
        out[r.subject] = r
    return out


# Sanity: pull donor rule_ids from the KB so tests don't hard-code them.
_RULE_COMPAT = next(r for r in T5_DONOR_RULES if r["kind"] == "compatible")["rule_id"]
_RULE_FW = next(r for r in T5_DONOR_RULES if r["kind"] == "firmware")["rule_id"]


# ── 1. Positive compatible MATCH when authority + prefix ───────────────────


def test_positive_compatible_match_when_authority_and_prefix() -> None:
    """Clean DTS with ``qcom,sa8797p-adsp-pas`` + IPCAT authority → compat MATCH.

    Isolates the compatible kind by declining any firmware-prefix substring
    in the DTS. Revision pin (board-id) is present to keep the NCC branch
    silent — we test that separately in the sibling suite.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert len(rows) == 1, (
        f"expected 1 MATCH row (dts.compatible), got {len(rows)}: "
        f"{[(r.subject, r.verdict) for r in rows]!r}"
    )
    row = rows[0]
    assert row.track == "T5"
    assert row.subject == "dts.compatible"
    assert row.verdict == "MATCH"
    assert row.warning is False, "MATCH must not warn (would close is_open gate)"
    assert row.confidence == "high"
    assert row.coverage_gap_reason is None
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == _T5_AUTH_ORIGIN
    assert row.authority["value"]["canonical_family"] == "sa8797p"
    assert row.authority["value"]["chip_name"] == NORD_CHIP_NAME
    assert row.source.get("dts_prefix_found") == "qcom,sa8797p-"
    assert row.review_actions == []
    print("PASS: authority + qcom,sa8797p- prefix → dts.compatible MATCH")


# ── 2. Positive firmware MATCH when authority + prefix ─────────────────────


def test_positive_firmware_match_when_authority_and_prefix() -> None:
    """Clean DTS with ``sa8797p/adsp.mbn`` + IPCAT authority → firmware MATCH.

    Isolates the firmware kind by declining any compatible-prefix substring
    in the DTS.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        firmware-name = "sa8797p/adsp.mbn";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert len(rows) == 1, (
        f"expected 1 MATCH row (dts.firmware), got {len(rows)}: "
        f"{[(r.subject, r.verdict) for r in rows]!r}"
    )
    row = rows[0]
    assert row.track == "T5"
    assert row.subject == "dts.firmware"
    assert row.verdict == "MATCH"
    assert row.warning is False
    assert row.confidence == "high"
    assert row.coverage_gap_reason is None
    assert row.authority["strength"] == "IPCAT_DIRECT"
    assert row.authority["origin"] == _T5_AUTH_ORIGIN
    assert row.authority["value"]["canonical_family"] == "sa8797p"
    assert row.source.get("dts_prefix_found") == "sa8797p/"
    assert row.review_actions == []
    print("PASS: authority + sa8797p/ prefix → dts.firmware MATCH")


# ── 3. Both kinds MATCH together (real-Nord case-e text) ───────────────────


def test_both_kinds_match_together() -> None:
    """Real-Nord case-(e) DTS text → both dts.compatible AND dts.firmware MATCH.

    This mirrors the case-(e) test in ``test_crossverify_t5.py`` — the two
    files independently pin the same contract; a change to either would
    trip the other, catching stale-test drift.
    """
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
    assert len(rows) == 2, (
        f"expected 2 MATCH rows, got {len(rows)}: "
        f"{[(r.subject, r.verdict) for r in rows]!r}"
    )
    by_subject = _by_subject(rows)
    assert set(by_subject) == {"dts.compatible", "dts.firmware"}, by_subject
    for row in rows:
        assert row.track == "T5"
        assert row.verdict == "MATCH"
        assert row.warning is False
        assert row.confidence == "high"
        assert row.authority["strength"] == "IPCAT_DIRECT"
        assert row.authority["value"]["canonical_family"] == "sa8797p"
    assert by_subject["dts.compatible"].source.get("dts_prefix_found") == "qcom,sa8797p-"
    assert by_subject["dts.firmware"].source.get("dts_prefix_found") == "sa8797p/"
    print("PASS: real-Nord case-e DTS → 2 MATCH rows (compatible + firmware)")


# ── 4. No positive MATCH when donor kind fired (mutual exclusivity) ────────


def test_no_positive_match_when_donor_kind_fired() -> None:
    """DTS with sa8775p compatible (donor) + sa8797p compatible (target prefix).

    Mutual-exclusivity contract: the compatible-kind donor fires → produces a
    DISAGREE_WITH_AUTHORITY row → the positive branch MUST skip the compatible
    kind. No MATCH row for compatible even though the target prefix is also
    present. Firmware is not referenced by this DTS at all, so no MATCH for
    firmware either.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8775p-adsp-pas", "qcom,sa8797p-adsp-pas";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    # Exactly one DISAGREE row on compatible (from the donor rule).
    assert len(rows) == 1, (
        f"expected exactly 1 row (donor DISAGREE for compatible), got {len(rows)}: "
        f"{[(r.subject, r.verdict) for r in rows]!r}"
    )
    row = rows[0]
    assert row.subject == "dts.compatible"
    assert row.verdict == "DISAGREE_WITH_AUTHORITY"
    # No MATCH row emitted for compatible — this is the mutual-exclusivity guard.
    match_rows = [r for r in rows if r.verdict == "MATCH"]
    assert match_rows == [], (
        f"mutual-exclusivity violation: compatible donor fired AND MATCH emitted: "
        f"{[(r.subject, r.verdict) for r in match_rows]!r}"
    )
    print("PASS: donor compatible fired → DISAGREE only, no MATCH (per-kind exclusivity)")


# ── 5. No positive MATCH when DTS missing prefix ───────────────────────────


def test_no_positive_match_when_dts_missing_prefix() -> None:
    """DTS with revision pin but neither ``qcom,sa8797p-`` nor ``sa8797p/`` → 0 rows.

    All four MATCH conditions must hold. When the DTS text lacks BOTH expected
    prefixes, condition (d) fails for BOTH kinds → the positive branch remains
    silent. No donor fires either, and revision is pinned → no NCC either.
    Expected: rows == [].
    """
    # Deliberately generic: name a Nord peripheral so the DTS is syntactically
    # plausible, but include no sa8797p-family strings on either kind.
    dts = """
    remoteproc: remoteproc@30000000 {
        status = "okay";
        qcom,board-id = <0x01 0x01>;
        qcom,msm-id   = <0x1AB 0x20000>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    assert rows == [], (
        f"expected 0 rows (no donor, no target prefix, revision pinned), got "
        f"{[(r.subject, r.verdict) for r in rows]!r}"
    )
    print("PASS: no target prefix in DTS → no MATCH rows (silent positive branch)")


# ── 6. No positive MATCH when authority unavailable (Path 2 has no branch) ─


def test_no_positive_match_when_authority_unavailable() -> None:
    """chips_list_chips unavailable + source family sa8797p + sa8797p prefix in DTS.

    Path 2 (KB_RULE authority) intentionally lacks a positive-attestation
    branch — a candidate-derived family declaration plus a candidate-derived
    DTS text is NOT enough to open the gate. The trust chain requires
    IPCAT_DIRECT authority for MATCH; KB_RULE is insufficient.

    This is a load-bearing constraint from §0 (preserve provenance) — a MATCH
    on Path 2 would let a bad target profile self-attest.
    """
    dts = {
        "family": "sa8797p",
        "text": (
            'compatible = "qcom,sa8797p-adsp-pas";\n'
            'firmware-name = "sa8797p/adsp.mbn";\n'
            "qcom,board-id = <0x01 0x01>;\n"
        ),
    }
    rows = track_t5(snapshot=_snap(_chips_unavailable()), dts=dts, kb=None)
    match_rows = [r for r in rows if r.verdict == "MATCH"]
    assert match_rows == [], (
        f"Path 2 must NOT emit MATCH (candidate-derived family cannot self-attest): "
        f"{[(r.subject, r.verdict, r.authority.get('strength')) for r in match_rows]!r}"
    )
    print("PASS: authority unavailable → no MATCH even with source family + DTS prefix")


# ── 7. MATCH row citations contain IPCAT anchor AND kb.rule meta id ────────


def test_match_row_citations_contain_ipcat_and_kb_rule() -> None:
    """Each MATCH row cites BOTH the IPCAT anchor AND the target-match meta rule.

    Citations are the reviewer-facing evidence trail. WP6 requirement 7 says
    every T5 row must carry ``kb.rule:<rule_id>`` — for the new MATCH rows
    that rule_id comes from ``T5_META_RULES['target_<kind>_match']``.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        firmware-name = "sa8797p/adsp.mbn";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    by_subject = _by_subject(rows)
    assert set(by_subject) == {"dts.compatible", "dts.firmware"}

    compat = by_subject["dts.compatible"]
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in compat.citations, compat.citations
    assert (
        f"kb.rule:{_T5_META_RULES['target_compatible_match']}" in compat.citations
    ), compat.citations

    firmware = by_subject["dts.firmware"]
    assert f"chips_list_chips:{NORD_CHIP_NAME}" in firmware.citations, firmware.citations
    assert (
        f"kb.rule:{_T5_META_RULES['target_firmware_match']}" in firmware.citations
    ), firmware.citations
    print("PASS: MATCH rows cite chips_list_chips:<name> AND kb.rule:t5.target.<kind>.match")


# ── 8. MATCH row warning is False (opens the downstream is_open gate) ──────


def test_match_row_warning_false_default() -> None:
    """MATCH row warning flag is False — a MATCH row must OPEN downstream gates.

    ``generation/model.py:is_open()`` returns False iff ``warning=True`` OR
    the verdict is not in ``_GATING_OPEN_VERDICTS`` ({MATCH, PARTIAL_MATCH}).
    So a MATCH with warning=True would silently CLOSE its gate — the whole
    point of this WP is to OPEN the dt_scaffolding gate. This asserts the
    invariant explicitly.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        firmware-name = "sa8797p/adsp.mbn";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    match_rows = [r for r in rows if r.verdict == "MATCH"]
    assert len(match_rows) == 2, (
        f"expected 2 MATCH rows for this input, got {len(match_rows)}"
    )
    for row in match_rows:
        assert row.warning is False, (
            f"MATCH row {row.subject!r} has warning=True — would CLOSE downstream "
            f"is_open() gate, defeating the purpose of the positive branch"
        )
    print("PASS: MATCH rows carry warning=False (open downstream is_open gate)")


# ── 9. MATCH row notes carry Turn-3 SCOPE + NOT_ATTESTED disclosure ────────


def test_match_row_notes_carry_not_attested_disclosure() -> None:
    """Turn-3 tightened contract: MATCH row notes carry the disclosure lines.

    Compatible MATCH must carry:
      * "SCOPE: SoC-family attestation only"
      * "NOT_ATTESTED: board_variant"
      * explicit non-authorization of qcom,iq10-rrd AND qcom,iq10-evk
      * "board-variant reconciliation is a separate track"

    Firmware MATCH must carry:
      * "SCOPE: SoC-family firmware-path prefix only"
      * "does NOT authorize any specific firmware binary"

    Firmware MATCH must NOT carry ``NOT_ATTESTED: board_variant`` — that
    is a compatible-only concern per the design.
    """
    dts = """
    remoteproc_adsp: remoteproc@30000000 {
        compatible = "qcom,sa8797p-adsp-pas";
        firmware-name = "sa8797p/adsp.mbn";
        qcom,board-id = <0x01 0x01>;
    };
    """
    rows = track_t5(snapshot=_snap(_chips_ok()), dts=dts, kb=None)
    by_subject = _by_subject(rows)
    assert set(by_subject) == {"dts.compatible", "dts.firmware"}

    compat = by_subject["dts.compatible"]
    assert any("SCOPE: SoC-family attestation only" in n for n in compat.notes), (
        f"compat MATCH missing SCOPE line: {compat.notes!r}"
    )
    assert any("NOT_ATTESTED: board_variant" == n for n in compat.notes), (
        f"compat MATCH missing NOT_ATTESTED: board_variant line: {compat.notes!r}"
    )
    assert any("qcom,iq10-rrd" in n for n in compat.notes), (
        f"compat MATCH missing qcom,iq10-rrd non-authorization: {compat.notes!r}"
    )
    assert any("qcom,iq10-evk" in n for n in compat.notes), (
        f"compat MATCH missing qcom,iq10-evk non-authorization: {compat.notes!r}"
    )
    assert any(
        "board-variant reconciliation is a separate track" in n for n in compat.notes
    ), f"compat MATCH missing separate-track pointer: {compat.notes!r}"

    firmware = by_subject["dts.firmware"]
    assert any(
        "SCOPE: SoC-family firmware-path prefix only" in n for n in firmware.notes
    ), f"firmware MATCH missing SCOPE line: {firmware.notes!r}"
    assert any(
        "does NOT authorize any specific firmware binary" in n for n in firmware.notes
    ), f"firmware MATCH missing firmware-binary non-authorization: {firmware.notes!r}"
    # Firmware MATCH must NOT carry the board_variant line — compat-only concern.
    assert not any("NOT_ATTESTED: board_variant" == n for n in firmware.notes), (
        f"firmware MATCH incorrectly carries board_variant disclosure: {firmware.notes!r}"
    )
    print(
        "PASS: MATCH notes carry Turn-3 SCOPE + NOT_ATTESTED lines "
        "(compat has board_variant, firmware does not)"
    )


def main() -> None:
    test_positive_compatible_match_when_authority_and_prefix()      # 1
    test_positive_firmware_match_when_authority_and_prefix()        # 2
    test_both_kinds_match_together()                                # 3
    test_no_positive_match_when_donor_kind_fired()                  # 4
    test_no_positive_match_when_dts_missing_prefix()                # 5
    test_no_positive_match_when_authority_unavailable()             # 6
    test_match_row_citations_contain_ipcat_and_kb_rule()            # 7
    test_match_row_warning_false_default()                          # 8
    test_match_row_notes_carry_not_attested_disclosure()            # 9
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
