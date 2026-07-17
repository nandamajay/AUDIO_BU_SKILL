"""Phase-2B WP1a — generation model (dataclasses only, no policy).

Pure, stdlib-only value objects for the Phase-2B generation pipeline. Mirrors
the sibling Phase-2A model (``orchestrator/reasoning/crossverify_model.py``):
``from __future__ import annotations``, frozen dataclasses, ``to_dict()``, no
third-party deps, no network, no timestamps.

Four dataclasses:

  * ``GeneratedArtifact`` — a generator emitted this artifact.
  * ``GeneratorSkipped`` — a generator refused to run (gate closed / policy).
  * ``GenerationResult`` — union alias ``GeneratedArtifact | GeneratorSkipped``.
  * ``TrustedFacts`` — the immutable Phase-2A row projection consumed by the
    generation runner. Ships an ``is_open(track, subject) -> bool`` helper
    encoding the gating rules from PHASE2B_SPECIFICATION.md §4.

All four are ``frozen=True`` (dataclass-immutable) and expose ``.to_dict()``
returning JSON-serializable output with a fixed key order so
``json.dumps(x.to_dict(), sort_keys=True)`` is byte-stable across runs.

Sort keys are defined at the class level (``sort_key()`` classmethods), *not*
scattered in the renderer — WP1b, WP7 and WP10 all import the same key.

**No policy.** No gating expressions, no skip-reason enums, no path-guard
constants — those live in ``generation/config.py`` (WP1b). This module has
an **import guard** (enforced by a test) that ``generation/config.py`` is not
imported here. Reverse direction (``reasoning/*`` importing ``generation/*``)
is forbidden by convention (a WP1b lint test enforces this).

Run the tests: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_model``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

from orchestrator.reasoning.crossverify_model import VerificationRow

# ── Gating verdict/warning state (PHASE2B_SPECIFICATION.md §4) ───────────────

# Verdicts that leave a gate OPEN. PARTIAL_MATCH is OPEN here — the WP1b
# ``KNOWN_BAD_PARTIAL_MATCH_RULES`` (donor-residue exception, §4.4) turns
# specific rule_ids back into skips at policy time; the type layer stays
# permissive.
_GATING_OPEN_VERDICTS: frozenset[str] = frozenset({"MATCH", "PARTIAL_MATCH"})

# Serialization key orders (fixed, deterministic — same discipline as
# ``VerificationRow._KEY_ORDER``).
_GENERATED_KEY_ORDER: tuple[str, ...] = (
    "kind",
    "artifact_class",
    "subject",
    "path_hint",
    "bytes_hex",
    "contributes_rows",
)
_SKIPPED_KEY_ORDER: tuple[str, ...] = (
    "kind",
    "artifact_class",
    "subject",
    "reason",
    "gating_rows",
)
_TRUSTED_FACTS_KEY_ORDER: tuple[str, ...] = ("rows_by_track_subject",)


@dataclass(frozen=True)
class GeneratedArtifact:
    """A generator produced this artifact.

    Immutable. Every field is required. ``bytes_`` holds the raw generated
    payload — DTS text, C source, etc. — and is hex-encoded in ``to_dict()``
    so the projection is JSON-serializable.

    ``contributes_rows`` are the Phase-2A ``VerificationRow`` objects the
    post-gen re-verification pass (WP7) will append to
    ``cross_verification.rows`` — the artifact declares up-front which rows
    it will produce, so a byte-drift in bytes_ has an anchor in the fixture
    chain.
    """

    subject: str
    artifact_class: str
    path_hint: str
    bytes_: bytes
    contributes_rows: list[VerificationRow] = field(default_factory=list)

    @classmethod
    def sort_key(cls, item: GeneratedArtifact) -> tuple[str, str]:
        """Stable sort key: ``(artifact_class, subject)``.

        Defined at the class level so WP1b, WP7 and WP10 all import the same
        ordering — no scattered ``sorted(..., key=lambda a: (a.artifact_class,
        a.subject))`` at each callsite.
        """
        return (item.artifact_class, item.subject)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order.

        ``bytes_`` is hex-encoded (via ``.hex()``) so the projection stays
        text-only for ``json.dumps(sort_keys=True)`` byte-stability. The
        ``kind`` discriminator lets a mixed ``GenerationResult`` list be
        round-tripped without runtime type-inspection.
        """
        values: dict[str, Any] = {
            "kind": "GeneratedArtifact",
            "artifact_class": self.artifact_class,
            "subject": self.subject,
            "path_hint": self.path_hint,
            "bytes_hex": self.bytes_.hex(),
            "contributes_rows": [row.to_dict() for row in self.contributes_rows],
        }
        return {key: values[key] for key in _GENERATED_KEY_ORDER}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GeneratedArtifact":
        """Rehydrate a GeneratedArtifact from its to_dict() output for
        the write path (WP11.2).

        Partial round-trip by design: contributes_rows is intentionally
        set to [] because the write path (runner.py:101-105) reads only
        path_hint and bytes_. Full VerificationRow rehydration would
        require VerificationRow.from_dict in reasoning/crossverify_model.py,
        which is deferred until a downstream consumer needs it.

        Callers that need contributes_rows must not use from_dict — use
        the original GeneratedArtifact object instead, or extend this
        method (and add VerificationRow.from_dict) when the need arises.
        """
        return cls(
            subject=d["subject"],
            artifact_class=d["artifact_class"],
            path_hint=d["path_hint"],
            bytes_=bytes.fromhex(d["bytes_hex"]),
            contributes_rows=[],
        )


