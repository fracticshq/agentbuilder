#!/usr/bin/env python3
"""Run the offline, deterministic Hybrid RAG golden evaluation suite.

The suite calls the production ``RetrievalPipeline`` with static in-memory
vector and BM25 responses.  It deliberately has no database, provider, LLM,
prompt, or network dependency.  ``deterministic_claim_support`` is a curated
retrieval-relevance proxy only; it is not an LLM judge or a claim-faithfulness
measurement of generated answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from retrieval.fusion.rrf import RRFFusion
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import DocumentChunk, RetrievalConfig, RetrievalContext, SearchResult


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "evals" / "cases" / "v1" / "hybrid_rag_golden.json"
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED_RETRIEVAL_STATUSES = {"evidence", "no_evidence"}
REQUIRED_METRIC_FLOORS = {"recall_at_k", "mrr", "ndcg_at_k"}
REQUIRED_CHUNK_FIELDS = {"chunk_id", "doc_id", "content", "score", "content_type", "metadata"}


class FixtureValidationError(ValueError):
    """Raised when the versioned golden fixture is malformed or unsafe to run."""


class GoldenEvaluationFailure(AssertionError):
    """Raised when real pipeline output differs from the declared golden contract."""


@dataclass(frozen=True)
class GoldenCase:
    """One fully validated static retrieval scenario."""

    case_id: str
    query: str
    rrf_k: int
    max_chunks: int
    dedup_enabled: bool
    backend_chunks: Mapping[str, tuple[Mapping[str, Any], ...]]
    expected_retrieval_status: str
    exclude_from_denominators: bool
    qrels: Mapping[str, int]
    expected_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class GoldenFixture:
    """Validated suite-level contract for deterministic retrieval quality."""

    schema_version: str
    suite: str
    metric_k: int
    metric_floors: Mapping[str, float]
    evidence_gate: Mapping[str, str]
    cases: tuple[GoldenCase, ...]


@dataclass(frozen=True)
class CaseEvaluation:
    """In-memory result retained for the API regression test, not JSON output."""

    case_id: str
    retrieval_status: str
    chunk_ids: tuple[str, ...]
    metrics: Mapping[str, float] | None


class StaticSearch:
    """A deterministic async backend that reconstructs chunks for every search."""

    def __init__(self, search_type: str, chunk_specs: Sequence[Mapping[str, Any]]):
        self.search_type = search_type
        self._chunk_specs = tuple(chunk_specs)

    async def search(self, query: str, **_kwargs: Any) -> SearchResult:
        # RRF writes scores and metadata into its chunk instances.  Rebuild
        # them on each call so one case/run cannot contaminate another.
        chunks = [_document_chunk_from_spec(spec) for spec in self._chunk_specs]
        return SearchResult(
            chunks=chunks,
            total_found=len(chunks),
            query=query,
            search_type=self.search_type,
        )


def _require_exact_object(value: Any, fields: set[str], *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FixtureValidationError(f"{context} must be an object")
    if set(value) != fields:
        raise FixtureValidationError(f"{context} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _require_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{context} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FixtureValidationError(f"{context} must be a positive integer")
    return value


def _validate_metric_floors(value: Any, *, context: str) -> Mapping[str, float]:
    raw_floors = _require_exact_object(value, REQUIRED_METRIC_FLOORS, context=context)
    floors: dict[str, float] = {}
    for metric_name, raw_floor in raw_floors.items():
        if isinstance(raw_floor, bool) or not isinstance(raw_floor, (int, float)):
            raise FixtureValidationError(f"{context}.{metric_name} must be a number")
        floor = float(raw_floor)
        if not 0.0 <= floor <= 1.0:
            raise FixtureValidationError(f"{context}.{metric_name} must be between 0 and 1")
        floors[metric_name] = floor
    return floors


def _validate_chunk_spec(value: Any, *, context: str) -> Mapping[str, Any]:
    raw_chunk = _require_exact_object(value, REQUIRED_CHUNK_FIELDS, context=context)
    chunk_id = _require_string(raw_chunk["chunk_id"], context=f"{context}.chunk_id")
    _require_string(raw_chunk["doc_id"], context=f"{context}.doc_id")
    _require_string(raw_chunk["content"], context=f"{context}.content")
    if isinstance(raw_chunk["score"], bool) or not isinstance(raw_chunk["score"], (int, float)):
        raise FixtureValidationError(f"{context}.score must be a number")
    _require_string(raw_chunk["content_type"], context=f"{context}.content_type")
    if not isinstance(raw_chunk["metadata"], dict):
        raise FixtureValidationError(f"{context}.metadata must be an object")

    # Deep-copy JSON values before RRF appends fusion metadata to chunks.
    return {
        "chunk_id": chunk_id,
        "doc_id": raw_chunk["doc_id"].strip(),
        "content": raw_chunk["content"].strip(),
        "score": float(raw_chunk["score"]),
        "content_type": raw_chunk["content_type"].strip(),
        "metadata": json.loads(json.dumps(raw_chunk["metadata"], sort_keys=True)),
    }


def _validate_case(value: Any, *, index: int, metric_k: int) -> GoldenCase:
    context = f"cases[{index}]"
    raw_case = _require_exact_object(
        value,
        {
            "id",
            "query",
            "config",
            "backends",
            "expected_retrieval_status",
            "ranking",
        },
        context=context,
    )
    case_id = _require_string(raw_case["id"], context=f"{context}.id")
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise FixtureValidationError(f"{context}.id must be lower-kebab-case: {case_id}")
    query = _require_string(raw_case["query"], context=f"{context}.query")

    raw_config = _require_exact_object(
        raw_case["config"], {"rrf_k", "max_chunks", "dedup_enabled"}, context=f"{context}.config"
    )
    rrf_k = _require_positive_int(raw_config["rrf_k"], context=f"{context}.config.rrf_k")
    max_chunks = _require_positive_int(raw_config["max_chunks"], context=f"{context}.config.max_chunks")
    if max_chunks < metric_k:
        raise FixtureValidationError(f"{context}.config.max_chunks must be at least metric_k")
    if not isinstance(raw_config["dedup_enabled"], bool):
        raise FixtureValidationError(f"{context}.config.dedup_enabled must be a boolean")

    raw_backends = _require_exact_object(raw_case["backends"], {"vector", "bm25"}, context=f"{context}.backends")
    backend_chunks: dict[str, tuple[Mapping[str, Any], ...]] = {}
    available_chunk_ids: set[str] = set()
    for backend_name in ("vector", "bm25"):
        raw_chunks = raw_backends[backend_name]
        if not isinstance(raw_chunks, list):
            raise FixtureValidationError(f"{context}.backends.{backend_name} must be an array")
        chunks = tuple(
            _validate_chunk_spec(chunk, context=f"{context}.backends.{backend_name}[{chunk_index}]")
            for chunk_index, chunk in enumerate(raw_chunks)
        )
        backend_chunks[backend_name] = chunks
        available_chunk_ids.update(chunk["chunk_id"] for chunk in chunks)

    expected_status = _require_string(
        raw_case["expected_retrieval_status"], context=f"{context}.expected_retrieval_status"
    )
    if expected_status not in EXPECTED_RETRIEVAL_STATUSES:
        raise FixtureValidationError(f"{context}.expected_retrieval_status must be evidence or no_evidence")

    raw_ranking = _require_exact_object(
        raw_case["ranking"], {"exclude_from_denominators", "qrels", "expected_chunk_ids"}, context=f"{context}.ranking"
    )
    excluded = raw_ranking["exclude_from_denominators"]
    if not isinstance(excluded, bool):
        raise FixtureValidationError(f"{context}.ranking.exclude_from_denominators must be a boolean")
    if not isinstance(raw_ranking["qrels"], dict):
        raise FixtureValidationError(f"{context}.ranking.qrels must be an object")
    qrels: dict[str, int] = {}
    for chunk_id, grade in raw_ranking["qrels"].items():
        if not isinstance(chunk_id, str) or not chunk_id:
            raise FixtureValidationError(f"{context}.ranking.qrels keys must be non-empty chunk IDs")
        if chunk_id not in available_chunk_ids:
            raise FixtureValidationError(f"{context}.ranking.qrels references unknown chunk_id: {chunk_id}")
        if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
            raise FixtureValidationError(f"{context}.ranking.qrels.{chunk_id} must be an integer between 0 and 3")
        qrels[chunk_id] = grade

    raw_expected_chunk_ids = raw_ranking["expected_chunk_ids"]
    if not isinstance(raw_expected_chunk_ids, list) or not all(
        isinstance(chunk_id, str) and chunk_id for chunk_id in raw_expected_chunk_ids
    ):
        raise FixtureValidationError(f"{context}.ranking.expected_chunk_ids must be an array of non-empty strings")
    expected_chunk_ids = tuple(raw_expected_chunk_ids)
    if len(expected_chunk_ids) != len(set(expected_chunk_ids)):
        raise FixtureValidationError(f"{context}.ranking.expected_chunk_ids must not contain duplicates")
    if len(expected_chunk_ids) > max_chunks:
        raise FixtureValidationError(f"{context}.ranking.expected_chunk_ids cannot exceed config.max_chunks")
    unknown_expected_ids = set(expected_chunk_ids) - available_chunk_ids
    if unknown_expected_ids:
        raise FixtureValidationError(
            f"{context}.ranking.expected_chunk_ids references unknown chunk_id(s): {', '.join(sorted(unknown_expected_ids))}"
        )

    relevant_count = sum(grade > 0 for grade in qrels.values())
    if excluded:
        if (
            expected_status != "no_evidence"
            or qrels
            or expected_chunk_ids
            or any(backend_chunks.values())
        ):
            raise FixtureValidationError(
                f"{context} excluded cases must be healthy no_evidence with empty backends, qrels, and expected chunks"
            )
    elif expected_status != "evidence" or relevant_count == 0:
        raise FixtureValidationError(f"{context} ranking cases must have evidence and at least one relevant qrel")

    return GoldenCase(
        case_id=case_id,
        query=query,
        rrf_k=rrf_k,
        max_chunks=max_chunks,
        dedup_enabled=raw_config["dedup_enabled"],
        backend_chunks=backend_chunks,
        expected_retrieval_status=expected_status,
        exclude_from_denominators=excluded,
        qrels=qrels,
        expected_chunk_ids=expected_chunk_ids,
    )


def load_fixture(fixture_path: Path = FIXTURE_PATH) -> GoldenFixture:
    """Load and strictly validate the versioned Hybrid RAG fixture."""
    try:
        raw_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureValidationError(f"fixture does not exist: {fixture_path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureValidationError(f"fixture is not valid JSON: {fixture_path}: {exc.msg}") from exc

    raw_fixture = _require_exact_object(
        raw_fixture,
        {"schema_version", "suite", "metric_k", "metric_floors", "evidence_gate", "cases"},
        context="fixture",
    )
    schema_version = _require_string(raw_fixture["schema_version"], context="fixture.schema_version")
    if schema_version != "1.0":
        raise FixtureValidationError("fixture.schema_version must be 1.0")
    suite = _require_string(raw_fixture["suite"], context="fixture.suite")
    if suite != "hybrid_rag_golden":
        raise FixtureValidationError("fixture.suite must be hybrid_rag_golden")
    metric_k = _require_positive_int(raw_fixture["metric_k"], context="fixture.metric_k")
    metric_floors = _validate_metric_floors(raw_fixture["metric_floors"], context="fixture.metric_floors")

    evidence_gate = _require_exact_object(
        raw_fixture["evidence_gate"], {"name", "kind", "description"}, context="fixture.evidence_gate"
    )
    evidence_gate = {
        field: _require_string(evidence_gate[field], context=f"fixture.evidence_gate.{field}")
        for field in ("name", "kind", "description")
    }
    if evidence_gate["name"] != "deterministic_claim_support":
        raise FixtureValidationError("fixture.evidence_gate.name must be deterministic_claim_support")
    if evidence_gate["kind"] != "deterministic_proxy":
        raise FixtureValidationError("fixture.evidence_gate.kind must be deterministic_proxy")

    raw_cases = raw_fixture["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) != 3:
        raise FixtureValidationError("fixture.cases must contain exactly three golden cases")
    cases = tuple(_validate_case(case, index=index, metric_k=metric_k) for index, case in enumerate(raw_cases))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise FixtureValidationError("fixture.cases must not contain duplicate case IDs")

    expected_case_ids = {"rrf-warranty-ranking", "structured-sku-product-dedup", "healthy-no-evidence"}
    if set(case_ids) != expected_case_ids:
        raise FixtureValidationError("fixture.cases must contain the required v1 golden case IDs")
    if sum(case.exclude_from_denominators for case in cases) != 1:
        raise FixtureValidationError("fixture.cases must contain exactly one denominator-excluded case")

    return GoldenFixture(
        schema_version=schema_version,
        suite=suite,
        metric_k=metric_k,
        metric_floors=metric_floors,
        evidence_gate=evidence_gate,
        cases=cases,
    )


def _document_chunk_from_spec(spec: Mapping[str, Any]) -> DocumentChunk:
    """Build a fresh model because production RRF mutates score and metadata."""
    return DocumentChunk(
        chunk_id=spec["chunk_id"],
        doc_id=spec["doc_id"],
        content=spec["content"],
        score=spec["score"],
        content_type=spec["content_type"],
        metadata=json.loads(json.dumps(spec["metadata"], sort_keys=True)),
    )


def build_pipeline(case: GoldenCase) -> RetrievalPipeline:
    """Construct a real pipeline wired only to static in-memory search backends."""
    pipeline = RetrievalPipeline.__new__(RetrievalPipeline)
    pipeline.config = RetrievalConfig(
        vector_enabled=True,
        bm25_enabled=True,
        vector_top_k=case.max_chunks,
        bm25_top_k=case.max_chunks,
        rrf_k=case.rrf_k,
        rerank_enabled=False,
        dedup_enabled=case.dedup_enabled,
        brand_boost_enabled=False,
        page_boost_enabled=False,
    )
    pipeline.vector_search = StaticSearch("vector", case.backend_chunks["vector"])
    pipeline.bm25_search = StaticSearch("bm25", case.backend_chunks["bm25"])
    pipeline.rrf = RRFFusion(k=case.rrf_k)
    pipeline.reranker = None
    pipeline.brand_boost = None
    pipeline.page_boost = None
    pipeline.verticals = set()
    return pipeline


def recall_at_k(retrieved_chunk_ids: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    """Compute binary Recall@k from retrieved chunk IDs and graded qrels."""
    relevant = {chunk_id for chunk_id, grade in qrels.items() if grade > 0}
    if not relevant:
        raise ValueError("Recall@k is undefined without at least one relevant qrel")
    return len(relevant.intersection(retrieved_chunk_ids[:k])) / len(relevant)


def mean_reciprocal_rank(retrieved_chunk_ids: Sequence[str], qrels: Mapping[str, int]) -> float:
    """Compute reciprocal rank of the first positive-grade qrel."""
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if qrels.get(chunk_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_chunk_ids: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    """Compute nDCG@k using ``2**grade - 1`` gain from the fixture's qrels."""
    def discounted_gain(grades: Iterable[int]) -> float:
        return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))

    observed = discounted_gain(qrels.get(chunk_id, 0) for chunk_id in retrieved_chunk_ids[:k])
    ideal = discounted_gain(sorted(qrels.values(), reverse=True)[:k])
    if ideal == 0.0:
        raise ValueError("nDCG@k is undefined without at least one positive qrel")
    return observed / ideal


