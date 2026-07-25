"""WP G-3A.9 hard-fail tests for candidate-derived codec injection.

Contract under test
-------------------
When ``run_target_onboarding`` is given an explicit ``codec_source_path``
(option (a): NAMED at the invocation site, never auto-discovered),
``analysis["codecs"]`` must be populated from that source with EVERY
codec fact carrying:

  * ``provenance_tag`` — the honest-label caveat string
    (``codecs=candidate-derived (<source>) NOT independently verified;
     T4a=same-source NOT cross-verified``).
  * ``source`` — the source marker (filename basename by default).

The runner also records ``output["_reasoning"]["codec_source"]`` at the
manifest layer so downstream artifact writers can prove the provenance
chain outside of ``analysis["codecs"]`` itself.

Backwards compat guarantee: if ``codec_source_path`` is falsy / omitted,
``analysis["codecs"]`` stays whatever the reasoning engine emitted
(``[]`` on every existing run) — no auto-discovery, no silent pickup.

Hard-fail invariant: if the internal decoration helper is bypassed or
monkey-patched to return a codec missing EITHER field, the runner MUST
raise ``RuntimeError``. This is the fossil-trap guard the user demanded
in the Q1 ruling.

Generality guarantee: no Nord token (``pcm1681``, ``adau1979``,
``ti,``, ``adi,`` etc.) appears anywhere in the reader / runner —
verified here by feeding a synthetic non-Nord .dts (``xyz,fake-1234``)
and confirming the injected fact carries exactly that compatible.

Run: PYTHONPATH=audio_bu_skill python3 -m tests.test_target_onboarding_codec_injection
(or: python3 audio_bu_skill/tests/test_target_onboarding_codec_injection.py)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from orchestrator.runners import target_onboarding_runner
from orchestrator.runners.target_onboarding_runner import (
    _build_candidate_codecs,
    run_target_onboarding,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_git_kernel(root: Path) -> Path:
    """Minimal real-git kernel fixture matching test_target_onboarding_wiring."""
    kernel = root / "linux-fake"
    for sub in ("arch", "drivers", "sound", "Documentation"):
        (kernel / sub).mkdir(parents=True, exist_ok=True)
    codecs = kernel / "sound" / "soc" / "codecs"
    codecs.mkdir(parents=True, exist_ok=True)
    (codecs / "pcm1681.c").write_text("// stub\n", encoding="utf-8")
    _git(kernel, "init", "-q")
    _git(kernel, "config", "user.email", "test@example.com")
    _git(kernel, "config", "user.name", "Test User")
    (kernel / "README").write_text("base\n", encoding="utf-8")
    _git(kernel, "add", "-A")
    _git(kernel, "commit", "-q", "-m", "initial")
    return kernel


def _write_candidate_dts(root: Path, *, name: str, nodes: list[tuple[str, str, str]]) -> Path:
    """Write a candidate .dts with the given (label, addr, compatible) nodes.

    Kept generic — callers pass in the compatibles they need. This
    fixture writer intentionally emits raw DTS syntax (no includes, no
    preprocessor) so the reader's regex sweep is exercised end-to-end.
    """
    body = "\n".join(
        f'{label}: audio-codec@{addr} {{\n'
        f'    compatible = "{compat}";\n'
        f'    reg = <0x{addr}>;\n'
        f'    #sound-dai-cells = <0>;\n'
        f'}};\n'
        for label, addr, compat in nodes
    )
    dts_path = root / name
    dts_path.write_text(f"&i2c18 {{\n{body}}};\n", encoding="utf-8")
    return dts_path


def _base_envelope(root: Path, target_name: str) -> dict:
    """Minimal envelope shared across happy-path / compat / generality tests."""
    targets_root = root / "audio_bu_skill" / "targets"
    tdir = targets_root / target_name
    ev_offline = tdir / "evidence" / "offline"
    ev_offline.mkdir(parents=True, exist_ok=True)
    (ev_offline / "note.txt").write_text("evidence\n", encoding="utf-8")
    return {
        "workspace_context": {"workspace_root": str(root)},
        "target_name": target_name,
        "kernel_source_path": "linux-fake",
        "run_id": f"{target_name}-onboarding",
        "evidence_roots": {
            "ipcat": f"audio_bu_skill/targets/{target_name}/evidence/ipcat",
            "offline_documents": f"audio_bu_skill/targets/{target_name}/evidence/offline",
        },
        "analysis_engine": "local-test",
        "test_mode": True,
        "target_db_root": "audio_bu_skill/targets",
    }


def _run(envelope: dict, targets_root: Path) -> dict:
    import orchestrator.main as m
    original = m.TARGETS_ROOT
    m.TARGETS_ROOT = targets_root
    try:
        return run_target_onboarding(envelope)
    finally:
        m.TARGETS_ROOT = original


def test_happy_path_injects_codecs_with_tag_and_source_and_manifest() -> None:
    """G-3A.9 north-star: two codec nodes in a candidate .dts flow into
    analysis['codecs'] with BOTH provenance_tag and source, AND the run
    manifest records codec_source at the _reasoning layer."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel(root)
        target_name = "candidate-target"
        env = _base_envelope(root, target_name)
        dts = _write_candidate_dts(
            root,
            name="candidate.dts",
            nodes=[
                ("pcm1681", "4c", "ti,pcm1681"),
                ("adau1979", "31", "adi,adau1979"),
            ],
        )
        env["codec_source_path"] = str(dts)

        output = _run(env, root / "audio_bu_skill" / "targets")

        codecs = output["_reasoning"]["analysis"]["codecs"]
        assert len(codecs) == 2, codecs
        seen_compatibles = {c["compatible"] for c in codecs}
        assert seen_compatibles == {"ti,pcm1681", "adi,adau1979"}, seen_compatibles

        for c in codecs:
            assert c.get("provenance_tag"), c
            assert c.get("source"), c
            assert "candidate-derived" in c["provenance_tag"], c
            assert "NOT independently verified" in c["provenance_tag"], c
            assert "same-source NOT cross-verified" in c["provenance_tag"], c
            assert c["source"] == "candidate.dts", c

        assert output["_reasoning"]["codec_source"] == str(dts)
        # G-3A.9 Q1 anchor: the flat target_profile MUST also carry
        # codec_source so profile.json on disk exposes the cross-artifact
        # audit anchor (the writer at orchestrator/main.py:768 dumps
        # output["target_profile"], not output["_reasoning"]).
        assert output["target_profile"]["codec_source"] == str(dts)
    print("PASS: happy-path — candidate .dts codecs injected with tag+source; "
          "manifest records codec_source at _reasoning layer")


