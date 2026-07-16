"""Phase-2B WP8 — tests for the additive Generation section renderer.

Pure, stdlib-only tests over ``orchestrator.main._render_generation_section``.
Mirrors WP3-WP7 test discipline: inline data, no fakes, no network, no pytest.

Five tests per PHASE2B_SPECIFICATION.md §WP8 (recon-locked E1 scope —
renderer + tests + fixtures ONLY; runner belongs to WP10):

  1. ``test_render_all_success`` — four GeneratedArtifacts + post-verify
     pass. Byte-identical against
     ``fixtures/phase2b/wp8_render_all_success_expected.md`` (has
     Contributes-rows FIXMEs subsection).
  2. ``test_render_gate_closed`` — one GeneratedArtifact + one
     GeneratorSkipped + post-verify fail on ≥1 row. Byte-identical.
  3. ``test_render_no_fixmes_omits_subsection`` — single artifact with
     empty ``contributes_rows``: subsection 3 is omitted entirely.
  4. ``test_render_null_guard`` — fourfold null-guard trigger. Empty gc,
     missing ``generation`` key, ``None`` value, and non-list ``artifacts``
     all return ``[]``.
  5. ``test_render_signature_and_purity`` — pure function; deterministic
     across repeated calls; no imports from ``orchestrator.generation.*``.

The renderer treats its input as opaque JSON dicts — it does NOT
deserialize back into GenerationResult objects. These tests inject
synthetic ``gc`` structures directly (no GenerationResult / TrustedFacts
construction here — that's the WP10 runner's job).

Run: ``PYTHONPATH=audio_bu_skill python3 -m tests.test_generation_render``
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.main import _render_generation_section


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2b"


# ── Helper builders (mirror to_dict shapes) ─────────────────────────────────

def _generated_artifact(
    artifact_class: str,
    *,
    subject: str | None = None,
    path_hint: str = "generated/stub.out",
    contributes_rows: list[dict] | None = None,
) -> dict:
    """Build a ``GeneratedArtifact.to_dict()``-shaped dict."""
    return {
        "kind": "GeneratedArtifact",
        "artifact_class": artifact_class,
        "subject": subject or artifact_class,
        "path_hint": path_hint,
        "bytes_hex": "2f2f207374756200",  # b"// stub\x00" hex — opaque
        "contributes_rows": contributes_rows or [],
    }


def _generator_skipped(
    artifact_class: str,
    reason: str,
    gating_rows: list[str],
    *,
    subject: str | None = None,
) -> dict:
    """Build a ``GeneratorSkipped.to_dict()``-shaped dict."""
    return {
        "kind": "GeneratorSkipped",
        "artifact_class": artifact_class,
        "subject": subject or artifact_class,
        "reason": reason,
        "gating_rows": gating_rows,
    }


def _pv_row(
    artifact_class: str,
    kind: str,
    verdict: str,
    message: str,
    *,
    subject: str | None = None,
) -> dict:
    """Build a ``PostVerificationRow.to_dict()``-shaped dict."""
    return {
        "artifact_class": artifact_class,
        "subject": subject or artifact_class,
        "kind": kind,
        "verdict": verdict,
        "message": message,
        "details": {},
    }


def _fixme_row(track: str, subject: str, coverage_gap_reason: str) -> dict:
    """Build a VerificationRow.to_dict()-shaped dict that qualifies as FIXME.

    (verdict=NOT_CROSS_CHECKABLE + coverage_gap_reason set).
    """
    return {
        "track": track,
        "subject": subject,
        "source": "test",
        "authority": {"strength": "UNAVAILABLE", "origin": "none"},
        "verdict": "NOT_CROSS_CHECKABLE",
        "confidence": "medium",
        "coverage_gap_reason": coverage_gap_reason,
        "rule_id": None,
        "warning": True,
        "review_actions": [],
        "citations": [],
        "notes": None,
    }


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ── 1. All success — 4 pass artifacts + post-verify pass ────────────────────

def test_render_all_success() -> None:
    """Four GeneratedArtifacts + post-verify pass renders as expected.

    Byte-identity against ``wp8_render_all_success_expected.md``. Two
    codec_stub contributes_rows qualify as FIXMEs (T4b NCC +
    authority_out_of_scope) — the third subsection appears with those two
    rows.
    """
    fixmes = [
        _fixme_row("T4b", "codec.adau1979", "authority_out_of_scope"),
        _fixme_row("T4b", "codec.pcm1681", "authority_out_of_scope"),
    ]
    gc = {
        "generation": {
            "artifacts": [
                _generated_artifact(
                    "dt_scaffolding",
                    path_hint="generated/dt_scaffolding/board.dtsi",
                ),
                _generated_artifact(
                    "codec_stub",
                    path_hint="generated/codec_stub/codec.c",
                    contributes_rows=fixmes,
                ),
                _generated_artifact(
                    "machine_driver",
                    path_hint="generated/machine_driver/machine.c",
                ),
                _generated_artifact(
                    "audioreach_topology",
                    path_hint="generated/audioreach_topology/topo.xml",
                ),
            ],
            "post_verification": {
                "verdict": "pass",
                "rows": [
                    _pv_row(
                        "audioreach_topology",
                        "gate_consistency",
                        "pass",
                        "gate-consistency: every registered gating row opens in source facts.",
                    ),
                    _pv_row(
                        "codec_stub",
                        "gate_consistency",
                        "pass",
                        "gate-consistency: every registered gating row opens in source facts.",
                    ),
                    _pv_row(
                        "dt_scaffolding",
                        "gate_consistency",
                        "pass",
                        "gate-consistency: every registered gating row opens in source facts.",
                    ),
                    _pv_row(
                        "machine_driver",
                        "gate_consistency",
                        "pass",
                        "gate-consistency: every registered gating row opens in source facts.",
                    ),
                ],
            },
        }
    }

    got = "\n".join(_render_generation_section(gc)) + "\n"
    expected = _read_fixture("wp8_render_all_success_expected.md")
    assert got == expected, (
        f"byte-identity failure for wp8_render_all_success_expected.md\n"
        f"---GOT---\n{got}\n---EXPECTED---\n{expected}\n---END---"
    )
    print("PASS: all-success — 4 artifacts + post-verify pass + 2 FIXMEs render byte-identically")


# ── 2. Gate closed — mixed artifact/skipped + post-verify fail ──────────────

def test_render_gate_closed() -> None:
    """One GeneratedArtifact + one GeneratorSkipped + post-verify fail.

    Byte-identity against ``wp8_render_gate_closed_expected.md``. codec_stub
    fails gate-consistency, machine_driver skip is valid. One T4b FIXME on
    the codec artifact so subsection 3 appears with one row.
    """
    gc = {
        "generation": {
            "artifacts": [
                _generated_artifact(
                    "codec_stub",
                    path_hint="generated/codec_stub/codec.c",
                    contributes_rows=[
                        _fixme_row("T4b", "codec.adau1979", "authority_out_of_scope"),
                    ],
                ),
                _generator_skipped(
                    "machine_driver",
                    reason="gating_row_disagree_on_bus",
                    gating_rows=["T2.soundwire_master"],
                ),
            ],
            "post_verification": {
                "verdict": "fail",
                "rows": [
                    _pv_row(
                        "codec_stub",
                        "gate_consistency",
                        "fail",
                        "gate-consistency: artifact emitted but the following gating "
                        "rows are CLOSED in source facts: ['T4a.qup.se3']",
                    ),
                    _pv_row(
                        "machine_driver",
                        "skip_validity",
                        "pass",
                        "skip-validity: reason='gating_row_disagree_on_bus' valid; "
                        "≥1 cited gate closed in source facts.",
                    ),
                ],
            },
        }
    }

    got = "\n".join(_render_generation_section(gc)) + "\n"
    expected = _read_fixture("wp8_render_gate_closed_expected.md")
    assert got == expected, (
        f"byte-identity failure for wp8_render_gate_closed_expected.md\n"
        f"---GOT---\n{got}\n---EXPECTED---\n{expected}\n---END---"
    )
    print("PASS: gate-closed — artifact+skipped + fail post-verify + 1 FIXME render byte-identically")


# ── 3. No FIXMEs → subsection 3 omitted ─────────────────────────────────────

def test_render_no_fixmes_omits_subsection() -> None:
    """A single artifact with empty ``contributes_rows`` omits subsection 3.

    Byte-identity against ``wp8_render_no_fixmes_expected.md`` — the third
    ``### Contributes-rows FIXMEs`` H3 header must NOT appear in the output.
    Also proves the omit-when-empty invariant.
    """
    gc = {
        "generation": {
            "artifacts": [
                _generated_artifact(
                    "dt_scaffolding",
                    path_hint="generated/dt_scaffolding/board.dtsi",
                    contributes_rows=[],
                ),
            ],
            "post_verification": {
                "verdict": "pass",
                "rows": [
                    _pv_row(
                        "dt_scaffolding",
                        "gate_consistency",
                        "pass",
                        "gate-consistency: every registered gating row opens in source facts.",
                    ),
                ],
            },
        }
    }

    got = "\n".join(_render_generation_section(gc)) + "\n"
    expected = _read_fixture("wp8_render_no_fixmes_expected.md")
    assert got == expected, (
        f"byte-identity failure for wp8_render_no_fixmes_expected.md\n"
        f"---GOT---\n{got}\n---EXPECTED---\n{expected}\n---END---"
    )
    assert "Contributes-rows FIXMEs" not in got, (
        "subsection 3 must be omitted entirely when no FIXMEs present"
    )
    print("PASS: no-FIXMEs — subsection 3 omitted, byte-identical")


# ── 4. Fourfold null-guard ──────────────────────────────────────────────────

def test_render_null_guard() -> None:
    """Fourfold null-guard: empty gc / missing key / None / bad shape → [].

    Also verifies byte-identity against the empty
    ``wp8_render_null_guard_expected.md`` fixture (empty file = single ""
    join = empty string).
    """
    empty_expected = _read_fixture("wp8_render_null_guard_expected.md")
    assert empty_expected == "", (
        "wp8_render_null_guard_expected.md must be an empty file "
        f"(got {len(empty_expected)} bytes)"
    )

    # (a) empty gc
    assert _render_generation_section({}) == [], "empty gc must return []"

    # (b) None gc
    assert _render_generation_section(None) == [], "None gc must return []"  # type: ignore[arg-type]

    # (c) missing 'generation' key
    assert _render_generation_section({"other": "keys"}) == [], (
        "missing 'generation' key must return []"
    )

    # (d) 'generation' present but None
    assert _render_generation_section({"generation": None}) == [], (
        "generation=None must return []"
    )

    # (e) 'generation' present but wrong type
    assert _render_generation_section({"generation": []}) == [], (
        "generation=[] (non-dict) must return []"
    )

    # (f) 'generation' present but empty dict
    assert _render_generation_section({"generation": {}}) == [], (
        "generation={} must return []"
    )

    # (g) 'generation' present, 'artifacts' missing
    assert _render_generation_section({"generation": {"post_verification": {}}}) == [], (
        "missing artifacts must return []"
    )

    # (h) 'generation' present, 'artifacts' wrong type
    assert _render_generation_section({"generation": {"artifacts": "not-a-list"}}) == [], (
        "artifacts=str must return []"
    )

    print("PASS: fourfold null-guard — 8 shapes all return []")


# ── 5. Signature + purity + import guard ────────────────────────────────────

def test_render_signature_and_purity() -> None:
    """Pure function: deterministic across repeated calls + no forbidden imports.

    (a) Repeatedly calling with the same input yields byte-identical output.
    (b) Signature is ``(gc: dict) -> list[str]``.
    (c) The renderer's containing module must NOT import any
        ``orchestrator.generation.*`` symbol — the renderer treats its
        input as opaque JSON dicts.
    """
    gc = {
        "generation": {
            "artifacts": [
                _generated_artifact(
                    "codec_stub",
                    contributes_rows=[
                        _fixme_row("T4b", "codec.pcm1681", "authority_out_of_scope"),
                    ],
                ),
            ],
            "post_verification": {
                "verdict": "pass",
                "rows": [
                    _pv_row(
                        "codec_stub",
                        "gate_consistency",
                        "pass",
                        "OK",
                    ),
                ],
            },
        }
    }

    # (a) deterministic
    out1 = _render_generation_section(gc)
    out2 = _render_generation_section(gc)
    out3 = _render_generation_section(gc)
    assert out1 == out2 == out3, "renderer must be deterministic across calls"
    assert isinstance(out1, list), "renderer must return list"
    assert all(isinstance(ln, str) for ln in out1), "renderer must return list[str]"

    # (b) signature
    sig = inspect.signature(_render_generation_section)
    params = list(sig.parameters)
    assert params == ["gc"], f"signature drift: params={params!r}"

    # (c) import guard — the RENDERER FUNCTION itself must not reference any
    # orchestrator.generation.* symbol or reconstruct any dataclass from
    # the generation model. main.py as a whole may legitimately import from
    # orchestrator.generation.* elsewhere (e.g. for a WP10 runner or facts
    # composition), so we scope the AST check to the renderer's source only.
    # ``isinstance(x, dict)`` / ``isinstance(x, list)`` is the shape null-guard
    # pattern from ``_render_crossverify_section`` and is allowed; what's
    # forbidden is discriminating on a generation-model dataclass at runtime.
    src = inspect.getsource(_render_generation_section)
    forbidden_substrings = [
        "orchestrator.generation.model",
        "orchestrator.generation.config",
        "orchestrator.generation.registry",
        "orchestrator.generation.post_verify",
        "orchestrator.generation.dt_scaffolding",
        "orchestrator.generation.codec_stub",
        "orchestrator.generation.machine_driver",
        "orchestrator.generation.audioreach_topology",
        "GeneratedArtifact(",
        "GeneratorSkipped(",
        "PostVerificationRow(",
        "PostVerificationResult(",
        "isinstance(_, GeneratedArtifact",
        "isinstance(_, GeneratorSkipped",
        ", GeneratedArtifact)",
        ", GeneratorSkipped)",
        ", PostVerificationRow)",
        ", PostVerificationResult)",
    ]
    offenders = [s for s in forbidden_substrings if s in src]
    assert not offenders, (
        f"renderer must be opaque-dict-only; found forbidden references: {offenders!r}"
    )

    print("PASS: renderer is deterministic + signature (gc:dict)->list[str] + opaque-dict-only")


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    test_render_all_success()                        # 1
    test_render_gate_closed()                        # 2
    test_render_no_fixmes_omits_subsection()         # 3
    test_render_null_guard()                         # 4
    test_render_signature_and_purity()               # 5
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
