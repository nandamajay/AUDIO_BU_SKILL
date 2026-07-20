"""WP-IPCAT-A C1 — provenance.json (v2.0.0) builder + per-file sha256 sidecars.

Inert and network-free. Given already-normalized data files and their digests,
this module builds the ``provenance.json`` manifest (design §3.1) and the
per-file ``.sha256`` sidecar payloads. It performs **no** disk I/O itself —
:mod:`.materialize` owns writing; this module owns *shape*. That split keeps the
schema testable (T-IA-08) without a filesystem.

Schema (design §3.1, ``schema_version`` ``"2.0.0"``):

    { schema_version, target, chip{alias,id,canonical_name}, acquired_at,
      mechanism, endpoint_host,
      boundary{auth_json_read, credentials_json_read, tls_verify, readonly_only},
      queries[]{tool, args, query_id, result_file, sha256, count_method},
      files[]{path, sha256, bytes} }

``acquired_at`` is the single non-deterministic field and appears **only** here,
never in a data file — so a re-run over an unchanged catalog changes only
``provenance.json`` and leaves every data file (and thus every
``IPCATCachedRef.sha256``) byte-identical (design §3.2).

Every ``files[].sha256`` is a 64-hex digest that must round-trip into an
:class:`IPCATCachedRef` constructor unchanged — this module never imports the
registry (T-IA-12), but the digests it emits are format-compatible so the later
(out-of-scope for C1) registry linkage is a lookup, not a re-hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "2.0.0"

# The boundary block is a compile-time constant: these are the invariants the
# acquisition path guarantees and the phase-1b artifact proved. They are never
# derived from runtime state — they are the safety contract itself.
BOUNDARY: dict[str, bool] = {
    "auth_json_read": False,
    "credentials_json_read": False,
    "tls_verify": True,
    "readonly_only": True,
}

_HEX_CHARS = frozenset("0123456789abcdef")


def _is_hex64(s: str) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in _HEX_CHARS for c in s)


@dataclass(frozen=True)
class QueryRecord:
    """One ``queries[]`` entry: a tool call and where its result landed."""

    tool: str
    args: Mapping[str, Any]
    query_id: str
    result_file: str
    sha256: str
    count_method: str | None = None

    def __post_init__(self) -> None:
        if not _is_hex64(self.sha256):
            raise ValueError(
                f"QueryRecord.sha256 must be 64 lowercase hex, got {self.sha256!r}"
            )


@dataclass(frozen=True)
class FileRecord:
    """One ``files[]`` entry: a published data file's identity."""

    path: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        if not _is_hex64(self.sha256):
            raise ValueError(
                f"FileRecord.sha256 must be 64 lowercase hex, got {self.sha256!r}"
            )
        if not isinstance(self.bytes, int) or self.bytes < 0:
            raise ValueError(
                f"FileRecord.bytes must be a non-negative int, got {self.bytes!r}"
            )


@dataclass(frozen=True)
class ChipRef:
    """The resolved chip identity block."""

    alias: str
    id: int
    canonical_name: str


def build_provenance(
    *,
    target: str,
    chip: ChipRef,
    acquired_at: str,
    mechanism: str,
    endpoint_host: str,
    queries: Sequence[QueryRecord],
    files: Sequence[FileRecord],
) -> dict[str, Any]:
    """Assemble the ``provenance.json`` dict (design §3.1 schema, v2.0.0).

    ``acquired_at`` is supplied by the caller (it is the one non-deterministic
    field) and must be an RFC-3339 / ISO-8601 UTC string, e.g.
    ``"2026-07-21T09:14:02Z"``. This function does not read the clock — keeping
    it pure means the schema is testable with a fixed timestamp (T-IA-08).
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "target": target,
        "chip": {
            "alias": chip.alias,
            "id": chip.id,
            "canonical_name": chip.canonical_name,
        },
        "acquired_at": acquired_at,
        "mechanism": mechanism,
        "endpoint_host": endpoint_host,
        "boundary": dict(BOUNDARY),
        "queries": [
            {
                "tool": q.tool,
                "args": dict(q.args),
                "query_id": q.query_id,
                "result_file": q.result_file,
                "sha256": q.sha256,
                "count_method": q.count_method,
            }
            for q in queries
        ],
        "files": [
            {"path": f.path, "sha256": f.sha256, "bytes": f.bytes}
            for f in files
        ],
    }


def sidecar_payload(sha_hex: str) -> bytes:
    """Return the ``.sha256`` sidecar bytes for a single data file.

    WP-IPCAT-A uses a **per-file** sidecar (one ``.sha256`` beside each data
    file), a simpler shape than WP-E's ``<target>.registry.hash``: just the
    64-hex digest and a trailing newline, matching the ``IPCATCachedRef.sha256``
    field exactly.
    """
    if not _is_hex64(sha_hex):
        raise ValueError(
            f"sidecar_payload: sha_hex must be 64 lowercase hex, got {sha_hex!r}"
        )
    return (sha_hex + "\n").encode("ascii")


__all__ = [
    "SCHEMA_VERSION",
    "BOUNDARY",
    "QueryRecord",
    "FileRecord",
    "ChipRef",
    "build_provenance",
    "sidecar_payload",
]
