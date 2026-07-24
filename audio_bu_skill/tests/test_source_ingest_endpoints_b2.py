# SPDX-License-Identifier: BSD-3-Clause-Clear
#
# WP-SRC-B2 red baseline — real IPCAT QUP endpoint plumbing (closes G-3A.11).
#
# Signed-off-by: Ajay Kumar Nandam <ajay.nandam@oss.qualcomm.com>
#
# WHAT THIS FILE IS
# -----------------
# The B2 layer of the WP-SRC-B suite — pinning the reader to the REAL
# ``chipio_get_qups`` payload shape (closes G-3A.11). Originally authored as
# the *red* baseline against a fictional pre-B2 reader that walked
# ``analysis["ipcat"]["qup_controllers"]`` (a key that appears in NO real
# evidence file); that fictional shape has since been eliminated. The
# sibling ``tests/test_source_ingest_endpoints.py`` (B-1..B-5) was migrated
# in the same WP-SRC-B2 GREEN pass to feed the real ``chipio_get_qups``
# flat-list shape (see ``_qup_populated_analysis`` and the migrated B-4
# empty-case entries there), so both suites now exercise the same real key.
#
# This file feeds the reader the **real** ``chipio_get_qups`` payload shape
# (a flat list of SE records, copied verbatim from
# ``targets/nord-iq10/evidence/ipcat/chipio_get_qups.json``) and asserts the
# reader derives endpoints from it. All tests here are GREEN post-migration:
# the reader at ``orchestrator/source_ingest/endpoints.py`` walks
# ``ipcat.chipio_get_qups`` and emits one ``EndpointFact`` per SE record.
# The historical red-baseline framing is preserved in the assertion messages
# so a future regression that reintroduces the fictional shape lights up
# with the same diagnostic prose that led to the original green fix.
#
# REAL-SHAPE FACTS (confirmed from the evidence file, NOT inferred)
# -----------------------------------------------------------------
#   * The payload is a flat JSON *list* (len 27), NOT a dict with a
#     ``qup_controllers`` key.
#   * Per-entry keys: ``swi`` (dict: address/map/name), ``se_number``,
#     ``group`` ("TLMM"/"SAIL"), ``wrapper_id``, and capability booleans
#     ``i2c`` / ``spi`` / ``uart`` / ...  There is NO ``kind`` / ``engine``
#     / ``bus`` / ``audio_role`` / ``group_name`` key — those were the
#     fictional-fixture inventions.
#   * ZERO SEs are ``i2s``-capable: I2S8 is an LPASS interface, not a QUP.
#     The audio-relevant QUP is the codec-control I2C SE (``QUPV3_0_SE4``,
#     ``i2c=True``) — which is ALSO the label-collision entry.
#   * ``swi.name == "QUPV3_0_SE4"`` appears 3x (wrapper_id 2/3/4, all
#     group=TLMM, all i2c=True). ``instance`` differs only by
#     ``u_qupv3_wrapper_N``. ``swi.name`` alone is therefore NOT unique.
#
# COLLISION / GATE POLICY (confirmed, decides these assertions)
# -------------------------------------------------------------
#   ``_GATING_OPEN_VERDICTS = frozenset({"MATCH", "PARTIAL_MATCH"})`` at
#   ``orchestrator/generation/model.py:46``, consumed by ``is_open`` at
#   ``:237``. PARTIAL_MATCH OPENS the T4a gate. So the ``QUPV3_0_SE4``
#   triple-collision does NOT need wrapper-disambiguation in B2 —
#   ``T-SRC-B2-2`` asserts *open-on-PARTIAL* via ``se_number`` alignment,
#   not a disambiguated MATCH. Wrapper-pinning (via ``wrapper_id`` /
#   ``instance``) is a deferrable later WP.
#
# VerificationGate (B2 scope-lock #2 — resolved, no code)
# -------------------------------------------------------
#   The G-3A.11 doc prose (``docs/PHASE3_KNOWN_GAPS.md:620-637``) claims a
#   ``VerificationGate`` symbol is undefined in
#   ``orchestrator/generation/model.py``, leaving the separator-reconcile
#   test red at import. That claim is STALE: ``grep -rn VerificationGate
#   orchestrator tests`` is empty, and the live separator test uses
#   ``TrustedFacts`` (not ``VerificationGate``) and passes. There is no
#   symbol to land — this baseline likewise gates on ``TrustedFacts``. The
#   doc prose is the only artifact that needs a stale-claim correction.
#
# GENERALITY GUARD (B2 scope-lock #3 — non-negotiable)
# ----------------------------------------------------
#   G-3A.13 proved all four generators silently bake Nord identity. The B2
#   reader must NOT become the fifth Nord-baked surface. ``T-SRC-B2-
#   GENERALITY`` feeds a non-Nord payload of the SAME real shape but with
#   foreign tokens ("FAKESOC_QUPV9_7_SE1", group "ZZTOP", se_number 1) and
#   asserts the derived endpoints carry THAT payload's tokens — never a
#   Nord token. A reader hardcoded to Nord's exact JSON would fail this.
#
# Run:
#   PYTHONPATH=. python3 -m pytest tests/test_source_ingest_endpoints_b2.py -q

