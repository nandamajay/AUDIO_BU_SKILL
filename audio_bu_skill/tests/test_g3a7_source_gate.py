"""G-3A.7 source→gate probe for T1 and T4a (Task 2, "option c").

Isolates the *source side* of the north-star gating chain: given an
in-memory generated_case source list, does `track_t1` / `track_t4a` produce
rows, and after `project_facts` do those rows satisfy the machine_driver /
codec_stub `is_open` gates?

Historical note (pre-WP-SRC-B commit 2): this file used to pin the T4a
colon-vs-dot separator MISMATCH — the producer emitted
``T4a.qup:QUPv3_0_SE_5`` (colon) while the gates scanned ``T4a.qup.``
(dot), so a populated source could not open either the machine_driver
Gate-2 or the codec_stub Gate-1. Its docstring explicitly predicted the
reconcile: "if the producer/gate separators were reconciled, update this
test and G-3A.7."

Current state (post-reconcile): the T4a producer at
``crossverify.py:_t4a_subject`` emits DOT-separated subjects
(``qup.QUPv3_0_SE_5``), so the projected fact keys as
``T4a.qup.<label>`` — which DOES match the gate prefix. The two T4a
tests now assert the *positive* case: a populated QUP source both
produces a MATCH row AND opens the joint machine_driver / codec_stub
gate. T1 tests are unchanged (T1's colon/dot bug does not exist).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_g3a7_source_gate``
"""

from __future__ import annotations

from typing import Any

from orchestrator.reasoning.crossverify import track_t1, track_t4a
from orchestrator.generation.facts import project_facts

# Gate prefixes, imported-by-value from the generators under test so this
# test tracks whatever the generators actually scan.
from orchestrator.generation.machine_driver import (
    _rows_with_prefix as _md_rows_with_prefix,
)

_T1_GATE_PREFIX = "T1.gpio.i2s."
_T4A_GATE_PREFIX = "T4a.qup."


# ── Snapshot builders (pure, no I/O) ────────────────────────────────────────


def _t1_snap(*, pin: int, function: int, name: str) -> dict[str, Any]:
    """A DIRECT-authority T1 snapshot that MATCHes one (pin, function)."""
    return {
        "tools": {
            "gpio_get_gpio_map": {"status": "ok", "payload": {"gpio_map_id": 1}},
            "gpio_list_gpios_from_map": {
                "status": "ok",
                "payload": [{"number": pin, "function": function, "name": name}],
            },
        }
    }


def _t4a_snap(*, se_number: int, engine: str) -> dict[str, Any]:
    """A T4a snapshot whose chipio_get_qups answers one QUP endpoint."""
    return {
        "tools": {
            "chipio_get_qups": {
                "status": "ok",
                "payload": [
                    {"se_number": se_number, "engine": engine, "instance": f"qup{se_number}"}
                ],
            }
        }
    }


def _open_rows_for_prefix(rows: list, prefix: str) -> list:
    """Project rows and return the subset that are is_open under `prefix`.

    Mirrors exactly what the generators do: project_facts → _rows_with_prefix
    → filter by facts.is_open(track, subject).
    """
    facts = project_facts(rows)
    return [
        r
        for r in _md_rows_with_prefix(facts, prefix)
        if facts.is_open(r.track, r.subject)
    ]


# ── T1: empty source → zero rows ────────────────────────────────────────────


def test_t1_empty_source_yields_zero_rows() -> None:
    rows = track_t1(snapshot=_t1_snap(pin=147, function=1, name="gpio.i2s.mclk"), source=[])
    assert rows == [], f"T1 must short-circuit to [] on empty source; got {rows!r}"
    print("PASS: T1 empty source → 0 rows (short-circuit at crossverify.py:416-417)")


# ── T1: the TASK'S literal input does NOT open the gate (finding) ───────────


def test_t1_task_literal_input_does_not_open_gate() -> None:
    """`{"pin":147,"function":1}` (no name) → subject `? (GPIO 147)`, no match.

    Regression-guards the finding that the task-spec's proposed T1 input is
    wrong: it produces a row, but not one under the `T1.gpio.i2s.` namespace,
    so the machine_driver Gate-1 stays closed.
    """
    snap = _t1_snap(pin=147, function=1, name="gpio.i2s.mclk")
    rows = track_t1(snapshot=snap, source=[{"pin": 147, "function": 1}])
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    assert rows[0].subject == "? (GPIO 147)", (
        f"bare source (no name) must render subject '? (GPIO 147)'; "
        f"got {rows[0].subject!r}"
    )
    open_rows = _open_rows_for_prefix(rows, _T1_GATE_PREFIX)
    assert open_rows == [], (
        "task-literal T1 input must NOT open the machine_driver gate "
        f"(prefix {_T1_GATE_PREFIX!r}); got {[r.subject for r in open_rows]!r}"
    )
    print(
        "PASS: T1 task-literal {pin,function} → subject '? (GPIO 147)', "
        "does NOT match gate prefix (finding: task input needs a name)"
    )