def _case_metrics(case: GoldenCase, chunk_ids: Sequence[str], metric_k: int) -> Mapping[str, float] | None:
    if case.exclude_from_denominators:
        return None
    return {
        "recall_at_k": recall_at_k(chunk_ids, case.qrels, metric_k),
        "mrr": mean_reciprocal_rank(chunk_ids, case.qrels),
        "ndcg_at_k": ndcg_at_k(chunk_ids, case.qrels, metric_k),
    }


async def evaluate_case(case: GoldenCase, *, metric_k: int) -> CaseEvaluation:
    """Retrieve one case through the actual pipeline and enforce its exact rank."""
    result: RetrievalContext = await build_pipeline(case).retrieve(case.query, max_chunks=case.max_chunks)
    retrieval_status = result.retrieval_metadata.get("status")
    if retrieval_status != case.expected_retrieval_status:
        raise GoldenEvaluationFailure(
            f"{case.case_id}: expected retrieval status {case.expected_retrieval_status!r}, got {retrieval_status!r}"
        )

    chunk_ids = tuple(chunk.chunk_id for chunk in result.chunks)
    if chunk_ids != case.expected_chunk_ids:
        raise GoldenEvaluationFailure(
            f"{case.case_id}: expected chunk ranking {list(case.expected_chunk_ids)!r}, got {list(chunk_ids)!r}"
        )

    return CaseEvaluation(
        case_id=case.case_id,
        retrieval_status=retrieval_status,
        chunk_ids=chunk_ids,
        metrics=_case_metrics(case, chunk_ids, metric_k),
    )


