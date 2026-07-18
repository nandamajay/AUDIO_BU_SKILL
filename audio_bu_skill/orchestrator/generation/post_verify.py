"""Phase-2B WP7 — post-generation fan-in trust verifier.

Pure, stdlib-only auditor that runs AFTER all four generator lanes have
produced their ``GenerationResult`` (``GeneratedArtifact`` |
``GeneratorSkipped``). It does NOT re-open gates; it audits each generator's
gate/skip decision against the source ``TrustedFacts`` to catch divergence
between the *emitted verdict* (artifact vs skip) and the *actual row state*
the generator claimed drove that verdict.

Two audit shapes (per WP7 locked A1 — gate-consistency + skip-validity, NOT
grep-based value-drift):

  (A) Gate-consistency (per ``GeneratedArtifact``): for every ``(track,
      subject_pattern)`` in the generator's registered ``gating_rows`` (see
      ``GATING_ROWS[artifact_class]``), expand the pattern against
      ``facts.rows_by_track_subject`` and require AT LEAST ONE matching row
      to be OPEN — per §4 rules, with the §3.7 T4b advisory carve-out (a
      row on an advisory track that is ``NOT_CROSS_CHECKABLE +
      authority_out_of_scope`` OR ``REVIEW_REQUIRED`` counts as open). Any
      gate where zero rows match OR every matching row is closed → FAIL.

  (B) Skip-validity (per ``GeneratorSkipped``): three checks.
        (i)   ``reason`` must be a member of the registered
              ``SKIP_REASONS``.
        (ii)  Every cited ``gating_rows`` entry must resolve to ≥1 real row
              in ``facts.rows_by_track_subject`` — glob-tolerant, so
              ``"T1.gpio.i2s.*"`` is satisfied by any row under that prefix.
              When *every* cited gate returns zero matches *and* every
              cited track is entirely absent from ``rows_by_track_subject``,
              emit the distinct verdict ``no_source_facts_available``
              (WP7 Option B) — the skip cannot be audited against absent
              evidence and MUST NOT be conflated with the mixed-mismatch
              ``fail`` path or with the ``authority_out_of_scope`` advisory
              carve-out.
        (iii) At least one cited gate must be CLOSED in ``facts`` — with
              the §4.4 KNOWN_BAD carve-out (a ``PARTIAL_MATCH`` row whose
              ``rule_id`` is in ``KNOWN_BAD_PARTIAL_MATCH_RULES`` counts
              as closed).

Grep-based value-drift (Shape B in the future spec — checking that literals
inside ``bytes_`` reflect the actual row values) is DEFERRED. The
``ValueFlattener`` registry (see ``registry.py``) is the extension point;
no live consumer today.

Zero I/O, zero timestamps, zero env reads. Byte-identical input →
byte-identical ``PostVerificationResult``.

Import discipline (WP7):

  * MAY import: ``orchestrator.generation.model`` (WP1a — dataclasses),
    ``orchestrator.generation.config`` (WP1b — ``SKIP_REASONS``,
    ``ADVISORY_ROWS``, ``KNOWN_BAD_PARTIAL_MATCH_RULES``, and lazily
    ``_GENERATION_ARTIFACT_ORDER`` / ``GATING_ROWS`` at call time),
    ``orchestrator.reasoning.crossverify_model`` (``VerificationRow`` — the
    verdict/rule_id/warning fields are read here directly).
  * MUST NOT import: any generator lane (``dt_scaffolding.py``,
    ``codec_stub.py``, ``machine_driver.py``, ``audioreach_topology.py``) —
    the post-verifier is generator-agnostic; it audits ``GenerationResult``
    values, not the code that produced them.
  * Enforced by ``tests/test_generation_post_verify.py::test_import_guard``.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_post_verify``
"""

from __future__ import annotations

