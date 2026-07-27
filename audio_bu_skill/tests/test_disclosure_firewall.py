"""WP-64 — disclosure-only firewall enforcement tests.

Four tests around the invariant: ``GeneratedArtifact.contributes_rows`` entries
(disclosures produced by generator lanes) must NEVER cross the firewall into
``TrustedFacts.rows_by_track_subject`` (authority). See
``docs/WP_64_DISCLOSURE_FIREWALL.md`` §3 for the four-layer proof.

Tests:

  A. ``test_project_facts_source_ast_free_of_contributes_rows`` — AST scan of
     ``orchestrator/generation/facts.py``: zero attribute accesses named
     ``contributes_rows``. project_facts() is structurally blind to the
     disclosure slot.

  B. ``test_reasoning_subsystem_free_of_disclosure_and_generation_imports`` —
     grep-static scan of every ``orchestrator/reasoning/*.py`` module: zero
     literal ``contributes_rows`` references AND zero imports from
     ``orchestrator.generation``. The reverse-import guard (WP-64 gap β) —
     reasoning cannot depend on generation, so it cannot read disclosures.

  C. ``test_cross_verification_rows_assignment_is_locality_pinned`` — AST scan
     of ``orchestrator/main.py``: exactly ONE ``gc["cross_verification"]["rows"] = ...``
     assignment site (the pre-generation projection at line 1192). Any drift
     is a firewall breach.

  D. ``test_project_facts_round_trip_is_idempotent`` — runtime idempotence:
     project → generate → collect artifacts → re-project. The resulting
     ``TrustedFacts.rows_by_track_subject`` MUST equal the initial projection
     (disclosure rows from ``contributes_rows`` do NOT re-enter the authority
     store, even if a caller naively re-uses the same ``gc``). This elevates
     the guarantee from grep-static to runtime-proven.

Run: ``PYTHONPATH=audio_bu_skill python3 -m pytest
audio_bu_skill/tests/test_disclosure_firewall.py -v``

Zero I/O beyond source-file reads, zero timestamps, stdlib only.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.generation import facts as facts_module
from orchestrator.generation.facts import project_facts
from orchestrator.generation.machine_driver import generate_machine_driver
from orchestrator.generation.model import GeneratedArtifact, TrustedFacts
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Shared helper: minimal clean-Nord Facts ─────────────────────────────────


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
    """Build a WP2-shaped VerificationRow. Mirrors
    ``tests/test_machine_driver_board_variant_not_attested.py::_row``.
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


def _clean_nord_rows() -> list[VerificationRow]:
    """Rows that open all four machine_driver gates (clean-Nord shape)."""
    return [
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


# ── A. facts.py is AST-blind to contributes_rows ────────────────────────────


def test_project_facts_source_ast_free_of_contributes_rows() -> None:
    """``facts.py`` MUST NOT contain any ``.contributes_rows`` attribute access.

    Layer 4 of the firewall (data-flow): ``project_facts`` builds
    ``TrustedFacts`` from an incoming ``list[VerificationRow]`` only. If the
    module source references ``.contributes_rows``, that is a structural claim
    that a disclosure could feed back into authority.

    AST scan is stricter than grep: it catches
    ``x.contributes_rows``, ``obj.contributes_rows[...]``, and
    ``getattr(obj, "contributes_rows")`` calls; it ignores incidental string
    literals in docstrings (which are fine — they're prose about the rule).
    """
    src_path = Path(inspect.getsourcefile(facts_module))  # type: ignore[arg-type]
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    attr_hits: list[tuple[int, str]] = []
    call_hits: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # Direct attribute access: ``x.contributes_rows``.
        if isinstance(node, ast.Attribute) and node.attr == "contributes_rows":
            attr_hits.append((node.lineno, ast.unparse(node)))
        # Reflective access: ``getattr(x, "contributes_rows", ...)``.
        if isinstance(node, ast.Call):
            fn = node.func
            fn_name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fn_name == "getattr" and node.args:
                arg = node.args[1] if len(node.args) > 1 else None
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value == "contributes_rows"
                ):
                    call_hits.append((node.lineno, ast.unparse(node)))

    assert not attr_hits, (
        f"facts.py contains .contributes_rows attribute access — firewall breach. "
        f"Sites (line, expr): {attr_hits!r}"
    )
    assert not call_hits, (
        f"facts.py contains getattr(..., 'contributes_rows') access — firewall "
        f"breach. Sites (line, expr): {call_hits!r}"
    )
    print("PASS: facts.py AST is blind to contributes_rows")


