"""Phase-2B WP4 — tests for the codec_stub generator.

Pure, stdlib-only tests over ``orchestrator.generation.codec_stub``. Mirrors
the Phase-2A + WP1a + WP1b + WP2 + WP3 test discipline: inline data, no
fakes, no network, no pytest. Six tests per PHASE2B_SPECIFICATION.md §WP4:

  1. ``test_nord_generates_expected_codec_stub`` — byte-identity vs
     ``tests/fixtures/phase2b/nord_codec_stub_expected.c`` for the recorded
     Nord snapshot (WP2 fixture). This is the primary regression anchor for
     the codec-stub emit path.
  2. ``test_missing_qup_endpoint_skipped`` — T4a.qup.* gate is closed when no
     T4a.qup.* row is open (no rows at all). Verdict:
     ``authority_not_in_snapshot``.
  3. ``test_codec_disagreement_skipped`` — a T4b.codec.* row with
     ``DISAGREE_WITH_AUTHORITY`` triggers ``codec_binding_disagreement``,
     byte-identical to ``tests/fixtures/phase2b/nord_codec_disagree_skipped_expected.json``.
  4. ``test_advisory_open_via_ncc_authority_out_of_scope`` — §3.7 advisory
     carve-out: T4b codec rows with NCC + authority_out_of_scope open the
     gate. Both known Nord codecs (ADAU1979, PCM1681) get i2c_board_info
     stanzas emitted.
  5. ``test_no_unavailable_facts_in_output`` — invariant #3: the generator
     never fabricates values from UNAVAILABLE authorities (poison marker
     scan on emitted bytes).
  6. ``test_import_guard`` — AST-based check: ``codec_stub.py`` MUST NOT
     import from ``orchestrator.generation.facts``,
     ``orchestrator.reasoning.crossverify``,
     ``orchestrator.reasoning.cardinality``, or
     ``orchestrator.generation.dt_scaffolding``.

Fixture-based rehydration:
--------------------------
WP4 does NOT need a WP3-style ``_clean_nord_facts()`` synthetic-facts helper
because the WP2 fixture ``nord_trusted_facts.json`` (as of the WP4 refresh)
already carries the two Nord codec rows in the shape WP4 expects: T4a.qup.se3
MATCH + T4b.codec.adau1979 NCC/authority_out_of_scope + T4b.codec.pcm1681
NCC/authority_out_of_scope. The WP3 "T5 known-bad residue" scenario that
forced synthetic facts there is irrelevant to WP4 (T5 is not in
``_GATING_ROW_NAMES``).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_codec``
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from orchestrator.generation import codec_stub as codec_module
from orchestrator.generation.codec_stub import generate_codec_stub
from orchestrator.generation.model import (
    GeneratedArtifact,
    GeneratorSkipped,
    TrustedFacts,
)
from orchestrator.reasoning.crossverify_model import VerificationRow

# ``tests/`` lives alongside ``orchestrator/`` under ``audio_bu_skill/``.
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


def _rehydrate_wp2_fixture() -> TrustedFacts:
    """Rehydrate ``tests/fixtures/phase2b/nord_trusted_facts.json`` → TrustedFacts.

    Matches the shape ``test_generation_facts.py`` uses for its dehydrated
    fan-out, but here we KEEP the two Nord codec rows literally as they land
    from the fixture (both NCC + authority_out_of_scope). WP4 accepts NCC
    rows directly via the §3.7 advisory carve-out — no rehydration needed.
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


# ── 1. Byte-identity: WP2 fixture → frozen expected C ───────────────────────


