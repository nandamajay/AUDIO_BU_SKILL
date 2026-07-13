"""codec_driver_porting runner: confirms upstream codec/AudioReach driver
availability before DT generation proceeds.

Interactive/judgment skill — mostly a grep-and-confirm over kernel_source_path
for each codec_part_number's ASoC driver, but "driver exists but needs a
DT-binding tweak" vs. "driver is genuinely missing" is a judgment call
supplied by the caller via input_envelope["verdicts"] (keyed by part number).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_codec_driver_porting(input_envelope: dict[str, Any]) -> dict[str, Any]:
    run_id = input_envelope["run_id"]
    codec_part_numbers = input_envelope["codec_part_numbers"]
    kernel_source_path = Path(input_envelope["kernel_source_path"])
    verdicts = input_envelope.get("verdicts") or {}

    availability: dict[str, Any] = {}
    evidence_refs: list[str] = []
    for part_number in codec_part_numbers:
        verdict = verdicts.get(part_number)
        if not verdict or "driver_path" not in verdict or "status" not in verdict or verdict["driver_path"] is None:
            availability[part_number] = {"status": "unresolved", "driver_path": None}
            continue
        driver_path = kernel_source_path / verdict["driver_path"]
        availability[part_number] = {
            "status": verdict["status"],  # "upstream_present" | "needs_port" | "needs_write" | "unresolved"
            "driver_path": str(driver_path),
            "exists_on_disk": driver_path.is_file(),
        }
        if driver_path.is_file():
            evidence_refs.append(str(driver_path))

    blocks_dt_generation = any(v["status"] in ("needs_port", "needs_write", "unresolved") for v in availability.values())

    return {
        "codec_driver_availability": {
            "run_id": run_id,
            "per_codec": availability,
            "blocks_dt_generation": blocks_dt_generation,
        },
        "evidence": {"evidence_refs": evidence_refs},
    }
