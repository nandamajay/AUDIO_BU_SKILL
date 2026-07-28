"""H-1 hardware-template dataclasses.

Three shapes:

  * :class:`FactRecord` — the mandatory per-leaf envelope. Every value in
    :class:`AudioHardwareTemplate` is a FactRecord (or ``None``). Enforces
    the projector-invariant "``candidate_derived`` implies UNAVAILABLE
    authority" at construction — i.e. a candidate can never appear
    with a real authority strength attached. This is the runtime half of
    ``test_h1_projector_never_promotes_candidate.py``.

  * :class:`AudioHardwareTemplate` — the top-level projection, grouped by
    entity family. Serialized to ``audio_hardware_template.json``.

  * :class:`GapManifest` — flattened reviewer view of every NCC /
    NOT_ATTESTED / candidate leaf. Serialized to ``gap_manifest.json``.

**No production behaviour reads these classes.** They exist purely to
serialize reviewer disclosures. Nothing in ``orchestrator/generation/`` or
``orchestrator/reasoning/`` may import them (WP-64 firewall).

Import discipline: this module MAY import
``orchestrator.reasoning.crossverify_model`` for the closed-enum names it
mirrors (``AUTHORITY_STRENGTHS``, ``COVERAGE_GAP_REASONS``). It MUST NOT
import any other reasoning submodule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.reasoning.crossverify_model import (
    AUTHORITY_STRENGTHS,
    COVERAGE_GAP_REASONS,
)

# ── Local closed enums (mirror crossverify_model where they overlap) ─────────

# NCC state on every FactRecord. Three states:
#   * ATTESTED         — a MATCH / PARTIAL_MATCH row exists AND authority
#                        strength is not UNAVAILABLE. Reviewer sees a
#                        real, cross-checked value.
#   * NOT_ATTESTED     — no row exists at all (schematic/candidate/WP-69
#                        style). The FactRecord's ``value`` slot is
#                        ``None``; ``candidate_value`` may hold what the
#                        schematic *would* have said.
#   * NOT_CROSS_CHECKABLE — a row exists with
#                        ``verdict=NOT_CROSS_CHECKABLE`` and a
#                        ``coverage_gap_reason``. Reviewer disclosure only.
NCC_STATES: frozenset[str] = frozenset(
    {"ATTESTED", "NOT_ATTESTED", "NOT_CROSS_CHECKABLE"}
)

SCHEMA_VERSION = "0.1.0-design"


# ── FactRecord ──────────────────────────────────────────────────────────────


@dataclass
class FactRecord:
    """Envelope around every leaf value in the audio hardware template.

    Fields:

    * ``value`` — the attested value if any, else ``None``. NOT set from
      ``candidate_value`` under any circumstance.
    * ``authority`` — the crossverify authority object
      (``{"strength": <enum>, "origin": <str>, ...}``). Defaults to
      ``{"strength": "UNAVAILABLE", "origin": "none"}`` when no row
      exists.
    * ``citations`` — the source citations from the underlying
      VerificationRow (or ``[]`` if none).
    * ``row_ref`` — ``"<track>.<subject>"`` pointer back to the
      originating row (or ``None`` if NOT_ATTESTED with no row at all).
    * ``independently_verified`` — mirrors the MATCH/PARTIAL_MATCH
      distinction: ``True`` iff verdict==MATCH.
    * ``candidate_derived`` — ``True`` iff the projector is disclosing
      that a candidate (schematic side) contributed a value but no
      authority attested it.
    * ``candidate_value`` — the raw candidate value, disclosed for
      reviewer visibility. Never promoted to ``value``.
    * ``reviewer_required`` — ``True`` iff the reviewer must attest
      this fact manually (mirrors row.review_actions non-empty, or
      NCC state, or candidate-only).
    * ``ncc_state`` — one of :data:`NCC_STATES`.
    * ``not_attested_disclosures`` — list of dicts, each ``{
      "reason": <coverage_gap_reason>, "detail": <str>, "citations":
      [...] }``. WP-69 style disclosures live here.
    * ``attestation`` — the curated-override attestation block
      (``{"attested_by", "timestamp", "evidence", "target"}``) when this
      leaf was gap-filled by a schematic/reviewer curated override, else
      ``None``. The ``evidence`` sheet reference is what a generation
      consumer surfaces in its disclosure comment
      (``schematic-attested (sheet <X>), NOT IPCAT-cross-verified``). It
      is **disclosure-only** — it never reaches cross_verification /
      TrustedFacts / any gate. Serialized only when non-None (a leaf with
      no curated attestation omits the key entirely, preserving
      byte-identity for un-curated targets like Nord).

    **Construction invariant** (test_h1_projector_never_promotes_candidate.py):

    If ``candidate_derived is True``, then ``authority["strength"]``
    MUST equal ``"UNAVAILABLE"``. A candidate cannot appear alongside a
    real authority — that would be a promotion. Raises ValueError on
    violation.
    """

    value: Any = None
    authority: dict[str, Any] = field(
        default_factory=lambda: {"strength": "UNAVAILABLE", "origin": "none"}
    )
    citations: list[str] = field(default_factory=list)
    row_ref: str | None = None
    independently_verified: bool = False
    candidate_derived: bool = False
    candidate_value: Any = None
    reviewer_required: bool = False
    ncc_state: str = "NOT_ATTESTED"
    not_attested_disclosures: list[dict[str, Any]] = field(default_factory=list)
    attestation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # authority.strength must be a real crossverify enum. If the
        # caller forgot to pass one, default is fine; if they passed
        # something bogus, fail loudly.
        if not isinstance(self.authority, dict):
            raise ValueError(
                f"authority must be a dict, got {type(self.authority).__name__}"
            )
        strength = self.authority.get("strength")
        if strength not in AUTHORITY_STRENGTHS:
            raise ValueError(
                f"illegal authority.strength {strength!r}; "
                f"expected one of {sorted(AUTHORITY_STRENGTHS)}"
            )
        self.authority.setdefault("origin", "none")

        if self.ncc_state not in NCC_STATES:
            raise ValueError(
                f"illegal ncc_state {self.ncc_state!r}; "
                f"expected one of {sorted(NCC_STATES)}"
            )

        # THE promotion invariant. A candidate-derived leaf can never
        # carry a real authority — that combination would be exactly
        # what the projector is forbidden from producing.
        if self.candidate_derived and strength != "UNAVAILABLE":
            raise ValueError(
                "FactRecord invariant violated: candidate_derived is True but "
                f"authority.strength is {strength!r}; a candidate cannot be "
                "promoted to an attested authority. Fix the projector."
            )

        # A candidate-derived leaf must not populate ``value`` (only
        # ``candidate_value``). Similarly, if there is no row_ref and no
        # candidate_value, the reviewer has nothing — that's fine, but
        # ``value`` should still be None.
        if self.candidate_derived and self.value is not None:
            raise ValueError(
                "FactRecord invariant violated: candidate_derived is True but "
                "``value`` is populated; candidate values must live in "
                "``candidate_value`` only."
            )

        # If independently_verified is True, ncc_state must be ATTESTED
        # — otherwise we'd be claiming verification on a gap row.
        if self.independently_verified and self.ncc_state != "ATTESTED":
            raise ValueError(
                "FactRecord invariant violated: independently_verified is True "
                f"but ncc_state is {self.ncc_state!r}; only ATTESTED facts can "
                "be independently_verified."
            )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection with a fixed key order.

        List/dict fields are copied so the returned dict is decoupled
        from the FactRecord.

        ``attestation`` is serialized ONLY when non-None: an un-curated
        leaf (the common case — e.g. every Nord schematic leaf) omits the
        key entirely, so adding this field does not perturb the bytes of
        an already-persisted template that carried no curated overrides.
        """
        out = {
            "value": self.value,
            "authority": dict(sorted(self.authority.items())),
            "citations": list(self.citations),
            "row_ref": self.row_ref,
            "independently_verified": self.independently_verified,
            "candidate_derived": self.candidate_derived,
            "candidate_value": self.candidate_value,
            "reviewer_required": self.reviewer_required,
            "ncc_state": self.ncc_state,
            "not_attested_disclosures": [dict(d) for d in self.not_attested_disclosures],
        }
        if self.attestation is not None:
            out["attestation"] = dict(self.attestation)
        return out