def test_hard_fail_when_decorator_returns_codec_missing_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """A codec fact missing provenance_tag must trigger RuntimeError."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel(root)
        target_name = "hf-tag"
        env = _base_envelope(root, target_name)
        dts = _write_candidate_dts(
            root, name="c.dts", nodes=[("foo", "10", "vendor,foo")],
        )
        env["codec_source_path"] = str(dts)

        def _bad_no_tag(codec_source_path: str) -> list:
            return [{"label": "foo", "compatible": "vendor,foo",
                     "part": "vendor,foo", "source": "c.dts"}]
        monkeypatch.setattr(target_onboarding_runner,
                            "_build_candidate_codecs", _bad_no_tag)

        with pytest.raises(RuntimeError, match="G-3A.9 invariant"):
            _run(env, root / "audio_bu_skill" / "targets")
    print("PASS: hard-fail — codec missing provenance_tag raises RuntimeError")


def test_hard_fail_when_decorator_returns_codec_missing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """A codec fact missing source must trigger RuntimeError."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel(root)
        target_name = "hf-src"
        env = _base_envelope(root, target_name)
        dts = _write_candidate_dts(
            root, name="c.dts", nodes=[("foo", "10", "vendor,foo")],
        )
        env["codec_source_path"] = str(dts)

        def _bad_no_source(codec_source_path: str) -> list:
            return [{"label": "foo", "compatible": "vendor,foo",
                     "part": "vendor,foo",
                     "provenance_tag": "codecs=candidate-derived (c.dts) "
                                       "NOT independently verified; "
                                       "T4a=same-source NOT cross-verified"}]
        monkeypatch.setattr(target_onboarding_runner,
                            "_build_candidate_codecs", _bad_no_source)

        with pytest.raises(RuntimeError, match="G-3A.9 invariant"):
            _run(env, root / "audio_bu_skill" / "targets")
    print("PASS: hard-fail — codec missing source raises RuntimeError")


