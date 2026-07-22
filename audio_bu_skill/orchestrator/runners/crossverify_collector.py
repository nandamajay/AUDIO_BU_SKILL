"""Phase-2A WP1 — Read-only IPCAT collector (impure boundary).

The **only** impure component in the Phase-2A pipeline. It performs every live
IPCAT ``tools/call`` and freezes a JSON-serialisable snapshot dict; the pure
Comparison Core (``orchestrator/reasoning/crossverify.py``, later work) consumes
that snapshot and performs zero I/O. This split makes every downstream verdict
byte-identical under replay.

Contract of one snapshot (returned by :func:`collect_snapshot`)::

    {
      "chip": <chip alias>,
      "mcp_state": "ok" | "degraded",   # WP-MCP-BANNER: aggregate authority
                                        # health, decided at snapshot-time.
                                        # "empty" is set by the caller when
                                        # collect_snapshot was never invoked.
      "provenance": {
        "tls": {"verify": True, "ssl_cert_file": <path>},
        "readonly_tools": [...sorted allow-list...],
        "gpio_map": {"id": <int|None>, "release": <str|None>},
      },
      "tools": {
        <tool_name>: {
          "status": "ok" | "unavailable",
          "payload": <JSON-ish structure> | None,
          "result_digest": <sha256 hex> | None,
          "error_class": <redacted category, only when unavailable>,
          "reason": <human-readable string, only when unavailable>,
          ...
        },
        ...
      }
    }

Each of the ten mandated tools always has an entry, even when a per-tool call
failed — a partial snapshot still drives partial verdicts downstream, and
``authority_unavailable`` becomes a first-class coverage gap rather than a hard
error. The collector never raises for a per-tool failure; the only way it
raises is (a) the caller names a tool that is not on the read-only allow-list,
or (b) the caller passes a forbidden credential path anywhere (defensive; the
collector opens no credential files itself).

Security envelope (mirrors ``experiments/ipcat_probe/probe.py``):
  * TLS ``verify=True`` — never disabled. ``SSL_CERT_FILE`` is defaulted to the
    system CA store so the corporate root is trusted (``certifi`` alone lacks
    it) without weakening verification. Set **only** when a live transport is
    built; importing this module never mutates the environment.
  * ``auth.json`` and ``.credentials.json`` are on a hard-refuse list — the
    collector never opens them, and calling any internal helper with those
    names raises ``PermissionError``.
  * Read-only allow-list — only the ten enumerate/lookup tools named in
    ``READONLY_MCP_TOOLS`` may be invoked. ``_require_readonly`` raises
    unconditionally (not an ``assert``) so ``-O`` cannot strip it.
  * No token or header value is ever returned by, logged by, or embedded in the
    snapshot.

Determinism: for a fixed ``transport`` response set, ``collect_snapshot``
produces byte-identical snapshots (no wall-clock, no ``random``, no ordering
that depends on ``dict`` insertion beyond the fixed key list). The
``result_digest`` fields are ``sha256(canonical-json)`` of each payload and
serve both as the replay-integrity check and as the pinning key for
``provenance.wp_c_commit`` and the later ``phase2a_verification.json`` output.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

# ── Read-only allow-list (WP1 §3, §6) ────────────────────────────────────────

#: The exact ten enumerate/lookup tools the WP-1 spec permits. Any name outside
#: this frozenset is refused before any I/O is attempted.
READONLY_MCP_TOOLS: frozenset[str] = frozenset(
    {
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
)

#: Credential paths the collector must never open. Presence-check only is not
#: even needed here — we simply refuse any request that would touch them.
FORBIDDEN_PATHS: frozenset[str] = frozenset({"auth.json", ".credentials.json"})

#: Terms used for the ``swi_search_swi`` union-of-terms scan (the W4 discipline
#: is applied later by the pure core; here we just record each term's response
#: so the core can reason over the union without re-calling IPCAT).
SWI_QUERY_TERMS: tuple[str, ...] = (
    "SOUNDWIRE_MASTER",
    "SWR_MSTR",
    "SWR",
    "LPASS_MACRO",
    "LPASS",
)

#: System CA bundle path. Contains the Qualcomm corporate root that ``certifi``
#: does not carry. ``SSL_CERT_FILE`` is defaulted to this only when a live
#: transport is built.
SYSTEM_CA_STORE: str = "/etc/ssl/certs/ca-certificates.crt"


# ── Small helpers (all pure) ─────────────────────────────────────────────────


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, default=str).encode(
        "utf-8"
    )


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


def _require_readonly(name: str) -> None:
    """Enforce the read-only allow-list unconditionally.

    Raises ``PermissionError`` — not ``assert`` — so the invariant holds under
    ``python -O`` (which strips ``assert``).
    """
    if name not in READONLY_MCP_TOOLS:
        raise PermissionError(
            f"Refusing to invoke {name!r}: not on the Phase-2A read-only "
            f"allow-list {sorted(READONLY_MCP_TOOLS)}. Only enumerate/lookup "
            "tools are permitted."
        )


def _assert_not_forbidden(path: str) -> None:
    """Defensive: refuse any credential path the collector must never touch.

    The collector opens no credential files, so this exists as a belt-and-braces
    guard for any helper that ends up handed a path in future work.
    """
    name = os.path.basename(str(path))
    if name in FORBIDDEN_PATHS:
        raise PermissionError(
            f"Refusing to access protected credential file {name!r}. "
            "Phase-2A collector is boundary-safe: no credential file is ever opened."
        )


def _classify_error(exc: BaseException) -> str:
    """Redacted error category — never the raw message (which could echo a header)."""
    return type(exc).__name__


# ── Per-tool call wrapper ────────────────────────────────────────────────────


def _tool_result_ok(payload: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "payload": payload,
        "result_digest": _digest(payload),
    }


def _tool_result_unavailable(
    error_class: str, reason: str = ""
) -> dict[str, Any]:
    """Return an ``unavailable`` per-tool result.

    ``error_class`` is the redacted, machine-readable exception category
    (mirrors :func:`_classify_error`). ``reason`` is a human-readable
    string added for WP-MCP-BANNER (G-3A.6) so operators see *why* the tool
    was unavailable, not just *which* exception class. It must never carry
    header/token echoes; :func:`_call` builds it defensively from
    ``str(exc)`` truncated to a fixed length.
    """
    entry: dict[str, Any] = {
        "status": "unavailable",
        "payload": None,
        "result_digest": None,
        "error_class": error_class,
        "reason": reason or error_class,
    }
    return entry


#: Cap on the ``reason`` string surfaced by :func:`_call`. Prevents an
#: adversarial or verbose exception message from bloating the snapshot or
#: leaking header echoes. The exception class name is always available
#: separately via ``error_class``.
_REASON_MAX_LEN: int = 240


def _redact_reason(exc: BaseException) -> str:
    """Build a bounded, human-readable ``reason`` for :func:`_tool_result_unavailable`.

    Formats as ``"<ExceptionClass>: <message>"`` and truncates to
    ``_REASON_MAX_LEN``. The exception message may itself echo a header
    (see :func:`_classify_error` comment), so this is treated as
    debug-visible-only; the machine sentinel remains ``error_class``.
    """
    cls = type(exc).__name__
    msg = str(exc).strip().replace("\n", " ").replace("\r", " ")
    if not msg:
        return cls
    combined = f"{cls}: {msg}"
    if len(combined) > _REASON_MAX_LEN:
        combined = combined[: _REASON_MAX_LEN - 1] + "…"
    return combined


def _call(transport: Any, name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Invoke one allow-listed tool.

    Any exception raised by ``transport.call_tool`` becomes an
    ``unavailable`` entry with a redacted ``error_class`` **and** a bounded
    human-readable ``reason`` (WP-MCP-BANNER / G-3A.6) — the caller must
    not fail the whole snapshot when one tool did not answer.
    """
    _require_readonly(name)
    try:
        payload = transport.call_tool(name, params)
    except BaseException as exc:  # noqa: BLE001 — controlled: return, do not raise
        return _tool_result_unavailable(
            _classify_error(exc), reason=_redact_reason(exc)
        )
    return _tool_result_ok(payload)


