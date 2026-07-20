"""WP-IPCAT-A C1 — live MCP transport (the ONLY socket-opener).

Adapted from the *working* helper ``experiments/ipcat_probe/_live_session.py``
(never from the broken ``probe.py``): JSON-RPC ``initialize`` to capture
``mcp-session-id`` → ``notifications/initialized`` → read-only ``tools/call``,
with SSE ``data:`` extraction, ``verify=True``, ``SSL_CERT_FILE`` set, and a
finite per-call timeout. The tool allow-list is **corrected** to the real MCP
names (``chips_list_chips`` etc.), fixing the probe's W1/D1 defect *in this new
module only*.

**Inertness (C1).** Importing this module opens no socket. The single function
that ever opens one is :func:`open_session`, and — in C1 — its only caller is
:func:`~orchestrator.ipcat_acquire.acquire_to_cache`, whose only intended
in-tree caller (``do_refresh_ipcat_cache``) does not exist until C2. There is no
edge from any existing flow into this package. Every test drives the flow
through an **injected mock transport**, so the live path is present but never
triggered.

**Safety invariants (design §2.1, §4.2; probe hardening).**

- **TLS always verified.** The real transport constructs ``httpx.Client`` with
  ``verify=True``; there is no code path that disables verification.
- **Read-only allow-list.** :func:`_require_readonly` raises
  :class:`PermissionError` (not ``assert`` — survives ``python -O``) for any
  tool name that is not an unambiguous read verb, so a mutating call can never
  be issued.
- **No credential files.** This module never opens ``auth.json`` or
  ``.credentials.json``; the bearer header is read by reference from the MCP
  entry and is never logged or returned.
- **No username.** The gateway derives identity from the token; a username is
  never sent.
- **Redacted failures.** Callers catch exceptions and reduce them via
  ``errors.classify_error`` (class name only). The auth wall is detected by
  substring and surfaced as a sentinel, never as a raised credential string.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Protocol

# ── read-only enforcement ─────────────────────────────────────────────────────

# A tool is callable only if its name contains a read verb and NO mutation verb.
_READ_TOKENS = ("list", "get", "search")
_MUTATION_TOKENS = (
    "create", "update", "delete", "write", "set", "add", "remove",
    "submit", "upload", "abort", "resume", "generate", "send", "reply",
    "put", "post", "patch", "exec", "run",
)

# Sentinel keys returned by a transport call (never raised) so the flow can
# branch without parsing a message that might carry sensitive text.
AUTHWALL_KEY = "_authwall"
ERROR_KEY = "_error"

_AUTHWALL_MARKER = "Authentication required"


def _require_readonly(tool: str) -> None:
    """Raise :class:`PermissionError` unless ``tool`` is an unambiguous read.

    Uses a raise, not ``assert``, so the guard is retained under ``python -O``.
    """
    name = tool.lower()
    if any(tok in name for tok in _MUTATION_TOKENS):
        raise PermissionError(f"refusing non-read-only tool: {tool!r}")
    if not any(tok in name for tok in _READ_TOKENS):
        raise PermissionError(f"tool not on read-only allow-list: {tool!r}")


# ── transport abstraction (injectable) ────────────────────────────────────────

class Transport(Protocol):
    """Minimal transport surface the flow depends on.

    Tests inject a fake implementing this Protocol so the network is never
    touched; the real :class:`HttpxTransport` is the sole socket-opener.
    """

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        """Issue a read-only ``tools/call`` and return the parsed result.

        On the auth wall, return ``{AUTHWALL_KEY: <redacted>}``; on a protocol
        error, return ``{ERROR_KEY: <object>}``; otherwise return the parsed
        JSON (or raw text) of the tool's content.
        """
        ...

    def close(self) -> None:
        ...


def _extract(text: str) -> Any:
    """Parse an MCP HTTP body that may be a raw JSON or an SSE ``data:`` line."""
    if "data:" in text[:20]:
        for ln in text.splitlines():
            if ln.startswith("data:"):
                return json.loads(ln[5:].strip())
    return json.loads(text)


class HttpxTransport:
    """The real live transport. Constructing it opens a socket — do not import-
    time instantiate. Mirrors ``_live_session.Session`` with corrected names and
    a bounded timeout, ``verify=True`` hard-wired.
    """

    def __init__(self, timeout_s: float = 90.0) -> None:
        # Import httpx lazily so merely importing this module (C1 inertness)
        # neither requires httpx nor touches TLS state.
        os.environ.setdefault("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
        import httpx  # local import — no import-time dependency

        entry = json.load(
            open(Path.home() / ".claude" / ".mcp.json")
        )["mcpServers"]["ipcat-mcp-server"]
        self._url = entry["url"].rstrip("/")
        hdr = dict(entry.get("headers", {}))
        hdr.setdefault("Accept", "application/json, text/event-stream")
        hdr.setdefault("Content-Type", "application/json")

        self._client = httpx.Client(verify=True, timeout=httpx.Timeout(timeout_s))
        r = self._client.post(
            self._url, headers=hdr,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "ipcat-acquire", "version": "0"},
                },
            },
        )
        sid = r.headers.get("mcp-session-id")
        self._hdr = dict(hdr)
        if sid:
            self._hdr["mcp-session-id"] = sid
            self._client.post(
                self._url, headers=self._hdr,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        _require_readonly(tool)
        r = self._client.post(
            self._url, headers=self._hdr,
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool, "arguments": dict(args)},
            },
        )
        j = _extract(r.text)
        if j.get("error"):
            return {ERROR_KEY: j["error"]}
        res = j.get("result", {})
        content = res.get("content", [])
        text = (
            "".join(p.get("text", "") for p in content)
            if isinstance(content, list) else str(content)
        )
        if isinstance(text, str) and _AUTHWALL_MARKER in text:
            return {AUTHWALL_KEY: text[:120]}
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text

    def close(self) -> None:
        self._client.close()


def open_session(
    mechanism: str, *, transport: Transport | None = None, timeout_s: float = 90.0
) -> Transport:
    """Return a live :class:`Transport` — the **only** socket-opener in C1.

    ``transport`` is an injection seam: when provided (tests), it is returned
    unchanged and no socket is opened. When ``None`` (production, C2-reachable
    only), a real :class:`HttpxTransport` is constructed, which is what opens
    the socket. ``mechanism`` is recorded in provenance by the caller; it does
    not change the transport shape in C1.
    """
    if transport is not None:
        return transport
    return HttpxTransport(timeout_s=timeout_s)


__all__ = [
    "Transport",
    "HttpxTransport",
    "open_session",
    "AUTHWALL_KEY",
    "ERROR_KEY",
]
