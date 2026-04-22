from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.admin_key import require_admin_key
from app.dependencies import get_runtime_settings_service
from app.services.runtime_settings_service import (
    RuntimeSettingsService,
    RuntimeSettingsValidationError,
)

logger = structlog.get_logger()
router = APIRouter()


class RuntimeSettingOptionResponse(BaseModel):
    value: str
    label: str


class RuntimeSettingFieldResponse(BaseModel):
    key: str
    label: str
    description: str
    input_type: str
    secret: bool
    required: bool
    configured: bool
    source: str
    value: str | None = None
    masked_value: str | None = None
    updated_at: str | None = None
    options: list[RuntimeSettingOptionResponse] = Field(default_factory=list)


class RuntimeSettingSectionResponse(BaseModel):
    id: str
    title: str
    description: str
    supports_connection_test: bool = False
    fields: list[RuntimeSettingFieldResponse]


class RuntimeSettingsResponse(BaseModel):
    sections: list[RuntimeSettingSectionResponse]


class RuntimeSettingsUpdateRequest(BaseModel):
    updates: dict[str, str | None]


class RuntimeSettingsUpdateResponse(BaseModel):
    updated: list[dict[str, Any]]
    settings: RuntimeSettingsResponse


class RuntimeSettingsTestRequest(BaseModel):
    sections: list[str] | None = None
    overrides: dict[str, str | None] = Field(default_factory=dict)


class RuntimeSettingsTestResult(BaseModel):
    section: str
    status: str
    detail: str


class RuntimeSettingsTestResponse(BaseModel):
    status: str
    results: list[RuntimeSettingsTestResult]


@router.get(
    "/runtime",
    response_model=RuntimeSettingsResponse,
    dependencies=[Depends(require_admin_key)],
)
async def list_runtime_settings(
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        return await runtime_settings_service.list_settings_for_admin()
    except Exception as exc:
        logger.error("runtime_settings_list_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while loading runtime settings.",
        ) from exc


@router.put(
    "/runtime",
    response_model=RuntimeSettingsUpdateResponse,
    dependencies=[Depends(require_admin_key)],
)
async def update_runtime_settings(
    request: RuntimeSettingsUpdateRequest,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        return await runtime_settings_service.update_settings(request.updates)
    except RuntimeSettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("runtime_settings_update_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while updating runtime settings.",
        ) from exc


@router.post(
    "/runtime/test",
    response_model=RuntimeSettingsTestResponse,
    dependencies=[Depends(require_admin_key)],
)
async def test_runtime_settings(
    request: RuntimeSettingsTestRequest,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    try:
        return await runtime_settings_service.test_connections(
            sections=request.sections,
            overrides=request.overrides,
        )
    except RuntimeSettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("runtime_settings_test_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while testing runtime settings.",
        ) from exc