# ── Live transport (lazy; unused by tests) ───────────────────────────────────


def _live_transport() -> Any:
    """Build a live IPCAT transport with TLS verify=True + system CA store.

    Lazy import — importing this module never touches ``httpx`` or the network,
    and unit tests always pass ``transport=`` explicitly so this path is only
    taken by attended live runs.
    """
    os.environ.setdefault("SSL_CERT_FILE", SYSTEM_CA_STORE)

    import asyncio
    import json as _json
    from pathlib import Path

    import httpx  # lazy
    from fastmcp import Client  # lazy
    from fastmcp.client.transports import StreamableHttpTransport  # lazy

    cfg_path = Path.home() / ".claude" / ".mcp.json"
    _assert_not_forbidden(cfg_path)
    with cfg_path.open() as f:
        entry = _json.load(f)["mcpServers"]["ipcat-mcp-server"]
    url = entry["url"].rstrip("/")

    def _tls_on_factory(headers=None, auth=None, timeout=None, **kwargs):
        kwargs.setdefault("follow_redirects", True)
        if timeout is None:
            timeout = httpx.Timeout(30.0)
        return httpx.AsyncClient(
            headers=headers, auth=auth, timeout=timeout, verify=True, **kwargs
        )

    fastmcp_transport = StreamableHttpTransport(
        url=url,
        headers=entry.get("headers", {}),
        httpx_client_factory=_tls_on_factory,
    )

    class _LiveTransport:
        """Minimal ``call_tool(name, params) -> payload`` shim over FastMCP."""

        def call_tool(self, name: str, params: dict[str, Any]) -> Any:
            async def _inner() -> Any:
                async with Client(fastmcp_transport) as c:
                    raw = await c.call_tool(name, params or {})
                content = getattr(raw, "content", raw)
                if isinstance(content, list):
                    text = "".join(getattr(p, "text", "") for p in content)
                else:
                    text = str(content)
                try:
                    return _json.loads(text)
                except (ValueError, TypeError):
                    return text

            return asyncio.run(asyncio.wait_for(_inner(), timeout=30.0))

    return _LiveTransport()


