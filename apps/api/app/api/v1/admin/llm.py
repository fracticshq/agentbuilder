from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import structlog

from app.auth.dependencies import require_system_admin
from app.dependencies import get_settings
from app.services.azure_openai_deployment_service import (
    AzureDeploymentAuthError,
    AzureDeploymentConfigError,
    AzureDeploymentRequestError,
    AzureOpenAIDeploymentService,
)

logger = structlog.get_logger()
router = APIRouter()


class AzureDeployment(BaseModel):
    deployment_name: str
    model_name: str
    model_version: Optional[str] = None
    provisioning_state: str
    sku_name: Optional[str] = None


class AzureDeploymentListResponse(BaseModel):
    provider: str = "azure_openai"
    default_deployment: Optional[str] = None
    deployments: list[AzureDeployment]


@router.get(
    "/azure/deployments",
    response_model=AzureDeploymentListResponse,
    dependencies=[Depends(require_system_admin)],
)
async def list_azure_openai_deployments(settings=Depends(get_settings)):
    service = AzureOpenAIDeploymentService(settings)
    try:
        return await service.list_deployments()
    except AzureDeploymentConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AzureDeploymentAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AzureDeploymentRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("azure_deployments_unhandled_error", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while listing Azure OpenAI deployments.",
        ) from exc
