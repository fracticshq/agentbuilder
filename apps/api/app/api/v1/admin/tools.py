from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_dashboard_access
from app.services.tool_registry import ToolRegistryService


router = APIRouter(dependencies=[Depends(require_dashboard_access)])


@router.get("/")
async def list_tools():
    return {"tools": ToolRegistryService().list_tools()}


@router.get("/agent-config-shape")
async def get_tool_agent_config_shape():
    return ToolRegistryService().agent_config_shape()
