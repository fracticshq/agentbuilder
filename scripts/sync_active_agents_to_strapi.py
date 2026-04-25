import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / 'apps' / 'api'
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.config import Settings
from app.connections import connection_manager
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.strapi_provisioning_service import StrapiProvisioningService


async def main():
    settings = Settings()

    await connection_manager.connect_mongodb()
    try:
        runtime_settings = RuntimeSettingsService(settings)
        strapi_config = await runtime_settings.get_strapi_runtime_config()
        provisioning = StrapiProvisioningService(
            strapi_config.get("base_url", ""),
            strapi_config.get("api_token", ""),
        )

        system_db = connection_manager.get_system_db()
        agents = await system_db.agents.find({"status": "active"}).to_list(length=None)
        synced = 0
        skipped = 0
        for agent in agents:
            brand = await system_db.brands.find_one({"id": agent.get("brand_id")})
            if not brand:
                skipped += 1
                continue
            success = await provisioning.provision_agent_dashboard_best_effort(brand, agent)
            if success:
                synced += 1
            else:
                skipped += 1
        print({"synced_active_agents": synced, "skipped_active_agents": skipped})
    finally:
        await connection_manager.close_all()


if __name__ == '__main__':
    asyncio.run(main())