async def evaluate_fixture(fixture: GoldenFixture) -> tuple[CaseEvaluation, ...]:
    """Evaluate all golden cases serially for stable, fixture-defined ranking order."""
    evaluations = []
    for case in fixture.cases:
        evaluations.append(await evaluate_case(case, metric_k=fixture.metric_k))
    evaluations = tuple(evaluations)
    ranking_evaluations = [evaluation for evaluation in evaluations if evaluation.metrics is not None]
    if not ranking_evaluations:
        raise GoldenEvaluationFailure("fixture has no ranking cases")

    aggregate_metrics = {
        metric_name: sum(evaluation.metrics[metric_name] for evaluation in ranking_evaluations) / len(ranking_evaluations)
        for metric_name in REQUIRED_METRIC_FLOORS
    }
    failed_floors = {
        metric_name: (aggregate_metrics[metric_name], fixture.metric_floors[metric_name])
        for metric_name in REQUIRED_METRIC_FLOORS
        if aggregate_metrics[metric_name] < fixture.metric_floors[metric_name]
    }
    if failed_floors:
        details = ", ".join(
            f"{name}={actual:.6f} < floor {floor:.6f}"
            for name, (actual, floor) in sorted(failed_floors.items())
        )
        raise GoldenEvaluationFailure(f"metric floor failure: {details}")
    return evaluations


