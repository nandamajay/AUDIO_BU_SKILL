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
* Live-call failures (TLS/DNS/connect/HTTP/MCP/library) are CAUGHT and mapped
  to the exit-code contract with a redacted category label — never a traceback,
  never a raw exception message (which could echo header/token material).
* Every live call is bounded by a finite, configurable timeout
  (IPCAT_PROBE_TIMEOUT, default 30s), reported as a clean failure.

Usage
-----
    # Inspect config/mechanism without connecting or needing deps:
    python probe.py --check

    # Path B (ipcat_client library provisioned):
    IPCAT_PROBE_MECHANISM=B python probe.py --chip <NORD_ALIAS>

    # Path A-Option-C (dedicated-token MCP provisioned):
    IPCAT_PROBE_MECHANISM=A python probe.py --chip <NORD_ALIAS>

Exit codes: 0 = success, 2 = partial (connected, unstructured/unresolved),
3 = failure (no connect / boundary-unsafe path required / live-call error /
timeout). See PHASE1A_README.md.
"""

import argparse
import concurrent.futures
import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------
# Finite, configurable per-call timeout. Bounds every live call so a hung
# endpoint yields a clean failure rather than an indefinite block.
try:
    PROBE_TIMEOUT_SECONDS = float(os.environ.get("IPCAT_PROBE_TIMEOUT", "30"))
    if PROBE_TIMEOUT_SECONDS <= 0:
        PROBE_TIMEOUT_SECONDS = 30.0
except ValueError:
    PROBE_TIMEOUT_SECONDS = 30.0

# Named identifier fields used for chip resolution (NO substring matching).
# This is the deterministic foundation Phase-1B's resolution contract builds on.
IDENTIFIER_FIELDS = (
    "chip_id", "id", "canonical_name", "name", "chip_name", "alias", "aliases",
)

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


def _classify_error(exc) -> str:
    """Return a SAFE, redacted category for a live-call exception.

    Walks the exception chain and reports only exception *type names* plus a
    coarse category. The raw exception message is deliberately NOT included:
    network errors are unlikely to echo the auth header, but omitting the
    message removes any possibility of token leakage into probe output.
    """
    chain = []
    seen = 0
    e = exc
    while e is not None and seen < 12:
        chain.append(type(e).__name__)
        e = e.__cause__ or e.__context__
        seen += 1
    names = " <- ".join(chain) or type(exc).__name__
    low = names.lower()
    if "sslcert" in low or "certificate" in low or "ssl" in low:
        cat = "tls_verification_failed"
    elif "gaierror" in low or "nameresolution" in low or "dns" in low:
        cat = "dns_failure"
    elif "timeout" in low:
        cat = "timeout"
    elif "connect" in low:
        cat = "connection_failed"
    elif "httpstatus" in low or "httperror" in low or "http" in low \
            or "responsevalidation" in low:
        cat = "http_error"
    elif "mcp" in low or "tool" in low:
        cat = "mcp_error"
    else:
        cat = "call_failed"
    return f"{cat} ({names})"


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


def _call_with_timeout(fn, *args):
    """Run a blocking callable with a finite wall-clock timeout.

    Used for the synchronous Path B library call. Raises
    concurrent.futures.TimeoutError on expiry (mapped to a clean failure by
    the caller). The worker thread is not force-killed — it is abandoned as a
    daemon — which is acceptable for a read-only probe.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *args)
        return fut.result(timeout=PROBE_TIMEOUT_SECONDS)


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
    try:
        resp = _call_with_timeout(fn)             # READ-ONLY enumerate, bounded
    except concurrent.futures.TimeoutError:
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=f"timeout after {PROBE_TIMEOUT_SECONDS:g}s")
        return result
    except BaseException as exc:                   # noqa: BLE001 — controlled
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=_classify_error(exc))
        return result
    structured = _is_structured(resp)
    resolution = _resolve_chip_in(resp, chip)
    result.update(connected=True, structured=structured,
                  nord_resolved=resolution["resolved"],
                  resolution=resolution,
                  note="ok" if (structured and resolution["resolved"]) else "see fields")
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
        # A finite client timeout backstops the outer wall-clock timeout.
        if timeout is None:
            timeout = httpx.Timeout(PROBE_TIMEOUT_SECONDS)
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
        # Inner asyncio timeout so the connection cannot hang past the budget.
        async def _inner():
            async with Client(transport) as c:
                raw = await c.call_tool(tool, {})  # READ-ONLY enumerate
                content = getattr(raw, "content", raw)
                text = "".join(getattr(p, "text", "") for p in content) \
                    if isinstance(content, list) else str(content)
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return text                    # prose → unstructured
        return await asyncio.wait_for(_inner(), timeout=PROBE_TIMEOUT_SECONDS)

    try:
        resp = asyncio.run(_run())
    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=f"timeout after {PROBE_TIMEOUT_SECONDS:g}s")
        return result
    except BaseException as exc:                   # noqa: BLE001 — controlled
        result.update(connected=False, structured=False, nord_resolved=False,
                      note=_classify_error(exc))
        return result
    structured = _is_structured(resp)
    resolution = _resolve_chip_in(resp, chip)
    result.update(connected=True, structured=structured,
                  nord_resolved=resolution["resolved"],
                  resolution=resolution,
                  note="ok" if (structured and resolution["resolved"]) else "see fields")
    return result


