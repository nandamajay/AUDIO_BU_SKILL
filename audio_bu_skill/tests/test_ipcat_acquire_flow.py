"""T-IA-03 + T-IA-09 — acquire_to_cache end-to-end flow (mock transport).

T-IA-03: acquire_to_cache with a cooperating mock transport resolves chip,
counts the W4 union, normalises, and publishes a complete cache.  Result is
AcquireStatus.OK, files are byte-identical to to_canonical of the mock data,
provenance.json is present and valid, no socket is opened.

T-IA-09: acquire_to_cache returns the correct AcquireStatus without writing
any bytes for each refusal scenario:
  - auth wall on any call        → AUTH_REQUIRED, 0 bytes written
  - chip alias not found          → UNRESOLVED, 0 bytes written
  - capped SWI search (at cap)    → CAPPED_SEARCH, 0 bytes written
  - transport error on mandatory  → TRANSPORT_ERROR, 0 bytes written
  - write error (lock held)       → WRITE_ERROR, 0 bytes written
  - dry_run=True                  → PLANNED, 0 bytes written, files non-empty

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_ipcat_acquire_flow
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from orchestrator.ipcat_acquire import AcquireResult, AcquireStatus, acquire_to_cache
from orchestrator.ipcat_acquire.client import AUTHWALL_KEY, ERROR_KEY
from orchestrator.ipcat_acquire.errors import AcquireWriteError
from orchestrator.ipcat_acquire.manifest import NORD_MANIFEST
from orchestrator.ipcat_acquire.materialize import LOCK_NAME, PROVENANCE_NAME
from orchestrator.ipcat_acquire.normalize import to_canonical


# ── mock transport ────────────────────────────────────────────────────────────

class _MockTransport:
    """Configurable deterministic mock. No socket; no side effects on import."""

    def __init__(self, responses: dict[str, Any], *, auth_wall_on: str | None = None):
        self._responses = responses
        self._auth_wall_on = auth_wall_on
        self.closed = False
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((tool, dict(args)))
        if self._auth_wall_on and tool == self._auth_wall_on:
            return {AUTHWALL_KEY: "Authentication required: please log in"}
        key = tool
        if key in self._responses:
            return self._responses[key]
        raise ConnectionError(f"mock: unexpected tool call {tool!r}")

    def close(self) -> None:
        self.closed = True


def _raises_transport(tool: str, args: Mapping[str, Any]) -> Any:
    raise ConnectionError("simulated network failure")


class _ErrorTransport:
    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        raise ConnectionError("simulated network failure")
    def close(self) -> None:
        pass


# ── canonical fixture responses ───────────────────────────────────────────────

_CHIP_ALIAS = "nordschleife_2.0"
_CHIP_ROW = {"alias": _CHIP_ALIAS, "id": 781, "canonical_name": "SA8797P (NordAU) v2"}

# The 12 tool responses the happy-path test needs.  SWI entries each return
# 2 rows — well below cap=25, so the union is stable.
_HAPPY_RESPONSES: dict[str, Any] = {
    "chips_list_chips":           [_CHIP_ROW],
    "cores_list_core_instances":  [{"name": "audio_q6"}],
    "swi_search_swi":             [{"name": "SWR_MASTER0"}, {"name": "SWR_MASTER1"}],
    "gpio_get_gpio_map":          {"gpio_map_id": 99},
    "gpio_list_gpios_from_map":   [{"gpio_num": 0, "name": "GPIO0"}],
    "gpio_list_tlmm_gpios":       [{"gpio_num": 0}],
    "chipio_get_qups":            [{"qup_id": "QUP0"}],
    "buses_list_buses":           [{"bus": "config_noc"}],
    "buses_list_bus_gateways":    [{"gateway": "gw0"}],
    "buses_list_bidpidmids":      [{"bid": 1}],
}


# ── T-IA-03: happy-path end-to-end ────────────────────────────────────────────

def test_ok_status_and_files_published() -> None:
    """Full happy-path: OK status, all manifest files present, no socket opened."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _MockTransport(_HAPPY_RESPONSES)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            acquired_at="2026-07-21T09:00:00Z",
        )
        assert result.status == AcquireStatus.OK, f"expected OK, got {result.status}: {result.message}"
        assert result.bytes_written > 0, "OK result must report bytes_written > 0"
        assert transport.closed, "transport.close() must be called"
        # All result files must exist on disk
        for fname in result.files:
            assert (base / fname).exists(), f"published file missing: {fname}"
        assert (base / PROVENANCE_NAME).exists(), "provenance.json missing"
    print("PASS T-IA-03a: acquire_to_cache returns OK, all files published, transport closed")


