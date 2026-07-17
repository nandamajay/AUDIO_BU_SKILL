"""Phase-2B WP2 — fact projector (regression anchor).

Pure, stdlib-only projection from Phase-2A's ``list[VerificationRow]`` output
to Phase-2B's ``TrustedFacts`` type. Every downstream generator (WP3–WP6) reads
``TrustedFacts``; a byte-drift in this projection propagates through the entire
generation pipeline. Consequently WP2 is the *regression anchor*: the frozen
fixture at ``tests/fixtures/phase2b/nord_trusted_facts.json`` is what every
downstream WP builds against, not a live projection.

Projection rules (PHASE2B_SPECIFICATION.md §WP2):

  * Each input row is keyed by ``f"{row.track}.{row.subject}"`` in
    ``rows_by_track_subject``. Callers looking up a gate name (e.g.
    ``"T5.dts.firmware"``) find the row directly.
  * The projection is *inclusive* — even ``warning=True`` rows and
    ``NOT_CROSS_CHECKABLE`` rows land in ``rows_by_track_subject`` so
    ``TrustedFacts.is_open()`` can gate on the row's own state. The gating
    decision (open/closed) is not performed here; ``is_open()`` is the
    predicate.
  * ``UNAVAILABLE`` authority strength / ``NOT_CROSS_CHECKABLE`` verdict rows
    still project — the fact *field* they populate at the runner layer is what
    "is None" means; the row entry itself is preserved so
    ``TrustedFacts.is_open()`` can return False for the right reason
    (verdict-based, not "row missing").
  * ``T4b`` advisory-row carve-out (§3.7) is NOT applied here — advisory-row
    handling is a *runner* concern (WP10) that layers on top of ``is_open()``.
  * Unknown ``(track, subject)`` combinations are NOT rejected: the projection
    is unopinionated about which pairs are known — that's WP1b's gating table.
    An unknown row still projects into ``rows_by_track_subject``; the runner's
    gate evaluator simply never queries it.
  * If two input rows have the same ``(track, subject)`` pair, the LAST one
    wins (dict-assignment semantics). Phase-2A does not emit duplicates in
    practice; this fallback is documented so future ambiguity has a
    deterministic tiebreaker rather than silent nondeterminism.

Zero I/O, zero timestamps, zero env reads. Deterministic: identical input
produces byte-identical ``TrustedFacts.to_dict()`` output.

Import discipline:

  * MAY import: ``orchestrator.generation.model`` (WP1a — ``TrustedFacts``,
    the projection target); ``orchestrator.reasoning.crossverify_model``
    (Phase-2A — ``VerificationRow`` type only, for the input signature).
  * MUST NOT import: ``orchestrator.reasoning.crossverify`` or
    ``orchestrator.reasoning.cardinality`` (Phase-2A verification internals —
    a projection has no business calling the verifier), nor any other
    Phase-2A module beyond ``VerificationRow`` itself. Enforced by
    ``tests/test_generation_facts.py::test_facts_import_guard``.
  * WP1b's ``generation.config`` (policy) is intentionally NOT imported —
    projection is *policy-free*; gating tables + advisory rules apply at the
    runner layer, not here. This keeps the fixture invariant to any WP1b
    policy churn.

Run the tests: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_facts``
"""

from __future__ import annotations

from orchestrator.generation.model import TrustedFacts
from orchestrator.reasoning.crossverify_model import VerificationRow


def _row_from_maybe_dict(row: VerificationRow | dict) -> VerificationRow:
    """Return row unchanged if it is a VerificationRow; construct one from a dict.

    ``gc["cross_verification"]["rows"]`` stores serialized dicts rather than
    ``VerificationRow`` objects (Phase-2A wiring serializes to dict on write;
    this is pre-existing since WP8). Callers such as ``main.py`` pass those
    dicts directly; this helper lets ``project_facts`` accept either shape
    so neither the Phase-2A wiring nor ``main.py`` need modification.
    """
    if isinstance(row, VerificationRow):
        return row
    return VerificationRow(**row)


def project_facts(rows: list) -> TrustedFacts:
    """Project a Phase-2A row list to a Phase-2B ``TrustedFacts``.

    Pure, deterministic, zero I/O. Every row lands in
    ``rows_by_track_subject`` keyed by ``f"{row.track}.{row.subject}"``.
    Duplicate keys are last-wins (see module docstring).

    The projection is *inclusive*: ``NOT_CROSS_CHECKABLE`` rows,
    ``UNAVAILABLE`` authority rows, ``warning=True`` rows, and unknown
    ``(track, subject)`` combinations all project — the downstream gating
    predicate (``TrustedFacts.is_open``) closes the gate for the right reason
    based on the row's own fields.

    Parameters
    ----------
    rows:
        Phase-2A ``VerificationRow`` list, or a list of the serialized dicts
        that ``gc["cross_verification"]["rows"]`` carries (i.e. the output of
        ``VerificationRow.to_dict()``). Both shapes are accepted; mixed lists
        are also tolerated. Callers need not rehydrate before calling.
        Typically ``cross_verification.rows`` from a completed verification run.

    Returns
    -------
    TrustedFacts
        Frozen projection. ``rows_by_track_subject`` populated in input order
        (dict-preserving); ``to_dict()`` emits keys in sorted order for
        byte-stable JSON serialization.
    """
    rows_by_track_subject: dict[str, VerificationRow] = {}
    for row in rows:
        vrow = _row_from_maybe_dict(row)
        key = f"{vrow.track}.{vrow.subject}"
        rows_by_track_subject[key] = vrow
    return TrustedFacts(rows_by_track_subject=rows_by_track_subject)


__all__ = ["project_facts"]
