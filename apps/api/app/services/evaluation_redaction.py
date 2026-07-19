"""Privacy boundary for persisted staging-quality evaluation records.

This module is intentionally narrower than a general-purpose evaluation
ingestion parser.  Staging results are accepted only when they are the
aggregate-only summary derived from the checked-in v2 synthetic fixture.  Raw
turns, source material, provider output, and free-form rationales never cross
this boundary or reach MongoDB.
"""

from __future__ import annotations

import hashlib
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping


# ``evals`` is repository-owned rather than an installed application package.
# Keep the import explicit so a deployment that omits the contract artifacts
# fails closed when staging evaluation ingestion is requested.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evals import staging_quality_contract as staging_contract  # noqa: E402


class EvaluationPrivacyError(ValueError):
    """A staging evaluation payload crossed a privacy or contract boundary."""


SAFE_REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9._:-]{1,127}$")
SAFE_REDACTED_RATIONALE_PATTERN = re.compile(r"^\[redacted\] [a-z][a-z0-9_]{2,79}$")

# The v2 contract already rejects direct identifiers, credentials and URLs.
# These names add evaluation-specific sinks that must never be accepted even if
# their values happen to be opaque.
FORBIDDEN_EVALUATION_FIELDS = frozenset(
    {
        "turns",
        "raw_turns",
        "synthetic_turns",
        "messages",
        "conversation_id",
        "conversation_ids",
        "customer_id",
        "customer_ids",
        "customer",
        "customers",
        "rationale",
        "reasoning",
        "raw_rationale",
        "birth_place",
        "birth_city",
        "birth_latitude",
        "birth_longitude",
        "birth_timezone",
        "provider",
        "provider_payload",
        "provider_response",
        "connector",
        "connector_payload",
        "connector_response",
        "tool_payload",
        "request_payload",
        "response_payload",
    }
)


