"""Phase-3A WP-E — Fact Registry SourceRef tagged union.

Seven variants — one per authoritative source class — plus a strict
:func:`parse` dispatcher. Every :class:`FactValue` carries exactly one
:class:`SourceRef`; the cross-check between ``authority`` and
``source_ref.kind`` is validated in :class:`FactValue.__post_init__`
(see :mod:`audio_bu_skill.orchestrator.fact_registry.models`).

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §7):

- The ``kind`` field is the discriminator. It is a :data:`typing.Literal`
  narrowed to a single string per variant; construction fails if the caller
  passes any other value.
- :class:`IPCATCachedRef.sha256` MUST be 64 hex chars.
- :class:`KernelRef.commit` MUST be 40 hex chars, ``line_start <= line_end``,
  and the ``kernel_ref_kind`` discriminator is required (C-3, 2026-07-20).
- :class:`ManualRef.ticket_url` — if non-None — is validated via
  :func:`urllib.parse.urlparse` requiring both ``scheme`` and ``netloc``
  (OQ-4, 2026-07-20). No regex tracker-lock.
- :func:`parse` accepts a mapping with a ``kind`` discriminator and returns
  the corresponding frozen dataclass. Any unknown ``kind`` raises
  :class:`ValueError` — never a soft-fail into ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Union
from urllib.parse import urlparse

# ── shared validators ─────────────────────────────────────────────────────

_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdefABCDEF")


def _is_hex_of_length(s: str, n: int) -> bool:
    """True iff ``s`` is exactly ``n`` characters, all hex."""
    return isinstance(s, str) and len(s) == n and all(c in _HEX_CHARS for c in s)


def _require_utc(name: str, dt: datetime) -> None:
    """Raise if ``dt`` is not a tz-aware UTC datetime."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name}: expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValueError(f"{name}: datetime must be tz-aware (got naive)")
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"{name}: datetime must be UTC (offset != 0)")


def _require_non_empty_str(name: str, s: Any) -> None:
    if not isinstance(s, str) or not s:
        raise ValueError(f"{name}: expected non-empty str, got {s!r}")


# ── seven variants (§7) ───────────────────────────────────────────────────

@dataclass(frozen=True)
class IPCATLiveRef:
    """Live MCP round-trip against the IP Catalog. Reserved for future work
    (G-3A.1); Phase-3A does not acquire live facts but the variant exists so
    the schema is forward-compatible."""

    kind: Literal["ipcat_live"]
    tool: str
    args: Mapping[str, Any]
    query_id: str
    ts: datetime

    def __post_init__(self) -> None:
        if self.kind != "ipcat_live":
            raise ValueError(
                f"IPCATLiveRef.kind: expected 'ipcat_live', got {self.kind!r}"
            )
        _require_non_empty_str("IPCATLiveRef.tool", self.tool)
        _require_non_empty_str("IPCATLiveRef.query_id", self.query_id)
        if not isinstance(self.args, Mapping):
            raise TypeError(
                "IPCATLiveRef.args: expected Mapping[str, Any], "
                f"got {type(self.args).__name__}"
            )
        _require_utc("IPCATLiveRef.ts", self.ts)


@dataclass(frozen=True)
class IPCATCachedRef:
    """Cached IPCAT evidence file under ``evidence/ipcat/``."""

    kind: Literal["ipcat_cached"]
    path: str
    sha256: str
    line: int | None = None

    def __post_init__(self) -> None:
        if self.kind != "ipcat_cached":
            raise ValueError(
                f"IPCATCachedRef.kind: expected 'ipcat_cached', got {self.kind!r}"
            )
        _require_non_empty_str("IPCATCachedRef.path", self.path)
        if not _is_hex_of_length(self.sha256, 64):
            raise ValueError(
                "IPCATCachedRef.sha256: expected 64 hex characters, "
                f"got {self.sha256!r}"
            )
        if self.line is not None and (not isinstance(self.line, int) or self.line < 0):
            raise ValueError(
                f"IPCATCachedRef.line: expected non-negative int or None, got {self.line!r}"
            )


@dataclass(frozen=True)
class KernelRef:
    """DTS or bindings-header reference into a pinned kernel tree.

    ``kernel_ref_kind`` (C-3, 2026-07-20) is the required discriminator that
    lets WP-F pick the right freshness policy without re-deriving DTS-vs-bindings
    from ``path``.
    """

    kind: Literal["kernel"]
    kernel_ref_kind: Literal["dts", "bindings"]
    repo: str
    commit: str
    path: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        if self.kind != "kernel":
            raise ValueError(
                f"KernelRef.kind: expected 'kernel', got {self.kind!r}"
            )
        if self.kernel_ref_kind not in ("dts", "bindings"):
            raise ValueError(
                "KernelRef.kernel_ref_kind: expected 'dts' or 'bindings', "
                f"got {self.kernel_ref_kind!r}"
            )
        _require_non_empty_str("KernelRef.repo", self.repo)
        if not _is_hex_of_length(self.commit, 40):
            raise ValueError(
                "KernelRef.commit: expected 40 hex characters, "
                f"got {self.commit!r}"
            )
        _require_non_empty_str("KernelRef.path", self.path)
        if not isinstance(self.line_start, int) or self.line_start < 1:
            raise ValueError(
                f"KernelRef.line_start: expected positive int, got {self.line_start!r}"
            )
        if not isinstance(self.line_end, int) or self.line_end < self.line_start:
            raise ValueError(
                "KernelRef.line_end: expected int >= line_start "
                f"({self.line_start}), got {self.line_end!r}"
            )


