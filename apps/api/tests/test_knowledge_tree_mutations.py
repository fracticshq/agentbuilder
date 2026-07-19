"""Regression coverage for the extracted knowledge folder/tree coordinator."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.knowledge_paths import normalize_folder_path, normalize_item_path
from app.services.knowledge_tree_mutations import KnowledgeTreeMutations


class AsyncCursor:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        async def iterate():
            for row in self._rows:
                yield row

        return iterate()


class MutationResult:
    def __init__(self, *, deleted_count=0, modified_count=0):
        self.deleted_count = deleted_count
        self.modified_count = modified_count


class FolderCollection:
    def __init__(self):
        self.find_queries = []
        self.delete_queries = []
        self.update_calls = []

    def find(self, query):
        self.find_queries.append(query)
        return AsyncCursor([])

    async def find_one(self, _query):
        return None

    async def update_one(self, filter_, update, upsert=False):
        self.update_calls.append((filter_, update, upsert))

    async def delete_many(self, query):
        self.delete_queries.append(query)
        return MutationResult(deleted_count=1)


class KnowledgeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.find_queries = []
        self.update_calls = []

    def find(self, query):
        self.find_queries.append(query)
        path_clause, brand_clause, *agent_clause = query["$and"]
        old_path = path_clause["$or"][0]["metadata.folder"]
        brand_aliases = set(brand_clause["$or"][0]["metadata.brand_id"]["$in"])
        required_agent = (
            agent_clause[0]["metadata.agent_id"] if agent_clause else None
        )

        matching = []
        for document in self.documents:
            metadata = document["metadata"]
            in_folder = metadata.get("folder") == old_path or metadata.get(
                "folder", ""
            ).startswith(f"{old_path}/")
            in_brand = (
                metadata.get("brand_id") in brand_aliases
                or metadata.get("brand_slug") in brand_aliases
            )
            in_agent = not required_agent or metadata.get("agent_id") == required_agent
            if in_folder and in_brand and in_agent:
                matching.append(document)
        return AsyncCursor(matching)

    async def update_one(self, filter_, update):
        self.update_calls.append((filter_, update))
        for document in self.documents:
            if document["_id"] == filter_["_id"]:
                for path, value in update["$set"].items():
                    if path.startswith("metadata."):
                        document["metadata"][path.removeprefix("metadata.")] = value
                    else:
                        document[path] = value


def build_mutations(*, folders, collections, qdrant=None):
    async def resolve_brand_scope(_brand_id):
        return {
            "brand_id": "brand-canonical",
            "brand_slug": "brand-slug",
            "aliases": ["brand-canonical", "brand-slug", "legacy-brand"],
            "db_name": "brand-slug",
        }

    async def get_folders(_brand_id):
        return folders

    async def get_collections(_brand_id):
        return collections

    return KnowledgeTreeMutations(
        resolve_brand_scope=resolve_brand_scope,
        get_knowledge_folders_collection=get_folders,
        get_brand_knowledge_collections=get_collections,
        normalize_folder_path=normalize_folder_path,
        normalize_item_path=normalize_item_path,
        qdrant=qdrant,
    )


@pytest.mark.asyncio
async def test_cascade_scopes_document_updates_to_brand_aliases_and_agent():
    documents = [
        {
            "_id": "canonical-agent-a",
            "chunk_id": "chunk-1",
            "title": "Guide",
            "metadata": {
                "folder": "/guides",
                "name": "guide",
                "brand_id": "brand-canonical",
                "agent_id": "agent-a",
            },
        },
        {
            "_id": "slug-agent-a",
            "chunk_id": "chunk-2",
            "title": "Nested guide",
            "metadata": {
                "folder": "/guides/nested",
                "name": "nested-guide",
                "brand_slug": "brand-slug",
                "agent_id": "agent-a",
            },
        },
        {
            "_id": "canonical-agent-b",
            "chunk_id": "chunk-3",
            "title": "Other agent guide",
            "metadata": {
                "folder": "/guides",
                "name": "other-agent-guide",
                "brand_id": "brand-canonical",
                "agent_id": "agent-b",
            },
        },
        {
            "_id": "other-brand-agent-a",
            "chunk_id": "chunk-4",
            "title": "Other brand guide",
            "metadata": {
                "folder": "/guides",
                "name": "other-brand-guide",
                "brand_id": "other-brand",
                "agent_id": "agent-a",
            },
        },
    ]
    collection = KnowledgeCollection(deepcopy(documents))
    mutations = build_mutations(
        folders=FolderCollection(),
        collections=[collection],
    )

    result = await mutations.cascade_folder_path_change(
        "legacy-brand",
        "/guides",
        "/manuals",
        agent_id="agent-a",
    )

    assert result == {"folders": 0, "documents": 2}
    folders_by_id = {item["_id"]: item["metadata"]["folder"] for item in collection.documents}
    assert folders_by_id["canonical-agent-a"] == "/manuals"
    assert folders_by_id["slug-agent-a"] == "/manuals/nested"
    assert folders_by_id["canonical-agent-b"] == "/guides"
    assert folders_by_id["other-brand-agent-a"] == "/guides"

    query = collection.find_queries[0]
    assert query["$and"][1]["$or"][0]["metadata.brand_id"]["$in"] == [
        "brand-canonical",
        "brand-slug",
        "legacy-brand",
    ]
    assert query["$and"][2] == {"metadata.agent_id": "agent-a"}


@pytest.mark.asyncio
async def test_qdrant_failure_does_not_rollback_mongo_folder_repoint():
    class FailingQdrant:
        def __init__(self):
            self.calls = []

        async def reparent_chunks(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise RuntimeError("Qdrant is unavailable")

    collection = KnowledgeCollection([
        {
            "_id": "chunk-row",
            "chunk_id": "chunk-1",
            "title": "Guide",
            "metadata": {
                "folder": "/guides",
                "name": "guide",
                "brand_id": "brand-canonical",
                "agent_id": "agent-a",
            },
        }
    ])
    qdrant = FailingQdrant()
    mutations = build_mutations(
        folders=FolderCollection(),
        collections=[collection],
        qdrant=qdrant,
    )

    result = await mutations.cascade_folder_path_change(
        "legacy-brand",
        "/guides",
        "/manuals",
        agent_id="agent-a",
    )

    assert result == {"folders": 0, "documents": 1}
    assert collection.documents[0]["metadata"]["folder"] == "/manuals"
    assert collection.documents[0]["metadata"]["path"] == "/manuals/guide"
    assert qdrant.calls[0][0] == (["chunk-1"], "/manuals", "/manuals/guide")
    assert qdrant.calls[0][1]["brand_slug"] == "brand-slug"


@pytest.mark.asyncio
async def test_delete_folder_keeps_canonical_brand_and_agent_scope():
    folders = FolderCollection()
    mutations = build_mutations(folders=folders, collections=[])

    result = await mutations.delete_folder(
        "legacy-brand",
        {
            "_id": "folder-row",
            "path": "/guides",
            "parent_path": "/",
        },
        agent_id="agent-a",
    )

    assert result == {
        "deleted": True,
        "type": "folder",
        "deleted_folders": 1,
        "reparented_documents": 0,
    }
    query = folders.delete_queries[0]
    assert query["brand_id"] == "brand-canonical"
    assert query["agent_id"] == "agent-a"
