"""Protected staging-only storage and review APIs for synthetic eval evidence."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import ensure_brand_access, ensure_permission, require_dashboard_access
from app.auth.models import Permission, User
from app.config import Settings
from app.connections import connection_manager
from app.dependencies import get_settings
from app.services.agent_api_keys import AgentApiKeyContext, AgentApiKeyService
from app.services.evaluation_redaction import (
    EvaluationPrivacyError,
    dashboard_reviewer_reference,
    validate_review_submission,
    validate_sanitized_report,
    validate_target_profile,
)
from app.services.quality_evaluation_store import QualityEvaluationStore, QualityEvaluationStoreError


router = APIRouter()
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetProfileRequest(_StrictRequest):
    profile: str = Field(..., min_length=2, max_length=128)
    data_classification: Literal["synthetic_only"]
    access_mode: Literal["read_only"]


class StagingEvaluationIngestRequest(_StrictRequest):
    """The only accepted result is the aggregate-only v2 sanitized summary."""

    agent_id: str = Field(..., min_length=1, max_length=128)
    brand_id: str = Field(..., min_length=1, max_length=128)
    target_profile: TargetProfileRequest
    report: dict[str, Any]


class EvaluationReviewRequest(_StrictRequest):
    case_id: str = Field(..., min_length=1, max_length=96)
    reviewer_type: Literal["human", "pinned_model"]
    # For a human this field is ignored and a server-derived opaque reviewer
    # reference is stored. For a pinned model it identifies declared metadata;
    # no provider is invoked by this API.
    reviewer_ref: str | None = Field(default=None, min_length=2, max_length=128)
    dimensions: list[dict[str, str]] = Field(..., min_length=1, max_length=16)
    outcome: Literal["pass", "fail", "needs_adjudication"]
    redacted_rationale: str = Field(..., min_length=12, max_length=96)
    provenance: dict[str, str | None]


def _store(settings: Settings) -> QualityEvaluationStore:
    return QualityEvaluationStore(result_ttl_seconds=settings.EVAL_RESULT_TTL_SECONDS)


def _require_staging_enabled(settings: Settings) -> None:
    """Keep the entire surface dark until a deployer explicitly enables it."""
    if not settings.EVAL_STAGING_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staging evaluations are disabled")
    if not settings.evaluation_target_allowlist:
        # Settings validates this too. The runtime check protects callers using
        # partial/fake settings objects and never falls back to environment.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Staging evaluation target allowlist is not configured")


async def _brand_scope(
    brand_id: str,
    current_user: User | None,
    permission: Permission,
) -> dict[str, Any]:
    ensure_permission(current_user, permission)
    ensure_brand_access(current_user, brand_id)
    try:
        brand = await connection_manager.get_system_db().brands.find_one(
            {"id": brand_id},
            {"id": 1, "slug": 1},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Evaluation storage is temporarily unavailable") from exc
    if not isinstance(brand, dict) or not brand.get("id") or not brand.get("slug"):
        # A non-global caller gets this only after their membership has been
        # checked; nothing about another tenant's run is disclosed.
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


async def _authenticate_ingestion_key(
    *,
    authorization: str | None,
    x_api_key: str | None,
    x_agent_api_key: str | None,
) -> AgentApiKeyContext:
    raw_key = x_agent_api_key or x_api_key
    if not raw_key and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1].strip()
    return await AgentApiKeyService().authenticate(raw_key, required_scope="evaluations:write")


async def _resolve_ingestion_scope(
    request: StagingEvaluationIngestRequest,
    context: AgentApiKeyContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve ownership from the narrow key and server records, never body trust."""
    if not context.agent_id or not context.brand_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluation ingestion requires an agent- and brand-bound Agent API key",
        )
    if request.agent_id != context.agent_id or request.brand_id != context.brand_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Report ownership does not match the Agent API key")
    try:
        system_db = connection_manager.get_system_db()
        agent = await system_db.agents.find_one({"id": context.agent_id})
        brand = await system_db.brands.find_one({"id": context.brand_id}, {"id": 1, "slug": 1})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Evaluation ownership lookup is unavailable") from exc
    AgentApiKeyService().assert_agent_allowed(context, agent)
    if not agent or agent.get("brand_id") != context.brand_id:
        raise HTTPException(status_code=403, detail="Agent ownership does not match the Agent API key")
    if not isinstance(brand, dict) or not brand.get("slug"):
        raise HTTPException(status_code=404, detail="Brand not found")
    if agent.get("brand_slug") and agent.get("brand_slug") != brand.get("slug"):
        raise HTTPException(status_code=403, detail="Agent brand scope is invalid")
    return agent, brand


def _identity_reference(current_user: User | None) -> str:
    if current_user is None:
        # This is possible only for explicitly enabled local admin-key
        # compatibility mode. It is opaque rather than a key or credential.
        return "local-admin-key"
    return dashboard_reviewer_reference(current_user.id, current_user.email)