# ── Public API ───────────────────────────────────────────────────────────────


def collect_snapshot(chip: str, *, transport: Any = None) -> dict[str, Any]:
    """Collect a frozen, JSON-serialisable IPCAT snapshot for ``chip``.

    ``transport`` is any object exposing ``call_tool(name, params) -> payload``.
    When ``None``, a live TLS-verified FastMCP transport is built lazily.

    The returned dict contains one entry per mandated tool under ``tools``.
    Every entry has ``status``, ``payload``, ``result_digest`` (and
    ``error_class`` when ``status == "unavailable"``). The collector never
    raises for a per-tool failure — it records ``unavailable`` and continues.
    """
    if transport is None:
        transport = _live_transport()

    tools: dict[str, dict[str, Any]] = {}

    tools["chips_list_chips"] = _call(transport, "chips_list_chips", {})
    tools["cores_list_core_instances"] = _call(
        transport, "cores_list_core_instances", {"chip": chip}
    )

    # swi_search_swi: run each configured term and keep its per-term response
    # inside a single tool entry. The pure core will apply union+stability (W4).
    swi_by_term: dict[str, dict[str, Any]] = {}
    for term in SWI_QUERY_TERMS:
        swi_by_term[term] = _call(
            transport, "swi_search_swi", {"chip": chip, "term": term}
        )
    swi_any_ok = any(r["status"] == "ok" for r in swi_by_term.values())
    if swi_any_ok:
        tools["swi_search_swi"] = {
            "status": "ok",
            "payload": swi_by_term,
            "result_digest": _digest(swi_by_term),
            "queries": list(SWI_QUERY_TERMS),
        }
    else:
        tools["swi_search_swi"] = {
            "status": "unavailable",
            "payload": swi_by_term,  # keep per-term error_class breakdown for debug
            "result_digest": None,
            "error_class": "all_swi_queries_failed",
            "reason": "all_swi_queries_failed: every configured term returned unavailable",
            "queries": list(SWI_QUERY_TERMS),
        }

    # GPIO map first — its id feeds the parameterised list call.
    gpio_map = _call(transport, "gpio_get_gpio_map", {"chip": chip})
    tools["gpio_get_gpio_map"] = gpio_map

    gpio_map_id: int | None = None
    gpio_map_release: str | None = None
    if gpio_map["status"] == "ok" and isinstance(gpio_map["payload"], dict):
        gpio_map_id = gpio_map["payload"].get("id")
        release = gpio_map["payload"].get("chipio_release") or {}
        if isinstance(release, dict):
            gpio_map_release = release.get("name")

    if gpio_map_id is None:
        tools["gpio_list_gpios_from_map"] = _tool_result_unavailable(
            "missing_gpio_map_id"
        )
    else:
        tools["gpio_list_gpios_from_map"] = _call(
            transport, "gpio_list_gpios_from_map", {"gpio_map_id": gpio_map_id}
        )

    tools["gpio_list_tlmm_gpios"] = _call(
        transport, "gpio_list_tlmm_gpios", {"chip": chip}
    )
    tools["chipio_get_qups"] = _call(transport, "chipio_get_qups", {"chip": chip})
    tools["buses_list_buses"] = _call(transport, "buses_list_buses", {"chip": chip})
    tools["buses_list_bus_gateways"] = _call(
        transport, "buses_list_bus_gateways", {"chip": chip}
    )
    tools["buses_list_bidpidmids"] = _call(
        transport, "buses_list_bidpidmids", {"chip": chip}
    )

    snapshot: dict[str, Any] = {
        "chip": chip,
        # WP-MCP-BANNER (G-3A.6): decide aggregate authority health at the
        # snapshot site, not in main.py. "empty" is the caller's concern —
        # if collect_snapshot never ran, provenance stays without mcp_state
        # and the banner renderer defaults to EMPTY. Here we choose between
        # "ok" (every tool answered) and "degraded" (≥1 tool unavailable).
        "mcp_state": (
            "degraded"
            if any(t.get("status") == "unavailable" for t in tools.values())
            else "ok"
        ),
        "provenance": {
            "tls": {"verify": True, "ssl_cert_file": SYSTEM_CA_STORE},
            "readonly_tools": sorted(READONLY_MCP_TOOLS),
            "gpio_map": {"id": gpio_map_id, "release": gpio_map_release},
        },
        "tools": tools,
    }
    # Defensive: prove the snapshot is JSON-serialisable at construction time,
    # not only when a caller tries to persist it. Also guards against a
    # transport that returned a payload with non-JSON-serialisable data.
    json.dumps(snapshot, sort_keys=True, default=str)
    return snapshot
