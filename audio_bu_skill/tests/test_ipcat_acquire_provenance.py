"""T-IA-08 — provenance.json builder + sidecar shape (network-free).

Verifies that build_provenance assembles the design §3.1 schema v2.0.0
correctly, that the BOUNDARY block is the compile-time safety constant,
that sidecar_payload produces the correct ASCII bytes, and that invalid
sha256 values are rejected by the dataclass validators.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_provenance
"""

from __future__ import annotations

import copy
import json

from orchestrator.ipcat_acquire.provenance import (
    BOUNDARY,
    SCHEMA_VERSION,
    ChipRef,
    FileRecord,
    QueryRecord,
    build_provenance,
    sidecar_payload,
)


_GOOD_SHA = "a" * 64
_CHIP = ChipRef(alias="nordschleife_2.0", id=781, canonical_name="SA8797P (NordAU) v2")


def _make_query(**kw) -> QueryRecord:
    defaults = dict(
        tool="chips_list_chips",
        args={},
        query_id="q1",
        result_file="chips_list_chips.json",
        sha256=_GOOD_SHA,
    )
    defaults.update(kw)
    return QueryRecord(**defaults)


def _make_file(**kw) -> FileRecord:
    defaults = dict(path="chips_list_chips.json", sha256=_GOOD_SHA, bytes=512)
    defaults.update(kw)
    return FileRecord(**defaults)


def _build(**kw) -> dict:
    defaults = dict(
        target="nord-iq10",
        chip=_CHIP,
        acquired_at="2026-07-21T09:00:00Z",
        mechanism="mcp_http",
        endpoint_host="qgenie-mcphub.qualcomm.com",
        queries=[_make_query()],
        files=[_make_file()],
    )
    defaults.update(kw)
    return build_provenance(**defaults)


# ── schema structure ───────────────────────────────────────────────────────────

def test_schema_version_is_2_0_0() -> None:
    assert SCHEMA_VERSION == "2.0.0"
    prov = _build()
    assert prov["schema_version"] == "2.0.0"
    print("PASS T-IA-08a: schema_version == '2.0.0'")


def test_top_level_keys_present() -> None:
    prov = _build()
    required = {
        "schema_version", "target", "chip", "acquired_at",
        "mechanism", "endpoint_host", "boundary", "queries", "files",
    }
    missing = required - prov.keys()
    assert not missing, f"T-IA-08b: missing top-level keys: {missing}"
    print(f"PASS T-IA-08b: all {len(required)} required top-level keys present")


def test_chip_block_shape() -> None:
    prov = _build()
    chip = prov["chip"]
    assert chip["alias"] == "nordschleife_2.0"
    assert chip["id"] == 781
    assert chip["canonical_name"] == "SA8797P (NordAU) v2"
    print("PASS T-IA-08c: chip block has alias, id, canonical_name")


def test_boundary_block_is_compile_time_constant() -> None:
    """BOUNDARY must encode the safety invariants, never runtime state."""
    prov = _build()
    b = prov["boundary"]
    assert b["auth_json_read"] is False
    assert b["credentials_json_read"] is False
    assert b["tls_verify"] is True
    assert b["readonly_only"] is True
    # Must match the module-level BOUNDARY constant
    assert b == BOUNDARY
    print("PASS T-IA-08d: boundary block matches compile-time BOUNDARY constant")


def test_queries_list_shape() -> None:
    q = _make_query(
        tool="swi_search_swi",
        args={"chip": "nordschleife_2.0", "q": "SWR"},
        query_id="q3c",
        result_file="swi_search_swi__swr.json",
        count_method="union{SOUNDWIRE_MASTER,SWR_MSTR,SWR}; stable; below_cap=true",
    )
    prov = _build(queries=[q])
    qrow = prov["queries"][0]
    assert qrow["tool"] == "swi_search_swi"
    assert qrow["args"] == {"chip": "nordschleife_2.0", "q": "SWR"}
    assert qrow["count_method"] is not None and "union" in qrow["count_method"]
    assert len(qrow["sha256"]) == 64
    print("PASS T-IA-08e: queries[] entry has all required fields incl count_method")


def test_files_list_shape() -> None:
    prov = _build()
    frow = prov["files"][0]
    assert "path" in frow
    assert "sha256" in frow and len(frow["sha256"]) == 64
    assert "bytes" in frow and frow["bytes"] >= 0
    print("PASS T-IA-08f: files[] entry has path, sha256 (64 hex), bytes (>=0)")


def test_acquired_at_is_caller_supplied() -> None:
    """acquired_at must be exactly the value the caller supplies (no clock read)."""
    stamp = "2026-07-21T09:14:02Z"
    prov = _build(acquired_at=stamp)
    assert prov["acquired_at"] == stamp
    print("PASS T-IA-08g: acquired_at is caller-supplied (build_provenance reads no clock)")


def test_build_provenance_pure() -> None:
    """Calling build_provenance twice with the same args produces equal dicts."""
    p1 = _build()
    p2 = _build()
    assert p1 == p2
    print("PASS T-IA-08h: build_provenance is a pure function (same input → equal output)")


# ── validation ─────────────────────────────────────────────────────────────────

def test_query_record_rejects_bad_sha() -> None:
    raised = False
    try:
        QueryRecord(tool="t", args={}, query_id="q1", result_file="f.json", sha256="not-hex")
    except ValueError:
        raised = True
    assert raised, "QueryRecord should reject a non-hex sha256"
    print("PASS T-IA-08i: QueryRecord raises ValueError on non-hex sha256")


def test_file_record_rejects_bad_sha() -> None:
    raised = False
    try:
        FileRecord(path="f.json", sha256="UPPER_CASE_BAD" + "x" * 50, bytes=0)
    except ValueError:
        raised = True
    assert raised, "FileRecord should reject a non-hex sha256"
    print("PASS T-IA-08j: FileRecord raises ValueError on non-hex sha256")


def test_file_record_rejects_negative_bytes() -> None:
    raised = False
    try:
        FileRecord(path="f.json", sha256=_GOOD_SHA, bytes=-1)
    except ValueError:
        raised = True
    assert raised, "FileRecord should reject negative bytes"
    print("PASS T-IA-08k: FileRecord raises ValueError on negative bytes")


# ── sidecar_payload ────────────────────────────────────────────────────────────

def test_sidecar_payload_shape() -> None:
    payload = sidecar_payload(_GOOD_SHA)
    assert payload == (_GOOD_SHA + "\n").encode("ascii")
    print("PASS T-IA-08l: sidecar_payload = sha256 hex + newline (ASCII)")


def test_sidecar_payload_rejects_bad_sha() -> None:
    raised = False
    try:
        sidecar_payload("not-a-sha256")
    except ValueError:
        raised = True
    assert raised, "sidecar_payload should reject a non-hex sha256"
    print("PASS T-IA-08m: sidecar_payload raises ValueError on non-hex sha256")


# ── runner ─────────────────────────────────────────────────────────────────────

def main() -> None:
    test_schema_version_is_2_0_0()
    test_top_level_keys_present()
    test_chip_block_shape()
    test_boundary_block_is_compile_time_constant()
    test_queries_list_shape()
    test_files_list_shape()
    test_acquired_at_is_caller_supplied()
    test_build_provenance_pure()
    test_query_record_rejects_bad_sha()
    test_file_record_rejects_bad_sha()
    test_file_record_rejects_negative_bytes()
    test_sidecar_payload_shape()
    test_sidecar_payload_rejects_bad_sha()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
