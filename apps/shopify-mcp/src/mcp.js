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
  const agentProfileUrl = reqHeaders['x-shopify-agent-profile-url'];
  
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
    // 1. Fetch Storefront Catalog Tools (New UCP Catalog) - HIGHEST PRIORITY
    const storefrontCatalogTools = await fetchTools(endpoints.storefrontCatalogMcp);
    storefrontCatalogTools.forEach(t => toolServerMap.set(toolCacheKey(shopUrl, t.name), endpoints.storefrontCatalogMcp));

    // 2. Fetch Storefront Tools (Legacy/Original)
    const storefrontTools = await fetchTools(endpoints.storefrontMcp);
    storefrontTools.forEach(t => {
      const key = toolCacheKey(shopUrl, t.name);
      // Only set if not already set by Catalog MCP (prefer Catalog version for tools like get_product)
      if (!toolServerMap.has(key)) {
        toolServerMap.set(key, endpoints.storefrontMcp);
      }
    });

    // 3. Fetch Customer Account Tools (Auth Required)
    let customerTools = [];
    if (customerToken) {
      customerTools = await fetchTools(endpoints.customerAccountMcp, {
        'Authorization': `Bearer ${customerToken}`
      });
      customerTools.forEach(t => {
        const key = toolCacheKey(shopUrl, t.name);
        if (!toolServerMap.has(key)) {
          toolServerMap.set(key, endpoints.customerAccountMcp);
        }
      });
    }

    // Deduplicate the list returned to the client, preferring Catalog tools
    const catalogToolNames = new Set(storefrontCatalogTools.map(t => t.name));
    const filteredStorefrontTools = storefrontTools.filter(t => !catalogToolNames.has(t.name));
    
    const allTools = [...storefrontCatalogTools, ...filteredStorefrontTools, ...customerTools];

    return {
      jsonrpc: '2.0',
      id: payload.id,
      result: {
        tools: allTools
      }
    };
  }

  if (payload.method === 'tools/call') {
    const { name, arguments: args } = payload.params;

    // Find which server handles this tool
    let targetUrl = toolServerMap.get(toolCacheKey(shopUrl, name));
    
    // Fallback: If not in cache, try identifying by prefix or name
    if (!targetUrl) {
      if (name.includes('catalog') || name === 'get_product') {
        targetUrl = endpoints.storefrontCatalogMcp;
      } else {
        // Default to storefront if unknown
        targetUrl = endpoints.storefrontMcp;
      }
    }

    // Inject Agent Profile Metadata if missing for Catalog tools
    if (targetUrl === endpoints.storefrontCatalogMcp) {
      if (!args.meta) args.meta = {};
      if (!args.meta['ucp-agent']) args.meta['ucp-agent'] = {};
      if (!args.meta['ucp-agent'].profile) {
        // Priority: Explicit arg > Header from message_service > Default
        args.meta['ucp-agent'].profile = agentProfileUrl || 'https://shopify.dev/ucp/agent-profiles/examples/2026-04-08/valid-with-capabilities.json';
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
