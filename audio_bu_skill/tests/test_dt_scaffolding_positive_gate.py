"""Unit tests for WP G-3B-gamma — dt_scaffolding positive-gate integration.

Companion to ``tests/test_crossverify_t5_positive_attestation.py``. Where
that file pins the producer contract on the T5 side, this file pins the
consumer contract on the ``dt_scaffolding`` side:

  * A ``TrustedFacts`` bundle carrying T5.dts.firmware=MATCH and
    T5.dts.compatible=MATCH (plus the three T1 pin rows) opens the gate and
    ``generate_dt`` emits a ``GeneratedArtifact``.

  * A ``TrustedFacts`` bundle with the T5 rows ABSENT continues to skip with
    ``reason=authority_not_in_snapshot`` (regression: the positive branch
    must not accidentally default-open).

  * A ``TrustedFacts`` bundle with T5.dts.firmware=DISAGREE_WITH_AUTHORITY
    (warning=True) closes the gate and ``generate_dt`` skips with
    ``reason=gating_row_disagree`` (regression: warning gate still works).

Additionally, a byte-identity subtest hash-checks the six Pipeline-1
modules under lock (design doc §6.5). Running ``generate_dt`` from this
file must not mutate any of them via import side-effects.

Constraint mapping (design doc §0):
- (1) trust-chain: MATCH rows built here go through the same ``is_open()``
      predicate at ``generation/model.py:213-237`` — NO-TOUCH guarantee.
- (2) provenance: authority=IPCAT_DIRECT is asserted on the MATCH rows
      constructed here.
- (5) fix only dt_scaffolding: byte-identity subtest asserts NO other
      generator module is touched.
- (6) regression tests: subtest 2 and 3 pin the pre-existing behavior
      (miss → skip; DISAGREE → skip) unchanged.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_dt_scaffolding_positive_gate``
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from orchestrator.generation.dt_scaffolding import generate_dt
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Helper builder (matches _row() from test_generation_dt.py) ─────────────


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
    """Build a minimal ``VerificationRow`` mirroring the sibling test-suite helper."""
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


def _facts_from_rows(rows: list[VerificationRow]) -> TrustedFacts:
    """Build a ``TrustedFacts`` bundle keyed as ``<track>.<subject>``.

    Deliberately does NOT call ``project_facts`` — the consumer contract
    only cares about the ``rows_by_track_subject`` dict shape and the
    ``is_open`` predicate; test-side coupling to the projector would drag
    in unrelated regressions.
    """
    return TrustedFacts(
        rows_by_track_subject={f"{r.track}.{r.subject}": r for r in rows}
    )


# ── 1. Positive MATCH rows open the gate → GeneratedArtifact ───────────────


def test_dt_scaffolding_opens_when_positive_rows_present() -> None:
    """T5.dts.firmware=MATCH + T5.dts.compatible=MATCH + T1 pins MATCH → artifact.

    This is the whole point of WP G-3B-gamma: with the two positive-attestation
    rows now emitted by ``track_t5``, ``dt_scaffolding``'s pre-existing gate
    (``facts.is_open("T5", "dts.firmware")`` / ``compatible``) opens and the
    generator produces a ``GeneratedArtifact`` instead of skipping.
    """
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    facts = _facts_from_rows(rows)

    # Sanity: is_open agrees with the new contract before the generator runs.
    assert facts.is_open("T5", "dts.firmware") is True
    assert facts.is_open("T5", "dts.compatible") is True

    result = generate_dt(facts)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact when both T5 MATCH rows present, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.subject == "dt_scaffolding"
    assert result.artifact_class == "dt_scaffolding"
    # No partial-artifact rows expected — all three T1 pins are MATCH.
    assert result.contributes_rows == [], (
        f"unexpected partial-artifact rows on clean facts: "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )
    # Sanity: bytes are non-empty and contain the ADSP node.
    text = result.bytes_.decode("utf-8")
    assert "qcom,sa8775p-adsp-pas" in text, (
        f"expected ADSP compatible in generated bytes: {text[:400]!r}"
    )
    print("PASS: T5 MATCH rows open the gate → GeneratedArtifact emitted")


# ── 2. T5 rows absent → skip with authority_not_in_snapshot ────────────────


def test_dt_scaffolding_still_skips_when_rows_absent() -> None:
    """No T5 rows in the bundle → generator MUST still skip.

    Regression guard: the positive branch is additive — absence of T5 rows
    must NOT become a silent default-open. The generator's Gate 2 checks
    the row's presence with ``facts.is_open("T5", "dts.firmware")``; a
    missing row returns False → skip with ``authority_not_in_snapshot``.
    """
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        # T5.dts.firmware and T5.dts.compatible both deliberately absent.
    ]
    facts = _facts_from_rows(rows)

    # Sanity: is_open is False for both missing rows.
    assert facts.is_open("T5", "dts.firmware") is False
    assert facts.is_open("T5", "dts.compatible") is False

    result = generate_dt(facts)
    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when T5 rows absent, got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.reason == "authority_not_in_snapshot", (
        f"expected authority_not_in_snapshot skip reason, got {result.reason!r}"
    )
    # Firmware is the first T5 gate checked, so it names the gating row.
    assert "T5.dts.firmware" in result.gating_rows, (
        f"expected T5.dts.firmware in gating_rows, got {result.gating_rows!r}"
    )
    print("PASS: T5 rows absent → skip with authority_not_in_snapshot (regression)")


# ── 3. T5 DISAGREE row → skip with gating_row_disagree (regression) ────────


def test_dt_scaffolding_still_skips_when_disagree_row_present() -> None:
    """T5.dts.firmware=DISAGREE_WITH_AUTHORITY (warning=True) → skip with disagree.

    Regression guard: the existing DISAGREE path (donor leak) still closes
    the gate correctly. The row's ``warning=True`` (default for DISAGREE
    per ``_WARNING_DEFAULT_TRUE`` at ``crossverify_model.py:81``) makes
    ``is_open`` return False, and ``dt_scaffolding``'s
    ``_skip_reason_for_closed_gate`` maps DISAGREE_WITH_AUTHORITY to
    ``gating_row_disagree``.
    """
    rows = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row(
            "T5", "dts.firmware", "DISAGREE_WITH_AUTHORITY",
            rule_id="t5.donor.firmware.sa8775p",
        ),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    facts = _facts_from_rows(rows)

    # Sanity: firmware row is present but the gate is closed (warning=True default).
    firmware_row = facts.rows_by_track_subject["T5.dts.firmware"]
    assert firmware_row.warning is True, (
        f"DISAGREE row should default to warning=True; got {firmware_row.warning!r}"
    )
    assert facts.is_open("T5", "dts.firmware") is False

    result = generate_dt(facts)
    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when T5 DISAGREE present, got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.reason == "gating_row_disagree", (
        f"expected gating_row_disagree, got {result.reason!r}"
    )
    assert "T5.dts.firmware" in result.gating_rows
    print("PASS: T5 DISAGREE row → skip with gating_row_disagree (regression)")


# ── 4. Byte-identity subtest — Pipeline 1 (dt_scaffolding side) untouched ──
#
# Design doc §6.5 pins six generator modules under the WP G-3B-gamma no-touch
# guarantee. Running the new positive-gate tests must not mutate any of them
# by import side-effect (that would signal a hidden global-state stashing).
#
# Note: the CodecPreviewEngine test (tests/test_codec_preview_engine.py:230)
# locks a THREE-module subset (codec_stub, model, __init__). This suite locks
# the WIDER six-module surface named by the design doc.

_PIPELINE_1_LOCKED = (
    Path("orchestrator/generation/dt_scaffolding.py"),
    Path("orchestrator/generation/model.py"),
    Path("orchestrator/generation/codec_stub.py"),
    Path("orchestrator/generation/machine_driver.py"),
    Path("orchestrator/generation/audioreach_topology.py"),
    Path("orchestrator/generation/post_verify.py"),
)


def _hash_locked() -> dict[str, str]:
    """Hash each locked module. Mirror of the pattern at
    ``tests/test_codec_preview_engine.py:237-243`` with the wider WP list.
    """
    repo_root = Path(__file__).resolve().parents[1]
    out: dict[str, str] = {}
    for rel in _PIPELINE_1_LOCKED:
        p = repo_root / rel
        assert p.is_file(), f"locked file missing: {p!r}"
        out[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_pipeline_1_generators_untouched_by_positive_gate() -> None:
    """Running the positive-gate tests must not mutate the 6 locked modules.

    Contract: WP G-3B-gamma modifies ONLY ``crossverify.py`` and
    ``crossverify_config.py`` (plus test files). Every module under
    ``orchestrator/generation/`` stays byte-identical.
    """
    before = _hash_locked()

    # Exercise all three code paths in this test module (positive gate + two
    # regression paths). Same call sites as the three tests above — any
    # side-effect stashing would appear here on the after-hash.
    rows_open = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row("T1", "gpio.i2s.ws", "MATCH"),
        _row("T1", "gpio.i2s.data", "MATCH"),
        _row("T5", "dts.firmware", "MATCH"),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    _ = generate_dt(_facts_from_rows(rows_open))
    _ = generate_dt(_facts_from_rows([_row("T1", "gpio.i2s.clk", "MATCH")]))
    rows_disagree = [
        _row("T1", "gpio.i2s.clk", "MATCH"),
        _row(
            "T5", "dts.firmware", "DISAGREE_WITH_AUTHORITY",
            rule_id="t5.donor.firmware.sa8775p",
        ),
        _row("T5", "dts.compatible", "MATCH"),
    ]
    _ = generate_dt(_facts_from_rows(rows_disagree))

    after = _hash_locked()
    assert before == after, (
        "byte-identity violation on Pipeline-1 generator modules — "
        f"before={before!r}\nafter={after!r}"
    )
    print(
        f"PASS: {len(_PIPELINE_1_LOCKED)} Pipeline-1 modules byte-identical "
        f"before/after positive-gate exercise"
    )


def main() -> None:
    test_dt_scaffolding_opens_when_positive_rows_present()          # 1
    test_dt_scaffolding_still_skips_when_rows_absent()              # 2
    test_dt_scaffolding_still_skips_when_disagree_row_present()     # 3
    test_pipeline_1_generators_untouched_by_positive_gate()         # 4 (byte-id)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
