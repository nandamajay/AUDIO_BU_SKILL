"""Phase-2B WP7 — tests for the generation registry module.

Pure, stdlib-only tests over ``orchestrator.generation.registry``. Mirrors the
Phase-2A + WP1a test discipline: inline data, no fakes, no network, no pytest.

Seven tests per PHASE2B_SPECIFICATION.md §WP7 (registry framework):

  1. ``test_register_generator_records_artifact_class``
  2. ``test_double_register_generator_raises``
  3. ``test_order_slot_collision_raises``
  4. ``test_double_register_skip_reason_raises``
  5. ``test_double_register_advisory_row_raises``
  6. ``test_double_register_known_bad_rule_raises``
  7. ``test_double_register_value_flattener_raises``

Discipline: every decorator (``@register_generator``, ``@register_skip_reason``,
``@register_advisory_row``, ``@register_known_bad_rule``,
``@register_value_flattener``) raises ``ValueError`` on double-register. This
is the WP7 locked "no silent overwrite" rule — a rebind at import time is
almost always a real bug (two generators claiming the same artifact_class, a
copy-paste of a skip reason, a flattener pattern collision).

The already-registered production entries (``dt_scaffolding`` / ``codec_stub``
/ ``machine_driver`` / ``audioreach_topology`` generators, the eleven
config-owned skip reasons, ``("T4b", "*")`` advisory, the ``t5.donor.firmware.sa8775p``
known-bad rule, the ``"count"`` value flattener) are used as the "already
registered" fixture — no monkey-patching, no reset — because the whole
point of the discipline is that these registrations are load-bearing and
must not be silently rebindable.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_registry``
"""

from __future__ import annotations

from orchestrator.generation import registry as gen_registry
from orchestrator.generation.registry import (
    ensure_generators_loaded,
    generator_order,
    register_advisory_row,
    register_generator,
    register_known_bad_rule,
    register_skip_reason,
    register_value_flattener,
)


# ── 1. register_generator records artifact_class + order ────────────────────


def test_register_generator_records_artifact_class() -> None:
    """The four WP3-WP6 generators must appear in the registry in canonical order.

    After ``ensure_generators_loaded()`` runs, ``generator_order()`` must
    return a tuple that includes all four production artifact classes, and
    they must appear in the WP1b-locked order (dt_scaffolding → codec_stub →
    machine_driver → audioreach_topology). This is the load-bearing
    contract: the runner iterates ``_GENERATION_ARTIFACT_ORDER`` in emit
    order, so a re-ordered registry silently reshuffles the four lanes.

    Because ``generator_order`` sorts by the per-generator ``order``
    integer parameter (NOT by import/registration order), this test also
    proves the sort key is correct — a bug where two orderings tie would
    surface as a non-deterministic tuple on rerun.
    """
    ensure_generators_loaded()
    order = generator_order()
    expected = (
        "dt_scaffolding",
        "codec_stub",
        "machine_driver",
        "audioreach_topology",
    )
    assert order == expected, (
        f"generator_order drift: got {order!r}, expected {expected!r}"
    )
    print("PASS: register_generator records all four artifact classes in canonical order")


# ── 2. Double-register generator raises ValueError ──────────────────────────


def test_double_register_generator_raises() -> None:
    """Re-registering an artifact_class must raise ValueError.

    The four WP3-WP6 generators are already registered at import time. A
    hostile re-decoration (or a copy-paste bug that duplicates the class
    name) MUST fail loudly rather than silently rebind. The error message
    must name the artifact class so the offending decoration is easy to
    locate.
    """
    ensure_generators_loaded()

    raised = False
    try:
        @register_generator(
            "dt_scaffolding",
            order=99,
            gating_rows=(("T5", "dts.firmware"),),
        )
        def _rebind(facts, kb=None):  # pragma: no cover — must not run
            raise AssertionError("must not reach")
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "dt_scaffolding" in message, (
            f"error message must name the artifact class; got: {message!r}"
        )

    assert raised, (
        "expected ValueError from re-registering 'dt_scaffolding'; nothing was raised"
    )
    print("PASS: double-register generator raises ValueError naming the artifact_class")


# ── 3. Order-slot collision raises ValueError ───────────────────────────────


