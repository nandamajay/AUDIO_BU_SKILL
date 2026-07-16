"""Phase-2B WP5 — tests for the machine_driver generator.

Pure, stdlib-only tests over ``orchestrator.generation.machine_driver``.
Mirrors the WP3/WP4 discipline: inline data, no fakes, no network, no pytest.

  1. ``test_nord_generates_expected_machine_driver`` — byte-identity vs
     ``tests/fixtures/phase2b/nord_machine_driver_expected.dtsi`` for a
     *synthetic* clean-Nord facts object. The clean facts carry a T2
     ``soundwire_master`` MATCH (instruction #1): the recorded WP2 fixture
     carries T2 DISAGREE, which correctly CLOSES the machine_driver gate — so
     the byte-identity happy-path cannot use the WP2 fixture directly. Also
     asserts the three ``contributes_rows`` partial-artifact subjects
     (decision A driver-match row + decision B per-link port_id rows).
  2. ``test_t2_disagree_gate_closed_skipped`` — the recorded WP2 fixture (T2
     ``soundwire_master`` DISAGREE_WITH_AUTHORITY) closes the gate with
     ``gating_row_disagree_on_bus``, byte-identical to
     ``nord_machine_driver_disagree_skipped_expected.json``.
  3. ``test_missing_pinctrl_gate_skipped`` — no open ``T1.gpio.i2s.*`` row →
     ``authority_not_in_snapshot`` on ``T1.gpio.i2s.*``.
  4. ``test_missing_qup_endpoint_skipped`` — pin open but no ``T4a.qup.*`` →
     ``authority_not_in_snapshot`` on ``T4a.qup.*``.
  5. ``test_codec_disagreement_hard_skip`` — a T4b codec DISAGREE triggers
     ``codec_binding_disagreement`` (a card must never reference a codec whose
     binding the authority disputes).
  6. ``test_no_unavailable_facts_in_output`` — invariant #3: poison marker
     injected into UNAVAILABLE authority values never surfaces in the bytes.
  7. ``test_import_guard`` — AST check: ``machine_driver.py`` MUST NOT import
     ``orchestrator.generation.facts``,
     ``orchestrator.reasoning.crossverify``,
     ``orchestrator.reasoning.cardinality``, or either peer generator.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_machine``
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from orchestrator.generation import machine_driver as machine_module
from orchestrator.generation.facts import project_facts
from orchestrator.generation.machine_driver import generate_machine_driver
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


def _clean_nord_facts() -> TrustedFacts:
    """Synthetic *clean-Nord* facts that open every machine_driver gate.

    Instruction #1: the recorded WP2 fixture carries a T2
    ``soundwire_master`` DISAGREE_WITH_AUTHORITY row, which correctly CLOSES
    the machine_driver T2 gate (``gating_row_disagree_on_bus``). The
    byte-identity happy-path therefore cannot use the WP2 fixture directly; it
    needs a projection whose T2 row is MATCH. This helper builds exactly that:

      * ``T1.gpio.i2s.mclk`` MATCH        → pinctrl gate open
      * ``T4a.qup.se3`` MATCH             → QUP endpoint gate open
      * ``T4b.codec.{adau1979,pcm1681}``  → NCC + authority_out_of_scope
                                            (advisory-open, no DISAGREE)
      * ``T2.soundwire_master`` MATCH     → SoundWire gate open (no DISAGREE)

    Everything else mirrors the Nord snapshot. ``project_facts`` keys the rows
    by ``<track>.<subject>`` exactly as the runner does.
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


