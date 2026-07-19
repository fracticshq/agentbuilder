"""Strict, offline contracts for privacy-safe staging evaluation artifacts.

The staging fixtures intentionally contain opaque synthetic descriptors rather
than prompts, customer data, source text, tenant identifiers, or credentials.
This module uses only the Python standard library so validation remains safe
to run in CI and in disconnected environments.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_FIXTURE_PATH = REPO_ROOT / "evals" / "cases" / "v2" / "staging_quality_cases.json"
REVIEW_RECORDS_PATH = REPO_ROOT / "evals" / "cases" / "v2" / "staging_quality_reviews.json"

CASE_SCHEMA_VERSION = "staging-quality-cases/v2"
REVIEW_SCHEMA_VERSION = "staging-quality-reviews/v2"
SUMMARY_SCHEMA_VERSION = "staging-quality-summary/v2"

REQUIRED_SUITES = frozenset(
    {
        "hybrid_rag",
        "ecommerce",
        "shopify",
        "lalkitab",
        "provider_outage",
        "prompt_injection",
        "tenant_isolation",
    }
)
ALLOWED_REVIEWER_TYPES = frozenset({"human", "pinned_model"})
ALLOWED_REVIEW_OUTCOMES = frozenset({"pass", "fail", "needs_adjudication"})
ALLOWED_DIMENSION_OUTCOMES = frozenset({"pass", "fail", "needs_adjudication"})
ALLOWED_TURN_ROLES = frozenset({"synthetic_user", "synthetic_assistant", "synthetic_system"})
ALLOWED_DATA_CLASSIFICATIONS = frozenset({"synthetic_only"})

CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
SAFE_REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9._:-]{1,127}$")
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")

# The detector deliberately targets credential-shaped values, URLs, and common
# direct identifiers. It is defense in depth: the strict schemas also avoid
# free-form prompt/source fields entirely.
UNSAFE_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b(?:api[_-]?key|password|secret|access[_-]?token|authorization)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bhttps?://", re.IGNORECASE),
    re.compile(r"\bwww\.", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\+?\d[\d .()\-]{7,}\d)\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:19|20)\d{2}[-/]\d{2}[-/]\d{2}\b"),
    re.compile(r"\b(?:date[ _-]?of[ _-]?birth|birth[ _-]?(?:date|time)|dob)\b", re.IGNORECASE),
    re.compile(r"\btenant[ _-]?id\s*[:=]\s*\S+", re.IGNORECASE),
)
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "query",
        "raw_query",
        "prompt",
        "system_prompt",
        "source",
        "sources",
        "source_text",
        "source_url",
        "tenant_id",
        "brand_id",
        "customer_id",
        "user_id",
        "birth_date",
        "date_of_birth",
        "birth_time",
        "credentials",
        "api_key",
        "access_token",
        "authorization",
        "password",
        "secret",
    }
)


class FixtureValidationError(ValueError):
    """Raised when a staging artifact is malformed or privacy-unsafe."""


@dataclass(frozen=True)
class StagingCase:
    """A validated synthetic staging scenario with no executable payload."""

    case_id: str
    suite: str
    fixture: Mapping[str, Any]
    rubric: Mapping[str, Any]
    seed: Mapping[str, Any]
    target_profile: Mapping[str, Any]
    synthetic_turns: tuple[Mapping[str, str], ...]
    public_invariants: tuple[str, ...]
    side_effect_mode: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class StagingCaseFixture:
    """The complete versioned case fixture."""

    schema_version: str
    suite: str
    side_effect_mode: str
    cases: tuple[StagingCase, ...]


@dataclass(frozen=True)
class ReviewRecord:
    """A privacy-safe human or pinned-model review record."""

    review_id: str
    case_id: str
    reviewer_type: str
    reviewer_ref: str
    dimensions: tuple[Mapping[str, str], ...]
    outcome: str
    redacted_rationale: str
    provenance: Mapping[str, str | None]


@dataclass(frozen=True)
class ReviewRecordFixture:
    """Validated review records and the review policy governing them."""

    schema_version: str
    review_policy: Mapping[str, Any]
    reviews: tuple[ReviewRecord, ...]


def canonical_sha256(value: Any) -> str:
    """Return a stable SHA-256 for provenance over a JSON-compatible value."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json(path: Path, *, artifact_name: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureValidationError(f"{artifact_name} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureValidationError(f"{artifact_name} is not valid JSON: {exc.msg}") from exc


