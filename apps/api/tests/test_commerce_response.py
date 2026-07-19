from types import SimpleNamespace

from app.services.commerce_response import (
    _deduplicate_entities,
    _prepare_commerce_products_for_response,
    _safe_commerce_cart,
)


def test_prepare_commerce_products_normalizes_currency_and_groups_variants():
    products = [
        {
            "id": "black",
            "sku": "speaker-black",
            "name": "Home Speaker – Black",
            "price": "4190000",
            "image": "https://example.test/black.jpg",
            "product_url": "https://shop.example.test/products/home-speaker?variant=black",
        },
        {
            "id": "white",
            "sku": "speaker-white",
            "name": "Home Speaker – White",
            "price": 4290000,
            "image": "https://example.test/white.jpg",
            "product_url": "https://shop.example.test/products/home-speaker?variant=white",
        },
    ]

    [card] = _prepare_commerce_products_for_response(
        products,
        {"commerce": {"default_currency": "inr", "currency_policy": "catalog_first_config_fallback"}},
    )

    assert card["currency"] == "INR"
    assert card["currency_source"] == "commerce.default_currency"
    assert card["price_unit"] == "minor"
    assert card["product_url"] == "https://shop.example.test/products/home-speaker?variant=black"
    assert card["variant_count"] == 2
    assert [variant["variant_title"] for variant in card["variants"]] == ["Black", "White"]


def test_safe_commerce_cart_uses_tool_metadata_and_removes_checkout_fragment():
    cart = _safe_commerce_cart(
        {},
        {
            "cart": SimpleNamespace(metadata={
                "commerce_action": {
                    "cart": {
                        "cartId": "cart-123",
                        "checkoutUrl": "https://shop.example.test/cart/123?locale=en#payment",
                        "lines": [{"variant_id": "black", "quantity": 1}],
                    }
                }
            }),
        },
        allowed_shop_url="https://shop.example.test",
    )

    assert cart == {
        "cart_id": "cart-123",
        "checkout_url": "https://shop.example.test/cart/123?locale=en",
        "cart_lines": [{"variant_id": "black", "quantity": 1}],
    }


def test_deduplicate_entities_falls_back_to_stable_json_identity():
    deduplicated = _deduplicate_entities(
        [
            {"sku": "SKU-1", "name": "First"},
            {"sku": "SKU-1", "name": "First duplicate"},
            {"name": "Unkeyed", "details": {"color": "black"}},
            {"details": {"color": "black"}, "name": "Unkeyed"},
        ],
        "id",
        "sku",
    )

    assert deduplicated == [
        {"sku": "SKU-1", "name": "First"},
        {"name": "Unkeyed", "details": {"color": "black"}},
    ]
