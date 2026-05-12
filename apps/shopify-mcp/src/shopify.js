import fetch from 'node-fetch';
import 'dotenv/config';

// Cache for discovered MCP endpoints to avoid redundant network calls
const discoveryCache = new Map();

/**
 * Discovers the Shopify MCP endpoints from the shop's storefront domain.
 * Uses the /.well-known/customer-account-api discovery endpoint.
 */
export async function discoverMcpEndpoints(shopUrl) {
  // Ensure we have just the domain (e.g. store.myshopify.com)
  const cleanUrl = shopUrl
    .replace(/^https?:\/\//, '')
    .split('/')[0];

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
      storefrontCatalogMcp: `https://${cleanUrl}/api/ucp/mcp`,
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
      storefrontCatalogMcp: `https://${cleanUrl}/api/ucp/mcp`,
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
 * Retries up to 3 times on 429 (rate limited) with exponential backoff.
 */
export async function forwardMcpRequest(url, payload, headers = {}, attempt = 1) {
  const MAX_ATTEMPTS = 3;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (response.status === 429 && attempt < MAX_ATTEMPTS) {
      const retryAfterMs = parseInt(response.headers.get('retry-after') || '0', 10) * 1000
        || (attempt * 1000); // fallback: 1s, 2s
      console.warn(`Shopify MCP rate limited (429). Retrying in ${retryAfterMs}ms (attempt ${attempt}/${MAX_ATTEMPTS})`);
      await new Promise(resolve => setTimeout(resolve, retryAfterMs));
      return forwardMcpRequest(url, payload, headers, attempt + 1);
    }

    if (!response.ok) {
      const err = new Error(`Shopify MCP returned HTTP ${response.status}`);
      err.status = response.status;
      throw err;
    }

    return response.json();
  } catch (err) {
    clearTimeout(timeout);
    console.error(`Error forwarding MCP request to ${url}:`, err.message);
    throw err;
  }
}
