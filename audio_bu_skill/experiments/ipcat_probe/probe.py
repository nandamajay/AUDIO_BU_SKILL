#!/usr/bin/env python3
"""
Phase-1A IPCAT access probe  —  READ-ONLY, STANDALONE, NON-PRODUCTION.

Purpose
-------
The smallest possible experiment that validates *structured* IPCAT access
from the Audio BU Skill working environment, per docs/PHASE1_IMPLEMENTATION_PLAN.md
Phase-1A. It answers exactly three questions and nothing more:

    1. Can we connect to the provisioned mechanism?
    2. Is the response STRUCTURED (typed / JSON) rather than prose?
    3. Can a single known chip (Nord) be resolved?

It does NOT resolve Eliza (Phase-1B), does NOT obtain counts (Phase-1C),
does NOT generate anything, and is NOT imported by any production code.

Isolation guarantees
---------------------
* Lives under experiments/ipcat_probe/ — outside the orchestrator import path.
* Nothing in audio_bu_skill/orchestrator imports this module.
* All mechanism-specific dependencies (ipcat_client / fastmcp / httpx) are
  imported LAZILY inside the call paths, so `--check` runs with no deps and
  never triggers an install.

Safety invariants (enforced in code below)
-------------------------------------------
* READ-ONLY: only enumerate/lookup tools are ever named; a hard allow-list
  rejects any tool/function name that is not on it.
* TLS verification is ALWAYS on (verify=True). Unlike the k-genesis reference
  transport (scripts/mcp_client.py:73, verify=False), we never disable it.
* auth.json is NEVER opened. Config/token come from ~/.claude/.mcp.json
  (Path A) or the environment (Path B) — presence-checked, value never logged.
* No write-capable operation is invoked. No file under the kernel tree or the
  production package is created or modified.

Usage
-----
    # Inspect config/mechanism without connecting or needing deps:
    python probe.py --check

    # Path B (ipcat_client library provisioned):
    IPCAT_PROBE_MECHANISM=B python probe.py --chip <NORD_ALIAS>

    # Path A-Option-C (dedicated-token MCP provisioned):
    IPCAT_PROBE_MECHANISM=A python probe.py --chip <NORD_ALIAS>

Exit codes: 0 = success, 2 = partial (connected, unstructured/unresolved),
3 = failure (no connect / boundary-unsafe path required). See PHASE1A_README.md.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Read-only tool allow-list. A probe must never invoke anything not here.
# These are ENUMERATION / LOOKUP names only — no write/generate verbs.
# --------------------------------------------------------------------------
READONLY_MCP_TOOLS = frozenset({
    # minimal chip-identity lookups only; extended coverage is Phase-1B/1C
    "swi_search_swi",
    "get_chips",
    "get_modules",
})
READONLY_LIB_FUNCS = frozenset({
    "get_chips",
    "get_modules",
})

# Files this probe must NEVER open, regardless of mechanism.
FORBIDDEN_PATHS = ("auth.json",)


def _assert_not_forbidden(path: str) -> None:
    name = os.path.basename(str(path))
    if name in FORBIDDEN_PATHS:
        raise PermissionError(
            f"Refusing to access protected credential file '{name}'. "
            "Phase-1A is boundary-safe: presence checks only, never reads."
        )


def _require_readonly(name: str, allow_list) -> None:
    """Explicit read-only enforcement.

    Replaces `assert name in allow_list`, which is stripped when the
    interpreter runs under `-O`. This raises unconditionally, so the
    read-only invariant holds regardless of optimization flags.
    """
    if name not in allow_list:
        raise PermissionError(
            f"Refusing to invoke '{name}': not on the Phase-1A read-only "
            f"allow-list {sorted(allow_list)}. Only enumerate/lookup tools "
            "are permitted."
        )


# --------------------------------------------------------------------------
# Config discovery (presence-check only; token value is never returned/logged)
# --------------------------------------------------------------------------

def _mcp_config_present() -> tuple[bool, str]:
    """Return (present, redacted_summary) for ~/.claude/.mcp.json.

    We only confirm the ipcat server entry exists and carries *some* auth
    header. We never return or log the token value.
    """
    cfg_path = Path.home() / ".claude" / ".mcp.json"
    _assert_not_forbidden(cfg_path)          # defensive: this is NOT auth.json
    if not cfg_path.exists():
        return False, f"{cfg_path} (absent)"
    try:
        with cfg_path.open() as f:
            cfg = json.load(f)
    except (OSError, ValueError) as exc:
        return False, f"{cfg_path} (unreadable: {type(exc).__name__})"
    servers = cfg.get("mcpServers", {})
    entry = servers.get("ipcat-mcp-server")
    if not entry:
        return False, f"{cfg_path} (no 'ipcat-mcp-server' entry)"
    has_url = bool(entry.get("url"))
    has_auth = bool(entry.get("headers"))
    return (has_url and has_auth), (
        f"{cfg_path} (ipcat-mcp-server: url={'yes' if has_url else 'no'}, "
        f"auth-header={'present' if has_auth else 'absent'})"
    )


def _lib_credential_present() -> tuple[bool, str]:
    """Path B: env-var-first credential presence (value never logged)."""
    candidates = ("IPCAT_TOKEN", "QGENIE_TOKEN", "IPCAT_CLIENT_TOKEN")
    for var in candidates:
        if os.environ.get(var):
            return True, f"env:{var} (present)"
    return False, f"none of {candidates} set in env"


# --------------------------------------------------------------------------
# Structured-response check — the core of Phase-1A question #2
# --------------------------------------------------------------------------

def _is_structured(obj) -> bool:
    """Structured == a parsed dict/list, NOT a bare prose string."""
    return isinstance(obj, (dict, list))


# --------------------------------------------------------------------------
# Path B — ipcat_client library
# --------------------------------------------------------------------------

def probe_path_b(chip: str) -> dict:
    present, summary = _lib_credential_present()
    result = {"mechanism": "B (ipcat_client)", "credential": summary}
    if not present:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note="credential absent — provision env-var-first token")
        return result
    try:
        import ipcat_client  # lazy: only when actually running Path B
    except ImportError as exc:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=f"ipcat_client not importable ({exc}); "
                           "Path B not provisioned")
        return result

    # read-only lookup only
    fn_name = "get_chips"
    _require_readonly(fn_name, READONLY_LIB_FUNCS)
    fn = getattr(ipcat_client, fn_name, None)
    if fn is None:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=f"ipcat_client.{fn_name} unavailable")
        return result
    resp = fn()                                   # READ-ONLY enumerate
    structured = _is_structured(resp)
    nord = _resolve_chip_in(resp, chip)
    result.update(connected=True, structured=structured, nord_resolved=nord,
                  note="ok" if (structured and nord) else "see fields")
    return result


# --------------------------------------------------------------------------
# Path A-Option-C — dedicated-token remote MCP (TLS ALWAYS ON)
# --------------------------------------------------------------------------

def probe_path_a(chip: str) -> dict:
    present, summary = _mcp_config_present()
    result = {"mechanism": "A-Option-C (dedicated-token MCP)", "config": summary}
    if not present:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note="mcp config/token absent — provision ~/.claude/.mcp.json")
        return result
    try:
        import asyncio
        import httpx                              # lazy
        from fastmcp import Client                # lazy
        from fastmcp.client.transports import StreamableHttpTransport
    except ImportError as exc:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=f"MCP client deps not importable ({exc}); "
                           "Path A not provisioned")
        return result

    cfg_path = Path.home() / ".claude" / ".mcp.json"
    with cfg_path.open() as f:
        entry = json.load(f)["mcpServers"]["ipcat-mcp-server"]
    url = entry["url"].rstrip("/")

    def _tls_on_factory(headers=None, auth=None, timeout=None, **kwargs):
        kwargs.setdefault("follow_redirects", True)
        # verify=True — TLS verification stays ON (unlike k-genesis verify=False)
        return httpx.AsyncClient(headers=headers, auth=auth, timeout=timeout,
                                 verify=True, **kwargs)

    transport = StreamableHttpTransport(
        url=url, headers=entry.get("headers", {}),
        httpx_client_factory=_tls_on_factory,
    )

    tool = "get_chips"
    _require_readonly(tool, READONLY_MCP_TOOLS)

    async def _run():
        async with Client(transport) as c:
            raw = await c.call_tool(tool, {})     # READ-ONLY enumerate
            content = getattr(raw, "content", raw)
            text = "".join(getattr(p, "text", "") for p in content) \
                if isinstance(content, list) else str(content)
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return text                        # prose → unstructured

    resp = asyncio.run(_run())
    structured = _is_structured(resp)
    nord = _resolve_chip_in(resp, chip)
    result.update(connected=True, structured=structured, nord_resolved=nord,
                  note="ok" if (structured and nord) else "see fields")
    return result


# --------------------------------------------------------------------------
# Nord resolution (question #3) — search a structured enumeration only.
# Eliza is intentionally NOT resolved here (that is Phase-1B).
# --------------------------------------------------------------------------

def _resolve_chip_in(resp, chip: str) -> bool:
    if not chip or not _is_structured(resp):
        return False
    needle = chip.strip().lower()
    rows = resp if isinstance(resp, list) else resp.get("chips", resp.get("data", []))
    if not isinstance(rows, list):
        return False
    for row in rows:
        hay = json.dumps(row).lower() if isinstance(row, (dict, list)) else str(row).lower()
        if needle in hay:
            return True
    return False


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Phase-1A IPCAT read-only probe")
    ap.add_argument("--chip", default=os.environ.get("IPCAT_PROBE_CHIP", ""),
                    help="Known chip to resolve (Nord alias). Not stored.")
    ap.add_argument("--mechanism",
                    default=os.environ.get("IPCAT_PROBE_MECHANISM", ""),
                    choices=["A", "B", ""],
                    help="A = dedicated-token MCP, B = ipcat_client")
    ap.add_argument("--check", action="store_true",
                    help="Config/presence check only — no connection, no deps")
    args = ap.parse_args()

    if args.check:
        b_present, b_sum = _lib_credential_present()
        a_present, a_sum = _mcp_config_present()
        print(json.dumps({
            "mode": "check",
            "path_b_ipcat_client": {"credential_present": b_present, "detail": b_sum},
            "path_a_mcp": {"config_present": a_present, "detail": a_sum},
            "note": "presence checks only; no connection attempted; "
                    "auth.json never accessed; TLS enforced when connecting",
        }, indent=2))
        return 0

    if not args.mechanism:
        print("ERROR: choose --mechanism A|B (or set IPCAT_PROBE_MECHANISM). "
              "This is set by the operator's provisioning decision.",
              file=sys.stderr)
        return 3
    if not args.chip:
        print("ERROR: --chip <NORD_ALIAS> required (or IPCAT_PROBE_CHIP).",
              file=sys.stderr)
        return 3

    result = probe_path_a(args.chip) if args.mechanism == "A" \
        else probe_path_b(args.chip)
    print(json.dumps(result, indent=2))

    if result.get("connected") and result.get("structured") and result.get("nord_resolved"):
        return 0                                   # success
    if result.get("connected"):
        return 2                                   # partial
    return 3                                        # failure


if __name__ == "__main__":
    raise SystemExit(main())