def test_nord_generates_expected_codec_stub() -> None:
    """WP2 Nord fixture produces byte-identical codec stub .c vs frozen fixture.

    The fixture at ``tests/fixtures/phase2b/nord_codec_stub_expected.c`` is
    the downstream contract for the codec-stub lane. Byte-drift here (a
    reordered codec, a whitespace change, a trailing-LF drift) fails with a
    clear diff.
    """
    facts = _rehydrate_wp2_fixture()
    result = generate_codec_stub(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for Nord WP2 facts, got "
        f"{type(result).__name__}: {result!r}"
    )
    assert result.subject == "codec_stub"
    assert result.artifact_class == "codec_stub"
    assert result.path_hint == "generated/codec_stub/nord_codec.c", (
        f"path_hint drift: {result.path_hint!r}"
    )
    # WP4 emits no partial-artifact rows when both codecs are in the Nord table.
    assert result.contributes_rows == [], (
        f"contributes_rows should be empty when both codecs are known-Nord, got: "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )

    expected_path = _FIXTURES / "nord_codec_stub_expected.c"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected_bytes = expected_path.read_bytes()

    assert result.bytes_ == expected_bytes, (
        f"codec_stub byte-drift vs {expected_path}. "
        f"actual (repr, first 400 bytes): {result.bytes_[:400]!r}. "
        f"expected (repr, first 400 bytes): {expected_bytes[:400]!r}"
    )
    print(
        f"PASS: Nord codec stub byte-identical vs {expected_path.name} "
        f"({len(result.bytes_)} bytes)"
    )


# ── 2. Missing QUP endpoint → skipped ───────────────────────────────────────


