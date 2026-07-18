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
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
import structlog

from app.auth.dependencies import ensure_brand_access, get_user_from_token_or_api_key
from app.auth.models import User, UserRole
from app.connections import connection_manager
from app.dependencies import get_runtime_settings_service
from app.services import catalog_service
from app.services.runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()
router = APIRouter()


CATALOG_MANAGE_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.BRAND_ADMIN,
}


async def _require_catalog_brand_access(brand_id: str, user: User) -> User:
    """Require a catalog-managing role and canonical brand scope."""
    if user.role not in CATALOG_MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="Catalog administration access is required")
    # Global roles intentionally have all-tenant scope; tenant roles receive a
    # not-found response for a foreign brand so resource existence is not leaked.
    ensure_brand_access(user, brand_id)
    return user


async def _require_catalog_path_brand_access(
    brand_id: str,
    user: User = Depends(get_user_from_token_or_api_key),
) -> User:
    return await _require_catalog_brand_access(brand_id, user)


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
    access_token = protected.pop("access_token", None)

    if isinstance(access_token, str) and access_token.strip():
        protected["access_token_encrypted"] = _encrypt_sync_secret(runtime_settings_service, access_token)
    elif existing.get("access_token_encrypted"):
        protected["access_token_encrypted"] = existing["access_token_encrypted"]
    elif existing.get("access_token"):
        protected["access_token_encrypted"] = _encrypt_sync_secret(runtime_settings_service, existing["access_token"])

    return protected


def _expose_sync_config_for_admin(config: dict) -> dict:
    safe = dict(config or {})
    configured = bool(safe.get("access_token_encrypted") or safe.get("access_token"))
    safe.pop("access_token", None)
    safe.pop("access_token_encrypted", None)
    safe["access_token_configured"] = configured
    return safe


def _decrypt_sync_config_for_runtime(
    config: dict,
    runtime_settings_service: RuntimeSettingsService,
) -> dict:
    runtime_config = dict(config or {})
    if runtime_config.get("access_token_encrypted") and not runtime_config.get("access_token"):
        runtime_config["access_token"] = _decrypt_sync_secret(
            runtime_settings_service,
            runtime_config.get("access_token_encrypted"),
        )
    return runtime_config


# ── Request models ────────────────────────────────────────────────────────────

class ShopifyImportRequest(BaseModel):
    store_url: str
    brand_id: str
    access_token: Optional[str] = None
    fallback_currency: Optional[str] = None


class JsonFeedRequest(BaseModel):
    url: str
    brand_id: str


class ScrapeRequest(BaseModel):
    urls: List[str]
    brand_id: str


class SyncConfigUpdate(BaseModel):
    source_type: str
    source_url: str
    access_token: Optional[str] = None
    fallback_currency: Optional[str] = None
    auto_sync: bool = False
    sync_frequency: str = "manual"  # daily | weekly | manual


# ── Import: Shopify ───────────────────────────────────────────────────────────

