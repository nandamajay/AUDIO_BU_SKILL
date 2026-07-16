"""Phase-2B WP7 — tests for the post-generation fan-in trust verifier.

Pure, stdlib-only tests over ``orchestrator.generation.post_verify``. Mirrors
the WP3-WP6 test discipline: inline data, no fakes, no network, no pytest.

Seven tests per PHASE2B_SPECIFICATION.md §WP7 (post-generation trust
verifier), locked answer A1 (gate-consistency + skip-validity, NOT
grep-based value-drift):

  1. ``test_happy_path_all_pass`` — one GeneratedArtifact + one
     GeneratorSkipped, both trust-verify to ``pass``.
  2. ``test_gate_consistency_fail_when_required_row_closed`` — a
     GeneratedArtifact claiming an artifact class whose gating row lands
     CLOSED in TrustedFacts must fail the fan-in check with
     ``kind == "gate_consistency"`` and ``verdict == "fail"``.
  3. ``test_gate_consistency_t4b_advisory_open_honored`` — §3.7 advisory
     carve-out: NCC + authority_out_of_scope on ``T4b.*`` counts as OPEN for
     gate-consistency (matches the codec_stub production reality).
  4. ``test_skip_validity_fail_when_reason_not_registered`` — a
     GeneratorSkipped with a reason string that isn't in ``SKIP_REASONS``
     must fail skip-validity. This is the "typo in the reason literal"
     guard.
  5. ``test_skip_validity_fail_when_cited_gate_expands_to_zero_rows`` — a
     GeneratorSkipped citing ``T4a.qup.*`` whose glob matches nothing in
     ``rows_by_track_subject`` must fail (§4.4: the cited gate must resolve
     to at least one real row).
  6. ``test_skip_validity_pass_when_known_bad_partial_match_closes_gate`` —
     a T5 PARTIAL_MATCH row whose ``rule_id`` is in
     ``KNOWN_BAD_PARTIAL_MATCH_RULES`` counts as CLOSED for skip validity.
     This is the WP1a "T5 known-bad residue" carve-out preserved in WP7.
  7. ``test_import_guard`` — AST check: ``post_verify.py`` must not import
     any Phase-2A module beyond ``crossverify_model``, and must not import
     from ``orchestrator.generation.facts``.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_post_verify``
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.generation import post_verify as post_verify_module
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.generation.post_verify import verify_generation_result
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Helper builders ─────────────────────────────────────────────────────────


def _row(
    track: str,
    subject: str,
    verdict: str,
    *,
    rule_id: str | None = None,
    warning: bool | None = None,
    coverage_gap_reason: str | None = None,
    authority_strength: str = "IPCAT_DIRECT",
    authority_origin: str = "ipcat.test",
    authority_value: object | None = None,
) -> VerificationRow:
    """Build a minimal ``VerificationRow`` matching the Phase-2A shape."""
    authority = {"strength": authority_strength, "origin": authority_origin}
    if authority_value is not None:
        authority["value"] = authority_value
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        authority=authority,
        confidence="high" if verdict == "MATCH" else "medium",
        coverage_gap_reason=coverage_gap_reason,
        rule_id=rule_id,
        warning=warning,
    )


def _artifact(
    artifact_class: str,
    *,
    path_hint: str | None = None,
    bytes_: bytes = b"// stub\n",
    contributes_rows: list[VerificationRow] | None = None,
) -> GeneratedArtifact:
    """Build a minimal ``GeneratedArtifact``. subject == artifact_class per WP1b."""
    return GeneratedArtifact(
        subject=artifact_class,
        artifact_class=artifact_class,
        path_hint=path_hint or f"generated/{artifact_class}/stub.out",
        bytes_=bytes_,
        contributes_rows=contributes_rows or [],
    )


def _skipped(
    artifact_class: str,
    reason: str,
    gating_rows: list[str],
) -> GeneratorSkipped:
    """Build a minimal ``GeneratorSkipped``. subject == artifact_class per WP1b."""
    return GeneratorSkipped(
        subject=artifact_class,
        artifact_class=artifact_class,
        reason=reason,
        gating_rows=gating_rows,
    )


# ── 1. Happy path: all-pass ─────────────────────────────────────────────────


def test_happy_path_all_pass() -> None:
    """A GeneratedArtifact with open gates + a GeneratorSkipped with a valid
    reason + a properly-closed gate both trust-verify to ``pass``.

    Covers the primary WP7 happy path: two rows in the fan-in result, both
    ``verdict == "pass"``, and the aggregate ``PostVerificationResult.verdict``
    is ``"pass"``.
    """
    rows_by_key = {
        # codec_stub gates: T4a.qup.* + T4b (advisory)
        "T4a.qup.se3": _row("T4a", "qup.se3", "MATCH"),
        "T4b.codec.adau1979": _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
        ),
        # machine_driver gates include T2.soundwire_master — DISAGREE closes it
        "T2.soundwire_master": _row(
            "T2",
            "soundwire_master",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    codec_artifact = _artifact("codec_stub", path_hint="generated/codec_stub/stub.c")
    machine_skipped = _skipped(
        "machine_driver",
        reason="gating_row_disagree_on_bus",
        gating_rows=["T2.soundwire_master"],
    )

    result = verify_generation_result([codec_artifact, machine_skipped], facts)

    assert result.verdict == "pass", (
        f"expected aggregate verdict 'pass', got {result.verdict!r}; "
        f"rows={[(r.artifact_class, r.kind, r.verdict, r.message) for r in result.rows]}"
    )
    assert len(result.rows) == 2, (
        f"expected 2 fan-in rows (one per result), got {len(result.rows)}: {result.rows!r}"
    )
    for row in result.rows:
        assert row.verdict == "pass", (
            f"row {row.artifact_class}/{row.kind} not pass: {row.message!r}"
        )
    # Kinds: one gate_consistency (codec), one skip_validity (machine).
    kinds = {(r.artifact_class, r.kind) for r in result.rows}
    assert kinds == {
        ("codec_stub", "gate_consistency"),
        ("machine_driver", "skip_validity"),
    }, f"kind/artifact_class drift: {kinds!r}"
    print("PASS: happy path — 2 results, both fan-in rows pass, aggregate pass")


# ── 2. Gate-consistency FAIL when required row closed ───────────────────────


def test_gate_consistency_fail_when_required_row_closed() -> None:
    """A GeneratedArtifact whose gating row is CLOSED in TrustedFacts fails.

    The bug this catches: a generator hits an internal short-circuit and
    emits an artifact against inputs the fan-in verifier would reject.
    Here the codec_stub's T4a.qup gate lands DISAGREE_WITH_AUTHORITY —
    the generator was supposed to skip, but somehow emitted an artifact
    anyway. WP7 catches it at the fan-in.
    """
    rows_by_key = {
        # T4a gate lands closed — DISAGREE.
        "T4a.qup.se3": _row(
            "T4a",
            "qup.se3",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    codec_artifact = _artifact("codec_stub")
    result = verify_generation_result([codec_artifact], facts)

    assert result.verdict == "fail", (
        f"expected aggregate verdict 'fail' when required T4a gate is closed, "
        f"got {result.verdict!r}"
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.artifact_class == "codec_stub"
    assert row.kind == "gate_consistency"
    assert row.verdict == "fail"
    assert "T4a" in row.message or "qup" in row.message.lower(), (
        f"failure message must reference the closed gate; got: {row.message!r}"
    )
    print(
        "PASS: gate-consistency FAIL when required row is closed "
        "(codec_stub emitted against DISAGREE T4a.qup.se3)"
    )


# ── 3. §3.7 advisory carve-out: T4b NCC+authority_out_of_scope opens gate ──


def test_gate_consistency_t4b_advisory_open_honored() -> None:
    """T4b NCC + authority_out_of_scope must be treated as OPEN by fan-in.

    This is production reality for Nord: both T4b codec rows land NCC +
    authority_out_of_scope, and WP4 (codec_stub) emits against them via
    the §3.7 advisory carve-out. WP7 must honor the same rule — otherwise
    every real Nord run fails fan-in and the artifact is quarantined.
    """
    rows_by_key = {
        "T4a.qup.se3": _row("T4a", "qup.se3", "MATCH"),
        "T4b.codec.adau1979": _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
        ),
        "T4b.codec.pcm1681": _row(
            "T4b",
            "codec.pcm1681",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    codec_artifact = _artifact("codec_stub")
    result = verify_generation_result([codec_artifact], facts)

    assert result.verdict == "pass", (
        f"advisory carve-out drift: expected 'pass' when T4b rows are "
        f"NCC+authority_out_of_scope (§3.7), got {result.verdict!r}; "
        f"message: {result.rows[0].message!r}"
    )
    assert result.rows[0].kind == "gate_consistency"
    assert result.rows[0].verdict == "pass"
    print("PASS: §3.7 advisory carve-out honored (T4b NCC+authority_out_of_scope opens gate)")


# ── 4. Skip-validity FAIL when reason not registered ────────────────────────


def test_skip_validity_fail_when_reason_not_registered() -> None:
    """A GeneratorSkipped with a reason not in SKIP_REASONS must fail.

    Catches "typo in the reason literal" — a bug where a generator claims
    to skip for a reason the registry has never heard of. The reason must
    be one of the eleven config-registered SkipReason values.
    """
    rows_by_key = {
        "T2.soundwire_master": _row(
            "T2",
            "soundwire_master",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    bogus = _skipped(
        "machine_driver",
        reason="gating_row_disagree_on_typo",  # not registered
        gating_rows=["T2.soundwire_master"],
    )
    result = verify_generation_result([bogus], facts)

    assert result.verdict == "fail", (
        f"expected 'fail' for unregistered skip reason, got {result.verdict!r}"
    )
    row = result.rows[0]
    assert row.kind == "skip_validity"
    assert row.verdict == "fail"
    assert "gating_row_disagree_on_typo" in row.message, (
        f"failure message must name the unregistered reason; got: {row.message!r}"
    )
    print("PASS: skip-validity FAIL when reason not in SKIP_REASONS")


# ── 5. Skip-validity FAIL when cited gate expands to zero rows ──────────────


def test_skip_validity_fail_when_cited_gate_expands_to_zero_rows() -> None:
    """A GeneratorSkipped citing a gate that matches no real rows fails.

    Catches "fabricated citation" — a generator claims to skip because of
    a gate that isn't even in the projection. §4.4: every cited gate must
    resolve (via glob or literal match) to at least one row in
    ``rows_by_track_subject``.
    """
    facts = TrustedFacts(rows_by_track_subject={})  # projection is empty

    skipped = _skipped(
        "codec_stub",
        reason="authority_not_in_snapshot",
        gating_rows=["T4a.qup.*"],  # glob that matches nothing
    )
    result = verify_generation_result([skipped], facts)

    assert result.verdict == "fail", (
        f"expected 'fail' when cited gate matches zero rows, got {result.verdict!r}"
    )
    row = result.rows[0]
    assert row.kind == "skip_validity"
    assert row.verdict == "fail"
    assert "T4a.qup" in row.message, (
        f"failure message must name the unresolved gate; got: {row.message!r}"
    )
    print("PASS: skip-validity FAIL when cited gate expands to zero rows")


# ── 6. Skip-validity PASS when KNOWN_BAD PARTIAL_MATCH counts as closed ─────


def test_skip_validity_pass_when_known_bad_partial_match_closes_gate() -> None:
    """A known-bad PARTIAL_MATCH row counts as CLOSED for skip validity.

    Preserves the WP1a §4.4 T5 known-bad carve-out: PARTIAL_MATCH rows
    whose ``rule_id`` is in ``KNOWN_BAD_PARTIAL_MATCH_RULES`` are treated
    as closed (they represent authority-flagged bad-data conditions), so a
    generator that skips citing such a row is skipping validly.
    """
    rows_by_key = {
        "T5.donor.firmware.sa8775p": _row(
            "T5",
            "donor.firmware.sa8775p",
            "PARTIAL_MATCH",
            rule_id="t5.donor.firmware.sa8775p",  # in KNOWN_BAD_PARTIAL_MATCH_RULES
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    skipped = _skipped(
        "dt_scaffolding",
        reason="gating_row_partial_match_donor_residue",
        gating_rows=["T5.donor.firmware.sa8775p"],
    )
    result = verify_generation_result([skipped], facts)

    assert result.verdict == "pass", (
        f"expected 'pass' — KNOWN_BAD PARTIAL_MATCH must count as closed for "
        f"skip validity, got {result.verdict!r}; message: {result.rows[0].message!r}"
    )
    row = result.rows[0]
    assert row.kind == "skip_validity"
    assert row.verdict == "pass"
    print("PASS: skip-validity PASS when KNOWN_BAD PARTIAL_MATCH counts as closed")


# ── 7. Import guard ─────────────────────────────────────────────────────────


def test_import_guard() -> None:
    """AST-based check: post_verify.py must not import forbidden modules.

    Forbidden modules (per §WP7 import discipline):

      * ``orchestrator.generation.facts`` — post_verify consumes TrustedFacts,
        never composes them.
      * ``orchestrator.reasoning.crossverify`` — Phase-2A verifier internals.
      * ``orchestrator.reasoning.cardinality`` — Phase-2A cardinality track.
      * Any generator module — post_verify inspects results, never invokes
        generators.

    The ONLY Phase-2A module post_verify is allowed to touch is
    ``orchestrator.reasoning.crossverify_model`` (for the ``VerificationRow``
    type). This is the WP7-locked "no reasoning-layer coupling" rule.
    """
    src_path = Path(inspect.getfile(post_verify_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden = {
        "orchestrator.generation.facts",
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
        "orchestrator.generation.dt_scaffolding",
        "orchestrator.generation.codec_stub",
        "orchestrator.generation.machine_driver",
        "orchestrator.generation.audioreach_topology",
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in forbidden:
                offenders.append(f"from {module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden:
                    offenders.append(f"import {alias.name}")
    assert not offenders, (
        f"WP7 import-guard failed: post_verify.py must not import forbidden "
        f"modules {sorted(forbidden)!r}. Offenders: {offenders!r}"
    )

    # Positive sanity: the module DOES import from the allowed set.
    allowed_hits: dict[str, bool] = {
        "orchestrator.generation.config": False,
        "orchestrator.generation.model": False,
        "orchestrator.reasoning.crossverify_model": False,
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in allowed_hits:
                allowed_hits[module] = True
    missing_allowed = [k for k, hit in allowed_hits.items() if not hit]
    assert not missing_allowed, (
        f"sanity: post_verify.py is expected to import from {list(allowed_hits)!r}, "
        f"missing: {missing_allowed!r}"
    )
    print(
        f"PASS: post_verify.py import guard held "
        f"(forbidden={sorted(forbidden)}, all three allowed modules imported)"
    )


def main() -> None:
    test_happy_path_all_pass()                                      # 1
    test_gate_consistency_fail_when_required_row_closed()           # 2
    test_gate_consistency_t4b_advisory_open_honored()               # 3
    test_skip_validity_fail_when_reason_not_registered()            # 4
    test_skip_validity_fail_when_cited_gate_expands_to_zero_rows()  # 5
    test_skip_validity_pass_when_known_bad_partial_match_closes_gate()  # 6
    test_import_guard()                                             # 7
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
