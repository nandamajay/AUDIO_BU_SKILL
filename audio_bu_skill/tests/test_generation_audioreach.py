"""Phase-2B WP6 — tests for the audioreach_topology generator.

Pure, stdlib-only tests over ``orchestrator.generation.audioreach_topology``.
Mirrors the WP3/WP4/WP5 discipline: inline data, no fakes, no network, no
pytest.

  1. ``test_nord_generates_expected_audioreach`` — byte-identity vs
     ``tests/fixtures/phase2b/nord_audioreach_expected.dtsi`` for the *refreshed
     WP2 fixture* (``nord_trusted_facts.json``), used directly. Unlike the WP5
     happy-path (which needed a synthetic clean-Nord object because the WP2
     fixture's T2 row is DISAGREE), the WP6 gates are the two T3 element-count
     rows — both MATCH in the refreshed fixture — so the recorded snapshot
     opens the gate as-is. Also asserts the single ``audioreach.topology_blob``
     partial-artifact row.
  2. ``test_eliza_lpass_disagree_gate_closed_skipped`` — synthetic Eliza-like
     facts (T3 ``lpass_macro_instance`` DISAGREE, catalog=4 vs proposal=2) close
     the gate with ``gating_row_disagree_on_lpass_count``, byte-identical to
     ``eliza_lpass_disagree_skipped_expected.json``. This is the "Rajesh-email"
     production divergence: a GPR tree must NOT be emitted against a disputed
     LPASS instance count.
  3. ``test_dsp_disagree_gate_closed_skipped`` — T3 ``dsp_subsystem_instance``
     DISAGREE (LPASS open) closes the *second* gate with the generic
     ``gating_row_disagree``.
  4. ``test_missing_t3_rows_skipped`` — no T3 rows at all → fail-closed
     ``authority_not_in_snapshot`` on the LPASS gate (checked first).
  5. ``test_no_unavailable_facts_in_output`` — invariant #3: a poison marker
     injected into the T3 authority ``value`` fields never surfaces in the
     emitted bytes (the GPR tree is authority-independent boilerplate).
  6. ``test_import_guard`` — AST check: ``audioreach_topology.py`` MUST NOT
     import ``orchestrator.generation.facts``,
     ``orchestrator.reasoning.crossverify``,
     ``orchestrator.reasoning.cardinality``, or any peer generator.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_audioreach``
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from orchestrator.generation import audioreach_topology as audioreach_module
from orchestrator.generation.audioreach_topology import generate_audioreach_topology
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow

_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _AUDIO_BU_ROOT / "tests" / "fixtures" / "phase2b"


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
    authority_origin: str = "wp_c.cardinality_catalog",
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


def _rehydrate_wp2_fixture() -> TrustedFacts:
    """Rehydrate ``tests/fixtures/phase2b/nord_trusted_facts.json`` → TrustedFacts.

    The refreshed Nord snapshot — used AS-IS for the happy-path byte-identity
    test. Its two T3 rows (``lpass_macro_instance`` MATCH, count=0;
    ``dsp_subsystem_instance`` MATCH, count=1) both open the WP6 gate.
    """
    wp2_fixture_path = _FIXTURES / "nord_trusted_facts.json"
    assert wp2_fixture_path.is_file(), f"missing WP2 fixture: {wp2_fixture_path!r}"
    data = json.loads(wp2_fixture_path.read_text(encoding="utf-8"))

    rows_by_key: dict[str, VerificationRow] = {}
    for key, row_dict in data["rows_by_track_subject"].items():
        rows_by_key[key] = VerificationRow(
            track=row_dict["track"],
            subject=row_dict["subject"],
            verdict=row_dict["verdict"],
            source=row_dict.get("source", {}),
            authority=row_dict.get("authority"),
            confidence=row_dict.get("confidence", "none"),
            coverage_gap_reason=row_dict.get("coverage_gap_reason"),
            rule_id=row_dict.get("rule_id"),
            warning=row_dict.get("warning"),
            review_actions=list(row_dict.get("review_actions", [])),
            citations=list(row_dict.get("citations", [])),
            notes=list(row_dict.get("notes", [])),
        )
    return TrustedFacts(rows_by_track_subject=rows_by_key)


def _eliza_disagree_facts() -> TrustedFacts:
    """Synthetic Eliza-like facts: the LPASS-count production divergence.

    Exactly two T3 rows:

      * ``T3.dsp_subsystem_instance`` MATCH (authority.value count=1) — open.
      * ``T3.lpass_macro_instance`` DISAGREE_WITH_AUTHORITY (warning=True,
        authority.value={"catalog": 4, "proposal": 2}) — the Eliza
        "Rajesh-email" divergence: the proposed DT declares 2 LPASS macro
        instances where the WP-C cardinality catalog derives 4 from IPCAT.

    The LPASS gate is checked FIRST, so this closes with the reserved reason
    ``gating_row_disagree_on_lpass_count``.
    """
    rows_by_key = {
        "T3.dsp_subsystem_instance": _row(
            "T3", "dsp_subsystem_instance", "MATCH", authority_value={"count": 1}
        ),
        "T3.lpass_macro_instance": _row(
            "T3",
            "lpass_macro_instance",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
            authority_value={"catalog": 4, "proposal": 2},
        ),
    }
    return TrustedFacts(rows_by_track_subject=rows_by_key)


# ── 1. Byte-identity: refreshed WP2 fixture → frozen expected DTSI ──────────


def test_nord_generates_expected_audioreach() -> None:
    """Refreshed Nord facts produce byte-identical GPR-tree DTSI vs fixture.

    The fixture at ``tests/fixtures/phase2b/nord_audioreach_expected.dtsi`` is
    the downstream contract for the audioreach-topology lane. Byte-drift here
    (a reordered node, a whitespace change, a trailing-LF drift) fails with a
    clear diff.
    """
    facts = _rehydrate_wp2_fixture()
    result = generate_audioreach_topology(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for refreshed Nord facts, got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.subject == "audioreach_topology"
    assert result.artifact_class == "audioreach_topology"
    assert result.path_hint == (
        "generated/audioreach_topology/nord_audioreach.dtsi"
    ), f"path_hint drift: {result.path_hint!r}"

    # One partial-artifact row: the ACDB topology-blob firmware dependency.
    contributed = [r.subject for r in result.contributes_rows]
    assert contributed == ["audioreach.topology_blob.nord_iq10"], (
        f"contributes_rows subject/order drift: {contributed!r}"
    )
    for r in result.contributes_rows:
        assert r.track == "T5", f"contributes_row track drift: {r.track!r}"
        assert r.verdict == "NOT_CROSS_CHECKABLE", f"verdict drift: {r.verdict!r}"
        assert r.coverage_gap_reason == "authority_out_of_scope", (
            f"coverage_gap_reason drift: {r.coverage_gap_reason!r}"
        )

    expected_path = _FIXTURES / "nord_audioreach_expected.dtsi"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected_bytes = expected_path.read_bytes()

    assert result.bytes_ == expected_bytes, (
        f"audioreach byte-drift vs {expected_path}. "
        f"actual (repr, first 400 bytes): {result.bytes_[:400]!r}. "
        f"expected (repr, first 400 bytes): {expected_bytes[:400]!r}"
    )
    print(
        f"PASS: Nord audioreach topology byte-identical vs {expected_path.name} "
        f"({len(result.bytes_)} bytes)"
    )


# ── 2. Eliza LPASS DISAGREE gate closed → skipped (byte-identical JSON) ─────


def test_eliza_lpass_disagree_gate_closed_skipped() -> None:
    """Eliza LPASS-count divergence closes the gate → skipped.

    Byte-identical to the frozen JSON fixture at
    ``tests/fixtures/phase2b/eliza_lpass_disagree_skipped_expected.json``. This
    is the production reality-anchor: catalog=4 vs proposal=2 LPASS macro
    instances → the GPR tree must NOT be emitted.
    """
    facts = _eliza_disagree_facts()
    result = generate_audioreach_topology(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for LPASS DISAGREE, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_disagree_on_lpass_count", (
        f"reason drift: {result.reason!r}"
    )
    assert result.gating_rows == ["T3.lpass_macro_instance"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "audioreach_topology"
    assert result.artifact_class == "audioreach_topology"

    expected_path = _FIXTURES / "eliza_lpass_disagree_skipped_expected.json"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = result.to_dict()
    assert actual == expected, (
        f"skipped JSON drift: actual={actual!r}, expected={expected!r}"
    )
    print(
        "PASS: Eliza LPASS DISAGREE → "
        "GeneratorSkipped(gating_row_disagree_on_lpass_count), byte-identical"
    )


# ── 3. DSP DISAGREE (second gate) → skipped ─────────────────────────────────


def test_dsp_disagree_gate_closed_skipped() -> None:
    """T3.dsp_subsystem_instance DISAGREE (LPASS open) closes the second gate.

    The LPASS gate is open (MATCH) so evaluation reaches the DSP gate; its
    DISAGREE closes with the generic ``gating_row_disagree``.
    """
    rows_by_key = {
        "T3.lpass_macro_instance": _row(
            "T3", "lpass_macro_instance", "MATCH", authority_value={"count": 0}
        ),
        "T3.dsp_subsystem_instance": _row(
            "T3",
            "dsp_subsystem_instance",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
            authority_value={"catalog": 1, "proposal": 2},
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_audioreach_topology(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for DSP DISAGREE, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_disagree", f"reason drift: {result.reason!r}"
    assert result.gating_rows == ["T3.dsp_subsystem_instance"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "audioreach_topology"
    print("PASS: DSP DISAGREE → GeneratorSkipped(gating_row_disagree)")


# ── 4. Missing T3 rows → fail-closed ────────────────────────────────────────


def test_missing_t3_rows_skipped() -> None:
    """No T3 rows at all → authority_not_in_snapshot on the LPASS gate.

    The LPASS gate is checked first; a missing row is fail-closed (§4.2).
    """
    facts = TrustedFacts(rows_by_track_subject={})
    result = generate_audioreach_topology(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when no T3 rows, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "authority_not_in_snapshot", (
        f"reason drift: {result.reason!r}"
    )
    assert result.gating_rows == ["T3.lpass_macro_instance"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "audioreach_topology"
    print(
        "PASS: missing T3 rows → GeneratorSkipped(authority_not_in_snapshot) "
        "on LPASS gate"
    )


# ── 5. Invariant #3: no fabricated values from authority rows ───────────────


def test_no_unavailable_facts_in_output() -> None:
    """The generator never emits a value drawn from an authority ``value`` field.

    The GPR service tree is authority-independent boilerplate (the T3 rows only
    gate emit; they do not feed content). Inject a poison marker into both T3
    authority ``value`` fields and assert it never appears in the bytes.
    """
    poison = "SHOULD_NOT_APPEAR_IN_AUDIOREACH_ffea0f31"
    rows_by_key = {
        "T3.lpass_macro_instance": _row(
            "T3", "lpass_macro_instance", "MATCH", authority_value=poison
        ),
        "T3.dsp_subsystem_instance": _row(
            "T3", "dsp_subsystem_instance", "MATCH", authority_value=poison
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_audioreach_topology(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact for open gates, got {type(result).__name__}"
    )
    text = result.bytes_.decode("utf-8")
    assert poison not in text, (
        f"poison marker leaked into audioreach topology (invariant #3 "
        f"violation):\n{text}"
    )
    print("PASS: no authority value fabricated into output (invariant #3)")


# ── 6. Import guard ─────────────────────────────────────────────────────────


def test_import_guard() -> None:
    """AST-based check: audioreach_topology.py MUST NOT import forbidden modules.

    Forbidden modules (per §WP6 import discipline):

      * ``orchestrator.generation.facts`` — WP6 receives ``TrustedFacts`` as
        input; ``project_facts`` composition happens at the runner layer.
      * ``orchestrator.reasoning.crossverify`` — Phase-2A verifier internals.
      * ``orchestrator.reasoning.cardinality`` — Phase-2A cardinality track.
      * ``orchestrator.generation.dt_scaffolding`` / ``...codec_stub`` /
        ``...machine_driver`` — peer generators; no generator↔generator
        coupling.
    """
    src_path = Path(inspect.getfile(audioreach_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden = {
        "orchestrator.generation.facts",
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
        "orchestrator.generation.dt_scaffolding",
        "orchestrator.generation.codec_stub",
        "orchestrator.generation.machine_driver",
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
        f"WP6 import-guard failed: audioreach_topology.py must not import "
        f"forbidden modules {sorted(forbidden)!r}. Offenders: {offenders!r}"
    )

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
        f"sanity: audioreach_topology.py is expected to import from "
        f"{list(allowed_hits)!r}, missing: {missing_allowed!r}"
    )
    print(
        f"PASS: audioreach_topology.py import guard held "
        f"(forbidden={sorted(forbidden)}, all three allowed modules imported)"
    )


def main() -> None:
    test_nord_generates_expected_audioreach()            # 1
    test_eliza_lpass_disagree_gate_closed_skipped()      # 2
    test_dsp_disagree_gate_closed_skipped()              # 3
    test_missing_t3_rows_skipped()                       # 4
    test_no_unavailable_facts_in_output()                # 5
    test_import_guard()                                  # 6
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
