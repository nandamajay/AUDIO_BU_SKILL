"""Phase-3A WP-E — tests for the seven SourceRef variants + parse dispatch —
T-E29..T-E33.

Runs entirely in-process; does not touch case.py, case.generated.py, WP7,
onboarding, or any runtime flow. Advisory-only per PHASE3_ARCHITECTURE.md.

Run:
    PYTHONPATH=.:audio_bu_skill python3 -m tests.test_fact_registry_source_refs
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from audio_bu_skill.orchestrator.fact_registry import (
    ACDBRef,
    InferredRef,
    IPCATCachedRef,
    IPCATLiveRef,
    KernelRef,
    ManualRef,
    SchematicRef,
)
from audio_bu_skill.orchestrator.fact_registry.source_refs import parse as parse_source_ref

UTC = timezone.utc
_TS = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)


def _assert_raises(fn, exc, message_substring=None):
    try:
        fn()
    except exc as e:
        if message_substring is not None and message_substring not in str(e):
            raise AssertionError(
                f"expected {exc.__name__} containing {message_substring!r}, "
                f"got {exc.__name__} with message {e!r}"
            )
        return
    raise AssertionError(f"expected {exc.__name__} to be raised, but nothing raised")


def _all_variants():
    return [
        IPCATLiveRef(kind="ipcat_live", tool="ipcat", args={"q": "1"},
                     query_id="Q-1", ts=_TS),
        IPCATCachedRef(kind="ipcat_cached", path="p/c.json", sha256="a" * 64, line=3),
        KernelRef(kind="kernel", kernel_ref_kind="dts", repo="kernel/msm-5.15",
                  commit="b" * 40, path="a.dts", line_start=10, line_end=12),
        SchematicRef(kind="schematic", doc_id="SCH-1", revision="C", page=12,
                     section="U400"),
        ACDBRef(kind="acdb", export_id="E-1", path="acdb/x.acdb", key="k"),
        ManualRef(kind="manual", note="n", ticket_url="https://t.example.com/A-1"),
        InferredRef(kind="inferred", inference_rule="rule-1",
                    inputs={"a": "b"}, note="n"),
    ]


def _to_json(sr) -> dict:
    """Serialise a source_ref dataclass into a JSON-ready dict, matching the
    store's generic field walk (datetime -> ISO-Z, Mapping -> dict)."""
    out = {}
    for f in dataclasses.fields(sr):
        v = getattr(sr, f.name)
        if isinstance(v, datetime):
            v = v.isoformat().replace("+00:00", "Z")
        elif isinstance(v, dict):
            v = dict(v)
        out[f.name] = v
    return out


# ── T-E29 — each of the 7 variants round-trips through parse ───────────────

def test_te29_all_variants_roundtrip() -> None:
    for sr in _all_variants():
        d = _to_json(sr)
        # For IPCATLiveRef, parse expects a datetime for ts; convert back.
        if d["kind"] == "ipcat_live":
            d["ts"] = _TS
        back = parse_source_ref(d)
        assert back == sr, f"round-trip mismatch for {sr.kind}: {back!r} != {sr!r}"


# ── T-E30 — parse raises on unknown / missing kind ─────────────────────────

def test_te30_parse_rejects_unknown_kind() -> None:
    _assert_raises(lambda: parse_source_ref({"kind": "nope"}), ValueError)
    _assert_raises(lambda: parse_source_ref({}), ValueError)


# ── T-E31 — parse raises on missing required fields per variant ────────────

def test_te31_parse_rejects_missing_fields() -> None:
    # schematic missing required 'page'
    _assert_raises(
        lambda: parse_source_ref({"kind": "schematic", "doc_id": "D", "revision": "A"}),
        TypeError,
    )
    # acdb missing 'key'
    _assert_raises(
        lambda: parse_source_ref({"kind": "acdb", "export_id": "E", "path": "p"}),
        TypeError,
    )
    # kernel missing discriminator 'kernel_ref_kind'
    _assert_raises(
        lambda: parse_source_ref({
            "kind": "kernel", "repo": "r", "commit": "b" * 40,
            "path": "a.dts", "line_start": 1, "line_end": 2,
        }),
        TypeError,
    )


# ── T-E32 — IPCATCachedRef.sha256 rejects non-64-hex ───────────────────────

def test_te32_ipcat_cached_sha256_validation() -> None:
    _assert_raises(
        lambda: IPCATCachedRef(kind="ipcat_cached", path="p", sha256="abc"),
        ValueError,
    )
    _assert_raises(
        lambda: IPCATCachedRef(kind="ipcat_cached", path="p", sha256="g" * 64),
        ValueError,
    )
    # valid 64-hex accepted
    ok = IPCATCachedRef(kind="ipcat_cached", path="p", sha256="a" * 64)
    assert ok.sha256 == "a" * 64


# ── T-E33 — KernelRef.commit rejects non-40-hex; discriminator round-trip ──

def test_te33_kernel_commit_and_discriminator() -> None:
    _assert_raises(
        lambda: KernelRef(kind="kernel", kernel_ref_kind="dts", repo="r",
                          commit="abc", path="a.dts", line_start=1, line_end=2),
        ValueError,
    )
    # bindings discriminator round-trips distinctly from dts
    b = KernelRef(kind="kernel", kernel_ref_kind="bindings", repo="r",
                  commit="b" * 40, path="x.yaml", line_start=1, line_end=1)
    back = parse_source_ref(_to_json(b))
    assert back == b
    assert back.kernel_ref_kind == "bindings"


def main() -> None:
    # T-E29  round-trips
    test_te29_all_variants_roundtrip()
    # T-E30..T-E31  dispatch + missing-field errors
    test_te30_parse_rejects_unknown_kind()
    test_te31_parse_rejects_missing_fields()
    # T-E32..T-E33  digest validation
    test_te32_ipcat_cached_sha256_validation()
    test_te33_kernel_commit_and_discriminator()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
