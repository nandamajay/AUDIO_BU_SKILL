"""triage schema + validation_rules enforcement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.schema_validation import SchemaValidationError, load_schema, validate_against

SCHEMA_PATH = Path(__file__).with_name("schema.json")

KNOWN_FAILURE_CATEGORIES = {"dt_generation", "compile", "boot_pas", "audio_path", "binding_review"}


class TriageValidationError(SchemaValidationError):
    pass


def validate_input(input_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(input_envelope, schema, schema_key="input_envelope", error_code="TRIAGE_INPUT_INVALID")


def validate_output(output_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(output_envelope, schema, schema_key="output_envelope", error_code="TRIAGE_OUTPUT_INVALID")

    diagnosis = output_envelope["triage_diagnosis"]
    unresolved = diagnosis["unresolved"]

    # must_mark_unresolved_if_no_root_cause_found
    if not diagnosis.get("root_cause") and not unresolved:
        raise TriageValidationError(
            code="ROOT_CAUSE_MISSING_NOT_FLAGGED",
            message="must_mark_unresolved_if_no_root_cause_found: no root_cause present but unresolved is not set",
            details={},
        )

    # must_classify_failure_category (only meaningful once a root cause is claimed)
    if not unresolved:
        category = diagnosis.get("failure_category")
        if category not in KNOWN_FAILURE_CATEGORIES:
            raise TriageValidationError(
                code="FAILURE_CATEGORY_UNCLASSIFIED",
                message="must_classify_failure_category: failure_category is missing or not one of the known gate categories",
                details={"failure_category": category, "allowed": sorted(KNOWN_FAILURE_CATEGORIES)},
            )

        # must_cite_evidence_for_diagnosis
        cited_evidence = output_envelope["evidence"]["evidence_refs"]
        if not cited_evidence:
            raise TriageValidationError(
                code="DIAGNOSIS_EVIDENCE_MISSING",
                message="must_cite_evidence_for_diagnosis: a resolved diagnosis must cite at least one evidence_ref",
                details={},
            )
