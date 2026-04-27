from __future__ import annotations

from typing import Any

import httpx

from app.bootstrap.atlas_vector import atlas_vector_index_definition
from app.bootstrap.database import BootstrapCheck
from app.config import Settings

ATLAS_API_BASE_URL = "https://cloud.mongodb.com/api/atlas/v2"


def has_atlas_admin_credentials(settings: Settings) -> bool:
    return all(
        [
            settings.ATLAS_PUBLIC_KEY,
            settings.ATLAS_PRIVATE_KEY,
            settings.ATLAS_PROJECT_ID,
            settings.ATLAS_CLUSTER_NAME,
        ]
    )


def missing_atlas_admin_credentials(settings: Settings) -> list[str]:
    missing = []
    for key in ["ATLAS_PUBLIC_KEY", "ATLAS_PRIVATE_KEY", "ATLAS_PROJECT_ID", "ATLAS_CLUSTER_NAME"]:
        if not getattr(settings, key):
            missing.append(key)
    return missing


def normalize_index_definition(definition: dict[str, Any] | None) -> dict[str, Any]:
    if not definition:
        return {"fields": []}

    fields = definition.get("fields") or []

    def field_key(field: dict[str, Any]) -> tuple[str, str]:
        return (str(field.get("path") or ""), str(field.get("type") or ""))

    normalized_fields = []
    for field in fields:
        normalized = {key: field[key] for key in sorted(field.keys()) if field.get(key) is not None}
        normalized_fields.append(normalized)

    return {"fields": sorted(normalized_fields, key=field_key)}


def definitions_match(current: dict[str, Any] | None, desired: dict[str, Any]) -> bool:
    return normalize_index_definition(current) == normalize_index_definition(desired)


def build_vector_index_payload(settings: Settings, database_name: str, collection_name: str = "knowledge_base") -> dict[str, Any]:
    return {
        "collectionName": collection_name,
        "database": database_name,
        "name": settings.VECTOR_INDEX_NAME,
        "type": "vectorSearch",
        "definition": atlas_vector_index_definition(settings),
    }


class AtlasAdminClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=ATLAS_API_BASE_URL,
            auth=httpx.DigestAuth(self.settings.ATLAS_PUBLIC_KEY, self.settings.ATLAS_PRIVATE_KEY),
            headers={
                "Accept": "application/vnd.atlas.2024-08-05+json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def __aenter__(self) -> "AtlasAdminClient":
        if self._client is None:
            self._client = self._build_client()
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _indexes_path(self, database_name: str, collection_name: str = "knowledge_base") -> str:
        return (
            f"/groups/{self.settings.ATLAS_PROJECT_ID}/clusters/{self.settings.ATLAS_CLUSTER_NAME}"
            f"/fts/indexes/{database_name}/{collection_name}"
        )

    def _index_path(self, index_id: str) -> str:
        return (
            f"/groups/{self.settings.ATLAS_PROJECT_ID}/clusters/{self.settings.ATLAS_CLUSTER_NAME}"
            f"/fts/indexes/{index_id}"
        )

    def _create_path(self) -> str:
        return f"/groups/{self.settings.ATLAS_PROJECT_ID}/clusters/{self.settings.ATLAS_CLUSTER_NAME}/fts/indexes"

    async def list_indexes(self, database_name: str, collection_name: str = "knowledge_base") -> list[dict[str, Any]]:
        response = await self.client.get(self._indexes_path(database_name, collection_name))
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list):
            return body
        return body.get("results") or []

    async def create_index(self, database_name: str, collection_name: str = "knowledge_base") -> dict[str, Any]:
        payload = build_vector_index_payload(self.settings, database_name, collection_name)
        response = await self.client.post(self._create_path(), json=payload)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def update_index(self, index_id: str, database_name: str, collection_name: str = "knowledge_base") -> dict[str, Any]:
        payload = build_vector_index_payload(self.settings, database_name, collection_name)
        response = await self.client.patch(self._index_path(index_id), json=payload)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def ensure_vector_index(
        self,
        database_name: str,
        *,
        collection_name: str = "knowledge_base",
        apply: bool = False,
    ) -> BootstrapCheck:
        desired = atlas_vector_index_definition(self.settings)
        missing_credentials = missing_atlas_admin_credentials(self.settings)
        if missing_credentials:
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="manual",
                detail=(
                    "Atlas Admin API credentials are not configured. Missing: "
                    + ", ".join(missing_credentials)
                ),
                metadata={"definition": desired},
            )

        try:
            indexes = await self.list_indexes(database_name, collection_name)
        except Exception as exc:
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="manual",
                detail=f"Atlas Admin API index inspection failed: {exc}",
                metadata={"definition": desired},
            )

        current = next((index for index in indexes if index.get("name") == self.settings.VECTOR_INDEX_NAME), None)
        if not current:
            if not apply:
                return BootstrapCheck(
                    name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                    status="manual",
                    detail="Atlas vector index is missing. Re-run bootstrap with --apply to create it.",
                    metadata={"definition": desired},
                )
            try:
                await self.create_index(database_name, collection_name)
                return BootstrapCheck(
                    name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                    status="ok",
                    detail="Atlas vector index create requested",
                )
            except Exception as exc:
                return BootstrapCheck(
                    name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                    status="error",
                    detail=f"Atlas vector index creation failed: {exc}",
                    metadata={"definition": desired},
                )

        current_definition = current.get("definition") or {}
        if definitions_match(current_definition, desired):
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="ok",
                detail="Atlas vector index already up to date",
            )

        index_id = current.get("indexID") or current.get("indexId") or current.get("id")
        if not apply:
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="manual",
                detail="Atlas vector index definition differs. Re-run bootstrap with --apply to update it.",
                metadata={"definition": desired},
            )
        if not index_id:
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="manual",
                detail="Atlas index differs but no index id was returned. Update it manually.",
                metadata={"definition": desired},
            )

        try:
            await self.update_index(index_id, database_name, collection_name)
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="ok",
                detail="Atlas vector index update requested",
            )
        except Exception as exc:
            return BootstrapCheck(
                name=f"{database_name}.{collection_name}.{self.settings.VECTOR_INDEX_NAME}",
                status="manual",
                detail=f"Atlas vector index update failed; update manually: {exc}",
                metadata={"definition": desired},
            )
