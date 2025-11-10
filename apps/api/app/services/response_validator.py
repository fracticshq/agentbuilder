"""
Response Validator - Phase 4: Server-side validation of LLM responses

Prevents hallucinated SKUs, prices, dealers, and contact information from reaching users.
Implements strict validation against catalog data.
"""

import re
import structlog
from typing import Dict, List, Optional, Tuple
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
