"""H-1 validation harness — run projector against 4 targets.

This is a **read-only, offline** validation script. It:

  1. Loads ``qgenie_analysis.json`` for each real target (nord-iq10, eliza)
     and synthesises a minimal ``gc`` shell around it. The real targets do
     not persist ``cross_verification.rows`` in the on-disk analysis file
     (that key is in-memory only during a live walk at main.py:1192), so
     the harness runs the projector with an **empty rows list** — this
     exercises the worst-case candidate-only path end-to-end.
  2. Loads ``gc.json`` for the synthetic fixtures (which DO carry
     cross_verification rows) and runs the projector with fixture
     citations enabled via ``H1_VALIDATION_ALLOWS_FIXTURES=1``.
  3. Emits per-target gap counts and writes the two output files
     alongside the target directory (never overwriting production
     artifacts — outputs land in ``h1_validation/`` subdirs).

Not a pytest module; run manually:

    python -m tests.h1_validation_harness

Expected outcome on real targets: ATTESTED count = 0 (no rows persisted),
candidate_only bucket dominates. This is not a defect — the harness is
demonstrating the projector accepts the real gc shape without crashing,
not that authority chains are populated. Populated-row validation lives
in the synthetic fixtures.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make the orchestrator package importable when the harness is run from
# the audio_bu_skill directory.
_HERE = Path(__file__).resolve()
_AUDIO_BU_SKILL = _HERE.parent.parent
if str(_AUDIO_BU_SKILL) not in sys.path:
    sys.path.insert(0, str(_AUDIO_BU_SKILL))

from orchestrator.hw_template.projector import (  # noqa: E402
    load_curated_overrides,
    project,
    write_outputs,
)


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _synthesise_gc_from_analysis(analysis: dict) -> dict:
    """Build a minimal gc-shell from a persisted qgenie_analysis.json.

    Real analyses do not carry ``cross_verification.rows`` on disk, so
    the harness inserts an empty rows list. Every emitted FactRecord
    will land as candidate_derived / NOT_ATTESTED — the worst-case path.
    """
    gc = {
        "soc": analysis.get("soc"),
        "codecs": analysis.get("codecs") or [],
        "amplifiers": analysis.get("amplifiers") or [],
        "buses": analysis.get("buses") or {},
        "soundwire": analysis.get("soundwire") or {},
        "ipcat": analysis.get("ipcat") or {},
        "cross_verification": {
            "rows": [],
            "snapshot_provenance": {
                "note": "H-1 validation harness — real target, rows not persisted",
            },
        },
    }
    return gc


def _run_real_target(target_name: str, target_dir: Path) -> dict:
    analysis_path = target_dir / "qgenie_analysis.json"
    if not analysis_path.is_file():
        return {
            "target": target_name,
            "status": "MISSING_ANALYSIS",
            "path": str(analysis_path),
        }
    analysis = _load_json(analysis_path)
    gc = _synthesise_gc_from_analysis(analysis)
    # WP_SCHEMATIC_ATTESTED_DESIGN §6 step 3/5: this is the live onboarding-time
    # write site. Auto-load targets/<t>/curated_overrides.json BY CONVENTION —
    # absent file → None (inert, un-curated target); malformed → loud. Nord ships
    # a SCHEMA-ONLY skeleton (six schematic leaves, value=null, no attestation):
    # every entry is a placeholder → skipped as un-curated → byte-identity
    # preserved until a human fills a leaf with a real cited value.
    curated = load_curated_overrides(
        target_dir / "curated_overrides.json", required=False
    )
    result = project(
        gc,
        target_name=target_name,
        run_id=f"h1-validation-{target_name}",
        curated_overrides=curated,
    )
    out_dir = target_dir / "h1_validation"
    write_outputs(result, out_dir)
    return {
        "target": target_name,
        "status": "OK",
        "gaps_by_reason": dict(result.gap_manifest.gap_count_by_reason),
        "total_gaps": len(result.gap_manifest.gaps),
        "codec_count": len(result.template.codecs),
        "amp_count": len(result.template.amplifiers),
        "bus_count": len(result.template.buses),
        "clock_count": len(result.template.clocks),
        "link_count": len(result.template.audio_links),
        "out_dir": str(out_dir),
    }


def _run_synthetic_target(target_name: str, target_dir: Path) -> dict:
    gc_path = target_dir / "gc.json"
    if not gc_path.is_file():
        return {"target": target_name, "status": "MISSING_GC", "path": str(gc_path)}
    gc = _load_json(gc_path)
    os.environ["H1_VALIDATION_ALLOWS_FIXTURES"] = "1"
    try:
        result = project(
            gc, target_name=target_name, run_id=f"h1-validation-{target_name}"
        )
    finally:
        # Leave the env untouched for other tools that may consume the
        # process env after this harness finishes.
        os.environ.pop("H1_VALIDATION_ALLOWS_FIXTURES", None)
    out_dir = target_dir
    write_outputs(result, out_dir)
    return {
        "target": target_name,
        "status": "OK",
        "gaps_by_reason": dict(result.gap_manifest.gap_count_by_reason),
        "total_gaps": len(result.gap_manifest.gaps),
        "codec_count": len(result.template.codecs),
        "amp_count": len(result.template.amplifiers),
        "bus_count": len(result.template.buses),
        "out_dir": str(out_dir),
    }


def main() -> int:
    targets_root = _AUDIO_BU_SKILL / "targets"
    reports = []
    reports.append(_run_real_target("nord-iq10", targets_root / "nord-iq10"))
    reports.append(_run_real_target("eliza", targets_root / "eliza"))
    reports.append(
        _run_synthetic_target("synthetic-i2s-min", targets_root / "synthetic-i2s-min")
    )
    reports.append(
        _run_synthetic_target("synthetic-swr-min", targets_root / "synthetic-swr-min")
    )
    print(json.dumps(reports, indent=2, sort_keys=False))
    # Exit non-zero if any target failed to project.
    for r in reports:
        if r.get("status") != "OK":
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
