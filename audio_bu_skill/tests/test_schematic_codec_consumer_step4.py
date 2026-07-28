"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 4 — codec_stub consumer of schematic leaves.

Step 3b (bb4a3e5) persisted the ``attestation`` block onto the applied
FactRecord and made ``to_dict()`` serialize it (only when non-None). Step 4 is
the CONSUMER: ``generate_codec_stub`` reads the schematic leaves
(``i2c_bus_label`` / ``i2c_address`` / ``reset_gpios``) from the RAW-DICT
template and, when a leaf is ATTESTED, emits its value WITH the pinned
disclosure comment::

    schematic-attested (<X>), NOT IPCAT-cross-verified

where ``<X>`` is the leaf's ``attestation.evidence`` (now reachable in the raw
dict).

Contract pinned by these tests (each maps 1:1 to a spec bullet):

  1. ATTESTED synthetic leaf -> value emitted WITH the pinned comment, sheet <X>
     sourced from ``attestation.evidence`` (built via the REAL projector, not a
     hand-rolled dict — so identity-join + serialization order are exercised).
  2. ATTESTED leaf whose evidence is missing AT THE CONSUMER -> loud ValueError
     (defence-in-depth; the validator already blocks empty evidence upstream,
     but a raw dict handed in directly must still be refused).
  3. NOT_ATTESTED leaf (and the un-curated Nord path) -> hardcoded fallback,
     BYTE-IDENTICAL to the committed 0f81452 fixture. PROVEN, not asserted.
  4. import-guard: ``codec_stub.py`` MUST NOT import
     ``orchestrator.hw_template.model`` (WP-64 firewall — the template is a raw
     dict). AST-checked here explicitly (the pre-existing ``test_import_guard``
     forbidden set did not name hw_template.model).
  5. firewall: consuming a template MUST NOT write ``cross_verification`` /
     ``TrustedFacts`` — the schematic value is disclosure-only. The ``facts``
     object and the input dict are unchanged after the call.
  6. Nord byte-identity WITHOUT any template (backward-compat) — the pre-step-4
     path (``generate_codec_stub(facts)``) is unperturbed.

The synthetic fixtures are built through the projector (mirroring
``test_schematic_attestation_persist_step3b.py``) so the raw dict has exactly
the shape the consumer will meet in production. The byte-identity anchor reads
the committed Nord template + WP2 facts fixtures.

Run: ``PYTHONPATH=.:audio_bu_skill python -m pytest \
    audio_bu_skill/tests/test_schematic_codec_consumer_step4.py -q``
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.generation import codec_stub as codec_module
from orchestrator.generation.codec_stub import generate_codec_stub
from orchestrator.generation.model import GeneratedArtifact, TrustedFacts
from orchestrator.hw_template.projector import project
from orchestrator.reasoning.crossverify_model import VerificationRow

_FIXTURES = _REPO / "tests" / "fixtures" / "phase2b"
_NORD_DIR = _REPO / "targets" / "nord-iq10"
_NORD_TEMPLATE = _NORD_DIR / "h1_validation" / "audio_hardware_template.json"

_SHEET = "Schematic LD20-94440 rev A, audio sheet"
_PINNED_SUFFIX = ", NOT IPCAT-cross-verified"


# ── shared builders (mirror test_generation_codec + step3b) ──────────────────


def _rehydrate_wp2_fixture() -> TrustedFacts:
    """Rehydrate the committed Nord WP2 facts fixture → TrustedFacts.

    Identical to ``test_generation_codec._rehydrate_wp2_fixture`` — kept local
    so this test file stands alone (no cross-test-module import coupling).
    """
    path = _FIXTURES / "nord_trusted_facts.json"
    assert path.is_file(), f"missing WP2 fixture: {path!r}"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, VerificationRow] = {}
    for key, rd in data["rows_by_track_subject"].items():
        rows[key] = VerificationRow(
            track=rd["track"],
            subject=rd["subject"],
            verdict=rd["verdict"],
            source=rd.get("source", {}),
            authority=rd.get("authority"),
            confidence=rd.get("confidence", "none"),
            coverage_gap_reason=rd.get("coverage_gap_reason"),
            rule_id=rd.get("rule_id"),
            warning=rd.get("warning"),
            review_actions=list(rd.get("review_actions", [])),
            citations=list(rd.get("citations", [])),
            notes=list(rd.get("notes", [])),
        )
    return TrustedFacts(rows_by_track_subject=rows)