@dataclass(frozen=True)
class SchematicRef:
    """Reference into a schematic PDF (doc_id + revision + page)."""

    kind: Literal["schematic"]
    doc_id: str
    revision: str
    page: int
    section: str | None = None

    def __post_init__(self) -> None:
        if self.kind != "schematic":
            raise ValueError(
                f"SchematicRef.kind: expected 'schematic', got {self.kind!r}"
            )
        _require_non_empty_str("SchematicRef.doc_id", self.doc_id)
        _require_non_empty_str("SchematicRef.revision", self.revision)
        if not isinstance(self.page, int) or self.page < 1:
            raise ValueError(
                f"SchematicRef.page: expected positive int, got {self.page!r}"
            )
        if self.section is not None and (
            not isinstance(self.section, str) or not self.section
        ):
            raise ValueError(
                f"SchematicRef.section: expected non-empty str or None, got {self.section!r}"
            )


@dataclass(frozen=True)
class ACDBRef:
    """Reference into an exported ACDB tarball / directory."""

    kind: Literal["acdb"]
    export_id: str
    path: str
    key: str

    def __post_init__(self) -> None:
        if self.kind != "acdb":
            raise ValueError(
                f"ACDBRef.kind: expected 'acdb', got {self.kind!r}"
            )
        _require_non_empty_str("ACDBRef.export_id", self.export_id)
        _require_non_empty_str("ACDBRef.path", self.path)
        _require_non_empty_str("ACDBRef.key", self.key)


@dataclass(frozen=True)
class ManualRef:
    """Human-provided source of truth. ``ticket_url``/``doc_ref`` optionality
    is the substrate that :meth:`ReviewRecord.has_evidence` reads via
    :class:`FactValue`'s manual-fact confidence cap (§8).

    ``ticket_url`` — if non-None — MUST parse with both ``scheme`` and
    ``netloc`` populated. No regex tracker-lock (OQ-4, 2026-07-20).
    """

    kind: Literal["manual"]
    note: str
    ticket_url: str | None = None
    doc_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind != "manual":
            raise ValueError(
                f"ManualRef.kind: expected 'manual', got {self.kind!r}"
            )
        _require_non_empty_str("ManualRef.note", self.note)
        if self.ticket_url is not None:
            if not isinstance(self.ticket_url, str) or not self.ticket_url:
                raise ValueError(
                    f"ManualRef.ticket_url: expected non-empty str or None, got {self.ticket_url!r}"
                )
            parsed = urlparse(self.ticket_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(
                    "ManualRef.ticket_url: URL must have both scheme and netloc "
                    f"(got {self.ticket_url!r})"
                )
        if self.doc_ref is not None and (
            not isinstance(self.doc_ref, str) or not self.doc_ref
        ):
            raise ValueError(
                f"ManualRef.doc_ref: expected non-empty str or None, got {self.doc_ref!r}"
            )


@dataclass(frozen=True)
class InferredRef:
    """Fact synthesised by a named inference rule from other facts. Gives
    ``AuthorityClass.INFERRED`` a first-class SourceRef; closes the §4.3 gap
    that would otherwise let INFERRED facts slip in without one."""

    kind: Literal["inferred"]
    inference_rule: str
    inputs: Mapping[str, str]
    note: str

    def __post_init__(self) -> None:
        if self.kind != "inferred":
            raise ValueError(
                f"InferredRef.kind: expected 'inferred', got {self.kind!r}"
            )
        _require_non_empty_str("InferredRef.inference_rule", self.inference_rule)
        _require_non_empty_str("InferredRef.note", self.note)
        if not isinstance(self.inputs, Mapping):
            raise TypeError(
                "InferredRef.inputs: expected Mapping[str, str], "
                f"got {type(self.inputs).__name__}"
            )
        for k, v in self.inputs.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError(
                    "InferredRef.inputs: all keys and values must be str "
                    f"(offender: {k!r} -> {v!r})"
                )


# ── union alias + dispatcher (§7) ─────────────────────────────────────────

SourceRef = Union[
    IPCATLiveRef,
    IPCATCachedRef,
    KernelRef,
    SchematicRef,
    ACDBRef,
    ManualRef,
    InferredRef,
]


_VARIANT_BY_KIND: dict[str, type] = {
    "ipcat_live":   IPCATLiveRef,
    "ipcat_cached": IPCATCachedRef,
    "kernel":       KernelRef,
    "schematic":    SchematicRef,
    "acdb":         ACDBRef,
    "manual":       ManualRef,
    "inferred":     InferredRef,
}


def parse(raw: Mapping[str, Any]) -> SourceRef:
    """Dispatch a JSON-decoded mapping to the right :class:`SourceRef` variant.

    Args:
        raw: mapping with a ``kind`` discriminator plus the variant's fields.

    Returns:
        The corresponding frozen dataclass instance.

    Raises:
        ValueError: if ``raw`` is not a mapping, has no ``kind``, or its
            ``kind`` is not one of the seven known variants.
        TypeError: if ``raw`` supplies a field of the wrong type or extra
            unknown fields (delegated to the dataclass ``__init__``).
    """
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"source_refs.parse: expected Mapping, got {type(raw).__name__}"
        )
    kind = raw.get("kind")
    variant = _VARIANT_BY_KIND.get(kind)
    if variant is None:
        raise ValueError(f"source_refs.parse: unknown SourceRef.kind: {kind!r}")
    kwargs = {k: v for k, v in raw.items() if k != "kind"}
    return variant(kind=kind, **kwargs)


__all__ = [
    "ACDBRef",
    "IPCATCachedRef",
    "IPCATLiveRef",
    "InferredRef",
    "KernelRef",
    "ManualRef",
    "SchematicRef",
    "SourceRef",
    "parse",
]
