"""codec_driver_porting schema + validation_rules enforcement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.schema_validation import SchemaValidationError, load_schema, validate_against

SCHEMA_PATH = Path(__file__).with_name("schema.json")


class CodecDriverPortingValidationError(SchemaValidationError):
    pass


def validate_input(input_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(input_envelope, schema, schema_key="input_envelope", error_code="CODEC_DRIVER_PORTING_INPUT_INVALID")


def validate_output(output_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(output_envelope, schema, schema_key="output_envelope", error_code="CODEC_DRIVER_PORTING_OUTPUT_INVALID")

    availability = output_envelope["codec_driver_availability"]
    per_codec = availability["per_codec"]
    evidence_refs = output_envelope["evidence"]["evidence_refs"]

    # must_check_upstream_kernel_tree_before_porting
    for part_number, verdict in per_codec.items():
        if verdict["status"] == "upstream_present" and not verdict.get("exists_on_disk"):
            raise CodecDriverPortingValidationError(
                code="UPSTREAM_CLAIM_UNVERIFIED",
                message="must_check_upstream_kernel_tree_before_porting: status=upstream_present but driver_path does not exist on disk",
                details={"codec_part_number": part_number, "driver_path": verdict.get("driver_path")},
            )

    # must_evidence_each_codec_verdict
    for part_number, verdict in per_codec.items():
        if verdict["status"] != "unresolved" and verdict.get("driver_path") not in evidence_refs:
            raise CodecDriverPortingValidationError(
                code="CODEC_VERDICT_NOT_EVIDENCED",
                message="must_evidence_each_codec_verdict: verdict's driver_path is not present in evidence_refs",
                details={"codec_part_number": part_number, "driver_path": verdict.get("driver_path")},
            )

    # must_flag_missing_drivers_before_dt_generation
    any_missing = any(v["status"] in ("needs_port", "needs_write", "unresolved") for v in per_codec.values())
    if any_missing and not availability["blocks_dt_generation"]:
        raise CodecDriverPortingValidationError(
            code="MISSING_DRIVER_NOT_FLAGGED",
            message="must_flag_missing_drivers_before_dt_generation: a codec needs porting/writing but blocks_dt_generation is not set",
            details={},
        )