def _rehydrate_wp2_fixture() -> TrustedFacts:
    """Rehydrate ``tests/fixtures/phase2b/nord_trusted_facts.json`` → TrustedFacts.

    The recorded Nord snapshot — used AS-IS for the gate-closed test. Its T2
    ``soundwire_master`` row is DISAGREE_WITH_AUTHORITY, which closes the
    machine_driver T2 gate.
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


# ── 1. Byte-identity: synthetic clean-Nord facts → frozen expected DTSI ─────


def test_nord_generates_expected_machine_driver() -> None:
    """Clean-Nord facts produce byte-identical sound-card DTSI vs frozen fixture.

    The fixture at ``tests/fixtures/phase2b/nord_machine_driver_expected.dtsi``
    is the downstream contract for the machine-driver lane. Byte-drift here (a
    reordered DAI-link, a whitespace change, a trailing-LF drift) fails with a
    clear diff.
    """
    facts = _clean_nord_facts()
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for clean-Nord facts, got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.subject == "machine_driver"
    assert result.artifact_class == "machine_driver"
    assert result.path_hint == "generated/machine_driver/nord_sound.dtsi", (
        f"path_hint drift: {result.path_hint!r}"
    )

    # Three partial-artifact rows: two decision-B port_id rows (one per link)
    # + one decision-A driver-match row. Order is emit order: playback link,
    # capture link, then the trailing driver-match row.
    contributed = [r.subject for r in result.contributes_rows]
    assert contributed == [
        "dai_link.port_id.i2s8_playback",
        "dai_link.port_id.i2s8_capture",
        "sound_card.driver_match.nord_iq10",
    ], f"contributes_rows subject/order drift: {contributed!r}"
    for r in result.contributes_rows:
        assert r.track == "T5", f"contributes_row track drift: {r.track!r}"
        assert r.verdict == "NOT_CROSS_CHECKABLE", f"verdict drift: {r.verdict!r}"
        assert r.coverage_gap_reason == "authority_out_of_scope", (
            f"coverage_gap_reason drift: {r.coverage_gap_reason!r}"
        )

    expected_path = _FIXTURES / "nord_machine_driver_expected.dtsi"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected_bytes = expected_path.read_bytes()

    assert result.bytes_ == expected_bytes, (
        f"machine_driver byte-drift vs {expected_path}. "
        f"actual (repr, first 400 bytes): {result.bytes_[:400]!r}. "
        f"expected (repr, first 400 bytes): {expected_bytes[:400]!r}"
    )
    print(
        f"PASS: Nord machine driver byte-identical vs {expected_path.name} "
        f"({len(result.bytes_)} bytes)"
    )


# ── 2. T2 DISAGREE gate closed → skipped (byte-identical JSON) ──────────────


def test_t2_disagree_gate_closed_skipped() -> None:
    """The recorded WP2 fixture (T2 DISAGREE) closes the gate → skipped.

    Byte-identical to the frozen JSON fixture at
    ``tests/fixtures/phase2b/nord_machine_driver_disagree_skipped_expected.json``.
    This is the reality-anchor: the actual Nord snapshot disputes the
    SoundWire bus topology, so the I2S8 card must NOT be emitted.
    """
    facts = _rehydrate_wp2_fixture()
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for T2 DISAGREE, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_disagree_on_bus", (
        f"reason drift: {result.reason!r}"
    )
    assert result.gating_rows == ["T2.soundwire_master"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "machine_driver"
    assert result.artifact_class == "machine_driver"

    expected_path = _FIXTURES / "nord_machine_driver_disagree_skipped_expected.json"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = result.to_dict()
    assert actual == expected, (
        f"skipped JSON drift: actual={actual!r}, expected={expected!r}"
    )
    print("PASS: T2 DISAGREE → GeneratorSkipped(gating_row_disagree_on_bus), byte-identical")


# ── 3. Missing pinctrl → skipped ────────────────────────────────────────────


def test_missing_pinctrl_gate_skipped() -> None:
    """No open T1.gpio.i2s.* row → skipped with authority_not_in_snapshot.

    Without a confirmed I2S8 pinmux the card's ``pinctrl-0 = <&i2s8_active>``
    reference is meaningless; the generator refuses before touching later
    gates.
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
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when no T1.gpio.i2s.* open, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "authority_not_in_snapshot", f"reason drift: {result.reason!r}"
    assert result.gating_rows == ["T1.gpio.i2s.*"], f"gating_rows drift: {result.gating_rows!r}"
    assert result.subject == "machine_driver"
    print("PASS: missing T1.gpio.i2s.* → GeneratorSkipped(authority_not_in_snapshot)")


# ── 4. Missing QUP endpoint → skipped ───────────────────────────────────────


