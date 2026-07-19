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


def test_catalog_capture_applies_configured_default_only_currency_to_prompt_and_cards():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools())
    orchestrator._initialize_session_state(
        chat_history=None,
        context={"commerce": {"default_currency": "INR", "currency_policy": "default_only"}},
    )
    result = ToolResult(
        success=True,
        data="",
        metadata={
            "products": [
                {
                    "rank": 1,
                    "name": "Klipsch Nashville Portable Bluetooth Speaker",
                    "variant_id": "gid://shopify/ProductVariant/1",
                    "id": "gid://shopify/ProductVariant/1",
                    "price": 2210000,
                    "currency": "USD",
                    "currency_source": "product",
                }
            ],
        },
    )

    orchestrator._capture_result_state("search_catalog", result)

    product_card = result.metadata["products"][0]
    assert product_card["currency"] == "INR"
    assert product_card["currency_source"] == "commerce.default_currency"
    assert "INR 22,100" in result.data
    assert "USD" not in result.data


def test_session_focus_applies_configured_default_only_currency():
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools())

    orchestrator._initialize_session_state(
        chat_history=None,
        context={
            "commerce": {"default_currency": "INR", "currency_policy": "default_only"},
            "session_state": {
                "active_product_focus": [
                    {
                        "rank": 1,
                        "name": "Klipsch Detroit Portable Bluetooth Speaker",
                        "variant_id": "gid://shopify/ProductVariant/1",
                        "price": 4290000,
                        "currency": "USD",
                    }
                ]
            },
        },
    )

    prompt = orchestrator._get_combined_system_prompt()

    assert orchestrator.active_product_focus[0]["currency"] == "INR"
    assert "price: INR 42,900" in prompt
    assert "USD" not in prompt


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


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", ["two", 0, -1])
async def test_invalid_cart_quantity_never_defaults_to_a_mutation(quantity):
    update_cart = FakeUpdateCartTool()
    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools(update_cart=update_cart))

    result = await orchestrator._execute_tool_action(
        "update_cart",
        {
            "add_items": [{
                "product_variant_id": "gid://shopify/ProductVariant/1",
                "quantity": quantity,
            }],
        },
    )

    assert result.success is False
    assert update_cart.calls == []
    assert "commerce service" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_tool_exception_does_not_return_diagnostic_to_the_orchestrator():
    class ExplodingTool:
        async def run(self, **_kwargs):
            raise RuntimeError("Authorization: Bearer secret-shopify-token")

    orchestrator = ShopifyOrchestrator(FakeLLM(), FakeTools(search_catalog=ExplodingTool()))
    result = await orchestrator._execute_tool_action("search_catalog", {"query": "earrings"})

    assert result.success is False
    assert "secret-shopify-token" not in (result.error or "")
    assert "commerce service" in (result.error or "").lower()