@dataclass(frozen=True)
class GeneratorSkipped:
    """A generator refused to run (or was blocked by a closed gate).

    Immutable. ``reason`` is a free-form string here (the WP1b
    ``SKIP_REASONS`` enum constrains it at policy time); ``gating_rows``
    lists the ``(track, subject)`` row identifiers that held the gate
    closed — e.g. ``["T5.dts.firmware", "T5.dts.compatible"]``.
    """

    subject: str
    artifact_class: str
    reason: str
    gating_rows: list[str] = field(default_factory=list)

    @classmethod
    def sort_key(cls, item: GeneratorSkipped) -> tuple[str, str]:
        """Stable sort key: ``(artifact_class, subject)``.

        Same shape as ``GeneratedArtifact.sort_key`` so a mixed
        ``GenerationResult`` list can be sorted by
        ``sort_key_for_result(item)`` (below) without a type branch at the
        callsite.
        """
        return (item.artifact_class, item.subject)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order."""
        values: dict[str, Any] = {
            "kind": "GeneratorSkipped",
            "artifact_class": self.artifact_class,
            "subject": self.subject,
            "reason": self.reason,
            "gating_rows": list(self.gating_rows),
        }
        return {key: values[key] for key in _SKIPPED_KEY_ORDER}


#: Union alias — a generator returns either a produced artifact or a skip
#: verdict. Kept as a runtime-usable ``Union`` (not ``X | Y``) so tests can
#: introspect the members via ``typing.get_args()`` without importing
#: ``types.UnionType`` and without depending on Python 3.10+ syntax coverage
#: in static analysis tools.
GenerationResult = Union[GeneratedArtifact, GeneratorSkipped]


def sort_key_for_result(item: GenerationResult) -> tuple[str, str]:
    """Common sort key for a mixed ``GenerationResult`` list.

    Both branches use ``(artifact_class, subject)``, so a mixed list of
    ``GeneratedArtifact`` and ``GeneratorSkipped`` sorts stably without a
    ``isinstance`` branch at the callsite.
    """
    return (item.artifact_class, item.subject)


@dataclass(frozen=True)
class TrustedFacts:
    """Immutable Phase-2A row projection consumed by the generation runner.

    ``rows_by_track_subject`` maps ``"<track>.<subject>"`` → ``VerificationRow``.
    The key format matches how ``GeneratorSkipped.gating_rows`` names its
    dependencies (e.g. ``"T5.dts.firmware"``), so callers use the same
    string vocabulary on both sides of a gate.

    Populated by WP2 (fact projector) from ``cross_verification.rows``. This
    module knows *nothing* about the projection logic — it just holds the
    result and answers ``is_open(track, subject)``.
    """

    rows_by_track_subject: dict[str, VerificationRow] = field(default_factory=dict)

    def is_open(self, track: str, subject: str) -> bool:
        """Return True iff row ``(track, subject)`` opens its gate.

        Gating rules (PHASE2B_SPECIFICATION.md §4):

          * A row with ``warning=True`` is ALWAYS closed — even if the
            verdict would otherwise open. ``warning`` is the reviewer
            work-list flag; the runner MUST NOT bypass it.
          * ``MATCH`` / ``PARTIAL_MATCH`` → OPEN.
          * Everything else (``NOT_CROSS_CHECKABLE`` for any reason,
            ``REVIEW_REQUIRED``, ``DISAGREE_WITH_AUTHORITY``) → CLOSED.
          * Missing row (``(track, subject)`` not projected) → CLOSED
            (fail-closed by default per §4.2).

        The T4b advisory-row carve-out (§3.7) is enforced at *policy* layer
        (WP1b + WP6), not here — this method is a pure predicate over the
        row's own state. Callers with advisory-row awareness override the
        decision at the runner level.
        """
        row = self.rows_by_track_subject.get(f"{track}.{subject}")
        if row is None:
            return False
        if row.warning:
            return False
        return row.verdict in _GATING_OPEN_VERDICTS

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order.

        Rows are emitted in sorted-key order (dict-key sorted) so
        ``json.dumps(sort_keys=True)`` byte-stability holds even if the
        producer populated the underlying dict in a different order.
        """
        values: dict[str, Any] = {
            "rows_by_track_subject": {
                key: self.rows_by_track_subject[key].to_dict()
                for key in sorted(self.rows_by_track_subject)
            },
        }
        return {key: values[key] for key in _TRUSTED_FACTS_KEY_ORDER}