# ── AudioHardwareTemplate ───────────────────────────────────────────────────


@dataclass
class AudioHardwareTemplate:
    """Top-level projection of the audio hardware template.

    Six entity groups (§3.1 of WP_H-1_DESIGN.md):

    * ``board_metadata`` — target_name, soc, board_variant, ...
    * ``codecs`` — list of codec-instance dicts.
    * ``amplifiers`` — list of amplifier-instance dicts.
    * ``buses`` — list of bus-instance dicts (I2S / SoundWire / SLIMbus).
    * ``clocks`` — list of clock-instance dicts.
    * ``audio_links`` — list of dai-link / route dicts.

    Every leaf value inside each group MUST be a FactRecord (or a
    ``FactRecord.to_dict()`` payload). This is a soft invariant enforced
    at ``to_dict``-time (the projector always builds FactRecords; a raw
    string / int here is a bug).

    ``generated_from`` records the provenance from
    ``gc["cross_verification"]["snapshot_provenance"]`` — chip alias,
    mcp_state, and any other keys the snapshot carried.
    """

    target_name: str
    run_id: str
    generated_from: dict[str, Any] = field(default_factory=dict)
    board_metadata: dict[str, Any] = field(default_factory=dict)
    codecs: list[dict[str, Any]] = field(default_factory=list)
    amplifiers: list[dict[str, Any]] = field(default_factory=list)
    buses: list[dict[str, Any]] = field(default_factory=list)
    clocks: list[dict[str, Any]] = field(default_factory=list)
    audio_links: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection with a fixed key order.

        FactRecord children are recursively converted via ``to_dict()``.
        Raw dicts / primitives are passed through unchanged, which keeps
        the output stable when the projector emits an intermediate
        FactRecord.to_dict() payload directly.
        """
        return {
            "$schema_version": self.schema_version,
            "target_name": self.target_name,
            "run_id": self.run_id,
            "generated_from": dict(self.generated_from),
            "board_metadata": _dictify(self.board_metadata),
            "codecs": [_dictify(c) for c in self.codecs],
            "amplifiers": [_dictify(a) for a in self.amplifiers],
            "buses": [_dictify(b) for b in self.buses],
            "clocks": [_dictify(c) for c in self.clocks],
            "audio_links": [_dictify(link) for link in self.audio_links],
        }


# ── GapManifest ─────────────────────────────────────────────────────────────


@dataclass
class GapManifest:
    """Flattened reviewer view of every NCC / candidate / NOT_ATTESTED leaf.

    Keyed by ``coverage_gap_reason`` (or the sentinel ``"not_attested"``
    for no-row-at-all disclosures, or ``"candidate_only"`` for
    schematic-side candidates). Every entry carries the same shape as
    the FactRecord it was flattened from, plus a ``path`` field pointing
    back into the AudioHardwareTemplate (e.g. ``"codecs[0].part_number"``).
    """

    target_name: str
    run_id: str
    gap_count_by_reason: dict[str, int] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        # gap_count_by_reason keys must be either a real
        # coverage_gap_reason, "not_attested", or "candidate_only".
        allowed = set(COVERAGE_GAP_REASONS) | {"not_attested", "candidate_only"}
        illegal = set(self.gap_count_by_reason) - allowed
        if illegal:
            raise ValueError(
                f"illegal gap_count_by_reason keys {sorted(illegal)!r}; "
                f"expected subset of {sorted(allowed)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema_version": self.schema_version,
            "target_name": self.target_name,
            "run_id": self.run_id,
            "gap_count_by_reason": dict(sorted(self.gap_count_by_reason.items())),
            "gaps": [dict(g) for g in self.gaps],
        }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _dictify(obj: Any) -> Any:
    """Recursively convert FactRecords to their dict form.

    Preserves order for dicts; converts lists element-wise; passes
    primitives through unchanged.
    """
    if isinstance(obj, FactRecord):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: _dictify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_dictify(item) for item in obj]
    return obj