from orchestrator.generation.config import (
    ADVISORY_ROWS,
    KNOWN_BAD_PARTIAL_MATCH_RULES,
    SKIP_REASONS,
)
from orchestrator.generation.model import (
    GeneratedArtifact,
    GenerationResult,
    GeneratorSkipped,
    PostVerificationResult,
    PostVerificationRow,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Pattern-matching primitives ─────────────────────────────────────────────

def _subject_matches(pattern: str, subject: str) -> bool:
    """Return True iff ``subject`` matches ``pattern``.

    Shapes handled (mirror the ``GATING_ROWS`` docstring in config.py):

      * ``"*"``          — matches any subject under the track.
      * ``"prefix.*"``   — matches subjects starting with ``"prefix."``.
      * ``"literal"``    — exact match.
    """
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return subject.startswith(pattern[:-1])  # keep the trailing dot
    return subject == pattern


def _expand_pattern(
    facts: TrustedFacts,
    track: str,
    pattern: str,
) -> list[tuple[str, VerificationRow]]:
    """Return every ``(subject, row)`` in ``facts`` matching ``(track, pattern)``.

    Iterates ``rows_by_track_subject`` in sorted-key order so downstream
    ``details`` fields stay byte-stable across runs.
    """
    matches: list[tuple[str, VerificationRow]] = []
    key_prefix = f"{track}."
    for key in sorted(facts.rows_by_track_subject):
        if not key.startswith(key_prefix):
            continue
        subject = key[len(key_prefix):]
        if _subject_matches(pattern, subject):
            matches.append((subject, facts.rows_by_track_subject[key]))
    return matches


def _is_advisory(track: str, subject: str) -> bool:
    """Return True iff ``(track, subject)`` is registered as an advisory row.

    Advisory rows honor the §3.7 carve-out at post-verification time. As of
    spec v1.0 ``ADVISORY_ROWS`` = ``{("T4b", "*")}`` — every T4b subject.
    """
    for adv_track, adv_pattern in ADVISORY_ROWS:
        if adv_track != track:
            continue
        if _subject_matches(adv_pattern, subject):
            return True
    return False


# ── Row-verdict predicates ──────────────────────────────────────────────────

def _row_open_for_gate_consistency(
    row: VerificationRow,
    is_advisory: bool,
) -> bool:
    """Return True iff ``row`` opens its gate at post-verification time.

    Mirrors ``TrustedFacts.is_open`` (MATCH / PARTIAL_MATCH → open) and folds
    in the §3.7 advisory carve-out on advisory tracks:
    ``NOT_CROSS_CHECKABLE + authority_out_of_scope`` OR ``REVIEW_REQUIRED``
    opens the gate. The advisory carve-out is *the* mechanism that lets real
    Nord T4b rows (which land NCC+authority_out_of_scope with ``warning=True``
    because the authority is UNAVAILABLE) open the gate — so ``warning=True``
    must NOT unconditionally close it on advisory tracks. For non-advisory
    tracks, ``warning=True`` continues to close (§4 rule).
    """
    if is_advisory:
        if row.verdict == "NOT_CROSS_CHECKABLE":
            return row.coverage_gap_reason == "authority_out_of_scope"
        if row.verdict == "REVIEW_REQUIRED":
            return True
        if row.verdict in ("MATCH", "PARTIAL_MATCH"):
            return not row.warning
        return False
    if row.warning:
        return False
    if row.verdict in ("MATCH", "PARTIAL_MATCH"):
        return True
    return False


def _row_closed_for_skip_validity(row: VerificationRow) -> bool:
    """Return True iff ``row`` counts as CLOSED for skip validity (§4.4 fold-in).

    Closed if:
      * ``warning=True``, OR
      * verdict is ``REVIEW_REQUIRED`` / ``DISAGREE_WITH_AUTHORITY`` /
        ``NOT_CROSS_CHECKABLE``, OR
      * verdict is ``PARTIAL_MATCH`` AND ``rule_id`` is in
        ``KNOWN_BAD_PARTIAL_MATCH_RULES`` (§4.4 known-bad donor-residue).

    ``MATCH`` is never closed. Plain (non-known-bad) ``PARTIAL_MATCH`` is
    not closed here — the runner still lets it open (§4.4 carve-out is
    additive, not subtractive).
    """
    if row.warning:
        return True
    if row.verdict in (
        "REVIEW_REQUIRED",
        "DISAGREE_WITH_AUTHORITY",
        "NOT_CROSS_CHECKABLE",
    ):
        return True
    if (
        row.verdict == "PARTIAL_MATCH"
        and row.rule_id in KNOWN_BAD_PARTIAL_MATCH_RULES
    ):
        return True
    return False


# ── Per-result auditors ─────────────────────────────────────────────────────

def _verify_generated(
    art: GeneratedArtifact,
    facts: TrustedFacts,
    gating_rows: tuple[tuple[str, str], ...],
) -> PostVerificationRow:
    """Audit gate-consistency for one ``GeneratedArtifact``.

    For every ``(track, pattern)`` in the artifact's registered
    ``gating_rows``, expand the pattern against ``facts`` and require AT
    LEAST ONE matching row to be open (mirrors how the generators actually
    run their gates: a glob like ``gpio.i2s.*`` opens if at least one pin
    is present-and-MATCHed). Any gate where zero matching rows exist OR
    every matching row is closed is a consistency FAIL.
    """
    closed_gates: list[str] = []
    inspected: dict[str, list[str]] = {}

    for track, pattern in gating_rows:
        matches = _expand_pattern(facts, track, pattern)
        gate_key = f"{track}.{pattern}"
        inspected[gate_key] = sorted(f"{track}.{subject}" for subject, _ in matches)
        if not matches:
            closed_gates.append(gate_key)
            continue
        # Per-row advisory decision — one ADVISORY_ROWS entry ("T4b", "*")
        # covers every T4b subject in v1.0, but the shape is generic.
        any_open = any(
            _row_open_for_gate_consistency(row, _is_advisory(track, subject))
            for subject, row in matches
        )
        if not any_open:
            closed_gates.append(gate_key)

    if closed_gates:
        return PostVerificationRow(
            artifact_class=art.artifact_class,
            subject=art.subject,
            kind="gate_consistency",
            verdict="fail",
            message=(
                "gate-consistency: artifact emitted but the following gating "
                f"rows are CLOSED in source facts: {sorted(closed_gates)}"
            ),
            details={
                "closed_gates": sorted(closed_gates),
                "inspected_rows": inspected,
            },
        )

    return PostVerificationRow(
        artifact_class=art.artifact_class,
        subject=art.subject,
        kind="gate_consistency",
        verdict="pass",
        message="gate-consistency: every registered gating row opens in source facts.",
        details={"inspected_rows": inspected},
    )


def _parse_cited_gate(cited: str) -> tuple[str, str]:
    """Split a cited gate ``"<track>.<subject_pattern>"`` into ``(track, pattern)``.

    ``GeneratorSkipped.gating_rows`` items are dotted strings like
    ``"T5.dts.firmware"`` or ``"T1.gpio.i2s.*"``. Track is the first
    dot-separated segment; everything after is the pattern.
    """
    head, _, tail = cited.partition(".")
    return (head, tail)


def _verify_skipped(
    skipped: GeneratorSkipped,
    facts: TrustedFacts,
) -> PostVerificationRow:
    """Audit skip-validity for one ``GeneratorSkipped``.

    Three checks in order (first failure wins so the ``message`` is precise):

      (i)   ``reason`` ∈ ``SKIP_REASONS``.
      (ii)  Every cited ``gating_rows`` entry resolves to ≥1 real row in
            ``facts`` (glob-tolerant).
      (iii) At least one cited row is CLOSED in ``facts`` (with §4.4
            KNOWN_BAD fold-in).
    """
    # (i) reason validity — the closed enumeration lives in
    # ``config.SKIP_REASONS``; anything outside it is a policy violation.
    if skipped.reason not in SKIP_REASONS:
        return PostVerificationRow(
            artifact_class=skipped.artifact_class,
            subject=skipped.subject,
            kind="skip_validity",
            verdict="fail",
            message=(
                f"skip-validity: reason {skipped.reason!r} is not a "
                "registered SkipReason."
            ),
            details={"reason": skipped.reason},
        )

    # (ii) + (iii) expand each cited gate and track match / closed status.
    unknown_gates: list[str] = []
    closed_gates: list[str] = []
    inspected: dict[str, list[str]] = {}
    for cited in skipped.gating_rows:
        track, pattern = _parse_cited_gate(cited)
        matches = _expand_pattern(facts, track, pattern)
        inspected[cited] = sorted(f"{track}.{subject}" for subject, _ in matches)
        if not matches:
            unknown_gates.append(cited)
            continue
        if any(_row_closed_for_skip_validity(row) for _, row in matches):
            closed_gates.append(cited)

    if unknown_gates:
        # Option B (WP7 evidence-first): distinguish "no source facts for
        # the cited tracks at all" from "some rows exist but don't cover
        # these specific gates". The former is a symptom of a target with
        # no crossverify evidence (Nord: no topology.pinmux, no DTS pins);
        # the latter is a real citation mismatch. Advisory carve-outs
        # (T4b NCC + authority_out_of_scope) remain a separate `fail`
        # path — they exist as rows in facts, just closed in a specific
        # way — and MUST NOT be conflated with either verdict here.
        cited_tracks = {
            _parse_cited_gate(cited)[0] for cited in skipped.gating_rows
        }
        tracks_with_no_rows = {
            track for track in cited_tracks
            if not any(
                key.startswith(f"{track}.")
                for key in facts.rows_by_track_subject
            )
        }
        if len(unknown_gates) == len(skipped.gating_rows) and tracks_with_no_rows == cited_tracks:
            return PostVerificationRow(
                artifact_class=skipped.artifact_class,
                subject=skipped.subject,
                kind="skip_validity",
                verdict="no_source_facts_available",
                message=(
                    "skip-validity: no source facts available for cited "
                    f"tracks {sorted(cited_tracks)} — this run has zero "
                    "crossverify rows under any of them. Skip verdict "
                    "cannot be audited against absent evidence; not a "
                    "citation mismatch. Preserved as distinct from "
                    "authority_out_of_scope."
                ),
                details={
                    "reason": skipped.reason,
                    "cited_tracks": sorted(cited_tracks),
                    "tracks_with_no_rows": sorted(tracks_with_no_rows),
                    "inspected_rows": inspected,
                },
            )
        return PostVerificationRow(
            artifact_class=skipped.artifact_class,
            subject=skipped.subject,
            kind="skip_validity",
            verdict="fail",
            message=(
                "skip-validity: cited gating rows have no matching entries "
                f"in source facts: {sorted(unknown_gates)}"
            ),
            details={
                "reason": skipped.reason,
                "unknown_gates": sorted(unknown_gates),
                "inspected_rows": inspected,
            },
        )

    if not closed_gates:
        return PostVerificationRow(
            artifact_class=skipped.artifact_class,
            subject=skipped.subject,
            kind="skip_validity",
            verdict="fail",
            message=(
                "skip-validity: skip verdict emitted but every cited gate "
                "is OPEN in source facts (with §4.4 KNOWN_BAD fold-in)."
            ),
            details={
                "reason": skipped.reason,
                "inspected_rows": inspected,
            },
        )

    return PostVerificationRow(
        artifact_class=skipped.artifact_class,
        subject=skipped.subject,
        kind="skip_validity",
        verdict="pass",
        message=(
            f"skip-validity: reason={skipped.reason!r} valid; "
            "≥1 cited gate closed in source facts."
        ),
        details={
            "reason": skipped.reason,
            "closed_gates": sorted(closed_gates),
            "inspected_rows": inspected,
        },
    )


# ── Public entry point ──────────────────────────────────────────────────────

def verify_generation_result(
    results: list[GenerationResult],
    facts: TrustedFacts,
) -> PostVerificationResult:
    """Audit a list of ``GenerationResult`` values against ``TrustedFacts``.

    Iterates ``results`` in canonical ``_GENERATION_ARTIFACT_ORDER``,
    producing one ``PostVerificationRow`` per input result (any
    artifact_class not present in ``results`` is silently skipped — the
    verifier audits what it is given; completeness is the runner's
    concern).

    Overall ``verdict`` is ``"pass"`` iff every emitted row's verdict is
    ``"pass"``. Rows with the distinct WP7 verdict
    ``"no_source_facts_available"`` are NOT ``"pass"`` — the overall
    result stays ``"fail"``. This preserves evidence-first semantics:
    a run with no source facts to audit against is honestly blocked,
    not silently promoted. Empty ``results`` yields ``verdict="pass"``
    with an empty ``rows`` list — a nothing-to-audit outcome is not a
    failure.

    The lazy config attributes (``_GENERATION_ARTIFACT_ORDER``,
    ``GATING_ROWS``) are imported here at call time rather than at module
    top so that the WP7 registry cycle contract (config → registry →
    lazily-imported generators) is preserved.
    """
    from orchestrator.generation.config import (
        _GENERATION_ARTIFACT_ORDER,
        GATING_ROWS,
    )

    results_by_class: dict[str, GenerationResult] = {
        result.artifact_class: result for result in results
    }

    rows: list[PostVerificationRow] = []
    for artifact_class in _GENERATION_ARTIFACT_ORDER:
        if artifact_class not in results_by_class:
            continue
        result = results_by_class[artifact_class]
        if isinstance(result, GeneratedArtifact):
            rows.append(_verify_generated(
                result,
                facts,
                GATING_ROWS[artifact_class],
            ))
        else:
            rows.append(_verify_skipped(result, facts))

    overall = "pass" if all(row.verdict == "pass" for row in rows) else "fail"
    return PostVerificationResult(verdict=overall, rows=rows)


__all__ = ["verify_generation_result"]
