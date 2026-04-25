import structlog
from typing import Any

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

logger = structlog.get_logger(__name__)


class StrapiProvisioningService:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self._enabled = bool(base_url and api_token and _HTTPX_AVAILABLE)
        self._headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _build_payload(self, brand_doc: dict[str, Any], agent_doc: dict[str, Any]) -> dict[str, Any]:
        return {
            'brand': {
                'id': brand_doc.get('id'),
                'slug': brand_doc.get('slug'),
                'name': brand_doc.get('name'),
            },
            'agent': {
                'id': agent_doc.get('id'),
                'name': agent_doc.get('name'),
                'slug': agent_doc.get('slug'),
                'status': agent_doc.get('status'),
            },
        }

    async def provision_agent_dashboard(self, brand_doc: dict, agent_doc: dict) -> None:
        if not self._enabled:
            return

        payload = self._build_payload(brand_doc, agent_doc)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f'{self.base_url}/api/admin/provision-agent',
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            logger.info('strapi_agent_provisioned', agent_id=agent_doc.get('id'), brand_slug=brand_doc.get('slug'))

    async def provision_agent_dashboard_best_effort(self, brand_doc: dict, agent_doc: dict) -> bool:
        if not self._enabled:
            logger.info(
                'strapi_agent_provisioning_skipped',
                reason='disabled',
                agent_id=agent_doc.get('id'),
                brand_slug=brand_doc.get('slug'),
            )
            return False

        try:
            await self.provision_agent_dashboard(brand_doc, agent_doc)
            return True
        except Exception as exc:
            logger.warning(
                'strapi_agent_provisioning_failed',
                error=str(exc),
                agent_id=agent_doc.get('id'),
                brand_slug=brand_doc.get('slug'),
                status=agent_doc.get('status'),
            )
            return False
