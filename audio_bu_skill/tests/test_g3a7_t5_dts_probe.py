"""G-3A.7 T5 dts probe (Task 2, "option b").

Exercises the *real* T5 source plumbing end-to-end: hand-place minimal DTS
under a temp `targets/<t>/dts/`, call `main._load_dts_files`, then
`track_t5`, then project into the dt_scaffolding gate.

Corrects the task-spec's proposed positive assertion. The spec asked for:
"non-empty valid dts → verdict transitions (MATCH/PARTIAL_MATCH), not NCC."
That is UNSATISFIABLE by the live producer: `track_t5`
(reasoning/crossverify.py:1312+) emits ONLY these verdicts —
`DISAGREE_WITH_AUTHORITY` (donor-leak rows, always warning=True) and
`NOT_CROSS_CHECKABLE` (revision-anchor / silicon-identity). It NEVER emits
`MATCH` or `PARTIAL_MATCH`, and it only ever emits a `dts.firmware` /
`dts.compatible` subject as a donor-LEAK (DISAGREE), never as a clean match.

Therefore the dt_scaffolding gate `is_open("T5","dts.firmware")`
(dt_scaffolding.py:213) is unsatisfiable from the live T5 producer regardless
of DTS content:
  - empty / benign DTS  → no `dts.firmware` row at all (gate: missing row);
  - firmware-leak DTS   → a `dts.firmware` row exists but verdict=DISAGREE
                          AND warning=True (gate: closed on verdict + warning).

This file asserts that ground truth so the finding is regression-guarded.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_g3a7_t5_dts_probe``
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from orchestrator.main import _load_dts_files
from orchestrator.reasoning.crossverify import track_t5
from orchestrator.generation.facts import project_facts


# ── Snapshot builders ───────────────────────────────────────────────────────


def _chips_ok(name: str) -> dict[str, Any]:
    """chips_list_chips answering one silicon identity by display name."""
    return {"tools": {"chips_list_chips": {"status": "ok", "payload": [{"name": name}]}}}


def _write_dts(target_dir: Path, filename: str, text: str) -> None:
    dts_dir = target_dir / "dts"
    dts_dir.mkdir(parents=True, exist_ok=True)
    (dts_dir / filename).write_text(text, encoding="utf-8")


# ── Empty dts dir → exactly one revision-anchor NCC row (NOT missing) ───────


def test_empty_dts_dir_yields_one_ncc_revision_anchor_row() -> None:
    """No DTS staged. `_load_dts_files` → [], `track_t5` does NOT short-circuit
    — it emits ONE NOT_CROSS_CHECKABLE 'revision_anchor' row (auth ok path).

    This is the mechanism distinction that G-3A.7 originally got wrong: T5 is
    NOT like T1/T4a (which return []). A row EXISTS; its verdict is NCC.
    """
    with tempfile.TemporaryDirectory() as td:
        target_dir = Path(td) / "eliza"
        target_dir.mkdir(parents=True)
        # deliberately do NOT create dts/ — exercise the missing-dir branch too
        dts = _load_dts_files(target_dir)
        assert dts == [], f"no dts dir must load []; got {dts!r}"

        rows = track_t5(snapshot=_chips_ok("sa8775p"), dts=dts)
        assert len(rows) == 1, f"empty DTS + auth ok → exactly 1 row; got {len(rows)}"
        row = rows[0]
        assert row.verdict == "NOT_CROSS_CHECKABLE", (
            f"empty DTS row must be NCC; got {row.verdict!r}"
        )
        assert row.coverage_gap_reason == "revision_not_pinned", (
            f"expected revision_not_pinned; got {row.coverage_gap_reason!r}"
        )
        print(
            "PASS: empty DTS → 1 NCC row (subject="
            f"{row.subject!r}, reason=revision_not_pinned) — NOT a missing row"
        )


# ── Non-empty DTS (firmware leak) → dts.firmware row EXISTS but is DISAGREE ──


def test_firmware_leak_dts_emits_disagree_not_match() -> None:
    """A DTS carrying an `sa8775p/....mbn` firmware string, cross-checked
    against a DIFFERENT authority family (sm8650), is a donor leak. T5 emits a
    `dts.firmware` row — the verdict TRANSITIONS away from NCC, exactly as the
    task asked — but it transitions to DISAGREE_WITH_AUTHORITY (warning=True),
    NOT to MATCH/PARTIAL_MATCH. The live producer cannot emit MATCH for T5.
    """
    with tempfile.TemporaryDirectory() as td:
        target_dir = Path(td) / "leaktarget"
        target_dir.mkdir(parents=True)
        _write_dts(
            target_dir,
            "audio.dtsi",
            'remoteproc { firmware-name = "sa8775p/adsp.mbn"; };',
        )
        dts = _load_dts_files(target_dir)
        assert dts and dts[0]["text"], "expected staged DTS to load with text"

        # authority family sm8650 != sa8775p → the sa8775p firmware string leaks
        rows = track_t5(snapshot=_chips_ok("sm8650"), dts=dts)
        subjects = {r.subject: r for r in rows}
        assert "dts.firmware" in subjects, (
            f"firmware-leak DTS must emit a dts.firmware row; got {list(subjects)!r}"
        )
        fw = subjects["dts.firmware"]
        assert fw.verdict != "NOT_CROSS_CHECKABLE", (
            "verdict must TRANSITION away from NCC on a populated leak DTS"
        )
        assert fw.verdict == "DISAGREE_WITH_AUTHORITY", (
            f"T5 firmware leak must be DISAGREE; got {fw.verdict!r}"
        )
        assert fw.warning is True, "donor-leak rows must carry warning=True"
        print(
            "PASS: firmware-leak DTS → dts.firmware row EXISTS, verdict "
            "transitions NCC→DISAGREE_WITH_AUTHORITY (warning=True), NOT MATCH"
        )


# ── The dt_scaffolding gate is unsatisfiable from the live T5 producer ──────


def test_dt_scaffolding_gate_unsatisfiable_from_live_t5() -> None:
    """Whatever the DTS, `is_open("T5","dts.firmware")` stays False.

    - benign DTS (no leak, no revision pin) → no dts.firmware row → gate closed
      on a MISSING row;
    - firmware-leak DTS → dts.firmware row present but DISAGREE+warning → gate
      closed on verdict+warning.
    """
    with tempfile.TemporaryDirectory() as td:
        # Case A: benign DTS, no donor leak (matching family → no leak fired)
        ta = Path(td) / "benign"
        ta.mkdir(parents=True)
        _write_dts(ta, "b.dtsi", 'soc { status = "okay"; };')
        rows_a = track_t5(snapshot=_chips_ok("sa8775p"), dts=_load_dts_files(ta))
        facts_a = project_facts(rows_a)
        assert facts_a.is_open("T5", "dts.firmware") is False, (
            "benign DTS must leave dt_scaffolding firmware gate closed"
        )
        assert "T5.dts.firmware" not in facts_a.rows_by_track_subject, (
            "benign DTS must not produce a dts.firmware row at all"
        )

        # Case B: firmware-leak DTS → row present, still not open
        tb = Path(td) / "leak"
        tb.mkdir(parents=True)
        _write_dts(tb, "l.dtsi", 'remoteproc { firmware-name = "sa8775p/adsp.mbn"; };')
        rows_b = track_t5(snapshot=_chips_ok("sm8650"), dts=_load_dts_files(tb))
        facts_b = project_facts(rows_b)
        assert "T5.dts.firmware" in facts_b.rows_by_track_subject, (
            "leak DTS should produce a dts.firmware row"
        )
        assert facts_b.is_open("T5", "dts.firmware") is False, (
            "FINDING FALSIFIED if this fires: a live T5 dts.firmware row opened "
            "the dt_scaffolding gate. track_t5 is not supposed to emit "
            "MATCH/PARTIAL_MATCH. Re-diagnose and update G-3A.7."
        )
        print(
            "PASS: dt_scaffolding T5.dts.firmware gate unsatisfiable from live "
            "producer — missing row (benign) or DISAGREE+warning (leak)"
        )


def main() -> None:
    test_empty_dts_dir_yields_one_ncc_revision_anchor_row()
    test_firmware_leak_dts_emits_disagree_not_match()
    test_dt_scaffolding_gate_unsatisfiable_from_live_t5()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