def test_missing_qup_endpoint_skipped() -> None:
    """Pin open but no T4a.qup.* row → skipped with authority_not_in_snapshot.

    The codec control bus must be authoritatively confirmed; the pinctrl gate
    passing is not sufficient on its own.
    """
    rows_by_key = {
        "T1.gpio.i2s.mclk": _row("T1", "gpio.i2s.mclk", "MATCH"),
        "T4b.codec.adau1979": _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when no T4a.qup.* row, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "authority_not_in_snapshot", f"reason drift: {result.reason!r}"
    assert result.gating_rows == ["T4a.qup.*"], f"gating_rows drift: {result.gating_rows!r}"
    assert result.subject == "machine_driver"
    print("PASS: missing T4a.qup.* → GeneratorSkipped(authority_not_in_snapshot)")


# ── 5. Codec disagreement → hard skip ───────────────────────────────────────


def test_codec_disagreement_hard_skip() -> None:
    """A T4b codec DISAGREE triggers codec_binding_disagreement.

    A card that boots but binds the wrong device on the disagreeing side is
    worse than no card — the generator hard-skips before the T2 gate.
    """
    rows_by_key = {
        "T1.gpio.i2s.mclk": _row("T1", "gpio.i2s.mclk", "MATCH"),
        "T4a.qup.se3": _row("T4a", "qup.se3", "MATCH"),
        "T4b.codec.adau1979": _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        "T4b.codec.pcm1681": _row(
            "T4b",
            "codec.pcm1681",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for codec disagreement, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "codec_binding_disagreement", f"reason drift: {result.reason!r}"
    assert result.gating_rows == ["T4b.codec.pcm1681"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "machine_driver"
    print("PASS: codec disagreement → GeneratorSkipped(codec_binding_disagreement)")


# ── 6. Invariant #3: no fabricated values from UNAVAILABLE authorities ──────


def test_no_unavailable_facts_in_output() -> None:
    """The generator never emits a value drawn from an UNAVAILABLE authority row.

    Injects a poison marker into the UNAVAILABLE authority ``value`` field of
    both codec rows and asserts the marker never appears in the emitted bytes.
    """
    poison = "SHOULD_NOT_APPEAR_IN_MACHINE_DRIVER_ffea0f31"
    rows = [
        _row("T1", "gpio.i2s.mclk", "MATCH"),
        _row("T4a", "qup.se3", "MATCH"),
        _row(
            "T4b",
            "codec.adau1979",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            authority_value=poison,
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
            authority_value=poison,
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
        _row("T2", "soundwire_master", "MATCH"),
    ]
    facts = project_facts(rows)
    result = generate_machine_driver(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact for open gates, got {type(result).__name__}"
    )
    text = result.bytes_.decode("utf-8")
    assert poison not in text, (
        f"poison marker leaked into machine driver (invariant #3 violation):\n{text}"
    )
    print("PASS: no UNAVAILABLE authority value fabricated into output (invariant #3)")


# ── 7. Import guard ─────────────────────────────────────────────────────────


def test_import_guard() -> None:
    """AST-based check: machine_driver.py MUST NOT import forbidden modules.

    Forbidden modules (per §WP5 import discipline):

      * ``orchestrator.generation.facts`` — WP5 receives ``TrustedFacts`` as
        input; ``project_facts`` composition happens at the runner layer.
      * ``orchestrator.reasoning.crossverify`` — Phase-2A verifier internals.
      * ``orchestrator.reasoning.cardinality`` — Phase-2A cardinality track.
      * ``orchestrator.generation.dt_scaffolding`` / ``...codec_stub`` — peer
        generators; no generator↔generator coupling.
    """
    src_path = Path(inspect.getfile(machine_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden = {
        "orchestrator.generation.facts",
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
        "orchestrator.generation.dt_scaffolding",
        "orchestrator.generation.codec_stub",
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
        f"WP5 import-guard failed: machine_driver.py must not import forbidden "
        f"modules {sorted(forbidden)!r}. Offenders: {offenders!r}"
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
        f"sanity: machine_driver.py is expected to import from {list(allowed_hits)!r}, "
        f"missing: {missing_allowed!r}"
    )
    print(
        f"PASS: machine_driver.py import guard held "
        f"(forbidden={sorted(forbidden)}, all three allowed modules imported)"
    )


def main() -> None:
    test_nord_generates_expected_machine_driver()   # 1
    test_t2_disagree_gate_closed_skipped()          # 2
    test_missing_pinctrl_gate_skipped()             # 3
    test_missing_qup_endpoint_skipped()             # 4
    test_codec_disagreement_hard_skip()             # 5
    test_no_unavailable_facts_in_output()           # 6
    test_import_guard()                             # 7
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
