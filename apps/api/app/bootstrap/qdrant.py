from __future__ import annotations

from app.bootstrap.database import BootstrapCheck
from app.config import Settings
from app.services.qdrant_vector_service import QdrantVectorService


async def ensure_qdrant_collections(settings: Settings, brand_db_names: list[str]) -> list[BootstrapCheck]:
    service = QdrantVectorService(settings)
    checks: list[BootstrapCheck] = []
    try:
        for db_name in brand_db_names:
            collection = await service.ensure_collection(db_name)
            checks.append(BootstrapCheck(name=f"qdrant.{collection}", status="ok", detail="collection ready"))
    except Exception as exc:
        checks.append(BootstrapCheck(name="qdrant", status="error", detail=str(exc)))
    finally:
        await service.close()
    return checks