from __future__ import annotations

import unittest
from typing import Any


# --------------------------------------------------------------------------- #
# Fixtures — REAL chipio_get_qups shape (verbatim evidence), plus a non-Nord
# payload of the same shape for the generality guard.
# --------------------------------------------------------------------------- #
def _real_chipio_get_qups_payload() -> list[dict[str, Any]]:
    """Return real Nord IQ-10 QUP SE records, copied verbatim.

    Source: ``targets/nord-iq10/evidence/ipcat/chipio_get_qups.json``
    (chip ``nordschleife_2.0``). This is the 4-entry ``se_number == 4``
    slice: the codec-control I2C SE (``QUPV3_0_SE4``, TLMM) plus its two
    wrapper collisions and the SAIL-domain SE4. Every field is real —
    ``swi``/``se_number``/``group``/``wrapper_id``/capability booleans.
    There is deliberately NO ``kind``/``engine``/``bus``/``audio_role``/
    ``group_name`` key: those were fictional-fixture inventions.
    """
    return [
        {
            "swi": {"address": None, "map": "SAILSS_ADDRESS_FILE_SW",
                    "name": "SAILSS_QUPV3_1_SE4"},
            "se_number": 4, "group": "SAIL", "wrapper_id": 1,
            "i2c": True, "spi": True, "uart": True,
            "instance": "u_sailss.u_sailss_top.u_hm_tile_ios."
                        "u_sm_tile_ios.u_qupv3_wrapper_0",
        },
        {
            "swi": {"address": None, "map": "ARM_ADDRESS_FILE_SW",
                    "name": "QUPV3_0_SE4"},
            "se_number": 4, "group": "TLMM", "wrapper_id": 2,
            "i2c": True, "spi": True, "uart": True,
            "instance": "u_qupv3_wrapper_0",
        },
        {
            "swi": {"address": None, "map": "ARM_ADDRESS_FILE_SW",
                    "name": "QUPV3_0_SE4"},
            "se_number": 4, "group": "TLMM", "wrapper_id": 3,
            "i2c": True, "spi": True, "uart": True,
            "instance": "u_qupv3_wrapper_1",
        },
        {
            "swi": {"address": None, "map": "ARM_ADDRESS_FILE_SW",
                    "name": "QUPV3_0_SE4"},
            "se_number": 4, "group": "TLMM", "wrapper_id": 4,
            "i2c": True, "spi": True, "uart": True,
            "instance": "u_qupv3_wrapper_2",
        },
    ]


def _real_shape_analysis() -> dict[str, Any]:
    """Analysis dict carrying the REAL ``chipio_get_qups`` payload.

    The payload lands under ``analysis["ipcat"]["chipio_get_qups"]`` — the
    real tool name, in the same ``ipcat`` section the pre-B2 fictional
    ``qup_controllers`` slot once occupied. The green B2 reader at
    ``orchestrator/source_ingest/endpoints.py`` walks exactly this key +
    the flat-list shape (per-entry ``swi`` / ``se_number`` / ``group`` /
    ``wrapper_id`` / capability booleans) and emits one ``EndpointFact``
    per SE record; every test below is green post-migration. The
    assertion messages keep the "if the reader returned SOURCE_UNRESOLVED
    it fell back to the fictional key" framing so a future regression
    that reintroduces the pre-B2 shape surfaces with the same diagnostic
    prose that led to the original green fix.
    """
    return {"ipcat": {"chipio_get_qups": _real_chipio_get_qups_payload()}, "dt": {}}


