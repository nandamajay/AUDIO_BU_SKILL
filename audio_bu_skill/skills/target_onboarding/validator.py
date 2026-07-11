"""target_onboarding schema + validation_rules enforcement.

Two layers, matching the skill-package shape: (1) schema.json structural
validation via jsonschema, (2) the skill.yaml `validation_rules` semantic checks
a JSON Schema can't express. The rules encode the human-review contract: at
least one candidate must be ranked, low confidence must force human review, and
a field the runner marked uncertain (in generated_case.needs_review) must not be
presented as finalized elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.schema_validation import SchemaValidationError, load_schema, validate_against

SCHEMA_PATH = Path(__file__).with_name("schema.json")


class TargetOnboardingValidationError(SchemaValidationError):
    pass


def validate_input(input_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(input_envelope, schema, schema_key="input_envelope",
                     error_code="TARGET_ONBOARDING_INPUT_INVALID")


def validate_output(output_envelope: dict[str, Any]) -> None:
    schema = load_schema(SCHEMA_PATH)
    validate_against(output_envelope, schema, schema_key="output_envelope",
                     error_code="TARGET_ONBOARDING_OUTPUT_INVALID")

    similarity = output_envelope["similarity_report"]
    generated = output_envelope["generated_case"]

    # must_rank_at_least_one_candidate
    ranked = similarity.get("ranked") or []
    if not ranked:
        raise TargetOnboardingValidationError(
            code="NO_CANDIDATE_RANKED",
            message="must_rank_at_least_one_candidate: similarity_report.ranked is empty",
            details={},
        )

    # must_flag_low_confidence_for_human_review
    conf = similarity.get("confidence") or {}
    if conf.get("low_confidence") and not output_envelope.get("human_review_needed"):
        raise TargetOnboardingValidationError(
            code="LOW_CONFIDENCE_NOT_FLAGGED",
            message="must_flag_low_confidence_for_human_review: confidence is low but human_review_needed is not set",
            details={"confidence": conf},
        )

    # must_not_finalize_uncertain_fields:
    #   (a) when the nearest-target choice is low-confidence, inherit_from must be
    #       left empty (not auto-finalized to a guessed parent), and
    #   (b) power_model_source is never auto-finalized (rpmhpd-vs-SCMI is the Nord
    #       blocker class) — it must always be flagged in needs_review.
    # needs_review entries are "<field>: <reason>" notes; key them by field name.
    needs_review = generated.get("needs_review") or []
    review_fields = {str(note).split(":", 1)[0].strip() for note in needs_review}
    if conf.get("low_confidence") and generated.get("inherit_from"):
        raise TargetOnboardingValidationError(
            code="UNCERTAIN_FIELD_FINALIZED",
            message="must_not_finalize_uncertain_fields: inherit_from was finalized despite low-confidence nearest-target",
            details={"inherit_from": generated.get("inherit_from"), "confidence": conf},
        )
    # power_model_source is never auto-finalized (rpmhpd-vs-SCMI is the Nord blocker class).
    if "power_model_source" not in review_fields:
        raise TargetOnboardingValidationError(
            code="POWER_MODEL_FINALIZED",
            message="must_not_finalize_uncertain_fields: power_model_source must be flagged NEEDS_REVIEW, never finalized",
            details={"power_model_source": generated.get("power_model_source")},
        )
