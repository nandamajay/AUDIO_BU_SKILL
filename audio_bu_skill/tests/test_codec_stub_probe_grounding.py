"""Slice 1 — integration tests: codec_stub grounded by CodecDriverProbe.

Exercises ``generate_codec_stub(facts, source=probe)`` — the probe-direct
wiring that grounds each codec's ``compatible`` on the kernel driver
of_match_table instead of a hardcoded assertion. Complements
``test_generation_codec.py`` (which pins the NO-source path: empty
contributes_rows + byte-identity). Here we pin the WITH-source path:

  1. Real-Nord FOUND: probe over ``codec_found_tree`` → compatible attested
     from the driver of_match_table; disclosure states kernel_source; the
     emitted comment carries the attested literal.
  2. Byte-identity: FOUND path emits bytes byte-identical to the no-source
     path (of_match_table literals equal ``_NORD_CODECS`` values on Nord) —
     only ``contributes_rows`` (disclosures) differ.
  3. Driver-ABSENT fallback: probe over ``codec_absent_tree`` → falls back to
     hardcoded ``_NORD_CODECS`` value, disclosure marks it NOT kernel-attested.
  4. Join-key caveat: every compatible disclosure carries the mandatory
     verbatim caveat that the LOOKUP KEY is candidate-derived (5267b2e1).
  5. Disclosure-only: the probe never reaches TrustedFacts / cross_verification
     and never changes the emit gate (FOUND vs ABSENT vs no-source all emit).

Fixture trees are the same on-disk codec driver fixtures used by
``test_codec_driver_probe.py`` — no network, no writes, no real kernel tree
dependency.

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_codec_stub_probe_grounding``
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.generation.codec_driver_probe import CodecDriverProbe
from orchestrator.generation.codec_stub import (
    generate_codec_stub,
    _JOIN_KEY_CAVEAT,
)
from orchestrator.generation.model import GeneratedArtifact, TrustedFacts
from orchestrator.reasoning.crossverify_model import VerificationRow

_AUDIO_BU_ROOT = Path(__file__).resolve().parent.parent
_KERNEL_TREES = _AUDIO_BU_ROOT / "tests" / "fixtures" / "kernel_trees"
_FOUND_TREE = str(_KERNEL_TREES / "codec_found_tree")
_ABSENT_TREE = str(_KERNEL_TREES / "codec_absent_tree")

_NORD_CODEC_KEYS = ("adau1979", "pcm1681")


# ── Helper builders (mirror test_generation_codec._row) ─────────────────────


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


def _advisory_open_nord_facts() -> TrustedFacts:
    """Both Nord codecs advisory-open (NCC + authority_out_of_scope) + QUP anchor."""
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
    return TrustedFacts(rows_by_track_subject=rows_by_key)


def _artifact(facts: TrustedFacts, *, source: CodecDriverProbe | None) -> GeneratedArtifact:
    result = generate_codec_stub(facts, source=source)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact for advisory-open gates, got "
        f"{type(result).__name__}: {result!r}"
    )
    return result


def _compat_rows(artifact: GeneratedArtifact) -> dict[str, VerificationRow]:
    """Map codec_key → the compatible_source disclosure row (if present)."""
    out: dict[str, VerificationRow] = {}
    for row in artifact.contributes_rows:
        if row.subject.startswith("codec.") and row.subject.endswith(".compatible_source"):
            key = row.subject[len("codec.") : -len(".compatible_source")]
            out[key] = row
    return out


# ── 1. FOUND: compatible attested from kernel_source ────────────────────────


def test_found_attests_compatible_from_kernel_source() -> None:
    """Probe over found tree → compatible attested; disclosure names kernel_source."""
    facts = _advisory_open_nord_facts()
    probe = CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)
    artifact = _artifact(facts, source=probe)

    rows = _compat_rows(artifact)
    assert set(rows) == {"adau1979", "pcm1681"}, (
        f"expected a compatible disclosure per Nord codec, got {sorted(rows)!r}"
    )

    for key, expected_compat, expected_file in (
        ("adau1979", "adi,adau1979", "adau1977-spi.c"),
        ("pcm1681", "ti,pcm1681", "pcm1681.c"),
    ):
        row = rows[key]
        assert row.track == "T4b", f"{key} disclosure track drift: {row.track!r}"
        assert row.verdict == "NOT_CROSS_CHECKABLE", (
            f"{key} disclosure verdict drift: {row.verdict!r}"
        )
        assert row.coverage_gap_reason == "authority_out_of_scope", (
            f"{key} disclosure coverage_gap_reason drift: {row.coverage_gap_reason!r}"
        )
        head = row.notes[0]
        assert "OBSERVED FOUND" in head, f"{key} not marked FOUND: {head!r}"
        assert expected_compat in head, f"{key} compatible missing from note: {head!r}"
        assert "kernel_source" in head, f"{key} provenance not kernel_source: {head!r}"
        assert expected_file in head, f"{key} driver file missing from note: {head!r}"

        # The emitted comment carries the attested literal.
        text = artifact.bytes_.decode("utf-8")
        assert f'/* compatible = "{expected_compat}" */' in text, (
            f"{key} attested compatible not emitted:\n{text}"
        )
    print("PASS: FOUND — both Nord codecs attested from kernel driver of_match_table")


# ── 2. Byte-identity across probe states (only disclosures differ) ──────────


def test_byte_identity_found_equals_no_source() -> None:
    """FOUND path emits byte-identical bytes to the no-source path on Nord.

    The of_match_table literals equal ``_NORD_CODECS`` values, so grounding the
    compatible on kernel_source cannot shift the emitted bytes — only the
    ``contributes_rows`` disclosures appear. Guards the Slice 1 byte-identity
    invariant.
    """
    facts = _advisory_open_nord_facts()

    no_source = _artifact(facts, source=None)
    found = _artifact(facts, source=CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS))
    absent = _artifact(facts, source=CodecDriverProbe.from_tree(_ABSENT_TREE, _NORD_CODEC_KEYS))
    null_probe = _artifact(facts, source=CodecDriverProbe.from_tree(None, _NORD_CODEC_KEYS))

    assert no_source.bytes_ == found.bytes_ == absent.bytes_ == null_probe.bytes_, (
        "codec_stub bytes drifted across probe states (byte-identity broken):\n"
        f"  no_source={len(no_source.bytes_)}B found={len(found.bytes_)}B "
        f"absent={len(absent.bytes_)}B null={len(null_probe.bytes_)}B"
    )

    # No-source path emits NO compatible disclosures (backward-compat contract).
    assert _compat_rows(no_source) == {}, (
        "no-source path must emit no compatible disclosures "
        f"(got {sorted(_compat_rows(no_source))!r})"
    )
    # Every source-passing path DOES emit disclosures.
    assert set(_compat_rows(found)) == {"adau1979", "pcm1681"}
    assert set(_compat_rows(absent)) == {"adau1979", "pcm1681"}
    assert set(_compat_rows(null_probe)) == {"adau1979", "pcm1681"}
    print("PASS: byte-identity across {no-source, FOUND, ABSENT, null} — only disclosures differ")


# ── 3. ABSENT: fallback to hardcoded, marked NOT kernel-attested ────────────


def test_absent_falls_back_marked_not_attested() -> None:
    """Driver-absent → emit hardcoded value, disclosure marks NOT kernel-attested."""
    facts = _advisory_open_nord_facts()
    probe = CodecDriverProbe.from_tree(_ABSENT_TREE, _NORD_CODEC_KEYS)
    artifact = _artifact(facts, source=probe)

    rows = _compat_rows(artifact)
    text = artifact.bytes_.decode("utf-8")
    for key, hardcoded in (("adau1979", "adi,adau1979"), ("pcm1681", "ti,pcm1681")):
        head = rows[key].notes[0]
        assert "OBSERVED ABSENT" in head, f"{key} not marked ABSENT: {head!r}"
        assert "NOT kernel-attested" in head, f"{key} attestation caveat missing: {head!r}"
        assert "codec driver must" in head, (
            f"{key} note must state the driver has to be written first: {head!r}"
        )
        # Emitted value is still the hardcoded fallback (honest degradation).
        assert f'/* compatible = "{hardcoded}" */' in text, (
            f"{key} fallback value not emitted:\n{text}"
        )
    print("PASS: ABSENT — fallback to hardcoded value, disclosed NOT kernel-attested")


# ── 4. Join-key caveat present verbatim on every disclosure ─────────────────


def test_join_key_caveat_present_verbatim() -> None:
    """Every compatible disclosure carries the mandatory join-key caveat verbatim.

    Slice 1 REQUIRED disclosure: the attested VALUE is kernel_source but the
    LOOKUP KEY that selected the driver is candidate-derived (5267b2e1), so the
    value is only as trustworthy as the codec selection. Asserted across FOUND
    and ABSENT (the two source-passing states that emit disclosures).
    """
    expected = (
        "compatible attested from kernel driver of_match_table (kernel_source); "
        "codec-identity join key is candidate-derived (5267b2e1) — value is only "
        "as trustworthy as the codec selection."
    )
    # Guard the module constant against silent drift from the required wording.
    assert _JOIN_KEY_CAVEAT == expected, (
        f"_JOIN_KEY_CAVEAT drifted from the required verbatim wording:\n"
        f"  actual={_JOIN_KEY_CAVEAT!r}\n  required={expected!r}"
    )

    facts = _advisory_open_nord_facts()
    for label, tree in (("FOUND", _FOUND_TREE), ("ABSENT", _ABSENT_TREE)):
        artifact = _artifact(facts, source=CodecDriverProbe.from_tree(tree, _NORD_CODEC_KEYS))
        rows = _compat_rows(artifact)
        assert rows, f"{label}: expected compatible disclosures, got none"
        for key, row in rows.items():
            assert expected in row.notes, (
                f"{label}/{key}: join-key caveat missing from disclosure notes:\n"
                f"{row.notes!r}"
            )
    print("PASS: join-key caveat present verbatim on every FOUND/ABSENT disclosure")


# ── 5. Disclosure-only: probe never reaches facts, never changes the gate ───


def test_probe_never_reaches_trusted_facts() -> None:
    """The probe object is never stored on TrustedFacts (disclosure-only)."""
    facts = _advisory_open_nord_facts()
    probe = CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)
    _artifact(facts, source=probe)

    for row in facts.rows_by_track_subject.values():
        for attr_name in vars(row):
            attr = getattr(row, attr_name)
            assert not isinstance(attr, CodecDriverProbe), (
                f"CodecDriverProbe leaked onto TrustedFacts row attr {attr_name!r}"
            )
    print("PASS: probe never stored on TrustedFacts (disclosure-only)")


def test_probe_does_not_change_emit_gate() -> None:
    """Every probe state emits an artifact — the probe cannot open/close a gate.

    The gate decision is driven solely by the TrustedFacts rows; the probe is
    disclosure-only. FOUND, ABSENT, null, and no-source must all emit (the
    facts open the advisory gate) — the probe only shifts provenance/notes.
    """
    facts = _advisory_open_nord_facts()
    states = {
        "no_source": generate_codec_stub(facts, source=None),
        "found": generate_codec_stub(
            facts, source=CodecDriverProbe.from_tree(_FOUND_TREE, _NORD_CODEC_KEYS)
        ),
        "absent": generate_codec_stub(
            facts, source=CodecDriverProbe.from_tree(_ABSENT_TREE, _NORD_CODEC_KEYS)
        ),
        "null": generate_codec_stub(
            facts, source=CodecDriverProbe.from_tree(None, _NORD_CODEC_KEYS)
        ),
    }
    for label, result in states.items():
        assert isinstance(result, GeneratedArtifact), (
            f"{label}: probe changed the emit gate (expected artifact, got "
            f"{type(result).__name__})"
        )
    print("PASS: no probe state changes the emit gate (all emit; probe is disclosure-only)")


def main() -> None:
    test_found_attests_compatible_from_kernel_source()   # 1
    test_byte_identity_found_equals_no_source()          # 2
    test_absent_falls_back_marked_not_attested()         # 3
    test_join_key_caveat_present_verbatim()              # 4
    test_probe_never_reaches_trusted_facts()             # 5
    test_probe_does_not_change_emit_gate()               # 5b
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
