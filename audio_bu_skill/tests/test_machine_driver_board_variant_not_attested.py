"""WP-69 — machine_driver board_variant NOT_ATTESTED disclosure tests.

Six focused tests around the WP-69 change (see
``docs/WP_69_BOARD_VARIANT_AUTHORITY.md`` §10):

  1. ``test_model_line_emits_fixme_literal`` — emitted DTSI contains the
     verbatim ``model = "FIXME(board_variant): NOT_ATTESTED";`` line and does
     NOT contain either candidate board-variant string ``IQ10-EVK`` or
     ``IQ10-RRD`` on the emit side.
  2. ``test_contributes_rows_carries_board_variant_disclosure`` — exactly one
     ``contributes_rows`` entry has
     ``subject="sound_card.model.board_variant"``,
     ``verdict="NOT_CROSS_CHECKABLE"``,
     ``coverage_gap_reason="authority_out_of_scope"``.
  3. ``test_disclosure_notes_enumerate_candidates_and_evidence`` — each of the
     five load-bearing note lines (scope statement, NOT_ATTESTED tag, candidate
     enumeration, evidence-path pointer, follow-up authority track pointer) is
     present verbatim.
  4. ``test_disclosure_row_authority_is_absent_or_empty`` — the NOT_CROSS_CHECKABLE
     row carries no ``authority`` value (``authority is None``): a disclosure
     row never carries an authority tuple.
  5. ``test_generator_does_not_gate_on_board_variant`` — a Facts bundle whose
     rows do NOT include the ``sound_card.model.board_variant`` subject still
     produces a ``GeneratedArtifact`` (the disclosure is emit-side, not a gate:
     the subject is NOT in ``_GATING_ROW_NAMES``).
  6. ``test_provenance_guard_clean_in_machine_driver`` — the candidate-commit
     short-hash ``5267b2e1`` never appears in an authority-carrying string
     literal in ``machine_driver.py``. It MAY appear in disclosure ``notes=``
     prose citations (that is the intended pattern — descriptive, not
     authority-authoring); the guard is scoped to authority context.

Run: ``PYTHONPATH=audio_bu_skill python3 -m pytest
audio_bu_skill/tests/test_machine_driver_board_variant_not_attested.py -v``

Zero I/O, zero timestamps, stdlib only.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.generation import machine_driver as machine_module
from orchestrator.generation.facts import project_facts
from orchestrator.generation.machine_driver import (
    _BOARD_VARIANT_CONTRIB_SUBJECT,
    _GATING_ROW_NAMES,
    _MODEL_FIXME_LITERAL,
    generate_machine_driver,
)
from orchestrator.generation.model import (
    GeneratedArtifact,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Shared helper: minimal clean-Nord Facts that opens all four gates ───────


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
) -> VerificationRow:
    """Build a ``VerificationRow`` with the WP2-shaped authority dict.

    Mirrors ``tests/test_generation_machine.py::_row`` — the same shape the
    real cross-verifier emits. The authority is a dict
    ``{"strength": ..., "origin": ...}``; ``None`` is normalized by
    ``VerificationRow.__post_init__`` to
    ``{"strength": "UNAVAILABLE", "origin": "none"}``.
    """
    authority = {"strength": authority_strength, "origin": authority_origin}
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


def _clean_nord_facts() -> TrustedFacts:
    """Build a synthetic clean-Nord Facts bundle that opens all four gates.

    Mirrors ``tests/test_generation_machine.py::_clean_nord_facts`` exactly:
    T1 pin MATCH, T4a QUP MATCH, T4b codec advisory-open x2
    (``NOT_CROSS_CHECKABLE`` + ``authority_out_of_scope``), T2
    ``soundwire_master`` MATCH. This projection opens all four gates in
    ``machine_driver.is_open``. Re-authored here so this test file is
    self-contained (WP-69 §10 acceptance).
    """
    rows = [
        _row("T1", "gpio.i2s.mclk", "MATCH"),
        _row("T4a", "qup.se3", "MATCH"),
        _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        _row(
            "T4b",
            "codec.pcm1681",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        _row("T2", "soundwire_master", "MATCH"),
    ]
    return project_facts(rows)


# ── 1. Emit line: verbatim FIXME literal, no candidate name on emit side ────


def test_model_line_emits_fixme_literal() -> None:
    """Emitted DTSI must carry the verbatim FIXME literal + no candidate names.

    Guards decision A (WP-69): the ``model =`` property is a machine-parseable
    ``FIXME(board_variant): NOT_ATTESTED`` literal. Neither of the two
    board-variant candidates (IQ10-EVK, IQ10-RRD) may appear anywhere in the
    emit bytes.
    """
    facts = _clean_nord_facts()
    result = generate_machine_driver(facts)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact, got {type(result).__name__}: {result!r}"
    )
    text = result.bytes_.decode("utf-8")

    expected_line = 'model = "FIXME(board_variant): NOT_ATTESTED";'
    assert expected_line in text, (
        f"expected verbatim FIXME emit line {expected_line!r} not in bytes "
        f"(first 400): {text[:400]!r}"
    )
    assert "IQ10-EVK" not in text, (
        f"candidate variant 'IQ10-EVK' leaked into emit bytes: {text!r}"
    )
    assert "IQ10-RRD" not in text, (
        f"candidate variant 'IQ10-RRD' leaked into emit bytes: {text!r}"
    )
    print("PASS: model line emits verbatim FIXME literal, no candidate leak")


# ── 2. contributes_rows carries exactly one board_variant disclosure row ────


def test_contributes_rows_carries_board_variant_disclosure() -> None:
    """Exactly one ``sound_card.model.board_variant`` row with the WP-69 shape.

    Row must be:
    * track T5
    * subject sound_card.model.board_variant
    * verdict NOT_CROSS_CHECKABLE
    * coverage_gap_reason authority_out_of_scope
    """
    facts = _clean_nord_facts()
    result = generate_machine_driver(facts)
    assert isinstance(result, GeneratedArtifact)

    matches = [
        r for r in result.contributes_rows if r.subject == _BOARD_VARIANT_CONTRIB_SUBJECT
    ]
    assert len(matches) == 1, (
        f"expected exactly one row with subject "
        f"{_BOARD_VARIANT_CONTRIB_SUBJECT!r}; got {len(matches)}: {matches!r}"
    )
    row = matches[0]
    assert row.track == "T5", f"track drift: {row.track!r}"
    assert row.subject == "sound_card.model.board_variant"
    assert row.verdict == "NOT_CROSS_CHECKABLE", f"verdict drift: {row.verdict!r}"
    assert row.coverage_gap_reason == "authority_out_of_scope", (
        f"coverage_gap_reason drift: {row.coverage_gap_reason!r}"
    )
    print("PASS: contributes_rows carries the WP-69 board_variant disclosure row")


# ── 3. Notes enumerate scope, NOT_ATTESTED, candidates, evidence, follow-up ─


def test_disclosure_notes_enumerate_candidates_and_evidence() -> None:
    """Each of the five load-bearing note phrases is present verbatim.

    Reviewer needs to see:
      * scope statement (``SCOPE: board-variant name``)
      * NOT_ATTESTED tag with reviewer_required=true
      * both candidate names (IQ10-EVK, IQ10-RRD) mentioned in prose
      * pointer to the schematic evidence path
      * pointer to the follow-up authority track / WP_H-1
    """
    facts = _clean_nord_facts()
    result = generate_machine_driver(facts)
    assert isinstance(result, GeneratedArtifact)

    matches = [
        r for r in result.contributes_rows if r.subject == _BOARD_VARIANT_CONTRIB_SUBJECT
    ]
    assert len(matches) == 1
    joined_notes = "\n".join(matches[0].notes)

    required_substrings = [
        "SCOPE: board-variant name",
        "NOT_ATTESTED: board_variant. reviewer_required=true.",
        "IQ10-EVK",
        "IQ10-RRD",
        "audio_bu_skill/targets/nord-iq10/evidence/offline/",
        "candidate DTS at commit 5267b2e1d7a5",
        "WP_H-1_AUDIO_HARDWARE_TEMPLATE_PROJECTOR",
    ]
    for needle in required_substrings:
        assert needle in joined_notes, (
            f"required note substring not found: {needle!r}. "
            f"notes:\n{joined_notes}"
        )
    print("PASS: disclosure notes enumerate scope, candidates, evidence, follow-up")


# ── 4. Disclosure row has no authority (authority is None) ──────────────────


def test_disclosure_row_authority_is_absent_or_empty() -> None:
    """The NOT_CROSS_CHECKABLE disclosure row must carry no live authority.

    ``VerificationRow.__post_init__`` normalizes an absent ``authority=``
    kwarg to ``{"strength": "UNAVAILABLE", "origin": "none"}``. That
    normalized-absent shape is the canonical "no authority attests this
    fact" state — the WP-69 disclosure must land there. In particular:

    * ``authority["strength"] == "UNAVAILABLE"`` (never IPCAT_DIRECT /
      IPCAT_DERIVED / KB_RULE).
    * ``authority`` does not carry a ``value`` key (no candidate value has
      been promoted into the authority slot).
    """
    facts = _clean_nord_facts()
    result = generate_machine_driver(facts)
    assert isinstance(result, GeneratedArtifact)
    matches = [
        r for r in result.contributes_rows if r.subject == _BOARD_VARIANT_CONTRIB_SUBJECT
    ]
    assert len(matches) == 1
    row = matches[0]
    assert isinstance(row.authority, dict), (
        f"authority must be a dict after normalization; got "
        f"{type(row.authority).__name__}: {row.authority!r}"
    )
    assert row.authority.get("strength") == "UNAVAILABLE", (
        f"disclosure row must have authority.strength=='UNAVAILABLE'; got "
        f"{row.authority!r}"
    )
    assert "value" not in row.authority, (
        f"disclosure row must not carry an authority.value; got "
        f"{row.authority!r}"
    )
    print("PASS: disclosure row carries no live authority (strength=UNAVAILABLE)")


# ── 5. board_variant subject is NOT a gate (regression: not in tuple) ───────


def test_generator_does_not_gate_on_board_variant() -> None:
    """The board_variant disclosure is emit-side only; must not be a gate.

    Two-part assertion:
    * ``_GATING_ROW_NAMES`` MUST NOT include ``sound_card.model.board_variant``.
    * A Facts bundle whose rows do not carry a ``sound_card.model.board_variant``
      subject still opens all four gates and produces a ``GeneratedArtifact``.
    """
    for name in _GATING_ROW_NAMES:
        assert "board_variant" not in name, (
            f"WP-69 disclosure subject leaked into gating tuple: {name!r}"
        )

    facts = _clean_nord_facts()
    row_keys = list(facts.rows_by_track_subject)
    assert not any(
        "board_variant" in k for k in row_keys
    ), "clean-Nord facts already carry a board_variant row; regression fixture broken"

    result = generate_machine_driver(facts)
    assert isinstance(result, GeneratedArtifact), (
        f"absence of a board_variant row must NOT close a gate; got "
        f"{type(result).__name__}: {result!r}"
    )
    print("PASS: board_variant is disclosure-only, not a gate")


# ── 6. Provenance guard: `5267b2e1` is not in an authority-carrying literal ─


def test_provenance_guard_clean_in_machine_driver() -> None:
    """Candidate commit short-hash must not appear in authority-carrying code.

    Guard implementation (AST-based, deliberately narrow):

    * Walk every ``ast.Constant`` string node in machine_driver.py.
    * For each hit of ``5267b2e1``, walk up to the enclosing statement. The
      hit is ONLY allowed if it lives inside a ``notes=`` keyword-argument
      list on a ``VerificationRow(...)`` call (i.e. a disclosure prose
      citation). Any other appearance — bare ``authority=`` tuple, string
      catalog, docstring line asserting a MATCH — fails the guard.

    Docstring-scope hits are allowed (they annotate policy).
    """
    src_path = Path(inspect.getsourcefile(machine_module))  # type: ignore[arg-type]
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Locate every string constant containing the candidate hash outside of
    # module/function docstrings and disclosure-notes contexts.
    violations: list[tuple[int, str]] = []

    def _is_disclosure_notes_context(node: ast.Constant, parents: list[ast.AST]) -> bool:
        # Walk back through the parent chain looking for either:
        #   * `notes=[..., "…5267b2e1…", ...]` inside a VerificationRow(...) call
        for ancestor in reversed(parents):
            if isinstance(ancestor, ast.keyword) and ancestor.arg == "notes":
                return True
            if isinstance(ancestor, ast.Call):
                fn = ancestor.func
                fn_name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if fn_name == "VerificationRow":
                    # Reached the call boundary without seeing notes= — not disclosure.
                    return False
        return False

    def _is_docstring(node: ast.Constant, parents: list[ast.AST]) -> bool:
        # A module/function/class docstring is the first Expr in that body.
        if len(parents) < 2:
            return False
        expr = parents[-1]
        body_owner = parents[-2]
        if not isinstance(expr, ast.Expr) or expr.value is not node:
            return False
        body = getattr(body_owner, "body", None)
        return isinstance(body, list) and bool(body) and body[0] is expr

    parent_stack: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        parent_stack.append(node)
        try:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "5267b2e1" in node.value:
                    if _is_docstring(node, parent_stack[:-1]):
                        return
                    if _is_disclosure_notes_context(node, parent_stack[:-1]):
                        return
                    violations.append((node.lineno, node.value[:120]))
            for child in ast.iter_child_nodes(node):
                visit(child)
        finally:
            parent_stack.pop()

    visit(tree)
    assert not violations, (
        f"provenance guard: `5267b2e1` appeared in authority context inside "
        f"machine_driver.py at (line, snippet): {violations!r}"
    )
    print("PASS: no `5267b2e1` in authority-carrying literals in machine_driver.py")


if __name__ == "__main__":
    # stdlib-only entry point — matches the WP5 test style.
    test_model_line_emits_fixme_literal()
    test_contributes_rows_carries_board_variant_disclosure()
    test_disclosure_notes_enumerate_candidates_and_evidence()
    test_disclosure_row_authority_is_absent_or_empty()
    test_generator_does_not_gate_on_board_variant()
    test_provenance_guard_clean_in_machine_driver()
    print("PASS: all 6 WP-69 board_variant NOT_ATTESTED tests")