def _non_nord_shape_analysis() -> dict[str, Any]:
    """A NON-Nord payload of the SAME real shape, with foreign tokens.

    Generality guard (scope-lock #3): a correct reader parses the shape,
    not Nord's literal strings. Every token here is deliberately un-Nord
    — ``FAKESOC_QUPV9_7_SE1`` (swi.name), ``ZZTOP`` (group),
    ``se_number 1``, ``wrapper_id 9`` — so the derived endpoints can be
    asserted to carry THESE tokens and NONE of Nord's.
    """
    return {
        "ipcat": {
            "chipio_get_qups": [
                {
                    "swi": {"address": None, "map": "FAKESOC_ADDRESS_FILE_SW",
                            "name": "FAKESOC_QUPV9_7_SE1"},
                    "se_number": 1, "group": "ZZTOP", "wrapper_id": 9,
                    "i2c": True, "spi": False, "uart": False,
                    "instance": "u_fakesoc_wrapper_9",
                },
            ],
        },
        "dt": {},
    }


def _independent_flat_qup_authority() -> dict[str, Any]:
    """Independent ``chipio_get_qups`` authority snapshot for T-SRC-B2-2.

    Hand-authored as the IPCAT catalog would be *dumped* — NOT a copy of
    the derived endpoint list. Aligns with the derived codec-control claim
    on ``se_number == 4`` only because it describes the same physical SE.
    The authority's capability set on ``se_number == 4`` is ``uart``-only
    (no ``i2c``), which DIFFERS from the derived codec-control SE's
    ``i2c=True``. Per ``_t4a_lookup_qup`` (``crossverify.py:1701``), a hit
    where the claim declares ``cap='i2c'`` but the authority row's
    ``row_caps={'uart'}`` does not contain it lands PARTIAL_MATCH at
    ``crossverify.py:2014`` (cap-divergence rule). PARTIAL_MATCH opens the
    gate per ``_GATING_OPEN_VERDICTS``. Includes a foreign SE
    (``se_number 9``) with no derived counterpart, proving the authority
    was authored on its own terms.
    """
    return {
        "chip": "nordschleife_2.0",
        "tools": {
            "chipio_get_qups": {
                "status": "ok",
                "payload": [
                    {"engine": "QUPv3_0_SE_4", "se_number": 4, "uart": True},
                    {"engine": "QUPv3_2_SE_9", "se_number": 9, "uart": True},
                ],
            },
        },
    }


# Nord tokens the generality guard forbids in a non-Nord derivation.
_NORD_TOKENS = ("QUPV3_0_SE4", "SAILSS_QUPV3_1_SE4", "nordschleife",
                "u_qupv3_wrapper", "TLMM", "SAIL")


