import pytest

from app.bootstrap.atlas_admin import (
    AtlasAdminClient,
    build_vector_index_payload,
    definitions_match,
    has_atlas_admin_credentials,
    missing_atlas_admin_credentials,
)
from app.config import Settings


class FakeResponse:
    def __init__(self, body=None):
        self._body = body if body is not None else {}
        self.content = b"{}"

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class FakeAtlasHttpClient:
    def __init__(self, indexes=None):
        self.indexes = indexes if indexes is not None else []
        self.posts = []
        self.patches = []

    async def get(self, path):
        return FakeResponse(self.indexes)

    async def post(self, path, json):
        self.posts.append({"path": path, "json": json})
        return FakeResponse({"created": True})

    async def patch(self, path, json):
        self.patches.append({"path": path, "json": json})
        return FakeResponse({"updated": True})

    async def aclose(self):
        return None


def settings(**overrides):
    values = {
        "SECRET_KEY": "test-secret-key",
        "ATLAS_PUBLIC_KEY": "public",
        "ATLAS_PRIVATE_KEY": "private",
        "ATLAS_PROJECT_ID": "project-id",
        "ATLAS_CLUSTER_NAME": "cluster-name",
        "VECTOR_INDEX_NAME": "vector_index",
        "VECTOR_DIMENSIONS": 1024,
    }
    values.update(overrides)
    return Settings(**values)


def test_atlas_credentials_are_detected():
    configured = settings()
    assert has_atlas_admin_credentials(configured)
    assert missing_atlas_admin_credentials(configured) == []

    incomplete = settings(ATLAS_PRIVATE_KEY="")
    assert not has_atlas_admin_credentials(incomplete)
    assert missing_atlas_admin_credentials(incomplete) == ["ATLAS_PRIVATE_KEY"]


def test_index_definition_matching_ignores_field_order():
    current = {
        "fields": [
            {"path": "content_type", "type": "filter"},
            {"similarity": "cosine", "numDimensions": 1024, "path": "embeddings", "type": "vector"},
        ]
    }
    desired = {
        "fields": [
            {"type": "vector", "path": "embeddings", "numDimensions": 1024, "similarity": "cosine"},
            {"type": "filter", "path": "content_type"},
        ]
    }

    assert definitions_match(current, desired)


def test_vector_index_payload_uses_brand_database_and_standard_collection():
    payload = build_vector_index_payload(settings(), "brand_essco_bathware")

    assert payload["database"] == "brand_essco_bathware"
    assert payload["collectionName"] == "knowledge_base"
    assert payload["name"] == "vector_index"
    assert payload["type"] == "vectorSearch"
    assert payload["definition"]["fields"][0]["path"] == "embeddings"


@pytest.mark.asyncio
async def test_missing_index_is_manual_without_apply():
    fake_client = FakeAtlasHttpClient(indexes=[])
    atlas = AtlasAdminClient(settings(), client=fake_client)

    check = await atlas.ensure_vector_index("brand_essco_bathware", apply=False)

    assert check.status == "manual"
    assert "missing" in check.detail
    assert fake_client.posts == []


@pytest.mark.asyncio
async def test_missing_index_is_created_with_apply():
    fake_client = FakeAtlasHttpClient(indexes=[])
    atlas = AtlasAdminClient(settings(), client=fake_client)

    check = await atlas.ensure_vector_index("brand_essco_bathware", apply=True)

    assert check.status == "ok"
    assert fake_client.posts[0]["json"]["database"] == "brand_essco_bathware"


@pytest.mark.asyncio
async def test_matching_index_is_left_unchanged():
    desired = build_vector_index_payload(settings(), "brand_essco_bathware")["definition"]
    fake_client = FakeAtlasHttpClient(indexes=[{"name": "vector_index", "definition": desired, "indexID": "idx-1"}])
    atlas = AtlasAdminClient(settings(), client=fake_client)

    check = await atlas.ensure_vector_index("brand_essco_bathware", apply=True)

    assert check.status == "ok"
    assert fake_client.posts == []
    assert fake_client.patches == []


@pytest.mark.asyncio
async def test_changed_index_is_updated_with_apply():
    current = {"fields": [{"type": "vector", "path": "embeddings", "numDimensions": 768, "similarity": "cosine"}]}
    fake_client = FakeAtlasHttpClient(indexes=[{"name": "vector_index", "definition": current, "indexID": "idx-1"}])
    atlas = AtlasAdminClient(settings(), client=fake_client)

    check = await atlas.ensure_vector_index("brand_essco_bathware", apply=True)

    assert check.status == "ok"
    assert fake_client.patches[0]["path"].endswith("/fts/indexes/idx-1")
    assert fake_client.patches[0]["json"]["definition"]["fields"][0]["numDimensions"] == 1024
