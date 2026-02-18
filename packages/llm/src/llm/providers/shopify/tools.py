"""
Shopify Tools - Wrapper for ShopifyMCPClient to be used by the Orchestrator.
"""
from typing import Dict, Any, List, Optional
from tools.types import BaseTool, ToolResult
from llm.providers.shopify.shopify_mcp_client import ShopifyMCPClient


class SearchProductsTool(BaseTool):
    name = "search_products_tool"
    description = "Search for products in the Shopify store. Returns a list of products with details."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword (e.g., 'snowboard', 'wax')"}
        },
        "required": ["query"]
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self, query: str) -> ToolResult:
        try:
            products = await self.client.search_products(query)
            return ToolResult(
                success=True, 
                data=products,
                metadata={"products": products if isinstance(products, list) else []}
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class CreateCartTool(BaseTool):
    name = "create_cart_tool"
    description = "Create a new shopping cart."
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self) -> ToolResult:
        try:
            cart = await self.client.create_cart()
            return ToolResult(
                success=True, 
                data=cart,
                metadata={"cart_id": cart.get("id"), "checkout_url": cart.get("checkoutUrl")}
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class AddToCartTool(BaseTool):
    name = "add_to_cart_tool"
    description = "Add a product variant to the cart."
    parameters_schema = {
        "type": "object",
        "properties": {
            "cartId": {"type": "string", "description": "The ID of the cart (optional)"},
            "merchandiseId": {"type": "string", "description": "The variant ID of the product to add"},
            "quantity": {"type": "integer", "description": "Quantity to add (default 1)"}
        },
        "required": ["merchandiseId"]
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self, merchandiseId: str, cartId: Optional[str] = None, quantity: int = 1) -> ToolResult:
        try:
            target_cart_id = cartId or self.client.cart_id
            if not target_cart_id:
                new_cart = await self.client.create_cart()
                target_cart_id = new_cart["id"]
                self.client.cart_id = target_cart_id
            
            cart = await self.client.add_to_cart(target_cart_id, merchandiseId, quantity)
            self.client.cart_id = cart["id"]
            
            return ToolResult(
                success=True, 
                data=cart,
                metadata={
                    "cart_id": cart["id"],
                    "checkout_url": cart.get("checkoutUrl"),
                    "lines": cart.get("lines", {}).get("edges", [])
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class GetCartTool(BaseTool):
    name = "get_cart_tool"
    description = "Get the current contents of the cart including line item IDs."
    parameters_schema = {
        "type": "object",
        "properties": {
            "cartId": {"type": "string", "description": "The ID of the cart (optional)"}
        },
        "required": []
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self, cartId: Optional[str] = None) -> ToolResult:
        try:
            target_cart_id = cartId or self.client.cart_id
            if not target_cart_id:
                return ToolResult(success=False, data=None, error="No cart found. Use create_cart_tool first.")
                
            cart = await self.client.get_cart(target_cart_id)
            return ToolResult(
                success=True, 
                data=cart,
                metadata={
                    "cart_id": cart["id"],
                    "checkout_url": cart.get("checkoutUrl")
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class RemoveFromCartTool(BaseTool):
    name = "remove_from_cart_tool"
    description = "Remove items from the cart using their line IDs."
    parameters_schema = {
        "type": "object",
        "properties": {
            "cartId": {"type": "string", "description": "The ID of the cart"},
            "lineIds": {"type": "array", "items": {"type": "string"}, "description": "List of line item IDs to remove"}
        },
        "required": ["cartId", "lineIds"]
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self, cartId: str, lineIds: List[str]) -> ToolResult:
        try:
            cart = await self.client.remove_from_cart(cartId, lineIds)
            return ToolResult(
                success=True, 
                data=cart,
                metadata={"cart_id": cart["id"], "checkout_url": cart.get("checkoutUrl")}
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class UpdateCartQuantityTool(BaseTool):
    name = "update_cart_quantity_tool"
    description = "Update the quantity of a line item in the cart."
    parameters_schema = {
        "type": "object",
        "properties": {
            "cartId": {"type": "string", "description": "The ID of the cart"},
            "lineId": {"type": "string", "description": "The ID of the line item"},
            "quantity": {"type": "integer", "description": "New quantity (0 to remove)"}
        },
        "required": ["cartId", "lineId", "quantity"]
    }

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self, cartId: str, lineId: str, quantity: int) -> ToolResult:
        try:
            cart = await self.client.update_cart_quantity(cartId, lineId, quantity)
            return ToolResult(
                success=True, 
                data=cart,
                metadata={"cart_id": cart["id"], "checkout_url": cart.get("checkoutUrl")}
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class GetShopInfoTool(BaseTool):
    name = "get_shop_info_tool"
    description = "Get status and information about the Shopify store."
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, client: ShopifyMCPClient):
        self.client = client

    async def run(self) -> ToolResult:
        try:
            info = await self.client.get_shop_info()
            return ToolResult(success=True, data=info)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class ShopifyToolSet:
    """Registry of all Shopify tools."""
    
    def __init__(self, client: ShopifyMCPClient):
        self.client = client
        self.tools = [
            SearchProductsTool(client),
            CreateCartTool(client),
            AddToCartTool(client),
            GetCartTool(client),
            RemoveFromCartTool(client),
            UpdateCartQuantityTool(client),
            GetShopInfoTool(client)
        ]

    def get_tools(self):
        """Return initialized tools."""
        return self.tools
