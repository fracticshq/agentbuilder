"""Stateful folder and tree mutations for the knowledge base.

The coordinator deliberately receives its storage, brand-scope, path, and
vector dependencies from :class:`KnowledgeService`.  That keeps the stateful
Mongo/Qdrant workflow independently testable without making this module depend
on the broad knowledge service.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog


logger = structlog.get_logger()

BrandScopeResolver = Callable[[str], Awaitable[Dict[str, Any]]]
FoldersCollectionProvider = Callable[[str], Awaitable[Any]]
KnowledgeCollectionsProvider = Callable[[str], Awaitable[list[Any]]]
FolderPathNormalizer = Callable[[Optional[str]], str]
ItemPathNormalizer = Callable[[Optional[str], Optional[str]], tuple[str, str, str]]
DocumentDeleter = Callable[..., Awaitable[bool]]


class KnowledgeTreeMutations:
    """Coordinate Mongo-backed knowledge folder and item tree mutations.

    Mongo is authoritative for tree state.  Qdrant reflects the resulting
    folder/path metadata after Mongo succeeds; vector errors are logged and do
    not undo an already committed Mongo mutation.
    """

    def __init__(
        self,
        *,
        resolve_brand_scope: BrandScopeResolver,
        get_knowledge_folders_collection: FoldersCollectionProvider,
        get_brand_knowledge_collections: KnowledgeCollectionsProvider,
        normalize_folder_path: FolderPathNormalizer,
        normalize_item_path: ItemPathNormalizer,
        qdrant: Optional[Any] = None,
        delete_document: Optional[DocumentDeleter] = None,
    ) -> None:
        self._resolve_brand_scope = resolve_brand_scope
        self._get_knowledge_folders_collection = get_knowledge_folders_collection
        self._get_brand_knowledge_collections = get_brand_knowledge_collections
        self._normalize_folder_path = normalize_folder_path
        self._normalize_item_path = normalize_item_path
        self._qdrant = qdrant
        self._delete_document = delete_document

    async def create_folder(
        self,
        brand_id: str,
        path: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        folder_path = self._normalize_folder_path(path)
        if folder_path == "/":
            raise ValueError("Root folder already exists")

        parent_path = self._normalize_folder_path(
            "/".join(folder_path.rstrip("/").split("/")[:-1]) or "/"
        )
        now = datetime.utcnow().isoformat()
        brand_scope = await self._resolve_brand_scope(brand_id)
        resolved_brand_id = brand_scope.get("brand_id") or brand_id
        folder_doc = {
            "id": folder_path,
            "brand_id": resolved_brand_id,
            "brand_slug": brand_scope.get("brand_slug"),
            "agent_id": agent_id,
            "name": folder_path.rstrip("/").split("/")[-1],
            "path": folder_path,
            "parent_path": parent_path,
            "created_at": now,
            "updated_at": now,
        }
        collection = await self._get_knowledge_folders_collection(brand_id)
        # Mongo rejects a path in both $setOnInsert and $set (WriteError 40).
        # Keep updated_at in $set so repeated creates refresh it.
        insert_only = {
            key: value for key, value in folder_doc.items() if key != "updated_at"
        }
        await collection.update_one(
            {
                "brand_id": resolved_brand_id,
                "agent_id": agent_id,
                "path": folder_path,
            },
            {"$setOnInsert": insert_only, "$set": {"updated_at": now}},
            upsert=True,
        )
        return {**folder_doc, "type": "folder"}

    async def find_folder_doc(
        self,
        brand_id: str,
        path: str,
        agent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the stored folder document for a normalized path, if present."""
        brand_scope = await self._resolve_brand_scope(brand_id)
        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        query: Dict[str, Any] = {
            "brand_id": brand_scope.get("brand_id") or brand_id,
            "path": self._normalize_folder_path(path),
        }
        if agent_id:
            query["agent_id"] = agent_id
        return await folders_collection.find_one(query)

    async def cascade_folder_path_change(
        self,
        brand_id: str,
        old_path: str,
        new_path: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Re-point descendant folders and documents after a folder path change."""
        old_path = self._normalize_folder_path(old_path)
        new_path = self._normalize_folder_path(new_path)
        # Reparenting to root is valid for folder deletion.  The root itself
        # cannot move, and a same-path change has no work to do.
        if old_path == "/" or old_path == new_path:
            return {"folders": 0, "documents": 0}

        now = datetime.utcnow().isoformat()
        old_prefix = old_path + "/"

        def repoint(value: str) -> str:
            if value == old_path:
                return new_path
            if value.startswith(old_prefix):
                return self._normalize_folder_path(new_path + value[len(old_path) :])
            return value

        brand_scope = await self._resolve_brand_scope(brand_id)
        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        folder_query: Dict[str, Any] = {
            "brand_id": brand_scope.get("brand_id") or brand_id,
            "path": {"$regex": f"^{re.escape(old_prefix)}"},
        }
        if agent_id:
            folder_query["agent_id"] = agent_id

        folders_updated = 0
        async for child in folders_collection.find(folder_query):
            child_path = child.get("path") or ""
            updated_path = repoint(child_path)
            updated_parent = repoint(child.get("parent_path") or "/")
            await folders_collection.update_one(
                {"_id": child["_id"]},
                {
                    "$set": {
                        "path": updated_path,
                        "id": updated_path,
                        "parent_path": updated_parent,
                        "updated_at": now,
                    }
                },
            )
            folders_updated += 1

        brand_aliases = brand_scope.get("aliases") or [brand_id]
        documents_updated = 0
        qdrant_groups: Dict[tuple[str, str], list[Any]] = {}
        for collection in await self._get_brand_knowledge_collections(brand_id):
            document_query: Dict[str, Any] = {
                "$and": [
                    {
                        "$or": [
                            {"metadata.folder": old_path},
                            {
                                "metadata.folder": {
                                    "$regex": f"^{re.escape(old_prefix)}"
                                }
                            },
                        ]
                    },
                    {
                        "$or": [
                            {"metadata.brand_id": {"$in": brand_aliases}},
                            {"metadata.brand_slug": {"$in": brand_aliases}},
                        ]
                    },
                ]
            }
            if agent_id:
                document_query["$and"].append({"metadata.agent_id": agent_id})

            async for document in collection.find(document_query):
                metadata = document.get("metadata") or {}
                new_folder = repoint(
                    self._normalize_folder_path(metadata.get("folder"))
                )
                name = metadata.get("name") or document.get("title") or document.get("doc_id")
                _, _, new_document_path = self._normalize_item_path(new_folder, name)
                await collection.update_one(
                    {"_id": document["_id"]},
                    {
                        "$set": {
                            "metadata.folder": new_folder,
                            "metadata.path": new_document_path,
                            "metadata.updated_at": now,
                        }
                    },
                )
                documents_updated += 1
                if self._qdrant and document.get("chunk_id"):
                    qdrant_groups.setdefault((new_folder, new_document_path), []).append(
                        document["chunk_id"]
                    )

        if self._qdrant and qdrant_groups:
            brand_slug = brand_scope.get("brand_slug") or brand_id
            for (new_folder, new_document_path), chunk_ids in qdrant_groups.items():
                try:
                    await self._qdrant.reparent_chunks(
                        chunk_ids,
                        new_folder,
                        new_document_path,
                        brand_slug=brand_slug,
                    )
                except Exception as exc:
                    # Mongo has already committed; preserve that authoritative
                    # update even if its vector mirror is temporarily unavailable.
                    logger.error(
                        "qdrant_reparent_failed",
                        folder=new_folder,
                        error=str(exc),
                    )

        return {"folders": folders_updated, "documents": documents_updated}

    async def move_item(
        self,
        brand_id: str,
        item_id: str,
        target_folder: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_folder = self._normalize_folder_path(target_folder)
        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]
        updated = 0
        item_name: Optional[str] = None

        folder_doc = await self.find_folder_doc(brand_id, item_id, agent_id)
        if folder_doc:
            folder_name = folder_doc.get("name") or self._normalize_folder_path(
                item_id
            ).rstrip("/").split("/")[-1]
            new_path = self._normalize_item_path(target_folder, folder_name)[2]
            if new_path == self._normalize_folder_path(item_id):
                return {
                    "id": new_path,
                    "type": "folder",
                    "path": new_path,
                    "parent_path": target_folder,
                }
            if new_path == folder_doc.get("path") or new_path.startswith(
                (folder_doc.get("path") or "") + "/"
            ):
                raise ValueError("Cannot move a folder into itself")

            now = datetime.utcnow().isoformat()
            folders_collection = await self._get_knowledge_folders_collection(brand_id)
            await folders_collection.update_one(
                {"_id": folder_doc["_id"]},
                {
                    "$set": {
                        "path": new_path,
                        "id": new_path,
                        "parent_path": target_folder,
                        "updated_at": now,
                    }
                },
            )
            await self.cascade_folder_path_change(
                brand_id,
                folder_doc.get("path"),
                new_path,
                agent_id,
            )
            return {
                "id": new_path,
                "type": "folder",
                "path": new_path,
                "parent_path": target_folder,
            }

        for collection in await self._get_brand_knowledge_collections(brand_id):
            query: Dict[str, Any] = {
                "$and": [
                    {
                        "$or": [
                            {"metadata.job_id": item_id},
                            {"doc_id": item_id},
                        ]
                    },
                    {
                        "$or": [
                            {"metadata.brand_id": {"$in": brand_aliases}},
                            {"metadata.brand_slug": {"$in": brand_aliases}},
                        ]
                    },
                ]
            }
            if agent_id:
                query["$and"].append({"metadata.agent_id": agent_id})

            first = await collection.find_one(query)
            if first and not item_name:
                item_name = (
                    (first.get("metadata") or {}).get("name")
                    or first.get("title")
                    or item_id
                )
            folder, name, path = self._normalize_item_path(
                target_folder, item_name or item_id
            )
            result = await collection.update_many(
                query,
                {
                    "$set": {
                        "metadata.folder": folder,
                        "metadata.name": name,
                        "metadata.path": path,
                        "metadata.updated_at": datetime.utcnow().isoformat(),
                    }
                },
            )
            updated += result.modified_count

        if updated == 0:
            return {}
        return {
            "id": item_id,
            "folder": target_folder,
            "path": self._normalize_item_path(
                target_folder, item_name or item_id
            )[2],
        }

    async def rename_item(
        self,
        brand_id: str,
        item_id: str,
        name: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_name = name.strip().strip("/")
        if not clean_name:
            raise ValueError("Name is required")

        brand_scope = await self._resolve_brand_scope(brand_id)
        brand_aliases = brand_scope.get("aliases") or [brand_id]

        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        folder_query: Dict[str, Any] = {
            "brand_id": brand_scope.get("brand_id") or brand_id,
            "path": item_id,
        }
        if agent_id:
            folder_query["agent_id"] = agent_id
        folder_doc = await folders_collection.find_one(folder_query)
        if folder_doc:
            parent = folder_doc.get("parent_path") or "/"
            old_path = folder_doc.get("path") or item_id
            new_path = self._normalize_item_path(parent, clean_name)[2]
            if new_path != old_path:
                await folders_collection.update_one(
                    {"_id": folder_doc["_id"]},
                    {
                        "$set": {
                            "name": clean_name,
                            "path": new_path,
                            "id": new_path,
                            "updated_at": datetime.utcnow().isoformat(),
                        }
                    },
                )
                await self.cascade_folder_path_change(
                    brand_id,
                    old_path,
                    new_path,
                    agent_id,
                )
            return {
                "id": new_path,
                "type": "folder",
                "name": clean_name,
                "path": new_path,
                "parent_path": parent,
            }

        updated = 0
        next_path: Optional[str] = None
        for collection in await self._get_brand_knowledge_collections(brand_id):
            query: Dict[str, Any] = {
                "$and": [
                    {
                        "$or": [
                            {"metadata.job_id": item_id},
                            {"doc_id": item_id},
                        ]
                    },
                    {
                        "$or": [
                            {"metadata.brand_id": {"$in": brand_aliases}},
                            {"metadata.brand_slug": {"$in": brand_aliases}},
                        ]
                    },
                ]
            }
            if agent_id:
                query["$and"].append({"metadata.agent_id": agent_id})

            first = await collection.find_one(query)
            folder = self._normalize_folder_path(
                (first or {}).get("metadata", {}).get("folder") if first else "/"
            )
            _, _, path = self._normalize_item_path(folder, clean_name)
            next_path = path
            result = await collection.update_many(
                query,
                {
                    "$set": {
                        "title": clean_name,
                        "metadata.filename": clean_name,
                        "metadata.name": clean_name,
                        "metadata.path": path,
                        "metadata.updated_at": datetime.utcnow().isoformat(),
                    }
                },
            )
            updated += result.modified_count

        if updated == 0:
            return {}
        return {
            "id": item_id,
            "type": "file",
            "name": clean_name,
            "path": next_path,
        }

    async def delete_item(
        self,
        item_id: str,
        brand_id: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a folder tree or delegate a file deletion to its owner."""
        folder_doc = await self.find_folder_doc(brand_id, item_id, agent_id)
        if folder_doc:
            return await self.delete_folder(brand_id, folder_doc, agent_id)
        if not self._delete_document:
            raise RuntimeError("A document deletion dependency is required")
        deleted = await self._delete_document(item_id, brand_id=brand_id)
        return {"deleted": deleted, "type": "file"}

    async def delete_folder(
        self,
        brand_id: str,
        folder_doc: Dict[str, Any],
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove folder records and reparent their documents to the parent."""
        folder_path = self._normalize_folder_path(folder_doc.get("path"))
        parent_path = self._normalize_folder_path(folder_doc.get("parent_path") or "/")

        brand_scope = await self._resolve_brand_scope(brand_id)
        folders_collection = await self._get_knowledge_folders_collection(brand_id)
        prefix = folder_path + "/"
        delete_query: Dict[str, Any] = {
            "brand_id": brand_scope.get("brand_id") or brand_id,
            "$or": [
                {"path": folder_path},
                {"path": {"$regex": f"^{re.escape(prefix)}"}},
            ],
        }
        if agent_id:
            delete_query["agent_id"] = agent_id
        result = await folders_collection.delete_many(delete_query)

        reparented = await self.cascade_folder_path_change(
            brand_id,
            folder_path,
            parent_path,
            agent_id,
        )
        return {
            "deleted": result.deleted_count > 0,
            "type": "folder",
            "deleted_folders": result.deleted_count,
            "reparented_documents": reparented.get("documents", 0),
        }
