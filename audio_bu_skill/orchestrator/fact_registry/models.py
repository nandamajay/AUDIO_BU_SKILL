"""Phase-3A WP-E — Fact Registry core value types.

Three frozen dataclasses form the type-level identity of a fact:

- :class:`FactKey`     — the identity by which a fact is looked up. Domain-
                         qualified family + subject + attribute triple.
- :class:`FactProvenance` — a single append-only history entry. Carries the
                         value it saw at capture time plus authority /
                         source_ref / captured_at / confidence / note / review /
                         is_revocation.
- :class:`FactValue`   — the top-of-chain descriptor + the full immutable
                         provenance chain. This is what :meth:`Registry.get`
                         returns (unless the chain top is a revocation).

Design contract (WP_E_FACT_REGISTRY_DESIGN.md §4, §5, §6):

FactKey (§4):
  - ``family`` matches ``^[A-Za-z][A-Za-z0-9_]*$``
  - ``attribute`` matches ``^[a-z][a-z0-9_]*$``
  - ``subject`` non-empty
  - ``domain`` is a WP-D :class:`Domain` instance
  - ``as_string()`` / ``parse()`` are round-trip inverses using the grammar
    ``<domain>.<family>/<subject>/<attribute>``.

FactProvenance (§6):
  - JSON-serialisable ``value``
  - tz-aware UTC ``captured_at``
  - ``confidence`` ∈ [0.0, 1.0]
  - Authority ↔ SourceRef.kind cross-check (§7 table) — INCLUDING the
    KERNEL_DTS / KERNEL_BINDINGS discrimination on ``kernel_ref_kind``.
  - ``authority_class == INFERRED`` implies ``authority == Authority.INFERRED``.
  - ``authority_class == MANUAL`` implies ``authority == Authority.MANUAL``.
  - If ``is_revocation is True``:
    * ``authority_class`` MUST be MANUAL,
    * ``review`` MUST be non-null with ``decision == REJECT``,
    * ``review.supersedes_provenance_index`` MUST be non-null.

FactValue (§5, 8 invariants):
  1. JSON-serialisable ``value``
  2. tz-aware UTC ``captured_at``
  3. ``confidence`` ∈ [0.0, 1.0]
  4. ``authority_class == MANUAL`` iff ``review is not None``
  5. ``authority_class == INFERRED`` implies ``authority == Authority.INFERRED``
  6. ``authority_class == MANUAL`` implies ``authority == Authority.MANUAL``
  7. ``provenance_chain`` non-empty; last-of-chain matches top-of-descriptor
     for non-revocation entries. If chain top is a revocation entry, the
     descriptor fields describe the LAST non-revocation entry in the chain.
  8. Manual-fact confidence cap: ``review is not None and not review.has_evidence``
     → clamp ``confidence`` to ``min(confidence, 0.4)`` at construction.

Imports are strictly from WP-D public :mod:`audio_bu_skill.fact_requirements`
(the :mod:`.schema` module is NOT imported directly, per §1.8).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, Union

# ── WP-D types (public re-export path per §1.8) ──────────────────────────────
from audio_bu_skill.fact_requirements import (
    Authority,
    AuthorityClass,
    Domain,
)

# ── WP-E siblings ────────────────────────────────────────────────────────────
from audio_bu_skill.orchestrator.fact_registry.review import (
    ReviewDecision,
    ReviewRecord,
)
from audio_bu_skill.orchestrator.fact_registry.source_refs import (
    ACDBRef,
    IPCATCachedRef,
    IPCATLiveRef,
    InferredRef,
    KernelRef,
    ManualRef,
    SchematicRef,
    SourceRef,
)


# ── JSON scalar / value alias (§5) ────────────────────────────────────────────

JsonScalar = Union[None, bool, int, float, str]
"""JSON scalar leaf values. :class:`FactValue.value` may be a scalar or a
JSON-compatible container (Mapping / Sequence) of the same."""


# ── FactKey grammar constants (§4) ────────────────────────────────────────────

_FAMILY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ATTRIBUTE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_utc(name: str, dt: datetime) -> None:
    """Raise if ``dt`` is not a tz-aware UTC datetime."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name}: expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        raise ValueError(f"{name}: datetime must be tz-aware (got naive)")
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"{name}: datetime must be UTC (offset != 0)")