def test_missing_qup_endpoint_skipped() -> None:
    """No T4a.qup.* row at all → skipped with authority_not_in_snapshot.

    A projection with codec rows but no QUP endpoint anchor cannot know
    which i2c controller to emit against; the generator refuses.
    """
    rows_by_key = {
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
    result = generate_codec_stub(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped when no T4a.qup.* row present, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "authority_not_in_snapshot", (
        f"reason drift: {result.reason!r}"
    )
    assert result.gating_rows == ["T4a.qup.*"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "codec_stub"
    assert result.artifact_class == "codec_stub"
    print("PASS: missing T4a.qup.* → GeneratorSkipped(authority_not_in_snapshot)")


# ── 3. Codec disagreement → skipped (byte-identical JSON) ───────────────────


def test_codec_disagreement_skipped() -> None:
    """A DISAGREE_WITH_AUTHORITY on a codec row triggers codec_binding_disagreement.

    Byte-identical to the frozen JSON fixture at
    ``tests/fixtures/phase2b/nord_codec_disagree_skipped_expected.json``.
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
        # PCM1681 row: authority DISAGREES — hard skip on the whole stub.
        "T4b.codec.pcm1681": _row(
            "T4b",
            "codec.pcm1681",
            "DISAGREE_WITH_AUTHORITY",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_codec_stub(facts)

    assert isinstance(result, GeneratorSkipped), (
        f"expected GeneratorSkipped for codec disagreement, "
        f"got {type(result).__name__}: {result!r}"
    )
    assert result.reason == "codec_binding_disagreement"
    assert result.gating_rows == ["T4b.codec.pcm1681"], (
        f"gating_rows drift: {result.gating_rows!r}"
    )
    assert result.subject == "codec_stub"
    assert result.artifact_class == "codec_stub"

    # Byte-identity vs frozen fixture.
    expected_path = _FIXTURES / "nord_codec_disagree_skipped_expected.json"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = result.to_dict()
    assert actual == expected, (
        f"skipped JSON drift: actual={actual!r}, expected={expected!r}"
    )
    print("PASS: codec disagreement → GeneratorSkipped, byte-identical to fixture")


# ── 4. Advisory open path (§3.7): NCC + authority_out_of_scope opens gate ───


def test_advisory_open_via_ncc_authority_out_of_scope() -> None:
    """§3.7 advisory carve-out: T4b NCC + authority_out_of_scope opens the gate.

    This is the primary path Nord actually hits. Verifies:
      * both codec rows are advisory-open (NCC + authority_out_of_scope)
      * generator emits an artifact (not skipped)
      * both known-Nord codecs get their i2c_board_info stanzas
      * emission order is deterministic (adau1979 before pcm1681)
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
        "T4b.codec.pcm1681": _row(
            "T4b",
            "codec.pcm1681",
            "NOT_CROSS_CHECKABLE",
            authority_strength="UNAVAILABLE",
            authority_origin="none",
            coverage_gap_reason="authority_out_of_scope",
            warning=True,
            rule_id="t4b.codec_binding.out_of_scope",
        ),
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_codec_stub(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact (advisory NCC+authority_out_of_scope opens gate), "
        f"got {type(result).__name__}: {result!r}"
    )
    text = result.bytes_.decode("utf-8")

    # Both codec stanzas emitted.
    assert "nord_adau1979_info" in text, f"missing ADAU1979 stanza:\n{text}"
    assert "nord_pcm1681_info" in text, f"missing PCM1681 stanza:\n{text}"
    assert "0x31" in text, f"missing ADAU1979 addr 0x31:\n{text}"
    assert "0x4c" in text, f"missing PCM1681 addr 0x4c:\n{text}"
    assert '"adi,adau1979"' in text, f"missing ADAU1979 compatible:\n{text}"
    assert '"ti,pcm1681"' in text, f"missing PCM1681 compatible:\n{text}"

    # Deterministic order: adau1979 stanza before pcm1681 stanza (sorted subject).
    adau_pos = text.index("nord_adau1979_info")
    pcm_pos = text.index("nord_pcm1681_info")
    assert adau_pos < pcm_pos, (
        f"emission order drift: adau1979 at {adau_pos}, pcm1681 at {pcm_pos} "
        f"(expected adau1979 first, sorted-subject order)"
    )
    print(
        "PASS: T4b NCC+authority_out_of_scope opens advisory gate; both Nord "
        "codecs emitted in sorted-subject order"
    )


# ── 5. Invariant #3: no fabricated values from UNAVAILABLE authorities ──────


def test_no_unavailable_facts_in_output() -> None:
    """The generator never emits a value drawn from an UNAVAILABLE authority row.

    Concrete failure mode: if the generator ever grew a code path that read
    ``row.authority["value"]`` and interpolated it into ``bytes_``, an
    UNAVAILABLE authority row (with a placeholder value) could surface a
    fabricated string in the emitted C. This test injects a poison marker
    into the UNAVAILABLE authority ``value`` field of both codec rows and
    asserts the marker never appears in the emitted bytes.
    """
    poison = "SHOULD_NOT_APPEAR_IN_CODEC_STUB_ffea0f31"
    rows_by_key = {
        "T4a.qup.se3": _row("T4a", "qup.se3", "MATCH"),
        "T4b.codec.adau1979": _row(
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
        "T4b.codec.pcm1681": _row(
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
    }
    facts = TrustedFacts(rows_by_track_subject=rows_by_key)
    result = generate_codec_stub(facts)

    assert isinstance(result, GeneratedArtifact), (
        f"expected artifact for advisory-open gates, got {type(result).__name__}"
    )
    text = result.bytes_.decode("utf-8")
    assert poison not in text, (
        f"poison marker leaked into codec stub (invariant #3 violation):\n{text}"
    )
    print("PASS: no UNAVAILABLE authority value fabricated into output (invariant #3)")


# ── 6. Import guard ─────────────────────────────────────────────────────────


def test_import_guard() -> None:
    """AST-based check: codec_stub.py MUST NOT import forbidden modules.

    Forbidden modules (per §WP4 import discipline):

      * ``orchestrator.generation.facts`` — WP4 receives ``TrustedFacts`` as
        input; ``project_facts`` composition happens at the runner layer.
      * ``orchestrator.reasoning.crossverify`` — Phase-2A verifier internals.
      * ``orchestrator.reasoning.cardinality`` — Phase-2A cardinality track.
      * ``orchestrator.generation.dt_scaffolding`` — peer generator; no
        generator↔generator coupling.
    """
    src_path = Path(inspect.getfile(codec_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    forbidden = {
        "orchestrator.generation.facts",
        "orchestrator.reasoning.crossverify",
        "orchestrator.reasoning.cardinality",
        "orchestrator.generation.dt_scaffolding",
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
        f"WP4 import-guard failed: codec_stub.py must not import forbidden "
        f"modules {sorted(forbidden)!r}. Offenders: {offenders!r}"
    )

    # Positive sanity: the module DOES import from the allowed modules.
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
        f"sanity: codec_stub.py is expected to import from {list(allowed_hits)!r}, "
        f"missing: {missing_allowed!r}"
    )
    print(
        f"PASS: codec_stub.py import guard held "
        f"(forbidden={sorted(forbidden)}, all three allowed modules imported)"
    )


def main() -> None:
    test_nord_generates_expected_codec_stub()               # 1
    test_missing_qup_endpoint_skipped()                     # 2
    test_codec_disagreement_skipped()                       # 3
    test_advisory_open_via_ncc_authority_out_of_scope()     # 4
    test_no_unavailable_facts_in_output()                   # 5
    test_import_guard()                                     # 6
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