def _require_exact_object(value: Any, fields: set[str], *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FixtureValidationError(f"{context} must be an object")
    if set(value) != fields:
        raise FixtureValidationError(f"{context} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _require_string(value: Any, *, context: str, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{context} must be a non-empty string")
    text = value.strip()
    if len(text) > max_length:
        raise FixtureValidationError(f"{context} exceeds {max_length} characters")
    return text


def _require_safe_tag(value: Any, *, context: str) -> str:
    text = _require_string(value, context=context, max_length=80)
    if not SAFE_TAG_PATTERN.fullmatch(text):
        raise FixtureValidationError(f"{context} must be a lower_snake_case public tag")
    return text


def _require_safe_reference(value: Any, *, context: str) -> str:
    text = _require_string(value, context=context, max_length=128)
    if not SAFE_REFERENCE_PATTERN.fullmatch(text):
        raise FixtureValidationError(f"{context} must be an opaque lower-case reference")
    return text


def _require_hash(value: Any, *, context: str, allow_null: bool = False) -> str | None:
    if value is None and allow_null:
        return None
    text = _require_string(value, context=context, max_length=64)
    if not HASH_PATTERN.fullmatch(text):
        raise FixtureValidationError(f"{context} must be a lowercase SHA-256 hash")
    return text


def _reject_unsafe_values(value: Any, *, context: str) -> None:
    """Reject direct identifiers, URLs, credential-like values, and hidden fields."""
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise FixtureValidationError(f"{context} contains a non-string field name")
            if key.lower() in FORBIDDEN_FIELD_NAMES:
                raise FixtureValidationError(f"{context}.{key} is not allowed in a privacy-safe artifact")
            _reject_unsafe_values(nested_value, context=f"{context}.{key}")
        return
    if isinstance(value, list):
        for index, nested_value in enumerate(value):
            _reject_unsafe_values(nested_value, context=f"{context}[{index}]")
        return
    if isinstance(value, str):
        for pattern in UNSAFE_VALUE_PATTERNS:
            if pattern.search(value):
                raise FixtureValidationError(f"{context} contains an unsafe secret-like or identifying value")


def _validate_fixture_reference(value: Any, *, context: str) -> Mapping[str, str]:
    record = _require_exact_object(value, {"id", "version", "sha256"}, context=context)
    return {
        "id": _require_safe_reference(record["id"], context=f"{context}.id"),
        "version": _require_safe_reference(record["version"], context=f"{context}.version"),
        "sha256": _require_hash(record["sha256"], context=f"{context}.sha256") or "",
    }


def _validate_rubric(value: Any, *, context: str) -> Mapping[str, Any]:
    record = _require_exact_object(value, {"id", "version", "dimensions"}, context=context)
    dimensions = record["dimensions"]
    if not isinstance(dimensions, list) or not dimensions:
        raise FixtureValidationError(f"{context}.dimensions must be a non-empty array")
    normalized_dimensions = tuple(
        _require_safe_tag(dimension, context=f"{context}.dimensions[{index}]")
        for index, dimension in enumerate(dimensions)
    )
    if len(normalized_dimensions) != len(set(normalized_dimensions)):
        raise FixtureValidationError(f"{context}.dimensions must not contain duplicates")
    return {
        "id": _require_safe_reference(record["id"], context=f"{context}.id"),
        "version": _require_safe_reference(record["version"], context=f"{context}.version"),
        "dimensions": normalized_dimensions,
    }


def _validate_seed(value: Any, *, context: str) -> Mapping[str, Any]:
    record = _require_exact_object(value, {"algorithm", "value"}, context=context)
    algorithm = _require_safe_reference(record["algorithm"], context=f"{context}.algorithm")
    if algorithm != "deterministic":
        raise FixtureValidationError(f"{context}.algorithm must be deterministic")
    seed_value = record["value"]
    if isinstance(seed_value, bool) or not isinstance(seed_value, int) or not 0 <= seed_value <= 2_147_483_647:
        raise FixtureValidationError(f"{context}.value must be a non-negative 32-bit integer")
    return {"algorithm": algorithm, "value": seed_value}


def _validate_target_profile(value: Any, *, context: str) -> Mapping[str, str]:
    record = _require_exact_object(
        value,
        {"profile", "data_classification", "access_mode"},
        context=context,
    )
    profile = _require_safe_reference(record["profile"], context=f"{context}.profile")
    classification = _require_safe_tag(record["data_classification"], context=f"{context}.data_classification")
    access_mode = _require_safe_reference(record["access_mode"], context=f"{context}.access_mode")
    if classification not in ALLOWED_DATA_CLASSIFICATIONS:
        raise FixtureValidationError(f"{context}.data_classification must be synthetic_only")
    if access_mode != "read_only":
        raise FixtureValidationError(f"{context}.access_mode must be read_only")
    return {"profile": profile, "data_classification": classification, "access_mode": access_mode}


def _validate_synthetic_turns(value: Any, *, context: str) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, list) or len(value) < 2:
        raise FixtureValidationError(f"{context} must contain at least two synthetic turns")

    turns: list[Mapping[str, str]] = []
    for index, raw_turn in enumerate(value, start=1):
        turn_context = f"{context}[{index - 1}]"
        turn = _require_exact_object(raw_turn, {"turn_id", "role", "intent", "input_descriptor"}, context=turn_context)
        expected_turn_id = f"turn_{index:02d}"
        turn_id = _require_safe_reference(turn["turn_id"], context=f"{turn_context}.turn_id")
        if turn_id != expected_turn_id:
            raise FixtureValidationError(f"{turn_context}.turn_id must be sequential ({expected_turn_id})")
        role = _require_safe_reference(turn["role"], context=f"{turn_context}.role")
        if role not in ALLOWED_TURN_ROLES:
            raise FixtureValidationError(f"{turn_context}.role must be a synthetic role")
        turns.append(
            {
                "turn_id": turn_id,
                "role": role,
                "intent": _require_safe_tag(turn["intent"], context=f"{turn_context}.intent"),
                "input_descriptor": _require_safe_tag(
                    turn["input_descriptor"], context=f"{turn_context}.input_descriptor"
                ),
            }
        )
    return tuple(turns)


