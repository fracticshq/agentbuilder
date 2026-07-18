import { discoverMcpEndpoints, fetchTools, forwardMcpRequest } from './shopify.js';
import { normalizeShopifyShopDomain } from './security.js';

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

function authUrlForShop(shopUrl, sessionId) {
  const baseUrl = process.env.SHOPIFY_BASE_URL || 'http://localhost:3005';
  const params = new URLSearchParams({ shop: shopUrl });
  if (sessionId) {
    params.set('session_id', sessionId);
  }
  return `${baseUrl}/auth/login?${params.toString()}`;
}

function normalizeUcpToolPayload(payload, ucpAgentProfile) {
  const toolName = payload?.params?.name;
  const toolArgs = payload?.params?.arguments || {};
  let normalizedArgs = { ...toolArgs };

  if (toolName === 'search_catalog' && !normalizedArgs.catalog) {
    const { query, filters, pagination, context, signals, ...rest } = normalizedArgs;
    normalizedArgs = {
      ...rest,
      catalog: {
        ...(query ? { query } : {}),
        ...(filters ? { filters } : {}),
        ...(pagination ? { pagination } : {}),
        ...(context ? { context } : {}),
        ...(signals ? { signals } : {}),
      },
    };
  }

  if (ucpAgentProfile) {
    normalizedArgs.meta = {
      ...(normalizedArgs.meta || {}),
      'ucp-agent': {
        ...((normalizedArgs.meta || {})['ucp-agent'] || {}),
        profile: ucpAgentProfile,
      },
    };
  }

  return {
    ...payload,
    params: {
      ...payload.params,
      arguments: normalizedArgs,
    },
  };
}

/**
 * Handles incoming JSON-RPC 2.0 requests for the Shopify MCP.
 * Delegates to official Shopify Storefront and Customer Account MCP servers.
 */
export async function handleMcpRequest(payload, session, reqHeaders) {
  if (payload.jsonrpc !== '2.0' || !payload.id || !payload.method) {
    throw new Error('Invalid JSON-RPC 2.0 Request');
  }

  const rawShopUrl = reqHeaders['x-shopify-shop-url'];
  const requestSessionId = reqHeaders['x-session-id'] || session?.id || session?.ID;
  const ucpAgentProfile = reqHeaders['x-shopify-ucp-agent-profile'];
  if (session && reqHeaders['x-shopify-client-id']) {
    session.shopify_client_id = reqHeaders['x-shopify-client-id'];
  }
  if (session && reqHeaders['x-shopify-client-secret']) {
    session.shopify_client_secret = reqHeaders['x-shopify-client-secret'];
  }
  const customerToken = reqHeaders['x-customer-access-token'] || session?.customer_access_token;
  
  if (!rawShopUrl) {
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

  const shopUrl = normalizeShopifyShopDomain(rawShopUrl);

  // Discover endpoints for this shop
  const endpoints = await discoverMcpEndpoints(shopUrl);
  
  if (payload.method === 'tools/list') {
    // 1. Fetch Storefront Tools (No Auth)
    const storefrontTools = await fetchTools(endpoints.storefrontMcp, {}, shopUrl);
    storefrontTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.storefrontMcp));

    // 2. Fetch UCP Catalog Tools (No customer auth, UCP-shaped schemas)
    const ucpCatalogTools = await fetchTools(endpoints.ucpCatalogMcp, {}, shopUrl);
    ucpCatalogTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.ucpCatalogMcp));

    // 3. Fetch Customer Account Tools (Auth Required)
    let customerTools = [];
    if (customerToken) {
      customerTools = await fetchTools(
        endpoints.customerAccountMcp,
        { 'Authorization': `Bearer ${customerToken}` },
        shopUrl,
      );
      customerTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.customerAccountMcp));
    }

    return {
      jsonrpc: '2.0',
      id: payload.id,
      result: {
        tools: [...ucpCatalogTools, ...storefrontTools, ...customerTools]
      }
    };
  }

  if (payload.method === 'tools/call') {
    const { name, arguments: args } = payload.params;
    
    // Find which server handles this tool
    let targetUrl = toolServerMap.get(toolCacheKey(shopUrl, name));
    
    // Fallback: If not in cache, try both (Storefront first)
    if (!targetUrl) {
      const storefrontTools = await fetchTools(endpoints.storefrontMcp, {}, shopUrl);
      if (storefrontTools.some(t => t.name === name)) {
        targetUrl = endpoints.storefrontMcp;
        toolServerMap.set(toolCacheKey(shopUrl, name), targetUrl);
      } else {
        const ucpCatalogTools = await fetchTools(endpoints.ucpCatalogMcp, {}, shopUrl);
        if (ucpCatalogTools.some(t => t.name === name)) {
          targetUrl = endpoints.ucpCatalogMcp;
          toolServerMap.set(toolCacheKey(shopUrl, name), targetUrl);
        } else {
          targetUrl = endpoints.customerAccountMcp;
          toolServerMap.set(toolCacheKey(shopUrl, name), targetUrl);
        }
      }
    }

    if (targetUrl === endpoints.ucpCatalogMcp) {
      payload = normalizeUcpToolPayload(payload, ucpAgentProfile);
    }

    const headers = {};
    if (targetUrl === endpoints.customerAccountMcp) {
      if (!customerToken) {
        throw new AuthRequiredError(authUrlForShop(shopUrl, requestSessionId));
      }
      headers['Authorization'] = `Bearer ${customerToken}`;
    }

    try {
      const result = await forwardMcpRequest(targetUrl, payload, headers, shopUrl);
      return result;
    } catch (err) {
      if (err.status === 401) {
        throw new AuthRequiredError(authUrlForShop(shopUrl, requestSessionId));
      }
      throw err;
    }
  }

  throw new Error(`Unsupported method: ${payload.method}`);
}
