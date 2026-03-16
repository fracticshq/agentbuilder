import fetch from 'node-fetch';
import 'dotenv/config';

// Cache for discovered MCP endpoints to avoid redundant network calls
const discoveryCache = new Map();

/**
 * Discovers the Shopify MCP endpoints from the shop's storefront domain.
 * Uses the /.well-known/customer-account-api discovery endpoint.
 */
export async function discoverMcpEndpoints(shopUrl) {
  const cleanUrl = shopUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
  
  if (discoveryCache.has(cleanUrl)) {
    return discoveryCache.get(cleanUrl);
  }

  const discoveryUrl = `https://${cleanUrl}/.well-known/customer-account-api`;
  try {
    const response = await fetch(discoveryUrl);
    if (!response.ok) throw new Error(`Discovery failed: ${response.statusText}`);
    
    const config = await response.json();
    const endpoints = {
      storefrontMcp: `https://${cleanUrl}/api/mcp`,
      customerAccountMcp: config.mcp_api || `https://${cleanUrl}/customer/api/mcp`,
      auth: {
        authorization_endpoint: config.authorization_endpoint,
        token_endpoint: config.token_endpoint,
        userinfo_endpoint: config.userinfo_endpoint
      }
    };
    
    discoveryCache.set(cleanUrl, endpoints);
    return endpoints;
  } catch (err) {
    console.error(`Error discovering MCP for ${shopUrl}:`, err);
    // Fallback to standard patterns if discovery fails
    return {
      storefrontMcp: `https://${cleanUrl}/api/mcp`,
      customerAccountMcp: `https://${cleanUrl}/customer/api/mcp`,
      auth: null
    };
  }
}

/**
 * Fetches the list of tools from a specific MCP endpoint.
 */
export async function fetchTools(url, headers = {}) {
  const payload = {
    jsonrpc: '2.0',
    id: 'discovery-' + Date.now(),
    method: 'tools/list',
    params: {}
  };

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000); // 5s timeout

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    clearTimeout(timeout);
    if (!response.ok) return [];
    const body = await response.json();
    return body.result?.tools || [];
  } catch (err) {
    console.error(`Error fetching tools from ${url}:`, err.message);
    return [];
  }
}

/**
 * Forwards a JSON-RPC request to an official Shopify MCP endpoint.
 */
export async function forwardMcpRequest(url, payload, headers = {}) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000); // 10s timeout for actual calls

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    clearTimeout(timeout);
    const body = await response.json();
    return body;
  } catch (err) {
    console.error(`Error forwarding MCP request to ${url}:`, err.message);
    throw err;
  }
}
