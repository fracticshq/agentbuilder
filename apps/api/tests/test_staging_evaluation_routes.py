"""Offline API coverage for protected staging-quality evidence routes."""

from __future__ import annotations

import socket
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import require_dashboard_access
from app.auth.models import User, UserRole
from app.dependencies import get_settings
from app.services.agent_api_keys import AgentApiKeyContext
from app.services.evaluation_redaction import load_validated_contract


class _FindCollection:
    def __init__(self, rows):
        self.rows = rows

    async def find_one(self, query, *_args, **_kwargs):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return deepcopy(row)
        return None


class _SystemDb:
    def __init__(self):
        self.agents = _FindCollection([
            {"id": "agent-1", "brand_id": "brand-1", "brand_slug": "brand-one"},
        ])
        self.brands = _FindCollection([
            {"id": "brand-1", "slug": "brand-one"},
            {"id": "brand-2", "slug": "brand-two"},
        ])


class _Store:
    def __init__(self):
        self.runs = {}
        self.calls = []

    async def create_run(self, **kwargs):
        self.calls.append(("create", kwargs))
        run = {
            "id": "run-1",
            "schema_version": "staging-quality-run/v1",
            "brand_id": kwargs["brand_id"],
            "agent_id": kwargs["agent_id"],
            "target_profile": kwargs["target_profile"],
            "report": kwargs["report"],
            "reviews": [],
        }
        self.runs[run["id"]] = run
        return deepcopy(run)

    async def list_runs(self, *, brand_id, **_kwargs):
        return [deepcopy(run) for run in self.runs.values() if run["brand_id"] == brand_id]

    async def get_run(self, *, brand_id, run_id, **_kwargs):
        run = self.runs.get(run_id)
        return deepcopy(run) if run and run["brand_id"] == brand_id else None

    async def has_human_review(self, *, brand_id, run_id, case_id, **_kwargs):
        run = self.runs.get(run_id)
        return bool(run and run["brand_id"] == brand_id and any(
            review["case_id"] == case_id and review["reviewer_type"] == "human"
            for review in run["reviews"]
        ))

    async def append_review(self, *, brand_id, run_id, review, submitted_by, **_kwargs):
        run = self.runs.get(run_id)
        if not run or run["brand_id"] != brand_id:
            return None
        run["reviews"].append({**review, "submitted_by": submitted_by})
        return deepcopy(run)


def _settings(*, enabled=True):
    from app.config import Settings

    return Settings(
        SECRET_KEY="test-secret",
        EVAL_STAGING_ENABLED=enabled,
        EVAL_STAGING_TARGET_ALLOWLIST="synthetic-external-staging" if enabled else "",
        EVAL_STAGING_MAX_CASES=25,
        EVAL_RESULT_TTL_SECONDS=3600,
    )


def _operator(*, brands=None):
    return User(
        id="user-1",
        email="operator@example.com",
        username="operator",
        password_hash="not-a-secret",
        role=UserRole.OPERATOR,
        brands=brands or ["brand-1"],
    )


def _summary():
    from evals.staging_quality_contract import sanitized_summary

    cases, reviews = load_validated_contract()
    return sanitized_summary(cases, reviews)


def _review_payload(reviewer_type):
    cases, records = load_validated_contract()
    record = next(item for item in records.reviews if item.reviewer_type == reviewer_type)
    return {
        "case_id": record.case_id,
        "reviewer_type": record.reviewer_type,
        "reviewer_ref": record.reviewer_ref,
        "dimensions": [dict(item) for item in record.dimensions],
        "outcome": record.outcome,
        "redacted_rationale": record.redacted_rationale,
        "provenance": dict(record.provenance),
    }


@pytest.fixture
def client(monkeypatch):
    from app.api.v1.admin import evaluations as module

    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1/admin")
    store = _Store()
    monkeypatch.setattr(module.connection_manager, "get_system_db", lambda: _SystemDb())
    monkeypatch.setattr(module, "_store", lambda _settings: store)

    async def authenticate(_service, _key, *, required_scope):
        assert required_scope == "evaluations:write"
        return AgentApiKeyContext(
            id="key-1",
            key_id="ab_agent_v1_test",
            scopes={"evaluations:write"},
            agent_id="agent-1",
            brand_id="brand-1",
        )

    monkeypatch.setattr(module.AgentApiKeyService, "authenticate", authenticate)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[require_dashboard_access] = _operator
    return TestClient(app), store, app


def _ingest_body():
    return {
        "agent_id": "agent-1",
        "brand_id": "brand-1",
        "target_profile": {
            "profile": "synthetic-external-staging",
            "data_classification": "synthetic_only",
            "access_mode": "read_only",
        },
        "report": _summary(),
    }


def test_disabled_flag_hides_ingestion_surface(client):
    test_client, _, app = client
    app.dependency_overrides[get_settings] = lambda: _settings(enabled=False)

    response = test_client.post("/api/v1/admin/evaluations/runs", json=_ingest_body(), headers={"X-Agent-API-Key": "ignored"})

    assert response.status_code == 404


def test_allowed_report_persists_no_store_without_network_or_model_calls(client, monkeypatch):
    test_client, store, _ = client

    def no_network(*_args, **_kwargs):
        raise AssertionError("staging evaluation ingestion must not make network calls")

    monkeypatch.setattr(socket, "create_connection", no_network)
    response = test_client.post("/api/v1/admin/evaluations/runs", json=_ingest_body(), headers={"X-Agent-API-Key": "ignored"})

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["run"]["report"]["case_count"] == 7
    assert store.calls[0][1]["agent_id"] == "agent-1"


def test_unsafe_raw_evaluation_payload_is_rejected_before_persistence(client):
    test_client, store, _ = client
    body = _ingest_body()
    body["report"]["raw_turns"] = [{"message": "customer data"}]

    response = test_client.post("/api/v1/admin/evaluations/runs", json=body, headers={"X-Agent-API-Key": "ignored"})

    assert response.status_code == 422
    assert store.calls == []


def test_dashboard_brand_isolation_and_review_provenance(client):
    test_client, _, app = client
    created = test_client.post("/api/v1/admin/evaluations/runs", json=_ingest_body(), headers={"X-Agent-API-Key": "ignored"})
    assert created.status_code == 201

    app.dependency_overrides[require_dashboard_access] = lambda: _operator(brands=["brand-2"])
    isolated = test_client.get("/api/v1/admin/brands/brand-1/evaluations/runs/run-1")
    assert isolated.status_code == 404

    app.dependency_overrides[require_dashboard_access] = _operator
    human = test_client.post(
        "/api/v1/admin/brands/brand-1/evaluations/runs/run-1/reviews",
        json=_review_payload("human"),
    )
    assert human.status_code == 200
    assert human.headers["cache-control"] == "no-store"
    stored_human = human.json()["run"]["reviews"][0]
    assert stored_human["reviewer_type"] == "human"
    assert stored_human["reviewer_ref"].startswith("dashboard-reviewer-")
    assert stored_human["provenance"]["pinned_model_sha256"] is None

    pinned = test_client.post(
        "/api/v1/admin/brands/brand-1/evaluations/runs/run-1/reviews",
        json=_review_payload("pinned_model"),
    )
    assert pinned.status_code == 200
    stored_pinned = pinned.json()["run"]["reviews"][1]
    assert stored_pinned["reviewer_type"] == "pinned_model"
    assert stored_pinned["provenance"]["pinned_model_sha256"]
