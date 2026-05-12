"""
Catalog API endpoints — multi-source product import + sync config.

Routes:
  POST /catalog/import/shopify
  POST /catalog/import/json-feed
  POST /catalog/import/csv
  POST /catalog/import/scrape
  GET  /catalog/jobs/{job_id}
  GET  /catalog/sync-config/{brand_id}
  PUT  /catalog/sync-config/{brand_id}
  POST /catalog/sync/{brand_id}
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import List, Optional, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
import structlog

from app.auth.dependencies import require_dashboard_access
from app.connections import connection_manager
from app.dependencies import (
    get_knowledge_service,
    get_runtime_settings_service,
    get_settings,
)
from app.services import catalog_service
from app.services.runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(require_dashboard_access)])


def _firecrawl_key() -> str:
    return os.getenv("FIRECRAWL_API_KEY", "")


def _encrypt_sync_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    return runtime_settings_service._encrypt(value.strip())


def _decrypt_sync_secret(runtime_settings_service: RuntimeSettingsService, value: str | None) -> str:
    if not value:
        return ""
    try:
        return runtime_settings_service._decrypt(value)
    except Exception as exc:
        logger.warning("catalog_sync_secret_decrypt_failed", error=str(exc))
        return ""


def _protect_sync_config_secrets(
    patch: dict,
    *,
    existing: dict | None = None,
    runtime_settings_service: RuntimeSettingsService,
) -> dict:
    protected = dict(patch or {})
    existing = dict(existing or {})
    
    # Handle Client ID
    client_id = protected.pop("client_id", None)
    if isinstance(client_id, str) and client_id.strip():
        protected["client_id_encrypted"] = _encrypt_sync_secret(runtime_settings_service, client_id)
    elif existing.get("client_id_encrypted"):
        protected["client_id_encrypted"] = existing["client_id_encrypted"]

    # Handle Client Secret
    client_secret = protected.pop("client_secret", None)
    if isinstance(client_secret, str) and client_secret.strip():
        protected["client_secret_encrypted"] = _encrypt_sync_secret(runtime_settings_service, client_secret)
    elif existing.get("client_secret_encrypted"):
        protected["client_secret_encrypted"] = existing["client_secret_encrypted"]

    return protected


def _expose_sync_config_for_admin(config: dict) -> dict:
    safe = dict(config or {})
    configured = bool(
        (safe.get("client_id_encrypted") or safe.get("client_id")) and 
        (safe.get("client_secret_encrypted") or safe.get("client_secret"))
    )
    safe.pop("client_id", None)
    safe.pop("client_id_encrypted", None)
    safe.pop("client_secret", None)
    safe.pop("client_secret_encrypted", None)
    safe["access_token_configured"] = configured
    return safe


def _decrypt_sync_config_for_runtime(
    config: dict,
    runtime_settings_service: RuntimeSettingsService,
) -> dict:
    runtime_config = dict(config or {})
    if runtime_config.get("client_id_encrypted") and not runtime_config.get("client_id"):
        runtime_config["client_id"] = _decrypt_sync_secret(
            runtime_settings_service,
            runtime_config.get("client_id_encrypted"),
        )
    if runtime_config.get("client_secret_encrypted") and not runtime_config.get("client_secret"):
        runtime_config["client_secret"] = _decrypt_sync_secret(
            runtime_settings_service,
            runtime_config.get("client_secret_encrypted"),
        )
    return runtime_config


# ── Request models ────────────────────────────────────────────────────────────

class ShopifyImportRequest(BaseModel):
    store_url: str
    brand_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class JsonFeedRequest(BaseModel):
    url: str
    brand_id: str


class ScrapeRequest(BaseModel):
    urls: List[str]
    brand_id: str


class SyncConfigUpdate(BaseModel):
    source_type: str
    source_url: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    auto_sync: bool = False
    sync_frequency: str = "manual"  # daily | weekly | manual


# ── Import: Shopify ───────────────────────────────────────────────────────────

@router.post("/import/shopify")
async def import_shopify(
    req: ShopifyImportRequest,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    knowledge_service: Any = Depends(get_knowledge_service),
    settings: Any = Depends(get_settings),
):
    """Start async Shopify product fetch. Paginates /products.json. Returns job_id."""
    job_id = str(uuid.uuid4())
    await catalog_service.create_job(job_id, "shopify", total=0)

    background_tasks.add_task(
        catalog_service.fetch_shopify_products,
        req.store_url,
        job_id,
        brand_id=req.brand_id,
        knowledge_service=knowledge_service,
        client_id=req.client_id,
        client_secret=req.client_secret,
        settings=settings,
    )

    # Persist sync config for this brand so resync works later
    sync_patch = {
        "source_type": "shopify",
        "source_url": req.store_url,
    }
    if req.client_id:
        sync_patch["client_id"] = req.client_id
    if req.client_secret:
        sync_patch["client_secret"] = req.client_secret

    await _upsert_sync_config(
        req.brand_id,
        sync_patch,
        runtime_settings_service=runtime_settings_service,
    )

    return {"job_id": job_id, "status": "processing"}


# ── Import: JSON feed ─────────────────────────────────────────────────────────

@router.post("/import/json-feed")
async def import_json_feed(req: JsonFeedRequest):
    """Fetch a JSON feed URL and auto-detect its format. Synchronous."""
    try:
        result = await catalog_service.fetch_json_feed(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")

    await _upsert_sync_config(req.brand_id, {
        "source_type": "json_feed",
        "source_url": req.url,
    })
    return result  # { items, detected_format, raw_count }


# ── Import: CSV ───────────────────────────────────────────────────────────────

@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    brand_id: str = Form(...),
):
    """Parse an uploaded CSV file and return rows as JSON. Synchronous."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    try:
        items = catalog_service.parse_csv(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"items": items, "detected_format": "csv", "raw_count": len(items)}


