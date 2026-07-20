"""T-IA-07 + T-IA-10 — normalize.to_canonical + W4 union count.

T-IA-07: to_canonical produces deterministic, byte-identical output for
equivalent inputs regardless of dict-key order or list order in the response.

T-IA-10: count_swi_union + build_count_method implement the W4 discipline
correctly: stable iff every per-term result is strictly below the cap;
unstable (None, False) when any term is at or above the cap.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_normalize
"""

from __future__ import annotations

import json

from orchestrator.ipcat_acquire.normalize import (
    build_count_method,
    count_swi_union,
    to_canonical,
)


# ── T-IA-07: to_canonical ─────────────────────────────────────────────────────

def test_canonical_sorts_dict_keys() -> None:
    """Dict key order must not affect the output bytes."""
    a = to_canonical({"z": 1, "a": 2, "m": 3})
    b = to_canonical({"a": 2, "m": 3, "z": 1})
    assert a == b, f"key-order sensitive: {a!r} != {b!r}"
    print("PASS T-IA-07a: dict key order does not affect canonical bytes")


def test_canonical_sorts_list_items() -> None:
    """List item order must not affect the output bytes."""
    a = to_canonical([{"name": "SWR_MASTER"}, {"name": "SWR0"}, {"name": "AUDIO_SS"}])
    b = to_canonical([{"name": "AUDIO_SS"}, {"name": "SWR_MASTER"}, {"name": "SWR0"}])
    assert a == b, f"list-order sensitive: {a!r} != {b!r}"
    print("PASS T-IA-07b: list item order does not affect canonical bytes")


def test_canonical_trailing_newline() -> None:
    """Output must end with exactly one newline."""
    out = to_canonical({"x": 1})
    assert out.endswith(b"\n"), "missing trailing newline"
    assert not out.endswith(b"\n\n"), "double trailing newline"
    print("PASS T-IA-07c: trailing newline present (exactly one)")


def test_canonical_utf8() -> None:
    """Non-ASCII content must be preserved, not escaped."""
    out = to_canonical({"name": "Ütf-8 α 山"})
    assert b"\\u" not in out, "unicode escaped in canonical bytes (ensure_ascii must be False)"
    assert "Ütf-8".encode("utf-8") in out, "non-ASCII content missing"
    print("PASS T-IA-07d: non-ASCII preserved as UTF-8 (ensure_ascii=False)")


def test_canonical_idempotent() -> None:
    """Calling to_canonical twice on the same input yields identical bytes."""
    obj = [{"id": "B", "val": [3, 1, 2]}, {"id": "A", "val": [99]}]
    assert to_canonical(obj) == to_canonical(obj)
    print("PASS T-IA-07e: to_canonical is idempotent (same input → same bytes)")


def test_canonical_bare_list() -> None:
    """A bare list (as returned by some IPCAT tools) round-trips cleanly."""
    rows = [{"name": "q2"}, {"name": "q1"}, {"name": "q3"}]
    canon = to_canonical(rows)
    parsed = json.loads(canon)
    assert isinstance(parsed, list) and len(parsed) == 3
    # Items must be sorted by canonical encoding
    keys = [r["name"] for r in parsed]
    assert keys == sorted(keys), f"list items not sorted: {keys}"
    print("PASS T-IA-07f: bare list canonical round-trip preserves all items sorted")


def test_canonical_nested_structure() -> None:
    """Nested dict+list structures are recursively stabilised."""
    a = to_canonical({"outer": {"z": [{"k": 2}, {"k": 1}], "a": "v"}})
    b = to_canonical({"outer": {"a": "v", "z": [{"k": 1}, {"k": 2}]}})
    assert a == b, "nested structure not canonical"
    print("PASS T-IA-07g: nested dict+list structures canonicalised recursively")


# ── T-IA-10: count_swi_union / build_count_method ─────────────────────────────

def _rows(names: list[str]) -> list[dict]:
    return [{"name": n} for n in names]


