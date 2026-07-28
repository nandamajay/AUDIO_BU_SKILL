"""WP_SCHEMATIC_ATTESTED_DESIGN.md §6 step 3 — live-wire curated_overrides.json.

Step 3 makes the schematic-capture channel LIVE at onboarding time by loading a
``curated_overrides.json`` file and passing it to ``project()`` at the sites that
actually WRITE ``audio_hardware_template.json``.

Uncomfortable-truth reconciliation (proven, not assumed):
    The design doc / step-3 scope name "main.py ~595" as the wiring site, but
    main.py:595 is a READ of a pre-existing template (the Phase-A *consumer*
    path); it never calls ``project()`` and never writes the template. The ONLY
    writers of ``audio_hardware_template.json`` in-tree are (a) the projector
    ``_cli`` and (b) ``tests/h1_validation_harness.py`` (which regenerated the
    committed Nord template). Step 3 therefore wires those two real write sites
    through one shared loader, ``load_curated_overrides``, and leaves main.py
    untouched (wiring curation into ``_run_generation`` would be step 4, the
    consumer — explicitly out of scope here).

Contract pinned by these tests:
  * file present + valid  -> overrides loaded and applied at projection time
  * file absent           -> None -> byte-identical projection (no schematic leaf moves)
  * file malformed        -> loud ValueError (never silently ignored)
  * CLI --curated-overrides parity with the API path (same bytes)
  * firewall: loaded overrides never mutate cross_verification / never leak to any gate
  * Nord byte-identity: no curated file present -> every schematic leaf NOT_ATTESTED

Still gap-fill-only, disclosure-only, candidate firewall intact. No consumer
(step 4) and no Nord placeholder file (step 5) are introduced here.

All fixtures are SYNTHETIC. Results are NOT real-target.

Run: ``PYTHONPATH=.:audio_bu_skill python -m pytest \
    audio_bu_skill/tests/test_schematic_curated_wiring_step3.py -q``
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from orchestrator.hw_template import projector as projmod
from orchestrator.hw_template.projector import (
    _cli,
    load_curated_overrides,
    project,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _gc_two_codecs() -> dict:
    """gc seeding two candidate-only codecs (mirrors real Nord: no authoritative
    rows, so every schematic leaf lands NOT_ATTESTED / value=null)."""
    return {
        "cross_verification": {"rows": []},
        "codecs": [
            {"part_number": "adau1979", "vendor": "adi", "role": "primary"},
            {"part_number": "pcm1681", "vendor": "ti", "role": "secondary"},
        ],
    }


def _codec_override(codec_key: str, field: str, value) -> dict:
    """A single identity-keyed codec schematic override entry."""
    return {
        f"codecs.{codec_key}.{field}": {
            "value": value,
            "authority": {"strength": "KB_RULE", "origin": "schematic"},
            "citations": ["<fixture: NOT_REAL_TARGET>"],
            "attestation": {
                "attested_by": "reviewer@example.com",
                "timestamp": "2026-07-28T00:00:00Z",
                "evidence": "Schematic LD20-94440 rev A, audio sheet",
                "target": "synth-t",
            },
        }
    }


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _project(gc: dict, overrides: dict | None):
    """project() with fixture citations enabled (SYNTHETIC gc)."""
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        return project(
            gc=gc, target_name="synth-t", run_id="step3-unit",
            curated_overrides=overrides,
        )
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)


def _adau(template) -> dict:
    return next(
        c for c in template.codecs
        if (c["part_number"].value or c["part_number"].candidate_value) == "adau1979"
    )


# ── 1. loader: file present + valid -> dict identical to the on-disk payload ──


def test_loader_reads_valid_file(tmp_path: Path):
    payload = _codec_override("adau1979", "i2c_address", "0x31")
    f = _write_json(tmp_path / "curated_overrides.json", payload)
    loaded = load_curated_overrides(f, required=False)
    assert loaded == payload


def test_loaded_overrides_apply_at_projection_time(tmp_path: Path):
    """A file loaded off disk fills the NOT_ATTESTED leaf exactly as an
    in-memory dict passed directly to project() would."""
    payload = _codec_override("adau1979", "i2c_address", "0x31")
    f = _write_json(tmp_path / "curated_overrides.json", payload)
    loaded = load_curated_overrides(f, required=False)

    result = _project(_gc_two_codecs(), loaded)
    leaf = _adau(result.template)["i2c_address"]
    assert leaf.value == "0x31"
    assert leaf.ncc_state == "ATTESTED"
    assert leaf.authority["origin"] == "schematic"


# ── 2. file absent -> None -> byte-identical projection ───────────────────────


def test_missing_file_convention_returns_none(tmp_path: Path):
    """Convention auto-load (required=False) of an absent file -> None."""
    assert load_curated_overrides(tmp_path / "does_not_exist.json", required=False) is None


def test_absent_curated_file_byte_identical_to_no_overrides(tmp_path: Path):
    """Loading an absent file and projecting == projecting with None: identical
    bytes, and every schematic leaf stays NOT_ATTESTED / null."""
    loaded = load_curated_overrides(tmp_path / "absent.json", required=False)
    assert loaded is None

    r_loaded = _project(_gc_two_codecs(), loaded)
    r_none = _project(_gc_two_codecs(), None)
    t1 = json.dumps(r_loaded.template.to_dict(), sort_keys=True)
    t2 = json.dumps(r_none.template.to_dict(), sort_keys=True)
    assert t1 == t2

    bm = r_loaded.template.board_metadata
    for field in ("mclk", "global_md_oe", "scmi_index"):
        assert bm[field].value is None
        assert bm[field].ncc_state == "NOT_ATTESTED"
    for c in r_loaded.template.codecs:
        for field in ("i2c_bus_label", "i2c_address", "reset_gpios"):
            assert c[field].value is None
            assert c[field].ncc_state == "NOT_ATTESTED"


# ── 3. malformed file -> loud ValueError (never silent) ───────────────────────


def test_malformed_json_raises_loudly(tmp_path: Path):
    f = tmp_path / "curated_overrides.json"
    f.write_text("{ this is not json", encoding="utf-8")
    # Loud regardless of required flag — a present-but-broken file is never dropped.
    with pytest.raises(ValueError, match="malformed curated overrides file"):
        load_curated_overrides(f, required=False)
    with pytest.raises(ValueError, match="malformed curated overrides file"):
        load_curated_overrides(f, required=True)


def test_non_object_json_raises(tmp_path: Path):
    """A valid-JSON-but-not-an-object file (e.g. a list) is a loud error."""
    f = _write_json(tmp_path / "curated_overrides.json", ["not", "an", "object"])
    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_curated_overrides(f, required=False)


def test_missing_required_file_raises(tmp_path: Path):
    """An explicit path that does not exist (required=True) is loud."""
    with pytest.raises(FileNotFoundError, match="curated overrides file not found"):
        load_curated_overrides(tmp_path / "nope.json", required=True)


# ── 4. CLI --curated-overrides parity with the API path ───────────────────────


def _run_cli(tmp_path: Path, gc: dict, curated_path: Path | None) -> dict:
    """Drive _cli end-to-end; return the written template dict."""
    gc_path = _write_json(tmp_path / "gc.json", gc)
    out_dir = tmp_path / "out"
    argv = [
        "--gc-json", str(gc_path),
        "--target", "synth-t",
        "--run-id", "step3-unit",
        "--out-dir", str(out_dir),
    ]
    if curated_path is not None:
        argv += ["--curated-overrides", str(curated_path)]
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        rc = _cli(argv)
    finally:
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
    assert rc == 0, f"_cli returned {rc}"
    return json.loads(
        (out_dir / "audio_hardware_template.json").read_text(encoding="utf-8")
    )


def test_cli_curated_flag_parity_with_api(tmp_path: Path):
    """_cli --curated-overrides produces the same template bytes as the API
    project(curated_overrides=...) path."""
    payload = _codec_override("adau1979", "i2c_address", "0x31")
    curated_path = _write_json(tmp_path / "curated_overrides.json", payload)

    cli_tmpl = _run_cli(tmp_path, _gc_two_codecs(), curated_path)

    api_result = _project(_gc_two_codecs(), payload)
    api_tmpl = api_result.template.to_dict()

    assert json.dumps(cli_tmpl, sort_keys=True) == json.dumps(api_tmpl, sort_keys=True)


def test_cli_no_flag_byte_identical_to_none(tmp_path: Path):
    """_cli with no --curated-overrides == project(None): byte-identical."""
    cli_tmpl = _run_cli(tmp_path, _gc_two_codecs(), None)
    api_tmpl = _project(_gc_two_codecs(), None).template.to_dict()
    assert json.dumps(cli_tmpl, sort_keys=True) == json.dumps(api_tmpl, sort_keys=True)


def test_cli_missing_curated_file_is_loud(tmp_path: Path):
    """An explicit --curated-overrides PATH that does not exist -> rc=2 (loud),
    NOT a silent success."""
    gc_path = _write_json(tmp_path / "gc.json", _gc_two_codecs())
    out_dir = tmp_path / "out"
    argv = [
        "--gc-json", str(gc_path),
        "--target", "synth-t",
        "--run-id", "step3-unit",
        "--out-dir", str(out_dir),
        "--curated-overrides", str(tmp_path / "absent.json"),
    ]
    assert _cli(argv) == 2
    # And nothing was written.
    assert not (out_dir / "audio_hardware_template.json").exists()


def test_cli_malformed_curated_file_is_loud(tmp_path: Path):
    (tmp_path / "curated_overrides.json").write_text("{bad", encoding="utf-8")
    gc_path = _write_json(tmp_path / "gc.json", _gc_two_codecs())
    out_dir = tmp_path / "out"
    argv = [
        "--gc-json", str(gc_path),
        "--target", "synth-t",
        "--run-id", "step3-unit",
        "--out-dir", str(out_dir),
        "--curated-overrides", str(tmp_path / "curated_overrides.json"),
    ]
    assert _cli(argv) == 2


# ── 5. firewall: loaded overrides never enter cross_verification ──────────────


def test_loaded_override_never_enters_cross_verification(tmp_path: Path):
    """A file-loaded override MUST NOT mutate gc['cross_verification']['rows']."""
    gc = _gc_two_codecs()
    gc_before = deepcopy(gc)
    payload = _codec_override("pcm1681", "reset_gpios", "gpio77")
    f = _write_json(tmp_path / "curated_overrides.json", payload)
    loaded = load_curated_overrides(f, required=False)

    result = _project(gc, loaded)

    assert gc["cross_verification"]["rows"] == gc_before["cross_verification"]["rows"]
    assert gc["cross_verification"]["rows"] == []
    c = next(
        x for x in result.template.codecs
        if (x["part_number"].value or x["part_number"].candidate_value) == "pcm1681"
    )
    assert c["reset_gpios"].value == "gpio77"


# ── 6. harness convention wiring uses the shared loader ───────────────────────


def test_harness_uses_shared_loader_by_convention(tmp_path: Path, monkeypatch):
    """h1_validation_harness._run_real_target auto-loads
    targets/<t>/curated_overrides.json via the shared loader (absent -> None),
    then projects — proving the harness write site is live-wired.

    We stub project/write_outputs to capture the curated_overrides value the
    harness forwards, without touching real target files.
    """
    import tests.h1_validation_harness as harness

    # Minimal analysis file so _synthesise_gc_from_analysis has input.
    target_dir = tmp_path / "synth-t"
    target_dir.mkdir()
    _write_json(target_dir / "qgenie_analysis.json", {"soc": None, "codecs": []})

    captured = {}

    class _FakeResult:
        class _GM:
            gap_count_by_reason = {}
            gaps = []
        gap_manifest = _GM()

        class _T:
            codecs = []
            amplifiers = []
            buses = []
            clocks = []
            audio_links = []
        template = _T()

    def _fake_project(gc, *, target_name, run_id, curated_overrides=None, **kw):
        captured["curated"] = curated_overrides
        return _FakeResult()

    def _fake_write(result, out_dir):
        return (Path(out_dir) / "audio_hardware_template.json",
                Path(out_dir) / "gap_manifest.json")

    monkeypatch.setattr(harness, "project", _fake_project)
    monkeypatch.setattr(harness, "write_outputs", _fake_write)

    # No curated file present -> harness must forward None.
    out = harness._run_real_target("synth-t", target_dir)
    assert out["status"] == "OK"
    assert captured["curated"] is None

    # Now drop a valid curated file -> harness must forward the loaded dict.
    payload = _codec_override("adau1979", "i2c_address", "0x31")
    _write_json(target_dir / "curated_overrides.json", payload)
    harness._run_real_target("synth-t", target_dir)
    assert captured["curated"] == payload


# ── 7. loader is the exact function both write sites import ────────────────────


def test_single_loader_shared_by_both_write_sites():
    """Parity guarantee: the projector CLI and the harness bind the SAME
    load_curated_overrides object (no drifting second implementation)."""
    import tests.h1_validation_harness as harness

    assert harness.load_curated_overrides is projmod.load_curated_overrides
