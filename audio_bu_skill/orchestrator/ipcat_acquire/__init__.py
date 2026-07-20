"""WP-IPCAT-A C1 — public surface: ``acquire_to_cache`` + result types.

This is the package entry point (design §2.1, §2.2). It orchestrates the inert
building blocks — :mod:`.client` (transport), :mod:`.manifest` (the Q2 query
set), :mod:`.normalize` (canonical bytes + W4 counting), :mod:`.provenance`
(schema), :mod:`.materialize` (atomic publish) — into one operator-initiated
acquisition, and returns an :class:`AcquireResult` describing the outcome.

**Inertness (C1).** Importing this package opens no socket and touches no live
name on disk. :func:`acquire_to_cache` is never called by any existing flow —
its only intended in-tree caller, ``do_refresh_ipcat_cache``, does not exist
until C2. Every test drives it through an **injected mock transport**
(``transport=`` seam), so the live path is present but never triggered.

**No process control here.** :func:`acquire_to_cache` returns a status; it never
calls ``sys.exit``. The status→exit-code mapping lives in
:func:`~orchestrator.ipcat_acquire.errors.exit_code_for` and is applied by C2's
``do_refresh_ipcat_cache`` dispatch. :attr:`AcquireResult.exit_code` exposes the
contract for convenience, but reading it has no side effect.

**Failure discipline (design §4.2).** Every network exception is caught and
reduced to a redacted category label via
:func:`~orchestrator.ipcat_acquire.errors.classify_error` (class name only —
never a message, traceback, or token). The auth wall (W2/D3) and a
non-stabilisable capped search (W4) are *refusals*, not degradations: they
return a status and write **zero** bytes rather than publish a partial cache.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .client import AUTHWALL_KEY, ERROR_KEY, Transport, open_session
from .errors import (
    AcquireStatus,
    AcquireWriteError,
    classify_error,
    exit_code_for,
)
from .manifest import (
    GPIO_MAP_ID,
    NORD_MANIFEST,
    SWI_UNION_TERMS,
)
from .materialize import write_atomic
from .normalize import build_count_method, count_swi_union, to_canonical
from .provenance import (
    ChipRef,
    FileRecord,
    QueryRecord,
    build_provenance,
    sidecar_payload,
)

# ``swi_search_swi`` returns a capped, relevance-ranked page (the tool's default
# ``length`` is 25). A per-term result at or above the cap may be truncated, so
# the W4 union count treats it as unstable (design §3.1 / R3).
_SWI_SEARCH_CAP = 25

# Default endpoint host recorded in provenance when a caller does not supply one
# (matches the phase-1b live artifact). C2's dispatch passes the real host; this
# default keeps C1 inert and target-agnostic.
_DEFAULT_ENDPOINT_HOST = "qgenie-mcphub.qualcomm.com"

# A fixed, credential-free message for the auth wall — the raw sentinel text is
# never surfaced (design §4.2 redaction).
_AUTH_MSG = "authentication required (interactive auth wall); no bytes written"


@dataclass(frozen=True)
class AcquireResult:
    """Outcome of one :func:`acquire_to_cache` call (no process control).

    ``files`` lists the data-file names that were published (``OK``) or would be
    published (``PLANNED``); it is empty for every refusal. ``message`` is always
    a redacted, credential-free string.
    """

    status: AcquireStatus
    target: str
    chip_alias: str
    files: tuple[str, ...] = ()
    bytes_written: int = 0
    message: str = ""

    @property
    def exit_code(self) -> int:
        """The design §4.2 process exit code for this result's status.

        Reading this is pure — it does **not** call ``sys.exit``. C2's dispatch
        is what turns it into a process exit.
        """
        return exit_code_for(self.status)


# ── small tolerant extractors (network-free) ──────────────────────────────────

_LIST_KEYS = ("rows", "data", "results", "items", "chips", "cores", "gpios", "buses")


def _as_rows(obj: Any) -> list[Any]:
    """Best-effort: pull the list of rows out of a tool response.

    A bare list is returned as-is; a dict is searched for the first well-known
    list-valued key. Anything else yields ``[]`` so a malformed response can
    never silently inflate a W4 count.
    """
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in _LIST_KEYS:
            v = obj.get(key)
            if isinstance(v, list):
                return v
    return []


def _resolve_chip(chips_obj: Any, alias: str) -> ChipRef | None:
    """Resolve ``alias`` → :class:`ChipRef` from a ``chips_list_chips`` response.

    Returns ``None`` (→ ``UNRESOLVED``, no write) when the alias is absent from a
    well-formed listing.
    """
    for row in _as_rows(chips_obj):
        if isinstance(row, dict) and str(row.get("alias", "")) == alias:
            raw_id = row.get("id", 0)
            try:
                cid = int(raw_id)
            except (TypeError, ValueError):
                cid = 0
            name = row.get("canonical_name") or row.get("name") or alias
            return ChipRef(alias=alias, id=cid, canonical_name=str(name))
    return None


def _extract_gpio_map_id(obj: Any) -> Any | None:
    """Pull a ``gpio_map_id`` out of a ``gpio_get_gpio_map`` response, if present."""
    def _from_dict(d: Mapping[str, Any]) -> Any | None:
        for k in ("gpio_map_id", "id", "map_id"):
            if k in d and isinstance(d[k], (int, str)):
                return d[k]
        return None

    if isinstance(obj, dict):
        got = _from_dict(obj)
        if got is not None:
            return got
    for row in _as_rows(obj):
        if isinstance(row, dict):
            got = _from_dict(row)
            if got is not None:
                return got
    return None


def _bind(args: Mapping[str, str], bindings: Mapping[str, str]) -> dict[str, Any]:
    """Bind an entry's argument template against the runtime placeholder map.

    A value that is a known placeholder (``"{chip}"``, ``"{gpio_map_id}"``) is
    substituted; a literal value (e.g. an swi search term) is passed through.
    """
    return {k: bindings.get(v, v) for k, v in args.items()}


def _utc_now_iso() -> str:
    """RFC-3339 UTC timestamp for ``acquired_at`` (the one non-deterministic field)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provenance_bytes(obj: Mapping[str, Any]) -> bytes:
    """Serialise the provenance dict to sorted-key JSON, preserving list order.

    Unlike :func:`normalize.to_canonical` (which sorts *list contents* for
    content identity), provenance keeps ``queries[]`` / ``files[]`` in manifest
    order — that order is part of the contract — while still sorting object keys
    for a stable manifest shape.
    """
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ": "))
    return (text + "\n").encode("utf-8")


