"""Public response metadata normalisation and redaction helpers.

This boundary converts untrusted tool/retrieval metadata into bounded citation,
product, dealer, and health objects safe for API/SSE delivery.  It deliberately
does not know about message orchestration or persistence.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import structlog

logger = structlog.get_logger(__name__)

_SENSITIVE_DATA_PATTERNS = [
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*\S+", re.IGNORECASE),
]
_MAX_PUBLIC_CITATIONS = 5
_PUBLIC_RETRIEVAL_STATUSES = {"evidence", "no_evidence", "degraded", "error"}
_PUBLIC_RETRIEVAL_REASONS = {"partial_backend_failure", "no_search_backend_succeeded", "pipeline_error", "retrieval_error", "retrieval_unavailable"}
_PUBLIC_RETRIEVAL_BACKEND_STATUSES = {"success", "unavailable", "error", "disabled"}
_PUBLIC_RETRIEVAL_BACKEND_REASONS = {"authentication_failed", "backend_unavailable", "collection_unavailable", "backend_error"}
_PUBLIC_RETRIEVAL_BACKENDS = {"vector", "bm25", "catalog"}


def sanitize_for_json(data: Any) -> Any:
    """Convert non-JSON values to strings while avoiding raw serialization errors."""
    try:
        return json.loads(json.dumps(data, default=str))
    except (TypeError, ValueError, OverflowError):
        return {} if isinstance(data, dict) else [] if isinstance(data, list) else None


def _safe_citation_text(value: Any, *, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized or any(pattern.search(normalized) for pattern in _SENSITIVE_DATA_PATTERNS):
        return None
    return normalized[:limit] or None


def _safe_citation_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return None
    if len(normalized) > 2_048 or any(pattern.search(normalized) for pattern in _SENSITIVE_DATA_PATTERNS):
        return None
    return normalized


def _normalized_citation_confidence(value: Any, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    if not math.isfinite(confidence):
        confidence = default
    return min(1.0, max(0.0, confidence))


def _citation_from_metadata(value: Any, *, default_confidence: float) -> Optional[dict]:
    if isinstance(value, str):
        raw_doc_id = raw_title = value
        raw_url = raw_snippet = None
        raw_confidence = default_confidence
    elif isinstance(value, dict):
        raw_doc_id = value.get("doc_id") or value.get("source_id") or value.get("id") or value.get("title")
        raw_title = value.get("title") or value.get("document_title") or value.get("name") or raw_doc_id
        raw_url = value.get("url") or value.get("source_url") or value.get("document_url")
        raw_snippet = value.get("snippet") or value.get("excerpt") or value.get("summary")
        raw_confidence = value.get("confidence", default_confidence)
    else:
        return None
    doc_id = _safe_citation_text(raw_doc_id, limit=128)
    if not doc_id:
        return None
    return {
        "doc_id": doc_id,
        "title": _safe_citation_text(raw_title, limit=256) or doc_id,
        "url": _safe_citation_url(raw_url),
        "snippet": _safe_citation_text(raw_snippet, limit=300),
        "confidence": _normalized_citation_confidence(raw_confidence, default=default_confidence),
    }


def _merge_citation(existing: dict, candidate: dict) -> dict:
    merged = dict(existing)
    if (not merged.get("title") or merged.get("title") == merged.get("doc_id")) and candidate.get("title"):
        merged["title"] = candidate["title"]
    for key in ("url", "snippet"):
        if not merged.get(key) and candidate.get(key):
            merged[key] = candidate[key]
    merged["confidence"] = max(
        _normalized_citation_confidence(merged.get("confidence"), default=0.0),
        _normalized_citation_confidence(candidate.get("confidence"), default=0.0),
    )
    return merged


def _safe_retrieval_health(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status not in _PUBLIC_RETRIEVAL_STATUSES:
        return None
    reason = value.get("reason")
    if reason not in _PUBLIC_RETRIEVAL_REASONS:
        reason = "retrieval_error" if status == "error" else "partial_backend_failure" if status == "degraded" else None
    backend_status: dict[str, dict[str, str]] = {}
    raw_backend_status = value.get("backend_status")
    if isinstance(raw_backend_status, dict):
        for backend, details in raw_backend_status.items():
            if backend not in _PUBLIC_RETRIEVAL_BACKENDS or not isinstance(details, dict):
                continue
            backend_state = details.get("status")
            if backend_state not in _PUBLIC_RETRIEVAL_BACKEND_STATUSES:
                continue
            safe_details = {"status": backend_state}
            backend_reason = details.get("reason")
            if backend_reason in _PUBLIC_RETRIEVAL_BACKEND_REASONS:
                safe_details["reason"] = backend_reason
            backend_status[backend] = safe_details
    return {
        "status": status,
        "reason": reason,
        "backend_status": backend_status,
        "successful_backends": [name for name, details in backend_status.items() if details["status"] == "success"],
        "failed_backends": [name for name, details in backend_status.items() if details["status"] in {"error", "unavailable"}],
    }


def _retrieval_health_from_tool_results(tool_results: Any) -> Optional[dict]:
    if not isinstance(tool_results, dict):
        return None
    health_records = []
    for tool_result in tool_results.values():
        metadata = getattr(tool_result, "metadata", None)
        if isinstance(metadata, dict):
            health = _safe_retrieval_health(metadata.get("retrieval"))
            if health:
                health_records.append(health)
    if not health_records:
        return None
    if len(health_records) == 1:
        return health_records[0]
    statuses = [record["status"] for record in health_records]
    if "error" in statuses and any(status != "error" for status in statuses):
        status, reason = "degraded", "partial_backend_failure"
    elif "error" in statuses:
        status = "error"
        reason = next(record["reason"] for record in health_records if record["status"] == "error")
    elif "degraded" in statuses:
        status, reason = "degraded", "partial_backend_failure"
    elif "evidence" in statuses:
        status, reason = "evidence", None
    else:
        status, reason = "no_evidence", None
    severity = {"success": 0, "disabled": 1, "unavailable": 2, "error": 3}
    backend_status: dict[str, dict[str, str]] = {}
    for record in health_records:
        for backend, details in record["backend_status"].items():
            previous = backend_status.get(backend)
            if previous and severity[previous["status"]] >= severity[details["status"]]:
                continue
            backend_status[backend] = dict(details)
    return {
        "status": status,
        "reason": reason,
        "backend_status": backend_status,
        "successful_backends": [name for name, details in backend_status.items() if details["status"] == "success"],
        "failed_backends": [name for name, details in backend_status.items() if details["status"] in {"error", "unavailable"}],
    }


def _response_retrieval_health(tool_results: Any, agent_metadata: Any = None) -> Optional[dict]:
    return _retrieval_health_from_tool_results(tool_results) or (
        _safe_retrieval_health(agent_metadata.get("retrieval")) if isinstance(agent_metadata, dict) else None
    )


def _extract_tool_result_metadata(tool_results: Any) -> tuple[list[dict], list[dict], list[dict]]:
    citations_by_doc_id: dict[str, dict] = {}
    products: list[dict] = []
    dealers: list[dict] = []
    for step_id, tool_result in (tool_results.items() if isinstance(tool_results, dict) else []):
        metadata = getattr(tool_result, "metadata", None)
        if not isinstance(metadata, dict) or not metadata:
            continue
        if isinstance(metadata.get("products"), list):
            products.extend(item for item in metadata["products"] if isinstance(item, dict))
        if isinstance(metadata.get("dealers"), list):
            dealers.extend(item for item in metadata["dealers"] if isinstance(item, dict))
        confidence = _normalized_citation_confidence(metadata.get("confidence"), default=1.0)
        candidates = metadata.get("citation_candidates")
        sources = metadata.get("sources")
        for source in [*(candidates[:20] if isinstance(candidates, list) else []), *(sources[:20] if isinstance(sources, list) else [])]:
            citation = _citation_from_metadata(source, default_confidence=confidence)
            if not citation:
                continue
            identity = citation["doc_id"].casefold()
            citations_by_doc_id[identity] = _merge_citation(citations_by_doc_id[identity], citation) if identity in citations_by_doc_id else citation
        logger.info(
            "tool_result_metadata",
            step_id=step_id,
            products_count=len(metadata.get("products", [])) if isinstance(metadata.get("products"), list) else 0,
            dealers_count=len(metadata.get("dealers", [])) if isinstance(metadata.get("dealers"), list) else 0,
            sources_count=len(sources) if isinstance(sources, list) else 0,
        )
    return (
        list(citations_by_doc_id.values())[:_MAX_PUBLIC_CITATIONS],
        [sanitize_for_json(product) for product in products],
        [sanitize_for_json(dealer) for dealer in dealers],
    )
