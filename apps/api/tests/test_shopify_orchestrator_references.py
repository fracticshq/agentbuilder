from types import SimpleNamespace

import pytest

from agent_runtime.orchestrator_shopify import ShopifyOrchestrator
from tools.types import ToolResult


class FakeLLM:
    async def generate(self, prompt, system_prompt=None):
        return SimpleNamespace(content="Done.")


class FakeUpdateCartTool:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(
            success=True,
            data={"ok": True},
            metadata={
                "cart": {
                    "cart_id": "cart-1",
                    "checkout_url": "https://checkout.example",
                    "line_items": [],
                }
            },
        )


class FakeTools(dict):
    pass


def make_orchestrator(products):
    update_cart = FakeUpdateCartTool()
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools(update_cart=update_cart))
    orchestrator.active_product_focus = products
    orchestrator.last_searched = {
        str(product["name"]).lower(): product["variant_id"]
        for product in products
    }
    return orchestrator, update_cart


def product(rank, name, variant_id, price):
    return {
        "rank": rank,
        "name": name,
        "title": name,
        "variant_id": variant_id,
        "id": variant_id,
        "price": price,
        "currency": "INR",
    }


@pytest.mark.asyncio
async def test_add_this_product_uses_active_top_product():
    orchestrator, update_cart = make_orchestrator([
        product(1, "Heart Drop Earrings", "gid://shopify/ProductVariant/1", 149900),
        product(2, "Pearl Earrings", "gid://shopify/ProductVariant/2", 99900),
    ])
    orchestrator.conversation = [{"role": "user", "content": "add this product to the cart"}]

    result = orchestrator._get_confirmed_cart_add()

    assert result["tool_name"] == "update_cart"
    assert result["tool_input"]["add_items"][0]["product_variant_id"] == "gid://shopify/ProductVariant/1"
    assert orchestrator.resolved_reference["status"] == "resolved"
    assert update_cart.calls == []


@pytest.mark.asyncio
async def test_add_second_one_resolves_ranked_product():
    orchestrator, _ = make_orchestrator([
        product(1, "Heart Drop Earrings", "gid://shopify/ProductVariant/1", 149900),
        product(2, "Pearl Earrings", "gid://shopify/ProductVariant/2", 99900),
    ])
    orchestrator.conversation = [{"role": "user", "content": "add the second one"}]

    result = orchestrator._get_confirmed_cart_add()

    assert result["tool_input"]["add_items"][0]["product_variant_id"] == "gid://shopify/ProductVariant/2"
    assert "ordinal" in orchestrator.resolved_reference["reason"].lower()


@pytest.mark.asyncio
async def test_add_cheaper_one_picks_lowest_price_product():
    orchestrator, _ = make_orchestrator([
        product(1, "Heart Drop Earrings", "gid://shopify/ProductVariant/1", 149900),
        product(2, "Pearl Earrings", "gid://shopify/ProductVariant/2", 99900),
    ])
    orchestrator.conversation = [{"role": "user", "content": "add the cheaper one"}]

    result = orchestrator._get_confirmed_cart_add()

    assert result["tool_input"]["add_items"][0]["product_variant_id"] == "gid://shopify/ProductVariant/2"
    assert "lowest-price" in orchestrator.resolved_reference["reason"]


def test_catalog_capture_preserves_tool_validated_order_and_metadata():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools())
    orchestrator.last_user_query = "show me heart drop earrings for wedding under 1500"
    orchestrator.last_search_query = orchestrator.last_user_query
    tool_products = [
        product(1, "Plain Earrings", "gid://shopify/ProductVariant/1", 120000),
        product(2, "Heart Drop Wedding Earrings", "gid://shopify/ProductVariant/2", 140000),
    ]
    result = ToolResult(
        success=True,
        data="",
        metadata={
            "products": tool_products,
            "commerce_intent": {"budget": {"operator": "max", "amount": 1500, "currency": None}},
            "rerank_results": [{"rank": 1, "name": "Plain Earrings"}],
        },
    )

    orchestrator._capture_result_state("search_catalog", result)

    assert [p["name"] for p in result.metadata["products"]] == [
        "Plain Earrings",
        "Heart Drop Wedding Earrings",
    ]
    assert orchestrator.active_product_focus[0]["name"] == "Plain Earrings"
    assert orchestrator.last_constraints == result.metadata["commerce_intent"]
    assert orchestrator.rerank_results == result.metadata["rerank_results"]
    assert result.data.splitlines()[1].startswith("1. Plain Earrings")


def test_reference_add_without_focus_asks_for_clarification_not_tool_call():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools(update_cart=FakeUpdateCartTool()))
    orchestrator.conversation = [{"role": "user", "content": "add this product to cart"}]

    result = orchestrator._get_confirmed_cart_add()

    assert result is None
    assert orchestrator.pending_clarification_response
    assert orchestrator.resolved_reference["status"] == "no_focus"


def test_active_focus_prompt_displays_minor_unit_prices_with_product_currency():
    orchestrator, _ = make_orchestrator([
        product(1, "Heart Drop Earrings", "gid://shopify/ProductVariant/1", 149900),
    ])

    prompt = orchestrator._get_combined_system_prompt()

    assert "price: INR 1,499" in prompt
    assert "price: 149900" not in prompt