def _gc_two_codecs() -> dict:
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


def _codec_override(codec_key: str, field: str, value, *, evidence: str = _SHEET) -> dict:
    return {
        f"codecs.{codec_key}.{field}": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": evidence,
                "target": "synth-t",
            },
        }
    }


def _projected_raw_template(overrides: dict | None) -> dict:
    """Project a synthetic 2-codec target through the REAL projector and return
    ``template.to_dict()`` — the exact raw dict the consumer meets in prod."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        result = project(
            gc=_gc_two_codecs(),
            target_name="synth-t",
            run_id="step4-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
    return result.template.to_dict()


def _emit_text(facts: TrustedFacts, template: dict | None) -> str:
    result = generate_codec_stub(facts, template=template)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact, got {type(result).__name__}: {result!r}"
    )
    return result.bytes_.decode("utf-8")


# ── 1. ATTESTED schematic leaf -> value emitted WITH the pinned comment ──────


def test_attested_i2c_address_emits_value_with_pinned_comment() -> None:
    """An ATTESTED ``i2c_address`` override flows through to the emitted stub as
    the schematic value + the pinned ``schematic-attested (<X>) ...``
    comment, with <X> sourced from ``attestation.evidence``."""
    template = _projected_raw_template(_codec_override("adau1979", "i2c_address", "0x31"))
    text = _emit_text(_rehydrate_wp2_fixture(), template)

    expected_line = (
        f"\t.addr = 0x31,  /* schematic-attested ({_SHEET})"
        f"{_PINNED_SUFFIX} */"
    )
    assert expected_line in text, (
        "ATTESTED i2c_address did not emit the pinned schematic-attested line.\n"
        f"expected: {expected_line!r}\n"
        f"emitted:\n{text}"
    )
    # The un-curated peer (pcm1681) still fires the hardcoded fallback.
    assert "\t.addr = 0x4c," in text, f"pcm1681 fallback missing:\n{text}"
    # The sheet <X> in the comment is exactly the attestation.evidence string.
    assert _SHEET in text
    print("PASS: ATTESTED i2c_address emits schematic value + pinned comment")


def test_attested_bus_and_reset_emit_disclosure_comments() -> None:
    """ATTESTED ``i2c_bus_label`` and ``reset_gpios`` each surface as a pinned
    disclosure comment line (not a raw value line — they are DT-context notes)."""
    overrides = {}
    overrides.update(_codec_override("adau1979", "i2c_bus_label", "&i2c18"))
    overrides.update(_codec_override("adau1979", "reset_gpios", "gpio77"))
    template = _projected_raw_template(overrides)
    text = _emit_text(_rehydrate_wp2_fixture(), template)

    assert (
        f"/* control bus: &i2c18  schematic-attested ({_SHEET})"
        f"{_PINNED_SUFFIX} */" in text
    ), f"i2c_bus_label disclosure missing:\n{text}"
    assert (
        f"/* reset-gpios: gpio77  schematic-attested ({_SHEET})"
        f"{_PINNED_SUFFIX} */" in text
    ), f"reset_gpios disclosure missing:\n{text}"
    print("PASS: ATTESTED bus + reset emit pinned disclosure comments")


# ── 2. ATTESTED leaf, evidence missing AT CONSUMER -> loud error ─────────────


def test_attested_leaf_missing_evidence_at_consumer_raises() -> None:
    """A raw dict handed to the consumer with an ATTESTED leaf but NO
    ``attestation.evidence`` sheet is refused loudly — the consumer must never
    emit an uncited schematic value, even if the upstream validator is bypassed
    (e.g. a hand-edited template dict)."""
    # Build a valid ATTESTED template, then strip evidence at the raw-dict level
    # to simulate a bypassed/hand-edited template reaching the consumer.
    template = _projected_raw_template(_codec_override("adau1979", "i2c_address", "0x31"))
    for codec in template["codecs"]:
        pn = codec["part_number"]
        if (pn.get("value") or pn.get("candidate_value")) == "adau1979":
            codec["i2c_address"]["attestation"]["evidence"] = ""

    with pytest.raises(ValueError, match="attestation.evidence"):
        generate_codec_stub(_rehydrate_wp2_fixture(), template=template)
    print("PASS: consumer refuses ATTESTED leaf with empty evidence")


def test_attested_leaf_no_attestation_block_at_consumer_raises() -> None:
    """ATTESTED leaf whose ``attestation`` block is entirely absent -> loud."""
    template = _projected_raw_template(_codec_override("pcm1681", "i2c_address", "0x4c"))
    for codec in template["codecs"]:
        pn = codec["part_number"]
        if (pn.get("value") or pn.get("candidate_value")) == "pcm1681":
            codec["i2c_address"].pop("attestation", None)

    with pytest.raises(ValueError, match="attestation.evidence"):
        generate_codec_stub(_rehydrate_wp2_fixture(), template=template)
    print("PASS: consumer refuses ATTESTED leaf with no attestation block")


# ── 3. NOT_ATTESTED / Nord -> hardcoded fallback, byte-identical ─────────────


def test_not_attested_template_is_byte_identical_to_no_template() -> None:
    """A projected template with ZERO curated overrides (every leaf
    NOT_ATTESTED, both codec identities null) contributes NO value — the emitted
    bytes are IDENTICAL to the no-template call."""
    facts = _rehydrate_wp2_fixture()
    template = _projected_raw_template(None)

    with_template = generate_codec_stub(facts, template=template)
    without_template = generate_codec_stub(facts)

    assert isinstance(with_template, GeneratedArtifact)
    assert isinstance(without_template, GeneratedArtifact)
    assert with_template.bytes_ == without_template.bytes_, (
        "NOT_ATTESTED template perturbed the bytes — fallback did not fire.\n"
        f"with-template (first 400): {with_template.bytes_[:400]!r}\n"
        f"without-template (first 400): {without_template.bytes_[:400]!r}"
    )
    print("PASS: NOT_ATTESTED template == no-template bytes")


def test_nord_byte_identity_with_real_committed_template() -> None:
    """NON-NEGOTIABLE: feed the REAL committed Nord template to the consumer
    alongside the real Nord WP2 facts -> byte-identical to the frozen
    ``nord_codec_stub_attested_expected.c``.

    WP-CODEC-IDENTITY-ATTEST Part 2 filled five schematic leaves into Nord's
    curated_overrides.json, so the committed template now carries ATTESTED
    i2c_address values (0x31 for adau1979, 0x4c for pcm1681). The consumer
    therefore emits each ``.addr`` line WITH the pinned
    ``schematic-attested (<X>), NOT IPCAT-cross-verified`` provenance
    comment. The numeric addresses are unchanged from the plain path (the
    ``_NORD_CODECS`` fallback already carried them) — the delta is disclosure
    ONLY. Proven against the attested fixture, not asserted by fiat.
    """
    facts = _rehydrate_wp2_fixture()
    nord_template = json.loads(_NORD_TEMPLATE.read_text(encoding="utf-8"))

    result = generate_codec_stub(facts, template=nord_template)
    assert isinstance(result, GeneratedArtifact), (
        f"expected GeneratedArtifact, got {type(result).__name__}"
    )
    assert result.contributes_rows == [], (
        f"template consumption must not add rows on Nord, got: "
        f"{[r.subject for r in result.contributes_rows]!r}"
    )

    expected_path = _FIXTURES / "nord_codec_stub_attested_expected.c"
    assert expected_path.is_file(), f"missing fixture: {expected_path!r}"
    expected_bytes = expected_path.read_bytes()
    assert result.bytes_ == expected_bytes, (
        f"Nord codec_stub drifted with the real committed (filled) template.\n"
        f"actual (first 400): {result.bytes_[:400]!r}\n"
        f"expected (first 400): {expected_bytes[:400]!r}"
    )
    print("PASS: Nord + real committed filled template == attested fixture (byte-identical)")


def test_nord_byte_identity_no_template_backward_compat() -> None:
    """Backward-compat: the pre-step-4 path (no template kwarg) is unperturbed
    — byte-identical to the frozen fixture."""
    facts = _rehydrate_wp2_fixture()
    result = generate_codec_stub(facts)
    expected_bytes = (_FIXTURES / "nord_codec_stub_expected.c").read_bytes()
    assert isinstance(result, GeneratedArtifact)
    assert result.bytes_ == expected_bytes
    print("PASS: no-template path byte-identical (backward-compat)")


# ── 4. import-guard: no hw_template.model import (WP-64 firewall) ────────────


def test_codec_stub_does_not_import_hw_template_model() -> None:
    """The consumer reads the template as a RAW DICT. It MUST NOT import
    ``orchestrator.hw_template.model`` (or any hw_template submodule) — that is
    the WP-64 firewall. AST-checked; the pre-existing ``test_import_guard``
    forbidden set did not name hw_template, so this closes the gap explicitly."""
    src_path = Path(inspect.getfile(codec_module))
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "orchestrator.hw_template" or module.startswith(
                "orchestrator.hw_template."
            ):
                offenders.append(f"from {module} import ... (line {node.lineno})")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "orchestrator.hw_template" or alias.name.startswith(
                    "orchestrator.hw_template."
                ):
                    offenders.append(f"import {alias.name} (line {node.lineno})")

    assert not offenders, (
        "WP-64 firewall breach: codec_stub.py imports hw_template — the template "
        f"must be consumed as a raw dict. Offenders: {offenders!r}"
    )
    print("PASS: codec_stub.py imports no hw_template.* module")


# ── 5. firewall: template consumption is disclosure-only ─────────────────────


def test_template_consumption_does_not_mutate_facts_or_template() -> None:
    """Emitting from an ATTESTED template MUST NOT write back into the facts
    projection or mutate the input template dict — the schematic value is
    disclosure-only and never re-enters cross_verification / TrustedFacts."""
    facts = _rehydrate_wp2_fixture()
    facts_rows_before = {
        k: v.to_dict() for k, v in facts.rows_by_track_subject.items()
    }
    template = _projected_raw_template(_codec_override("adau1979", "i2c_address", "0x31"))
    template_before = deepcopy(template)

    generate_codec_stub(facts, template=template)

    facts_rows_after = {
        k: v.to_dict() for k, v in facts.rows_by_track_subject.items()
    }
    assert facts_rows_after == facts_rows_before, (
        "template consumption mutated the TrustedFacts rows — firewall breach"
    )
    assert template == template_before, (
        "template consumption mutated the input template dict"
    )
    # And no schematic-attested row leaked into contributes_rows as an authority.
    result = generate_codec_stub(facts, template=template)
    for row in result.contributes_rows:
        assert row.verdict != "MATCH", (
            f"schematic value promoted to a MATCH row: {row.subject!r}"
        )
    print("PASS: template consumption is disclosure-only (no facts/template mutation)")


# ── standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_attested_i2c_address_emits_value_with_pinned_comment()
    test_attested_bus_and_reset_emit_disclosure_comments()
    test_attested_leaf_missing_evidence_at_consumer_raises()
    test_attested_leaf_no_attestation_block_at_consumer_raises()
    test_not_attested_template_is_byte_identical_to_no_template()
    test_nord_byte_identity_with_real_committed_template()
    test_nord_byte_identity_no_template_backward_compat()
    test_codec_stub_does_not_import_hw_template_model()
    test_template_consumption_does_not_mutate_facts_or_template()
    print("\nAll step-4 consumer tests passed.")
