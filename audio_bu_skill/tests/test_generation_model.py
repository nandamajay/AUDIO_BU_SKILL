"""Phase-2B WP1a — tests for the generation model dataclasses.

Pure, stdlib-only tests over ``orchestrator.generation.model``. Mirrors the
Phase-2A test discipline: inline fixtures, no fakes, no network. Seven tests
per PHASE2B_SPECIFICATION.md §WP1a:

  1. ``test_generated_artifact_frozen_and_serializable``
  2. ``test_generator_skipped_frozen_and_serializable``
  3. ``test_generation_result_union_type``
  4. ``test_trusted_facts_projection_and_is_open``
  5. ``test_sort_keys_deterministic``
  6. ``test_to_dict_json_roundtrip``
  7. ``test_import_guard_no_config_import``

Test 7 is a *static-source* import guard — it inspects ``model.py`` as text
and asserts no ``from orchestrator.generation.config`` / ``import
orchestrator.generation.config`` line is present. This is the WP1a-side
half of the invariant "model is independent of policy"; the WP1b lint test
enforces the reverse (``reasoning/*`` may not import ``generation/*``).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_model``
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
from typing import Union, get_args, get_origin

from orchestrator.generation import model as gen_model
from orchestrator.generation.model import (
    GeneratedArtifact,
    GenerationResult,
    GeneratorSkipped,
    TrustedFacts,
    sort_key_for_result,
)
from orchestrator.reasoning.crossverify_model import VerificationRow


# ── Fixture builders ────────────────────────────────────────────────────────


def _row(
    *,
    track: str = "T5",
    subject: str = "dts.firmware",
    verdict: str = "MATCH",
    warning: bool = False,
    coverage_gap_reason: str | None = None,
) -> VerificationRow:
    """Minimal VerificationRow — only the fields ``is_open`` inspects vary.

    ``coverage_gap_reason`` is auto-supplied (``authority_out_of_scope``) for
    ``NOT_CROSS_CHECKABLE`` verdicts so callers of the test helper don't have
    to remember the __post_init__ invariant; caller may override.
    """
    if verdict == "NOT_CROSS_CHECKABLE" and coverage_gap_reason is None:
        coverage_gap_reason = "authority_out_of_scope"
    return VerificationRow(
        track=track,
        subject=subject,
        verdict=verdict,
        source={},
        authority={"strength": "IPCAT_DIRECT", "origin": "test", "value": {}},
        confidence="high",
        warning=warning,
        coverage_gap_reason=coverage_gap_reason,
    )


def _artifact(
    *,
    subject: str = "adsp@30000000",
    artifact_class: str = "dts.node",
    path_hint: str = "arch/arm64/boot/dts/qcom/foo.dtsi",
    bytes_: bytes = b"remoteproc_adsp { compatible = \"qcom,sa8797p-adsp-pas\"; };\n",
    contributes_rows: list[VerificationRow] | None = None,
) -> GeneratedArtifact:
    return GeneratedArtifact(
        subject=subject,
        artifact_class=artifact_class,
        path_hint=path_hint,
        bytes_=bytes_,
        contributes_rows=list(contributes_rows) if contributes_rows is not None else [],
    )


def _skipped(
    *,
    subject: str = "adsp@30000000",
    artifact_class: str = "dts.node",
    reason: str = "gate_closed",
    gating_rows: list[str] | None = None,
) -> GeneratorSkipped:
    return GeneratorSkipped(
        subject=subject,
        artifact_class=artifact_class,
        reason=reason,
        gating_rows=list(gating_rows) if gating_rows is not None else [],
    )


# ── 1. GeneratedArtifact — frozen, serializable, fixed key order ────────────


def test_generated_artifact_frozen_and_serializable() -> None:
    """GeneratedArtifact is a frozen dataclass with a deterministic to_dict()."""
    row = _row()
    art = _artifact(contributes_rows=[row])

    # frozen — mutation raises FrozenInstanceError
    try:
        art.subject = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("GeneratedArtifact must be frozen")

    # to_dict shape & key order
    d = art.to_dict()
    assert list(d.keys()) == [
        "kind",
        "artifact_class",
        "subject",
        "path_hint",
        "bytes_hex",
        "contributes_rows",
    ], f"unexpected key order: {list(d.keys())}"
    assert d["kind"] == "GeneratedArtifact"
    assert d["artifact_class"] == "dts.node"
    assert d["subject"] == "adsp@30000000"
    assert d["path_hint"] == "arch/arm64/boot/dts/qcom/foo.dtsi"
    # bytes_ hex-encoded (round-trippable)
    assert d["bytes_hex"] == art.bytes_.hex()
    assert bytes.fromhex(d["bytes_hex"]) == art.bytes_
    # contributes_rows are VerificationRow.to_dict() shapes
    assert len(d["contributes_rows"]) == 1
    assert d["contributes_rows"][0] == row.to_dict()

    # empty contributes_rows default
    empty = _artifact()
    assert empty.to_dict()["contributes_rows"] == []
    print("PASS: GeneratedArtifact frozen + to_dict deterministic")


# ── 2. GeneratorSkipped — frozen, serializable, fixed key order ─────────────


def test_generator_skipped_frozen_and_serializable() -> None:
    """GeneratorSkipped is a frozen dataclass with a deterministic to_dict()."""
    sk = _skipped(reason="gate_closed", gating_rows=["T5.dts.firmware", "T5.dts.compatible"])

    try:
        sk.reason = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("GeneratorSkipped must be frozen")

    d = sk.to_dict()
    assert list(d.keys()) == [
        "kind",
        "artifact_class",
        "subject",
        "reason",
        "gating_rows",
    ], f"unexpected key order: {list(d.keys())}"
    assert d["kind"] == "GeneratorSkipped"
    assert d["reason"] == "gate_closed"
    # order-preserving copy — not sorted
    assert d["gating_rows"] == ["T5.dts.firmware", "T5.dts.compatible"]
    # to_dict returns a copy — mutating it does not touch the frozen dataclass
    d["gating_rows"].append("mutated")
    assert sk.gating_rows == ["T5.dts.firmware", "T5.dts.compatible"]

    # empty gating_rows default
    assert _skipped().to_dict()["gating_rows"] == []
    print("PASS: GeneratorSkipped frozen + to_dict deterministic")


# ── 3. GenerationResult — union type of the two branches ────────────────────


def test_generation_result_union_type() -> None:
    """GenerationResult is a Union of the two dataclasses (both members present)."""
    # typing.get_origin/get_args works for typing.Union.
    origin = get_origin(GenerationResult)
    assert origin is Union, f"GenerationResult origin should be typing.Union, got {origin!r}"
    args = set(get_args(GenerationResult))
    assert args == {GeneratedArtifact, GeneratorSkipped}, (
        f"GenerationResult members must be exactly {{GeneratedArtifact, GeneratorSkipped}}, got {args!r}"
    )

    # both concrete values are structurally acceptable — no isinstance branch
    # at the callsite is needed for the common sort key.
    art = _artifact(artifact_class="dts.node", subject="a")
    sk = _skipped(artifact_class="c.file", subject="b")
    mixed = [art, sk]
    mixed.sort(key=sort_key_for_result)
    assert [x.artifact_class for x in mixed] == ["c.file", "dts.node"]
    print("PASS: GenerationResult is a Union of both branches + sort_key_for_result works")


# ── 4. TrustedFacts — projection + is_open gating rules (§4) ────────────────


def test_trusted_facts_projection_and_is_open() -> None:
    """is_open covers §4 gating rules; missing rows fail closed."""
    rows = {
        # MATCH → open
        "T5.dts.firmware": _row(verdict="MATCH"),
        # PARTIAL_MATCH → open (type layer; donor-residue exception is WP1b policy)
        "T3.dmic_line": _row(track="T3", subject="dmic_line", verdict="PARTIAL_MATCH"),
        # NCC → closed regardless of coverage_gap_reason
        "T3.soundwire_master": _row(
            track="T3", subject="soundwire_master", verdict="NOT_CROSS_CHECKABLE"
        ),
        # REVIEW_REQUIRED → closed
        "T4a.foo": _row(track="T4a", subject="foo", verdict="REVIEW_REQUIRED"),
        # DISAGREE → closed
        "T2.soundwire_master": _row(
            track="T2", subject="soundwire_master", verdict="DISAGREE_WITH_AUTHORITY"
        ),
        # warning=True + MATCH → closed (warning is fatal)
        "T3.speaker": _row(track="T3", subject="speaker", verdict="MATCH", warning=True),
    }
    tf = TrustedFacts(rows_by_track_subject=dict(rows))

    assert tf.is_open("T5", "dts.firmware") is True
    assert tf.is_open("T3", "dmic_line") is True
    assert tf.is_open("T3", "soundwire_master") is False
    assert tf.is_open("T4a", "foo") is False
    assert tf.is_open("T2", "soundwire_master") is False
    assert tf.is_open("T3", "speaker") is False, "warning=True must close the gate"
    # missing row — fail closed (§4.2)
    assert tf.is_open("T99", "does.not.exist") is False

    # frozen
    try:
        tf.rows_by_track_subject = {}  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("TrustedFacts must be frozen")

    # deterministic to_dict — rows serialized in sorted-key order
    d = tf.to_dict()
    assert list(d.keys()) == ["rows_by_track_subject"]
    inner = d["rows_by_track_subject"]
    assert list(inner.keys()) == sorted(rows.keys()), (
        f"rows_by_track_subject must be emitted in sorted key order, got {list(inner.keys())}"
    )
    # each value is a VerificationRow.to_dict() projection
    assert inner["T5.dts.firmware"] == rows["T5.dts.firmware"].to_dict()

    # empty TrustedFacts is also valid
    empty = TrustedFacts()
    assert empty.to_dict() == {"rows_by_track_subject": {}}
    assert empty.is_open("anything", "goes") is False
    print("PASS: TrustedFacts projection + is_open honours §4 gating (incl. warning=True)")


# ── 5. Sort keys — class-level, deterministic, common shape ─────────────────


def test_sort_keys_deterministic() -> None:
    """Sort keys are defined at the class level and sort stably."""
    arts = [
        _artifact(artifact_class="c.file", subject="b"),
        _artifact(artifact_class="dts.node", subject="a"),
        _artifact(artifact_class="c.file", subject="a"),
    ]
    arts.sort(key=GeneratedArtifact.sort_key)
    assert [(a.artifact_class, a.subject) for a in arts] == [
        ("c.file", "a"),
        ("c.file", "b"),
        ("dts.node", "a"),
    ]

    sks = [
        _skipped(artifact_class="dts.node", subject="z"),
        _skipped(artifact_class="c.file", subject="a"),
    ]
    sks.sort(key=GeneratorSkipped.sort_key)
    assert [(s.artifact_class, s.subject) for s in sks] == [
        ("c.file", "a"),
        ("dts.node", "z"),
    ]

    # mixed list — same shape from both branches
    mixed: list[GenerationResult] = [
        _artifact(artifact_class="dts.node", subject="a"),
        _skipped(artifact_class="c.file", subject="a"),
        _artifact(artifact_class="c.file", subject="b"),
    ]
    mixed.sort(key=sort_key_for_result)
    assert [(x.artifact_class, x.subject) for x in mixed] == [
        ("c.file", "a"),
        ("c.file", "b"),
        ("dts.node", "a"),
    ]

    # sort_key methods are attributes on the class (importable by WP1b/WP7/WP10)
    assert callable(GeneratedArtifact.sort_key)
    assert callable(GeneratorSkipped.sort_key)
    print("PASS: sort keys defined at class level; mixed list sorts stably")


# ── 6. to_dict JSON round-trip — byte-stable across runs ────────────────────


def test_to_dict_json_roundtrip() -> None:
    """json.dumps(..., sort_keys=True) succeeds and byte-round-trips."""
    row_a = _row(track="T3", subject="dmic_line", verdict="MATCH")
    row_b = _row(track="T5", subject="dts.firmware", verdict="MATCH")
    art = _artifact(
        artifact_class="dts.node",
        subject="adsp",
        bytes_=b"\x00\x01\xff hello \xaa",
        contributes_rows=[row_a, row_b],
    )
    sk = _skipped(
        artifact_class="c.file",
        subject="sound-card.c",
        reason="gate_closed",
        gating_rows=["T5.dts.firmware"],
    )
    tf = TrustedFacts(rows_by_track_subject={"T5.dts.firmware": row_b, "T3.dmic_line": row_a})

    for obj in (art, sk, tf):
        d = obj.to_dict()
        # sort_keys=True must succeed (i.e., all keys are strings, all values JSON)
        s1 = json.dumps(d, sort_keys=True)
        # round-trip: parse back and re-dump — byte-equal (canonical form)
        d2 = json.loads(s1)
        s2 = json.dumps(d2, sort_keys=True)
        assert s1 == s2, f"json round-trip drift on {type(obj).__name__}: {s1!r} vs {s2!r}"
        # repeated to_dict on the same input is byte-equal
        assert json.dumps(obj.to_dict(), sort_keys=True) == s1

    # cross-branch: mixed-list serialization is stable in sort_key_for_result order
    mixed: list[GenerationResult] = [sk, art]
    mixed.sort(key=sort_key_for_result)
    payload = json.dumps([x.to_dict() for x in mixed], sort_keys=True)
    assert json.dumps([x.to_dict() for x in sorted(mixed, key=sort_key_for_result)],
                      sort_keys=True) == payload
    print("PASS: to_dict JSON round-trips byte-stably (sort_keys=True)")


# ── 7. Import guard — model.py does not import from generation/config ───────


def test_import_guard_no_config_import() -> None:
    """Static-source check: ``model.py`` must not import from ``generation.config``.

    The invariant per PHASE2B_SPECIFICATION.md §WP1a is that model is
    independent of policy — the *types* live here; the *rules* live in
    ``generation/config.py`` (WP1b). A regex over the source lets us catch
    both ``from orchestrator.generation.config import X`` and
    ``import orchestrator.generation.config`` (and their relative-import
    equivalents).

    We look at the source file, not runtime state — an import that only
    executes under a certain codepath still counts as a violation and
    must be caught here.
    """
    src = inspect.getsource(gen_model)
    # Any form of importing from generation.config is forbidden.
    forbidden_patterns = [
        # absolute — with or without an aliased "as X"
        r"\bfrom\s+orchestrator\.generation\.config\b",
        r"\bimport\s+orchestrator\.generation\.config\b",
        # relative — from . import config / from .config import ...
        r"\bfrom\s+\.config\b",
        r"\bfrom\s+\.\s+import\s+config\b",
    ]
    for pat in forbidden_patterns:
        matches = re.findall(pat, src)
        # Filter to code lines only — comments and docstrings can mention "config"
        # freely, but no *statement* may match. A simple check: strip out lines
        # that are inside a docstring or begin with '#'. The regexes above
        # anchor on `from`/`import` keywords, which don't appear at the start of
        # our docstring lines. Still, defend explicitly:
        code_lines = [
            ln for ln in src.splitlines()
            if not ln.lstrip().startswith("#")
        ]
        real_matches = [
            ln for ln in code_lines
            if re.search(pat, ln) and not ln.lstrip().startswith('"')
        ]
        assert not real_matches, (
            f"import guard failed: model.py must not import from generation.config "
            f"(pattern {pat!r} matched lines: {real_matches!r})"
        )

    # And a positive check: the module DOES import VerificationRow (proof the
    # test is looking at the right file and would fail on a real violation).
    assert re.search(
        r"\bfrom\s+orchestrator\.reasoning\.crossverify_model\s+import\s+VerificationRow\b",
        src,
    ), "sanity: model.py should import VerificationRow from crossverify_model"
    print("PASS: model.py has no import from generation.config (import guard held)")


def main() -> None:
    test_generated_artifact_frozen_and_serializable()  # 1
    test_generator_skipped_frozen_and_serializable()   # 2
    test_generation_result_union_type()                # 3
    test_trusted_facts_projection_and_is_open()        # 4
    test_sort_keys_deterministic()                     # 5
    test_to_dict_json_roundtrip()                      # 6
    test_import_guard_no_config_import()               # 7
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
