from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastapi.concurrency import run_in_threadpool

from azure.identity import DefaultAzureCredential

from ..config import Settings
from .runtime_settings_service import RuntimeSettingsService

logger = structlog.get_logger()

ARM_SCOPE = "https://management.azure.com/.default"
ARM_API_VERSION = "2024-10-01"


class AzureDeploymentConfigError(RuntimeError):
    """Raised when the backend is missing Azure ARM discovery configuration."""


class AzureDeploymentAuthError(RuntimeError):
    """Raised when Azure credentials cannot acquire a management token."""


class AzureDeploymentRequestError(RuntimeError):
    """Raised when the Azure ARM deployments request fails."""


class AzureOpenAIDeploymentService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runtime_settings_service = RuntimeSettingsService(settings)
        self._arm_config: dict[str, str] = {}

    def _ensure_arm_config(self, config: dict[str, str]) -> None:
        missing = [
            key
            for key, value in {
                "AZURE_SUBSCRIPTION_ID": config.get("subscription_id"),
                "AZURE_RESOURCE_GROUP": config.get("resource_group"),
                "AZURE_OPENAI_ACCOUNT_NAME": config.get("account_name"),
            }.items()
            if not value
        ]
        if missing:
            raise AzureDeploymentConfigError(
                f"Azure deployment discovery is not configured. Missing: {', '.join(missing)}"
            )

    async def _get_arm_token(self) -> str:
        credential = DefaultAzureCredential()
        try:
            token = await run_in_threadpool(credential.get_token, ARM_SCOPE)
        except Exception as exc:
            logger.warning("azure_arm_token_fetch_failed", error=str(exc))
            raise AzureDeploymentAuthError(
                "Failed to acquire Azure management token with DefaultAzureCredential."
            ) from exc
        return token.token

    def _build_deployments_url(self, config: dict[str, str] | None = None) -> str:
        config = config or self._arm_config
        return (
            "https://management.azure.com/subscriptions/"
            f"{config['subscription_id']}/resourceGroups/"
            f"{config['resource_group']}/providers/Microsoft.CognitiveServices/accounts/"
            f"{config['account_name']}/deployments"
            f"?api-version={ARM_API_VERSION}"
        )

    async def _fetch_deployments_payload(self, config: dict[str, str] | None = None) -> dict[str, Any]:
        token = await self._get_arm_token()
        url = self._build_deployments_url(config)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("azure_arm_deployments_transport_error", error=str(exc))
            raise AzureDeploymentRequestError(
                "Azure ARM request failed while listing Azure OpenAI deployments."
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "azure_arm_deployments_http_error",
                status_code=response.status_code,
                body=response.text[:500],
            )
            raise AzureDeploymentRequestError(
                f"Azure ARM request failed with status {response.status_code}."
            )

        return response.json()

    @staticmethod
    def _model_name(properties: dict[str, Any], deployment_name: str) -> str:
        model = properties.get("model")
        if isinstance(model, dict):
            return model.get("name") or deployment_name
        if isinstance(model, str) and model:
            return model
        return deployment_name

    @staticmethod
    def _model_version(properties: dict[str, Any]) -> str | None:
        model = properties.get("model")
        if isinstance(model, dict):
            return model.get("version")
        return None

    def _parse_deployments(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        deployments: list[dict[str, Any]] = []
        for item in payload.get("value", []):
            if not isinstance(item, dict):
                continue
            properties = item.get("properties") or {}
            provisioning_state = properties.get("provisioningState") or ""
            if provisioning_state != "Succeeded":
                continue

            deployment_name = item.get("name")
            if not deployment_name:
                continue

            deployments.append(
                {
                    "deployment_name": deployment_name,
                    "model_name": self._model_name(properties, deployment_name),
                    "model_version": self._model_version(properties),
                    "provisioning_state": provisioning_state,
                    "sku_name": (item.get("sku") or {}).get("name"),
                }
            )

        deployments.sort(key=lambda deployment: deployment["deployment_name"].lower())
        return deployments

    async def _fallback_deployment_response(self, arm_config: dict[str, str]) -> dict[str, Any]:
        runtime_config = await self.runtime_settings_service.get_llm_runtime_config(
            provider_name="azure_openai"
        )
        deployment_name = (
            arm_config.get("default_deployment")
            or runtime_config.get("deployment_name")
            or runtime_config.get("model")
            or ""
        )
        model_name = runtime_config.get("model") or deployment_name
        deployments = []
        if deployment_name:
            deployments.append(
                {
                    "deployment_name": deployment_name,
                    "model_name": model_name,
                    "model_version": None,
                    "provisioning_state": "Configured",
                    "sku_name": None,
                }
            )

        return {
            "provider": "azure_openai",
            "default_deployment": deployment_name or None,
            "deployments": deployments,
        }

    async def list_deployments(self) -> dict[str, Any]:
        arm_config = await self.runtime_settings_service.get_azure_arm_config()
        self._arm_config = arm_config
        # A configured runtime deployment is not evidence that ARM discovery is
        # available. Surface missing ARM metadata to the operator instead of
        # presenting the configured deployment as a discovered one.
        self._ensure_arm_config(arm_config)
        fallback_response = await self._fallback_deployment_response(arm_config)

        try:
            payload = await self._fetch_deployments_payload()
        except (AzureDeploymentAuthError, AzureDeploymentRequestError) as exc:
            logger.warning(
                "azure_deployments_discovery_fallback",
                error=str(exc),
                fallback_count=len(fallback_response["deployments"]),
            )
            return fallback_response

        deployments = self._parse_deployments(payload)
        if not deployments:
            return fallback_response

        return {
            "provider": "azure_openai",
            "default_deployment": arm_config.get("default_deployment") or None,
            "deployments": deployments,
        }