def _require_json_serialisable(name: str, value: Any) -> None:
    """Round-trip ``value`` through :mod:`json` with ``allow_nan=False``.

    Rejects NaN / Inf as those are not permitted by RFC 8259. Anything that
    round-trips is a legal JSON value tree.
    """
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}: value must be JSON-serialisable ({exc})"
        ) from exc


# ── FactKey (§4) ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FactKey:
    """Type-level identity for a fact.

    FactKey does NOT carry ``target``, ``board``, or ``chip`` — those are
    captured by the file boundary (``<target>.json``) or by the fact's
    :class:`SourceRef`. Frozen so it can serve as a dict key inside
    :class:`Registry`.
    """

    domain: Domain
    family: str
    subject: str
    attribute: str

    def __post_init__(self) -> None:
        if not isinstance(self.domain, Domain):
            raise TypeError(
                "FactKey.domain: expected Domain enum, "
                f"got {type(self.domain).__name__}"
            )
        if not isinstance(self.family, str) or not _FAMILY_RE.match(self.family):
            raise ValueError(
                "FactKey.family: expected match of "
                f"^[A-Za-z][A-Za-z0-9_]*$, got {self.family!r}"
            )
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError(
                f"FactKey.subject: expected non-empty str, got {self.subject!r}"
            )
        if not isinstance(self.attribute, str) or not _ATTRIBUTE_RE.match(self.attribute):
            raise ValueError(
                "FactKey.attribute: expected match of "
                f"^[a-z][a-z0-9_]*$, got {self.attribute!r}"
            )

    @property
    def qualified_family(self) -> str:
        """Dot-joined ``<domain>.<family>``."""
        return f"{self.domain.value}.{self.family}"

    def as_string(self) -> str:
        """Canonical stringification: ``<domain>.<family>/<subject>/<attribute>``.

        Round-trip inverse of :meth:`parse`.
        """
        return f"{self.qualified_family}/{self.subject}/{self.attribute}"

    @classmethod
    def parse(cls, s: str) -> "FactKey":
        """Inverse of :meth:`as_string`.

        Grammar: ``<domain>.<family>/<subject>/<attribute>``, split on ``/`` from
        the right to allow subjects/attributes free of ``/`` while tolerating
        ``.`` in the ``<domain>.<family>`` head (though ``family`` itself is
        alnum + underscore, the ``.`` is the domain-family delimiter).

        Raises:
            ValueError: on any grammar violation.
        """
        if not isinstance(s, str) or not s:
            raise ValueError(f"FactKey.parse: expected non-empty str, got {s!r}")
        parts = s.split("/")
        if len(parts) != 3:
            raise ValueError(
                f"FactKey.parse: expected 3 '/'-separated fields, got {s!r}"
            )
        head, subject, attribute = parts
        if "." not in head:
            raise ValueError(
                f"FactKey.parse: head must contain '<domain>.<family>', got {head!r}"
            )
        domain_str, family = head.split(".", 1)
        try:
            domain = Domain(domain_str)
        except ValueError as exc:
            raise ValueError(
                f"FactKey.parse: unknown domain {domain_str!r}"
            ) from exc
        return cls(domain=domain, family=family, subject=subject, attribute=attribute)


# ── Authority ↔ SourceRef.kind cross-check (§7 table) ────────────────────────

