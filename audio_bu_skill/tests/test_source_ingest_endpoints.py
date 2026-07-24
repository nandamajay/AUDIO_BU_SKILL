"""WP-SRC-B red baseline: QUP endpoint ingestion + T4a separator reconcile.

Test-first per PHASE3A_IMPLEMENTATION_PLAN.md §5a. This module lands
the failing contract for the endpoint producer + T4a producer/gate
separator reconciliation that jointly (with WP-SRC-A1+A2 already
landed) flips ``machine_driver`` AND ``codec_stub`` from 0→1 on real
Nord — moving the north-star scorecard 1/4 → 3/4.

Contract pinned by WP-SRC-B (PHASE3A_IMPLEMENTATION_PLAN.md §4
WP-SRC-B; docs/PHASE3_KNOWN_GAPS.md G-3A.7 T4a half):

  * T-SRC-B-1: ``derive_endpoints_from_ipcat(analysis)`` exists in
    ``orchestrator.source_ingest.endpoints`` and returns a non-empty
    ``list[EndpointFact]`` on a QUP-populated analysis fixture.
    GREEN since the producer landed at 3fde67b.
  * T-SRC-B-2: **SEPARATOR RECONCILE.** Populated endpoints must
    produce a ``track_t4a`` row whose ``subject`` STARTS WITH
    ``"qup."`` (dot separator) — NOT ``"qup:"`` (colon). The full
    key ``"T4a." + subject`` must be lookupable in the
    ``TrustedFacts.rows_by_track_subject`` dict AND
    ``gate.is_open("T4a", subject)`` must return ``True``. This is
    the direct assertion that the current producer↔gate mismatch
    (``crossverify.py:1743-1754`` emits colon; ``machine_driver.py:229``
    and ``codec_stub.py:214`` scan the dot prefix) is resolved.
    Red today because the producer still emits colon form.
  * T-SRC-B-3: **JOINT FLIP integration.** On a fixture profile
    carrying populated ``audio_topology.pinmux`` (WP-SRC-A1/A2
    output) AND populated ``audio_topology.endpoints`` AND the
    separator reconciled, both the ``machine_driver`` and
    ``codec_stub`` generators must report OPEN gates (no
    ``GeneratorSkipped`` on ``T4a.qup.*``). Red today because
    endpoints are absent AND the producer emits colon-form
    subjects.
  * T-SRC-B-4: underivable / empty endpoints input →
    ``derive_endpoints_from_ipcat`` returns the
    ``SOURCE_UNRESOLVED`` bare-singleton sentinel — same Design B
    contract as WP-SRC-A1. GREEN since the producer landed at 3fde67b.
  * T-SRC-B-5: determinism — two invocations of
    ``derive_endpoints_from_ipcat`` on the same analysis fixture
    produce byte-identical dicts under
    ``json.dumps(..., sort_keys=True)``. Mirrors T-SRC-A-4 /
    T-SRC-A2-4 discipline. GREEN since the producer landed at 3fde67b.

Failure discipline (§5a): each test guards its import in
``try / except ImportError`` and raises ``AssertionError`` naming
the exact missing surface — module, function, or attribute — so the
red-state pytest output identifies the T-SRC-B-N test AND the
missing symbol in one line. This is the sibling idiom to
``tests/test_source_ingest_pinmux.py`` and
``tests/test_source_ingest_dt_reader.py``.

Explicitly out of scope for this red-baseline commit:
  * Any implementation of the endpoints producer — ships in a
    follow-up green commit.
  * The separator reconcile decision (producer-side ``qup.`` swap
    vs gate-side ``qup:`` acceptance) — that decision is recorded
    in the follow-up commit message.
  * Any change to ``main.py``, ``machine_driver.py``,
    ``codec_stub.py``, ``crossverify.py``, or the onboarding runner
    — this file is red-baseline only.
  * ``codec_driver_porting`` — G-3A.8, deferred out-of-band.
  * WP-SRC-C DTS / T5 producer↔gate reconcile — separate WP.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_source_ingest_endpoints``
or ``cd audio_bu_skill && python3 -m pytest tests/test_source_ingest_endpoints.py -v``.

Signed-off-by: Ajay Kumar Nandam <ajayn@qti.qualcomm.com>
"""

