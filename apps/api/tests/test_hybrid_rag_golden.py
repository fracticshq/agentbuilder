"""Offline golden coverage for the real Hybrid RAG retrieval pipeline."""

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.run_hybrid_rag_golden import build_pipeline, evaluate_fixture, load_fixture, sanitized_report


@pytest.mark.asyncio
async def test_hybrid_rag_golden_fixture_uses_real_pipeline_with_deterministic_backends():
    fixture = load_fixture()

    warranty_case = next(case for case in fixture.cases if case.case_id == "rrf-warranty-ranking")
    warranty_result = await build_pipeline(warranty_case).retrieve(
        warranty_case.query,
        max_chunks=warranty_case.max_chunks,
    )
    assert [chunk.chunk_id for chunk in warranty_result.chunks] == [
        "warranty-coverage",
        "warranty-registration",
        "warranty-general-care",
    ]
    assert warranty_result.retrieval_metadata["status"] == "evidence"

    evaluations = await evaluate_fixture(fixture)
    report = sanitized_report(fixture, evaluations)

    assert {evaluation.case_id: evaluation.chunk_ids for evaluation in evaluations} == {
        "rrf-warranty-ranking": (
            "warranty-coverage",
            "warranty-registration",
            "warranty-general-care",
        ),
        "structured-sku-product-dedup": (
            "product-speaker-mini",
            "product-speaker-main",
        ),
        "healthy-no-evidence": (),
    }
    assert {evaluation.case_id: evaluation.retrieval_status for evaluation in evaluations} == {
        "rrf-warranty-ranking": "evidence",
        "structured-sku-product-dedup": "evidence",
        "healthy-no-evidence": "no_evidence",
    }
    assert report["evidence_gate"]["name"] == "deterministic_claim_support"
    assert report["metrics"] == {"mrr": 1.0, "ndcg_at_k": 1.0, "recall_at_k": 1.0}
    assert report["case_counts"] == {
        "total": 3,
        "ranking_denominator": 2,
        "excluded_no_evidence": 1,
    }

    # A second retrieval reconstructs all chunks, so RRF's in-place score and
    # metadata mutations cannot leak from the first golden evaluation.
    repeated_evaluations = await evaluate_fixture(fixture)
    assert repeated_evaluations == evaluations
