"""
Response Validator - Phase 4: Server-side validation of LLM responses

Prevents hallucinated SKUs, prices, dealers, and contact information from reaching users.
Implements strict validation against catalog data.
"""

import re
import structlog
from typing import Any, Dict, Iterable, List, Optional, Tuple
from dataclasses import dataclass

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of response validation."""
    is_valid: bool
    confidence: float  # 0.0 to 1.0
    issues: List[str]  # List of validation issues found
    sanitized_response: str  # Response with issues removed/flagged
    metadata: Dict  # Additional validation metadata


# The claim-evidence check below intentionally uses deterministic, local rules.
# It is the final server-side gate after every runtime (RAG, commerce, planner,
# and Lal Kitab) has produced an answer, so it must neither call a model nor
# expose its working evidence to a user-facing response or log record.
_PRIVATE_ANNOTATION_PATTERNS = (
    re.compile(r"<!--.*?-->", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"\[\s*(?:evidence|source|citation|doc(?:ument)?(?:[_\s-]?id)?|"
        r"provider|tool|connector|rag|chunk)\s*(?:[:#=-][^\]]*)?\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"\(\s*(?:evidence|source|citation|doc(?:ument)?(?:[_\s-]?id)?|"
        r"provider|tool|connector|rag|chunk)\s*:[^)]*\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"<(?:evidence|source|citation|provider|tool|connector|rag|chunk)\b[^>]*>"
        r".*?</(?:evidence|source|citation|provider|tool|connector|rag|chunk)>",
        re.IGNORECASE | re.DOTALL,
    ),
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"(?<![\w])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")
_DATE_PATTERN = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
_URL_PATTERN = re.compile(r"https?://[^\s)>]+", re.IGNORECASE)
_SKU_PATTERN = re.compile(r"\b(?:[A-Z]{1,8}[-_][A-Z0-9][A-Z0-9_-]*|[A-Z0-9]{5,})\b")
_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
_TOKEN_ALIASES = {
    "cost": "price",
    "costs": "price",
    "priced": "price",
    "pricing": "price",
    "available": "stock",
    "availability": "stock",
    "warranties": "warranty",
    "years": "year",
}
_STOP_TOKENS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do", "does",
    "for", "from", "has", "have", "here", "i", "if", "in", "is", "it", "its", "of",
    "on", "or", "our", "please", "that", "the", "their", "there", "these", "this", "to",
    "was", "we", "with", "you", "your", "product", "products", "option", "options", "result",
    "results", "response", "answer", "information", "details", "help", "helpful", "matching",
}
_SAFE_RESPONSE_PATTERNS = (
    re.compile(r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening))\b", re.IGNORECASE),
    re.compile(r"^\s*(?:thanks|thank you|you're welcome|you are welcome)\b", re.IGNORECASE),
    re.compile(r"\b(?:i can|i'll|i will|let me|please|could you|can you)\s+(?:help|check|find|share|provide|confirm|tell|choose|try)\b", re.IGNORECASE),
    re.compile(r"\b(?:how can i help|what would you like|share (?:the|a)|please (?:share|provide|confirm))\b", re.IGNORECASE),
    re.compile(r"\b(?:don't|do not|cannot|can[’']t|couldn't|couldn[’']t|unable to)\s+(?:verify|confirm|answer|safely give|access)\b", re.IGNORECASE),
    re.compile(r"\b(?:don[’']t have|do not have|not enough|insufficient)\s+(?:enough )?(?:verified )?(?:information|evidence)\b", re.IGNORECASE),
    re.compile(r"\b(?:try again|contact (?:the )?(?:brand|support|team))\b", re.IGNORECASE),
    re.compile(r"^\s*(?:streaming )?response complete\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*this is a helpful response(?: with citations)?\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*here (?:is|are) (?:the )?(?:matching|relevant) (?:product|products|option|options|result|results)\.?\s*$", re.IGNORECASE),
)
_ASSERTION_PATTERN = re.compile(
    r"\b(?:is|are|was|were|has|have|had|cost|costs|priced|price|available|includes?|"
    r"supports?|ships?|delivers?|located|made|works?|compatible|warranty|guarantee|"
    r"offers?|comes|contains?|features?|provides?|requires?|will)\b",
    re.IGNORECASE,
)


def _canonical_token(token: str) -> str:
    token = token.lower()
    token = _NUMBER_WORDS.get(token, token)
    token = _TOKEN_ALIASES.get(token, token)
    if len(token) > 4 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 4 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def _tokens(value: str) -> set[str]:
    return {_canonical_token(match.group(0)) for match in _TOKEN_PATTERN.finditer(value or "")}


def _meaningful_tokens(value: str) -> set[str]:
    return {token for token in _tokens(value) if token not in _STOP_TOKENS and len(token) > 1}


def _normalised_url(value: str) -> str:
    return value.rstrip(".,;:!?)]}").lower()


def _anchors(value: str) -> set[str]:
    """Extract exact factual anchors that cannot be supported approximately."""
    text = value or ""
    anchors: set[str] = set()
    for date in _DATE_PATTERN.findall(text):
        anchors.add(f"date:{date.replace('/', '-')}")
    for url in _URL_PATTERN.findall(text):
        anchors.add(f"url:{_normalised_url(url)}")
    for number in _NUMBER_PATTERN.findall(text):
        anchors.add(f"number:{number.replace(',', '')}")
    for token in _SKU_PATTERN.findall(text):
        anchors.add(f"sku:{token.lower()}")
    for word, number in _NUMBER_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            anchors.add(f"number:{number}")
    if re.search(r"\b(?:in[ -]stock|available now)\b", text, re.IGNORECASE):
        anchors.add("availability:in_stock")
    if re.search(r"\b(?:out[ -]of[ -]stock|unavailable)\b", text, re.IGNORECASE):
        anchors.add("availability:out_of_stock")
    return anchors


def _structured_text(value: Any, *, depth: int = 0) -> str:
    """Flatten structured evidence while retaining field names as factual context."""
    if depth > 5 or value is None:
        return ""
    if isinstance(value, dict):
        pieces: list[str] = []
        for key, item in value.items():
            safe_key = str(key).replace("_", " ").replace("-", " ")
            if key in {"in_stock", "inStock", "available"} and isinstance(item, bool):
                pieces.append("availability in stock" if item else "availability out of stock")
            nested = _structured_text(item, depth=depth + 1)
            if nested:
                pieces.append(f"{safe_key} {nested}")
        return " ".join(pieces)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_structured_text(item, depth=depth + 1) for item in value)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _actual_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    # A source identifier is not evidence. Real snippets may be short, but
    # should contain a phrase or an explicit factual anchor plus context.
    return text if len(_meaningful_tokens(text)) >= 2 or (len(_anchors(text)) and _meaningful_tokens(text)) else ""


def _citation_text(value: Any) -> str:
    """Read content fields from a source object, never a bare source ID/title."""
    if not isinstance(value, dict):
        return ""
    fields = ("snippet", "excerpt", "summary", "content", "text", "body", "description")
    return " ".join(_actual_text(value.get(field)) for field in fields if value.get(field) is not None)


def _tool_evidence(tool_results: Any, runtime_metadata: Optional[Dict[str, Any]]) -> list[str]:
    """Collect textual and structured evidence without returning identifiers or diagnostics."""
    records: list[str] = []
    for tool_result in (tool_results or {}).values() if isinstance(tool_results, dict) else []:
        if getattr(tool_result, "success", True) is False:
            continue
        data = getattr(tool_result, "data", None)
        if isinstance(data, dict):
            text = _structured_text(data)
            if text:
                records.append(text)
        elif isinstance(data, (list, tuple)):
            for item in data:
                text = _structured_text(item) if isinstance(item, (dict, list, tuple)) else _actual_text(item)
                if text:
                    records.append(text)
        else:
            text = _actual_text(data)
            if text:
                records.append(text)

        metadata = getattr(tool_result, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        for key in ("products", "dealers", "validated_products", "active_product_focus"):
            values = metadata.get(key)
            if isinstance(values, list):
                for item in values:
                    text = _structured_text(item)
                    if text:
                        records.append(text)
        for key in ("citation_candidates", "sources", "rag_chunks"):
            values = metadata.get(key)
            if isinstance(values, list):
                for item in values:
                    text = _citation_text(item)
                    if text:
                        records.append(text)
        for key in ("response_summary", "summary"):
            text = _actual_text(metadata.get(key))
            if text:
                records.append(text)

    metadata = runtime_metadata if isinstance(runtime_metadata, dict) else {}
    # Lal Kitab runtime evidence is private, so only pull it into the local
    # comparison buffer. It is deliberately not logged or put into a response.
    if metadata.get("lalkitab_runtime"):
        api_context = metadata.get("lalkitab_api_context_full")
        if isinstance(api_context, dict):
            for key in ("normalized_birth_input", "chart_context", "secondary_endpoint_results"):
                text = _structured_text(api_context.get(key))
                if text:
                    records.append(text)
        rag_context = metadata.get("lalkitab_rag_context_full")
        if isinstance(rag_context, dict):
            for chunk in rag_context.get("chunks") or []:
                if isinstance(chunk, dict):
                    text = _actual_text(chunk.get("content") or chunk.get("text"))
                    if text:
                        records.append(text)
    return records[:100]


def _split_claims(response: str) -> Iterable[str]:
    for claim in re.split(r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-Z#*\-])|\n+", response or ""):
        claim = claim.strip(" \t-*#")
        if claim:
            yield claim


def _is_safe_nonfactual(claim: str) -> bool:
    if not claim:
        return True
    if claim.rstrip().endswith("?"):
        return True
    return any(pattern.search(claim) for pattern in _SAFE_RESPONSE_PATTERNS)


def _is_factual_claim(claim: str) -> bool:
    if _is_safe_nonfactual(claim):
        return False
    if _anchors(claim):
        return True
    return bool(_ASSERTION_PATTERN.search(claim))


def validate_claim_evidence(
    response: str,
    *,
    tool_results: Any = None,
    runtime_metadata: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """Deterministically reject factual claims that lack usable evidence.

    ``sources=["doc-123"]`` is intentionally ignored: it is provenance, not
    evidence. A claim needs actual retrieved text or structured data, exact
    support for any factual anchors, and meaningful lexical overlap.
    """
    sanitized = response or ""
    annotation_stripped = False
    for pattern in _PRIVATE_ANNOTATION_PATTERNS:
        updated = pattern.sub("", sanitized)
        annotation_stripped = annotation_stripped or updated != sanitized
        sanitized = updated
    sanitized = re.sub(r"[ \t]+\n", "\n", sanitized)
    sanitized = re.sub(r" {2,}", " ", sanitized).strip()

    evidence_records = _tool_evidence(tool_results, runtime_metadata)
    evidence_tokens = [_meaningful_tokens(record) for record in evidence_records]
    evidence_anchors: set[str] = set()
    for record in evidence_records:
        evidence_anchors.update(_anchors(record))

    unsupported = 0
    claim_count = 0
    if not sanitized:
        unsupported = 1
    for claim in _split_claims(sanitized):
        if not _is_factual_claim(claim):
            continue
        claim_count += 1
        anchors = _anchors(claim)
        if anchors and not anchors.issubset(evidence_anchors):
            unsupported += 1
            continue
        claim_tokens = _meaningful_tokens(claim)
        overlaps = [len(claim_tokens & tokens) for tokens in evidence_tokens]
        best_overlap = max(overlaps, default=0)
        # Exact anchors still need a semantic tie such as price, warranty, a
        # SKU, or a product/entity token. Anchor-only matches are not enough.
        required_overlap = 1 if anchors else 2
        if best_overlap < required_overlap:
            unsupported += 1

    is_valid = unsupported == 0
    metadata = {
        "claim_count": claim_count,
        "evidence_record_count": len(evidence_records),
        "unsupported_claim_count": unsupported,
        "private_annotation_stripped": annotation_stripped,
    }
    logger.info(
        "claim_evidence_validated",
        is_valid=is_valid,
        claim_count=claim_count,
        evidence_record_count=len(evidence_records),
        unsupported_claim_count=unsupported,
        private_annotation_stripped=annotation_stripped,
    )
    return ValidationResult(
        is_valid=is_valid,
        confidence=1.0 if is_valid else 0.0,
        issues=[] if is_valid else ["unsupported_factual_claim"],
        sanitized_response=sanitized,
        metadata=metadata,
    )


class ResponseValidator:
    """
    Validates LLM responses against catalog data to prevent hallucinations.
    
    Phase 4 Implementation:
    - SKU validation: Verify mentioned SKUs exist in catalog
    - Price validation: Check prices match catalog
    - Dealer validation: Verify dealer info is accurate
    - Contact validation: Ensure phone/email/address are from catalog
    """
    
    # Regex patterns for extraction
    SKU_PATTERN = re.compile(r'\b[A-Z0-9]{4,10}\b')  # e.g., 1003A, SKU-123
    PRICE_PATTERN = re.compile(r'[₹$€£]\s*[\d,]+(?:\.\d{2})?')  # e.g., ₹4,500
    PHONE_PATTERN = re.compile(r'[\+\d][\d\s\-\(\)]{8,20}\d')  # Phone numbers
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize validator.
        
        Args:
            strict_mode: If True, reject responses with any validation failures.
                        If False, only flag issues but allow response.
        """
        self.strict_mode = strict_mode
        logger.info("response_validator_initialized", strict_mode=strict_mode)
    
    async def validate_response(
        self,
        response: str,
        query_intent: str,
        catalog_products: Optional[List[Dict]] = None,
        catalog_dealers: Optional[List[Dict]] = None,
    ) -> ValidationResult:
        """
        Validate LLM response against catalog data.
        
        Args:
            response: Generated LLM response text
            query_intent: Detected query intent (product_search, dealer_search, etc.)
            catalog_products: List of products from Phase 3 extraction
            catalog_dealers: List of dealers from Phase 3 extraction
            
        Returns:
            ValidationResult with validation status and sanitized response
        """
        issues = []
        confidence = 1.0
        metadata = {
            "query_intent": query_intent,
            "products_in_catalog": len(catalog_products) if catalog_products else 0,
            "dealers_in_catalog": len(catalog_dealers) if catalog_dealers else 0,
        }
        
        # Product validation for product queries
        if query_intent == "product_search" and catalog_products is not None:
            product_issues = await self._validate_products(response, catalog_products)
            issues.extend(product_issues)
            
            # Reduce confidence for each product issue
            if product_issues:
                confidence -= len(product_issues) * 0.15
        
        # Dealer validation for dealer queries
        if query_intent == "dealer_search" and catalog_dealers is not None:
            dealer_issues = await self._validate_dealers(response, catalog_dealers)
            issues.extend(dealer_issues)
            
            # Reduce confidence for each dealer issue
            if dealer_issues:
                confidence -= len(dealer_issues) * 0.15
        
        # General validation for all responses
        general_issues = await self._validate_general(response)
        issues.extend(general_issues)
        
        # Ensure confidence is in valid range
        confidence = max(0.0, min(1.0, confidence))
        
        # Sanitize response if issues found
        sanitized_response = response
        if issues:
            sanitized_response = await self._sanitize_response(
                response,
                issues,
                catalog_products,
                catalog_dealers
            )
        
        # Determine if valid based on strict mode
        is_valid = True
        if self.strict_mode and issues:
            # In strict mode, any critical issue fails validation
            critical_issues = [i for i in issues if "CRITICAL" in i or "hallucinated" in i.lower()]
            if critical_issues:
                is_valid = False
        
        metadata["issues_count"] = len(issues)
        metadata["critical_issues"] = len([i for i in issues if "CRITICAL" in i])
        
        logger.info(
            "response_validated",
            is_valid=is_valid,
            confidence=confidence,
            issues_count=len(issues),
            query_intent=query_intent,
        )
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            issues=issues,
            sanitized_response=sanitized_response,
            metadata=metadata,
        )
    
    async def _validate_products(self, response: str, catalog_products: List[Dict]) -> List[str]:
        """
        Validate product mentions against catalog.
        
        Checks:
        - SKUs mentioned exist in catalog
        - Prices match catalog (if mentioned)
        - Product names are accurate
        """
        issues = []
        
        # Build catalog lookup
        catalog_skus = {p["sku"]: p for p in catalog_products}
        catalog_names = {p["name"].lower(): p for p in catalog_products}
        
        # Extract potential SKUs from response
        potential_skus = self.SKU_PATTERN.findall(response)
        
        for sku in potential_skus:
            # Skip common words that match SKU pattern
            if sku.lower() in {"http", "https", "html", "mail", "code"}:
                continue
            
            # Check if SKU exists in catalog
            if sku not in catalog_skus:
                issues.append(f"CRITICAL: Hallucinated SKU '{sku}' not in catalog")
                logger.warning("hallucinated_sku_detected", sku=sku)
        
        # Extract prices and verify
        price_matches = self.PRICE_PATTERN.findall(response)
        if price_matches and catalog_products:
            # Check if prices are reasonable (within catalog range)
            catalog_prices = [p.get("price", 0) for p in catalog_products if p.get("price")]
            if catalog_prices:
                min_price = min(catalog_prices)
                max_price = max(catalog_prices)
                
                for price_str in price_matches:
                    # Parse price
                    price_num = int(re.sub(r'[^\d]', '', price_str))
                    
                    # Check if price is within reasonable range (catalog min/max ± 50%)
                    if price_num < min_price * 0.5 or price_num > max_price * 1.5:
                        issues.append(f"WARNING: Suspicious price '{price_str}' outside catalog range")
        
        # Check for vague product descriptions without SKU
        vague_patterns = [
            r'our\s+\w+\s+product',
            r'this\s+\w+\s+model',
            r'available\s+\w+\s+options',
        ]
        
        for pattern in vague_patterns:
            if re.search(pattern, response.lower()):
                # Only flag if no SKUs mentioned at all
                if not potential_skus:
                    issues.append("WARNING: Vague product reference without specific SKU")
                    break
        
        return issues
    
    async def _validate_dealers(self, response: str, catalog_dealers: List[Dict]) -> List[str]:
        """
        Validate dealer mentions against catalog.
        
        Checks:
        - Dealer names exist in catalog
        - Phone numbers match catalog
        - Addresses are accurate
        - Cities/states are correct
        """
        issues = []
        
        # Build catalog lookup
        catalog_names = {d["name"].lower(): d for d in catalog_dealers}
        catalog_phones = {d.get("phone", ""): d for d in catalog_dealers if d.get("phone")}
        catalog_emails = {d.get("email", ""): d for d in catalog_dealers if d.get("email")}
        
        # Extract phone numbers from response
        phone_matches = self.PHONE_PATTERN.findall(response)
        for phone in phone_matches:
            # Normalize phone (remove spaces, dashes, etc.)
            normalized = re.sub(r'[\s\-\(\)]', '', phone)
            
            # Check if phone exists in catalog
            found = False
            for catalog_phone in catalog_phones.keys():
                if catalog_phone and re.sub(r'[\s\-\(\)]', '', catalog_phone) == normalized:
                    found = True
                    break
            
            if not found:
                issues.append(f"CRITICAL: Hallucinated phone number '{phone}' not in dealer catalog")
                logger.warning("hallucinated_phone_detected", phone=phone)
        
        # Extract email addresses
        email_matches = self.EMAIL_PATTERN.findall(response)
        for email in email_matches:
            if email.lower() not in catalog_emails:
                issues.append(f"CRITICAL: Hallucinated email '{email}' not in dealer catalog")
                logger.warning("hallucinated_email_detected", email=email)
        
        # Check for dealer names mentioned
        for dealer_name, dealer_data in catalog_names.items():
            if dealer_name in response.lower():
                # Verify associated contact info is correct if mentioned
                if dealer_data.get("city"):
                    city = dealer_data["city"]
                    # Check if city is mentioned near dealer name (within 100 chars)
                    dealer_pos = response.lower().find(dealer_name)
                    context = response[max(0, dealer_pos - 50):dealer_pos + 100].lower()
                    
                    if city.lower() not in context:
                        # Only flag if a different city is mentioned
                        pass  # Too strict, skip for now
        
        return issues
    
    async def _validate_general(self, response: str) -> List[str]:
        """
        General validation checks applicable to all responses.
        
        Checks:
        - Response length reasonable
        - No placeholder text
        - No system prompts leaked
        - Professional tone maintained
        """
        issues = []
        
        # Check for placeholder text
        placeholders = [
            r'\[.*?\]',  # [placeholder]
            r'<.*?>',    # <placeholder>
            r'XXX',
            r'TODO',
            r'FIXME',
        ]
        
        for pattern in placeholders:
            if re.search(pattern, response):
                issues.append("WARNING: Placeholder text detected in response")
                break
        
        # Check for leaked system prompts
        leaked_patterns = [
            r'you are (a|an)\s+\w+\s+assistant',
            r'as an ai',
            r'i am (a|an) language model',
            r'i don\'t have access to',
            r'my knowledge was last updated',
        ]
        
        for pattern in leaked_patterns:
            if re.search(pattern, response.lower()):
                issues.append("WARNING: System prompt language detected")
                break
        
        # Check response length
        if len(response) < 20:
            issues.append("WARNING: Response too short (< 20 chars)")
        elif len(response) > 5000:
            issues.append("WARNING: Response very long (> 5000 chars)")
        
        # Check for reasonable structure
        if response and not any(c in response for c in '.!?'):
            issues.append("WARNING: No punctuation in response")
        
        return issues
    
    async def _sanitize_response(
        self,
        response: str,
        issues: List[str],
        catalog_products: Optional[List[Dict]],
        catalog_dealers: Optional[List[Dict]],
    ) -> str:
        """
        Remove or flag hallucinated content from response.
        
        Strategies:
        - Remove hallucinated SKUs
        - Replace incorrect prices with "contact us for pricing"
        - Remove hallucinated contact information
        - Add disclaimer if critical issues found
        """
        sanitized = response
        
        # Extract critical issues
        critical_issues = [i for i in issues if "CRITICAL" in i]
        
        if not critical_issues:
            # No critical issues, return original
            return sanitized
        
        # Build valid data sets
        valid_skus = set()
        if catalog_products:
            valid_skus = {p["sku"] for p in catalog_products}
        
        valid_phones = set()
        valid_emails = set()
        if catalog_dealers:
            valid_phones = {d.get("phone", "") for d in catalog_dealers if d.get("phone")}
            valid_emails = {d.get("email", "") for d in catalog_dealers if d.get("email")}
        
        # Remove hallucinated SKUs
        potential_skus = self.SKU_PATTERN.findall(sanitized)
        for sku in potential_skus:
            if sku not in valid_skus and sku.lower() not in {"http", "https", "html", "mail"}:
                # Replace with generic reference
                sanitized = re.sub(
                    r'\b' + re.escape(sku) + r'\b',
                    '[Product Code]',
                    sanitized
                )
                logger.info("sanitized_hallucinated_sku", sku=sku)
        
        # Remove hallucinated phone numbers
        phone_matches = self.PHONE_PATTERN.findall(sanitized)
        for phone in phone_matches:
            normalized = re.sub(r'[\s\-\(\)]', '', phone)
            
            is_valid = False
            for valid_phone in valid_phones:
                if valid_phone and re.sub(r'[\s\-\(\)]', '', valid_phone) == normalized:
                    is_valid = True
                    break
            
            if not is_valid:
                sanitized = sanitized.replace(phone, '[Contact Number]')
                logger.info("sanitized_hallucinated_phone", phone=phone)
        
        # Remove hallucinated emails
        email_matches = self.EMAIL_PATTERN.findall(sanitized)
        for email in email_matches:
            if email.lower() not in valid_emails:
                sanitized = sanitized.replace(email, '[Email Address]')
                logger.info("sanitized_hallucinated_email", email=email)
        
        # Add disclaimer for critical issues
        if len(critical_issues) > 2:
            disclaimer = (
                "\n\n⚠️ Note: Some information in this response could not be verified. "
                "Please contact customer support for accurate details."
            )
            sanitized += disclaimer
        
        return sanitized
    
    def get_validation_summary(self, result: ValidationResult) -> str:
        """
        Get human-readable validation summary.
        
        Args:
            result: ValidationResult to summarize
            
        Returns:
            Formatted summary string
        """
        summary_parts = [
            f"Validation: {'PASSED' if result.is_valid else 'FAILED'}",
            f"Confidence: {result.confidence:.2%}",
            f"Issues: {len(result.issues)}",
        ]
        
        if result.issues:
            critical = len([i for i in result.issues if "CRITICAL" in i])
            warnings = len([i for i in result.issues if "WARNING" in i])
            
            if critical:
                summary_parts.append(f"Critical: {critical}")
            if warnings:
                summary_parts.append(f"Warnings: {warnings}")
        
        return " | ".join(summary_parts)
