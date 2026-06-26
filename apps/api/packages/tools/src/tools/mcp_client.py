import httpx
import uuid
import json
from typing import Any, Dict, List, Optional
import structlog
from .types import BaseTool, ToolResult

logger = structlog.get_logger(__name__)

class McpTool(BaseTool):
    """Dynamic tool instance for a remote Model Context Protocol (MCP) tool."""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: Dict[str, Any],
        mcp_endpoint: str,
        session_id: str,
        headers: Dict[str, str] = None
    ):
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema
        self.mcp_endpoint = mcp_endpoint
        self.session_id = session_id
        self.headers = headers or {}
        
    async def run(self, **kwargs) -> ToolResult:
        """Execute the remote MCP tool via JSON-RPC."""
        if kwargs is None:
            kwargs = {}
        kwargs = self._normalize_arguments(kwargs)

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": str(uuid.uuid4()),
            "params": {
                "name": self.name,
                "arguments": kwargs
            }
        }
        
        request_headers = {
            "Content-Type": "application/json",
            "x-session-id": self.session_id
        }
        request_headers.update(self.headers)
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.mcp_endpoint, json=payload, headers=request_headers)
                response.raise_for_status()
                data = response.json()
                
                # Handle standard JSON-RPC errors
                if "error" in data:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=data["error"].get("message", str(data["error"]))
                    )
                
                # Extract results from Shopify MCP response format
                result = data.get("result", {})
                result_content = result.get("content", [])
                is_error = result.get("isError", False)
                text_output = ""
                metadata: Dict[str, Any] = {"products": [], "dealers": [], "cart": None, "customer": None, "orders": []}
                
                for content_block in result_content:
                    if content_block.get("type") == "text":
                        text_output += content_block.get("text", "")
                
                # Try to parse JSON from text output for richer metadata extraction
                parsed_json = None
                if text_output:
                    try:
                        parsed_json = json.loads(text_output)
                    except (json.JSONDecodeError, ValueError):
                        parsed_json = None
                
                # Use parsed_json or result dict as the data source
                data_source = parsed_json if parsed_json is not None else result
                
                # ── Extract Products (search_catalog/search_shop_catalog/get_product_details) ──
                raw_products = []
                if isinstance(data_source, dict):
                    if "products" in data_source:
                        raw_products = data_source["products"]
                    elif "data" in data_source and isinstance(data_source["data"], dict):
                        raw_products = data_source["data"].get("products", [])
                elif isinstance(data_source, list):
                    # Some tools return a list of products directly
                    if data_source and isinstance(data_source[0], dict) and "product_id" in data_source[0]:
                        raw_products = data_source
                        
                for rp in raw_products:
                    if not isinstance(rp, dict): continue
                    p_id = str(rp.get("product_id") or rp.get("id") or rp.get("admin_graphql_api_id") or "")
                    name = rp.get("title") or rp.get("name") or "Unnamed Product"
                    
                    # SKU: prefer first variant SKU
                    sku = rp.get("sku") or rp.get("handle") or p_id
                    
                    variants_list = []
                    raw_variants = rp.get("variants")
                    if isinstance(raw_variants, list):
                        variants_list = raw_variants
                    elif isinstance(raw_variants, dict):
                        # Handle GraphQL edges/nodes pattern
                        edges = raw_variants.get("edges") or []
                        if isinstance(edges, list):
                            variants_list = [e.get("node", {}) for e in edges if isinstance(e, dict)]
                    
                    if variants_list:
                        sku = variants_list[0].get("sku") or sku
                    
                    # Price: from variants.price or top-level
                    price = rp.get("price", 0)
                    currency = rp.get("currency") or rp.get("currencyCode")
                    price_range = rp.get("price_range")
                    if not price and isinstance(price_range, dict):
                        min_price = price_range.get("min") or {}
                        if isinstance(min_price, dict):
                            price = min_price.get("amount", 0)
                            currency = min_price.get("currency") or currency
                    if not price and variants_list:
                        variant_price = variants_list[0].get("price", 0)
                        if isinstance(variant_price, dict):
                            price = variant_price.get("amount", 0)
                            currency = variant_price.get("currency") or currency
                        else:
                            price = variant_price
                    
                    # Variant ID for cart operations
                    variant_id = None
                    if variants_list:
                        variant_id = variants_list[0].get("variant_id") or variants_list[0].get("id")
                    
                    # Image URL
                    img = rp.get("image_url") or rp.get("image")
                    if not img:
                        if isinstance(rp.get("images"), list) and rp["images"]:
                            img = rp["images"][0].get("src")
                        elif isinstance(rp.get("media"), list) and rp["media"]:
                            img = rp["media"][0].get("url")
                        elif isinstance(rp.get("featuredImage"), dict):
                            img = rp["featuredImage"].get("url")
                            
                    metadata["products"].append({
                        "id": p_id,
                        "variant_id": str(variant_id) if variant_id else p_id,
                        "sku": sku,
                        "name": name,
                        "price": float(price) if price else 0.0,
                        "currency": str(currency).upper() if currency else None,
                        "currency_source": "product" if currency else "missing",
                        "category": str(rp.get("category") or rp.get("productType") or "General"),
                        "in_stock": bool(rp.get("in_stock") if rp.get("in_stock") is not None else True),
                        "image_url": img,
                        "product_url": rp.get("product_url") or rp.get("url")
                    })
                
                # ── Extract Cart (update_cart, get_cart) ──
                cart_data = None
                if isinstance(data_source, dict):
                    # Response may have a 'cart' key, 'data' key containing 'cart', or be the cart itself
                    cart_obj = data_source.get("cart")
                    if not cart_obj and "data" in data_source and isinstance(data_source["data"], dict):
                        cart_obj = data_source["data"].get("cart")
                        
                    if not cart_obj and ("checkoutUrl" in data_source or "checkout_url" in data_source):
                        cart_obj = data_source
                        
                    if cart_obj and isinstance(cart_obj, dict):
                        cart_id = cart_obj.get("id") or cart_obj.get("cart_id")
                        checkout_url = cart_obj.get("checkoutUrl") or cart_obj.get("checkout_url")
                        line_items = cart_obj.get("lines") or cart_obj.get("lineItems") or []
                        if cart_id or checkout_url:
                            cart_data = {
                                "cart_id": cart_id,
                                "checkout_url": checkout_url,
                                "line_items": line_items
                            }
                            metadata["cart"] = cart_data
                
                # ── Extract Customer / Orders ──
                if isinstance(data_source, dict):
                    customer = data_source.get("customer")
                    if customer and isinstance(customer, dict):
                        metadata["customer"] = {
                            "id": customer.get("id"),
                            "email": customer.get("email"),
                            "first_name": customer.get("firstName") or customer.get("first_name"),
                            "last_name": customer.get("lastName") or customer.get("last_name"),
                        }
                    orders = data_source.get("orders") or []
                    if orders and isinstance(orders, list):
                        metadata["orders"] = [
                            {"id": o.get("id"), "name": o.get("name"), "status": o.get("displayFinancialStatus") or o.get("status")}
                            for o in orders if isinstance(o, dict)
                        ]
                
                # ── Dealers ──
                if isinstance(data_source, dict):
                    dealers = data_source.get("dealers") or (data_source.get("data") or {}).get("dealers") or []
                    metadata["dealers"] = dealers
                        
                return ToolResult(
                    success=not is_error,
                    data=text_output,
                    error=text_output if is_error else None,
                    metadata=metadata
                )
        except Exception as e:
            logger.error("mcp_tool_execution_failed", tool=self.name, error=str(e))
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to execute MCP tool: {str(e)}"
            )

    def _normalize_arguments(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Accept legacy/simple agent tool inputs and shape them for UCP tools."""
        if self.name != "search_catalog":
            return kwargs
        if "catalog" in kwargs:
            return kwargs

        normalized: Dict[str, Any] = {}
        catalog: Dict[str, Any] = {}
        for key in ("query", "filters", "pagination", "context", "signals"):
            if key in kwargs and kwargs[key] not in (None, ""):
                catalog[key] = kwargs[key]
        if "limit" in kwargs and "pagination" not in catalog:
            catalog["pagination"] = {"limit": kwargs["limit"]}

        for key, value in kwargs.items():
            if key not in {"query", "filters", "pagination", "context", "signals", "limit"}:
                normalized[key] = value
        normalized["catalog"] = catalog
        return normalized

class McpClient:
    """Client for discovering and fetching tools from an MCP server."""
    
    def __init__(self, endpoint: str, headers: Dict[str, str] = None):
        self.endpoint = endpoint
        self.headers = headers or {}
        
    async def discover_tools(self, session_id: str = "default") -> List[BaseTool]:
        """Fetch remote tools from the MCP server and wrap them in BaseTool instances."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list",
            "params": {}
        }
        
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self.headers)
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.endpoint, json=payload, headers=request_headers)
                response.raise_for_status()
                data = response.json()
                
                if "error" in data:
                    logger.error("mcp_tool_discovery_failed", error=data["error"])
                    return []
                    
                tools_data = data.get("result", {}).get("tools", [])
                dynamic_tools = []
                
                for td in tools_data:
                    tool = McpTool(
                        name=td.get("name"),
                        description=td.get("description"),
                        parameters_schema=td.get("inputSchema", {}),
                        mcp_endpoint=self.endpoint,
                        session_id=session_id,
                        headers=self.headers
                    )
                    dynamic_tools.append(tool)
                    
                return dynamic_tools
                
        except Exception as e:
            logger.warning("mcp_server_unreachable", endpoint=self.endpoint, error=str(e))
            return []
