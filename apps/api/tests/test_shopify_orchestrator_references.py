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


def test_rerank_products_uses_full_constraints_not_only_shopify_order():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools())
    orchestrator.last_user_query = "show me heart drop earrings for wedding under 1500"
    orchestrator.last_constraints = orchestrator._extract_shopping_constraints(orchestrator.last_user_query)
    products = [
        product(1, "Plain Earrings", "gid://shopify/ProductVariant/1", 120000),
        product(2, "Heart Drop Wedding Earrings", "gid://shopify/ProductVariant/2", 140000),
    ]

    ranked = orchestrator._rerank_products(products)

    assert ranked[0]["name"] == "Heart Drop Wedding Earrings"
    assert "heart" in ranked[0]["matched_constraints"]
    assert "under budget 1500" in ranked[0]["matched_constraints"]
    assert "over budget 1500" not in ranked[0]["missing_constraints"]
    assert ranked[0]["match_score"] > ranked[1]["match_score"]


def test_reference_add_without_focus_asks_for_clarification_not_tool_call():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools(update_cart=FakeUpdateCartTool()))
    orchestrator.conversation = [{"role": "user", "content": "add this product to cart"}]

    result = orchestrator._get_confirmed_cart_add()

    assert result is None
    assert orchestrator.pending_clarification_response
    assert orchestrator.resolved_reference["status"] == "no_focus"


def test_active_focus_prompt_displays_minor_unit_prices_as_rupees():
    orchestrator, _ = make_orchestrator([
        product(1, "Heart Drop Earrings", "gid://shopify/ProductVariant/1", 149900),
    ])

    prompt = orchestrator._get_combined_system_prompt()

    assert "price: 1499" in prompt
    assert "price: 149900" not in prompt