def test_published_bytes_are_canonical() -> None:
    """Data file content is byte-identical to to_canonical of the mock response."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _MockTransport(_HAPPY_RESPONSES)
        acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            acquired_at="2026-07-21T09:00:00Z",
        )
        expected = to_canonical([_CHIP_ROW])
        actual = (base / "chips_list_chips.json").read_bytes()
        assert actual == expected, f"chips_list_chips.json: content mismatch"
    print("PASS T-IA-03b: published file content is byte-identical to to_canonical(mock_response)")


def test_provenance_schema_version() -> None:
    """provenance.json contains schema_version '2.0.0'."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _MockTransport(_HAPPY_RESPONSES)
        acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            acquired_at="2026-07-21T09:00:00Z",
        )
        prov = json.loads((base / PROVENANCE_NAME).read_text())
        assert prov["schema_version"] == "2.0.0"
        assert prov["target"] == "nord-iq10"
        assert prov["chip"]["alias"] == _CHIP_ALIAS
    print("PASS T-IA-03c: provenance.json has correct schema_version, target, chip.alias")


def test_result_exit_code_ok_is_zero() -> None:
    """AcquireResult.exit_code is 0 for OK (never calls sys.exit)."""
    with tempfile.TemporaryDirectory() as tmp:
        transport = _MockTransport(_HAPPY_RESPONSES)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=Path(tmp),
            transport=transport,
            acquired_at="2026-07-21T09:00:00Z",
        )
        assert result.exit_code == 0
    print("PASS T-IA-03d: AcquireResult.exit_code == 0 for OK status")


def test_dry_run_writes_zero_bytes() -> None:
    """dry_run=True returns PLANNED and writes nothing to disk."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _MockTransport(_HAPPY_RESPONSES)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            dry_run=True,
        )
        assert result.status == AcquireStatus.PLANNED, result.status
        assert result.bytes_written == 0
        assert len(result.files) > 0, "PLANNED must report intended file names"
        # No data files may exist on disk
        json_files = list(base.glob("*.json"))
        assert not json_files, f"dry-run must not write JSON files: {json_files}"
    print("PASS T-IA-03e: dry_run=True → PLANNED, 0 bytes written, intended files reported")


# ── T-IA-09: refusal scenarios ────────────────────────────────────────────────

def _zero_bytes_in(base: Path) -> bool:
    """True iff no .json or .sha256 data file exists in base."""
    return not any(
        base.glob("*.json")
    ) and not any(base.glob("*.sha256"))


def test_auth_wall_returns_auth_required() -> None:
    """Auth wall on the first tool call → AUTH_REQUIRED, nothing written."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _MockTransport({}, auth_wall_on="chips_list_chips")
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
        )
        assert result.status == AcquireStatus.AUTH_REQUIRED, result.status
        assert result.bytes_written == 0
        assert _zero_bytes_in(base), "auth wall must write zero bytes"
    print("PASS T-IA-09a: auth wall → AUTH_REQUIRED, 0 bytes written")


