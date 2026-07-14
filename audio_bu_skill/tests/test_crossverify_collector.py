"""Unit tests for Phase-2A WP1 — crossverify_collector.

Pure tests over ``orchestrator.runners.crossverify_collector`` — no network,
no ``httpx``, no ``fastmcp`` import. A minimal ``FakeTransport`` replays
per-tool payloads (and per-tool exceptions), exercising:

  * read-only allow-list enforcement (``_require_readonly`` and the collector's
    own call path both reject non-allow-listed tools);
  * digest stability — the same payload yields the same ``result_digest``
    across two independent collector runs;
  * unavailable-tool path — a failing tool becomes
    ``status="unavailable"``, ``payload=None`` (except ``swi_search_swi``
    which retains its per-term breakdown for debug), with a redacted
    ``error_class``, and the rest of the snapshot completes;
  * determinism — two runs against identical transport responses produce
    byte-identical snapshots (no wall-clock, no ``random``);
  * fake-transport replay — every mandated tool key is present in the
    snapshot with a valid shape; JSON round-trip succeeds;
  * cascading unavailability — a failing ``gpio_get_gpio_map`` produces
    ``missing_gpio_map_id`` on ``gpio_list_gpios_from_map`` without asking
    the transport.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_crossverify_collector``
"""

from __future__ import annotations

import json
from typing import Any

from orchestrator.runners import crossverify_collector as C
from orchestrator.runners.crossverify_collector import (
    READONLY_MCP_TOOLS,
    SWI_QUERY_TERMS,
    collect_snapshot,
)


# ── Fake transport ───────────────────────────────────────────────────────────


