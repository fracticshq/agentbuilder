"""P5 vertical-scope regression coverage for the deterministic firewall."""

from app.services.capability_firewall import CapabilityFirewall


def test_generic_agents_do_not_inherit_bathware_vocabulary():
    firewall = CapabilityFirewall()
    contract = firewall.build_contract(
        brand_slug="acme-bathware",
        agent_record={"brand_name": "Acme Bathware", "name": "Faucet Helper"},
        agent_config={"domain": {"type": "generic"}},
    )

    decision = firewall.evaluate("show a commode and recommend lunch", contract)

    assert decision.action == "block"
    assert decision.safe_query == ""


def test_explicit_bathware_vertical_keeps_mixed_scope_filtering():
    firewall = CapabilityFirewall()
    contract = firewall.build_contract(
        brand_slug="acme",
        agent_config={"domain": {"type": "ecommerce", "verticals": ["bathware"]}},
    )

    decision = firewall.evaluate("show a commode and recommend lunch", contract)

    assert decision.action == "filter"
    assert decision.safe_query == "show a commode"


def test_generic_commerce_terms_remain_in_scope_without_a_vertical_profile():
    firewall = CapabilityFirewall()
    contract = firewall.build_contract(brand_slug="acme", agent_config={"domain": {"type": "generic"}})

    decision = firewall.evaluate("what is the warranty for this product", contract)

    assert decision.action == "allow"
