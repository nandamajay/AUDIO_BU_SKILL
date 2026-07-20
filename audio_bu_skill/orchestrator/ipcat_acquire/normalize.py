"""WP-IPCAT-A C1 — deterministic normalization + W4 union counting.

Inert and network-free: this module transforms already-fetched, in-memory MCP
responses into canonical bytes and computes trustworthy counts. It opens no
socket and reads no file.

Two responsibilities (design §3.2 determinism rule, §3.1 ``count_method``):

1. :func:`to_canonical` — serialise a Python object to **canonical JSON bytes**:
   ``sort_keys=True``, ``ensure_ascii=False``, ``separators=(",", ": ")``, a
   fixed float repr, and a trailing newline. An unchanged catalog therefore
   re-materialises byte-for-byte, so the sha256 of a data file is a true content
   identity (the same guarantee WP-E gives its JSONL). ``acquired_at`` is the
   only non-deterministic field and it lives *only* in ``provenance.json`` — it
   never passes through here.

2. :func:`count_swi_union` / :func:`build_count_method` — the W4 discipline for
   ``swi_search_swi``. That tool is capped and relevance-ranked and its
   ``total_hits`` is unreliable, so a count is trusted only when the **union**
   of the search terms yields a set of identifiers that is (a) *set-stable*
   across the per-term result lists (the union equals what each term's rows
   contribute, with no term pushing the total past the cap) and (b) *below the
   cap*. When the union cannot be shown below-cap and stable, the count is
   refused (the caller maps that to :class:`AcquireStatus.CAPPED_SEARCH` and
   writes nothing).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence


# Matches the WP-E / phase-1b canonical form (design §3.2).
_JSON_KWARGS = dict(
    sort_keys=True,
    ensure_ascii=False,
    separators=(",", ": "),
)


def _stabilise(obj: Any) -> Any:
    """Recursively coerce ``obj`` into a canonical, comparison-stable shape.

    - ``dict`` → dict with recursively stabilised values (key order handled by
      ``sort_keys`` at dump time).
    - ``list`` / ``tuple`` → list of stabilised items, sorted by their canonical
      JSON encoding so an unordered catalog listing re-materialises identically.
      Sorting by the canonical encoding (not the raw value) keeps heterogeneous
      lists sortable without raising on mixed types.
    - scalars → returned unchanged; ``float`` relies on Python's repr-round-trip
      which ``json`` already emits deterministically.
    """
    if isinstance(obj, dict):
        return {k: _stabilise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        items = [_stabilise(v) for v in obj]
        items.sort(key=lambda v: json.dumps(v, **_JSON_KWARGS))
        return items
    return obj


def to_canonical(obj: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes for ``obj`` (with trailing newline).

    Deterministic: the same logical content always yields byte-identical output,
    regardless of input key/list order. This is the byte stream whose sha256
    becomes the file's content identity and the ``IPCATCachedRef.sha256``.
    """
    text = json.dumps(_stabilise(obj), **_JSON_KWARGS)
    return (text + "\n").encode("utf-8")


def _ids_from_rows(rows: Iterable[Any], id_key: str) -> set[str]:
    """Extract the set of identifier strings from a tool's result rows.

    Rows are expected to be dicts carrying ``id_key``; rows lacking it are
    ignored (defensive — a malformed row must not silently inflate a count).
    """
    ids: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and id_key in row:
            ids.add(str(row[id_key]))
    return ids


def count_swi_union(
    per_term_rows: dict[str, Sequence[Any]],
    *,
    cap: int,
    id_key: str = "name",
) -> tuple[int | None, bool]:
    """Count distinct SWI hits across the union of search terms (W4).

    ``per_term_rows`` maps each search term to its returned rows. Returns
    ``(count, stable)``:

    - ``stable`` is True iff every per-term result is strictly below ``cap``
      (so no term was truncated) — the precondition under which the union is a
      trustworthy total.
    - ``count`` is the size of the union of identifiers when ``stable``; it is
      ``None`` when not stable, signalling the caller to refuse the write with
      :class:`AcquireStatus.CAPPED_SEARCH`.

    A term at or above ``cap`` means its list was (potentially) truncated by the
    server, so the union under-counts and cannot be trusted — hence unstable.
    """
    stable = True
    union: set[str] = set()
    for _term, rows in per_term_rows.items():
        rows = list(rows)
        if len(rows) >= cap:
            stable = False
        union |= _ids_from_rows(rows, id_key)
    if not stable:
        return None, False
    return len(union), True


def build_count_method(
    terms: Sequence[str],
    *,
    stable: bool,
    below_cap: bool,
) -> str:
    """Build the ``count_method`` provenance string (design §3.1).

    Example: ``"union{SOUNDWIRE_MASTER,SWR_MSTR,SWR}; stable; below_cap=true"``.
    The string is human-auditable proof that the count was a union-of-terms
    computation, never a bare ``len()`` or an untrusted ``total_hits``.
    """
    term_list = ",".join(terms)
    stable_tok = "stable" if stable else "unstable"
    return f"union{{{term_list}}}; {stable_tok}; below_cap={str(below_cap).lower()}"


__all__ = [
    "to_canonical",
    "count_swi_union",
    "build_count_method",
]
