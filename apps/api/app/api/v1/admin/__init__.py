from fastapi import APIRouter
from .brands import router as brands_router
from .agents import router as agents_router
from .llm import router as llm_router
from .settings import router as settings_router
from .session import router as session_router
from .observability import router as observability_router
from .skills import router as skills_router
from .tools import router as tools_router
from .artifacts import router as artifacts_router
from .agent_api_keys import router as agent_api_keys_router
from .agent_manifests import router as agent_manifests_router
from .console import router as console_router
from .connectors import router as connectors_router
from .privacy import router as privacy_router
from .evaluations import router as evaluations_router

router = APIRouter()

router.include_router(brands_router, prefix="/brands", tags=["brands"])
router.include_router(connectors_router, prefix="/agents", tags=["agent-connectors"])
router.include_router(agents_router, prefix="/agents", tags=["agents"])
router.include_router(llm_router, prefix="/llm", tags=["llm"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(session_router, prefix="/session", tags=["session"])
router.include_router(observability_router, prefix="/observability", tags=["observability"])
router.include_router(skills_router, prefix="/skills", tags=["skills"])
router.include_router(tools_router, prefix="/tools", tags=["tools"])
router.include_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
router.include_router(agent_api_keys_router, prefix="/agent-api", tags=["agent-api-keys"])
router.include_router(agent_manifests_router, prefix="/agents", tags=["agent-manifests"])
router.include_router(console_router, prefix="/console", tags=["agent-console"])
router.include_router(privacy_router, tags=["privacy"])
router.include_router(evaluations_router, tags=["staging-evaluations"])