# --------------------------------------------------------------------------- #
# T-SRC-B2-1: reader consumes the REAL chipio_get_qups shape
# --------------------------------------------------------------------------- #
class TestReaderConsumesRealQupShape(unittest.TestCase):
    """T-SRC-B2-1: derive_endpoints_from_ipcat reads the real key path."""

    def test_real_chipio_get_qups_yields_non_empty_endpoints(self) -> None:
        from orchestrator.source_ingest.endpoints import (
            SOURCE_UNRESOLVED,
            EndpointFact,
            derive_endpoints_from_ipcat,
        )

        analysis = _real_shape_analysis()
        facts = derive_endpoints_from_ipcat(analysis)

        if facts is SOURCE_UNRESOLVED:
            raise AssertionError(
                "T-SRC-B2-1: derive_endpoints_from_ipcat returned "
                "SOURCE_UNRESOLVED on the REAL chipio_get_qups payload. "
                "The reader still reads the fictional "
                "`analysis['ipcat']['qup_controllers']` key "
                "(endpoints.py:202) and ignores the real "
                "`analysis['ipcat']['chipio_get_qups']` flat list. WP-SRC-B2 "
                "green must read the real shape (swi.name / se_number / "
                "group / wrapper_id / i2c) so real Nord --onboard populates "
                "audio_topology['endpoints'] and the T4a.qup.* gate can open."
            )
        if not isinstance(facts, list) or not facts:
            raise AssertionError(
                "T-SRC-B2-1: the real chipio_get_qups payload must derive a "
                f"non-empty list[EndpointFact]; got {facts!r}."
            )
        for f in facts:
            if not isinstance(f, EndpointFact):
                raise AssertionError(
                    "T-SRC-B2-1: every derived fact must be an EndpointFact; "
                    f"got {type(f).__name__}."
                )

        # Additive tightening (WP-SRC-B2): non-empty is not enough — a green
        # reader could emit empty-shell EndpointFacts and pass. Assert the
        # derived facts carry BOTH the real swi.name token AND the real
        # se_number field off the chipio_get_qups payload.
        blob = repr([f.to_dict() for f in facts])
        if "QUPV3_0_SE4" not in blob:
            raise AssertionError(
                "T-SRC-B2-1: derived facts do not carry the real swi.name "
                "token 'QUPV3_0_SE4' (the codec-control SE). Green may be "
                f"emitting empty-shell EndpointFacts. Derived: {blob}"
            )
        if not any(getattr(f, "se_number", None) == 4 for f in facts):
            raise AssertionError(
                "T-SRC-B2-1: no derived fact carries se_number == 4 (the "
                "codec-control SE). The real se_number field is not being "
                f"read off the chipio_get_qups payload. Derived: {blob}"
            )


# --------------------------------------------------------------------------- #
# T-SRC-B2-2: a T4a.qup.* row opens on the real shape (open-on-PARTIAL)
# --------------------------------------------------------------------------- #
class TestRealShapeOpensT4aGate(unittest.TestCase):
    """T-SRC-B2-2: real endpoints -> track_t4a -> an OPEN T4a.qup.* row."""

    def test_real_endpoints_open_t4a_gate_on_partial_match(self) -> None:
        from orchestrator.source_ingest.endpoints import (
            SOURCE_UNRESOLVED,
            derive_endpoints_from_ipcat,
        )
        from orchestrator.reasoning.crossverify import track_t4a
        from orchestrator.generation.model import TrustedFacts

        endpoints = derive_endpoints_from_ipcat(_real_shape_analysis())
        if endpoints is SOURCE_UNRESOLVED:
            raise AssertionError(
                "T-SRC-B2-2: derive_endpoints_from_ipcat returned "
                "SOURCE_UNRESOLVED on the real shape, so track_t4a has no "
                "source claims to cross-verify. Reader must read "
                "`ipcat.chipio_get_qups` (see T-SRC-B2-1)."
            )

        # Independent authority — NOT the derived list echoed back. Aligns
        # on se_number == 4 (the codec-control SE) -> PARTIAL_MATCH -> open.
        rows = track_t4a(snapshot=_independent_flat_qup_authority(),
                         endpoints=endpoints)

        if not isinstance(rows, list) or not rows:
            raise AssertionError(
                "T-SRC-B2-2: track_t4a on real-shape endpoints must emit a "
                f"non-empty row list; got {rows!r}."
            )

        rows_by_key: dict[str, Any] = {}
        for row in rows:
            subject = getattr(row, "subject", None)
            if not isinstance(subject, str) or not subject.startswith("qup."):
                raise AssertionError(
                    "T-SRC-B2-2: every track_t4a row must carry a `qup.` "
                    f"(dot) subject; got {subject!r}."
                )
            rows_by_key[f"T4a.{subject}"] = row

        gate = TrustedFacts(rows_by_track_subject=rows_by_key)
        any_open = any(
            gate.is_open("T4a", key[len("T4a."):]) for key in rows_by_key
        )
        if not any_open:
            raise AssertionError(
                "T-SRC-B2-2: at least one T4a.qup.<label> row must be OPEN "
                "(MATCH or PARTIAL_MATCH per _GATING_OPEN_VERDICTS, "
                "model.py:46) once real endpoints are populated. All rows "
                f"were CLOSED. Rows: {list(rows_by_key)}"
            )

        # Additive tightening (WP-SRC-B2): open-on-PARTIAL must be proven
        # specifically PARTIAL_MATCH via se_number alignment + cap
        # divergence, not merely "some verdict in _GATING_OPEN_VERDICTS".
        # The authority row for ``se_number == 4`` lists ``uart`` only
        # (no ``i2c``); the derived codec-control SE claims ``cap='i2c'``.
        # Per ``_t4a_lookup_qup`` (``crossverify.py:1701``), a hit where
        # ``claim_cap not in row_caps`` yields PARTIAL_MATCH at
        # ``crossverify.py:2014``. A MATCH here would mean either the
        # authority was echoed back OR the cap-divergence rule failed to
        # fire.
        open_keys = [key for key in rows_by_key
                     if gate.is_open("T4a", key[len("T4a."):])]

        # Field-absence is a DISTINCT root cause from "opened, but not on
        # PARTIAL" — fail loudly and separately rather than swallowing a
        # renamed/missing `verdict` into the PARTIAL branch below.
        missing_verdict = [
            key for key in open_keys
            if not isinstance(getattr(rows_by_key[key], "verdict", None), str)
        ]
        if missing_verdict:
            raise AssertionError(
                "T-SRC-B2-2: an OPEN T4a.qup.<label> row is missing a string "
                "`verdict` field (absent or renamed) — cannot assert "
                "PARTIAL_MATCH. VerificationRow.verdict must be the bare str "
                "checked at crossverify_model.py:141. Offending open rows: "
                f"{missing_verdict}"
            )

        open_partial = [
            key for key in open_keys
            if rows_by_key[key].verdict == "PARTIAL_MATCH"
        ]
        if not open_partial:
            open_verdicts = {key: rows_by_key[key].verdict for key in open_keys}
            raise AssertionError(
                "T-SRC-B2-2: a T4a.qup.<label> row opened, but NONE opened on "
                "PARTIAL_MATCH via se_number alignment — open-on-PARTIAL is "
                f"unproven. OPEN rows and their verdicts: {open_verdicts}"
            )