def _validate_invariants(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FixtureValidationError(f"{context} must be a non-empty array")
    invariants = tuple(
        _require_safe_tag(invariant, context=f"{context}[{index}]") for index, invariant in enumerate(value)
    )
    if len(invariants) != len(set(invariants)):
        raise FixtureValidationError(f"{context} must not contain duplicates")
    return invariants


def _validate_case(value: Any, *, index: int) -> StagingCase:
    context = f"cases[{index}]"
    _reject_unsafe_values(value, context=context)
    case = _require_exact_object(
        value,
        {
            "id",
            "suite",
            "fixture",
            "rubric",
            "seed",
            "target_profile",
            "synthetic_turns",
            "public_invariants",
            "side_effect_mode",
        },
        context=context,
    )
    case_id = _require_string(case["id"], context=f"{context}.id", max_length=96)
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise FixtureValidationError(f"{context}.id must be lower-kebab-case")
    suite = _require_safe_tag(case["suite"], context=f"{context}.suite")
    if suite not in REQUIRED_SUITES:
        raise FixtureValidationError(f"{context}.suite is not a supported staging suite")
    side_effect_mode = _require_safe_reference(case["side_effect_mode"], context=f"{context}.side_effect_mode")
    if side_effect_mode != "read_only":
        raise FixtureValidationError(f"{context}.side_effect_mode must be read_only")

    fixture = _validate_fixture_reference(case["fixture"], context=f"{context}.fixture")
    rubric = _validate_rubric(case["rubric"], context=f"{context}.rubric")
    seed = _validate_seed(case["seed"], context=f"{context}.seed")
    target_profile = _validate_target_profile(case["target_profile"], context=f"{context}.target_profile")
    synthetic_turns = _validate_synthetic_turns(case["synthetic_turns"], context=f"{context}.synthetic_turns")
    public_invariants = _validate_invariants(case["public_invariants"], context=f"{context}.public_invariants")

    return StagingCase(
        case_id=case_id,
        suite=suite,
        fixture=fixture,
        rubric=rubric,
        seed=seed,
        target_profile=target_profile,
        synthetic_turns=synthetic_turns,
        public_invariants=public_invariants,
        side_effect_mode=side_effect_mode,
        raw=value,
    )


def load_case_fixture(path: Path = CASE_FIXTURE_PATH) -> StagingCaseFixture:
    """Load and strictly validate the versioned synthetic staging cases."""
    raw_fixture = _load_json(path, artifact_name="staging case fixture")
    _reject_unsafe_values(raw_fixture, context="fixture")
    fixture = _require_exact_object(
        raw_fixture,
        {"schema_version", "artifact_kind", "suite", "side_effect_mode", "cases"},
        context="fixture",
    )
    if fixture["schema_version"] != CASE_SCHEMA_VERSION:
        raise FixtureValidationError(f"fixture.schema_version must be {CASE_SCHEMA_VERSION}")
    if fixture["artifact_kind"] != "synthetic_staging_cases":
        raise FixtureValidationError("fixture.artifact_kind must be synthetic_staging_cases")
    suite = _require_safe_tag(fixture["suite"], context="fixture.suite")
    if suite != "staging_quality":
        raise FixtureValidationError("fixture.suite must be staging_quality")
    side_effect_mode = _require_safe_reference(fixture["side_effect_mode"], context="fixture.side_effect_mode")
    if side_effect_mode != "read_only":
        raise FixtureValidationError("fixture.side_effect_mode must be read_only")
    if not isinstance(fixture["cases"], list) or not fixture["cases"]:
        raise FixtureValidationError("fixture.cases must be a non-empty array")

    cases = tuple(_validate_case(case, index=index) for index, case in enumerate(fixture["cases"]))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise FixtureValidationError("fixture.cases must not contain duplicate case IDs")
    covered_suites = {case.suite for case in cases}
    missing_suites = REQUIRED_SUITES - covered_suites
    if missing_suites:
        raise FixtureValidationError(f"fixture is missing required suite(s): {', '.join(sorted(missing_suites))}")

    return StagingCaseFixture(
        schema_version=CASE_SCHEMA_VERSION,
        suite=suite,
        side_effect_mode=side_effect_mode,
        cases=cases,
    )


def _validate_review_policy(value: Any) -> Mapping[str, Any]:
    policy = _require_exact_object(
        value,
        {"human_review_primary", "pinned_model_second_opinion", "llm_faithfulness_metrics"},
        context="review_fixture.review_policy",
    )
    if policy["human_review_primary"] is not True:
        raise FixtureValidationError("review_fixture.review_policy.human_review_primary must be true")
    if policy["pinned_model_second_opinion"] != "optional":
        raise FixtureValidationError(
            "review_fixture.review_policy.pinned_model_second_opinion must be optional"
        )
    if policy["llm_faithfulness_metrics"] != "not_claimed":
        raise FixtureValidationError("review_fixture.review_policy.llm_faithfulness_metrics must be not_claimed")
    return dict(policy)


def _validate_review_dimensions(value: Any, *, context: str, rubric_dimensions: Sequence[str]) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise FixtureValidationError(f"{context} must be a non-empty array")
    dimensions: list[Mapping[str, str]] = []
    for index, raw_dimension in enumerate(value):
        dimension_context = f"{context}[{index}]"
        dimension = _require_exact_object(raw_dimension, {"name", "outcome"}, context=dimension_context)
        name = _require_safe_tag(dimension["name"], context=f"{dimension_context}.name")
        outcome = _require_safe_reference(dimension["outcome"], context=f"{dimension_context}.outcome")
        if outcome not in ALLOWED_DIMENSION_OUTCOMES:
            raise FixtureValidationError(f"{dimension_context}.outcome is not supported")
        dimensions.append({"name": name, "outcome": outcome})
    names = [dimension["name"] for dimension in dimensions]
    if len(names) != len(set(names)):
        raise FixtureValidationError(f"{context} must not contain duplicate dimensions")
    if set(names) != set(rubric_dimensions):
        raise FixtureValidationError(f"{context} must exactly match the case rubric dimensions")
    return tuple(dimensions)


def _validate_redacted_rationale(value: Any, *, context: str) -> str:
    rationale = _require_string(value, context=context, max_length=96)
    if not re.fullmatch(r"\[redacted\] [a-z][a-z0-9_]{2,79}", rationale):
        raise FixtureValidationError(
            f"{context} must be [redacted] followed by one opaque lower_snake_case rationale tag"
        )
    return rationale


def _validate_provenance(value: Any, *, context: str, case: StagingCase, reviewer_type: str) -> Mapping[str, str | None]:
    provenance = _require_exact_object(
        value,
        {
            "case_sha256",
            "fixture_sha256",
            "rubric_sha256",
            "review_protocol_sha256",
            "pinned_model_sha256",
        },
        context=context,
    )
    validated = {
        "case_sha256": _require_hash(provenance["case_sha256"], context=f"{context}.case_sha256"),
        "fixture_sha256": _require_hash(provenance["fixture_sha256"], context=f"{context}.fixture_sha256"),
        "rubric_sha256": _require_hash(provenance["rubric_sha256"], context=f"{context}.rubric_sha256"),
        "review_protocol_sha256": _require_hash(
            provenance["review_protocol_sha256"], context=f"{context}.review_protocol_sha256"
        ),
        "pinned_model_sha256": _require_hash(
            provenance["pinned_model_sha256"],
            context=f"{context}.pinned_model_sha256",
            allow_null=True,
        ),
    }
    if validated["case_sha256"] != canonical_sha256(case.raw):
        raise FixtureValidationError(f"{context}.case_sha256 does not match the referenced case")
    if validated["fixture_sha256"] != case.fixture["sha256"]:
        raise FixtureValidationError(f"{context}.fixture_sha256 does not match the case fixture reference")
    if validated["rubric_sha256"] != canonical_sha256(case.rubric):
        raise FixtureValidationError(f"{context}.rubric_sha256 does not match the case rubric")
    if reviewer_type == "pinned_model" and validated["pinned_model_sha256"] is None:
        raise FixtureValidationError(f"{context}.pinned_model_sha256 is required for a pinned_model review")
    if reviewer_type == "human" and validated["pinned_model_sha256"] is not None:
        raise FixtureValidationError(f"{context}.pinned_model_sha256 must be null for a human review")
    return validated


def _validate_review(value: Any, *, index: int, cases_by_id: Mapping[str, StagingCase]) -> ReviewRecord:
    context = f"reviews[{index}]"
    _reject_unsafe_values(value, context=context)
    review = _require_exact_object(
        value,
        {
            "id",
            "case_id",
            "reviewer_type",
            "reviewer_ref",
            "dimensions",
            "outcome",
            "redacted_rationale",
            "provenance",
        },
        context=context,
    )
    review_id = _require_string(review["id"], context=f"{context}.id", max_length=96)
    if not CASE_ID_PATTERN.fullmatch(review_id):
        raise FixtureValidationError(f"{context}.id must be lower-kebab-case")
    case_id = _require_string(review["case_id"], context=f"{context}.case_id", max_length=96)
    if case_id not in cases_by_id:
        raise FixtureValidationError(f"{context}.case_id does not reference a known case")
    reviewer_type = _require_safe_reference(review["reviewer_type"], context=f"{context}.reviewer_type")
    if reviewer_type not in ALLOWED_REVIEWER_TYPES:
        raise FixtureValidationError(f"{context}.reviewer_type must be human or pinned_model")
    reviewer_ref = _require_safe_reference(review["reviewer_ref"], context=f"{context}.reviewer_ref")
    case = cases_by_id[case_id]
    dimensions = _validate_review_dimensions(
        review["dimensions"], context=f"{context}.dimensions", rubric_dimensions=case.rubric["dimensions"]
    )
    outcome = _require_safe_reference(review["outcome"], context=f"{context}.outcome")
    if outcome not in ALLOWED_REVIEW_OUTCOMES:
        raise FixtureValidationError(f"{context}.outcome must be pass, fail, or needs_adjudication")
    dimension_outcomes = {dimension["outcome"] for dimension in dimensions}
    if outcome == "pass" and dimension_outcomes != {"pass"}:
        raise FixtureValidationError(f"{context}.outcome pass requires all dimensions to pass")
    if outcome == "fail" and "fail" not in dimension_outcomes:
        raise FixtureValidationError(f"{context}.outcome fail requires at least one failed dimension")
    rationale = _validate_redacted_rationale(review["redacted_rationale"], context=f"{context}.redacted_rationale")
    provenance = _validate_provenance(
        review["provenance"], context=f"{context}.provenance", case=case, reviewer_type=reviewer_type
    )
    return ReviewRecord(
        review_id=review_id,
        case_id=case_id,
        reviewer_type=reviewer_type,
        reviewer_ref=reviewer_ref,
        dimensions=dimensions,
        outcome=outcome,
        redacted_rationale=rationale,
        provenance=provenance,
    )


def load_review_records(
    path: Path = REVIEW_RECORDS_PATH, *, cases: StagingCaseFixture | None = None
) -> ReviewRecordFixture:
    """Load review records; human review remains the required decision-maker."""
    case_fixture = cases or load_case_fixture()
    raw_fixture = _load_json(path, artifact_name="staging review records")
    _reject_unsafe_values(raw_fixture, context="review_fixture")
    fixture = _require_exact_object(
        raw_fixture,
        {"schema_version", "artifact_kind", "review_policy", "reviews"},
        context="review_fixture",
    )
    if fixture["schema_version"] != REVIEW_SCHEMA_VERSION:
        raise FixtureValidationError(f"review_fixture.schema_version must be {REVIEW_SCHEMA_VERSION}")
    if fixture["artifact_kind"] != "staging_quality_review_records":
        raise FixtureValidationError("review_fixture.artifact_kind must be staging_quality_review_records")
    policy = _validate_review_policy(fixture["review_policy"])
    if not isinstance(fixture["reviews"], list):
        raise FixtureValidationError("review_fixture.reviews must be an array")
    cases_by_id = {case.case_id: case for case in case_fixture.cases}
    reviews = tuple(
        _validate_review(review, index=index, cases_by_id=cases_by_id)
        for index, review in enumerate(fixture["reviews"])
    )
    review_ids = [review.review_id for review in reviews]
    if len(review_ids) != len(set(review_ids)):
        raise FixtureValidationError("review_fixture.reviews must not contain duplicate review IDs")
    return ReviewRecordFixture(schema_version=REVIEW_SCHEMA_VERSION, review_policy=policy, reviews=reviews)


def validate_artifacts(
    case_path: Path = CASE_FIXTURE_PATH, review_path: Path = REVIEW_RECORDS_PATH
) -> tuple[StagingCaseFixture, ReviewRecordFixture]:
    """Validate both versioned artifacts without contacting any external system."""
    cases = load_case_fixture(case_path)
    return cases, load_review_records(review_path, cases=cases)


def sanitized_summary(cases: StagingCaseFixture, reviews: ReviewRecordFixture) -> dict[str, Any]:
    """Return aggregate-only data suitable for an offline CI artifact.

    The summary deliberately omits turns, descriptors, invariants, rationales,
    provenance values, prompts, and any possible source payload.
    """
    suite_counts: dict[str, int] = {}
    for case in cases.cases:
        suite_counts[case.suite] = suite_counts.get(case.suite, 0) + 1
    reviewer_type_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    human_outcomes_by_case: dict[str, list[str]] = {case.case_id: [] for case in cases.cases}
    for review in reviews.reviews:
        reviewer_type_counts[review.reviewer_type] = reviewer_type_counts.get(review.reviewer_type, 0) + 1
        outcome_counts[review.outcome] = outcome_counts.get(review.outcome, 0) + 1
        if review.reviewer_type == "human":
            human_outcomes_by_case[review.case_id].append(review.outcome)

    case_statuses = []
    for case in cases.cases:
        human_outcomes = human_outcomes_by_case[case.case_id]
        if not human_outcomes:
            review_status = "pending_human_review"
        elif "fail" in human_outcomes:
            review_status = "fail"
        elif "needs_adjudication" in human_outcomes:
            review_status = "needs_adjudication"
        else:
            review_status = "pass"
        case_statuses.append({"id": case.case_id, "suite": case.suite, "review_status": review_status})

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "artifact_kind": "staging_quality_sanitized_summary",
        "side_effect_mode": "read_only",
        "case_count": len(cases.cases),
        "case_counts_by_suite": dict(sorted(suite_counts.items())),
        "review_count": len(reviews.reviews),
        "review_counts_by_reviewer_type": dict(sorted(reviewer_type_counts.items())),
        "review_counts_by_outcome": dict(sorted(outcome_counts.items())),
        "case_statuses": case_statuses,
    }
