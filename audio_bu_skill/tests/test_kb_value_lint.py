"""Tests for the KB value-lint (Track A / WP-A).

Asserts:
  * the committed `references/kb/` passes lint (zero values, zero target names),
    index consistency, and skeleton conformance;
  * crafted bad fixtures (hex address, clock rate, part number, target name,
    SoC-bound compatible, doc ID) each fail lint;
  * flagship rule IDs are present and registered.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_kb_value_lint
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from orchestrator import kb_lint

KB_DIR = Path(__file__).resolve().parents[1] / "references" / "kb"


def test_committed_kb_is_clean() -> None:
    assert kb_lint.lint_kb(KB_DIR) == [], "committed KB has value/target-name violations"
    assert kb_lint.check_index_consistency(KB_DIR) == [], "committed KB index inconsistent"
    assert kb_lint.check_skeleton_conformance(KB_DIR) == [], "committed KB missing sections"
    print("PASS: committed KB is clean (values, index, skeleton)")


def test_flagship_ids_registered() -> None:
    ids = set(kb_lint._registered_ids(KB_DIR / "_index.md"))
    for flagship in ("PROV-001", "PROV-002", "PROV-003", "PROV-D1", "SWR-D1", "AR-001", "CLK-001"):
        assert flagship in ids, f"flagship rule ID {flagship} not registered"
    print("PASS: flagship rule IDs present and registered")


def _lint_one(text: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bad.md"
        p.write_text(text, encoding="utf-8")
        return kb_lint.lint_file(p)


def test_hex_address_fails() -> None:
    assert _lint_one("The base is at 0x30000000 for this block.\n")
    print("PASS: hex address rejected")


def test_clock_rate_fails() -> None:
    assert _lint_one("The controller runs at 9600 kHz nominal.\n")
    print("PASS: clock rate rejected")


def test_part_number_fails() -> None:
    assert _lint_one("Use the PCM1681 codec driver here.\n")
    print("PASS: vendor part number rejected")


def test_soc_compatible_fails() -> None:
    assert _lint_one("Bind compatible = qcom,sa8797p-adsp-pas in the node.\n")
    print("PASS: SoC-bound compatible rejected")


def test_doc_id_fails() -> None:
    assert _lint_one("See document 674dd412a66dd46a38c52306 for details.\n")
    print("PASS: document ID rejected")


def test_target_name_fails_everywhere() -> None:
    # target names are forbidden even inside an anonymized-illustration block
    text = "## Anonymized illustrations\n\n- Eliza exhibited a split coverage case.\n"
    violations = _lint_one(text)
    assert any("target name" in v for v in violations), violations
    print("PASS: target name rejected even in anonymized block")


def test_value_allowed_in_anon_block() -> None:
    # a value shape (bare integer) with NO target name is tolerated in the anon block
    text = "## Anonymized illustrations\n\n- a target had 2048 distinct entries.\n"
    assert _lint_one(text) == [], "value shape in anon block (no target name) should pass"
    print("PASS: value shape tolerated in anonymized block when no target named")


def test_index_detects_unregistered_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kb = Path(tmp)
        (kb / "_index.md").write_text(
            "| Rule ID | File | Summary | Status | Added | Confirmations |\n"
            "|--|--|--|--|--|--|\n"
            "| FOO-001 | foo.md | x | active | 2026-07-13 | 0 |\n",
            encoding="utf-8",
        )
        (kb / "foo.md").write_text(
            "# KB: foo\n## Rules\n- FOO-001 real. BAR-999 is not registered.\n",
            encoding="utf-8",
        )
        problems = kb_lint.check_index_consistency(kb)
        assert any("BAR-999" in p for p in problems), problems
    print("PASS: index consistency detects unregistered cited ID")


def main() -> None:
    test_committed_kb_is_clean()
    test_flagship_ids_registered()
    test_hex_address_fails()
    test_clock_rate_fails()
    test_part_number_fails()
    test_soc_compatible_fails()
    test_doc_id_fails()
    test_target_name_fails_everywhere()
    test_value_allowed_in_anon_block()
    test_index_detects_unregistered_id()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