from __future__ import annotations

import json
import unittest
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures — synthetic QUP-populated analysis and joint-flip profile
# ---------------------------------------------------------------------------


def _qup_populated_analysis() -> dict[str, Any]:
    """Return a synthetic analysis dict carrying QUP-controller endpoint claims.

    Shape matches what the WP-SRC-A2 wiring commit's ``analysis`` mapping
    already carries on real ``--onboard`` runs after IPCAT enrichment:
    an ``ipcat`` section with ``qup_controllers`` listing each SE by
    instance / engine name and the audio bus it services. The producer
    under test is expected to walk this shape (or a compatible one it
    defines) and emit ``EndpointFact`` entries for each I2S/I2C bus
    endpoint the machine driver must own.

    Two SEs are included so T-SRC-B-1 can assert a non-empty list AND
    T-SRC-B-2/3 can key on a specific subject.
    """
    return {
        "ipcat": {
            "qup_controllers": [
                {
                    "kind": "qup",
                    "engine": "QUPv3_0_SE_5",
                    "instance": "qup_0_se5",
                    "bus": "i2s",
                    "audio_role": "primary_i2s",
                    "se_number": 5,
                    "group_name": "qup_0",
                },
                {
                    "kind": "qup",
                    "engine": "QUPv3_1_SE_2",
                    "instance": "qup_1_se2",
                    "bus": "i2c",
                    "audio_role": "codec_control",
                    "se_number": 2,
                    "group_name": "qup_1",
                },
            ],
        },
        "dt": {},
    }


