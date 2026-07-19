"""Provider-neutral commerce catalog retrieval helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit


DEFAULT_COMMERCE_CONFIG: Dict[str, Any] = {
    "default_currency": None,
    "display_policy": {
        "show_sources": False,
        "show_product_cards": True,
    },
    "retrieval": {
        "fusion": "rrf",
        "rrf_k": 60,
        "max_cards": 5,
        "max_product_cards": 5,
        "max_variants_per_card": 100,
        "self_crag_enabled": True,
        "max_retries": 2,
    },
    "taxonomy": {
        "source": "catalog",
        "category_field": "category",
        "product_type_field": "product_type",
        "tags_field": "tags",
    },
}

STOPWORDS = {
    "a", "an", "and", "any", "are", "available", "below", "budget", "buy",
    "can", "catalog", "cost", "find", "for", "from", "give", "have", "i",
    "in", "item", "items", "less", "looking", "max", "maximum", "me", "of",
    "or", "please", "price", "product", "products", "recommend", "search",
    "show", "some", "than", "the", "to", "under", "up", "upto", "want",
    "with", "within", "you",
}

CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "₨": "INR",
    "¥": "JPY",
}

CURRENCY_CODES = {
    "aed", "aud", "brl", "cad", "chf", "cny", "eur", "gbp", "hkd", "idr",
    "inr", "jpy", "krw", "mxn", "myr", "nzd", "php", "pkr", "sar", "sgd",
    "thb", "try", "usd", "zar",
}

_MAX_CITATION_CANDIDATES = 5
_MAX_CITATION_TEXT_CHARS = 300

_RETRIEVAL_STATUSES = {"evidence", "no_evidence", "degraded", "error"}
_RETRIEVAL_BACKENDS = {"vector", "bm25"}
_BACKEND_STATUSES = {"success", "unavailable", "error", "disabled"}
_BACKEND_REASONS = {
    "authentication_failed",
    "backend_unavailable",
    "collection_unavailable",
    "backend_error",
}
_RETRIEVAL_REASONS = {
    "partial_backend_failure",
    "no_search_backend_succeeded",
    "pipeline_error",
    "retrieval_error",
}


def safe_retrieval_metadata(context: Any) -> Dict[str, Any]:
    """Return the public-safe subset of a RetrievalContext's diagnostics.

    Commerce may use direct catalog records in addition to RAG, but callers
    still need to distinguish a valid empty RAG result from a backend outage.
    Keep this contract intentionally small so provider error details cannot be
    forwarded through commerce diagnostics.
    """
    raw_metadata = getattr(context, "retrieval_metadata", {}) or {}
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    status = raw_metadata.get("status")
    if status not in _RETRIEVAL_STATUSES:
        status = "evidence" if getattr(context, "chunks", None) else "no_evidence"

    reason = raw_metadata.get("reason")
    if reason not in _RETRIEVAL_REASONS:
        reason = "retrieval_error" if status == "error" else (
            "partial_backend_failure" if status == "degraded" else None
        )

    backend_status: Dict[str, Dict[str, str]] = {}
    raw_backend_status = raw_metadata.get("backend_status")
    if isinstance(raw_backend_status, dict):
        for backend, details in raw_backend_status.items():
            if backend not in _RETRIEVAL_BACKENDS or not isinstance(details, dict):
                continue
            backend_state = details.get("status")
            if backend_state not in _BACKEND_STATUSES:
                continue
            safe_details: Dict[str, str] = {"status": backend_state}
            backend_reason = details.get("reason")
            if backend_reason in _BACKEND_REASONS:
                safe_details["reason"] = backend_reason
            backend_status[backend] = safe_details

    return {
        "status": status,
        "reason": reason,
        "backend_status": backend_status,
        "successful_backends": [
            backend
            for backend, details in backend_status.items()
            if details["status"] == "success"
        ],
        "failed_backends": [
            backend
            for backend, details in backend_status.items()
            if details["status"] in {"error", "unavailable"}
        ],
    }


def citation_candidates_from_context(context: Any) -> List[Dict[str, Optional[str]]]:
    """Return bounded source fields suitable for user-facing citations."""
    candidates: List[Dict[str, Optional[str]]] = []
    seen_doc_ids = set()
    for chunk in list(getattr(context, "chunks", []) or []):
        doc_id = _citation_text(getattr(chunk, "doc_id", None), limit=128)
        if not doc_id or doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)
        candidates.append({
            "doc_id": doc_id,
            "title": _citation_text(getattr(chunk, "title", None), limit=256) or doc_id,
            "url": _citation_url(getattr(chunk, "url", None)),
            "snippet": _citation_text(
                getattr(chunk, "text", None) or getattr(chunk, "content", None),
                limit=_MAX_CITATION_TEXT_CHARS,
            ),
        })
        if len(candidates) >= _MAX_CITATION_CANDIDATES:
            break
    return candidates


def _citation_text(value: Any, *, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] or None


def _citation_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(parsed)


@dataclass
class CommerceIntent:
    query: str
    terms: List[str] = field(default_factory=list)
    product_type: Optional[str] = None
    budget_max: Optional[float] = None
    budget_currency: Optional[str] = None
    negative_terms: List[str] = field(default_factory=list)
    expanded_terms: List[str] = field(default_factory=list)
    availability_required: bool = False


@dataclass
class CommerceRetrievalResult:
    products: List[Dict[str, Any]]
    sources: List[Any]
    confidence: float
    search_query: str
    intent: CommerceIntent
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class CommerceRetrievalPipeline:
    """Search catalog products with structured intent, fusion, and validation."""

    def __init__(self, retrieval_pipeline: Any, commerce_config: Optional[Dict[str, Any]] = None):
        self.pipeline = retrieval_pipeline
        self.commerce_config = self._merge_config(commerce_config)

    async def retrieve(
        self,
        *,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        pagination: Optional[Dict[str, Any]] = None,
        page_context: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        commerce_config: Optional[Dict[str, Any]] = None,
    ) -> CommerceRetrievalResult:
        if commerce_config is not None:
            self.commerce_config = self._merge_config(commerce_config)

        limit = self.result_limit(pagination)
        intent = self.parse_intent(query, context=context, filters=filters)
        product_filters = {"content_type": "product", **(filters or {})}

        direct_products = await self._direct_catalog_products(intent, product_filters, limit)
        retrieval_context = await self._retrieve_context(query, product_filters, limit, page_context)
        retrieval_products = self._products_from_chunks(getattr(retrieval_context, "chunks", []) or [])

        fused = self._fuse_ranked_products([direct_products, retrieval_products], limit=limit * 4)
        valid, invalid_reasons = self._validate_candidates(fused, intent)

        retried = False
        expanded_query = self._expanded_query(query, intent)
        max_retries = self.retrieval_int("max_retries", 2)
        self_crag_enabled = bool(self.retrieval_config().get("self_crag_enabled", True))
        if self_crag_enabled and max_retries > 0 and not valid and expanded_query != query:
            retried = True
            retry_context = await self._retrieve_context(expanded_query, product_filters, limit, page_context)
            retry_products = self._products_from_chunks(getattr(retry_context, "chunks", []) or [])
            retry_direct = await self._direct_catalog_products(
                CommerceIntent(
                    query=expanded_query,
                    terms=sorted(set([*intent.terms, *intent.expanded_terms])),
                    product_type=intent.product_type,
                    budget_max=intent.budget_max,
                    budget_currency=intent.budget_currency,
                    negative_terms=intent.negative_terms,
                    expanded_terms=intent.expanded_terms,
                    availability_required=intent.availability_required,
                ),
                product_filters,
                limit,
            )
            fused = self._fuse_ranked_products([retry_direct, retry_products], limit=limit * 4)
            valid, invalid_reasons = self._validate_candidates(fused, intent)
            retrieval_context = retry_context

        products = await self._group_variant_products(valid, limit=limit, filters=product_filters, intent=intent)
        confidence = self._confidence(products, direct_products, retrieval_products, retrieval_context)
        return CommerceRetrievalResult(
            products=products,
            sources=list(getattr(retrieval_context, "sources", []) or []),
            confidence=confidence,
            search_query=expanded_query if retried else query,
            intent=intent,
            diagnostics={
                "rankers": {
                    "direct_catalog": len(direct_products),
                    "retrieval_products": len(retrieval_products),
                },
                "retrieval": safe_retrieval_metadata(retrieval_context),
                "citation_candidates": citation_candidates_from_context(retrieval_context),
                "retried_with_expanded_query": retried,
                "invalid_reasons": invalid_reasons[:10],
                "variant_groups": sum(1 for product in products if product.get("has_variants")),
            },
        )

    def parse_intent(
        self,
        query: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> CommerceIntent:
        query = query or ""
        context = context if isinstance(context, dict) else {}
        constraints = context.get("constraints") if isinstance(context.get("constraints"), dict) else {}
        taxonomy_match = self._taxonomy_match(query)
        product_type = (
            self._clean_text(constraints.get("product_type"))
            or self._clean_text((filters or {}).get("product_type"))
            or taxonomy_match
            or self._fallback_product_type(query)
        )
        budget_amount, budget_currency = self._extract_budget(query)
        if isinstance(constraints.get("budget"), dict):
            amount = constraints["budget"].get("amount")
            if amount not in (None, ""):
                try:
                    budget_amount = float(amount)
                except (TypeError, ValueError):
                    pass
            budget_currency = constraints["budget"].get("currency") or budget_currency

        negative_terms = []
        for term in constraints.get("negative_constraints") or []:
            cleaned = self._clean_text(term)
            if cleaned:
                negative_terms.append(cleaned)
        negative_terms.extend(self._taxonomy_exclusions(product_type))

        for term in re.findall(r"\b(?:not|no|avoid|without)\s+([a-z0-9 -]{2,30})", query.lower()):
            cleaned = re.sub(r"\b(for|with|and|or|under|below|above|over)\b.*$", "", term).strip()
            if cleaned:
                negative_terms.append(cleaned)

        availability_required = bool(re.search(r"\b(in stock|in-stock|available|availability)\b", query.lower()))

        terms = self._query_terms(query, product_type)
        expanded_terms = self._taxonomy_expansions(product_type)
        return CommerceIntent(
            query=query,
            terms=terms,
            product_type=product_type,
            budget_max=budget_amount,
            budget_currency=budget_currency or self.default_currency(),
            negative_terms=sorted(set(negative_terms)),
            expanded_terms=expanded_terms,
            availability_required=availability_required,
        )

    def default_currency(self) -> Optional[str]:
        currency = self.commerce_config.get("default_currency")
        if currency in (None, ""):
            return None
        return str(currency).upper()

    @staticmethod
    def pagination_limit(pagination: Optional[Dict[str, Any]]) -> int:
        if isinstance(pagination, dict):
            try:
                return max(1, min(int(pagination.get("limit") or 5), 20))
            except (TypeError, ValueError):
                pass
        return 5

    def result_limit(self, pagination: Optional[Dict[str, Any]]) -> int:
        configured = (
            self.retrieval_int("max_product_cards", 0)
            or self.retrieval_int("max_cards", 0)
            or 5
        )
        configured = max(1, min(configured, 20))
        if isinstance(pagination, dict) and pagination.get("limit") not in (None, ""):
            return max(1, min(self.pagination_limit(pagination), configured))
        return configured

    def retrieval_config(self) -> Dict[str, Any]:
        retrieval = self.commerce_config.get("retrieval")
        return retrieval if isinstance(retrieval, dict) else {}

    def retrieval_int(self, key: str, default: int) -> int:
        try:
            return int(self.retrieval_config().get(key, default))
        except (TypeError, ValueError):
            return default

    async def _retrieve_context(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int,
        page_context: Optional[Dict[str, Any]],
    ) -> Any:
        kwargs = {
            "query": query,
            "filters": filters,
            "max_chunks": max(limit * 2, 5),
        }
        if page_context:
            kwargs["page_context"] = page_context
        return await self.pipeline.retrieve(**kwargs)

    async def _direct_catalog_products(
        self,
        intent: CommerceIntent,
        filters: Dict[str, Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        collection = self._catalog_collection()
        if collection is None:
            return []

        mongo_query: Dict[str, Any] = {
            "content_type": "product",
            # Legacy/manual products omit these fields and remain eligible. A
            # Shopify delete/uninstall explicitly sets both to false, making it
            # impossible for a stale product to re-enter direct retrieval.
            "product_data.source_active": {"$ne": False},
            "metadata.catalog_source.active": {"$ne": False},
            **(filters or {}),
        }
        if intent.budget_max is not None:
            max_price = max(float(intent.budget_max), float(intent.budget_max) * 100)
            mongo_query["product_data.price"] = {"$gt": 0, "$lte": max_price}

        pattern = self._term_pattern([*intent.terms, *intent.expanded_terms])
        if pattern:
            taxonomy = self.commerce_config.get("taxonomy") or {}
            category_field = taxonomy.get("category_field") or "category"
            product_type_field = taxonomy.get("product_type_field") or "product_type"
            tags_field = taxonomy.get("tags_field") or "tags"
            mongo_query["$or"] = [
                {"title": {"$regex": pattern, "$options": "i"}},
                {"content": {"$regex": pattern, "$options": "i"}},
                {"product_data.name": {"$regex": pattern, "$options": "i"}},
                {f"product_data.{category_field}": {"$regex": pattern, "$options": "i"}},
                {f"product_data.{product_type_field}": {"$regex": pattern, "$options": "i"}},
                {f"product_data.{tags_field}": {"$regex": pattern, "$options": "i"}},
                {"product_data.sku": {"$regex": pattern, "$options": "i"}},
                {"product_data.handle": {"$regex": pattern, "$options": "i"}},
            ]

        cursor = collection.find(
            mongo_query,
            {"product_data": 1, "title": 1, "content": 1, "doc_id": 1, "url": 1},
        ).limit(limit * 20)
        rows = await cursor.to_list(length=limit * 20)

        products = []
        seen = set()
        for row in rows:
            product_data = row.get("product_data") or {}
            if product_data.get("source_active") is False:
                continue
            product = self._normalize_product(product_data, source="direct_catalog", row=row)
            identity = self._identity(product)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            products.append(product)
        return products

    def _products_from_chunks(self, chunks: Iterable[Any]) -> List[Dict[str, Any]]:
        products = []
        seen = set()
        for chunk in chunks:
            product_data = getattr(chunk, "product_data", None)
            if not product_data and isinstance(getattr(chunk, "metadata", None), dict):
                product_data = chunk.metadata.get("product_data")
            if not isinstance(product_data, dict):
                continue
            if product_data.get("source_active") is False:
                continue
            product = self._normalize_product(product_data, source="retrieval", row={"doc_id": getattr(chunk, "doc_id", None)})
            identity = self._identity(product)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            products.append(product)
        return products

    def _normalize_product(
        self,
        product_data: Dict[str, Any],
        *,
        source: str,
        row: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = row or {}
        product_id = (
            product_data.get("sku")
            or product_data.get("product_id")
            or product_data.get("id")
            or product_data.get("variant_id")
            or product_data.get("handle")
        )
        name = product_data.get("name") or product_data.get("title") or row.get("title") or product_id or "Product"
        currency, currency_source = self._normalize_currency(product_data.get("currency") or product_data.get("currencyCode"))
        item = dict(product_data)
        item.update({
            "id": product_id,
            "sku": product_data.get("sku") or product_id,
            "name": name,
            "title": product_data.get("title") or name,
            "description": product_data.get("description") or product_data.get("category") or "",
            "price": product_data.get("price"),
            "price_minor": product_data.get("price_minor", product_data.get("price")),
            "price_unit": "minor",
            "currency": currency,
            "currency_source": currency_source,
            "image": product_data.get("image") or product_data.get("image_url"),
            "image_url": product_data.get("image_url") or product_data.get("image"),
            "url": product_data.get("url") or product_data.get("product_url"),
            "product_url": product_data.get("product_url") or product_data.get("url"),
            "source": source,
        })
        if product_data.get("variant_id") is not None:
            item["variant_id"] = product_data.get("variant_id")
        return item

    async def _group_variant_products(
        self,
        products: List[Dict[str, Any]],
        *,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        intent: Optional[CommerceIntent] = None,
    ) -> List[Dict[str, Any]]:
        groups: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for rank, product in enumerate(products, start=1):
            group_key = self._product_group_key(product)
            if not group_key:
                group_key = self._identity(product) or f"product:{rank}"
            if group_key not in groups:
                groups[group_key] = {
                    "key": group_key,
                    "rank": rank,
                    "products": [],
                }
                order.append(group_key)
            product_copy = dict(product)
            product_copy["_variant_rank"] = rank
            groups[group_key]["products"].append(product_copy)

        grouped_products: List[Dict[str, Any]] = []
        for group_key in order:
            group_products = groups[group_key]["products"]
            selected = self._select_default_variant(group_products)
            group_products = await self._hydrate_variant_group(selected, group_products, filters=filters)
            if intent is not None:
                valid_group, _ = self._validate_candidates(group_products, intent)
                if valid_group:
                    group_products = valid_group
            group_products = self._ordered_variant_products(group_products, selected)
            grouped = dict(selected)
            variants = [self._variant_from_product(product, selected) for product in group_products]
            variant_prices = [
                self._numeric_price(variant.get("price"))
                for variant in variants
                if self._numeric_price(variant.get("price")) is not None
            ]
            grouped["product_group_id"] = selected.get("product_group_id") or group_key
            grouped["name"] = selected.get("parent_name") or self._common_product_name(group_products) or selected.get("name")
            grouped["title"] = grouped["name"]
            grouped["has_variants"] = len(variants) > 1 or bool(selected.get("has_variants"))
            grouped["variant_count"] = max(int(selected.get("variant_count") or 0), len(variants))
            grouped["variants"] = variants
            grouped["default_variant_id"] = selected.get("variant_id") or selected.get("default_variant_id") or selected.get("id")
            if variant_prices:
                grouped["price_min"] = min(variant_prices)
                grouped["price_max"] = max(variant_prices)
            grouped.pop("_variant_rank", None)
            grouped_products.append(grouped)
            if len(grouped_products) >= limit:
                break
        return grouped_products

    async def _hydrate_variant_group(
        self,
        selected: Dict[str, Any],
        group_products: List[Dict[str, Any]],
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        collection = self._catalog_collection()
        if collection is None:
            return group_products

        queries = self._variant_group_queries(selected)
        if not queries:
            return group_products

        max_variants = max(1, min(self.retrieval_int("max_variants_per_card", 100), 500))
        base_filters = {
            key: value
            for key, value in (filters or {}).items()
            if key not in {"$or", "product_data.price"}
        }
        base_filters["content_type"] = "product"
        base_filters["product_data.source_active"] = {"$ne": False}
        base_filters["metadata.catalog_source.active"] = {"$ne": False}

        hydrated: List[Dict[str, Any]] = []
        for query in queries:
            cursor = collection.find(
                {**base_filters, **query},
                {"product_data": 1, "title": 1, "content": 1, "doc_id": 1, "url": 1},
            ).limit(max_variants)
            rows = await cursor.to_list(length=max_variants)
            for row_index, row in enumerate(rows):
                product_data = row.get("product_data") or {}
                if product_data.get("source_active") is False:
                    continue
                product = self._normalize_product(product_data, source="variant_hydration", row=row)
                product["_variant_rank"] = int(selected.get("_variant_rank") or 9999) + 1000 + row_index
                hydrated.append(product)
            if hydrated:
                break

        return self._dedupe_variant_products([*group_products, *hydrated])

    def _variant_group_queries(self, product: Dict[str, Any]) -> List[Dict[str, Any]]:
        queries: List[Dict[str, Any]] = []
        for key in ("product_group_id", "product_id", "handle"):
            value = product.get(key)
            if value not in (None, ""):
                queries.append({f"product_data.{key}": value})

        url = product.get("product_url") or product.get("url") or product.get("variant_url")
        base_url = self._base_product_url(url)
        if base_url:
            escaped = re.escape(base_url.rstrip("/"))
            queries.append({
                "$or": [
                    {"product_data.product_url": base_url},
                    {"product_data.url": base_url},
                    {"product_data.variant_url": {"$regex": rf"^{escaped}(?:/)?(?:\?.*)?$"}},
                ]
            })

        deduped = []
        seen = set()
        for query in queries:
            key = repr(query)
            if key not in seen:
                seen.add(key)
                deduped.append(query)
        return deduped

    def _dedupe_variant_products(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for product in products:
            identity = self._variant_identity(product)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            deduped.append(product)
        return deduped

    def _ordered_variant_products(
        self,
        products: List[Dict[str, Any]],
        selected: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        selected_identity = self._variant_identity(selected)

        def sort_key(product: Dict[str, Any]) -> Tuple[int, int, float, str]:
            identity = self._variant_identity(product)
            selected_rank = 0 if identity and identity == selected_identity else 1
            in_stock_rank = 0 if product.get("in_stock", True) else 1
            price = self._numeric_price(product.get("price"))
            return (
                selected_rank,
                int(product.get("_variant_rank") or 9999),
                float(price if price is not None else 10**18),
                identity or "",
            )

        return sorted(products, key=sort_key)

    def _product_group_key(self, product: Dict[str, Any]) -> Optional[str]:
        for key in ("product_group_id", "product_id", "handle"):
            value = product.get(key)
            if value not in (None, ""):
                return f"{key}:{str(value).strip().lower()}"
        url = product.get("product_url") or product.get("url") or product.get("variant_url")
        base_url = self._base_product_url(url)
        if base_url:
            return f"url:{base_url.lower()}"
        return None

    @staticmethod
    def _base_product_url(url: Any) -> Optional[str]:
        if url in (None, ""):
            return None
        try:
            parts = urlsplit(str(url))
            if not parts.scheme or not parts.netloc:
                return re.sub(r"\?.*$", "", str(url)).rstrip("/")
            return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        except Exception:
            return re.sub(r"\?.*$", "", str(url)).rstrip("/")

    def _select_default_variant(self, products: List[Dict[str, Any]]) -> Dict[str, Any]:
        def sort_key(product: Dict[str, Any]) -> Tuple[int, float, int]:
            in_stock_rank = 0 if product.get("in_stock", True) else 1
            price = self._numeric_price(product.get("price"))
            return (int(product.get("_variant_rank") or 9999), in_stock_rank, float(price if price is not None else 10**18))

        return min(products, key=sort_key)

    def _variant_from_product(self, product: Dict[str, Any], selected: Dict[str, Any]) -> Dict[str, Any]:
        variant_options = product.get("variant_options")
        if not isinstance(variant_options, dict):
            variant_options = {}
        label = self._variant_label(product, selected)
        if not variant_options and label:
            variant_options = {"Variant": label}
        return {
            "id": product.get("variant_id") or product.get("id") or product.get("sku"),
            "variant_id": product.get("variant_id") or product.get("id") or product.get("sku"),
            "sku": product.get("variant_sku") or product.get("sku"),
            "variant_sku": product.get("variant_sku") or product.get("sku"),
            "name": product.get("name"),
            "title": product.get("variant_title") or label or product.get("name"),
            "variant_title": product.get("variant_title") or label,
            "variant_options": variant_options,
            "price": product.get("price"),
            "price_minor": product.get("price_minor", product.get("price")),
            "price_unit": "minor",
            "currency": product.get("currency"),
            "currency_source": product.get("currency_source"),
            "image_url": product.get("image_url") or product.get("image"),
            "image": product.get("image") or product.get("image_url"),
            "product_url": product.get("product_url") or product.get("url"),
            "variant_url": product.get("variant_url") or product.get("product_url") or product.get("url"),
            "in_stock": product.get("in_stock", True),
            "is_default": (product.get("variant_id") or product.get("id") or product.get("sku")) == (
                selected.get("variant_id") or selected.get("id") or selected.get("sku")
            ),
        }

    def _variant_label(self, product: Dict[str, Any], selected: Dict[str, Any]) -> str:
        explicit = product.get("variant_title")
        if explicit not in (None, "", "Default Title"):
            return str(explicit)
        parent = product.get("parent_name") or selected.get("parent_name") or self._common_product_name([product, selected])
        name = str(product.get("name") or "")
        if parent and name.lower().startswith(str(parent).lower()):
            return re.sub(r"^[\s\-–—/]+", "", name[len(str(parent)):]).strip()
        return ""

    def _common_product_name(self, products: List[Dict[str, Any]]) -> str:
        parent_names = [str(product.get("parent_name")) for product in products if product.get("parent_name")]
        if parent_names:
            return parent_names[0]
        names = [str(product.get("name") or product.get("title") or "") for product in products if product.get("name") or product.get("title")]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        prefix = names[0]
        for name in names[1:]:
            while prefix and not name.lower().startswith(prefix.lower()):
                prefix = prefix[:-1]
        prefix = re.sub(r"[\s\-–—/]+$", "", prefix).strip()
        return prefix or names[0]

    @staticmethod
    def _numeric_price(price: Any) -> Optional[float]:
        try:
            return float(price)
        except (TypeError, ValueError):
            return None

    def _normalize_currency(self, currency: Any) -> Tuple[Optional[str], str]:
        fallback = self.default_currency()
        policy = str(self.commerce_config.get("currency_policy") or "catalog_first_config_fallback").strip().lower()
        catalog_currency = str(currency).strip().upper() if currency not in (None, "") and str(currency).strip() else None

        if policy == "default_only":
            if fallback:
                return fallback, "commerce.default_currency"
            return None, "missing"

        if catalog_currency:
            return catalog_currency, "product"

        if policy != "catalog_only" and fallback:
            return fallback, "commerce.default_currency"

        return None, "missing"

    def _fuse_ranked_products(self, ranked_lists: List[List[Dict[str, Any]]], *, limit: int) -> List[Dict[str, Any]]:
        scores: Dict[str, float] = {}
        products: Dict[str, Dict[str, Any]] = {}
        appearances: Dict[str, List[str]] = {}
        k = max(1, self.retrieval_int("rrf_k", 60))
        for ranked in ranked_lists:
            for rank, product in enumerate(ranked, start=1):
                identity = self._identity(product)
                if not identity:
                    continue
                scores[identity] = scores.get(identity, 0.0) + 1.0 / (k + rank)
                appearances.setdefault(identity, []).append(str(product.get("source") or "ranker"))
                if identity not in products:
                    products[identity] = dict(product)

        fused = []
        for identity, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
            product = products[identity]
            product["retrieval_score"] = score
            product["ranker_sources"] = sorted(set(appearances.get(identity) or []))
            fused.append(product)
            if len(fused) >= limit:
                break
        return fused

    def _validate_candidates(
        self,
        candidates: List[Dict[str, Any]],
        intent: CommerceIntent,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        valid = []
        invalid = []
        for product in candidates:
            missing = []
            matched = []
            text = self._product_text(product)

            if intent.budget_max is not None:
                comparable_price = self._price_for_compare(product.get("price"), intent.budget_max)
                if comparable_price is None or comparable_price > intent.budget_max:
                    missing.append(f"under budget {intent.budget_max:g}")
                else:
                    matched.append(f"under budget {intent.budget_max:g}")

            if intent.product_type:
                accepted_terms = {intent.product_type, *intent.expanded_terms}
                if not any(self._term_in_text(term, text) for term in accepted_terms if term):
                    missing.append(f"type {intent.product_type}")
                else:
                    matched.append(f"type {intent.product_type}")
            elif intent.terms:
                if not any(self._term_in_text(term, text) for term in intent.terms):
                    missing.append("query terms")

            if intent.availability_required and product.get("in_stock") is not True:
                missing.append("in stock")

            excluded = [term for term in intent.negative_terms if self._term_in_text(term, text)]
            if excluded:
                missing.append(f"excluded {', '.join(excluded[:3])}")

            if missing:
                invalid.append({"product": product.get("name") or product.get("id"), "missing": missing})
                continue

            enriched = dict(product)
            enriched["matched_constraints"] = matched
            enriched["missing_constraints"] = []
            if matched:
                enriched["reason"] = "Matches " + ", ".join(matched) + "."
            valid.append(enriched)
        return valid, invalid

    def _confidence(
        self,
        products: List[Dict[str, Any]],
        direct_products: List[Dict[str, Any]],
        retrieval_products: List[Dict[str, Any]],
        retrieval_context: Any,
    ) -> float:
        if not products:
            return 0.0
        base = float(getattr(retrieval_context, "confidence", 0.0) or 0.0)
        ranker_bonus = 0.2 if direct_products and retrieval_products else 0.1
        return min(0.95, max(base, 0.65) + ranker_bonus)

    def _expanded_query(self, query: str, intent: CommerceIntent) -> str:
        terms = [query, *intent.expanded_terms]
        expanded = " ".join(term for term in terms if term)
        return re.sub(r"\s+", " ", expanded).strip()

    def _extract_budget(self, query: str) -> Tuple[Optional[float], Optional[str]]:
        lowered = (query or "").lower()
        has_budget_signal = bool(
            re.search(r"\b(under|below|less than|within|budget|max|maximum|upto|up to)\b", lowered)
            or any(symbol in query for symbol in CURRENCY_SYMBOLS)
            or re.search(r"\b(" + "|".join(sorted(CURRENCY_CODES)) + r"|rs\.?)\b", lowered)
            or re.search(r"\b[0-9][0-9,]*(?:\.\d+)?\s*(?:k|thousand|lakh|lac|m|million)\b", lowered)
        )
        if not has_budget_signal:
            return None, None

        prefix = r"(?<![a-z0-9])(?:(?P<symbol>[$€£₹₨¥])|(?P<code>\b(?:" + "|".join(sorted(CURRENCY_CODES)) + r"|rs\.?)\b))?"
        match = re.search(
            prefix + r"\s*(?P<amount>[0-9][0-9,]*(?:\.\d+)?)\s*(?P<suffix>k|thousand|lakh|lac|m|million)?\b",
            lowered,
            re.IGNORECASE,
        )
        if not match:
            return None, None
        amount = float(match.group("amount").replace(",", ""))
        suffix = (match.group("suffix") or "").lower()
        if suffix in {"k", "thousand"}:
            amount *= 1_000
        elif suffix in {"lakh", "lac"}:
            amount *= 100_000
        elif suffix in {"m", "million"}:
            amount *= 1_000_000

        currency = None
        symbol = match.group("symbol")
        code = match.group("code")
        if symbol:
            currency = CURRENCY_SYMBOLS.get(symbol)
        elif code:
            normalized = code.replace(".", "").upper()
            currency = "INR" if normalized == "RS" else normalized
        return amount, currency

    def _taxonomy_match(self, query: str) -> Optional[str]:
        normalized_query = self._clean_text(query)
        for label, terms, _exclusions in self._taxonomy_entries():
            if any(self._term_in_text(term, normalized_query) for term in [label, *terms]):
                return label
        return None

    def _taxonomy_expansions(self, product_type: Optional[str]) -> List[str]:
        if not product_type:
            return []
        expansions = []
        for label, terms, _exclusions in self._taxonomy_entries():
            if label == product_type or product_type in terms:
                expansions.extend([label, *terms])
        return sorted(set(self._clean_text(term) for term in expansions if self._clean_text(term)))

    def _taxonomy_exclusions(self, product_type: Optional[str]) -> List[str]:
        exclusions = []
        taxonomy = self.commerce_config.get("taxonomy") or {}
        for key in ("exclusions", "exclude", "negative_terms"):
            value = taxonomy.get(key)
            if isinstance(value, list):
                exclusions.extend(str(term) for term in value)
        for label, terms, entry_exclusions in self._taxonomy_entries():
            if product_type and (label == product_type or product_type in terms):
                exclusions.extend(entry_exclusions)
        return sorted(set(self._clean_text(term) for term in exclusions if self._clean_text(term)))

    def _taxonomy_entries(self) -> List[Tuple[str, List[str], List[str]]]:
        taxonomy = self.commerce_config.get("taxonomy") or {}
        raw_entries = taxonomy.get("categories") or taxonomy.get("product_types") or taxonomy.get("types") or []
        entries = []
        if isinstance(raw_entries, dict):
            iterable = raw_entries.items()
        elif isinstance(raw_entries, list):
            iterable = [(entry.get("name") or entry.get("id"), entry) for entry in raw_entries if isinstance(entry, dict)]
        else:
            iterable = []

        for label, entry in iterable:
            label = self._clean_text(label)
            if not label:
                continue
            terms = []
            exclusions = []
            if isinstance(entry, dict):
                for key in ("aliases", "synonyms", "terms", "children"):
                    value = entry.get(key)
                    if isinstance(value, list):
                        terms.extend(str(term) for term in value)
                    elif isinstance(value, dict):
                        terms.extend(str(term) for term in value.keys())
                for key in ("exclusions", "exclude", "negative_terms"):
                    value = entry.get(key)
                    if isinstance(value, list):
                        exclusions.extend(str(term) for term in value)
            elif isinstance(entry, list):
                terms.extend(str(term) for term in entry)
            entries.append((
                label,
                sorted(set(self._clean_text(term) for term in terms if self._clean_text(term))),
                sorted(set(self._clean_text(term) for term in exclusions if self._clean_text(term))),
            ))
        return entries

    def _fallback_product_type(self, query: str) -> Optional[str]:
        cleaned = self._clean_text(query)
        terms = [term for term in cleaned.split() if term not in STOPWORDS and not term.isdigit()]
        return terms[-1] if terms else None

    def _query_terms(self, query: str, product_type: Optional[str]) -> List[str]:
        cleaned = self._clean_text(query)
        cleaned = re.sub(
            r"\b(under|below|less than|within|budget|max|maximum|upto|up to)\b\s*[$€£₹₨¥]?\s*[a-z]{0,3}\.?\s*[0-9][0-9,]*(?:\.\d+)?\s*(?:k|thousand|lakh|lac|m|million)?",
            " ",
            cleaned,
        )
        tokens = [token for token in cleaned.split() if token not in STOPWORDS and not token.isdigit()]
        if product_type:
            tokens.append(product_type)
        return sorted(set(tokens))

    def _catalog_collection(self) -> Any:
        bm25 = getattr(self.pipeline, "bm25_search", None)
        collection = getattr(bm25, "collection", None)
        if collection is not None:
            return collection
        vector = getattr(self.pipeline, "vector_search", None)
        return getattr(vector, "collection", None)

    def _term_pattern(self, terms: Iterable[str]) -> str:
        cleaned = [self._clean_text(term) for term in terms]
        cleaned = [term for term in cleaned if term and term not in STOPWORDS]
        return "|".join(re.escape(term) for term in sorted(set(cleaned), key=len, reverse=True))

    def _product_text(self, product: Dict[str, Any]) -> str:
        taxonomy = self.commerce_config.get("taxonomy") or {}
        fields = [
            "name", "title", "description", "category", "product_type", "tags", "sku", "handle", "product_group_id",
            taxonomy.get("category_field") or "category",
            taxonomy.get("product_type_field") or "product_type",
            taxonomy.get("tags_field") or "tags",
        ]
        values = []
        for field in fields:
            value = product.get(field)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            elif isinstance(value, dict):
                values.extend(str(item) for item in value.values())
            elif value not in (None, ""):
                values.append(str(value))
        return self._clean_text(" ".join(values))

    @staticmethod
    def _term_in_text(term: str, text: str) -> bool:
        term = re.escape((term or "").strip().lower())
        if not term:
            return False
        return bool(re.search(rf"(?<!\w){term}(?:s|es)?(?!\w)", text or ""))

    @staticmethod
    def _price_for_compare(price: Any, budget: Optional[float]) -> Optional[float]:
        try:
            numeric = float(price)
        except (TypeError, ValueError):
            return None
        if budget and numeric > budget and numeric / 100 <= budget:
            return numeric / 100
        return numeric

    @staticmethod
    def _identity(product: Dict[str, Any]) -> Optional[str]:
        for key in ("sku", "id", "product_id", "variant_id", "handle", "product_url", "url", "name"):
            value = product.get(key)
            if value not in (None, ""):
                return re.sub(r"\s+", " ", str(value).strip().lower())
        return None

    @staticmethod
    def _variant_identity(product: Dict[str, Any]) -> Optional[str]:
        for key in ("variant_id", "variant_sku", "sku", "variant_url", "id"):
            value = product.get(key)
            if value not in (None, ""):
                return re.sub(r"\s+", " ", str(value).strip().lower())
        return None

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value in (None, ""):
            return ""
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", str(value).lower())).strip()

    @classmethod
    def _merge_config(cls, commerce_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        config = commerce_config if isinstance(commerce_config, dict) else {}
        if "commerce" in config and isinstance(config.get("commerce"), dict):
            config = config["commerce"]
        return cls._deep_merge(DEFAULT_COMMERCE_CONFIG, config)

    @classmethod
    def _deep_merge(cls, defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        merged = {
            key: cls._deep_merge(value, {}) if isinstance(value, dict) else value
            for key, value in defaults.items()
        }
        for key, value in overrides.items():
            if value is None:
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