# --------------------------------------------------------------------------
# Nord resolution (question #3) — NAMED-FIELD matching over a structured
# enumeration. NO substring matching. Deterministic selection + ambiguity
# detection. This is the foundation Phase-1B's resolution contract builds on
# (RESOLVED / ABSENT / AMBIGUOUS). Eliza is intentionally NOT resolved here.
# --------------------------------------------------------------------------

def _iter_rows(resp):
    """Yield candidate row dicts from a structured enumeration."""
    if isinstance(resp, list):
        rows = resp
    elif isinstance(resp, dict):
        rows = resp.get("chips", resp.get("data", resp.get("results", [])))
    else:
        rows = []
    return rows if isinstance(rows, list) else []


def _field_values(row) -> list:
    """Return the string values of a row's IDENTIFIER_FIELDS (only)."""
    if not isinstance(row, dict):
        return []
    vals = []
    for key in IDENTIFIER_FIELDS:
        if key not in row:
            continue
        v = row[key]
        if isinstance(v, (list, tuple)):
            vals.extend(str(x) for x in v)
        elif v is not None:
            vals.append(str(v))
    return vals


def _resolve_chip_in(resp, chip: str) -> dict:
    """Resolve *chip* against named identifier fields only.

    Returns a structured resolution (the Phase-1B foundation):
        {status: RESOLVED|ABSENT|AMBIGUOUS|UNSTRUCTURED,
         resolved: bool, matched_field: str|None, candidates: [...]}

    Matching is EXACT (case-insensitive) on a named identifier field — never a
    JSON substring — so an alias that merely appears inside an unrelated value
    cannot produce a false positive. >1 distinct matching row => AMBIGUOUS
    (never silently picks one).
    """
    empty = {"status": "UNSTRUCTURED", "resolved": False,
             "matched_field": None, "candidates": []}
    if not chip or not _is_structured(resp):
        return empty
    needle = chip.strip().lower()
    matches = []
    for idx, row in enumerate(_iter_rows(resp)):
        for key in IDENTIFIER_FIELDS:
            if not isinstance(row, dict) or key not in row:
                continue
            v = row[key]
            candidates = ([str(x) for x in v]
                          if isinstance(v, (list, tuple)) else [str(v)])
            if any(c.strip().lower() == needle for c in candidates):
                matches.append({"row_index": idx, "matched_field": key,
                                "identifiers": _field_values(row)})
                break
    # Distinct rows only (same row matched via >1 field counts once).
    distinct = {m["row_index"]: m for m in matches}
    if len(distinct) == 1:
        m = next(iter(distinct.values()))
        return {"status": "RESOLVED", "resolved": True,
                "matched_field": m["matched_field"], "candidates": [m]}
    if len(distinct) > 1:
        return {"status": "AMBIGUOUS", "resolved": False,
                "matched_field": None, "candidates": list(distinct.values())}
    return {"status": "ABSENT", "resolved": False,
            "matched_field": None, "candidates": []}


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
            "timeout_seconds": PROBE_TIMEOUT_SECONDS,
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
