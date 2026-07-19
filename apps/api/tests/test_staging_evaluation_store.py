"""Offline coverage for redacted staging-evaluation persistence boundaries."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.quality_evaluation_store import (
    QUALITY_EVALUATION_RUNS_COLLECTION,
    QualityEvaluationStore,
)


class _Result:
    def __init__(self, *, matched_count: int = 0, deleted_count: int = 0):
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        return _Cursor(sorted(self.rows, key=lambda row: row.get(key), reverse=direction < 0))

    async def to_list(self, *, length):
        return deepcopy(self.rows[:length])


class _Collection:
    def __init__(self):
        self.rows = []
        self.indexes = []

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    async def insert_one(self, row):
        self.rows.append(deepcopy(row))

    def find(self, query):
        return _Cursor([row for row in self.rows if _matches(row, query)])

    async def find_one(self, query, *_args, **_kwargs):
        for row in self.rows:
            if _matches(row, query):
                return deepcopy(row)
        return None

    async def update_one(self, query, update):
        for row in self.rows:
            if _matches(row, query):
                row.setdefault("reviews", []).append(deepcopy(update["$push"]["reviews"]))
                return _Result(matched_count=1)
        return _Result()

    async def delete_many(self, query):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return _Result(deleted_count=before - len(self.rows))


class _BrandDb:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        assert name == QUALITY_EVALUATION_RUNS_COLLECTION
        return self.collection


def _matches(row, query):
    for key, expected in query.items():
        if key == "reviews" and "$elemMatch" in expected:
            if not any(_matches(review, expected["$elemMatch"]) for review in row.get("reviews", [])):
                return False
            continue
        if row.get(key) != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_store_is_brand_scoped_and_creates_ttl_indexes(monkeypatch):
    from app.services import quality_evaluation_store as store_module

    first = _Collection()
    second = _Collection()
    databases = {"brand-one": _BrandDb(first), "brand-two": _BrandDb(second)}
    monkeypatch.setattr(store_module.connection_manager, "get_brand_db", lambda slug: databases[slug])
    store = QualityEvaluationStore(result_ttl_seconds=3600)

    created = await store.create_run(
        brand_id="brand-1",
        brand_slug="brand-one",
        agent_id="agent-1",
        target_profile={"profile": "synthetic-external-staging", "data_classification": "synthetic_only", "access_mode": "read_only"},
        report={"schema_version": "staging-quality-summary/v2"},
        ingested_by_key_id="ab_agent_v1_test",
    )

    assert created["brand_id"] == "brand-1"
    assert first.rows[0]["agent_id"] == "agent-1"
    assert first.rows[0]["ingested_by_key_id"] == "ab_agent_v1_test"
    assert any(index[1].get("expireAfterSeconds") == 0 for index in first.indexes)
    assert await store.get_run(
        brand_id="brand-2",
        brand_slug="brand-one",
        run_id=created["id"],
    ) is None
    assert await store.list_runs(brand_id="brand-2", brand_slug="brand-two") == []


@pytest.mark.asyncio
async def test_persisted_reviews_do_not_mutate_run_ownership(monkeypatch):
    from app.services import quality_evaluation_store as store_module

    collection = _Collection()
    monkeypatch.setattr(store_module.connection_manager, "get_brand_db", lambda _slug: _BrandDb(collection))
    store = QualityEvaluationStore(result_ttl_seconds=3600)
    created = await store.create_run(
        brand_id="brand-1",
        brand_slug="brand-one",
        agent_id="agent-1",
        target_profile={"profile": "synthetic-external-staging", "data_classification": "synthetic_only", "access_mode": "read_only"},
        report={"schema_version": "staging-quality-summary/v2"},
        ingested_by_key_id="ab_agent_v1_test",
    )
    review = {
        "id": "review-test",
        "case_id": "hybrid-rag-public-evidence",
        "reviewer_type": "human",
        "reviewer_ref": "dashboard-reviewer-aaaaaaaaaaaaaaaaaaaaaaaa",
        "dimensions": [{"name": "expected_behavior", "outcome": "pass"}],
        "outcome": "pass",
        "redacted_rationale": "[redacted] public_invariants_only",
        "provenance": {},
    }

    updated = await store.append_review(
        brand_id="brand-1",
        brand_slug="brand-one",
        run_id=created["id"],
        review=review,
        submitted_by="dashboard-reviewer-aaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert updated["brand_id"] == "brand-1"
    assert updated["agent_id"] == "agent-1"
    assert updated["reviews"][0]["reviewer_type"] == "human"
    assert await store.has_human_review(
        brand_id="brand-1",
        brand_slug="brand-one",
        run_id=created["id"],
        case_id="hybrid-rag-public-evidence",
    ) is True


@pytest.mark.asyncio
async def test_privacy_retention_includes_staging_quality_results(monkeypatch):
    from app.services import privacy_lifecycle_service as privacy_module

    class _RetentionCollection:
        def __init__(self, deleted_count):
            self.deleted_count = deleted_count
            self.queries = []

        async def delete_many(self, query):
            self.queries.append(query)
            return _Result(deleted_count=self.deleted_count)

    collections = {
        "conversations": _RetentionCollection(1),
        "short_term_summaries": _RetentionCollection(1),
        "episodic_memory": _RetentionCollection(1),
        "activity_events": _RetentionCollection(1),
        "observability_events": _RetentionCollection(1),
        "quality_evaluation_runs": _RetentionCollection(2),
    }

    class _RetentionDb:
        def __getitem__(self, name):
            return collections[name]

    service = privacy_module.PrivacyLifecycleService.__new__(privacy_module.PrivacyLifecycleService)
    service.settings = SimpleNamespace(PRIVACY_DEFAULT_RETENTION_DAYS=90)
    monkeypatch.setattr(privacy_module.connection_manager, "get_brand_db", lambda _slug: _RetentionDb())

    result = await service.apply_retention_policy(
        brand_id="brand-1",
        brand_slug="brand-one",
        retention_days=30,
    )

    assert result["deleted"]["quality_evaluation_runs"] == 2
    assert "created_at" in collections["quality_evaluation_runs"].queries[0]