# ── Import: Firecrawl scrape ──────────────────────────────────────────────────

@router.post("/import/scrape")
async def import_scrape(
    req: ScrapeRequest,
    background_tasks: BackgroundTasks,
    settings: Any = Depends(get_settings),
):
    """Start async Firecrawl-based product extraction. Returns job_id."""
    if not settings.USE_FIRECRAWL:
        raise HTTPException(
            status_code=400,
            detail="Firecrawl scraping is currently disabled in system settings.",
        )

    api_key = _firecrawl_key()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="FIRECRAWL_API_KEY is not configured in your .env file.",
        )
    if not req.urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")
    if len(req.urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per request.")

    job_id = str(uuid.uuid4())
    await catalog_service.create_job(job_id, "scrape", total=len(req.urls))

    background_tasks.add_task(
        catalog_service.run_firecrawl_scrape,
        req.urls,
        job_id,
        api_key,
    )
    return {"job_id": job_id, "status": "processing"}


# ── Job status ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await catalog_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# ── Sync config ───────────────────────────────────────────────────────────────

@router.get("/sync-config/{brand_id}")
async def get_sync_config(brand_id: str):
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")
    config = dict(brand.get("catalog_sync") or {})
    return _expose_sync_config_for_admin(config)


@router.put("/sync-config/{brand_id}")
async def update_sync_config(
    brand_id: str,
    update: SyncConfigUpdate,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
):
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    existing = dict(brand.get("catalog_sync") or {})
    patch = _protect_sync_config_secrets(
        {
            **existing,
            "source_type": update.source_type,
            "source_url": update.source_url,
            "auto_sync": update.auto_sync,
            "sync_frequency": update.sync_frequency,
            "updated_at": datetime.utcnow().isoformat(),
        },
        existing=existing,
        runtime_settings_service=runtime_settings_service,
    )
    if update.client_id:
        patch = _protect_sync_config_secrets(
            {**patch, "client_id": update.client_id},
            existing=existing,
            runtime_settings_service=runtime_settings_service,
        )
    if update.client_secret:
        patch = _protect_sync_config_secrets(
            {**patch, "client_secret": update.client_secret},
            existing=existing,
            runtime_settings_service=runtime_settings_service,
        )

    await db.brands.update_one({"id": brand_id}, {"$set": {"catalog_sync": patch}})
    return _expose_sync_config_for_admin(patch)


@router.post("/sync/{brand_id}")
async def manual_sync(
    brand_id: str,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    knowledge_service: Any = Depends(get_knowledge_service),
    settings: Any = Depends(get_settings),
):
    """Trigger an immediate resync from the brand's stored sync config."""
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    config = _decrypt_sync_config_for_runtime(
        brand.get("catalog_sync") or {},
        runtime_settings_service,
    )
    if not config:
        raise HTTPException(status_code=400, detail="No sync config saved for this brand.")

    source_type = config.get("source_type")

    # Update last_synced_at
    await db.brands.update_one(
        {"id": brand_id},
        {"$set": {"catalog_sync.last_synced_at": datetime.utcnow().isoformat()}},
    )

    if source_type == "shopify":
        job_id = str(uuid.uuid4())
        await catalog_service.create_job(job_id, "shopify")
        background_tasks.add_task(
            catalog_service.fetch_shopify_products,
            config["source_url"],
            job_id,
            brand_id=brand_id,
            knowledge_service=knowledge_service,
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            settings=settings,
        )
        return {"job_id": job_id, "status": "processing"}

    if source_type == "json_feed":
        try:
            result = await catalog_service.fetch_json_feed(config["source_url"])
            return {"status": "completed", **result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    raise HTTPException(
        status_code=400,
        detail=f"Auto-sync not supported for source type '{source_type}'. Re-import manually.",
    )


# ── Internal helper ───────────────────────────────────────────────────────────

async def _upsert_sync_config(
    brand_id: str,
    patch: dict,
    *,
    runtime_settings_service: RuntimeSettingsService | None = None,
) -> None:
    try:
        db = connection_manager.get_system_db()
        brand = await db.brands.find_one({"id": brand_id})
        if brand:
            existing = dict(brand.get("catalog_sync") or {})
            merged = {**existing, **patch}
            if merged.get("source_type") != "shopify":
                merged.pop("client_id", None)
                merged.pop("client_id_encrypted", None)
                merged.pop("client_secret", None)
                merged.pop("client_secret_encrypted", None)
            if runtime_settings_service:
                merged = _protect_sync_config_secrets(
                    merged,
                    existing=existing,
                    runtime_settings_service=runtime_settings_service,
                )
            await db.brands.update_one(
                {"id": brand_id},
                {"$set": {"catalog_sync": merged}},
            )
    except Exception as exc:
        logger.warning("sync_config_save_failed", brand_id=brand_id, error=str(exc))