def test_union_stable_distinct_terms() -> None:
    """Fully disjoint terms, each below cap → stable union = sum of sizes."""
    per_term = {
        "SOUNDWIRE_MASTER": _rows(["SWR_MASTER0", "SWR_MASTER1"]),
        "SWR_MSTR":         _rows(["SWR_MSTR_CLK"]),
        "SWR":              _rows(["SWR0", "SWR1", "SWR2"]),
    }
    count, stable = count_swi_union(per_term, cap=10)
    assert stable is True, f"expected stable, got {stable}"
    assert count == 6, f"expected union size 6, got {count}"
    print("PASS T-IA-10a: disjoint terms below cap → stable, union=6")


def test_union_stable_overlapping_terms() -> None:
    """Overlapping terms (shared names) — union deduplicates correctly."""
    per_term = {
        "SOUNDWIRE_MASTER": _rows(["SWR_A", "SWR_B"]),
        "SWR_MSTR":         _rows(["SWR_B", "SWR_C"]),  # SWR_B is shared
    }
    count, stable = count_swi_union(per_term, cap=10)
    assert stable is True
    assert count == 3, f"expected 3 (A, B, C deduplicated), got {count}"
    print("PASS T-IA-10b: overlapping terms deduplicated in union count")


def test_union_unstable_at_cap() -> None:
    """A term at exactly cap → unstable (may be truncated)."""
    cap = 5
    per_term = {
        "SOUNDWIRE_MASTER": _rows(["a", "b", "c", "d", "e"]),  # == cap
        "SWR_MSTR":         _rows(["x"]),
    }
    count, stable = count_swi_union(per_term, cap=cap)
    assert stable is False, f"expected unstable when term == cap, got stable={stable}"
    assert count is None, f"expected count=None when unstable, got {count}"
    print("PASS T-IA-10c: term at cap → unstable, count=None")


def test_union_unstable_above_cap() -> None:
    """A term above cap → unstable."""
    cap = 3
    per_term = {
        "SWR": _rows(["a", "b", "c", "d"]),  # > cap
    }
    count, stable = count_swi_union(per_term, cap=cap)
    assert stable is False
    assert count is None
    print("PASS T-IA-10d: term above cap → unstable, count=None")


def test_union_empty_terms() -> None:
    """No terms → stable, count=0 (vacuously true)."""
    count, stable = count_swi_union({}, cap=25)
    assert stable is True
    assert count == 0
    print("PASS T-IA-10e: empty per_term_rows → stable, count=0")


def test_union_one_empty_term() -> None:
    """One term returning zero rows → stable, count=0."""
    count, stable = count_swi_union({"SWR": []}, cap=25)
    assert stable is True
    assert count == 0
    print("PASS T-IA-10f: one empty-result term → stable, count=0")


def test_count_method_stable_below_cap() -> None:
    """build_count_method produces the canonical provenance string."""
    s = build_count_method(("SOUNDWIRE_MASTER", "SWR_MSTR", "SWR"), stable=True, below_cap=True)
    assert s == "union{SOUNDWIRE_MASTER,SWR_MSTR,SWR}; stable; below_cap=true", repr(s)
    print("PASS T-IA-10g: build_count_method stable+below_cap string correct")


def test_count_method_unstable() -> None:
    """Unstable result produces 'unstable; below_cap=false'."""
    s = build_count_method(("SWR",), stable=False, below_cap=False)
    assert "unstable" in s
    assert "below_cap=false" in s
    print("PASS T-IA-10h: build_count_method unstable string correct")


# ── runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    test_canonical_sorts_dict_keys()
    test_canonical_sorts_list_items()
    test_canonical_trailing_newline()
    test_canonical_utf8()
    test_canonical_idempotent()
    test_canonical_bare_list()
    test_canonical_nested_structure()
    test_union_stable_distinct_terms()
    test_union_stable_overlapping_terms()
    test_union_unstable_at_cap()
    test_union_unstable_above_cap()
    test_union_empty_terms()
    test_union_one_empty_term()
    test_count_method_stable_below_cap()
    test_count_method_unstable()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
