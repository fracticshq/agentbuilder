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

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, model_validator
import structlog

from app.auth.dependencies import ensure_brand_access, get_user_from_token_or_api_key
from app.auth.models import User, UserRole
from app.connections import connection_manager
from app.config import Settings
from app.dependencies import get_catalog_sync_store, get_runtime_settings_service, get_settings
from app.services import catalog_service
from app.services.catalog_sync_store import CatalogSyncStore, CatalogSyncStoreUnavailableError
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


async def _authorized_catalog_brand_id(brand_id: str, user: User) -> str:
    """Resolve a request alias and authorize the canonical catalog owner scope."""
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({
        "$or": [
            {"id": brand_id},
            {"slug": brand_id},
        ]
    })
    canonical_brand_id = str(brand.get("id") or brand_id) if brand else brand_id
    await _require_catalog_brand_access(canonical_brand_id, user)
    return canonical_brand_id


def _catalog_job_for_response(job: dict) -> dict:
    """Keep job response shape while withholding provider/network exception text."""
    safe_job = dict(job)
    for field in (
        "_id",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "access_token",
        "access_token_encrypted",
        "error_type",
    ):
        safe_job.pop(field, None)
    if safe_job.get("error"):
        safe_job["error"] = "Catalog import failed. Review server logs for details."

    if isinstance(safe_job.get("results"), list):
        safe_results = []
        for result in safe_job["results"]:
            if not isinstance(result, dict):
                safe_results.append(result)
                continue
            safe_result = dict(result)
            if safe_result.get("error"):
                safe_result["error"] = "Catalog item import failed. Review server logs for details."
            safe_results.append(safe_result)
        safe_job["results"] = safe_results
    return safe_job


async def _load_catalog_brand_scope(brand_identifier: str, user: User) -> tuple[str, dict]:
    """Resolve a brand alias once and return its immutable catalog scope."""
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"$or": [{"id": brand_identifier}, {"slug": brand_identifier}]})
    if not brand:
        # Keep foreign/nonexistent resources indistinguishable for tenant roles.
        await _require_catalog_brand_access(brand_identifier, user)
        raise HTTPException(status_code=404, detail="Brand not found.")
    canonical_brand_id = str(brand.get("id") or brand_identifier)
    await _require_catalog_brand_access(canonical_brand_id, user)
    return canonical_brand_id, brand


def _shopify_domain(source_url: str) -> str:
    """Use the canonical .myshopify.com host as the webhook-to-brand key."""
    return catalog_service.normalize_authenticated_shopify_store_url(source_url).removeprefix("https://")


async def _ensure_shopify_store_available(
    *,
    brand_id: str,
    source_url: str,
) -> None:
    """Prevent one Shopify shop from being attached to two platform tenants."""
    db = connection_manager.get_system_db()
    domain = _shopify_domain(source_url)
    other = await db.brands.find_one(
        {
            "id": {"$ne": brand_id},
            "catalog_sync.source_type": "shopify",
            "$or": [
                {"catalog_sync.shop_domain": domain},
                {"catalog_sync.source_url": source_url},
            ],
        }
    )
    if other:
        raise HTTPException(status_code=409, detail="This Shopify shop is already connected to another brand.")


