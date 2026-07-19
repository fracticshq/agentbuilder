"""Offline unit coverage for the privacy-safe staging-evaluation contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.run_staging_quality import main
from evals.staging_quality_contract import (
    CASE_FIXTURE_PATH,
    REVIEW_RECORDS_PATH,
    FixtureValidationError,
    load_case_fixture,
    load_review_records,
    sanitized_summary,
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v2_contract_accepts_read_only_synthetic_cases_and_provenance_checked_reviews():
    cases = load_case_fixture()
    reviews = load_review_records(cases=cases)

    assert {case.suite for case in cases.cases} == {
        "hybrid_rag",
        "ecommerce",
        "shopify",
        "lalkitab",
        "provider_outage",
        "prompt_injection",
        "tenant_isolation",
    }
    assert all(case.side_effect_mode == "read_only" for case in cases.cases)
    assert reviews.review_policy == {
        "human_review_primary": True,
        "pinned_model_second_opinion": "optional",
        "llm_faithfulness_metrics": "not_claimed",
    }
    assert {review.reviewer_type for review in reviews.reviews} == {"human", "pinned_model"}
    assert all(review.redacted_rationale.startswith("[redacted]") for review in reviews.reviews)


def test_case_contract_rejects_unknown_fields(tmp_path: Path):
    raw_cases = _read_json(CASE_FIXTURE_PATH)
    raw_cases["cases"][0]["unexpected"] = "not_allowed"

    with pytest.raises(FixtureValidationError, match="must contain exactly"):
        load_case_fixture(_write_json(tmp_path / "cases.json", raw_cases))


def test_contract_rejects_unsafe_secret_like_turn_descriptor(tmp_path: Path):
    raw_cases = _read_json(CASE_FIXTURE_PATH)
    raw_cases["cases"][0]["synthetic_turns"][0]["input_descriptor"] = "sk-abcdefghijklmnopqrstuvwxyz123456"

    with pytest.raises(FixtureValidationError, match="unsafe secret-like or identifying value"):
        load_case_fixture(_write_json(tmp_path / "unsafe-cases.json", raw_cases))


def test_review_contract_rejects_unredacted_direct_identifier(tmp_path: Path):
    cases = load_case_fixture()
    raw_reviews = _read_json(REVIEW_RECORDS_PATH)
    raw_reviews["reviews"][0]["redacted_rationale"] = "[redacted] Contact reviewer@example.com for details."

    with pytest.raises(FixtureValidationError, match="unsafe secret-like or identifying value"):
        load_review_records(_write_json(tmp_path / "unsafe-reviews.json", raw_reviews), cases=cases)


def test_sanitized_summary_excludes_turns_and_review_rationales():
    cases = load_case_fixture()
    reviews = load_review_records(cases=cases)
    summary = sanitized_summary(cases, reviews)
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["side_effect_mode"] == "read_only"
    assert "synthetic_turns" not in rendered
    assert "input_descriptor" not in rendered
    assert "redacted_rationale" not in rendered
    assert "provenance" not in rendered
    assert "synthetic_rag_lookup" not in rendered


def test_execute_mode_fails_closed_with_or_without_future_environment_flags(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STAGING_QUALITY_EXECUTE_ENABLED", raising=False)
    monkeypatch.delenv("STAGING_QUALITY_TARGET_ALLOWLIST", raising=False)
    assert main(["--execute"]) == 2

    monkeypatch.setenv("STAGING_QUALITY_EXECUTE_ENABLED", "1")
    monkeypatch.setenv("STAGING_QUALITY_TARGET_ALLOWLIST", "synthetic-external-staging")
    assert main(["--execute"]) == 2
