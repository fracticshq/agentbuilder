"""
Shopify MCP Client - Direct Storefront API calls via GraphQL and Admin API.
Fully async using httpx.
"""
import os
import json
import httpx
from dotenv import load_dotenv

# Load .env from agentbuilder root
_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
load_dotenv(_root_env)


class ShopifyMCPClient:
    """Direct Shopify Storefront and Admin API client."""

    def __init__(self):
        self.shop_url = os.getenv("SHOPIFY_SHOP_URL")
        self.storefront_token = os.getenv("SHOPIFY_STOREFRONT_API_ACCESS_TOKEN")
        self.admin_token = os.getenv("SHOPIFY_STOREFRONT_ADMIN_ACCESS_TOKEN")


        if not self.shop_url or not self.storefront_token:
            raise ValueError(f"Missing SHOPIFY_SHOP_URL or token. Got: {self.shop_url}, {'***' if self.storefront_token else None}")

        self.storefront_endpoint = f"https://{self.shop_url}/api/2026-01/graphql.json"
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": self.storefront_token,
        }
        if self.admin_token:
            self.admin_endpoint = f"https://{self.shop_url}/admin/api/2026-01"
            self.admin_headers = {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.admin_token
            }

        # Initialize cart_id so it's always available
        self.cart_id = None

    # ---- GraphQL helper ----
    async def _graphql(self, query: str, variables: dict = None) -> dict:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.storefront_endpoint, headers=self.storefront_headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL error: {data['errors']}")
            return data

    # ---- Tools ----

    async def search_products(self, query: str, limit: int = 10) -> list:
        if not query or not query.strip():
            query = "*"  # Return all products when no query given

        gql = """
        query SearchProducts($query: String!, $first: Int!) {
          products(first: $first, query: $query) {
            edges {
              node {
                id
                title
                description
                priceRange {
                  minVariantPrice { amount currencyCode }
                }
                variants(first: 1) {
                  edges { node { id } }
                }
              }
            }
          }
        }
        """
        data = await self._graphql(gql, {"query": query, "first": limit})
        products = []
        for edge in data["data"]["products"]["edges"]:
            node = edge["node"]
            products.append({
                "id": node["id"],
                "title": node["title"],
                "description": node["description"],
                "price": node["priceRange"]["minVariantPrice"]["amount"],
                "currency": node["priceRange"]["minVariantPrice"]["currencyCode"],
                "variant_id": node["variants"]["edges"][0]["node"]["id"] if node["variants"]["edges"] else None,
            })
        return products if products else "No products found"

    async def get_product(self, product_id: str) -> dict:
        gql = """
        query GetProduct($id: ID!) {
          product(id: $id) {
            id
            title
            description
            priceRange {
              minVariantPrice { amount currencyCode }
              maxVariantPrice { amount currencyCode }
            }
            variants(first: 10) {
              edges { node { id title sku availableForSale } }
            }
            images(first: 5) {
              edges { node { src altText } }
            }
          }
        }
        """
        data = await self._graphql(gql, {"id": product_id})
        return data["data"]["product"]

    async def create_cart(self) -> dict:
        gql = """
        mutation cartCreate {
          cartCreate {
            cart { id checkoutUrl }
          }
        }
        """
        data = await self._graphql(gql)
        cart = data["data"]["cartCreate"]["cart"]
        # Show checkout URL so user can see cart on web
        if cart.get("checkoutUrl"):
            print(f"\n🔗 Checkout URL → {cart['checkoutUrl']}")
        return cart

    async def add_to_cart(self, cart_id: str, variant_id: str, quantity: int = 1) -> dict:
        # Strip ?key=... from cart ID — Shopify GraphQL doesn't accept it
        cart_id = cart_id.split("?")[0]

        gql = """
        mutation cartLinesAdd($cartId: ID!, $lines: [CartLineInput!]!) {
          cartLinesAdd(cartId: $cartId, lines: $lines) {
            cart {
              id
              checkoutUrl
              lines(first: 10) {
                edges {
                  node {
                    id
                    quantity
                    merchandise {
                      ... on ProductVariant {
                        id
                        title
                        product { title }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "cartId": cart_id,
            "lines": [{"merchandiseId": variant_id, "quantity": quantity}]
        }
        data = await self._graphql(gql, variables)
        cart = data["data"]["cartLinesAdd"]["cart"]
        # Show checkout URL after adding items
        if cart.get("checkoutUrl"):
            print(f"\n🔗 Checkout URL → {cart['checkoutUrl']}")
        return cart
    async def get_cart(self, cart_id: str) -> dict:
        """Fetch current cart contents via Storefront API"""
        cart_id = cart_id.split("?")[0]
        gql = """
        query getCart($id: ID!) {
        cart(id: $id) {
            id
            checkoutUrl
            lines(first: 10) {
            edges {
                node {
                id
                quantity
                merchandise {
                    ... on ProductVariant {
                    id
                    title
                    product { title }
                    }
                }
                }
            }
            }
        }
        }
        """
        data = await self._graphql(gql, {"id": cart_id})
        return data["data"]["cart"]

    async def search_orders(self, limit: int = 10) -> list:
        """Retrieve orders (Admin API required)."""
        if not self.admin_token:
            raise ValueError("Missing SHOPIFY_STOREFRONT_ADMIN_ACCESS_TOKEN for order queries")
        url = f"{self.admin_endpoint}/orders.json?limit={limit}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=self.admin_headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("orders", [])

    async def get_order(self, order_id: str) -> dict:
        """Retrieve a single order by ID (Admin API required)."""
        if not self.admin_token:
            raise ValueError("Missing SHOPIFY_ADMIN_ACCESS_TOKEN for order queries")
        url = f"{self.admin_endpoint}/orders/{order_id}.json"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=self.admin_headers)
            resp.raise_for_status()
            return resp.json().get("order", {})

    async def get_shop_info(self) -> dict:
        gql = """
        {
          shop {
            name
            description
            primaryDomain {
              url
              host
            }
            paymentSettings {
              currencyCode
            }
          }
        }
        """
        data = await self._graphql(gql)
        return data.get("data", {}).get("shop", {})



    # ---- Tool router ----
    async def call_tool(self, tool_name: str, tool_input: dict):
        if tool_name == "search_products_tool":
            return await self.search_products(tool_input.get("query", ""))
        
        elif tool_name == "get_product_tool":
            product_id = tool_input.get("product_id") or tool_input.get("id")
            if not product_id:
                raise ValueError("get_product_tool requires 'product_id' or 'id'")
            return await self.get_product(product_id)
        
        elif tool_name == "search_orders_tool":
            return await self.search_orders(tool_input.get("limit", 10))
        
        elif tool_name == "get_order_tool":
            order_id = tool_input.get("order_id") or tool_input.get("id")
            if not order_id:
                raise ValueError("get_order_tool requires 'order_id'")
            return await self.get_order(order_id)
        
        elif tool_name == "create_cart_tool":
            cart = await self.create_cart()
            # ✅ Store only global cart ID (strip ?key=...)
            cart_id = cart.get("id", "").split("?")[0]
            self.cart_id = cart_id
            return cart
        
        elif tool_name == "add_to_cart_tool":
            cart_id = tool_input.get("cartId") or self.cart_id
            if cart_id:
                cart_id = cart_id.split("?")[0]
            variant_id = tool_input.get("merchandiseId") or tool_input.get("variant_id")
            quantity = tool_input.get("quantity", 1)

            if not cart_id or not variant_id:
                raise ValueError("add_to_cart_tool requires 'cartId' and 'merchandiseId' / 'variant_id'")

            return await self.add_to_cart(cart_id, variant_id, quantity)
        
        elif tool_name == "get_cart_tool":
            cart_id = tool_input.get("cartId") or self.cart_id
            if not cart_id:
                raise ValueError("get_cart_tool requires 'cartId'")
            return await self.get_cart(cart_id)
        
        elif tool_name == "get_shop_info_tool":
            return await self.get_shop_info()
        
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
