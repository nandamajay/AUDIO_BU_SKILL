"""H-2 reviewer dataclasses (read-only projections of H-1 output).

Five shapes, all **frozen** so nothing downstream of the loader can
mutate a projected fact back into something the reviewer did not read
from H-1:

  * :class:`ReviewerContext` — the set of input/output paths for one
    target. Pure data; the loader consumes it, the renderers (Phase 3+)
    consume it. No behaviour.

  * :class:`FactView` — a frozen projection of one H-1 ``FactRecord``
    (the 10-field envelope) plus the ``path`` it was flattened from.
    This is the H-2 read-side mirror of ``hw_template.model.FactRecord``,
    but it is deliberately a *separate* type: H-2 must not import
    ``orchestrator.hw_template.*`` (invariant I-2), so it reconstructs
    the envelope from the parsed JSON dict rather than sharing the class.

  * :class:`GapView` — one flattened gap from ``gap_manifest.json``,
    carrying the ``FactView`` plus H-2-only ``severity`` / ``state`` /
    ``comment`` slots. In Phase 1 those three are always ``None`` —
    severity assignment (``severity.py``) and workflow state
    (``state.py``) are Phase-2 subsystems and do not exist yet.

  * :class:`EntityView` — one entity instance (codec / amplifier / bus /
    clock / audio_link) or the singleton ``board_metadata`` group, as a
    map of field-name → :class:`FactView`.

  * :class:`TargetView` — the whole target: its entities, its gaps, and
    a small summary dict. This is what :func:`orchestrator.reviewer.loader.load`
    returns.

**Firewall posture (invariants I-1, I-2, I-4):**

  * Nothing here writes ``gc["cross_verification"]["rows"]``,
    ``TrustedFacts``, ``audio_hardware_template.json``, or
    ``gap_manifest.json``. These are inert data holders.
  * Nothing here imports ``orchestrator.hw_template.*``,
    ``orchestrator.reasoning.*``, ``orchestrator.generation.*``, or
    ``orchestrator.codegen.*``. The closed authority / NCC enums are
    re-declared locally (below) precisely so no such import is needed.
  * The authority-strength enum is the same closed 4-value set H-1 uses.
    ``SCHEMATIC_DIRECT`` and ``HUMAN_ATTESTED`` are NOT members and must
    never be added (invariant I-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Local closed enums (re-declared; NOT imported — see I-2) ─────────────────
#
# These mirror ``orchestrator.reasoning.crossverify_model.AUTHORITY_STRENGTHS``
# and ``orchestrator.hw_template.model.NCC_STATES`` by value. They are
# duplicated on purpose: the reviewer subsystem is a JSON-only downstream
# leaf and is forbidden (I-2) from importing either module. If H-1 ever
# widens these enums, this copy must be updated in lock-step — a drift
# guard lives in the Phase-1 tests.

AUTHORITY_STRENGTHS: frozenset[str] = frozenset(
    {"IPCAT_DIRECT", "IPCAT_DERIVED", "KB_RULE", "UNAVAILABLE"}
)

NCC_STATES: frozenset[str] = frozenset(
    {"ATTESTED", "NOT_ATTESTED", "NOT_CROSS_CHECKABLE"}
)

# The reasons a leaf can land in the gap manifest (mirrors
# ``hw_template.model.GapManifest``: real coverage_gap_reasons collapse
# under NOT_CROSS_CHECKABLE, plus the two projector sentinels).
GAP_REASONS: frozenset[str] = frozenset(
    {"candidate_only", "not_attested", "authority_out_of_scope"}
)

# Entity families in an AudioHardwareTemplate (H-1 §3.1). ``board_metadata``
# is a singleton group; the rest are lists.
ENTITY_KINDS: frozenset[str] = frozenset(
    {"board_metadata", "codec", "amplifier", "bus", "clock", "audio_link"}
)

SCHEMA_VERSION = "0.1.0-design"


# ── ReviewerContext ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReviewerContext:
    """Input/output paths for one target's reviewer run.

    Read-only description of *where* H-1 outputs live and *where* the
    reviewer subtree should be written. Holding a path here is not a
    licence to write it — the loader only reads ``template_path`` and
    ``gap_manifest_path`` (and, if present, ``gap_states_path`` /
    ``attested_findings_path``). Output rendering is Phase 3+.

    Fields:

    * ``target_name`` — e.g. ``"nord-iq10"``. Recorded verbatim.
    * ``template_path`` — path to ``audio_hardware_template.json``.
    * ``gap_manifest_path`` — path to ``gap_manifest.json``.
    * ``attested_findings_path`` — path to the (optional) advisory
      ``attested_findings.md``. May not exist; loader tolerates absence.
    * ``gap_states_path`` — path to the (optional) reviewer-edited
      ``gap_states.json``. May not exist; loader tolerates absence.
    """

    target_name: str
    template_path: str
    gap_manifest_path: str
    attested_findings_path: str | None = None
    gap_states_path: str | None = None


# ── FactView ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FactView:
    """Frozen projection of one H-1 ``FactRecord`` envelope.

    Mirrors the 10 FactRecord fields, but ``authority`` is split into
    ``authority_strength`` + ``authority_origin`` for ergonomic reviewer
    rendering, and ``citations`` / ``not_attested_disclosures`` are
    stored as tuples so the whole object is deeply immutable.

    ``path`` is the flattened location the record came from (e.g.
    ``"codecs[0].part_number"``) when the FactView originates from the
    gap manifest, or the field name within an entity when it originates
    from the template. It is ``None`` for template-side records where the
    caller supplies the path via the enclosing :class:`EntityView`.

    This type is READ-ONLY. It never carries a value H-1 did not project;
    ``from_record`` copies verbatim and performs no promotion.
    """

    value: Any = None
    authority_strength: str = "UNAVAILABLE"
    authority_origin: str = "none"
    citations: tuple[str, ...] = ()
    row_ref: str | None = None
    independently_verified: bool = False
    candidate_derived: bool = False
    candidate_value: Any = None
    reviewer_required: bool = False
    ncc_state: str = "NOT_ATTESTED"
    not_attested_disclosures: tuple[dict[str, Any], ...] = ()
    path: str | None = None

    def __post_init__(self) -> None:
        # Read-side validation only. We do NOT re-run H-1's promotion
        # invariant here (that is H-1's construction-time job); we simply
        # refuse to hold a value outside the closed enums, so a corrupt
        # or hand-edited H-1 artefact surfaces loudly at load time rather
        # than silently rendering an illegal authority.
        if self.authority_strength not in AUTHORITY_STRENGTHS:
            raise ValueError(
                f"illegal authority_strength {self.authority_strength!r}; "
                f"expected one of {sorted(AUTHORITY_STRENGTHS)}. "
                "H-2 does not widen the authority enum (invariant I-4)."
            )
        if self.ncc_state not in NCC_STATES:
            raise ValueError(
                f"illegal ncc_state {self.ncc_state!r}; "
                f"expected one of {sorted(NCC_STATES)}"
            )

    @classmethod
    def from_record(cls, record: dict[str, Any], *, path: str | None = None) -> "FactView":
        """Build a FactView from a parsed H-1 FactRecord dict.

        Accepts the shape produced by ``FactRecord.to_dict()`` (an
        ``authority`` sub-dict) and copies every field verbatim. No
        promotion, no defaulting of ``value`` from ``candidate_value``.
        Missing keys fall back to the safe NOT_ATTESTED / UNAVAILABLE
        defaults so a partially-populated record still loads.
        """
        if not isinstance(record, dict):
            raise ValueError(
                f"FactRecord payload must be a dict, got {type(record).__name__}"
            )
        authority = record.get("authority") or {}
        if not isinstance(authority, dict):
            raise ValueError(
                f"authority must be a dict, got {type(authority).__name__}"
            )
        citations = tuple(record.get("citations") or ())
        disclosures = tuple(
            dict(d) for d in (record.get("not_attested_disclosures") or ())
        )
        return cls(
            value=record.get("value"),
            authority_strength=authority.get("strength", "UNAVAILABLE"),
            authority_origin=authority.get("origin", "none"),
            citations=citations,
            row_ref=record.get("row_ref"),
            independently_verified=bool(record.get("independently_verified", False)),
            candidate_derived=bool(record.get("candidate_derived", False)),
            candidate_value=record.get("candidate_value"),
            reviewer_required=bool(record.get("reviewer_required", False)),
            ncc_state=record.get("ncc_state", "NOT_ATTESTED"),
            not_attested_disclosures=disclosures,
            path=path,
        )


# ── GapView ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GapView:
    """One flattened gap from ``gap_manifest.json``.

    Carries the projected :class:`FactView` plus H-2-only reviewer slots:

    * ``severity`` — ``CRITICAL`` / ``MAJOR`` / ``MINOR`` / ``INFO``, or
      ``None``. **Always ``None`` in Phase 1** — severity assignment is
      the Phase-2 ``severity.py`` subsystem.
    * ``state`` — reviewer workflow state (``open`` / ``attesting`` /
      ``attested`` / ``waived`` / ``escalated``), or ``None``. **Always
      ``None`` in Phase 1** — state tracking is the Phase-2 ``state.py``
      subsystem.
    * ``comment`` — reviewer comment attached to a non-open state, or
      ``None``. Phase 2.

    ``severity`` / ``state`` / ``comment`` are H-2-internal reviewer
    annotations only. They are NEVER written back into any H-1 artefact
    or authority path.
    """

    path: str
    reason: str
    fact: FactView
    severity: str | None = None
    state: str | None = None
    comment: str | None = None

    def __post_init__(self) -> None:
        if self.reason not in GAP_REASONS:
            raise ValueError(
                f"illegal gap reason {self.reason!r}; "
                f"expected one of {sorted(GAP_REASONS)}"
            )


# ── EntityView ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntityView:
    """One entity instance projected from the template.

    * ``kind`` — one of :data:`ENTITY_KINDS`
      (``board_metadata`` / ``codec`` / ``amplifier`` / ``bus`` /
      ``clock`` / ``audio_link``).
    * ``index`` — position within its family list, or ``0`` for the
      singleton ``board_metadata`` group.
    * ``fields`` — map of field-name → :class:`FactView`.
    * ``nested_disclosures`` — any non-FactRecord disclosure payloads
      carried alongside the entity (reserved for later phases; empty in
      the current projector output).
    """

    kind: str
    index: int
    fields: dict[str, FactView] = field(default_factory=dict)
    nested_disclosures: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ENTITY_KINDS:
            raise ValueError(
                f"illegal entity kind {self.kind!r}; "
                f"expected one of {sorted(ENTITY_KINDS)}"
            )


# ── TargetView ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TargetView:
    """The whole projected target — the loader's return type.

    * ``target_name`` — verbatim from the template.
    * ``run_id`` — verbatim from the template.
    * ``schema_version`` — the H-1 schema version the artefacts declared.
    * ``generated_from`` — provenance dict copied from the template.
    * ``entities`` — tuple of :class:`EntityView` (board_metadata first,
      then codecs, amplifiers, buses, clocks, audio_links in order).
    * ``gaps`` — tuple of :class:`GapView`, in manifest order.
    * ``summary`` — small derived counts dict (entity counts, gap counts
      by reason). Purely descriptive; not an authority signal.
    """

    target_name: str
    run_id: str
    schema_version: str = SCHEMA_VERSION
    generated_from: dict[str, Any] = field(default_factory=dict)
    entities: tuple[EntityView, ...] = ()
    gaps: tuple[GapView, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    def entities_of(self, kind: str) -> tuple[EntityView, ...]:
        """Return the entities of one kind, in order."""
        return tuple(e for e in self.entities if e.kind == kind)