def test_backwards_compat_no_codec_source_path_leaves_codecs_empty() -> None:
    """Without codec_source_path, analysis['codecs'] stays at the
    engine's default ([]) — no auto-discovery, no silent pickup."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel(root)
        target_name = "compat"
        env = _base_envelope(root, target_name)
        # No codec_source_path key at all.

        output = _run(env, root / "audio_bu_skill" / "targets")

        codecs = output["_reasoning"]["analysis"]["codecs"]
        assert codecs == [], codecs
        assert output["_reasoning"]["codec_source"] is None
        # G-3A.9 Q1 anchor still present at the flat profile layer even when
        # no codec_source_path was supplied — value is None but the KEY MUST
        # exist so downstream consumers (and the "no silent drop" invariant)
        # have a definite present-with-null vs. missing-key distinction.
        assert "codec_source" in output["target_profile"], output["target_profile"].keys()
        assert output["target_profile"]["codec_source"] is None
    print("PASS: backwards-compat — no codec_source_path -> analysis['codecs'] "
          "stays [], manifest codec_source is None")


def test_generality_no_nord_tokens_leak_from_orchestrator() -> None:
    """A synthetic non-Nord .dts (xyz,fake-1234) must produce a fact
    carrying exactly that compatible — proving the orchestrator body
    never bakes in Nord-specific tokens."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_git_kernel(root)
        target_name = "generic"
        env = _base_envelope(root, target_name)
        dts = _write_candidate_dts(
            root,
            name="synthetic.dts",
            nodes=[("synth", "aa", "xyz,fake-1234")],
        )
        env["codec_source_path"] = str(dts)

        output = _run(env, root / "audio_bu_skill" / "targets")

        codecs = output["_reasoning"]["analysis"]["codecs"]
        assert len(codecs) == 1, codecs
        assert codecs[0]["compatible"] == "xyz,fake-1234", codecs
        assert codecs[0]["part"] == "xyz,fake-1234", codecs
        # No accidental leaks in provenance tag either.
        for c in codecs:
            for token in ("pcm1681", "adau1979", "ti,", "adi,", "nord"):
                assert token not in c["provenance_tag"].lower(), (token, c)
    print("PASS: generality — synthetic non-Nord codec flows through; no Nord "
          "tokens leak from orchestrator body")


def test_build_candidate_codecs_returns_empty_when_no_source() -> None:
    """The decoration helper is inert when no source is passed —
    additional coverage for the backwards-compat gate."""
    assert _build_candidate_codecs("") == []
    assert _build_candidate_codecs("/nonexistent/path.dts") == []
    print("PASS: _build_candidate_codecs returns [] on falsy / missing path")


def main() -> None:
    test_happy_path_injects_codecs_with_tag_and_source_and_manifest()
    # pytest-monkeypatch cases are runnable under pytest; skip in bare-main run.
    test_backwards_compat_no_codec_source_path_leaves_codecs_empty()
    test_generality_no_nord_tokens_leak_from_orchestrator()
    test_build_candidate_codecs_returns_empty_when_no_source()
    print("ALL BARE-MAIN TESTS PASSED (run under pytest for hard-fail monkeypatch cases)")


if __name__ == "__main__":
    main()
