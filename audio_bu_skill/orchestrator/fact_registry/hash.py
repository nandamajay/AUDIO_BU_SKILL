"""Phase-3A WP-E — Fact Registry SHA-256 sidecar helpers.

The registry stores a companion ``<target>.registry.hash`` sidecar file that
carries the sha256 of the accompanying JSONL. Per §10 of the design, the
sidecar is a single line of the form::

    sha256:<64hex>  <target>.json

with **two ASCII spaces** between the hex digest and the filename (the
`sha256sum -c` convention). A load-time mismatch surfaces as
:class:`RegistryStatus.HASH_MISMATCH` — never a raise.

The writer flow (§9) lands the sidecar **before** the JSONL rename (C-1);
that inversion is what makes the reader's 50 ms retry (§9 reader flow)
self-healing.

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §9, §10):

- :func:`sha256_of_file` streams the file in fixed-size chunks so a
  large registry does not have to be materialised in memory.
- :func:`sidecar_line` builds the canonical sidecar payload and is the
  single writer of that format anywhere in the package.
- :func:`parse_sidecar` is the strict reader: it accepts exactly the shape
  above, rejects any deviation with :class:`ValueError`, and refuses a
  sidecar whose trailing filename does not match the expected target.
- Neither reader nor writer raises for the top-level "sidecar disagrees with
  JSONL bytes" condition — that is a :class:`RegistryStatus.HASH_MISMATCH`
  policy in :mod:`.store`, not an exception from this module.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


# ── constants ────────────────────────────────────────────────────────────────

_CHUNK_SIZE: int = 1 << 20  # 1 MiB — plenty for a JSONL registry
_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")


# ── hashing ──────────────────────────────────────────────────────────────────

def sha256_of_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(
            f"sha256_of_bytes: expected bytes-like, got {type(data).__name__}"
        )
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_of_file(path: Path) -> str:
    """Stream-hash a file on disk and return the lowercase hex digest.

    Streams the file in 1 MiB chunks. Never materialises the whole file in
    memory.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        IsADirectoryError: if ``path`` refers to a directory.
        PermissionError: if ``path`` is not readable.
    """
    if not isinstance(path, Path):
        raise TypeError(f"sha256_of_file: expected Path, got {type(path).__name__}")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── sidecar format ───────────────────────────────────────────────────────────

def _is_hex64(s: str) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in _HEX_CHARS for c in s)


def sidecar_line(target: str, sha_hex: str) -> str:
    """Return the canonical sidecar payload for ``target`` with digest ``sha_hex``.

    The output includes a trailing newline (POSIX convention) so a writer
    can write the returned string verbatim.

    Raises:
        ValueError: if ``target`` looks unsafe (empty, contains a slash or
            backslash, starts with ``.``) or if ``sha_hex`` is not 64
            lowercase hex characters.
    """
    if not isinstance(target, str) or not target:
        raise ValueError(
            f"sidecar_line: target must be a non-empty str, got {target!r}"
        )
    if "/" in target or "\\" in target or target.startswith("."):
        raise ValueError(
            f"sidecar_line: {target!r} is not a valid target identifier"
        )
    if not _is_hex64(sha_hex):
        raise ValueError(
            "sidecar_line: sha_hex must be 64 lowercase hex characters, "
            f"got {sha_hex!r}"
        )
    return f"sha256:{sha_hex}  {target}.json\n"


def parse_sidecar(text: str, target: str) -> str:
    """Strictly parse a sidecar file's text and return the hex digest.

    The accepted shape is exactly the string produced by :func:`sidecar_line`:
    ``sha256:<64hex>  <target>.json`` with two ASCII spaces, optionally
    followed by a single trailing ``\\n``. No other whitespace, no comments,
    no additional lines.

    Args:
        text: full contents of the sidecar file.
        target: expected target identifier (the sidecar's trailing filename
            must be ``<target>.json``).

    Returns:
        The 64-character lowercase hex SHA-256 as written in the sidecar.

    Raises:
        ValueError: on any deviation from the canonical shape or a
            filename mismatch against ``target``.
    """
    if not isinstance(text, str):
        raise ValueError(
            f"parse_sidecar: expected str contents, got {type(text).__name__}"
        )
    if not isinstance(target, str) or not target:
        raise ValueError(
            f"parse_sidecar: target must be a non-empty str, got {target!r}"
        )

    # Strip at most one trailing newline; anything else is a shape error.
    if text.endswith("\n"):
        body = text[:-1]
    else:
        body = text
    if "\n" in body:
        raise ValueError(
            "parse_sidecar: sidecar must be a single line (found embedded newline)"
        )

    prefix = "sha256:"
    if not body.startswith(prefix):
        raise ValueError(
            f"parse_sidecar: sidecar must start with 'sha256:' (got {body[:16]!r})"
        )
    rest = body[len(prefix):]

    # Split on the exact two-space separator between digest and filename.
    sep = "  "
    idx = rest.find(sep)
    if idx < 0:
        raise ValueError(
            "parse_sidecar: sidecar must contain two ASCII spaces between "
            "digest and filename"
        )
    digest = rest[:idx]
    filename = rest[idx + len(sep):]

    if not _is_hex64(digest):
        raise ValueError(
            "parse_sidecar: digest must be 64 lowercase hex characters, "
            f"got {digest!r}"
        )
    expected_filename = f"{target}.json"
    if filename != expected_filename:
        raise ValueError(
            f"parse_sidecar: sidecar filename {filename!r} does not match "
            f"expected {expected_filename!r}"
        )
    return digest


__all__ = [
    "parse_sidecar",
    "sha256_of_bytes",
    "sha256_of_file",
    "sidecar_line",
]
