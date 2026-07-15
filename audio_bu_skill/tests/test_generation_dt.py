"""Phase-2B WP3 — tests for the DT scaffolding generator.

Pure, stdlib-only tests over ``orchestrator.generation.dt_scaffolding``.
Mirrors the Phase-2A + WP1a + WP1b + WP2 test discipline: inline data, no
fakes, no network, no pytest. Seven tests per PHASE2B_SPECIFICATION.md §WP3:

  1. ``test_nord_generates_expected_dtsi`` — byte-identity vs
     ``tests/fixtures/phase2b/nord_dt_expected.dtsi`` for a clean Nord scenario
     (in-test synthetic facts; see fixture-deviation note below).
  2. ``test_eliza_donor_firmware_skipped`` — the §4.4 known-bad path routes
     to ``GeneratorSkipped(reason=gating_row_partial_match_donor_residue)``
     byte-identical to ``tests/fixtures/phase2b/eliza_skipped_expected.json``.
  3. ``test_missing_i2s_pin_fixme_marker`` — partial-artifact contract:
     missing T1 pin → ``FIXME(<pin>)`` in ``bytes_`` AND a partial-artifact
     row appended to ``contributes_rows``.
  4. ``test_no_unavailable_facts_in_output`` — invariant #3: the generator
     never fabricates values it does not have (verified by scanning bytes_
     for any authority ``value`` from an UNAVAILABLE row).
  5. ``test_partial_match_open_carries_rule_id_comment`` — §4.4 header
     comment discipline for a non-known-bad PARTIAL_MATCH-open firmware row.
  6. ``test_wp2_fixture_hits_donor_residue`` — reality anchor: the WP2
     ``nord_trusted_facts.json`` fixture, run against ``generate_dt``,
     produces ``GeneratorSkipped`` (its ``T5.dts.firmware`` rule_id is in
     ``KNOWN_BAD_PARTIAL_MATCH_RULES``). Documents the fixture-deviation
     that justifies the in-test synthetic Nord facts.
  7. ``test_import_guard`` — AST-based check: ``dt_scaffolding.py`` MUST NOT
     import from ``orchestrator.generation.facts``,
     ``orchestrator.reasoning.crossverify``, or
     ``orchestrator.reasoning.cardinality``.

Fixture deviation (§WP3 note):
------------------------------
The WP2 Nord fixture (``tests/fixtures/phase2b/nord_trusted_facts.json``) has
``T5.dts.firmware`` with ``rule_id="t5.donor.firmware.sa8775p"``, which IS a
member of ``KNOWN_BAD_PARTIAL_MATCH_RULES``, AND lacks any
``T5.dts.compatible`` row. Applied strictly, the WP2 fixture routes to
``GeneratorSkipped`` — matching the Eliza donor-residue path, NOT the Nord
gate-open path the WP3 spec describes.

To exercise the gate-open path without modifying the WP2 fixture (which is
the regression anchor for WP2 itself), tests 1/3/4/5 build in-test synthetic
Nord facts using ``_clean_nord_facts()``. Test 6 pins the reality anchor —
the recorded WP2 snapshot has known-bad donor residue and rightly routes to
skipped when handed to a WP3 generator. Both the synthetic path (spec-drawn
intent) and the fixture path (recorded reality) are tested.

WP3 pin vocabulary (Nord-family scoping):
-----------------------------------------
Pin subjects use the Nord ``aud_intfc8`` naming (``clk``, ``ws``, ``data``),
not the generic legacy ``mclk/bclk/lrclk/dout`` shape. This matches:

  * ``linux-nord/drivers/pinctrl/qcom/pinctrl-nord.c`` mux enums
    (``msm_mux_aud_intfc8_{clk,ws,data}``, PINGROUP(73/74/75))
  * The IQ-10 booting DTB's ``i2s8_active`` state node body

Only three pins are wired on IQ-10 I2S8 (no MCLK sub-node — the aud_mclk*
groups are separate states, not wired by IQ-10). ``_clean_nord_facts()``
carries only these three T1 pin rows plus T5 firmware + T5 compatible.

Firmware string:
----------------
The generator emits ``firmware-name = "qcom/sa8775p/adsp.mbn"`` because
Nord IQ-10 is a lemans-family SA8797P part that shares the SA8775P ADSP
firmware image (verified: sibling ``lemans-evk.dts``). The Phase-2A KB rule
``t5.donor.firmware.sa8775p`` catches the *Eliza-target* misuse of the same
string, not the legitimate lemans-family use — a target-family carve-out is
tracked as a Phase-2A follow-up and does not block WP3.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_dt``
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from orchestrator.generation import dt_scaffolding as dt_module
from orchestrator.generation.config import KNOWN_BAD_PARTIAL_MATCH_RULES
from orchestrator.generation.dt_scaffolding import generate_dt
from orchestrator.generation.facts import project_facts
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow

# ``tests/`` lives alongside ``orchestrator/`` under ``audio_bu_skill/``.
_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _AUDIO_BU_ROOT / "tests" / "fixtures" / "phase2b"


# ── Helper builders — inline, deterministic ─────────────────────────────────


def _row(
    track: str,
    subject: str,
    verdict: str,
    *,
    rule_id: str | None = None,
    warning: bool | None = None,
    coverage_gap_reason: str | None = None,
    authority_strength: str = "IPCAT_DIRECT",
) -> VerificationRow:
    """Build a minimal ``VerificationRow`` matching the Phase-2A shape.

    Every keyword is a passthrough; the caller is responsible for producing
    a legal (verdict × coverage_gap_reason) combination. The row goes through
    the Phase-2A ``__post_init__`` validator, so an illegal combination
    raises at construction — the tests use only well-formed rows.
    """
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        authority={"strength": authority_strength, "origin": "ipcat.test"},
        confidence="high" if verdict == "MATCH" else "medium",
        coverage_gap_reason=coverage_gap_reason,
        rule_id=rule_id,
        warning=warning,
    )


def _clean_nord_facts() -> TrustedFacts:
    """Synthetic Nord facts: all three I2S8 pins MATCH; firmware + compatible MATCH.

    Not identical to the WP2 fixture — see the module docstring "fixture
    deviation" note. This is the gate-open scenario the WP3 spec describes.

    Pin vocabulary: ``clk`` / ``ws`` / ``data`` — the Nord aud_intfc8 pin
    identifiers (GPIO73/74/75), not the legacy generic mclk/bclk/lrclk/dout.
    IQ-10 wires three lines on i2s8; MCLK lives on separate aud_mclk* pin
    groups which IQ-10 does not wire.
    """
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    return project_facts(rows)


# ── 1. Byte-identity: clean Nord → frozen expected DTSI ─────────────────────


def test_nord_generates_expected_dtsi() -> None:
    """Clean synthetic Nord facts produce byte-identical DTSI vs frozen fixture.

    The fixture at ``tests/fixtures/phase2b/nord_dt_expected.dtsi`` is the
    downstream contract for the DT scaffolding lane. Byte-drift here (a
    reordered pin, a whitespace change, a trailing-LF drift) fails the test
    with a clear diff.
    """
    facts = _clean_nord_facts()
    result = generate_dt(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for clean Nord, got {type(result).__name__}: {result!r}"
    )
    assert result.subject == "dt_scaffolding"
    assert result.artifact_class == "dt_scaffolding"
    assert result.path_hint == "generated/dt_scaffolding/sound.dtsi", (
        f"path_hint drift: {result.path_hint!r}"
    )
    # No partial-artifact rows on a clean scenario.
    assert result.contributes_rows == [], (
        f"contributes_rows should be empty when all pins are MATCH, got: "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )

    expected_path = _FIXTURES / "nord_dt_expected.dtsi"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected_bytes = expected_path.read_bytes()

    assert result.bytes_ == expected_bytes, (
        f"DTSI byte-drift vs {expected_path}. "
        f"actual (repr, first 400 bytes): {result.bytes_[:400]!r}. "
        f"expected (repr, first 400 bytes): {expected_bytes[:400]!r}"
    )
    print(
        f"PASS: Nord DTSI byte-identical vs {expected_path.name} "
        f"({len(result.bytes_)} bytes)"
    )


# ── 2. Eliza donor residue → skipped (byte-identical JSON) ──────────────────


def test_eliza_donor_firmware_skipped() -> None:
    """Known-bad donor residue routes to GeneratorSkipped per §4.4.

    Verifies both the semantic (kind, reason, gating_rows) and the byte-
    identity of the serialized skip vs the frozen JSON fixture at
    ``tests/fixtures/phase2b/eliza_skipped_expected.json``.
    """
    rows = [
        # Eliza-shape: T5.dts.firmware PARTIAL_MATCH with donor rule_id.
        _row(
            "T5",
            "dts.firmware",
            "PARTIAL_MATCH",
            rule_id="t5.donor.firmware.sa8775p",
        ),
        _row("T5", "dts.compatible", "MATCH"),  # would otherwise open the gate
        _row("T1", "gpio.i2s.mclk", "MATCH"),   # T1 doesn't save us — donor check runs first
    ]
    facts = project_facts(rows)
    result = generate_dt(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for donor-residue firmware, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_partial_match_donor_residue"
    assert result.gating_rows == ["T5.dts.firmware"]
    assert result.subject == "dt_scaffolding"
    assert result.artifact_class == "dt_scaffolding"

    # Byte-identity vs frozen fixture (canonical JSON serialization).
    expected_path = _FIXTURES / "eliza_skipped_expected.json"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = result.to_dict()
    assert actual == expected, (
        f"skipped JSON drift: actual={actual!r}, expected={expected!r}"
    )
    print("PASS: Eliza donor firmware → GeneratorSkipped, byte-identical to fixture")


# ── 3. Missing pin → FIXME marker + partial-artifact row ────────────────────


def test_missing_i2s_pin_fixme_marker() -> None:
    """A missing T1 pin becomes FIXME(<pin>) AND appends a contributes_rows entry.

    Verifies the partial-artifact contract: file still emitted (gate at pin
    granularity, not file granularity per §4.1); missing pin becomes a
    FIXME so the reviewer sees the gap; a NOT_CROSS_CHECKABLE row is
    appended to ``contributes_rows`` so WP7's post-gen verifier can pick
    up the gap.
    """
    # Same as _clean_nord_facts() but WITHOUT ``T1.gpio.i2s.ws``.
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        # ws deliberately absent
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    facts = project_facts(rows)
    result = generate_dt(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact (per-pin gating is not file-granular), "
        f"got {type(result).__name__}"
    )
    # FIXME marker in bytes for the missing pin only.
    text = result.bytes_.decode("utf-8")
    assert "FIXME(ws)" in text, (
        f"missing FIXME(ws) marker in generated bytes:\n{text}"
    )
    # Present pins do NOT get FIXME markers.
    for present in ("clk", "data"):
        assert f"FIXME({present})" not in text, (
            f"unexpected FIXME({present}) — this pin was MATCH:\n{text}"
        )

    # Exactly one partial-artifact contributes_rows entry, naming the missing pin.
    assert len(result.contributes_rows) == 1, (
        f"expected exactly 1 partial-artifact row, got "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )
    (partial,) = result.contributes_rows
    assert partial.track == "T1"
    assert partial.subject == "gpio.i2s.ws"
    assert partial.verdict == "NOT_CROSS_CHECKABLE"
    assert partial.coverage_gap_reason == "authority_out_of_scope"
    print("PASS: missing pin → FIXME(pin) in bytes + partial-artifact row in contributes_rows")


# ── 4. Invariant #3: no fabricated values from UNAVAILABLE authorities ──────


def test_no_unavailable_facts_in_output() -> None:
    """The generator never emits a value drawn from an UNAVAILABLE authority row.

    Concrete failure mode: if the generator ever grew a code path that read
    ``row.authority["value"]`` and interpolated it into ``bytes_``, an
    UNAVAILABLE authority row (with ``value=None`` or a placeholder) could
    surface a fabricated/None value in the DTSI. This test injects a poison
    marker into an UNAVAILABLE authority's ``value`` field and asserts the
    marker never appears in the emitted bytes.
    """
    poison = "SHOULD_NOT_APPEAR_IN_DTSI_ffea0f31"
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    facts = project_facts(rows)
    # Splice the poison after projection so the row is well-formed at construction.
    poisoned_row = VerificationRow(
        track="T4b",
        subject="codec.wsa883x",
        verdict="NOT_CROSS_CHECKABLE",
        authority={"strength": "UNAVAILABLE", "origin": "none", "value": poison},
        coverage_gap_reason="authority_out_of_scope",
    )
    facts.rows_by_track_subject["T4b.codec.wsa883x"] = poisoned_row

    result = generate_dt(facts)
    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact for clean gates, got {type(result).__name__}"
    )
    assert poison not in result.bytes_.decode("utf-8"), (
        f"poison marker leaked into DTSI (invariant #3 violation): "
        f"{result.bytes_.decode('utf-8')!r}"
    )
    print("PASS: no UNAVAILABLE authority value fabricated into output (invariant #3)")


# ── 5. PARTIAL_MATCH-open (non-known-bad) → header comment discipline ───────


def test_partial_match_open_carries_rule_id_comment() -> None:
    """§4.4 header-comment discipline: non-known-bad PARTIAL_MATCH firmware.

    A PARTIAL_MATCH firmware row whose rule_id is NOT in
    ``KNOWN_BAD_PARTIAL_MATCH_RULES`` opens the gate — but the artifact must
    carry a machine-parseable header comment naming the rule_id so a
    downstream grep for ``PARTIAL_MATCH gate`` surfaces it for review.
    """
    non_known_bad_rule = "t5.firmware.review.pending_ceo"
    # Sanity: chosen rule_id is genuinely NOT in the known-bad set.
    assert non_known_bad_rule not in KNOWN_BAD_PARTIAL_MATCH_RULES, (
        f"test setup error: {non_known_bad_rule!r} is in KNOWN_BAD_PARTIAL_MATCH_RULES"
    )

    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "PARTIAL_MATCH", rule_id=non_known_bad_rule),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    facts = project_facts(rows)
    result = generate_dt(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact (non-known-bad PARTIAL_MATCH opens gate), "
        f"got {type(result).__name__}: {result!r}"
    )
    text = result.bytes_.decode("utf-8")
    # Machine-parseable header lines per spec §4.4.
    expected_lead = (
        f"// PARTIAL_MATCH gate: T5.dts.firmware (rule_id={non_known_bad_rule})"
    )
    assert text.startswith(expected_lead + "\n"), (
        f"missing/misplaced PARTIAL_MATCH header lead line:\n{text[:400]!r}"
    )
    for required in (
        "//   The row matched on",
        "//   the verdict to PARTIAL_MATCH",
        "//   confirm firmware before this artifact is merged.",
    ):
        assert required in text, (
            f"missing required PARTIAL_MATCH header fragment {required!r}\n{text}"
        )
    print(
        "PASS: non-known-bad PARTIAL_MATCH firmware emits §4.4 header comment "
        f"(rule_id={non_known_bad_rule})"
    )


# ── 6. Reality anchor: WP2 fixture routes to skipped (fixture deviation note) ─


def test_wp2_fixture_hits_donor_residue() -> None:
    """The recorded WP2 Nord fixture has known-bad donor residue → routes to skipped.

    This is the reality anchor for the fixture deviation documented in the
    module docstring. The WP2 fixture (regression anchor for WP2) recorded
    Nord's actual Phase-2A snapshot at commit-time; that snapshot has
    ``T5.dts.firmware`` with ``rule_id=t5.donor.firmware.sa8775p``, which
    IS the known-bad Eliza donor residue. Handing this snapshot to WP3 must
    route to GeneratorSkipped — exactly what the Eliza test asserts. That's
    the correct behavior: the WP2 fixture is a legitimate snapshot of a
    known-bad state; WP3 should refuse it.

    Consequently, ``test_nord_generates_expected_dtsi`` uses synthetic
    clean-Nord facts (via ``_clean_nord_facts()``), not the WP2 fixture.
    """
    wp2_fixture_path = _FIXTURES / "nord_trusted_facts.json"
    assert wp2_fixture_path.is_file(), f"missing WP2 fixture: {wp2_fixture_path!r}"
    data = json.loads(wp2_fixture_path.read_text(encoding="utf-8"))

    # Rehydrate rows_by_track_subject → dict[str, VerificationRow].
    rows_by_key: dict[str, VerificationRow] = {}
    for key, row_dict in data["rows_by_track_subject"].items():
        row = VerificationRow(
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
        rows_by_key[key] = row
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)

    # Sanity: the fixture really does have the donor rule_id.
    firmware = facts.rows_by_track_subject.get("T5.dts.firmware")
    assert firmware is not None, "WP2 fixture missing T5.dts.firmware — spec drift"
    assert firmware.rule_id in KNOWN_BAD_PARTIAL_MATCH_RULES, (
        f"WP2 fixture drift: expected donor rule_id in "
        f"KNOWN_BAD_PARTIAL_MATCH_RULES, got {firmware.rule_id!r}"
    )

    result = generate_dt(facts)
    assert isinstance(result, GeneratorSkipped), (
        f"WP2 fixture MUST route to skipped (donor residue), got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_partial_match_donor_residue"
    assert result.gating_rows == ["T5.dts.firmware"]
    print(
        "PASS: WP2 nord_trusted_facts.json → skipped (donor residue anchor); "
        "gate-open path exercised via synthetic facts (see fixture-deviation note)"
    )


# ── 7. Import guard — WP3 does not reach into forbidden modules ─────────────


def test_import_guard() -> None:
    """AST-based check: dt_scaffolding.py MUST NOT import forbidden modules.

    Forbidden modules (per §WP3 import discipline):

      * ``orchestrator.generation.facts`` — WP3 receives ``TrustedFacts`` as
        input; ``project_facts`` composition happens at the runner layer.
      * ``orchestrator.reasoning.crossverify`` — Phase-2A verifier internals.
      * ``orchestrator.reasoning.cardinality`` — Phase-2A cardinality track.

    AST inspection (not regex) so both ``from X import Y`` and
    ``import X.Y`` are caught, and comments/docstrings mentioning these
    modules cannot produce false positives.
    """
    src_path = Path(inspect.getfile(dt_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden = {
        "orchestrator.generation.facts",
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
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
        f"WP3 import-guard failed: dt_scaffolding.py must not import forbidden "
        f"modules {sorted(forbidden)!r}. Offenders: {offenders!r}"
    )

    # Positive sanity: the module DOES import from the allowed modules
    # (proves we parsed the right file).
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
        f"sanity: dt_scaffolding.py is expected to import from {list(allowed_hits)!r}, "
        f"missing: {missing_allowed!r}"
    )
    print(
        f"PASS: dt_scaffolding.py import guard held "
        f"(forbidden={sorted(forbidden)}, all three allowed modules imported)"
    )


def main() -> None:
    test_nord_generates_expected_dtsi()               # 1
    test_eliza_donor_firmware_skipped()               # 2
    test_missing_i2s_pin_fixme_marker()               # 3
    test_no_unavailable_facts_in_output()             # 4
    test_partial_match_open_carries_rule_id_comment() # 5
    test_wp2_fixture_hits_donor_residue()             # 6
    test_import_guard()                               # 7
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
