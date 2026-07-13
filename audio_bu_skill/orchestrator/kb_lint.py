"""Value-lint for the Audio Knowledge Base (Track A / WP-A).

A standalone, dependency-free checker (no orchestrator import) that enforces the
KB's core invariant: **the shared KB contains rules, never values, never target
names.** It scans `references/kb/**/*.md` for forbidden value shapes and target
codenames, and cross-checks the `_index.md` rule-ID registry for consistency.

Forbidden value shapes (each a hard failure with file:line):
  * hex literals            0x[0-9A-Fa-f]{3,}
  * clock rates             <int> Hz|kHz|MHz|GHz
  * SoC-bound compatibles   qcom,<soc>-<...>
  * document IDs            24-hex-char ids, or LD<digits>
  * vendor part numbers     <2+ caps><3+ digits><optional caps>  (e.g. a DAC part)
  * bare large integers     >=4-digit standalone ints (register sizes/addresses),
                            after ISO dates are allowlisted

Target names: a small, extensible denylist seed of codenames/part tokens that
must never appear in the shared KB (they are target evidence, not framework KB).

Allowlist: forbidden *value* shapes (not target names) are permitted only inside
an explicit `## Anonymized illustrations` block — and even there a target name is
still a hard failure.

Usage:
    python3 orchestrator/kb_lint.py [references/kb]
Exit code 0 = clean, 1 = one or more violations (printed as file:line).

    from orchestrator.kb_lint import lint_kb, check_index_consistency
    violations = lint_kb(kb_dir)            # list[str] of "file:line: message"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ── forbidden value-shape patterns ──
_HEX = re.compile(r"0x[0-9A-Fa-f]{3,}")
_RATE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:Hz|kHz|MHz|GHz)\b")
_SOC_COMPATIBLE = re.compile(r"\bqcom,[a-z0-9]+-[a-z0-9-]+\b")
_DOC_ID = re.compile(r"\b[0-9a-f]{24}\b|\bLD\d{3,}\b")
# a vendor part number: >=2 uppercase letters immediately followed by >=3 digits
# (optionally trailing caps). Rule IDs like PROV-001 have a hyphen, so are safe.
_PART_NUMBER = re.compile(r"\b[A-Z]{2,}\d{3,}[A-Z]*\b")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_BARE_BIG_INT = re.compile(r"(?<![\w-])\d{4,}(?![\w-])")

# Seed denylist of target codenames / part tokens (case-insensitive, extensible).
# These are *target evidence*, never shared-KB content.
TARGET_NAME_DENYLIST: tuple[str, ...] = (
    "nord",
    "eliza",
    "sa8797p",
    "sa8797",
    "sa8775p",
    "cq7790",
    "cq7790s",
    "lemans",
    "honu",
    "waipio",
    "pakala",
    "olympic",
)

_ANON_HEADER = "## anonymized illustrations"
# section headers end an allowlisted block
_SECTION_HEADER = re.compile(r"^##\s")


def _value_violations(line: str, *, in_anon_block: bool) -> list[str]:
    """Return messages for forbidden *value* shapes on one line. Value shapes are
    tolerated inside the anonymized-illustration block; target names never are."""
    msgs: list[str] = []
    if in_anon_block:
        return msgs  # value shapes allowed here; target-name check runs separately
    if _HEX.search(line):
        msgs.append("hex address/literal (a value — belongs in target evidence)")
    if _RATE.search(line):
        msgs.append("clock rate (a value — belongs in target evidence)")
    if _SOC_COMPATIBLE.search(line):
        msgs.append("SoC-bound compatible string (a value — belongs in target evidence)")
    if _DOC_ID.search(line):
        msgs.append("document ID (a value — belongs in target evidence)")
    if _PART_NUMBER.search(line):
        msgs.append("vendor part number (a value — belongs in target evidence)")
    # bare big integers, after removing ISO dates (change-log / index dates are OK)
    if _BARE_BIG_INT.search(_ISO_DATE.sub("", line)):
        msgs.append("bare large integer (register size/address — belongs in target evidence)")
    return msgs


def _target_name_violations(line: str) -> list[str]:
    low = line.lower()
    hits = [name for name in TARGET_NAME_DENYLIST if re.search(rf"\b{re.escape(name)}\b", low)]
    return [f"target name {name!r} (KB must be target-agnostic)" for name in hits]


def lint_file(path: Path) -> list[str]:
    """Lint one KB markdown file → list of 'file:line: message' violations."""
    violations: list[str] = []
    in_anon_block = False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw
        if _SECTION_HEADER.match(line):
            in_anon_block = line.strip().lower() == _ANON_HEADER
        # target names are forbidden everywhere, including anonymized blocks
        for msg in _target_name_violations(line):
            violations.append(f"{path}:{n}: {msg}")
        for msg in _value_violations(line, in_anon_block=in_anon_block):
            violations.append(f"{path}:{n}: {msg}")
    return violations


def lint_kb(kb_dir: Path) -> list[str]:
    """Lint every *.md under kb_dir (recursively). Returns all violations."""
    violations: list[str] = []
    for path in sorted(kb_dir.rglob("*.md")):
        violations.extend(lint_file(path))
    return violations


# ── _index.md consistency ──
_INDEX_ROW = re.compile(r"^\|\s*([A-Z]+-[A-Z]?\d+)\s*\|")
_RULE_ID = re.compile(r"\b([A-Z]{2,}-[A-Z]?\d{1,3})\b")


def _registered_ids(index_path: Path) -> list[str]:
    ids: list[str] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        m = _INDEX_ROW.match(line)
        if m:
            ids.append(m.group(1))
    return ids


def check_index_consistency(kb_dir: Path) -> list[str]:
    """Every rule ID defined/cited in a KB file exists in _index.md; no dupes."""
    problems: list[str] = []
    index_path = kb_dir / "_index.md"
    if not index_path.is_file():
        return [f"{index_path}: missing rule-ID registry"]

    registered = _registered_ids(index_path)
    seen: set[str] = set()
    for rid in registered:
        if rid in seen:
            problems.append(f"{index_path}: duplicate rule ID {rid}")
        seen.add(rid)
    registered_set = set(registered)

    # every ID cited in a KB body must be registered
    for path in sorted(kb_dir.rglob("*.md")):
        if path.name == "_index.md" or path.parent.name == "_schema":
            continue
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            for rid in _RULE_ID.findall(line):
                if rid not in registered_set:
                    problems.append(f"{path}:{n}: cites unregistered rule ID {rid}")
    return problems


# ── skeleton conformance ──
_REQUIRED_SECTIONS = (
    "Scope", "Rules", "Patterns", "Distinctions", "Provenance",
    "Anti-patterns", "Anonymized illustrations", "Open questions", "Change log",
)


def check_skeleton_conformance(kb_dir: Path) -> list[str]:
    """Each domain KB file must contain every required '## ' section (A.0)."""
    problems: list[str] = []
    for path in sorted(kb_dir.glob("*.md")):
        if path.name == "_index.md":
            continue
        headers = {
            line[3:].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("## ")
        }
        for section in _REQUIRED_SECTIONS:
            if section not in headers:
                problems.append(f"{path}: missing required section '## {section}'")
    return problems


def run(kb_dir: Path) -> int:
    all_problems = (
        lint_kb(kb_dir)
        + check_index_consistency(kb_dir)
        + check_skeleton_conformance(kb_dir)
    )
    if all_problems:
        print(f"KB lint FAILED — {len(all_problems)} violation(s):")
        for p in all_problems:
            print(f"  {p}")
        return 1
    print(f"KB lint OK — {kb_dir} is clean (zero values, zero target names).")
    return 0


def main(argv: list[str]) -> int:
    kb_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "references" / "kb"
    return run(kb_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