def acquire_to_cache(
    *,
    target: str,
    chip_alias: str,
    mechanism: str,
    evidence_ipcat_dir: Path | str,
    dry_run: bool = False,
    transport: Transport | None = None,
    acquired_at: str | None = None,
    endpoint_host: str = _DEFAULT_ENDPOINT_HOST,
    swi_cap: int = _SWI_SEARCH_CAP,
    timeout_s: float = 90.0,
    now: float | None = None,
) -> AcquireResult:
    """Acquire the Nord IPCAT cache into ``evidence_ipcat_dir`` (design §2.2).

    Orchestrates the manifest queries through the (injectable) transport,
    counts the W4 union, normalises each response to canonical bytes, and — on
    full success and unless ``dry_run`` — atomically publishes the cache with a
    provenance manifest. Returns an :class:`AcquireResult`; never calls
    ``sys.exit``.

    Refusals write **zero** bytes and leave any existing cache byte-identical:

    - auth wall (any call) → ``AUTH_REQUIRED``
    - unresolvable chip alias → ``UNRESOLVED``
    - non-stabilisable capped search → ``CAPPED_SEARCH``
    - transport failure on a mandatory query → ``TRANSPORT_ERROR``
    - lock timeout / disk error during publish → ``WRITE_ERROR`` (old cache intact)

    ``transport`` is the test seam: when provided, no socket is opened. When
    ``None``, :func:`client.open_session` constructs the live transport (the sole
    socket-opener) — a path unreachable from any existing flow in C1.
    """
    base_dir = Path(evidence_ipcat_dir)

    def _result(status: AcquireStatus, msg: str) -> AcquireResult:
        return AcquireResult(status=status, target=target, chip_alias=chip_alias, message=msg)

    session = open_session(mechanism, transport=transport, timeout_s=timeout_s)
    try:
        bindings: dict[str, str] = {"{chip}": chip_alias}
        responses: dict[str, Any] = {}
        per_term_rows: dict[str, list[Any]] = {}

        for entry in NORD_MANIFEST:
            call_args = _bind(entry.args, bindings)
            try:
                raw = session.call(entry.tool, call_args)
            except Exception as exc:  # noqa: BLE001 — reduced to a redacted label
                if entry.mandatory:
                    return _result(AcquireStatus.TRANSPORT_ERROR, classify_error(exc))
                continue  # optional tool: absence never blocks (design §0/Q2)

            if isinstance(raw, dict) and AUTHWALL_KEY in raw:
                # The auth wall is backend-wide, not tool-specific → global refusal.
                return _result(AcquireStatus.AUTH_REQUIRED, _AUTH_MSG)
            if isinstance(raw, dict) and ERROR_KEY in raw:
                if entry.mandatory:
                    return _result(AcquireStatus.TRANSPORT_ERROR, "protocol_error")
                continue

            responses[entry.query_id] = raw
            if entry.tool == "swi_search_swi":
                per_term_rows[str(entry.args.get("q", entry.query_id))] = _as_rows(raw)
            if entry.tool == "gpio_get_gpio_map":
                gid = _extract_gpio_map_id(raw)
                if gid is not None:
                    bindings[GPIO_MAP_ID] = str(gid)
    finally:
        session.close()

    # Chip identity (from chips_list_chips) — a refusal if the alias is absent.
    chip_ref = _resolve_chip(responses.get("q1"), chip_alias)
    if chip_ref is None:
        return _result(
            AcquireStatus.UNRESOLVED,
            f"chip alias not found in catalog: {chip_alias!r}",
        )

    # W4 union count — refuse (no write) rather than emit an undercount.
    _count, stable = count_swi_union(per_term_rows, cap=swi_cap)
    if not stable:
        return _result(
            AcquireStatus.CAPPED_SEARCH,
            "swi_search_swi not stabilisable below cap; refusing partial count",
        )
    count_method = build_count_method(SWI_UNION_TERMS, stable=True, below_cap=True)

    # Normalise each collected response → canonical bytes + digest, in manifest
    # order (so provenance queries[]/files[] mirror the contract order).
    data_files: dict[str, bytes] = {}
    sidecars: dict[str, bytes] = {}
    query_records: list[QueryRecord] = []
    file_records: list[FileRecord] = []
    for entry in NORD_MANIFEST:
        if entry.query_id not in responses:
            continue  # a skipped optional tool
        canon = to_canonical(responses[entry.query_id])
        sha = hashlib.sha256(canon).hexdigest()
        data_files[entry.result_file] = canon
        sidecars[entry.result_file + ".sha256"] = sidecar_payload(sha)
        query_records.append(
            QueryRecord(
                tool=entry.tool,
                args=_bind(entry.args, bindings),
                query_id=entry.query_id,
                result_file=entry.result_file,
                sha256=sha,
                count_method=count_method if entry.tool == "swi_search_swi" else None,
            )
        )
        file_records.append(
            FileRecord(path=entry.result_file, sha256=sha, bytes=len(canon))
        )

    # --dry-run: resolve params + report intended paths, write ZERO bytes.
    if dry_run:
        return AcquireResult(
            status=AcquireStatus.PLANNED,
            target=target,
            chip_alias=chip_alias,
            files=tuple(data_files),
            bytes_written=0,
            message="dry-run: no bytes written",
        )

    prov = build_provenance(
        target=target,
        chip=chip_ref,
        acquired_at=acquired_at if acquired_at is not None else _utc_now_iso(),
        mechanism=mechanism,
        endpoint_host=endpoint_host,
        queries=query_records,
        files=file_records,
    )
    prov_bytes = _provenance_bytes(prov)

    try:
        write_atomic(base_dir, data_files, sidecars, prov_bytes, now=now)
    except AcquireWriteError as exc:
        # Old cache is byte-identical (design §4.2/§4.3).
        return _result(AcquireStatus.WRITE_ERROR, classify_error(exc))

    total = (
        sum(len(b) for b in data_files.values())
        + sum(len(b) for b in sidecars.values())
        + len(prov_bytes)
    )
    return AcquireResult(
        status=AcquireStatus.OK,
        target=target,
        chip_alias=chip_alias,
        files=tuple(data_files),
        bytes_written=total,
        message="cache published",
    )


__all__ = [
    "acquire_to_cache",
    "AcquireResult",
    "AcquireStatus",
]