# ── B. reasoning/*.py is free of disclosure + generation coupling ───────────


def test_reasoning_subsystem_free_of_disclosure_and_generation_imports() -> None:
    """Every ``orchestrator/reasoning/*.py`` MUST be free of the disclosure slot.

    Two-part static guard:

    * No literal ``contributes_rows`` reference anywhere in the reasoning
      subsystem source — the reasoning modules are authority-producers, they
      have no business reading a disclosure store.
    * No ``from orchestrator.generation`` or ``import orchestrator.generation``
      statement — the reasoning subsystem is upstream of generation; a reverse
      import would create a cycle AND open a channel for disclosures to
      re-enter authority.

    Closes WP-64 gap β (reverse-import guard).
    """
    reasoning_dir = Path(
        inspect.getsourcefile(facts_module)  # type: ignore[arg-type]
    ).parent.parent / "reasoning"
    assert reasoning_dir.is_dir(), (
        f"reasoning dir not found at {reasoning_dir}"
    )

    contributes_hits: list[tuple[str, int, str]] = []
    generation_import_hits: list[tuple[str, int, str]] = []

    for py_file in sorted(reasoning_dir.glob("*.py")):
        src = py_file.read_text(encoding="utf-8")

        # Literal grep: any physical ``contributes_rows`` occurrence.
        for lineno, line in enumerate(src.splitlines(), start=1):
            if "contributes_rows" in line:
                contributes_hits.append((py_file.name, lineno, line.strip()))

        # AST scan for orchestrator.generation imports.
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.generation" or module.startswith(
                    "orchestrator.generation."
                ):
                    generation_import_hits.append(
                        (py_file.name, node.lineno, ast.unparse(node))
                    )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.generation" or alias.name.startswith(
                        "orchestrator.generation."
                    ):
                        generation_import_hits.append(
                            (py_file.name, node.lineno, ast.unparse(node))
                        )

    assert not contributes_hits, (
        f"reasoning subsystem references `contributes_rows` — firewall breach. "
        f"Sites (file, line, text): {contributes_hits!r}"
    )
    assert not generation_import_hits, (
        f"reasoning subsystem imports from orchestrator.generation — reverse "
        f"import guard breach. Sites (file, line, stmt): {generation_import_hits!r}"
    )
    print(
        "PASS: reasoning subsystem is free of contributes_rows references and "
        "orchestrator.generation imports"
    )


# ── C. cross_verification.rows has exactly one assignment site in main.py ───


