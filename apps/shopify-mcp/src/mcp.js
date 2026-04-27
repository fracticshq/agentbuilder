import { discoverMcpEndpoints, fetchTools, forwardMcpRequest } from './shopify.js';

class AuthRequiredError extends Error {
  constructor(authUrl) {
    super('Authentication required');
    this.name = 'AuthRequiredError';
    this.authUrl = authUrl || `${process.env.SHOPIFY_BASE_URL || 'http://localhost:3005'}/auth/login`;
  }
}

// Map to track which MCP server handles which tool
const toolServerMap = new Map();

function toolCacheKey(shopUrl, toolName) {
  return `${shopUrl}:${toolName}`;
}

function authUrlForShop(shopUrl) {
  const baseUrl = process.env.SHOPIFY_BASE_URL || 'http://localhost:3005';
  const params = new URLSearchParams({ shop: shopUrl });
  return `${baseUrl}/auth/login?${params.toString()}`;
}

/**
 * Handles incoming JSON-RPC 2.0 requests for the Shopify MCP.
 * Delegates to official Shopify Storefront and Customer Account MCP servers.
 */
export async function handleMcpRequest(payload, session, reqHeaders) {
  if (payload.jsonrpc !== '2.0' || !payload.id || !payload.method) {
    throw new Error('Invalid JSON-RPC 2.0 Request');
  }

  const shopUrl = reqHeaders['x-shopify-shop-url'];
  const customerToken = reqHeaders['x-customer-access-token'] || session?.customer_access_token;
  
  if (!shopUrl) {
    if (payload.method === 'tools/list') {
      console.warn('Discovery attempt without x-shopify-shop-url header. Returning empty list.');
      return {
        jsonrpc: '2.0',
        id: payload.id,
        result: { tools: [] }
      };
    } else {
      throw new Error('Missing x-shopify-shop-url header.');
    }
  }

  // Discover endpoints for this shop
  const endpoints = await discoverMcpEndpoints(shopUrl);
  
  if (payload.method === 'tools/list') {
    // 1. Fetch Storefront Tools (No Auth)
    const storefrontTools = await fetchTools(endpoints.storefrontMcp);
    storefrontTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.storefrontMcp));

    // 2. Fetch Customer Account Tools (Auth Required)
    let customerTools = [];
    if (customerToken) {
      customerTools = await fetchTools(endpoints.customerAccountMcp, {
        'Authorization': `Bearer ${customerToken}`
      });
      customerTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.customerAccountMcp));
    }

    return {
      jsonrpc: '2.0',
      id: payload.id,
      result: {
        tools: [...storefrontTools, ...customerTools]
      }
    };
  }

  if (payload.method === 'tools/call') {
    const { name, arguments: args } = payload.params;
    
    // Find which server handles this tool
    let targetUrl = toolServerMap.get(toolCacheKey(shopUrl, name));
    
    // Fallback: If not in cache, try both (Storefront first)
    if (!targetUrl) {
      const storefrontTools = await fetchTools(endpoints.storefrontMcp);
      if (storefrontTools.some(t => t.name === name)) {
        targetUrl = endpoints.storefrontMcp;
        toolServerMap.set(toolCacheKey(shopUrl, name), targetUrl);
      } else {
        targetUrl = endpoints.customerAccountMcp;
        toolServerMap.set(toolCacheKey(shopUrl, name), targetUrl);
      }
    }

    const headers = {};
    if (targetUrl === endpoints.customerAccountMcp) {
      if (!customerToken) {
        throw new AuthRequiredError(authUrlForShop(shopUrl));
      }
      headers['Authorization'] = `Bearer ${customerToken}`;
    }

    try {
      const result = await forwardMcpRequest(targetUrl, payload, headers);
      return result;
    } catch (err) {
      if (err.status === 401) {
        throw new AuthRequiredError(authUrlForShop(shopUrl));
      }
      throw err;
    }
  }

  throw new Error(`Unsupported method: ${payload.method}`);
}
