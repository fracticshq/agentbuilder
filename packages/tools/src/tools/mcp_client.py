import httpx
import uuid
import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit
import structlog
from .types import BaseTool, ToolResult

logger = structlog.get_logger(__name__)


class McpDiscoveryError(RuntimeError):
    """The MCP tool catalogue could not be established safely."""


_SAFE_MCP_TOOL_ERROR = "The connected service could not complete that action. Please try again."


def _connection_items(value: Any) -> List[Dict[str, Any]]:
    """Normalize Shopify connection/list shapes without losing node identity."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [item for item in nodes if isinstance(item, dict)]
        edges = value.get("edges")
        if isinstance(edges, list):
            return [edge.get("node", {}) for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node", {}), dict)]
    return []


def _payload_candidates(result: Dict[str, Any]) -> tuple[str, List[Any]]:
    """Prefer structured MCP payloads while retaining legacy text compatibility."""
    text_parts: List[str] = []
    candidates: List[Any] = []
    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)):
        candidates.append(structured)

    for block in result.get("content", []) or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            text = str(block["text"])
            text_parts.append(text)
            try:
                parsed = json.loads(text)
                if isinstance(parsed, (dict, list)):
                    candidates.append(parsed)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        elif isinstance(block.get("data"), (dict, list)):
            candidates.append(block["data"])

    combined = "".join(text_parts).strip()
    if combined:
        try:
            parsed = json.loads(combined)
            if isinstance(parsed, (dict, list)):
                candidates.append(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    candidates.append(result)
    return combined, candidates


def _money_minor(value: Any, currency: Any = None) -> tuple[Optional[int], Optional[str]]:
    """Convert external commerce amounts to the canonical minor-unit contract."""
    if isinstance(value, dict):
        currency = value.get("currency") or value.get("currencyCode") or currency
        if value.get("minor") is not None or value.get("amount_minor") is not None:
            value = value.get("minor") if value.get("minor") is not None else value.get("amount_minor")
        else:
            value = value.get("amount") or value.get("value") or value.get("price")
    if value in (None, ""):
        return None, str(currency).upper() if currency else None
    try:
        return int(round(float(str(value).replace(",", "")) * 100)), str(currency).upper() if currency else None
    except (TypeError, ValueError):
        return None, str(currency).upper() if currency else None


def _safe_checkout_url(value: Any, allowed_shop_url: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        parsed = urlsplit(str(value))
        allowed = urlsplit(str(allowed_shop_url or ""))
        if parsed.scheme != "https" or not parsed.hostname:
            return None
        if allowed.hostname and parsed.hostname != allowed.hostname:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except Exception:
        return None


def _find_cart(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    for key in ("cart", "cartCreate", "cartLinesAdd", "cartLinesUpdate", "cartLinesRemove", "getCart"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = value.get("cart") if isinstance(value.get("cart"), dict) else value
            if isinstance(nested, dict) and (
                nested.get("id") or nested.get("cart_id") or nested.get("checkoutUrl") or nested.get("checkout_url")
            ):
                return nested
    if payload.get("checkoutUrl") or payload.get("checkout_url"):
        return payload
    data = payload.get("data")
    if isinstance(data, dict):
        return _find_cart(data)
    return None


def _find_value(payload: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                return payload[key]
        for value in payload.values():
            if isinstance(value, dict):
                found = _find_value(value, keys)
                if found is not None:
                    return found
    return None


def _base_product_url(url: Any) -> Optional[str]:
    if url in (None, ""):
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.scheme or not parts.netloc:
            return str(url).split("?", 1)[0].rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return str(url).split("?", 1)[0].rstrip("/")


def _variant_url(product_url: Any, variant_id: Any) -> Optional[str]:
    if product_url in (None, ""):
        return None
    base_url = _base_product_url(product_url) or str(product_url)
    if variant_id in (None, ""):
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}variant={variant_id}"


def _variant_options(raw_variant: Dict[str, Any]) -> Dict[str, str]:
    options = raw_variant.get("variant_options") or raw_variant.get("selectedOptions") or raw_variant.get("selected_options")
    if isinstance(options, dict):
        return {str(key): str(value) for key, value in options.items() if value not in (None, "")}
    if isinstance(options, list):
        normalized: Dict[str, str] = {}
        for index, option in enumerate(options, start=1):
            if isinstance(option, dict):
                name = option.get("name") or option.get("label") or f"Option {index}"
                value = option.get("value")
                if value not in (None, ""):
                    normalized[str(name)] = str(value)
        return normalized
    normalized = {}
    for index in range(1, 4):
        value = raw_variant.get(f"option{index}")
        if value not in (None, ""):
            normalized[f"Option {index}"] = str(value)
    return normalized

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
                is_error = result.get("isError", False)
                text_output, payload_candidates = _payload_candidates(result)
                metadata: Dict[str, Any] = {"products": [], "dealers": [], "cart": None, "customer": None, "orders": []}

                # Structured MCP payloads take precedence over legacy text JSON.
                data_source = payload_candidates[0] if payload_candidates else result
                
                # ── Extract Products (search_shop_catalog, get_product_details) ──
                raw_products = []
                for candidate in payload_candidates:
                    if isinstance(candidate, list):
                        raw_products = _connection_items(candidate)
                    else:
                        found_products = _find_value(candidate, ("products",))
                        raw_products = _connection_items(found_products)
                    if raw_products:
                        break
                if not raw_products and isinstance(data_source, list):
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
                    variants_list = _connection_items(raw_variants)
                    
                    if variants_list:
                        sku = variants_list[0].get("sku") or sku
                    
                    # Price: from variants.price or top-level
                    price = rp.get("price", 0)
                    currency = rp.get("currency") or rp.get("currencyCode")
                    price_range = rp.get("price_range") or rp.get("priceRange")
                    if not price and isinstance(price_range, dict):
                        min_price = price_range.get("min") or price_range.get("minVariantPrice") or {}
                        if isinstance(min_price, dict):
                            price = min_price.get("amount") or min_price.get("value") or 0
                            currency = min_price.get("currency") or currency
                    if not price and variants_list:
                        variant_price = variants_list[0].get("price", 0)
                        if isinstance(variant_price, dict):
                            price = variant_price.get("amount", 0)
                            currency = variant_price.get("currency") or currency
                        else:
                            price = variant_price
                    
                    price_minor, price_currency = _money_minor(price, currency)
                    currency = price_currency or (str(currency).upper() if currency else None)

                    # Variant ID for cart operations. Never substitute a product ID.
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

                    product_url = rp.get("product_url") or rp.get("url")
                    normalized_variants = []
                    for raw_variant in variants_list:
                        if not isinstance(raw_variant, dict):
                            continue
                        raw_variant_id = raw_variant.get("variant_id") or raw_variant.get("id")
                        raw_variant_sku = raw_variant.get("sku") or raw_variant_id or sku
                        raw_variant_price = raw_variant.get("price") if raw_variant.get("price") is not None else price
                        raw_variant_currency = (
                            raw_variant.get("currency")
                            or raw_variant.get("currencyCode")
                            or currency
                        )
                        variant_price_minor, variant_price_currency = _money_minor(raw_variant_price, raw_variant_currency)
                        raw_variant_currency = variant_price_currency or raw_variant_currency
                        normalized_variants.append({
                            "id": str(raw_variant_id or raw_variant_sku),
                            "variant_id": str(raw_variant_id or raw_variant_sku),
                            "sku": str(raw_variant_sku),
                            "variant_sku": str(raw_variant_sku),
                            "title": raw_variant.get("title") or raw_variant.get("name"),
                            "variant_title": raw_variant.get("title") or raw_variant.get("name"),
                            "variant_options": _variant_options(raw_variant),
                            "price": variant_price_minor or 0,
                            "price_minor": variant_price_minor,
                            "price_unit": "minor",
                            "currency": str(raw_variant_currency).upper() if raw_variant_currency else None,
                            "currency_source": "product" if raw_variant_currency else "missing",
                            "image_url": raw_variant.get("image_url") or raw_variant.get("image") or img,
                            "product_url": product_url,
                            "variant_url": _variant_url(product_url, raw_variant_id),
                            "in_stock": bool(raw_variant.get("in_stock") if raw_variant.get("in_stock") is not None else True),
                            "is_default": raw_variant_id == variant_id,
                        })
                    variant_prices = [variant["price_minor"] for variant in normalized_variants if variant.get("price_minor") is not None]
                            
                    metadata["products"].append({
                        "id": p_id,
                        "variant_id": str(variant_id) if variant_id else None,
                        "sku": sku,
                        "name": name,
                        "price": price_minor or 0,
                        "price_minor": price_minor,
                        "price_unit": "minor",
                        "currency": str(currency).upper() if currency else None,
                        "currency_source": "catalog" if currency else "missing",
                        "category": str(rp.get("category") or rp.get("productType") or "General"),
                        "in_stock": bool(rp.get("in_stock") if rp.get("in_stock") is not None else True),
                        "image_url": img,
                        "product_url": product_url,
                        "product_group_id": str(rp.get("product_group_id") or rp.get("product_id") or rp.get("id") or _base_product_url(product_url) or p_id),
                        "handle": rp.get("handle"),
                        "has_variants": len(normalized_variants) > 1,
                        "variant_count": len(normalized_variants),
                        "price_min": min(variant_prices) if variant_prices else None,
                        "price_max": max(variant_prices) if variant_prices else None,
                        "default_variant_id": str(variant_id) if variant_id else None,
                        "variants": normalized_variants,
                    })
                
                # ── Extract Cart (update_cart, get_cart) ──
                cart_data = None
                for candidate in payload_candidates:
                    cart_obj = _find_cart(candidate)
                    if cart_obj:
                        allowed_shop_url = self.headers.get("x-shopify-shop-url") or self.headers.get("X-Shopify-Shop-Url")
                        checkout_url = _safe_checkout_url(
                            cart_obj.get("checkoutUrl") or cart_obj.get("checkout_url"),
                            allowed_shop_url,
                        )
                        line_items = _connection_items(cart_obj.get("lines") or cart_obj.get("lineItems") or cart_obj.get("line_items"))
                        cart_id = cart_obj.get("id") or cart_obj.get("cart_id") or cart_obj.get("cartId")
                        if cart_id or checkout_url:
                            cart_data = {
                                "cart_id": str(cart_id) if cart_id else None,
                                "checkout_url": checkout_url,
                                "cart_lines": line_items,
                                "lines": line_items,
                                "line_items": line_items,
                            }
                            metadata["cart"] = cart_data
                            metadata["commerce_action"] = {"status": "succeeded", "cart": cart_data}
                            break
                
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
                    data=None if is_error else (text_output or json.dumps(data_source, default=str)),
                    # MCP error blocks are remote input.  Never promote their
                    # diagnostics into model context or a customer response.
                    error=_SAFE_MCP_TOOL_ERROR if is_error else None,
                    metadata=metadata,
                )
        except Exception as exc:
            logger.error(
                "mcp_tool_execution_failed",
                tool=self.name,
                error_type=type(exc).__name__,
            )
            return ToolResult(
                success=False,
                data=None,
                error=_SAFE_MCP_TOOL_ERROR,
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
                    logger.error("mcp_tool_discovery_failed", error_type="jsonrpc_error")
                    raise McpDiscoveryError("MCP tool discovery failed")
                    
                tools_data = data.get("result", {}).get("tools", [])
                if not isinstance(tools_data, list):
                    raise McpDiscoveryError("MCP tool discovery returned an invalid catalogue")
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
                
        except McpDiscoveryError:
            raise
        except Exception as exc:
            logger.warning(
                "mcp_server_unreachable",
                endpoint=self.endpoint,
                error_type=type(exc).__name__,
            )
            raise McpDiscoveryError("MCP tool discovery is unavailable") from exc
