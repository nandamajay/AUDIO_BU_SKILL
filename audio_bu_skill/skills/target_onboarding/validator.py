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

    # must_use_qgenie_engine: the intelligent path is QGenie-only in production; a
    # "local-test" result reaching here without test_mode means the no-fallback
    # gate in orchestrator.reasoning.get_reasoning_client was bypassed somehow —
    # this is the last-line defense, not the primary enforcement point.
    reasoning = output_envelope.get("_reasoning") or {}
    engine_id = reasoning.get("engine_id")
    if engine_id == "local-test" and not reasoning.get("test_mode"):
        raise TargetOnboardingValidationError(
            code="LOCAL_ENGINE_BLOCKED",
            message="must_use_qgenie_engine: local-test engine result reached the validator outside test_mode",
            details={"engine_id": engine_id},
        )

    # must_cite_evidence_per_finding / must_flag_missing_evidence apply to the
    # real QGenie engine only — the demoted local-test comparator is documented
    # to never read datasheet/IPCAT content, so holding it to the same
    # evidentiary bar would just make the test-only escape hatch unusable.
    if engine_id != "qgenie":
        return

    # must_cite_evidence_per_finding: every QGenie finding with a non-zero
    # confidence must carry at least one citation — an uncited "fact" is not
    # auditable and must not be trusted.
    analysis = (output_envelope.get("target_profile") or {}).get("qgenie_analysis") or {}
    uncited = _findings_without_citations(analysis)
    if uncited:
        raise TargetOnboardingValidationError(
            code="FINDING_MISSING_CITATION",
            message="must_cite_evidence_per_finding: QGenie findings with confidence > 0 must cite evidence",
            details={"uncited_findings": uncited},
        )

    # must_flag_missing_evidence: anything QGenie listed as missing must surface
    # in generated_case.needs_review so a human sees it before promoting the case.
    for missing in analysis.get("missing_evidence") or []:
        note = f"missing_evidence: {missing}"
        if note not in needs_review:
            raise TargetOnboardingValidationError(
                code="MISSING_EVIDENCE_NOT_FLAGGED",
                message="must_flag_missing_evidence: QGenie-reported missing evidence was not carried into needs_review",
                details={"missing_evidence": missing},
            )


def _findings_without_citations(analysis: dict[str, Any]) -> list[str]:
    """Return dotted-path labels of any confident finding lacking a citation."""
    uncited: list[str] = []

    def _check(label: str, block: Any) -> None:
        if not isinstance(block, dict):
            return
        confidence = block.get("confidence")
        if confidence and float(confidence) > 0 and not block.get("citations"):
            uncited.append(label)

    _check("soc", analysis.get("soc"))
    _check("soundwire", analysis.get("soundwire"))
    _check("power_model", analysis.get("power_model"))
    for group_key in ("codecs", "amplifiers", "mics", "speakers", "buses"):
        for i, item in enumerate(analysis.get(group_key) or []):
            _check(f"{group_key}[{i}]", item)
    for i, item in enumerate(analysis.get("nearest_targets") or []):
        if isinstance(item, dict) and float(item.get("score") or 0) > 0 and not item.get("citations"):
            uncited.append(f"nearest_targets[{i}]")
    return uncited