def _joint_flip_profile() -> dict[str, Any]:
    """Return a synthetic profile carrying populated pinmux + endpoints.

    Used by T-SRC-B-3 to exercise the two joint-flip generators
    (``machine_driver``, ``codec_stub``) end-to-end. The pinmux entries
    are the WP-SRC-A1/A2 output shape (``gpio.i2s.<role>``); the
    endpoints entries are the WP-SRC-B producer output shape and MUST
    key ``track_t4a`` rows on ``qup.<label>`` (dot separator) — the
    reconciled form the two generators' gates scan for.
    """
    return {
        "audio_topology": {
            "pinmux": [
                {"name": "gpio.i2s.mclk", "pin": 147, "function": 1, "role": "mclk"},
                {"name": "gpio.i2s.sclk", "pin": 148, "function": 1, "role": "sclk"},
                {"name": "gpio.i2s.ws", "pin": 149, "function": 1, "role": "ws"},
                {"name": "gpio.i2s.data", "pin": 150, "function": 1, "role": "data"},
            ],
            "endpoints": [
                {"name": "qup.qup_0_se5", "kind": "qup", "bus": "i2s", "role": "primary_i2s"},
                {"name": "qup.qup_1_se2", "kind": "qup", "bus": "i2c", "role": "codec_control"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# T-SRC-B-1: producer exists, returns non-empty list on QUP-populated input
# ---------------------------------------------------------------------------


class TestDeriveEndpointsContract(unittest.TestCase):
    """T-SRC-B-1: derive_endpoints_from_ipcat exists and returns endpoints."""

    def test_derive_endpoints_returns_non_empty_list(self) -> None:
        try:
            from orchestrator.source_ingest.endpoints import (  # type: ignore[attr-defined]
                EndpointFact,
                derive_endpoints_from_ipcat,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-1: expected `derive_endpoints_from_ipcat(analysis) "
                "-> list[EndpointFact] | SOURCE_UNRESOLVED` in "
                "`orchestrator.source_ingest.endpoints`. This module does "
                "not exist yet — WP-SRC-B red baseline. The producer must "
                "walk `analysis['ipcat']['qup_controllers']` (or a "
                "compatible shape) and emit one `EndpointFact` per audio "
                "bus endpoint so `track_t4a` can produce `T4a.qup.<label>` "
                "MATCH rows on real Nord/Eliza. This closes the T4a half "
                f"of G-3A.7. ImportError: {exc}"
            ) from exc

        analysis = _qup_populated_analysis()
        facts = derive_endpoints_from_ipcat(analysis)

        if not isinstance(facts, list) or not facts:
            raise AssertionError(
                "T-SRC-B-1: derive_endpoints_from_ipcat on a QUP-populated "
                "analysis must return a non-empty `list[EndpointFact]`; "
                f"got {facts!r}."
            )
        for f in facts:
            if not isinstance(f, EndpointFact):
                raise AssertionError(
                    "T-SRC-B-1: every emitted fact must be an "
                    f"`EndpointFact` instance; got {type(f).__name__}."
                )


# ---------------------------------------------------------------------------
# T-SRC-B-2: separator reconcile — track_t4a subject uses dot, not colon
# ---------------------------------------------------------------------------


class TestT4aSeparatorReconcile(unittest.TestCase):
    """T-SRC-B-2: producer↔gate separator is `qup.` (dot) — not `qup:`."""

    def test_t4a_row_subject_uses_dot_separator_and_is_open(self) -> None:
        try:
            from orchestrator.source_ingest.endpoints import (  # type: ignore[attr-defined]
                derive_endpoints_from_ipcat,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-2: expected `derive_endpoints_from_ipcat` in "
                "`orchestrator.source_ingest.endpoints` — the producer "
                "whose output must be plumbed into `track_t4a` such that "
                "the row `subject` starts with `qup.` (dot), NOT `qup:` "
                "(colon). Producer at `crossverify.py:1743-1754` currently "
                "emits colon form; gates at `machine_driver.py:229` and "
                "`codec_stub.py:214` scan the `T4a.qup.` prefix. "
                f"ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.reasoning.crossverify import track_t4a
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-2: prerequisite import of `track_t4a` from "
                "`orchestrator.reasoning.crossverify` failed — the T4a "
                "producer must exist for the separator reconcile assertion "
                f"to be meaningful. ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.generation.model import TrustedFacts
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-2: prerequisite import of `TrustedFacts` from "
                "`orchestrator.generation.model` failed — the gate needs "
                f"to exist so `is_open` can be exercised. ImportError: {exc}"
            ) from exc

        analysis = _qup_populated_analysis()
        endpoints = derive_endpoints_from_ipcat(analysis)

        try:
            rows = track_t4a(analysis=analysis, endpoints=endpoints)
        except TypeError as exc:
            raise AssertionError(
                "T-SRC-B-2: `track_t4a` signature must accept the "
                "WP-SRC-B endpoint list as input (e.g. via an "
                "`endpoints=` kwarg or an `analysis['audio_topology']"
                "['endpoints']` lookup). Producer wiring is part of the "
                f"WP-SRC-B green commit. TypeError: {exc}"
            ) from exc

        if not isinstance(rows, list) or not rows:
            raise AssertionError(
                "T-SRC-B-2: `track_t4a` on populated endpoints must emit "
                f"a non-empty row list; got {rows!r}."
            )

        rows_by_key: dict[str, Any] = {}
        for row in rows:
            subject = getattr(row, "subject", None)
            if not isinstance(subject, str):
                raise AssertionError(
                    "T-SRC-B-2: every track_t4a row must carry a string "
                    f"`subject`; got {subject!r}."
                )
            if subject.startswith("qup:"):
                raise AssertionError(
                    "T-SRC-B-2: SEPARATOR RECONCILE — track_t4a emitted a "
                    f"row with legacy colon subject {subject!r}. The "
                    "producer must swap `qup:<label>` → `qup.<label>` (or "
                    "the gates must accept both) so the row keys match "
                    "the `T4a.qup.` prefix scan at machine_driver.py:229 "
                    "and codec_stub.py:214. G-3A.7 T4a half still open."
                )
            if not subject.startswith("qup."):
                raise AssertionError(
                    "T-SRC-B-2: every track_t4a row emitted from WP-SRC-B "
                    "endpoints must have a `qup.` prefixed subject; got "
                    f"{subject!r}."
                )
            rows_by_key[f"T4a.{subject}"] = row

        gate = TrustedFacts(rows_by_track_subject=rows_by_key)
        any_open = False
        for full_key in rows_by_key:
            subject = full_key[len("T4a."):]
            if gate.is_open("T4a", subject):
                any_open = True
                break
        if not any_open:
            raise AssertionError(
                "T-SRC-B-2: at least one `T4a.qup.<label>` row must be "
                "OPEN once endpoints are populated AND the separator is "
                "reconciled. All emitted rows were CLOSED — the "
                f"reconcile is incomplete. Rows: {list(rows_by_key)}"
            )


# ---------------------------------------------------------------------------
# T-SRC-B-3: joint flip — machine_driver AND codec_stub open on Nord fixture
# ---------------------------------------------------------------------------


class TestJointFlipMachineDriverAndCodecStub(unittest.TestCase):
    """T-SRC-B-3: A1+A2+B fixture flips both joint-triple generators."""

    def test_both_generators_open_on_joint_fixture(self) -> None:
        try:
            from orchestrator.source_ingest.endpoints import (  # type: ignore[attr-defined]
                derive_endpoints_from_ipcat,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-3: expected `derive_endpoints_from_ipcat` in "
                "`orchestrator.source_ingest.endpoints`. WP-SRC-B red "
                f"baseline: module does not exist. ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.runners.machine_driver_generation_runner import (
                run_machine_driver_generation,
            )
            from orchestrator.runners.codec_generation_runner import (
                run_codec_stub_generation,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-3: prerequisite import of `run_machine_driver_generation` "
                "and/or `run_codec_stub_generation` failed — the joint-flip "
                "generators must exist for the north-star scorecard delta to "
                f"be assertable. ImportError: {exc}"
            ) from exc

        profile = _joint_flip_profile()
        analysis = _qup_populated_analysis()
        # Cross-verify plumbing: the joint-flip fixture MUST expose the
        # separator-reconciled endpoints via the producer under test so
        # both generators see the same `T4a.qup.<label>` MATCH rows. If
        # the producer still emits colon form the join is a no-op and
        # this test fails at the gate assertions below — that failure is
        # T-SRC-B-3's red state at HEAD.
        _ = derive_endpoints_from_ipcat(analysis)

        try:
            md_result = run_machine_driver_generation(profile=profile, analysis=analysis)
        except TypeError as exc:
            raise AssertionError(
                "T-SRC-B-3: `run_machine_driver_generation` signature "
                "must accept `profile` and `analysis` kwargs so the "
                "joint-flip fixture can be exercised end-to-end. "
                f"TypeError: {exc}"
            ) from exc
        try:
            cs_result = run_codec_stub_generation(profile=profile, analysis=analysis)
        except TypeError as exc:
            raise AssertionError(
                "T-SRC-B-3: `run_codec_stub_generation` signature must "
                "accept `profile` and `analysis` kwargs so the joint-flip "
                f"fixture can be exercised end-to-end. TypeError: {exc}"
            ) from exc

        md_skipped = getattr(md_result, "skipped", None)
        if md_skipped is not None and md_skipped:
            raise AssertionError(
                "T-SRC-B-3: machine_driver generator was SKIPPED on the "
                "joint-flip fixture — WP-SRC-B did not open the "
                f"`T4a.qup.*` gate. Skip reason: {md_skipped!r}."
            )
        cs_skipped = getattr(cs_result, "skipped", None)
        if cs_skipped is not None and cs_skipped:
            raise AssertionError(
                "T-SRC-B-3: codec_stub generator was SKIPPED on the "
                "joint-flip fixture — WP-SRC-B did not open the "
                f"`T4a.qup.*` gate. Skip reason: {cs_skipped!r}."
            )


# ---------------------------------------------------------------------------
# T-SRC-B-4: underivable input → SOURCE_UNRESOLVED (Design B identity)
# ---------------------------------------------------------------------------


class TestDeriveEndpointsUnresolved(unittest.TestCase):
    """T-SRC-B-4: empty / underivable input → SOURCE_UNRESOLVED singleton."""

    def test_empty_analysis_returns_sentinel(self) -> None:
        try:
            from orchestrator.source_ingest.endpoints import (  # type: ignore[attr-defined]
                derive_endpoints_from_ipcat,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-4: expected `derive_endpoints_from_ipcat` in "
                "`orchestrator.source_ingest.endpoints` — the producer "
                "that must return the bare-singleton `SOURCE_UNRESOLVED` "
                "on empty / underivable input (Design B identity check, "
                f"mirrors T-SRC-A-3). ImportError: {exc}"
            ) from exc

        try:
            from orchestrator.source_ingest import SOURCE_UNRESOLVED
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-4: prerequisite import of `SOURCE_UNRESOLVED` "
                "from `orchestrator.source_ingest` failed — WP-SRC-A1 "
                f"must land before B can assert the sentinel contract. "
                f"ImportError: {exc}"
            ) from exc

        for empty in ({}, {"ipcat": {}}, {"ipcat": {"qup_controllers": []}}):
            result = derive_endpoints_from_ipcat(empty)
            if result is not SOURCE_UNRESOLVED:
                raise AssertionError(
                    "T-SRC-B-4: derive_endpoints_from_ipcat on empty / "
                    "underivable input must return the bare-singleton "
                    "`SOURCE_UNRESOLVED` (identity check, NOT a string "
                    f"literal); got {result!r} for input {empty!r}."
                )


# ---------------------------------------------------------------------------
# T-SRC-B-5: determinism — byte-identical output across invocations
# ---------------------------------------------------------------------------


class TestDeriveEndpointsDeterminism(unittest.TestCase):
    """T-SRC-B-5: two derivations on the same analysis are byte-identical."""

    def test_two_derivations_are_byte_identical(self) -> None:
        try:
            from orchestrator.source_ingest.endpoints import (  # type: ignore[attr-defined]
                derive_endpoints_from_ipcat,
            )
        except ImportError as exc:
            raise AssertionError(
                "T-SRC-B-5: expected `derive_endpoints_from_ipcat` in "
                "`orchestrator.source_ingest.endpoints` — the producer "
                "that must be deterministic across repeated invocations "
                "(sorted iteration, no time / uuid injection). "
                f"ImportError: {exc}"
            ) from exc

        analysis = _qup_populated_analysis()
        first = derive_endpoints_from_ipcat(analysis)
        second = derive_endpoints_from_ipcat(analysis)

        def _canonicalize(x: Any) -> bytes:
            # EndpointFact instances need to canonicalize to their
            # ordered field dict; fall back to `vars()` if the class
            # does not expose a `to_dict()` — either yields a JSON-able
            # mapping under `sort_keys=True`.
            if isinstance(x, list):
                payload = [
                    (item.to_dict() if hasattr(item, "to_dict") else vars(item))
                    for item in x
                ]
            else:
                payload = x
            return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")

        first_bytes = _canonicalize(first)
        second_bytes = _canonicalize(second)

        if first_bytes != second_bytes:
            raise AssertionError(
                "T-SRC-B-5: two invocations of derive_endpoints_from_ipcat "
                "on the same analysis fixture produced diverging canonical-"
                "JSON bytes. Producer must be deterministic — sorted "
                "iteration over ipcat rows, stable field order in each "
                "EndpointFact, no time / uuid / hash injection.\n"
                f"  first : {first_bytes!r}\n"
                f"  second: {second_bytes!r}"
            )


if __name__ == "__main__":
    unittest.main()