async def _enqueue_shopify_sync(
    *,
    catalog_sync_store: CatalogSyncStore,
    brand_id: str,
    brand: dict,
    source_url: str,
    access_token_encrypted: str | None,
    fallback_currency: str | None,
    trigger: str,
    idempotency_key: str | None = None,
    webhook_topic: str | None = None,
    webhook_id: str | None = None,
) -> tuple[dict, bool]:
    job, deduplicated = await catalog_sync_store.enqueue_sync(
        job_id=str(uuid.uuid4()),
        brand_id=brand_id,
        brand_slug=str(brand.get("slug") or brand_id),
        source_url=source_url,
        access_token_encrypted=access_token_encrypted,
        fallback_currency=fallback_currency,
        trigger=trigger,
        idempotency_key=idempotency_key,
        webhook_topic=webhook_topic,
        webhook_id=webhook_id,
    )
    if not deduplicated:
        # Retain the legacy progress row for existing admin clients while the
        # lease, retry and idempotency state remains in CatalogSyncStore.
        try:
            await catalog_service.create_job(str(job["job_id"]), "shopify", brand_id=brand_id, total=0)
        except Exception:
            # Do not leave a queue row claimable when the compatibility progress
            # record could not be persisted. The caller receives a retryable
            # failure and no worker starts a partial sync.
            await catalog_sync_store.cancel_queued(str(job["job_id"]), reason="catalog_progress_store_unavailable")
            raise
    return job, deduplicated


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
        logger.warning("catalog_sync_secret_decrypt_failed", error_type=type(exc).__name__)
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
    sync_frequency: Literal["daily", "weekly", "manual"] = "manual"

    @model_validator(mode="after")
    def validate_auto_sync_frequency(self):
        if self.auto_sync and self.sync_frequency == "manual":
            raise ValueError("Auto-sync requires a daily or weekly frequency.")
        return self


# ── Import: Shopify ───────────────────────────────────────────────────────────

@router.post("/import/shopify")
async def import_shopify(
    req: ShopifyImportRequest,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    catalog_sync_store: CatalogSyncStore = Depends(get_catalog_sync_store),
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Queue a restart-safe Shopify catalog snapshot for one brand."""
    try:
        brand_id, brand = await _load_catalog_brand_scope(req.brand_id, user)
        existing_config = dict(brand.get("catalog_sync") or {})
        existing_token = str(existing_config.get("access_token") or "").strip()
        existing_encrypted_token = str(existing_config.get("access_token_encrypted") or "").strip()
        supplied_token = str(req.access_token or "").strip()
        if not supplied_token and not existing_token and not existing_encrypted_token:
            raise ValueError("A Shopify Admin API access token is required for a production catalog sync.")
        store_url = catalog_service.normalize_authenticated_shopify_store_url(req.store_url)
        await _ensure_shopify_store_available(brand_id=brand_id, source_url=store_url)
        fallback_currency = catalog_service.normalize_currency_code(req.fallback_currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    encrypted_access_token = (
        _encrypt_sync_secret(runtime_settings_service, supplied_token)
        if supplied_token
        else existing_encrypted_token or _encrypt_sync_secret(runtime_settings_service, existing_token)
    )
    # Save the encrypted configuration before queuing the job so a dashboard
    # refresh can recover its scope, but keep the queue's credential snapshot
    # encrypted and independent of later dashboard edits.
    try:
        await _upsert_sync_config(
            brand_id,
            {
                "source_type": "shopify",
                "source_url": store_url,
                "shop_domain": _shopify_domain(store_url),
                "enabled": True,
                **({"access_token": supplied_token} if supplied_token else {}),
                **({"fallback_currency": fallback_currency} if fallback_currency else {}),
            },
            runtime_settings_service=runtime_settings_service,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Catalog configuration storage is unavailable.") from exc

    try:
        job, deduplicated = await _enqueue_shopify_sync(
            catalog_sync_store=catalog_sync_store,
            brand_id=brand_id,
            brand=brand,
            source_url=store_url,
            access_token_encrypted=encrypted_access_token,
            fallback_currency=fallback_currency,
            trigger="admin_import",
        )
    except CatalogSyncStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Catalog sync queue is unavailable.") from exc

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "source_url": store_url,
        "deduplicated": deduplicated,
    }


# ── Import: JSON feed ─────────────────────────────────────────────────────────

@router.post("/import/json-feed")
async def import_json_feed(
    req: JsonFeedRequest,
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Fetch a JSON feed URL and auto-detect its format. Synchronous."""
    try:
        brand_id = await _authorized_catalog_brand_id(req.brand_id, user)
        feed_url = await catalog_service.validate_json_feed_url(req.url)
        fallback_currency = await catalog_service._resolve_configured_default_currency(brand_id)
        result = await catalog_service.fetch_json_feed(feed_url, fallback_currency=fallback_currency)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("catalog_json_feed_fetch_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Catalog feed fetch failed.") from None

    try:
        await _upsert_sync_config(brand_id, {
            "source_type": "json_feed",
            "source_url": feed_url,
        })
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Catalog configuration storage is unavailable.") from exc
    return result  # { items, detected_format, raw_count }


# ── Import: CSV ───────────────────────────────────────────────────────────────

@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    brand_id: str = Form(...),
    user: User = Depends(get_user_from_token_or_api_key),
):
    """Parse an uploaded CSV file and return rows as JSON. Synchronous."""
    await _authorized_catalog_brand_id(brand_id, user)
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
    brand_id = await _authorized_catalog_brand_id(req.brand_id, user)
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
    await catalog_service.create_job(job_id, "scrape", brand_id=brand_id, total=len(req.urls))
    fallback_currency = await catalog_service._resolve_configured_default_currency(brand_id)

    background_tasks.add_task(
        catalog_service.run_firecrawl_scrape,
        req.urls,
        job_id,
        api_key,
        brand_id,
        fallback_currency=fallback_currency,
    )
    return {"job_id": job_id, "status": "processing"}