def sanitized_report(fixture: GoldenFixture, evaluations: Sequence[CaseEvaluation]) -> Mapping[str, Any]:
    """Return only suite IDs, status counts, and aggregate metrics—never source text."""
    ranking_evaluations = [evaluation for evaluation in evaluations if evaluation.metrics is not None]
    metrics = {
        metric_name: sum(evaluation.metrics[metric_name] for evaluation in ranking_evaluations) / len(ranking_evaluations)
        for metric_name in sorted(REQUIRED_METRIC_FLOORS)
    }
    status_counts: dict[str, int] = {}
    for evaluation in evaluations:
        status_counts[evaluation.retrieval_status] = status_counts.get(evaluation.retrieval_status, 0) + 1

    return {
        "suite": fixture.suite,
        "schema_version": fixture.schema_version,
        "evidence_gate": dict(fixture.evidence_gate),
        "metric_k": fixture.metric_k,
        "metric_floors": dict(fixture.metric_floors),
        "metrics": metrics,
        "case_counts": {
            "total": len(evaluations),
            "ranking_denominator": len(ranking_evaluations),
            "excluded_no_evidence": len(evaluations) - len(ranking_evaluations),
        },
        "retrieval_status_counts": status_counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-output",
        type=Path,
        help="write the sanitized aggregate metrics report to this path",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the fixture without invoking the retrieval pipeline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        fixture = load_fixture()
        if args.validate_only:
            print(f"Validated {len(fixture.cases)} Hybrid RAG golden case(s).")
            return 0
        evaluations = asyncio.run(evaluate_fixture(fixture))
        report = sanitized_report(fixture, evaluations)
    except (FixtureValidationError, GoldenEvaluationFailure, ValueError) as exc:
        print(f"Hybrid RAG golden evaluation failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Hybrid RAG golden evaluation passed: "
        f"Recall@{report['metric_k']}={report['metrics']['recall_at_k']:.3f}, "
        f"MRR={report['metrics']['mrr']:.3f}, "
        f"nDCG@{report['metric_k']}={report['metrics']['ndcg_at_k']:.3f}; "
        f"{report['case_counts']['excluded_no_evidence']} healthy no-evidence case(s) excluded.",
        flush=True,
    )
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote sanitized metrics to {args.json_output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
