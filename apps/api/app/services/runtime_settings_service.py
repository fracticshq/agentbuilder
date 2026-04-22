from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from cryptography.fernet import Fernet

from llm.factory import create_provider_from_env
from retrieval.vector.voyage_client import VoyageClient

from ..config import Settings
from ..connections import connection_manager
from ..runtime_settings_registry import (
    SECTIONS,
    SECTIONS_BY_ID,
    SETTINGS_BY_KEY,
    SETTINGS_REGISTRY,
    RuntimeSettingDefinition,
)

logger = structlog.get_logger(__name__)

RUNTIME_SETTINGS_COLLECTION = "runtime_settings"


class RuntimeSettingsUnavailableError(RuntimeError):
    """Raised when a caller needs the settings store but MongoDB is unavailable."""


class RuntimeSettingsValidationError(RuntimeError):
    """Raised when runtime settings validation fails."""


class RuntimeSettingsService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._fernet = Fernet(self._derive_encryption_key())

    def _derive_encryption_key(self) -> bytes:
        seed = (
            self._normalize_seed_candidate(getattr(self.settings, "SETTINGS_ENCRYPTION_KEY", None))
            or self._normalize_seed_candidate(getattr(self.settings, "PII_ENCRYPTION_KEY", None))
            or self._normalize_seed_candidate(getattr(self.settings, "SECRET_KEY", None))
            or "agentbuilder-runtime-settings"
        )
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def _normalize_seed_candidate(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            decoded = value.decode("utf-8", errors="ignore").strip()
            return decoded or None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return None

    def _get_collection(self):
        try:
            system_db = connection_manager.get_system_db()
        except Exception as exc:
            raise RuntimeSettingsUnavailableError("System database is not connected.") from exc
        return system_db[RUNTIME_SETTINGS_COLLECTION]

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    def _mask_value(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "•" * len(value)
        return f"{'•' * max(4, len(value) - 4)}{value[-4:]}"

    def _trimmed_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        trimmed = value.strip()
        return trimmed or None

    def _setting_env_value(self, definition: RuntimeSettingDefinition) -> str | None:
        if not definition.env_var:
            return None
        env_value = getattr(self.settings, definition.env_var, None)
        return self._trimmed_or_none(env_value)

    async def ensure_indexes(self) -> None:
        try:
            collection = self._get_collection()
        except RuntimeSettingsUnavailableError:
            return

        await collection.create_index("key", unique=True, name="runtime_setting_key_idx")
        await collection.create_index("section", name="runtime_setting_section_idx")

    async def _load_stored_documents(self) -> dict[str, dict[str, Any]]:
        try:
            collection = self._get_collection()
        except RuntimeSettingsUnavailableError:
            return {}

        documents: dict[str, dict[str, Any]] = {}
        async for document in collection.find({}):
            key = document.get("key")
            if isinstance(key, str):
                documents[key] = document
        return documents

    async def get_effective_values(self, overrides: dict[str, Any] | None = None) -> dict[str, str | None]:
        stored_documents = await self._load_stored_documents()
        effective: dict[str, str | None] = {}
        overrides = overrides or {}

        for definition in SETTINGS_REGISTRY:
            if definition.key in overrides:
                effective[definition.key] = self._trimmed_or_none(overrides[definition.key])
                continue

            stored_document = stored_documents.get(definition.key)
            encrypted_value = stored_document.get("value_encrypted") if stored_document else None
            if encrypted_value:
                try:
                    effective[definition.key] = self._decrypt(encrypted_value)
                    continue
                except Exception as exc:
                    logger.error("runtime_setting_decrypt_failed", key=definition.key, error=str(exc))

            effective[definition.key] = self._setting_env_value(definition)

        return effective

    async def list_settings_for_admin(self) -> dict[str, Any]:
        stored_documents = await self._load_stored_documents()
        effective_values = await self.get_effective_values()
        sections_payload: list[dict[str, Any]] = []

        for section in SECTIONS:
            fields: list[dict[str, Any]] = []
            for definition in SETTINGS_REGISTRY:
                if definition.section != section.id:
                    continue

                stored_document = stored_documents.get(definition.key)
                effective_value = effective_values.get(definition.key)
                source = "stored" if stored_document else ("environment" if effective_value else "default")
                field_payload: dict[str, Any] = {
                    "key": definition.key,
                    "label": definition.label,
                    "description": definition.description,
                    "input_type": definition.input_type,
                    "secret": definition.secret,
                    "required": definition.required,
                    "configured": bool(effective_value),
                    "source": source,
                }

                if definition.options:
                    field_payload["options"] = [
                        {"value": option.value, "label": option.label}
                        for option in definition.options
                    ]

                updated_at = stored_document.get("updated_at") if stored_document else None
                if updated_at:
                    field_payload["updated_at"] = updated_at

                if definition.secret:
                    field_payload["masked_value"] = self._mask_value(effective_value or "")
                else:
                    field_payload["value"] = effective_value or ""

                fields.append(field_payload)

            sections_payload.append(
                {
                    "id": section.id,
                    "title": section.title,
                    "description": section.description,
                    "supports_connection_test": section.supports_connection_test,
                    "fields": fields,
                }
            )

        return {"sections": sections_payload}

    async def update_settings(
        self,
        updates: dict[str, Any],
        *,
        actor: str = "admin",
    ) -> dict[str, Any]:
        invalid_keys = sorted(key for key in updates if key not in SETTINGS_BY_KEY)
        if invalid_keys:
            raise RuntimeSettingsValidationError(
                f"Unknown runtime setting keys: {', '.join(invalid_keys)}"
            )

        try:
            collection = self._get_collection()
        except RuntimeSettingsUnavailableError as exc:
            raise RuntimeSettingsValidationError(
                "System database is not connected. Runtime settings cannot be updated."
            ) from exc

        now = datetime.now(timezone.utc).isoformat()
        stored_documents = await self._load_stored_documents()
        applied_updates: list[dict[str, Any]] = []

        for key, raw_value in updates.items():
            definition = SETTINGS_BY_KEY[key]
            value = self._trimmed_or_none(raw_value)
            previous_document = stored_documents.get(key)
            previous_value = None
            if previous_document and previous_document.get("value_encrypted"):
                try:
                    previous_value = self._decrypt(previous_document["value_encrypted"])
                except Exception:
                    previous_value = None

            if value is None:
                await collection.delete_one({"key": key})
                applied_updates.append(
                    {
                        "key": key,
                        "action": "cleared",
                        "section": definition.section,
                    }
                )
            else:
                await collection.update_one(
                    {"key": key},
                    {
                        "$set": {
                            "key": key,
                            "section": definition.section,
                            "secret": definition.secret,
                            "value_encrypted": self._encrypt(value),
                            "updated_at": now,
                            "updated_by": actor,
                        },
                        "$setOnInsert": {
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )
                applied_updates.append(
                    {
                        "key": key,
                        "action": "updated",
                        "section": definition.section,
                    }
                )

            await self._write_audit_log(
                action="runtime_setting_updated" if value is not None else "runtime_setting_cleared",
                actor=actor,
                key=key,
                secret=definition.secret,
                previous_value=previous_value,
                new_value=value,
                timestamp=now,
            )

        return {
            "updated": applied_updates,
            "settings": await self.list_settings_for_admin(),
        }

    async def _write_audit_log(
        self,
        *,
        action: str,
        actor: str,
        key: str,
        secret: bool,
        previous_value: str | None,
        new_value: str | None,
        timestamp: str,
    ) -> None:
        try:
            system_db = connection_manager.get_system_db()
        except Exception:
            logger.warning("runtime_setting_audit_log_skipped", key=key)
            return

        await system_db["audit_logs"].insert_one(
            {
                "action": action,
                "actor": actor,
                "target": "runtime_settings",
                "key": key,
                "secret": secret,
                "previous_value_masked": self._mask_value(previous_value or "") if secret else previous_value,
                "new_value_masked": self._mask_value(new_value or "") if secret else new_value,
                "created_at": timestamp,
            }
        )

    async def get_llm_runtime_config(
        self,
        *,
        provider_name: str | None = None,
        model: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = await self.get_effective_values(overrides=overrides)
        resolved_provider = provider_name or values.get("general.default_llm_provider") or "openai"

        if resolved_provider == "azure_openai":
            deployment_name = model or values.get("azure_openai.deployment") or values.get("azure_openai.model")
            return {
                "provider_name": resolved_provider,
                "api_key": values.get("azure_openai.api_key") or "",
                "model": model or values.get("azure_openai.model") or deployment_name or "gpt-5.4-mini",
                "api_version": values.get("azure_openai.api_version") or "",
                "azure_endpoint": values.get("azure_openai.endpoint") or "",
                "deployment_name": deployment_name or "",
            }

        if resolved_provider == "qwen":
            return {
                "provider_name": resolved_provider,
                "api_key": values.get("qwen.api_key") or "",
                "model": model or values.get("qwen.model") or "qwen-max",
                "base_url": values.get("qwen.base_url") or "",
            }

        return {
            "provider_name": resolved_provider,
            "api_key": values.get("openai.api_key") or "",
            "model": model or values.get("openai.model") or "gpt-4o-mini",
            "base_url": values.get("openai.base_url") or "",
        }

    async def get_voyage_runtime_config(
        self,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = await self.get_effective_values(overrides=overrides)
        return {
            "api_key": values.get("voyage.api_key") or "",
            "model": values.get("voyage.model") or "voyage-large-2-instruct",
        }

    async def get_azure_arm_config(
        self,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = await self.get_effective_values(overrides=overrides)
        return {
            "subscription_id": values.get("azure_openai.subscription_id") or "",
            "resource_group": values.get("azure_openai.resource_group") or "",
            "account_name": values.get("azure_openai.account_name") or "",
            "default_deployment": values.get("azure_openai.deployment") or "",
        }

    def _filtered_overrides(
        self,
        overrides: dict[str, Any] | None,
        sections: Iterable[str],
    ) -> dict[str, Any]:
        if not overrides:
            return {}
        allowed_sections = set(sections)
        return {
            key: value
            for key, value in overrides.items()
            if (definition := SETTINGS_BY_KEY.get(key)) and definition.section in allowed_sections
        }

    async def test_connections(
        self,
        *,
        sections: list[str] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_sections = sections or [
            section.id for section in SECTIONS if section.supports_connection_test
        ]

        unknown_sections = sorted(section for section in requested_sections if section not in SECTIONS_BY_ID)
        if unknown_sections:
            raise RuntimeSettingsValidationError(
                f"Unknown settings sections: {', '.join(unknown_sections)}"
            )

        results: list[dict[str, Any]] = []
        for section_id in requested_sections:
            if section_id == "azure_openai":
                results.append(
                    await self._test_azure_openai_connection(
                        overrides=self._filtered_overrides(overrides, ["azure_openai", "general"])
                    )
                )
            elif section_id == "voyage":
                results.append(
                    await self._test_voyage_connection(
                        overrides=self._filtered_overrides(overrides, ["voyage"])
                    )
                )

        overall_status = "healthy" if all(result["status"] == "healthy" for result in results) else "unhealthy"
        return {
            "status": overall_status,
            "results": results,
        }

    async def _test_azure_openai_connection(
        self,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = await self.get_llm_runtime_config(
            provider_name="azure_openai",
            overrides=overrides,
        )

        missing = [
            key
            for key, value in {
                "azure_openai.api_key": config.get("api_key"),
                "azure_openai.endpoint": config.get("azure_endpoint"),
                "azure_openai.api_version": config.get("api_version"),
                "azure_openai.deployment": config.get("deployment_name"),
            }.items()
            if not self._trimmed_or_none(value)
        ]
        if missing:
            return {
                "section": "azure_openai",
                "status": "unhealthy",
                "detail": f"Missing required Azure OpenAI settings: {', '.join(missing)}",
            }

        try:
            provider = create_provider_from_env(
                provider_name="azure_openai",
                api_key=config["api_key"],
                model=config["model"],
                api_version=config["api_version"],
                azure_endpoint=config["azure_endpoint"],
                deployment_name=config["deployment_name"],
            )
            health = await provider.health_check()
            status = "healthy" if health.get("status") == "healthy" else "unhealthy"
            return {
                "section": "azure_openai",
                "status": status,
                "detail": health.get("error") or f"Connected to deployment {config['deployment_name']}.",
            }
        except Exception as exc:
            logger.warning("runtime_settings_azure_test_failed", error=str(exc))
            return {
                "section": "azure_openai",
                "status": "unhealthy",
                "detail": str(exc),
            }

    async def _test_voyage_connection(
        self,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = await self.get_voyage_runtime_config(overrides=overrides)
        missing = [
            key
            for key, value in {
                "voyage.api_key": config.get("api_key"),
                "voyage.model": config.get("model"),
            }.items()
            if not self._trimmed_or_none(value)
        ]
        if missing:
            return {
                "section": "voyage",
                "status": "unhealthy",
                "detail": f"Missing required Voyage settings: {', '.join(missing)}",
            }

        client = None
        try:
            client = VoyageClient(api_key=config["api_key"], model=config["model"])
            healthy = await client.health_check()
            return {
                "section": "voyage",
                "status": "healthy" if healthy else "unhealthy",
                "detail": "Voyage embeddings connection is healthy." if healthy else "Voyage health check failed.",
            }
        except Exception as exc:
            logger.warning("runtime_settings_voyage_test_failed", error=str(exc))
            return {
                "section": "voyage",
                "status": "unhealthy",
                "detail": str(exc),
            }
        finally:
            if client is not None:
                await client.close()