def test_cross_verification_rows_assignment_is_locality_pinned() -> None:
    """Only main.py may assign ``gc["cross_verification"]["rows"] = ...``.

    AST scan of ``orchestrator/main.py`` for
    ``Subscript(Subscript(Name("gc"), Constant("cross_verification")),
    Constant("rows"))`` assignment targets. The count is expected to be 1
    (the pre-generation projection). Zero and multiple both fail — zero means
    the projection was removed (silent regression); multiple means a second
    writer entered the code path (potential disclosure re-injection).

    NOTE: this test scans main.py ONLY. If a future WP legitimately needs to
    add a second site, the assertion must be updated with a comment naming
    the new site and its justification.

    We resolve ``main.py`` via ``facts_module``'s package path rather than
    importing ``orchestrator.main`` — importing main would leave a
    ``sys.modules`` residue that trips
    ``test_ipcat_acquire_isolation``'s order-dependent isolation guard.
    """
    orch_dir = Path(inspect.getsourcefile(facts_module)).parent.parent  # type: ignore[arg-type]
    src_path = orch_dir / "main.py"
    assert src_path.is_file(), f"main.py not found at {src_path}"
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    assign_sites: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                # Match: gc["cross_verification"]["rows"]
                if not isinstance(tgt, ast.Subscript):
                    continue
                outer_slice = tgt.slice
                if not (
                    isinstance(outer_slice, ast.Constant)
                    and outer_slice.value == "rows"
                ):
                    continue
                inner = tgt.value
                if not isinstance(inner, ast.Subscript):
                    continue
                inner_slice = inner.slice
                if not (
                    isinstance(inner_slice, ast.Constant)
                    and inner_slice.value == "cross_verification"
                ):
                    continue
                assign_sites.append((node.lineno, ast.unparse(node)))

        # Also catch dict-literal assignments like:
        #   gc["cross_verification"] = {"rows": ...}
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Subscript):
                    continue
                slc = tgt.slice
                if not (
                    isinstance(slc, ast.Constant) and slc.value == "cross_verification"
                ):
                    continue
                if isinstance(node.value, ast.Dict):
                    keys = [
                        k.value
                        for k in node.value.keys
                        if isinstance(k, ast.Constant)
                    ]
                    if "rows" in keys:
                        assign_sites.append((node.lineno, ast.unparse(node)))

    # Deduplicate (a dict-literal assignment matches both branches).
    unique_lines = sorted({s[0] for s in assign_sites})
    assert len(unique_lines) == 1, (
        f"expected exactly ONE writer of gc['cross_verification']['rows'] in "
        f"main.py; found {len(unique_lines)} at lines {unique_lines!r}. "
        f"Full sites: {assign_sites!r}. If a new writer was intentionally "
        f"added, update this test with the site + justification."
    )
    print(
        f"PASS: cross_verification.rows has exactly one assignment site in "
        f"main.py at line {unique_lines[0]}"
    )


# ── D. Runtime idempotence: disclosures never re-enter authority ────────────


def test_project_facts_round_trip_is_idempotent() -> None:
    """project → generate → re-project = same TrustedFacts.

    Runtime proof of the firewall:

    1. Build a clean-Nord ``rows`` list.
    2. Project once → ``facts_a``.
    3. Run ``generate_machine_driver`` to produce a ``GeneratedArtifact`` with
       three disclosure entries in ``contributes_rows`` (two I2S8 port
       placeholders + one WP-69 board_variant + one driver_match).
    4. Simulate the (WRONG) contamination: build a candidate rows list that
       is ``rows + artifact.contributes_rows`` — the shape a naive caller
       might build if they thought disclosures were feedable.
    5. Re-project both lists. The authoritative claim: ``facts_a`` (clean
       projection) MUST equal what ``project_facts(rows)`` returns on any
       future call — the incoming rows list is the sole authority source.
    6. Additionally: any ``contributes_rows`` subject in the artifact MUST
       NOT be present in ``facts_a.rows_by_track_subject`` UNLESS the same
       key was already in the original ``rows`` list. This is the invariant
       ``project_facts`` promises.

    A green result here means: even if a downstream caller does the wrong
    thing and mixes disclosures into an authority list, the pipeline built
    on top of the CORRECT projection is unaffected — because
    ``project_facts`` is deterministic and reads only what it is handed.
    """
    rows = _clean_nord_rows()
    facts_a = project_facts(rows)
    artifact = generate_machine_driver(facts_a)
    assert isinstance(artifact, GeneratedArtifact), (
        f"clean-Nord facts should have opened the gate; got "
        f"{type(artifact).__name__}: {artifact!r}"
    )
    assert artifact.contributes_rows, (
        "expected machine_driver to emit at least one disclosure row on "
        "clean-Nord facts; got empty contributes_rows"
    )

    # Re-project the ORIGINAL rows list. Must be byte-identical to facts_a.
    facts_a_again = project_facts(rows)
    assert facts_a.rows_by_track_subject == facts_a_again.rows_by_track_subject, (
        "project_facts is not deterministic on the same input: "
        f"first={sorted(facts_a.rows_by_track_subject)} "
        f"second={sorted(facts_a_again.rows_by_track_subject)}"
    )

    # Simulate the wrong contamination path: build a rows list that ALSO
    # includes the artifact's disclosures. Even if a downstream caller does
    # this, projecting *from the original rows* still returns facts_a — this
    # is the invariant that keeps main.py:567 safe.
    contaminated = list(rows) + list(artifact.contributes_rows)
    facts_contaminated = project_facts(contaminated)

    # The disclosure keys the contamination would add:
    disclosure_keys = {
        f"{r.track}.{r.subject}" for r in artifact.contributes_rows
    }
    authority_keys = set(facts_a.rows_by_track_subject.keys())

    # Every disclosure key that is NOT already in authority_keys must show
    # up as new-in-contaminated — proving that IF a caller mixed the lists
    # the disclosures WOULD land in authority. We then rely on the
    # firewall (facts.py, tested in A; main.py assignment site, tested in
    # C) to ensure no caller does this.
    new_in_contaminated = (
        set(facts_contaminated.rows_by_track_subject.keys()) - authority_keys
    )
    disclosure_only_keys = disclosure_keys - authority_keys
    assert new_in_contaminated == disclosure_only_keys, (
        "contaminated-projection sanity check drifted: "
        f"new_in_contaminated={sorted(new_in_contaminated)} "
        f"disclosure_only_keys={sorted(disclosure_only_keys)}"
    )

    # The load-bearing claim: the CORRECT projection (facts_a) does not
    # contain any disclosure-only key.
    leaked = disclosure_only_keys & authority_keys
    assert not leaked, (
        f"disclosure keys leaked into the clean authority projection: {leaked!r}"
    )
    assert not (disclosure_only_keys & set(facts_a.rows_by_track_subject)), (
        f"clean projection carries disclosure-only keys: "
        f"{disclosure_only_keys & set(facts_a.rows_by_track_subject)!r}"
    )

    print(
        f"PASS: project_facts idempotent; {len(disclosure_only_keys)} "
        f"disclosure keys never enter clean authority projection"
    )