@router.post("/import/shopify")
async def import_shopify(
    req: ShopifyImportRequest,
    background_tasks: BackgroundTasks,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Start async Shopify product fetch. Paginates /products.json. Returns job_id."""
    try:
        await _require_catalog_brand_access(req.brand_id, user)
        store_url = catalog_service.normalize_shopify_store_url(req.store_url)
        if req.access_token and req.access_token.strip():
            store_url = catalog_service.normalize_authenticated_shopify_store_url(store_url)
        fallback_currency = catalog_service.normalize_currency_code(req.fallback_currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Save the encrypted configuration before scheduling the worker so a
    # dashboard refresh can always recover the job's source settings.
    await _upsert_sync_config(
        req.brand_id,
        {
            "source_type": "shopify",
            "source_url": store_url,
            **({"access_token": req.access_token} if req.access_token else {}),
            **({"fallback_currency": fallback_currency} if fallback_currency else {}),
        },
        runtime_settings_service=runtime_settings_service,
    )

    job_id = str(uuid.uuid4())
    await catalog_service.create_job(job_id, "shopify", total=0)

    background_tasks.add_task(
        catalog_service.fetch_shopify_products,
        store_url,
        req.access_token,
        job_id,
        req.brand_id,
        fallback_currency,
    )

    return {
        "job_id": job_id,
        "status": "processing",
        "source_url": store_url,
        "warning": None if req.access_token else "Public Shopify import: use an Admin API token for production sync.",
    }


# ── Import: JSON feed ─────────────────────────────────────────────────────────

@router.post("/import/json-feed")
async def import_json_feed(
    req: JsonFeedRequest,
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Fetch a JSON feed URL and auto-detect its format. Synchronous."""
    try:
        await _require_catalog_brand_access(req.brand_id, user)
        feed_url = await catalog_service.validate_json_feed_url(req.url)
        fallback_currency = await catalog_service._resolve_configured_default_currency(req.brand_id)
        result = await catalog_service.fetch_json_feed(feed_url, fallback_currency=fallback_currency)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")

    await _upsert_sync_config(req.brand_id, {
        "source_type": "json_feed",
        "source_url": feed_url,
    })
    return result  # { items, detected_format, raw_count }


# ── Import: CSV ───────────────────────────────────────────────────────────────

@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    brand_id: str = Form(...),
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Parse an uploaded CSV file and return rows as JSON. Synchronous."""
    await _require_catalog_brand_access(brand_id, user)
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
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Start async Firecrawl-based product extraction. Returns job_id."""
    await _require_catalog_brand_access(req.brand_id, user)
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
    fallback_currency = await catalog_service._resolve_configured_default_currency(req.brand_id)

    background_tasks.add_task(
        catalog_service.run_firecrawl_scrape,
        req.urls,
        job_id,
        api_key,
        fallback_currency=fallback_currency,
    )
    return {"job_id": job_id, "status": "processing"}


# ── Job status ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    brand_id: Optional[str] = None,
    user: User = Depends(get_user_from_token_or_api_key),
):
    job = await catalog_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job_brand_id = job.get("brand_id")
    if not job_brand_id or (brand_id and job_brand_id != brand_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    await _require_catalog_brand_access(str(job_brand_id), user)
    return job


# ── Sync config ───────────────────────────────────────────────────────────────

@router.get("/sync-config/{brand_id}")
async def get_sync_config(
    brand_id: str,
    _: User = Depends(_require_catalog_path_brand_access),
):
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
    _: User = Depends(_require_catalog_path_brand_access),
):
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    existing = dict(brand.get("catalog_sync") or {})
    try:
        if update.source_type == "shopify":
            source_url = catalog_service.normalize_shopify_store_url(update.source_url)
            has_saved_access_token = bool(existing.get("access_token_encrypted") or existing.get("access_token"))
            if (update.access_token and update.access_token.strip()) or has_saved_access_token:
                source_url = catalog_service.normalize_authenticated_shopify_store_url(source_url)
        elif update.source_type == "json_feed":
            source_url = await catalog_service.validate_json_feed_url(update.source_url)
        else:
            source_url = update.source_url.strip()
        fields_set = getattr(update, "model_fields_set", getattr(update, "__fields_set__", set()))
        fallback_currency = None
        if "fallback_currency" in fields_set:
            fallback_currency = catalog_service.normalize_currency_code(update.fallback_currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sync_patch = {
        **existing,
        "source_type": update.source_type,
        "source_url": source_url,
        "auto_sync": update.auto_sync,
        "sync_frequency": update.sync_frequency,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if "fallback_currency" in fields_set:
        sync_patch["fallback_currency"] = fallback_currency
    patch = _protect_sync_config_secrets(
        sync_patch,
        existing=existing,
        runtime_settings_service=runtime_settings_service,
    )
    if update.access_token:
        patch = _protect_sync_config_secrets(
            {**patch, "access_token": update.access_token},
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
    _: User = Depends(_require_catalog_path_brand_access),
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

    if source_type == "shopify":
        try:
            source_url = catalog_service.normalize_shopify_store_url(config.get("source_url"))
            if config.get("access_token") and str(config.get("access_token")).strip():
                source_url = catalog_service.normalize_authenticated_shopify_store_url(source_url)
            fallback_currency = catalog_service.normalize_currency_code(config.get("fallback_currency"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job_id = str(uuid.uuid4())
        await catalog_service.create_job(job_id, "shopify")
        background_tasks.add_task(
            catalog_service.fetch_shopify_products,
            source_url,
            config.get("access_token"),
            job_id,
            brand_id,
            fallback_currency,
        )
        return {
            "job_id": job_id,
            "status": "processing",
            "source_url": source_url,
            "warning": None if config.get("access_token") else "Public Shopify import: use an Admin API token for production sync.",
        }

    if source_type == "json_feed":
        try:
            fallback_currency = await catalog_service._resolve_configured_default_currency(brand_id)
            result = await catalog_service.fetch_json_feed(config["source_url"], fallback_currency=fallback_currency)
            completed_at = datetime.utcnow().isoformat()
            await db.brands.update_one(
                {"id": brand_id},
                {"$set": {
                    "catalog_sync.last_sync_status": "completed",
                    "catalog_sync.last_sync_completed_at": completed_at,
                    "catalog_sync.last_synced_at": completed_at,
                    "catalog_sync.last_sync_error": None,
                }},
            )
            return {"status": "completed", **result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
                merged.pop("access_token", None)
                merged.pop("access_token_encrypted", None)
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
