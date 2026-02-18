"""
Shopify MCP Client - Direct Storefront API calls via GraphQL and Admin API.
Fully async using httpx.
"""
import os
import json
import httpx
from dotenv import load_dotenv
import structlog

# Load .env from agentbuilder root
_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
load_dotenv(_root_env)


logger = structlog.get_logger(__name__)

class ShopifyMCPClient:
    """Direct Shopify Storefront and Admin API client."""

    def __init__(self, shop_url: str = None, storefront_token: str = None, admin_token: str = None, cart_id: str = None, api_version: str = None):
        self.shop_url = shop_url or os.getenv("SHOPIFY_SHOP_URL")
        self.storefront_token = storefront_token or os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN")
        self.admin_token = admin_token or os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN")
        self.api_version = api_version or os.getenv("SHOPIFY_API_VERSION")


        if not self.shop_url or not self.storefront_token:
            raise ValueError("Missing SHOPIFY_SHOP_URL or storefront_token")

        self.storefront_endpoint = f"https://{self.shop_url}/api/{self.api_version}/graphql.json"
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": self.storefront_token,
        }
        if self.admin_token:
            self.admin_endpoint = f"https://{self.shop_url}/admin/api/{self.api_version}"
            self.admin_headers = {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.admin_token
            }

        # Initialize cart_id so it's always available
        self.cart_id = cart_id

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
            logger.info("checkout_url_available", url=cart['checkoutUrl'])
        return cart

    async def add_to_cart(self, cart_id: str, variant_id: str, quantity: int = 1) -> dict:
        # full cart id required

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
            userErrors { field message }
          }
        }
        """
        variables = {
            "cartId": cart_id,
            "lines": [{"merchandiseId": variant_id, "quantity": quantity}]
        }
        data = await self._graphql(gql, variables)
        result = data["data"]["cartLinesAdd"]
        if result.get("userErrors"):
            return {"error": result["userErrors"], "success": False}
        
        cart = result["cart"]
        # Show checkout URL after adding items
        if cart.get("checkoutUrl"):
            logger.info("checkout_url_available", url=cart['checkoutUrl'])
        return cart

    async def remove_from_cart(self, cart_id: str, line_ids: list) -> dict:
        gql = """
        mutation cartLinesRemove($cartId: ID!, $lineIds: [ID!]!) {
          cartLinesRemove(cartId: $cartId, lineIds: $lineIds) {
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
            userErrors { field message }
          }
        }
        """
        variables = {
            "cartId": cart_id,
            "lineIds": line_ids
        }
        data = await self._graphql(gql, variables)
        result = data["data"]["cartLinesRemove"]
        if result.get("userErrors"):
            return {"error": result["userErrors"], "success": False}
        return result["cart"]

    async def update_cart_quantity(self, cart_id: str, line_id: str, quantity: int) -> dict:
        gql = """
        mutation cartLinesUpdate($cartId: ID!, $lines: [CartLineUpdateInput!]!) {
          cartLinesUpdate(cartId: $cartId, lines: $lines) {
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
            userErrors { field message }
          }
        }
        """
        variables = {
            "cartId": cart_id,
            "lines": [{"id": line_id, "quantity": quantity}]
        }
        data = await self._graphql(gql, variables)
        result = data["data"]["cartLinesUpdate"]
        if result.get("userErrors"):
            return {"error": result["userErrors"], "success": False}
        return result["cart"]
    async def get_cart(self, cart_id: str) -> dict:
        """Fetch current cart contents via Storefront API"""
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
            raise ValueError("Missing SHOPIFY_ADMIN_ACCESS_TOKEN for order queries")
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
    
    # ---- Async connection interface ---- 
    async def connect(self): 
        """No-op for direct API client.""" 
        pass 
    async def disconnect(self): 
        """No-op for direct API client.""" 
        pass



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
            cart_id = cart.get("id", "")
            self.cart_id = cart_id
            return cart
        
        elif tool_name == "add_to_cart_tool":
            cart_id = tool_input.get("cartId") or self.cart_id
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

        elif tool_name == "remove_from_cart_tool":
            cart_id = tool_input.get("cartId") or self.cart_id
            line_ids = tool_input.get("lineIds")
            if not cart_id or not line_ids:
                raise ValueError("remove_from_cart_tool requires 'cartId' and 'lineIds'")
            # Ensure line_ids is a list
            if isinstance(line_ids, str):
                line_ids = [line_ids]
            return await self.remove_from_cart(cart_id, line_ids)

        elif tool_name == "update_cart_quantity_tool":
            cart_id = tool_input.get("cartId") or self.cart_id
            line_id = tool_input.get("lineId")
            quantity = tool_input.get("quantity")
            if not cart_id or not line_id or quantity is None:
                raise ValueError("update_cart_quantity_tool requires 'cartId', 'lineId', and 'quantity'")
            return await self.update_cart_quantity(cart_id, line_id, int(quantity))
        
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