# --------------------------------------------------------------------------- #
# T-SRC-B2-GENERALITY: non-Nord payload yields non-Nord endpoints
# --------------------------------------------------------------------------- #
class TestReaderIsNotNordBaked(unittest.TestCase):
    """T-SRC-B2-GENERALITY: parse the shape, not Nord's literal tokens."""

    def test_non_nord_payload_yields_that_payloads_tokens(self) -> None:
        from orchestrator.source_ingest.endpoints import (
            SOURCE_UNRESOLVED,
            derive_endpoints_from_ipcat,
        )

        facts = derive_endpoints_from_ipcat(_non_nord_shape_analysis())

        if facts is SOURCE_UNRESOLVED:
            raise AssertionError(
                "T-SRC-B2-GENERALITY: derive_endpoints_from_ipcat returned "
                "SOURCE_UNRESOLVED on a non-Nord payload of the real shape. "
                "The reader must parse the chipio_get_qups shape generically "
                "(same failure as T-SRC-B2-1: it still reads the fictional "
                "qup_controllers key)."
            )
        if not isinstance(facts, list) or not facts:
            raise AssertionError(
                "T-SRC-B2-GENERALITY: a non-Nord payload of the real shape "
                f"must derive a non-empty list[EndpointFact]; got {facts!r}."
            )

        # The derived facts must carry the FOREIGN tokens...
        blob = repr([f.to_dict() for f in facts])
        if "FAKESOC_QUPV9_7_SE1" not in blob and "ZZTOP" not in blob:
            raise AssertionError(
                "T-SRC-B2-GENERALITY: derived endpoints do not carry the "
                "non-Nord payload's tokens (expected FAKESOC_QUPV9_7_SE1 / "
                f"ZZTOP). The reader is not shape-generic. Derived: {blob}"
            )
        # ...and NONE of Nord's (would prove a hardcoded Nord derivation).
        for tok in _NORD_TOKENS:
            if tok in blob:
                raise AssertionError(
                    "T-SRC-B2-GENERALITY: derived endpoints for a non-Nord "
                    f"payload leaked the Nord token {tok!r} — the reader is "
                    f"Nord-baked (the fifth G-3A.13 surface). Derived: {blob}"
                )


if __name__ == "__main__":
    unittest.main()
