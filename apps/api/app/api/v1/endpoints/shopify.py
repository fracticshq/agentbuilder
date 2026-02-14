from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from llm.providers.shopify.shopify_mcp_client import ShopifyMCPClient
import structlog
import httpx

logger = structlog.get_logger(__name__)

router = APIRouter()

class ShopifyVerifyRequest(BaseModel):
    shop_url: str
    storefront_token: str
    admin_token: Optional[str] = None

@router.post("/verify")
async def verify_shopify_connection(request: ShopifyVerifyRequest):
    """
    Verify Shopify credentials by attempting to fetch shop info.
    """
    try:
        # Sanitize shop_url: remove protocol and trailing slash
        clean_shop_url = request.shop_url.strip()
        if clean_shop_url.startswith("https://"):
            clean_shop_url = clean_shop_url[8:]
        elif clean_shop_url.startswith("http://"):
            clean_shop_url = clean_shop_url[7:]
        
        if clean_shop_url.endswith("/"):
            clean_shop_url = clean_shop_url[:-1]
            
        logger.info("verifying_shopify_credentials", shop_url=clean_shop_url)
        
        # Initialize client with provided credentials
        client = ShopifyMCPClient(
            shop_url=clean_shop_url,
            storefront_token=request.storefront_token,
            admin_token=request.admin_token
        )
        
        # Attempt to get shop info
        shop_info = await client.get_shop_info()
        
        if not shop_info:
            raise ValueError("Failed to retrieve shop info. Credentials might be invalid.")
            
        return {
            "success": True,
            "message": "Successfully connected to Shopify",
            "shop": {
                "name": shop_info.get("name"),
                "domain": shop_info.get("primaryDomain", {}).get("url")
            }
        }
        
    except httpx.HTTPStatusError as e:
        logger.error("shopify_verification_http_error", error=str(e), status=e.response.status_code)
        if e.response.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials. Please check your Shop URL and Storefront Access Token."
            )
        elif e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Please check your API access scopes."
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Shopify API error: {str(e)}"
            )
    except Exception as e:
        logger.error("shopify_verification_failed", error=str(e))
        raise HTTPException(
            status_code=400,
            detail=f"Verification failed: {str(e)}"
        )