def _validate_authority_source_ref(
    where: str,
    authority: Authority,
    source_ref: SourceRef,
) -> None:
    """Enforce the §7 cross-check table.

    Each ``Authority`` value pins the required ``source_ref.kind`` (and, for
    the two kernel variants, the required ``kernel_ref_kind`` discriminator).
    Any mismatch raises :class:`ValueError` — this is the invariant that
    prevents IPCAT_LIVE-labelled facts from silently carrying ManualRefs.
    """
    kind = getattr(source_ref, "kind", None)
    if authority is Authority.IPCAT_LIVE:
        if kind != "ipcat_live":
            raise ValueError(
                f"{where}: authority IPCAT_LIVE requires source_ref.kind "
                f"'ipcat_live', got {kind!r}"
            )
    elif authority is Authority.IPCAT_CACHED:
        if kind != "ipcat_cached":
            raise ValueError(
                f"{where}: authority IPCAT_CACHED requires source_ref.kind "
                f"'ipcat_cached', got {kind!r}"
            )
    elif authority is Authority.KERNEL_DTS:
        if kind != "kernel":
            raise ValueError(
                f"{where}: authority KERNEL_DTS requires source_ref.kind "
                f"'kernel', got {kind!r}"
            )
        # Guaranteed to be a KernelRef by the kind match above.
        if getattr(source_ref, "kernel_ref_kind", None) != "dts":
            raise ValueError(
                f"{where}: authority KERNEL_DTS requires "
                f"kernel_ref_kind == 'dts', got "
                f"{getattr(source_ref, 'kernel_ref_kind', None)!r}"
            )
    elif authority is Authority.KERNEL_BINDINGS:
        if kind != "kernel":
            raise ValueError(
                f"{where}: authority KERNEL_BINDINGS requires source_ref.kind "
                f"'kernel', got {kind!r}"
            )
        if getattr(source_ref, "kernel_ref_kind", None) != "bindings":
            raise ValueError(
                f"{where}: authority KERNEL_BINDINGS requires "
                f"kernel_ref_kind == 'bindings', got "
                f"{getattr(source_ref, 'kernel_ref_kind', None)!r}"
            )
    elif authority is Authority.SCHEMATIC_PDF:
        if kind != "schematic":
            raise ValueError(
                f"{where}: authority SCHEMATIC_PDF requires source_ref.kind "
                f"'schematic', got {kind!r}"
            )
    elif authority is Authority.ACDB_EXPORT:
        if kind != "acdb":
            raise ValueError(
                f"{where}: authority ACDB_EXPORT requires source_ref.kind "
                f"'acdb', got {kind!r}"
            )
    elif authority is Authority.MANUAL:
        if kind != "manual":
            raise ValueError(
                f"{where}: authority MANUAL requires source_ref.kind "
                f"'manual', got {kind!r}"
            )
    elif authority is Authority.INFERRED:
        if kind != "inferred":
            raise ValueError(
                f"{where}: authority INFERRED requires source_ref.kind "
                f"'inferred', got {kind!r}"
            )
    else:
        # Defensive: WP-D adds a new Authority member without WP-E follow-up.
        raise ValueError(
            f"{where}: authority {authority!r} has no cross-check rule"
        )


# ── FactProvenance (§6) ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class FactProvenance:
    """One append-only history entry for a fact.

    Provenance entries **carry the value they saw at capture time**, not a
    pointer to :attr:`FactValue.value`. Comparing values across a chain is
    how WP-F detects conflicts.

    A revocation entry (``is_revocation=True``) withdraws a prior MANUAL fact
    per PHASE3_ARCHITECTURE.md §6.4. The revocation is itself an append —
    prior entries are never mutated. When the chain top is a revocation entry,
    :meth:`Registry.get` returns ``None`` and :meth:`Registry.iter_facts`
    skips the fact; the chain remains on disk for audit.
    """

    value: Any                       # JsonScalar | Mapping | Sequence (JSON tree)
    authority: Authority
    authority_class: AuthorityClass
    source_ref: SourceRef
    captured_at: datetime            # tz-aware UTC
    confidence: float                # [0.0, 1.0]
    note: str                        # brief human-authored context
    review: "ReviewRecord | None" = None
    is_revocation: bool = False

    def __post_init__(self) -> None:
        # 1. value is JSON-serialisable (round-trips through json.dumps).
        _require_json_serialisable("FactProvenance.value", self.value)

        # Type checks on enum fields.
        if not isinstance(self.authority, Authority):
            raise TypeError(
                "FactProvenance.authority: expected Authority, "
                f"got {type(self.authority).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            raise TypeError(
                "FactProvenance.authority_class: expected AuthorityClass, "
                f"got {type(self.authority_class).__name__}"
            )

        # 2. captured_at is tz-aware UTC.
        _require_utc("FactProvenance.captured_at", self.captured_at)

        # 3. confidence ∈ [0.0, 1.0].
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise TypeError(
                "FactProvenance.confidence: expected float, "
                f"got {type(self.confidence).__name__}"
            )
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "FactProvenance.confidence: expected value in [0.0, 1.0], "
                f"got {self.confidence!r}"
            )

        # note must be a str (empty allowed for provenance's free-text field).
        if not isinstance(self.note, str):
            raise TypeError(
                "FactProvenance.note: expected str, "
                f"got {type(self.note).__name__}"
            )

        # review, if set, must be a ReviewRecord (frozen sibling class).
        if self.review is not None and not isinstance(self.review, ReviewRecord):
            raise TypeError(
                "FactProvenance.review: expected ReviewRecord or None, "
                f"got {type(self.review).__name__}"
            )

        # is_revocation must be a genuine bool (int subclasses excluded).
        if type(self.is_revocation) is not bool:
            raise TypeError(
                "FactProvenance.is_revocation: expected bool, "
                f"got {type(self.is_revocation).__name__}"
            )

        # Cross-check: authority_class MANUAL implies Authority.MANUAL.
        if (
            self.authority_class is AuthorityClass.MANUAL
            and self.authority is not Authority.MANUAL
        ):
            raise ValueError(
                "FactProvenance: authority_class MANUAL requires "
                f"authority == MANUAL, got {self.authority!r}"
            )

        # Cross-check: authority_class INFERRED implies Authority.INFERRED.
        if (
            self.authority_class is AuthorityClass.INFERRED
            and self.authority is not Authority.INFERRED
        ):
            raise ValueError(
                "FactProvenance: authority_class INFERRED requires "
                f"authority == INFERRED, got {self.authority!r}"
            )

        # §7 cross-check (Authority ↔ SourceRef.kind, with KERNEL_* discrim).
        _validate_authority_source_ref(
            "FactProvenance", self.authority, self.source_ref
        )

        # Revocation invariants (§6).
        if self.is_revocation:
            if self.authority_class is not AuthorityClass.MANUAL:
                raise ValueError(
                    "FactProvenance: is_revocation=True requires "
                    "authority_class == MANUAL, got "
                    f"{self.authority_class!r}"
                )
            if self.review is None:
                raise ValueError(
                    "FactProvenance: is_revocation=True requires a "
                    "non-null review"
                )
            if self.review.decision is not ReviewDecision.REJECT:
                raise ValueError(
                    "FactProvenance: is_revocation=True requires "
                    "review.decision == REJECT, got "
                    f"{self.review.decision!r}"
                )
            if self.review.supersedes_provenance_index is None:
                raise ValueError(
                    "FactProvenance: is_revocation=True requires "
                    "review.supersedes_provenance_index to be non-null"
                )


