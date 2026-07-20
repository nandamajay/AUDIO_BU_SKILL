"""Phase-3A WP-D — schema module.

Types shared by the catalog, loader, and downstream WPs. Pure dataclasses +
frozen enums; **no I/O, no yaml/json parsing here** (that lives in ``loader``).

Everything is written to be *purely declarative* so a bad catalog entry fails
at import time (via ``__post_init__`` validation) rather than surfacing later
inside the coverage engine.

Design decisions locked from PHASE3_ARCHITECTURE.md §4:

  * ``Authority`` is the concrete source of a fact (IPCAT_LIVE / IPCAT_CACHED /
    KERNEL_DTS / KERNEL_BINDINGS / SCHEMATIC_PDF / ACDB_EXPORT / MANUAL /
    INFERRED).
  * ``AuthorityClass`` is a coarser axis (PRIMARY / FALLBACK / INFERRED /
    MANUAL) that coverage rules key off — decoupling class-of-source from
    identity-of-source so adding a new authority doesn't fan out into every
    rule.
  * ``Requiredness`` is set **per subject**, not per family (§5.5 revision). A
    family aggregates subject requirements; no family carries a bare
    percentage threshold in Phase-3A.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

# ── Domain scoping ──
# Hierarchical family names ("Audio.GPIO", "Camera.CCI", ...) from day one so
# other domains do not collide with audio's namespace when they come online
# (PHASE3_ARCHITECTURE.md §2 C1). Only Audio and a Generic placeholder ship in
# Phase-3A.


class Domain(str, Enum):
    AUDIO = "Audio"
    CAMERA = "Camera"        # placeholder — no families in Phase-3A
    DISPLAY = "Display"      # placeholder — no families in Phase-3A
    PCIE = "PCIe"            # placeholder — no families in Phase-3A
    GENERIC = "Generic"      # cross-domain families (empty in Phase-3A)


# ── Authorities ──
# Enum of source-of-fact identifiers. Kept flat so the WP-E provenance chain
# can serialise a single string per hop.


class Authority(str, Enum):
    IPCAT_LIVE = "ipcat_live"
    IPCAT_CACHED = "ipcat_cached"
    SCHEMATIC_PDF = "schematic_pdf"
    KERNEL_DTS = "kernel_dts"
    KERNEL_BINDINGS = "kernel_bindings"
    ACDB_EXPORT = "acdb_export"
    MANUAL = "manual"
    INFERRED = "inferred"


class AuthorityClass(str, Enum):
    """Coarser axis coverage rules key off (§5, §7.2 confidence weights).

    PRIMARY   → the family's declared primary authority produced it.
    FALLBACK  → a declared fallback authority produced it.
    INFERRED  → the system derived it (never PRIMARY on a critical family).
    MANUAL    → a human / team supplied it (requires ReviewRecord in WP-E).
    """

    PRIMARY = "primary"
    FALLBACK = "fallback"
    INFERRED = "inferred"
    MANUAL = "manual"


# ── Subject requiredness ──


class Requiredness(str, Enum):
    """Per-subject requiredness. Replaces family-level percentage thresholds.

    MANDATORY → subject must have a covered, non-conflicting fact for its
                family to reach ``verdict=PASS`` (Phase-3A: advisory only).
    ADVISORY  → subject is recommended; missing subjects reported separately.
    OPTIONAL  → tracked for completeness; never gates anything.
    """

    MANDATORY = "mandatory"
    ADVISORY = "advisory"
    OPTIONAL = "optional"


# ── Subject requirement ──
# A subject requirement is a *pattern* (regex-anchored or literal) plus its
# requiredness and two boolean flags that describe how the subject *would* be
# used by later phases (Phase-3A does not enforce either flag).


_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]*$")


@dataclass(frozen=True)
class SubjectRequirement:
    """Declared requirement for one subject class within a fact family.

    ``subject_pattern`` may be a literal identifier ("VDD_LCX") or a regex
    string ("MI2S[0-9]+_BCLK"). When ``is_regex=False`` the pattern must
    match ``_IDENT_RE``. Regex patterns are anchored at both ends by the
    loader; they are not compiled here (kept stringly-typed) so the catalog
    stays trivially serialisable.
    """

    subject_pattern: str
    requiredness: Requiredness
    promotion_relevant: bool = False   # will this subject gate promotion later?
    generation_relevant: bool = False  # will this subject gate code generation?
    is_regex: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.subject_pattern, str) or not self.subject_pattern:
            raise ValueError("SubjectRequirement.subject_pattern must be a non-empty str")
        if not isinstance(self.requiredness, Requiredness):
            raise TypeError(
                f"SubjectRequirement.requiredness must be a Requiredness, got {type(self.requiredness).__name__}"
            )
        if not isinstance(self.promotion_relevant, bool):
            raise TypeError("SubjectRequirement.promotion_relevant must be bool")
        if not isinstance(self.generation_relevant, bool):
            raise TypeError("SubjectRequirement.generation_relevant must be bool")
        if not isinstance(self.is_regex, bool):
            raise TypeError("SubjectRequirement.is_regex must be bool")
        if not self.is_regex and not _IDENT_RE.match(self.subject_pattern):
            raise ValueError(
                f"SubjectRequirement.subject_pattern {self.subject_pattern!r} is not a "
                f"valid literal identifier; set is_regex=True to allow richer patterns"
            )
        if self.is_regex:
            # Anchor and validate — cheap defence against typos entering the catalog.
            try:
                re.compile(f"^(?:{self.subject_pattern})$")
            except re.error as exc:
                raise ValueError(
                    f"SubjectRequirement.subject_pattern {self.subject_pattern!r} "
                    f"failed to compile as regex: {exc}"
                ) from exc


# ── Fact family definition ──


_FAMILY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class FactFamilyDef:
    """One fact family, scoped by a Domain.

    ``qualified_name`` derives ``<Domain>.<name>`` and is the canonical string
    used by the WP-E registry (FactKey prefix) and WP-G report renderer.

    ``primary_authorities`` is a non-empty ordered tuple: the first is *the*
    primary, later entries are additional-primary sources of equal weight (a
    fact from any is treated as PRIMARY by the coverage engine).
    ``fallback_authorities`` may be empty; entries there count as FALLBACK.
    ``allowed_manual`` gates whether MANUAL facts are accepted for this
    family (some families — INFERRED-only sanity data — set this to False).
    """

    domain: Domain
    name: str
    description: str
    primary_authorities: tuple[Authority, ...]
    fallback_authorities: tuple[Authority, ...] = ()
    allowed_manual: bool = True
    critical: bool = False
    subject_requirements: tuple[SubjectRequirement, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.domain, Domain):
            raise TypeError("FactFamilyDef.domain must be a Domain")
        if not isinstance(self.name, str) or not _FAMILY_NAME_RE.match(self.name):
            raise ValueError(
                f"FactFamilyDef.name {self.name!r} must match {_FAMILY_NAME_RE.pattern}"
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("FactFamilyDef.description must be a non-empty str")
        if not self.primary_authorities:
            raise ValueError(
                f"FactFamilyDef {self.qualified_name!r}: primary_authorities must be non-empty"
            )
        for a in self.primary_authorities:
            if not isinstance(a, Authority):
                raise TypeError(
                    f"FactFamilyDef.primary_authorities entry must be Authority, got {type(a).__name__}"
                )
        for a in self.fallback_authorities:
            if not isinstance(a, Authority):
                raise TypeError(
                    f"FactFamilyDef.fallback_authorities entry must be Authority, got {type(a).__name__}"
                )
        prim_set = set(self.primary_authorities)
        fb_set = set(self.fallback_authorities)
        overlap = prim_set & fb_set
        if overlap:
            names = ", ".join(sorted(a.value for a in overlap))
            raise ValueError(
                f"FactFamilyDef {self.qualified_name!r}: authority "
                f"{names} appears in both primary and fallback lists"
            )
        if not isinstance(self.allowed_manual, bool):
            raise TypeError("FactFamilyDef.allowed_manual must be bool")
        if not isinstance(self.critical, bool):
            raise TypeError("FactFamilyDef.critical must be bool")
        # Every family must declare at least one MANDATORY or ADVISORY subject,
        # OR explicitly be an all-optional family (subject list may be empty).
        # In that latter case the family is informational-only and its coverage
        # verdict cannot be worse than WARN in the engine (WP-F).
        for s in self.subject_requirements:
            if not isinstance(s, SubjectRequirement):
                raise TypeError(
                    "FactFamilyDef.subject_requirements entries must be SubjectRequirement"
                )
        # Duplicate subject_pattern within a single family is a bug.
        patterns = [s.subject_pattern for s in self.subject_requirements]
        if len(patterns) != len(set(patterns)):
            dupes = sorted({p for p in patterns if patterns.count(p) > 1})
            raise ValueError(
                f"FactFamilyDef {self.qualified_name!r}: duplicate subject_pattern(s) "
                f"{dupes!r}"
            )
        # Critical families must have at least one MANDATORY subject — otherwise
        # nothing keeps the family from PASSing with an empty registry.
        if self.critical and not any(
            s.requiredness is Requiredness.MANDATORY for s in self.subject_requirements
        ):
            raise ValueError(
                f"FactFamilyDef {self.qualified_name!r} is critical but declares "
                f"zero MANDATORY subjects"
            )

    @property
    def qualified_name(self) -> str:
        return f"{self.domain.value}.{self.name}"

    def mandatory_requirements(self) -> tuple[SubjectRequirement, ...]:
        return tuple(s for s in self.subject_requirements if s.requiredness is Requiredness.MANDATORY)

    def advisory_requirements(self) -> tuple[SubjectRequirement, ...]:
        return tuple(s for s in self.subject_requirements if s.requiredness is Requiredness.ADVISORY)

    def optional_requirements(self) -> tuple[SubjectRequirement, ...]:
        return tuple(s for s in self.subject_requirements if s.requiredness is Requiredness.OPTIONAL)


# ── Freshness policy ──
# Static TTL policy (§5.4). Phase-3A does no auto-refresh; the policy is used
# by WP-F at report render time to derive a fact's ``freshness_state``.


@dataclass(frozen=True)
class AuthorityTTL:
    """TTL for facts of a given authority. Seconds; ``None`` = never expires."""

    authority: Authority
    fresh_seconds: int | None
    stale_seconds: int | None       # after this: STALE; before: FRESH
    expired_seconds: int | None     # after this: EXPIRED

    def __post_init__(self) -> None:
        if not isinstance(self.authority, Authority):
            raise TypeError("AuthorityTTL.authority must be Authority")
        for label, val in (
            ("fresh_seconds", self.fresh_seconds),
            ("stale_seconds", self.stale_seconds),
            ("expired_seconds", self.expired_seconds),
        ):
            if val is not None and (not isinstance(val, int) or val < 0):
                raise ValueError(f"AuthorityTTL.{label} must be a non-negative int or None")
        # Monotonicity: fresh ≤ stale ≤ expired (when all are set).
        if (
            self.fresh_seconds is not None
            and self.stale_seconds is not None
            and self.fresh_seconds > self.stale_seconds
        ):
            raise ValueError(
                f"AuthorityTTL {self.authority.value}: fresh_seconds "
                f"{self.fresh_seconds} > stale_seconds {self.stale_seconds}"
            )
        if (
            self.stale_seconds is not None
            and self.expired_seconds is not None
            and self.stale_seconds > self.expired_seconds
        ):
            raise ValueError(
                f"AuthorityTTL {self.authority.value}: stale_seconds "
                f"{self.stale_seconds} > expired_seconds {self.expired_seconds}"
            )


@dataclass(frozen=True)
class FreshnessPolicy:
    """Per-authority TTL policy. Every ``Authority`` must have exactly one entry."""

    ttls: tuple[AuthorityTTL, ...]

    def __post_init__(self) -> None:
        seen: set[Authority] = set()
        for ttl in self.ttls:
            if not isinstance(ttl, AuthorityTTL):
                raise TypeError("FreshnessPolicy.ttls entries must be AuthorityTTL")
            if ttl.authority in seen:
                raise ValueError(
                    f"FreshnessPolicy: duplicate TTL for authority {ttl.authority.value}"
                )
            seen.add(ttl.authority)
        missing = set(Authority) - seen
        if missing:
            names = ", ".join(sorted(a.value for a in missing))
            raise ValueError(
                f"FreshnessPolicy missing TTL entries for authorities: {names}"
            )

    def ttl_for(self, authority: Authority) -> AuthorityTTL:
        for ttl in self.ttls:
            if ttl.authority is authority:
                return ttl
        raise KeyError(f"no TTL for authority {authority.value}")  # unreachable given __post_init__


# ── Catalog aggregate ──


@dataclass(frozen=True)
class Catalog:
    """Complete fact-family catalog: an ordered, frozen collection of families."""

    families: tuple[FactFamilyDef, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for fam in self.families:
            if not isinstance(fam, FactFamilyDef):
                raise TypeError("Catalog.families entries must be FactFamilyDef")
            q = fam.qualified_name
            if q in seen:
                raise ValueError(f"Catalog: duplicate family qualified_name {q!r}")
            seen.add(q)

    def qualified_names(self) -> tuple[str, ...]:
        return tuple(fam.qualified_name for fam in self.families)

    def by_qualified_name(self, qualified_name: str) -> FactFamilyDef:
        for fam in self.families:
            if fam.qualified_name == qualified_name:
                return fam
        raise KeyError(qualified_name)

    def in_domain(self, domain: Domain) -> tuple[FactFamilyDef, ...]:
        return tuple(fam for fam in self.families if fam.domain is domain)


def merge_families(*groups: Iterable[FactFamilyDef]) -> tuple[FactFamilyDef, ...]:
    """Concatenate per-domain family lists preserving declaration order.

    Duplicate ``qualified_name`` across groups raises — the loader uses this
    to catch a domain accidentally redefining another domain's family.
    """
    out: list[FactFamilyDef] = []
    seen: set[str] = set()
    for group in groups:
        for fam in group:
            q = fam.qualified_name
            if q in seen:
                raise ValueError(f"merge_families: duplicate family qualified_name {q!r}")
            seen.add(q)
            out.append(fam)
    return tuple(out)


__all__ = [
    "Authority",
    "AuthorityClass",
    "AuthorityTTL",
    "Catalog",
    "Domain",
    "FactFamilyDef",
    "FreshnessPolicy",
    "Requiredness",
    "SubjectRequirement",
    "merge_families",
]
