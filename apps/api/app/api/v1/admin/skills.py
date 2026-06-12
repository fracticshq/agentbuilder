from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_dashboard_access
from app.services.skill_registry import BuiltInSkillRegistry


router = APIRouter(dependencies=[Depends(require_dashboard_access)])


@router.get("/")
async def list_built_in_skills():
    return {"skills": BuiltInSkillRegistry().list_skills()}


@router.get("/agent-config-shape")
async def get_skill_agent_config_shape():
    return BuiltInSkillRegistry().agent_config_shape()