# ── FactValue (§5) ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FactValue:
    """Top-of-chain descriptor plus the full immutable provenance history.

    Frozen. Constructors that violate any of the 8 §5 invariants raise
    :class:`ValueError` (semantic) or :class:`TypeError` (type). Manual-fact
    confidence is clamped at construction time to ``min(confidence, 0.4)``
    when the attached :class:`ReviewRecord` carries no evidence — the cap is
    applied via :func:`object.__setattr__` because the dataclass is frozen.
    """

    value: Any                                       # JSON-serialisable
    authority: Authority
    authority_class: AuthorityClass
    captured_at: datetime                            # tz-aware UTC
    source_ref: SourceRef
    confidence: float                                # [0.0, 1.0], may be capped
    review: "ReviewRecord | None"
    notes: str
    provenance_chain: tuple[FactProvenance, ...]

    def __post_init__(self) -> None:
        # 1. value is JSON-serialisable.
        _require_json_serialisable("FactValue.value", self.value)

        # Type checks on enum fields.
        if not isinstance(self.authority, Authority):
            raise TypeError(
                "FactValue.authority: expected Authority, "
                f"got {type(self.authority).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            raise TypeError(
                "FactValue.authority_class: expected AuthorityClass, "
                f"got {type(self.authority_class).__name__}"
            )

        # 2. captured_at is tz-aware UTC.
        _require_utc("FactValue.captured_at", self.captured_at)

        # 3. confidence ∈ [0.0, 1.0].
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise TypeError(
                "FactValue.confidence: expected float, "
                f"got {type(self.confidence).__name__}"
            )
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "FactValue.confidence: expected value in [0.0, 1.0], "
                f"got {self.confidence!r}"
            )

        # notes must be a str (empty allowed).
        if not isinstance(self.notes, str):
            raise TypeError(
                "FactValue.notes: expected str, "
                f"got {type(self.notes).__name__}"
            )

        # review type check.
        if self.review is not None and not isinstance(self.review, ReviewRecord):
            raise TypeError(
                "FactValue.review: expected ReviewRecord or None, "
                f"got {type(self.review).__name__}"
            )

        # 4. authority_class == MANUAL iff review is not None.
        is_manual = self.authority_class is AuthorityClass.MANUAL
        has_review = self.review is not None
        if is_manual != has_review:
            raise ValueError(
                "FactValue: authority_class MANUAL iff review is not None "
                f"(authority_class={self.authority_class!r}, "
                f"review={'set' if has_review else 'None'})"
            )

        # 5. authority_class == INFERRED implies authority == INFERRED.
        if (
            self.authority_class is AuthorityClass.INFERRED
            and self.authority is not Authority.INFERRED
        ):
            raise ValueError(
                "FactValue: authority_class INFERRED requires "
                f"authority == INFERRED, got {self.authority!r}"
            )

        # 6. authority_class == MANUAL implies authority == MANUAL.
        if is_manual and self.authority is not Authority.MANUAL:
            raise ValueError(
                "FactValue: authority_class MANUAL requires "
                f"authority == MANUAL, got {self.authority!r}"
            )

        # §7 cross-check (Authority ↔ SourceRef.kind, incl. KERNEL_* discrim).
        _validate_authority_source_ref(
            "FactValue", self.authority, self.source_ref
        )

        # 7. provenance_chain non-empty tuple of FactProvenance.
        if not isinstance(self.provenance_chain, tuple):
            raise TypeError(
                "FactValue.provenance_chain: expected tuple, "
                f"got {type(self.provenance_chain).__name__}"
            )
        if len(self.provenance_chain) == 0:
            raise ValueError(
                "FactValue.provenance_chain: must be non-empty"
            )
        for i, entry in enumerate(self.provenance_chain):
            if not isinstance(entry, FactProvenance):
                raise TypeError(
                    f"FactValue.provenance_chain[{i}]: expected "
                    f"FactProvenance, got {type(entry).__name__}"
                )

        # 7 (cont). Descriptor-vs-chain-top match.
        last = self.provenance_chain[-1]
        if not last.is_revocation:
            # Non-revocation top: the 7 shared fields must match byte-for-byte.
            self._require_descriptor_matches(last, kind="last non-revocation top")
        else:
            # Revocation top: descriptor must describe the LAST non-revocation
            # entry in the chain (the "live" value at the moment of revocation).
            # If the chain has none, that is a malformed FactValue.
            last_nonrevoke: FactProvenance | None = None
            for entry in reversed(self.provenance_chain):
                if not entry.is_revocation:
                    last_nonrevoke = entry
                    break
            if last_nonrevoke is None:
                raise ValueError(
                    "FactValue.provenance_chain: revocation top requires at "
                    "least one prior non-revocation entry"
                )
            self._require_descriptor_matches(
                last_nonrevoke, kind="last non-revocation entry (pre-revocation)"
            )

        # 8. Manual-fact confidence cap.
        # Applied via object.__setattr__ because the dataclass is frozen; this
        # is the canonical Python pattern for frozen dataclass normalisation.
        if self.review is not None and not self.review.has_evidence:
            capped = min(float(self.confidence), 0.4)
            if capped != self.confidence:
                object.__setattr__(self, "confidence", capped)

    # ── internal helpers ─────────────────────────────────────────────────────

    def _require_descriptor_matches(
        self, entry: FactProvenance, *, kind: str
    ) -> None:
        """Compare the 7 shared fields with the given chain entry.

        Frozen-dataclass equality is field-wise recursive, so ``==`` on each
        field is byte-equivalent for the value types WP-E supports (SourceRef
        variants, ReviewRecord, enums, datetime, str, float, JSON scalars).
        """
        mismatches: list[str] = []
        if self.value != entry.value:
            mismatches.append("value")
        if self.authority is not entry.authority:
            mismatches.append("authority")
        if self.authority_class is not entry.authority_class:
            mismatches.append("authority_class")
        if self.source_ref != entry.source_ref:
            mismatches.append("source_ref")
        if self.captured_at != entry.captured_at:
            mismatches.append("captured_at")
        # confidence compared BEFORE the manual-fact cap runs — the cap is
        # applied on `self` in step 8, so the descriptor as received from the
        # caller MUST match the entry byte-for-byte. If the caller passes a
        # capped confidence in the descriptor plus an uncapped one in the
        # entry, that's a malformed FactValue; catching it early is correct.
        if float(self.confidence) != float(entry.confidence):
            mismatches.append("confidence")
        if self.review != entry.review:
            mismatches.append("review")
        if mismatches:
            raise ValueError(
                f"FactValue.provenance_chain: descriptor fields do not match "
                f"the {kind}: {', '.join(mismatches)}"
            )


__all__ = [
    "FactKey",
    "FactProvenance",
    "FactValue",
    "JsonScalar",
]
