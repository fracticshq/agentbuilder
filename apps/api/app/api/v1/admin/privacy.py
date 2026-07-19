"""Tenant-scoped operator APIs for privacy lifecycle administration."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import ensure_brand_access, ensure_permission, require_dashboard_access
from app.auth.models import Permission, User
from app.config import Settings
from app.connections import connection_manager
from app.dependencies import get_settings
from app.services.privacy_lifecycle_service import PrivacyLifecycleError, PrivacyLifecycleService

router = APIRouter(dependencies=[Depends(require_dashboard_access)])


class RetentionPolicyRequest(BaseModel):
    retention_days: int = Field(..., ge=1, le=3650)


async def _brand_scope(
    brand_id: str,
    current_user: User | None,
    permission: Permission,
) -> dict:
    ensure_permission(current_user, permission)
    ensure_brand_access(current_user, brand_id)
    try:
        brand = await connection_manager.get_system_db().brands.find_one(
            {"id": brand_id},
            {"id": 1, "slug": 1},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Privacy storage is temporarily unavailable") from exc
    if not isinstance(brand, dict) or not brand.get("slug"):
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


def _service(settings: Settings) -> PrivacyLifecycleService:
    return PrivacyLifecycleService(settings)


@router.get("/brands/{brand_id}/privacy/retention")
async def get_retention_policy(
    brand_id: str,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
):
    brand = await _brand_scope(brand_id, current_user, Permission.PRIVACY_READ)
    try:
        policy = await _service(settings).get_retention_policy(
            brand_id=brand_id,
            brand_slug=brand["slug"],
        )
    except PrivacyLifecycleError as exc:
        raise HTTPException(status_code=503, detail="Privacy policy is temporarily unavailable") from exc
    return JSONResponse(jsonable_encoder(policy), headers={"Cache-Control": "no-store"})


@router.put("/brands/{brand_id}/privacy/retention")
async def set_retention_policy(
    brand_id: str,
    request: RetentionPolicyRequest,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
):
    brand = await _brand_scope(brand_id, current_user, Permission.PRIVACY_WRITE)
    try:
        policy = await _service(settings).set_retention_policy(
            brand_id=brand_id,
            brand_slug=brand["slug"],
            retention_days=request.retention_days,
            updated_by=getattr(current_user, "id", None),
        )
    except (PrivacyLifecycleError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Privacy policy could not be updated") from exc
    return JSONResponse(jsonable_encoder(policy), headers={"Cache-Control": "no-store"})


@router.post("/brands/{brand_id}/privacy/retention/run")
async def run_retention_cleanup(
    brand_id: str,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
):
    brand = await _brand_scope(brand_id, current_user, Permission.PRIVACY_WRITE)
    try:
        result = await _service(settings).apply_retention_policy(
            brand_id=brand_id,
            brand_slug=brand["slug"],
        )
    except PrivacyLifecycleError as exc:
        raise HTTPException(status_code=503, detail="Retention cleanup could not be completed") from exc
    return JSONResponse(jsonable_encoder(result), headers={"Cache-Control": "no-store"})


@router.get("/brands/{brand_id}/privacy/subjects/{subject_id}/export")
async def export_subject_data(
    brand_id: str,
    subject_id: str,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
):
    brand = await _brand_scope(brand_id, current_user, Permission.PRIVACY_READ)
    try:
        payload = await _service(settings).export_subject(
            brand_id=brand_id,
            brand_slug=brand["slug"],
            subject_id=subject_id,
        )
    except PrivacyLifecycleError as exc:
        raise HTTPException(status_code=503, detail="Privacy export is temporarily unavailable") from exc
    return JSONResponse(jsonable_encoder(payload), headers={"Cache-Control": "no-store"})


@router.delete("/brands/{brand_id}/privacy/subjects/{subject_id}")
async def delete_subject_data(
    brand_id: str,
    subject_id: str,
    settings: Settings = Depends(get_settings),
    current_user: User | None = Depends(require_dashboard_access),
):
    brand = await _brand_scope(brand_id, current_user, Permission.PRIVACY_DELETE)
    try:
        receipt = await _service(settings).delete_subject(
            brand_id=brand_id,
            brand_slug=brand["slug"],
            subject_id=subject_id,
            requested_by=getattr(current_user, "id", None),
        )
    except PrivacyLifecycleError as exc:
        raise HTTPException(status_code=503, detail="Privacy deletion is temporarily unavailable") from exc
    return JSONResponse(
        jsonable_encoder(receipt),
        status_code=202 if receipt["status"] == "pending" else 200,
        headers={"Cache-Control": "no-store"},
    )