def test_order_slot_collision_raises() -> None:
    """Two generators cannot occupy the same ``order`` integer.

    The order slots for the four production generators are 0..3. Attempting
    to register a NEW artifact_class at an already-taken slot must raise
    ValueError. This catches the "add a fifth lane, forget to bump order"
    bug at import time.
    """
    ensure_generators_loaded()

    raised = False
    try:
        @register_generator(
            "collision_lane",
            order=0,  # taken by dt_scaffolding
            gating_rows=(("T5", "dts.firmware"),),
        )
        def _collision(facts, kb=None):  # pragma: no cover — must not run
            raise AssertionError("must not reach")
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "0" in message and "dt_scaffolding" in message, (
            f"error message must name the colliding slot ({0}) and the existing "
            f"generator ('dt_scaffolding'); got: {message!r}"
        )

    assert raised, (
        "expected ValueError from registering at taken order slot 0; nothing was raised"
    )
    print("PASS: order-slot collision raises ValueError naming slot + incumbent")


# ── 4. Double-register skip reason raises ValueError ────────────────────────


def test_double_register_skip_reason_raises() -> None:
    """Re-registering a skip reason must raise ValueError.

    ``config.py`` registers eleven skip reasons at import time. Any second
    call — even from within the same module, even with the same string —
    must raise. This is the guard that catches "copy-pasted the string and
    forgot to change it".
    """
    raised = False
    try:
        register_skip_reason("gating_row_warning")  # already registered by config.py
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "gating_row_warning" in message, (
            f"error message must name the reason; got: {message!r}"
        )
    assert raised, (
        "expected ValueError from re-registering 'gating_row_warning'; nothing was raised"
    )
    print("PASS: double-register skip reason raises ValueError naming the reason")


# ── 5. Double-register advisory row raises ValueError ───────────────────────


def test_double_register_advisory_row_raises() -> None:
    """Re-registering an ``(track, subject)`` advisory pair must raise.

    ``config.py`` registers ``("T4b", "*")`` at import time. Any second
    call with the same pair must raise ValueError naming the pair so the
    offending call site is easy to locate.
    """
    raised = False
    try:
        register_advisory_row("T4b", "*")  # already registered
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "T4b" in message and "*" in message, (
            f"error message must name the (track, subject) pair; got: {message!r}"
        )
    assert raised, (
        "expected ValueError from re-registering ('T4b', '*'); nothing was raised"
    )
    print("PASS: double-register advisory row raises ValueError naming the pair")


# ── 6. Double-register known-bad rule raises ValueError ─────────────────────


def test_double_register_known_bad_rule_raises() -> None:
    """Re-registering a known-bad PARTIAL_MATCH rule id must raise.

    ``config.py`` registers ``t5.donor.firmware.sa8775p`` at import time.
    Any second call with the same rule_id must raise ValueError. This
    catches a stale-rule duplication (or a rename that leaves the old
    literal behind).
    """
    raised = False
    try:
        register_known_bad_rule("t5.donor.firmware.sa8775p")
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "t5.donor.firmware.sa8775p" in message, (
            f"error message must name the rule_id; got: {message!r}"
        )
    assert raised, (
        "expected ValueError from re-registering rule id; nothing was raised"
    )
    print("PASS: double-register known-bad rule raises ValueError naming the rule_id")


# ── 7. Double-register value flattener raises ValueError ────────────────────


def test_double_register_value_flattener_raises() -> None:
    """Re-registering a value-flattener pattern must raise.

    ``registry.py`` registers the ``"count"`` flattener at module import.
    A second decoration with the same pattern must raise ValueError. No
    live consumer exists today (WP7 locked C — registry built, deferred
    activation), but the discipline is enforced now so a later consumer
    cannot silently be replaced.
    """
    raised = False
    try:
        @register_value_flattener("count")
        def _rebind(value):  # pragma: no cover — must not run
            raise AssertionError("must not reach")
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "count" in message, (
            f"error message must name the pattern; got: {message!r}"
        )
    assert raised, (
        "expected ValueError from re-registering 'count' flattener; nothing was raised"
    )
    print("PASS: double-register value flattener raises ValueError naming the pattern")


def main() -> None:
    test_register_generator_records_artifact_class()    # 1
    test_double_register_generator_raises()             # 2
    test_order_slot_collision_raises()                  # 3
    test_double_register_skip_reason_raises()           # 4
    test_double_register_advisory_row_raises()          # 5
    test_double_register_known_bad_rule_raises()        # 6
    test_double_register_value_flattener_raises()       # 7
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