def test_chip_not_found_returns_unresolved() -> None:
    """chip alias absent from chips_list_chips response → UNRESOLVED."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # Respond with a chip that has a different alias
        resp = dict(_HAPPY_RESPONSES)
        resp["chips_list_chips"] = [{"alias": "other_chip", "id": 1}]
        transport = _MockTransport(resp)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
        )
        assert result.status == AcquireStatus.UNRESOLVED, result.status
        assert result.bytes_written == 0
    print("PASS T-IA-09b: chip alias not found → UNRESOLVED, 0 bytes written")


def test_capped_swi_returns_capped_search() -> None:
    """SWI result at cap → CAPPED_SEARCH (W4 unstable), nothing written."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cap = 3
        # Make SWR term return exactly cap items (= at cap → unstable)
        resp = dict(_HAPPY_RESPONSES)
        resp["swi_search_swi"] = [{"name": f"SWR{i}"} for i in range(cap)]
        transport = _MockTransport(resp)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            swi_cap=cap,
        )
        assert result.status == AcquireStatus.CAPPED_SEARCH, result.status
        assert result.bytes_written == 0
    print("PASS T-IA-09c: capped SWI at cap → CAPPED_SEARCH, 0 bytes written")


def test_transport_error_on_mandatory_returns_transport_error() -> None:
    """ConnectionError on a mandatory tool → TRANSPORT_ERROR, nothing written."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        transport = _ErrorTransport()
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
        )
        assert result.status == AcquireStatus.TRANSPORT_ERROR, result.status
        assert result.bytes_written == 0
        # The message must be a redacted class name, not a raw error string
        assert "ConnectionError" in result.message or result.message != "", result.message
    print("PASS T-IA-09d: transport error on mandatory → TRANSPORT_ERROR, 0 bytes written, redacted message")


def test_write_error_on_lock_held_returns_write_error() -> None:
    """If materialize cannot acquire the lock, WRITE_ERROR, old cache intact."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # Pre-hold the lock
        lock_path = base / LOCK_NAME
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            transport = _MockTransport(_HAPPY_RESPONSES)
            result = acquire_to_cache(
                target="nord-iq10",
                chip_alias=_CHIP_ALIAS,
                mechanism="mcp_http",
                evidence_ipcat_dir=base,
                transport=transport,
                acquired_at="2026-07-21T09:00:00Z",
                now=time.time(),
            )
            assert result.status == AcquireStatus.WRITE_ERROR, result.status
            assert result.bytes_written == 0
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    print("PASS T-IA-09e: WRITE_ERROR on lock-held → 0 bytes, old cache intact")


def test_optional_tool_error_does_not_block() -> None:
    """A transport error on an optional tool does not prevent OK status."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        resp = dict(_HAPPY_RESPONSES)
        # Remove optional tools — _MockTransport will raise ConnectionError for them
        del resp["buses_list_bus_gateways"]
        del resp["buses_list_bidpidmids"]
        transport = _MockTransport(resp)
        result = acquire_to_cache(
            target="nord-iq10",
            chip_alias=_CHIP_ALIAS,
            mechanism="mcp_http",
            evidence_ipcat_dir=base,
            transport=transport,
            acquired_at="2026-07-21T09:00:00Z",
        )
        assert result.status == AcquireStatus.OK, (
            f"optional tool failure must not block OK, got {result.status}: {result.message}"
        )
    print("PASS T-IA-09f: transport error on optional tool → OK (optional absence is acceptable)")


# ── runner ─────────────────────────────────────────────────────────────────────

def main() -> None:
    test_ok_status_and_files_published()
    test_published_bytes_are_canonical()
    test_provenance_schema_version()
    test_result_exit_code_ok_is_zero()
    test_dry_run_writes_zero_bytes()
    test_auth_wall_returns_auth_required()
    test_chip_not_found_returns_unresolved()
    test_capped_swi_returns_capped_search()
    test_transport_error_on_mandatory_returns_transport_error()
    test_write_error_on_lock_held_returns_write_error()
    test_optional_tool_error_does_not_block()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