def _reject_unsafe(value: Any, *, context: str) -> None:
    """Reject unsafe values and evaluation-only forbidden field names."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise EvaluationPrivacyError(f"{context} contains a non-string field name")
            if key.lower() in FORBIDDEN_EVALUATION_FIELDS:
                raise EvaluationPrivacyError(f"{context}.{key} is not permitted in a staging evaluation record")
            _reject_unsafe(nested, context=f"{context}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_unsafe(nested, context=f"{context}[{index}]")
        return
    try:
        staging_contract._reject_unsafe_values(value, context=context)
    except staging_contract.FixtureValidationError as exc:
        raise EvaluationPrivacyError(str(exc)) from exc


def _require_exact_fields(value: Any, fields: set[str], *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise EvaluationPrivacyError(f"{context} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _safe_reference(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not SAFE_REFERENCE_PATTERN.fullmatch(value.strip()):
        raise EvaluationPrivacyError(f"{context} must be an opaque lower-case reference")
    return value.strip()


def load_validated_contract() -> tuple[Any, Any]:
    """Load the existing v2 artifacts before accepting any external report."""
    try:
        return staging_contract.validate_artifacts()
    except (OSError, staging_contract.FixtureValidationError) as exc:
        raise EvaluationPrivacyError("The staging evaluation contract is unavailable or invalid") from exc


def validate_target_profile(
    value: Mapping[str, Any],
    *,
    allowed_profiles: set[str],
) -> dict[str, str]:
    """Require an allowlisted synthetic, read-only contract target."""
    _reject_unsafe(value, context="target_profile")
    target = _require_exact_fields(
        value,
        {"profile", "data_classification", "access_mode"},
        context="target_profile",
    )
    profile = _safe_reference(target["profile"], context="target_profile.profile")
    classification = _safe_reference(target["data_classification"], context="target_profile.data_classification")
    access_mode = _safe_reference(target["access_mode"], context="target_profile.access_mode")
    if not allowed_profiles or profile not in allowed_profiles:
        raise EvaluationPrivacyError("target_profile.profile is not an allowlisted protected staging target")
    if classification != "synthetic_only" or access_mode != "read_only":
        raise EvaluationPrivacyError("target_profile must be synthetic_only and read_only")

    cases, _ = load_validated_contract()
    valid_targets = {tuple(sorted(case.target_profile.items())) for case in cases.cases}
    normalized = {
        "profile": profile,
        "data_classification": classification,
        "access_mode": access_mode,
    }
    if tuple(sorted(normalized.items())) not in valid_targets:
        raise EvaluationPrivacyError("target_profile is not declared by the v2 staging contract")
    return normalized


def validate_sanitized_report(value: Any, *, max_cases: int) -> dict[str, Any]:
    """Accept only the aggregate v2 report produced by the validated fixture.

    Equality with ``sanitized_summary`` is deliberate: a caller may submit a
    detached copy of the offline report, but cannot turn this API into a raw
    evaluation-result sink or make outcome claims that the checked-in contract
    does not substantiate.
    """
    _reject_unsafe(value, context="report")
    cases, reviews = load_validated_contract()
    expected = staging_contract.sanitized_summary(cases, reviews)
    report = _require_exact_fields(value, set(expected), context="report")
    case_count = report.get("case_count")
    case_statuses = report.get("case_statuses")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
        raise EvaluationPrivacyError("report.case_count must be a positive integer")
    if case_count > max_cases:
        raise EvaluationPrivacyError("report.case_count exceeds EVAL_STAGING_MAX_CASES")
    if not isinstance(case_statuses, list) or len(case_statuses) > max_cases:
        raise EvaluationPrivacyError("report.case_statuses exceeds EVAL_STAGING_MAX_CASES")
    if report != expected:
        raise EvaluationPrivacyError("report must exactly match the validated v2 sanitized summary")
    # Return a fresh primitive dictionary, never a caller-owned mutable object.
    return dict(expected)


def dashboard_reviewer_reference(user_id: str | None, email: str | None) -> str:
    """Create an opaque reviewer reference without persisting personal data."""
    identity = str(user_id or email or "dashboard-operator")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"dashboard-reviewer-{digest}"


def validate_review_submission(
    value: Mapping[str, Any],
    *,
    reviewer_ref: str,
) -> dict[str, Any]:
    """Validate a redacted human or pinned-model second-opinion record.

    The contract validator checks dimensions, case/rubric hashes and the
    reviewer-type-specific pinned-model hash.  No provider or model code is
    imported or called here; a pinned model is only declared provenance.
    """
    _reject_unsafe(value, context="review")
    review = _require_exact_fields(
        value,
        {"case_id", "reviewer_type", "dimensions", "outcome", "redacted_rationale", "provenance"},
        context="review",
    )
    reviewer_type = _safe_reference(review["reviewer_type"], context="review.reviewer_type")
    if reviewer_type not in staging_contract.ALLOWED_REVIEWER_TYPES:
        raise EvaluationPrivacyError("review.reviewer_type must be human or pinned_model")
    rationale = review.get("redacted_rationale")
    if not isinstance(rationale, str) or not SAFE_REDACTED_RATIONALE_PATTERN.fullmatch(rationale.strip()):
        raise EvaluationPrivacyError("review.redacted_rationale must be a redacted rationale tag")

    cases, _ = load_validated_contract()
    review_id = f"review-{uuid.uuid4()}"
    contract_input = {
        "id": review_id,
        "case_id": review["case_id"],
        "reviewer_type": reviewer_type,
        "reviewer_ref": _safe_reference(reviewer_ref, context="reviewer_ref"),
        "dimensions": review["dimensions"],
        "outcome": review["outcome"],
        "redacted_rationale": rationale.strip(),
        "provenance": review["provenance"],
    }
    try:
        validated = staging_contract._validate_review(
            contract_input,
            index=0,
            cases_by_id={case.case_id: case for case in cases.cases},
        )
    except staging_contract.FixtureValidationError as exc:
        raise EvaluationPrivacyError(str(exc)) from exc
    return {
        "id": validated.review_id,
        "case_id": validated.case_id,
        "reviewer_type": validated.reviewer_type,
        "reviewer_ref": validated.reviewer_ref,
        "dimensions": [dict(dimension) for dimension in validated.dimensions],
        "outcome": validated.outcome,
        "redacted_rationale": validated.redacted_rationale,
        "provenance": dict(validated.provenance),
    }
