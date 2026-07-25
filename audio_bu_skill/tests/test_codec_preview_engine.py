"""CodecPreviewEngine tests (WP G-3B-beta).

Enforces the WP contract:

1. Engine is registered under ``"codec_preview"`` and resolvable via the ABC
   factory. Default remains ``NullEngine``.
2. Every emitted ``Change`` carries provenance disclosures + reviewer
   disclosures in ``needs_review``, and a preview body in ``rationale``.
3. Nothing the engine emits is shaped to be indexed as
   ``cross_verification.rows`` (disclosure-only invariant).
4. Pipeline 1 (``orchestrator/generation``) is not touched — byte-identity
   check on the three modules under lock: ``codec_stub.py``, ``model.py``,
   ``__init__.py``.
5. The engine never writes to disk.
6. Runner injects the provenance dict into the task_spec.

Real-Nord profile shape (grep-verified against
``audio_bu_skill/targets/nord-iq10/profile.json``): flat top-level with
``codec_source`` (str), ``codecs`` (list[str] of ``vendor,part``), no
``_reasoning`` top-level.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from orchestrator.codegen import (
    CodecPreviewEngine,
    NullEngine,
    resolve_engine,
)
from orchestrator.codegen.models import ChangeSet
from orchestrator.runners.codec_generation_runner import run_codec_generation


# Real-Nord profile shape (grep-verified), minimal subset the engine reads.
_NORD_PROFILE = {
    "target_name": "nord-iq10",
    "codec_source": "/tmp/g3a9-candidate/iq10-evk.dts",
    "codecs": ["adi,adau1979", "ti,pcm1681"],
    "cites": {
        "soc": ["ipcat://sa8797p"],
        "power_model": ["ipcat://sa8797p/power"],
        "soundwire": ["ipcat://sa8797p/soundwire"],
    },
}

_TASK_SPEC_MINIMAL = {
    "skill_id": "codec_generation",
    "target": "nord-iq10",
    "run_id": "test-run-1",
    "target_profile": _NORD_PROFILE,
}


# ---------------------------------------------------------------------------
# 1. Factory registration
# ---------------------------------------------------------------------------

def test_null_engine_still_default() -> None:
    """The inert NullEngine must remain the default. Codec preview is opt-in."""
    engine = resolve_engine()
    assert isinstance(engine, NullEngine)


def test_codec_preview_resolvable_by_name() -> None:
    engine = resolve_engine("codec_preview")
    assert isinstance(engine, CodecPreviewEngine)
    assert engine.engine_id == "codec_preview"


def test_unknown_name_still_falls_back_to_null() -> None:
    engine = resolve_engine("does_not_exist")
    assert isinstance(engine, NullEngine)


# ---------------------------------------------------------------------------
# 2. Emit shape
# ---------------------------------------------------------------------------

def test_two_codec_profile_emits_two_changes() -> None:
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    assert isinstance(cs, ChangeSet)
    assert cs.engine_id == "codec_preview"
    assert cs.skill_id == "codec_generation"
    assert cs.target == "nord-iq10"
    assert not cs.is_empty()
    assert len(cs.changes) == 2
    # Deterministic: sorted by part.
    paths = [c.path for c in cs.changes]
    assert paths == sorted(paths)


def test_change_path_shape() -> None:
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    for change in cs.changes:
        assert change.path.startswith("sound/soc/codecs/")
        assert change.path.endswith("-preview.c")
        assert change.change_type == "create"
        assert change.skill_id == "codec_generation"
        assert change.unified_diff == ""  # foundation contract


def test_empty_codecs_returns_empty_changeset() -> None:
    spec = {
        "skill_id": "codec_generation",
        "target": "nord-iq10",
        "run_id": "test-empty",
        "target_profile": {"codecs": [], "codec_source": None},
    }
    cs = CodecPreviewEngine().generate(spec)
    assert cs.is_empty()
    assert "skipped" in cs.summary
    assert cs.engine_id == "codec_preview"


def test_malformed_codec_entries_are_skipped() -> None:
    spec = {
        "skill_id": "codec_generation",
        "target": "nord-iq10",
        "run_id": "test-malformed",
        "target_profile": {
            "codecs": ["no_comma_here", ",", "adi,adau1979", "  ,  "],
            "codec_source": None,
        },
    }
    cs = CodecPreviewEngine().generate(spec)
    # Only the well-formed adi,adau1979 survives.
    assert len(cs.changes) == 1
    assert "adau1979" in cs.changes[0].path


# ---------------------------------------------------------------------------
# 3. Provenance labels
# ---------------------------------------------------------------------------

def test_provenance_labels_present_when_codec_source_populated() -> None:
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    expected_candidate = (
        "PROVENANCE: codec source is candidate-derived from "
        "/tmp/g3a9-candidate/iq10-evk.dts, NOT independently verified"
    )
    expected_t4a = (
        "PROVENANCE: T4a QUP MATCH is same-source (IPCAT-vs-IPCAT); "
        "NOT cross-verified per G-3A.11"
    )
    for change in cs.changes:
        assert expected_candidate in change.needs_review
        assert expected_t4a in change.needs_review


def test_provenance_labeled_when_no_codec_source() -> None:
    spec = {
        "skill_id": "codec_generation",
        "target": "nord-iq10",
        "run_id": "test-no-src",
        "target_profile": {"codecs": ["adi,adau1979"], "codec_source": None},
    }
    cs = CodecPreviewEngine().generate(spec)
    assert len(cs.changes) == 1
    absent_line = "PROVENANCE: no codec source path provided"
    # Absence is reported explicitly, never silently dropped.
    assert absent_line in cs.changes[0].needs_review


def test_reviewer_disclosures_deterministic_order() -> None:
    a = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    b = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        b.to_dict(), sort_keys=True
    )


def test_preview_body_in_rationale() -> None:
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    for change in cs.changes:
        assert change.rationale  # non-empty preview body
        assert "SPDX-License-Identifier: GPL-2.0-only" in change.rationale
        assert "MODULE_DEVICE_TABLE" in change.rationale
        assert "NOT independently verified" in change.rationale


# ---------------------------------------------------------------------------
# 4. Disclosure-only invariant — the core contract of this WP
# ---------------------------------------------------------------------------

def test_disclosures_are_not_rows() -> None:
    """No key in the emitted ChangeSet resembles a cross-verification row.

    The disclosure-only invariant forbids the engine's output from being shaped
    like ``cross_verification.rows``. This test greps the serialized payload.
    """
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    payload = json.dumps(cs.to_dict(), sort_keys=True)
    forbidden_keys = (
        '"verdict"',
        '"is_open"',
        '"track"',
        '"subject"',
        '"cross_verify"',
        '"cross_verification"',
        '"contributes_rows"',
    )
    for key in forbidden_keys:
        assert key not in payload, f"disclosure-only violation: {key} in payload"


def test_no_match_or_pass_verdict_in_payload() -> None:
    """The engine MUST NOT emit tokens that could be laundered into a PASS."""
    cs = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    payload = json.dumps(cs.to_dict(), sort_keys=True)
    # These verdict tokens must not appear in a shape suggesting a PASS/MATCH.
    # Provenance strings say "NOT cross-verified" / "NOT independently verified" —
    # deliberately negative, and the test allows those.
    assert '"MATCH"' not in payload
    assert '"PARTIAL_MATCH"' not in payload


# ---------------------------------------------------------------------------
# 5. Pipeline 1 untouched — byte-identity of gate-critical modules
# ---------------------------------------------------------------------------

_PIPELINE_1_LOCKED = (
    Path("orchestrator/generation/codec_stub.py"),
    Path("orchestrator/generation/model.py"),
    Path("orchestrator/generation/__init__.py"),
)


def _hash_locked() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    out: dict[str, str] = {}
    for rel in _PIPELINE_1_LOCKED:
        p = repo_root / rel
        out[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_pipeline_1_untouched() -> None:
    """Running the preview engine must not mutate Pipeline 1 modules."""
    before = _hash_locked()
    _ = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)
    after = _hash_locked()
    assert before == after


# ---------------------------------------------------------------------------
# 6. No disk write
# ---------------------------------------------------------------------------

def test_engine_never_writes_disk(tmp_path: Path) -> None:
    """Patch open/write_text/write_bytes: engine must not attempt any write."""
    real_open = open
    write_calls: list[Any] = []

    def track_open(*args: Any, **kwargs: Any) -> Any:
        # Detect any write-mode open.
        mode = ""
        if len(args) >= 2 and isinstance(args[1], str):
            mode = args[1]
        else:
            mode = kwargs.get("mode", "r")
        if any(m in mode for m in ("w", "a", "x", "+")):
            write_calls.append(("open", args, kwargs))
        return real_open(*args, **kwargs)

    with mock.patch("builtins.open", side_effect=track_open), mock.patch.object(
        Path, "write_text", autospec=True
    ) as wt, mock.patch.object(Path, "write_bytes", autospec=True) as wb:
        _ = CodecPreviewEngine().generate(_TASK_SPEC_MINIMAL)

    assert wt.call_count == 0
    assert wb.call_count == 0
    assert write_calls == []


# ---------------------------------------------------------------------------
# 7. Runner wires the provenance dict
# ---------------------------------------------------------------------------

def test_runner_injects_provenance_when_codec_source_present() -> None:
    """The runner must build a task_spec with the provenance dict from the profile.

    Assertion is indirect (the runner calls the engine and returns a ChangeSet
    dict), so we swap in NullEngine explicitly and inspect the task_spec via a
    monkey-patched engine.
    """
    captured_task_specs: list[dict[str, Any]] = []

    class CaptureEngine(NullEngine):
        engine_id = "capture"

        def generate(self, task_spec: dict[str, Any]) -> ChangeSet:
            captured_task_specs.append(task_spec)
            return super().generate(task_spec)

    envelope = {
        "target_name": "nord-iq10",
        "run_id": "runner-test-1",
        "target_profile": _NORD_PROFILE,
        "engine_id": "capture",
    }

    from orchestrator.codegen.engine import _ENGINES

    _ENGINES["capture"] = CaptureEngine
    try:
        run_codec_generation(envelope)
    finally:
        _ENGINES.pop("capture", None)

    assert len(captured_task_specs) == 1
    prov = captured_task_specs[0].get("provenance")
    assert isinstance(prov, dict)
    assert prov["codec_source_path"] == "/tmp/g3a9-candidate/iq10-evk.dts"
    assert prov["candidate_derived"] is True
    assert prov["independently_verified"] is False
    assert prov["same_source_t4a"] is True


def test_runner_provenance_when_codec_source_absent() -> None:
    """No codec_source → candidate_derived False, path None. Absence is honest."""
    captured: list[dict[str, Any]] = []

    class CaptureEngine(NullEngine):
        engine_id = "capture_absent"

        def generate(self, task_spec: dict[str, Any]) -> ChangeSet:
            captured.append(task_spec)
            return super().generate(task_spec)

    envelope = {
        "target_name": "some-target",
        "run_id": "runner-test-2",
        "target_profile": {"codecs": [], "codec_source": None},
        "engine_id": "capture_absent",
    }

    from orchestrator.codegen.engine import _ENGINES

    _ENGINES["capture_absent"] = CaptureEngine
    try:
        run_codec_generation(envelope)
    finally:
        _ENGINES.pop("capture_absent", None)

    prov = captured[0]["provenance"]
    assert prov["codec_source_path"] is None
    assert prov["candidate_derived"] is False
    assert prov["independently_verified"] is False


# ---------------------------------------------------------------------------
# 8. Runner + CodecPreviewEngine end-to-end shape
# ---------------------------------------------------------------------------

def test_runner_with_codec_preview_end_to_end() -> None:
    envelope = {
        "target_name": "nord-iq10",
        "run_id": "e2e-run-1",
        "target_profile": _NORD_PROFILE,
        "engine_id": "codec_preview",
    }
    result = run_codec_generation(envelope)
    assert result["human_review_needed"] is True
    cs = result["change_set"]
    assert cs["engine_id"] == "codec_preview"
    assert len(cs["changes"]) == 2
    for change in cs["changes"]:
        assert change["path"].endswith("-preview.c")
        assert change["needs_review"]
        assert any("candidate-derived" in line for line in change["needs_review"])