class FakeTransport:
    """Minimal ``call_tool`` shim used by the tests.

    Given a ``responses`` dict of ``{tool_name: payload}`` and an optional
    ``errors`` dict of ``{tool_name: Exception}``, replays those exactly.
    ``swi_search_swi`` is dispatched per-term via ``responses["swi_search_swi"]``
    which itself is a ``{term: payload}`` map, matching the collector's shape.
    Every call is recorded to ``self.calls`` for allow-list assertions.
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, dict(params)))
        if name in self.errors:
            raise self.errors[name]
        if name == "swi_search_swi":
            per_term = self.responses.get("swi_search_swi") or {}
            term = params.get("term")
            if term in self.errors:
                raise self.errors[term]
            return per_term.get(term, {"results": []})
        if name in self.responses:
            return self.responses[name]
        return {}


def _nord_like_responses() -> dict[str, Any]:
    """A minimal set of realistic-shaped payloads for one chip."""
    return {
        "chips_list_chips": [
            {"id": 781, "name": "SA8797P (NordAU) v2", "alias": "nordschleife_2.0"}
        ],
        "cores_list_core_instances": [
            {"id": 43, "name": "High Performance Audio Subsystem"}
        ],
        "swi_search_swi": {
            "SOUNDWIRE_MASTER": {"results": []},
            "SWR_MSTR": {"results": []},
            "SWR": {"results": []},
            "LPASS_MACRO": {"results": []},
            "LPASS": {"results": []},
        },
        "gpio_get_gpio_map": {
            "id": 8240,
            "group": {"name": "TLMM"},
            "chipio_release": {"name": "nordau_io v1.2 ECO F03 Release"},
        },
        "gpio_list_gpios_from_map": [
            {"name": "aud_intfc0_clk", "number": 57, "function": 1}
        ],
        "gpio_list_tlmm_gpios": [
            {"name": "aud_intfc0_clk", "number": 57, "function": 1}
        ],
        "chipio_get_qups": [{"se_number": 0, "i2c": True}],
        "buses_list_buses": [{"name": "audio_core_noc"}],
        "buses_list_bus_gateways": [],
        "buses_list_bidpidmids": [],
    }


# ── Allow-list enforcement ───────────────────────────────────────────────────


def test_allowlist_rejects_non_allowlisted_tool() -> None:
    try:
        C._require_readonly("not_a_real_tool")
    except PermissionError:
        print("PASS: allow-list refuses non-allow-listed tool name")
        return
    raise AssertionError("FAIL: allow-list did not refuse an unknown tool")


def test_allowlist_covers_exactly_ten_tools() -> None:
    assert READONLY_MCP_TOOLS == {
        "chips_list_chips",
        "cores_list_core_instances",
        "swi_search_swi",
        "gpio_get_gpio_map",
        "gpio_list_gpios_from_map",
        "gpio_list_tlmm_gpios",
        "chipio_get_qups",
        "buses_list_buses",
        "buses_list_bus_gateways",
        "buses_list_bidpidmids",
    }
    print("PASS: allow-list is exactly the ten mandated tools")


def test_collector_only_calls_allowlisted_tools() -> None:
    t = FakeTransport(_nord_like_responses())
    collect_snapshot("nordschleife_2.0", transport=t)
    invoked = {name for name, _ in t.calls}
    assert invoked <= READONLY_MCP_TOOLS, f"non-allow-listed calls: {invoked - READONLY_MCP_TOOLS}"
    # every mandated tool actually got called (swi via multiple terms)
    assert invoked == READONLY_MCP_TOOLS
    print("PASS: collector invokes only allow-listed tools, and calls every one")


def test_forbidden_paths_are_refused() -> None:
    for name in ("auth.json", ".credentials.json", "/tmp/auth.json"):
        try:
            C._assert_not_forbidden(name)
        except PermissionError:
            continue
        raise AssertionError(f"FAIL: _assert_not_forbidden({name!r}) did not raise")
    print("PASS: auth.json / .credentials.json are refused unconditionally")


# ── Snapshot shape + JSON serialisability ────────────────────────────────────


def test_snapshot_shape_and_all_tools_present() -> None:
    snap = collect_snapshot("nordschleife_2.0", transport=FakeTransport(_nord_like_responses()))
    assert snap["chip"] == "nordschleife_2.0"
    assert snap["provenance"]["tls"] == {
        "verify": True,
        "ssl_cert_file": C.SYSTEM_CA_STORE,
    }
    assert snap["provenance"]["readonly_tools"] == sorted(READONLY_MCP_TOOLS)
    assert snap["provenance"]["gpio_map"] == {
        "id": 8240,
        "release": "nordau_io v1.2 ECO F03 Release",
    }
    for name in READONLY_MCP_TOOLS:
        assert name in snap["tools"], f"missing tool entry {name!r}"
        entry = snap["tools"][name]
        assert "status" in entry and "payload" in entry and "result_digest" in entry
        assert entry["status"] in ("ok", "unavailable")
        if entry["status"] == "ok":
            assert isinstance(entry["result_digest"], str) and len(entry["result_digest"]) == 64
        else:
            assert entry["result_digest"] is None
            assert "error_class" in entry
    print("PASS: snapshot has every tool key with a valid shape")


def test_snapshot_is_json_serialisable() -> None:
    snap = collect_snapshot("nordschleife_2.0", transport=FakeTransport(_nord_like_responses()))
    blob = json.dumps(snap, sort_keys=True)
    assert isinstance(blob, str) and blob
    round_tripped = json.loads(blob)
    assert round_tripped["chip"] == "nordschleife_2.0"
    print("PASS: snapshot is JSON-serialisable (round-trips)")


# ── Digest stability ─────────────────────────────────────────────────────────


def test_digest_is_stable_across_runs() -> None:
    a = collect_snapshot("nord", transport=FakeTransport(_nord_like_responses()))
    b = collect_snapshot("nord", transport=FakeTransport(_nord_like_responses()))
    for name in READONLY_MCP_TOOLS:
        assert a["tools"][name]["result_digest"] == b["tools"][name]["result_digest"], name
    print("PASS: result_digest is stable across two independent runs")


def test_digest_changes_when_payload_changes() -> None:
    r1 = _nord_like_responses()
    r2 = _nord_like_responses()
    r2["chips_list_chips"] = [{"id": 999, "name": "OTHER"}]
    a = collect_snapshot("x", transport=FakeTransport(r1))
    b = collect_snapshot("x", transport=FakeTransport(r2))
    assert (
        a["tools"]["chips_list_chips"]["result_digest"]
        != b["tools"]["chips_list_chips"]["result_digest"]
    )
    print("PASS: result_digest changes when the payload changes")


# ── Unavailable-tool path ────────────────────────────────────────────────────


def test_unavailable_tool_records_error_and_snapshot_completes() -> None:
    r = _nord_like_responses()
    errs = {"chipio_get_qups": TimeoutError("boom")}
    snap = collect_snapshot("nord", transport=FakeTransport(r, errors=errs))
    qups = snap["tools"]["chipio_get_qups"]
    assert qups["status"] == "unavailable"
    assert qups["payload"] is None
    assert qups["result_digest"] is None
    assert qups["error_class"] == "TimeoutError"
    # rest of snapshot is intact
    assert snap["tools"]["chips_list_chips"]["status"] == "ok"
    assert snap["tools"]["buses_list_buses"]["status"] == "ok"
    print("PASS: one failing tool yields 'unavailable'; snapshot completes")


def test_missing_gpio_map_id_cascades_without_transport_call() -> None:
    r = _nord_like_responses()
    errs = {"gpio_get_gpio_map": RuntimeError("no map")}
    t = FakeTransport(r, errors=errs)
    snap = collect_snapshot("nord", transport=t)
    assert snap["tools"]["gpio_get_gpio_map"]["status"] == "unavailable"
    from_map = snap["tools"]["gpio_list_gpios_from_map"]
    assert from_map["status"] == "unavailable"
    assert from_map["error_class"] == "missing_gpio_map_id"
    # transport should never have been asked for gpio_list_gpios_from_map
    invoked = [name for name, _ in t.calls]
    assert "gpio_list_gpios_from_map" not in invoked
    # provenance.gpio_map records the absence
    assert snap["provenance"]["gpio_map"] == {"id": None, "release": None}
    print("PASS: missing gpio_map_id cascades to 'missing_gpio_map_id' without a call")


def test_swi_partial_failure_still_ok() -> None:
    r = _nord_like_responses()
    errs = {"SWR": RuntimeError("cap hit")}  # one of five terms fails
    snap = collect_snapshot("nord", transport=FakeTransport(r, errors=errs))
    swi = snap["tools"]["swi_search_swi"]
    assert swi["status"] == "ok", "some terms succeeded → tool status is ok"
    assert swi["payload"]["SWR"]["status"] == "unavailable"
    assert swi["payload"]["SOUNDWIRE_MASTER"]["status"] == "ok"
    print("PASS: swi_search_swi is 'ok' when at least one term answered")


def test_swi_total_failure_is_unavailable() -> None:
    r = _nord_like_responses()
    errs = {term: RuntimeError("cap") for term in SWI_QUERY_TERMS}
    snap = collect_snapshot("nord", transport=FakeTransport(r, errors=errs))
    swi = snap["tools"]["swi_search_swi"]
    assert swi["status"] == "unavailable"
    assert swi["error_class"] == "all_swi_queries_failed"
    print("PASS: swi_search_swi is 'unavailable' when every term failed")


# ── Determinism (fake-transport replay) ──────────────────────────────────────


def test_snapshots_are_byte_identical_under_replay() -> None:
    r = _nord_like_responses()
    a = collect_snapshot("nord", transport=FakeTransport(r))
    b = collect_snapshot("nord", transport=FakeTransport(r))
    ja = json.dumps(a, sort_keys=True)
    jb = json.dumps(b, sort_keys=True)
    assert ja == jb, "snapshots must be byte-identical under fake-transport replay"
    print("PASS: two runs produce byte-identical snapshots (fake-transport replay)")


def main() -> None:
    test_allowlist_rejects_non_allowlisted_tool()
    test_allowlist_covers_exactly_ten_tools()
    test_collector_only_calls_allowlisted_tools()
    test_forbidden_paths_are_refused()
    test_snapshot_shape_and_all_tools_present()
    test_snapshot_is_json_serialisable()
    test_digest_is_stable_across_runs()
    test_digest_changes_when_payload_changes()
    test_unavailable_tool_records_error_and_snapshot_completes()
    test_missing_gpio_map_id_cascades_without_transport_call()
    test_swi_partial_failure_still_ok()
    test_swi_total_failure_is_unavailable()
    test_snapshots_are_byte_identical_under_replay()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