@router.post("/evaluations/runs", status_code=status.HTTP_201_CREATED)
async def ingest_staging_evaluation_run(
    request: StagingEvaluationIngestRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    x_agent_api_key: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Persist a signed-by-scope, synthetic-only staging summary.

    This endpoint intentionally performs no evaluation work and imports no
    provider/model adapter. A service has to generate the offline contract
    report elsewhere and hold the explicit ``evaluations:write`` key scope.
    """
    _require_staging_enabled(settings)
    context = await _authenticate_ingestion_key(
        authorization=authorization,
        x_api_key=x_api_key,
        x_agent_api_key=x_agent_api_key,
    )
    _, brand = await _resolve_ingestion_scope(request, context)
    try:
        target_profile = validate_target_profile(
            request.target_profile.model_dump(),
            allowed_profiles=settings.evaluation_target_allowlist,
        )
        report = validate_sanitized_report(request.report, max_cases=settings.EVAL_STAGING_MAX_CASES)
        run = await _store(settings).create_run(
            brand_id=brand["id"],
            brand_slug=brand["slug"],
            agent_id=context.agent_id,
            target_profile=target_profile,
            report=report,
            ingested_by_key_id=context.key_id,
        )
    except EvaluationPrivacyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualityEvaluationStoreError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evaluation result storage is unavailable") from exc
    return JSONResponse(jsonable_encoder({"run": run}), status_code=status.HTTP_201_CREATED, headers=NO_STORE_HEADERS)


@router.get("/brands/{brand_id}/evaluations/runs")
async def list_staging_evaluation_runs(
    brand_id: str,
    limit: int = Query(50, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
) -> JSONResponse:
    _require_staging_enabled(settings)
    brand = await _brand_scope(brand_id, current_user, Permission.EVALUATION_READ)
    try:
        runs = await _store(settings).list_runs(brand_id=brand_id, brand_slug=brand["slug"], limit=limit)
    except QualityEvaluationStoreError as exc:
        raise HTTPException(status_code=503, detail="Evaluation results are temporarily unavailable") from exc
    return JSONResponse(jsonable_encoder({"runs": runs}), headers=NO_STORE_HEADERS)


@router.get("/brands/{brand_id}/evaluations/runs/{run_id}")
async def get_staging_evaluation_run(
    brand_id: str,
    run_id: str,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
) -> JSONResponse:
    _require_staging_enabled(settings)
    brand = await _brand_scope(brand_id, current_user, Permission.EVALUATION_READ)
    try:
        run = await _store(settings).get_run(brand_id=brand_id, brand_slug=brand["slug"], run_id=run_id)
    except QualityEvaluationStoreError as exc:
        raise HTTPException(status_code=503, detail="Evaluation result is temporarily unavailable") from exc
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return JSONResponse(jsonable_encoder({"run": run}), headers=NO_STORE_HEADERS)


@router.post("/brands/{brand_id}/evaluations/runs/{run_id}/reviews")
async def submit_staging_evaluation_review(
    brand_id: str,
    run_id: str,
    request: EvaluationReviewRequest,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
) -> JSONResponse:
    """Store a redacted human decision or an optional pinned-model opinion.

    Human review remains primary: a pinned-model record can only be appended
    after a human review of that case. The endpoint stores declared metadata;
    it never calls a model or provider.
    """
    _require_staging_enabled(settings)
    brand = await _brand_scope(brand_id, current_user, Permission.EVALUATION_REVIEW)
    reviewer_ref = (
        _identity_reference(current_user)
        if request.reviewer_type == "human"
        else (request.reviewer_ref or "")
    )
    try:
        # ``reviewer_ref`` is transport metadata: humans receive a
        # server-derived opaque reference and pinned models may declare one.
        # It is intentionally not a client-controlled contract field.
        review = validate_review_submission(
            request.model_dump(exclude={"reviewer_ref"}),
            reviewer_ref=reviewer_ref,
        )
        store = _store(settings)
        if review["reviewer_type"] == "pinned_model":
            has_human = await store.has_human_review(
                brand_id=brand_id,
                brand_slug=brand["slug"],
                run_id=run_id,
                case_id=review["case_id"],
            )
            if not has_human:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A human review is required before a pinned-model second opinion",
                )
        run = await store.append_review(
            brand_id=brand_id,
            brand_slug=brand["slug"],
            run_id=run_id,
            review=review,
            submitted_by=_identity_reference(current_user),
        )
    except EvaluationPrivacyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except QualityEvaluationStoreError as exc:
        raise HTTPException(status_code=503, detail="Evaluation review storage is temporarily unavailable") from exc
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return JSONResponse(jsonable_encoder({"run": run}), headers=NO_STORE_HEADERS)
