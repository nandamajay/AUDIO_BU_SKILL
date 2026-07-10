"""source_intake schema + validation_rules enforcement.

Two layers, matching the laei skill-package shape: (1) schema.json
structural validation via jsonschema, (2) the skill.yaml
`validation_rules` semantic checks that a JSON Schema can't express
(e.g. "if ambiguities exist, human_review_needed must be true").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.schema_validation import SchemaValidationError, load_schema, validate_against

SCHEMA_PATH = Path(__file__).with_name("schema.json")


class SourceIntakeValidationError(SchemaValidationError):
    pass


def validate_input(input_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(input_envelope, schema, schema_key="input_envelope", error_code="SOURCE_INTAKE_INPUT_INVALID")


def validate_output(output_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(output_envelope, schema, schema_key="output_envelope", error_code="SOURCE_INTAKE_OUTPUT_INVALID")

    resolved = output_envelope["resolved_evidence_sources"]

    # must_resolve_ipcat_vs_offline_choice
    if resolved.get("evidence_source") not in ("ipcat", "offline_documents", "both", "ipcat_first"):
        raise SourceIntakeValidationError(
            code="IPCAT_VS_OFFLINE_UNRESOLVED",
            message="must_resolve_ipcat_vs_offline_choice: evidence_source was not resolved to a known choice",
            details={"evidence_source": resolved.get("evidence_source")},
        )

    # must_capture_power_model_source
    if not resolved.get("power_model_source"):
        raise SourceIntakeValidationError(
            code="POWER_MODEL_SOURCE_MISSING",
            message="must_capture_power_model_source: power_model_source was not captured",
            details={},
        )

    # must_flag_unresolved_ambiguities_for_human_review
    ambiguities = resolved.get("ambiguities") or []
    if ambiguities and not output_envelope.get("human_review_needed"):
        raise SourceIntakeValidationError(
            code="AMBIGUITY_NOT_FLAGGED",
            message="must_flag_unresolved_ambiguities_for_human_review: ambiguities present but human_review_needed is not set",
            details={"ambiguities": ambiguities},
        )