# ── Job status ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    brand_id: Optional[str] = None,
    catalog_sync_store: CatalogSyncStore = Depends(get_catalog_sync_store),
    user: User = Depends(get_user_from_token_or_api_key),
):
    try:
        job = await catalog_sync_store.get(job_id)
    except CatalogSyncStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Catalog sync queue is unavailable.") from exc
    if job is None:
        job = await catalog_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job_brand_id = job.get("brand_id")
    if not job_brand_id:
        raise HTTPException(status_code=404, detail="Job not found.")
    if brand_id:
        requested_brand_id = await _authorized_catalog_brand_id(brand_id, user)
        if str(job_brand_id) != requested_brand_id:
            raise HTTPException(status_code=404, detail="Job not found.")
    await _require_catalog_brand_access(str(job_brand_id), user)
    return _catalog_job_for_response(job)


@router.post("/shopify/webhooks", status_code=202)
async def receive_shopify_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    catalog_sync_store: CatalogSyncStore = Depends(get_catalog_sync_store),
):
    """Verify a Shopify webhook and enqueue only the affected tenant's work.

    This endpoint is intentionally public to Shopify, but never trusts a shop
    header until the raw request has passed HMAC verification and that canonical
    shop is mapped to exactly one enabled brand configuration.
    """
    if not settings.SHOPIFY_WEBHOOKS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    secret = settings.SHOPIFY_WEBHOOK_SECRET.encode("utf-8")
    signature = request.headers.get("x-shopify-hmac-sha256", "")
    body = await request.body()
    if len(body) > max(1, int(settings.SHOPIFY_WEBHOOK_MAX_BODY_BYTES)):
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode("ascii")
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Shopify webhook signature")

    raw_shop = request.headers.get("x-shopify-shop-domain", "")
    try:
        source_url = catalog_service.normalize_authenticated_shopify_store_url(raw_shop)
        shop_domain = _shopify_domain(source_url)
    except ValueError:
        # Do not reveal whether a tenant has any Shopify integration.
        return {"status": "ignored"}

    db = connection_manager.get_system_db()
    brand = await db.brands.find_one(
        {
            "catalog_sync.source_type": "shopify",
            "$or": [
                {"catalog_sync.shop_domain": shop_domain},
                {"catalog_sync.source_url": source_url},
            ],
        }
    )
    if not brand:
        return {"status": "ignored"}
    config = dict(brand.get("catalog_sync") or {})
    if config.get("enabled") is False:
        return {"status": "ignored"}

    brand_id = str(brand.get("id") or "")
    if not brand_id:
        return {"status": "ignored"}
    topic = str(request.headers.get("x-shopify-topic", "")).strip().lower()
    webhook_id = str(request.headers.get("x-shopify-webhook-id", "")).strip()
    if not webhook_id:
        webhook_id = hashlib.sha256(body).hexdigest()
    idempotency_key = f"shopify:webhook:{shop_domain}:{webhook_id}"

    try:
        if topic == "products/delete":
            payload = json.loads(body.decode("utf-8"))
            product_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
            if not product_id:
                return {"status": "ignored"}
            job, deduplicated = await catalog_sync_store.enqueue_lifecycle_action(
                job_id=str(uuid.uuid4()),
                brand_id=brand_id,
                brand_slug=str(brand.get("slug") or brand_id),
                source_url=source_url,
                action="deactivate_product",
                product_id=product_id,
                trigger="shopify_webhook",
                idempotency_key=idempotency_key,
                webhook_topic=topic,
                webhook_id=webhook_id,
            )
        elif topic == "app/uninstalled":
            # Stop future snapshots before asynchronously deactivating all
            # catalog rows. The credential is removed, not merely hidden.
            await db.brands.update_one(
                {"id": brand_id},
                {
                    "$set": {
                        "catalog_sync.enabled": False,
                        "catalog_sync.uninstalled_at": datetime.utcnow().isoformat(),
                    },
                    "$unset": {
                        "catalog_sync.access_token": "",
                        "catalog_sync.access_token_encrypted": "",
                    },
                },
            )
            job, deduplicated = await catalog_sync_store.enqueue_lifecycle_action(
                job_id=str(uuid.uuid4()),
                brand_id=brand_id,
                brand_slug=str(brand.get("slug") or brand_id),
                source_url=source_url,
                action="deactivate_source",
                trigger="shopify_webhook",
                idempotency_key=idempotency_key,
                webhook_topic=topic,
                webhook_id=webhook_id,
            )
        elif topic in {"products/create", "products/update", "products/publish", "products/unpublish", "inventory_levels/update"}:
            if not config.get("access_token_encrypted") and not config.get("access_token"):
                logger.error("shopify_webhook_missing_catalog_credential", brand_id=brand_id, topic=topic)
                raise HTTPException(status_code=503, detail="Shopify catalog credentials are unavailable")
            job, deduplicated = await _enqueue_shopify_sync(
                catalog_sync_store=catalog_sync_store,
                brand_id=brand_id,
                brand=brand,
                source_url=source_url,
                access_token_encrypted=(
                    str(config.get("access_token_encrypted") or "")
                    or _encrypt_sync_secret(runtime_settings_service, str(config.get("access_token") or ""))
                ),
                fallback_currency=config.get("fallback_currency"),
                trigger="shopify_webhook",
                idempotency_key=idempotency_key,
                webhook_topic=topic,
                webhook_id=webhook_id,
            )
        else:
            return {"status": "ignored"}
    except (CatalogSyncStoreUnavailableError, ValueError) as exc:
        logger.error("shopify_webhook_queue_failed", error_type=type(exc).__name__, topic=topic)
        raise HTTPException(status_code=503, detail="Webhook queue is unavailable") from exc

    return {"status": "accepted", "job_id": job["job_id"], "deduplicated": deduplicated}


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
            has_saved_access_token = bool(existing.get("access_token_encrypted") or existing.get("access_token"))
            if not ((update.access_token and update.access_token.strip()) or has_saved_access_token):
                raise ValueError("A Shopify Admin API access token is required for a production catalog sync.")
            source_url = catalog_service.normalize_authenticated_shopify_store_url(update.source_url)
            await _ensure_shopify_store_available(brand_id=brand_id, source_url=source_url)
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
    if update.source_type == "shopify":
        sync_patch["shop_domain"] = _shopify_domain(source_url)
        sync_patch["enabled"] = True
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

    try:
        result = await db.brands.update_one({"id": brand_id}, {"$set": {"catalog_sync": patch}})
    except Exception as exc:
        logger.warning("catalog_sync_config_update_failed", brand_id=brand_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Catalog configuration storage is unavailable.") from exc
    if getattr(result, "matched_count", 1) == 0:
        raise HTTPException(status_code=404, detail="Brand not found.")
    return _expose_sync_config_for_admin(patch)


@router.post("/sync/{brand_id}")
async def manual_sync(
    brand_id: str,
    runtime_settings_service: RuntimeSettingsService = Depends(get_runtime_settings_service),
    catalog_sync_store: CatalogSyncStore = Depends(get_catalog_sync_store),
    _: User = Depends(_require_catalog_path_brand_access),
):
    """Queue an immediate resync from the immutable stored Shopify scope."""
    db = connection_manager.get_system_db()
    brand = await db.brands.find_one({"id": brand_id})
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")
    canonical_brand_id = str(brand.get("id") or brand_id)
    await _require_catalog_brand_access(canonical_brand_id, _)

    stored_config = dict(brand.get("catalog_sync") or {})
    config = _decrypt_sync_config_for_runtime(
        stored_config,
        runtime_settings_service,
    )
    if not config:
        raise HTTPException(status_code=400, detail="No sync config saved for this brand.")
    if config.get("enabled") is False:
        raise HTTPException(status_code=409, detail="Shopify sync is disabled for this brand.")

    source_type = config.get("source_type")

    if source_type == "shopify":
        try:
            source_url = catalog_service.normalize_authenticated_shopify_store_url(config.get("source_url"))
            if not config.get("access_token") or not str(config.get("access_token")).strip():
                raise ValueError("Shopify sync credentials are unavailable. Save a new Admin API token.")
            fallback_currency = catalog_service.normalize_currency_code(config.get("fallback_currency"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            job, deduplicated = await _enqueue_shopify_sync(
                catalog_sync_store=catalog_sync_store,
                brand_id=canonical_brand_id,
                brand=brand,
                source_url=source_url,
                access_token_encrypted=(
                    str(stored_config.get("access_token_encrypted") or "")
                    or _encrypt_sync_secret(runtime_settings_service, str(config.get("access_token") or ""))
                ),
                fallback_currency=fallback_currency,
                trigger="manual_sync",
            )
        except CatalogSyncStoreUnavailableError as exc:
            raise HTTPException(status_code=503, detail="Catalog sync queue is unavailable.") from exc
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "source_url": source_url,
            "deduplicated": deduplicated,
        }

    if source_type == "json_feed":
        try:
            fallback_currency = await catalog_service._resolve_configured_default_currency(canonical_brand_id)
            result = await catalog_service.fetch_json_feed(config["source_url"], fallback_currency=fallback_currency)
            completed_at = datetime.utcnow().isoformat()
            await db.brands.update_one(
                {"id": canonical_brand_id},
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
            logger.error(
                "catalog_manual_sync_failed",
                brand_id=canonical_brand_id,
                error_type=type(exc).__name__,
            )
            raise HTTPException(status_code=500, detail="Catalog sync failed.") from None

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
    """Persist the configuration before a durable sync is made claimable."""
    try:
        db = connection_manager.get_system_db()
        brand = await db.brands.find_one({"id": brand_id})
        if not brand:
            raise ValueError("Brand not found.")
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
        result = await db.brands.update_one(
            {"id": brand_id},
            {"$set": {"catalog_sync": merged}},
        )
        if getattr(result, "matched_count", 1) == 0:
            raise ValueError("Brand not found.")
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("sync_config_save_failed", brand_id=brand_id, error_type=type(exc).__name__)
        raise RuntimeError("Catalog sync configuration storage is unavailable") from exc