# ── T1: CORRECTED input DOES open the machine_driver Gate-1 ─────────────────


def test_t1_named_source_opens_machine_driver_gate() -> None:
    """With `name="gpio.i2s.mclk"`, the row keys as `T1.gpio.i2s.mclk (GPIO 147)`
    and is_open → the machine_driver Gate-1 opens. This is the *satisfiable*
    positive case the task was reaching for."""
    snap = _t1_snap(pin=147, function=1, name="gpio.i2s.mclk")
    rows = track_t1(
        snapshot=snap,
        source=[{"pin": 147, "function": 1, "name": "gpio.i2s.mclk"}],
    )
    assert len(rows) >= 1, "expected ≥1 T1 row from populated source"
    open_rows = _open_rows_for_prefix(rows, _T1_GATE_PREFIX)
    assert len(open_rows) >= 1, (
        "populated+named T1 source must yield ≥1 open row under "
        f"{_T1_GATE_PREFIX!r}; got {[r.subject for r in rows]!r}"
    )
    assert all(r.verdict in ("MATCH", "PARTIAL_MATCH") for r in open_rows)
    print(
        "PASS: T1 named source → ≥1 open row for machine_driver gate "
        f"({[r.subject for r in open_rows]!r})"
    )


# ── T4a: empty source → zero rows ───────────────────────────────────────────


def test_t4a_empty_source_yields_zero_rows() -> None:
    rows = track_t4a(snapshot=_t4a_snap(se_number=5, engine="QUPv3_0_SE_5"), source=[])
    assert rows == [], f"T4a must short-circuit to [] on empty source; got {rows!r}"
    print("PASS: T4a empty source → 0 rows (short-circuit at crossverify.py:1816-1817)")


# ── T4a: populated source produces a row, but it CANNOT open the gate ───────


def test_t4a_populated_source_opens_gate_after_separator_reconcile() -> None:
    """POST-RECONCILE positive assertion for codec_stub / machine_driver T4a.

    A populated QUP endpoint DOES produce a MATCH row AND now opens the
    joint T4a gate: WP-SRC-B commit 2 reconciled the producer at
    ``crossverify.py:_t4a_subject`` from colon (``qup:QUPv3_0_SE_5``) to
    dot (``qup.QUPv3_0_SE_5``), so the projected fact keys as
    ``T4a.qup.<label>`` — which matches the ``T4a.qup.`` prefix scanned
    by both ``machine_driver.py:229`` and ``codec_stub.py:214``.

    This is the *reconciled* replacement for the historical G-3A.7
    finding-guard (see file docstring) that pinned the mismatch and told
    the reader to update this test and G-3A.7 when the separators were
    reconciled. That reconcile just happened.
    """
    snap = _t4a_snap(se_number=5, engine="QUPv3_0_SE_5")
    rows = track_t4a(
        snapshot=snap,
        source=[{"kind": "qup", "engine": "QUPv3_0_SE_5", "se_number": 5}],
    )
    assert len(rows) >= 1, "expected ≥1 T4a row from populated QUP source"
    assert any(r.verdict == "MATCH" for r in rows), (
        "populated T4a source with matching authority should MATCH; "
        f"got verdicts {[r.verdict for r in rows]!r}"
    )
    # Post-reconcile: producer emits DOT-separated subjects.
    facts = project_facts(rows)
    keys = sorted(facts.rows_by_track_subject)
    assert any(k.startswith("T4a.qup.") for k in keys), (
        f"reconciled producer must emit a dot-separated T4a.qup. key; got {keys!r}"
    )
    # Regression guard: no colon-form leak. If this fires, some code path
    # is still emitting the legacy colon separator.
    assert not any(k.startswith("T4a.qup:") for k in keys), (
        f"legacy colon-form key must be gone post-reconcile; got {keys!r}"
    )
    # ...and now the dot-prefixed gate opens.
    open_rows = _open_rows_for_prefix(rows, _T4A_GATE_PREFIX)
    assert len(open_rows) >= 1, (
        f"populated T4a source must open ≥1 row under gate {_T4A_GATE_PREFIX!r} "
        f"after separator reconcile; got {[r.subject for r in open_rows]!r} "
        f"(all keys: {keys!r})"
    )
    print(
        "PASS: T4a populated source → MATCH row keyed 'T4a.qup....' (dot), "
        "opens the joint machine_driver / codec_stub gate. G-3A.7 finding "
        "resolved by WP-SRC-B commit 2 producer-side separator reconcile."
    )


def main() -> None:
    test_t1_empty_source_yields_zero_rows()
    test_t1_task_literal_input_does_not_open_gate()
    test_t1_named_source_opens_machine_driver_gate()
    test_t4a_empty_source_yields_zero_rows()
    test_t4a_populated_source_opens_gate_after_separator_reconcile()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