# ── WP7 — post-verification model (fan-in trust check) ─────────────────────
#
# WP7's post-gen verifier runs AFTER all four generator lanes have produced
# their ``GenerationResult`` (``GeneratedArtifact`` | ``GeneratorSkipped``).
# It does not re-open gates; it audits the gate/skip decisions AGAINST the
# source ``TrustedFacts`` to catch two bug classes:
#
#   (A) Gate-consistency (per ``GeneratedArtifact``): every gating row for the
#       artifact_class is open (per §4 rules, with the §3.7 T4b advisory
#       carve-out for the ``NCC + authority_out_of_scope`` verdict).
#   (B) Skip-validity (per ``GeneratorSkipped``): every cited gating_rows
#       entry is (i) a real row key in ``TrustedFacts.rows_by_track_subject``
#       (glob patterns like ``"gpio.i2s.*"`` are tolerated), (ii) at least one
#       cited row is closed in the source (with the §4.4 KNOWN_BAD carve-out —
#       a PARTIAL_MATCH row whose ``rule_id`` is known-bad counts as closed),
#       and (iii) the skip ``reason`` is registered in ``SKIP_REASONS``.
#
# ``verdict``: ``"pass"`` | ``"fail"``. ``details`` is a free-form structured
# breadcrumb (row keys inspected, carve-out that applied, etc.) — a JSON dict
# with sorted keys so byte-identity fixture comparisons stay stable.
_POST_ROW_KEY_ORDER: tuple[str, ...] = (
    "artifact_class",
    "subject",
    "kind",
    "verdict",
    "message",
    "details",
)
_POST_RESULT_KEY_ORDER: tuple[str, ...] = ("verdict", "rows")


@dataclass(frozen=True)
class PostVerificationRow:
    """One row of the WP7 post-generation verifier's output.

    ``kind`` mirrors the ``GenerationResult`` variant this row audits —
    ``"GeneratedArtifact"`` or ``"GeneratorSkipped"``. Immutable.
    """

    artifact_class: str
    subject: str
    kind: str
    verdict: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def sort_key(cls, item: PostVerificationRow) -> tuple[str, str, str]:
        """Stable sort key: ``(artifact_class, subject, kind)``."""
        return (item.artifact_class, item.subject, item.kind)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order.

        ``details`` keys are sorted at emit time so ``json.dumps(sort_keys=True)``
        is not the *only* thing standing between us and byte drift.
        """
        values: dict[str, Any] = {
            "artifact_class": self.artifact_class,
            "subject": self.subject,
            "kind": self.kind,
            "verdict": self.verdict,
            "message": self.message,
            "details": {key: self.details[key] for key in sorted(self.details)},
        }
        return {key: values[key] for key in _POST_ROW_KEY_ORDER}


@dataclass(frozen=True)
class PostVerificationResult:
    """WP7 aggregate: overall ``verdict`` + per-artifact ``rows``.

    ``verdict`` is ``"pass"`` iff every row's verdict is ``"pass"``. ``rows``
    is sorted by ``PostVerificationRow.sort_key`` so serialization is
    byte-stable across runs.
    """

    verdict: str
    rows: list[PostVerificationRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection with a fixed key order."""
        sorted_rows = sorted(self.rows, key=PostVerificationRow.sort_key)
        values: dict[str, Any] = {
            "verdict": self.verdict,
            "rows": [row.to_dict() for row in sorted_rows],
        }
        return {key: values[key] for key in _POST_RESULT_KEY_ORDER}
