from app.services.message_service import _deduplicate_entities


def test_deduplicate_entities_uses_fallback_identity_keys():
    entities = [
        {"sku": "EOS-CHR-538RB", "name": "Diamond Shower"},
        {"sku": "EOS-CHR-538RB", "name": "Diamond Shower"},
        {"product_id": "prod-491", "name": "Overhead Shower"},
        {"name": "Hand Shower"},
        {"name": "Hand Shower"},
    ]

    deduplicated = _deduplicate_entities(
        entities,
        "id",
        "sku",
        "product_id",
        "variant_id",
        "name",
    )

    assert deduplicated == [
        {"sku": "EOS-CHR-538RB", "name": "Diamond Shower"},
        {"product_id": "prod-491", "name": "Overhead Shower"},
        {"name": "Hand Shower"},
    ]