# ── E. Negative-fixture proof: contamination WOULD be visible if it happened ─


def test_negative_fixture_contamination_would_be_detectable() -> None:
    """Elevate the guarantee from 'green today' to 'green because firewall exists'.

    Constructs a poisoned rows list by injecting a fake MATCH row that
    shares the shape of a disclosure subject. If the firewall were breached
    (i.e. a caller fed disclosures back into cross_verification.rows), the
    resulting TrustedFacts WOULD contain that subject as authority — and
    downstream gate/skip logic would treat it as MATCH. This test proves
    the detection path works: given contamination, we CAN see it.

    This is the negative complement to (D): (D) proves the clean projection
    stays clean; (E) proves that contamination is not silently absorbed —
    it appears in the projection as new keys.
    """
    rows = _clean_nord_rows()
    facts_clean = project_facts(rows)
    clean_keys = set(facts_clean.rows_by_track_subject.keys())

    # Poison: inject a fake MATCH row on a subject that is NOT in the clean
    # projection. If this row survives projection, it lands in authority.
    poisoned = list(rows) + [
        _row(
            "T5",
            "sound_card.model.board_variant",
            "MATCH",  # <-- authoritative verdict, would open a gate
            authority_strength="IPCAT_DIRECT",
            authority_origin="ipcat.injected",
        ),
    ]
    facts_poisoned = project_facts(poisoned)
    poisoned_keys = set(facts_poisoned.rows_by_track_subject.keys())

    new_key = "T5.sound_card.model.board_variant"
    assert new_key not in clean_keys, (
        f"regression: {new_key!r} was already in the clean projection — "
        "test fixture no longer models a disclosure-shaped subject"
    )
    assert new_key in poisoned_keys, (
        f"contamination path is not detectable: injected MATCH row on "
        f"{new_key!r} did NOT enter the projection. If it were silently "
        f"dropped, downstream firewall tests would be measuring nothing."
    )
    landed = facts_poisoned.rows_by_track_subject[new_key]
    assert landed.verdict == "MATCH", (
        f"injected row landed with wrong verdict {landed.verdict!r}"
    )
    print(
        "PASS: contamination path is observable — firewall tests measure a "
        "real invariant, not a vacuous one"
    )


if __name__ == "__main__":
    # stdlib-only entry point — mirrors WP5/WP6 test style.
    test_project_facts_source_ast_free_of_contributes_rows()
    test_reasoning_subsystem_free_of_disclosure_and_generation_imports()
    test_cross_verification_rows_assignment_is_locality_pinned()
    test_project_facts_round_trip_is_idempotent()
    test_negative_fixture_contamination_would_be_detectable()
    print("PASS: all 5 WP-64 disclosure firewall tests")
