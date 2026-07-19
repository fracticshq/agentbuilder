"""Deterministic claim-level evidence validation regressions."""

from tools.types import ToolResult

from app.services.response_validator import validate_claim_evidence


def test_supported_retrieval_claim_passes_and_private_annotation_is_removed():
    result = validate_claim_evidence(
        "The warranty coverage is 2 years. [evidence: warranty-terms-v1]",
        tool_results={
            "knowledge": ToolResult(
                success=True,
                data="Warranty coverage is 2 years from the original purchase date.",
                metadata={"sources": ["warranty-terms-v1"]},
            )
        },
    )

    assert result.is_valid is True
    assert result.sanitized_response == "The warranty coverage is 2 years."
    assert result.metadata["private_annotation_stripped"] is True
    assert result.metadata["unsupported_claim_count"] == 0


def test_bare_source_identifier_cannot_support_a_factual_claim():
    result = validate_claim_evidence(
        "The warranty coverage is 2 years.",
        tool_results={
            "knowledge": ToolResult(
                success=True,
                data=None,
                metadata={"sources": ["warranty-terms-v1"]},
            )
        },
    )

    assert result.is_valid is False
    assert result.issues == ["unsupported_factual_claim"]
    assert result.metadata["evidence_record_count"] == 0


def test_structured_product_price_and_stock_are_usable_evidence_without_citation_text():
    result = validate_claim_evidence(
        "Bookshelf Speaker costs ₹999 and is in stock.",
        tool_results={
            "catalog": ToolResult(
                success=True,
                data=None,
                metadata={
                    "products": [
                        {
                            "name": "Bookshelf Speaker",
                            "price": 999,
                            "currency": "INR",
                            "in_stock": True,
                        }
                    ]
                },
            )
        },
    )

    assert result.is_valid is True


def test_wrong_factual_anchor_fails_closed_even_when_other_product_evidence_exists():
    result = validate_claim_evidence(
        "Bookshelf Speaker costs ₹799 and is in stock.",
        tool_results={
            "catalog": ToolResult(
                success=True,
                data=None,
                metadata={"products": [{"name": "Bookshelf Speaker", "price": 999, "in_stock": True}]},
            )
        },
    )

    assert result.is_valid is False
    assert result.metadata["unsupported_claim_count"] == 1


def test_greetings_questions_and_safe_abstentions_need_no_evidence():
    for response in (
        "Hello! How can I help?",
        "Could you share the product SKU?",
        "I don’t have enough verified information to answer that reliably. Please try again.",
        "I can’t safely give a Lal Kitab prediction or remedy until I can verify the calculated chart.",
    ):
        result = validate_claim_evidence(response)
        assert result.is_valid is True, response
