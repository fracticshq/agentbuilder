import crypto from 'crypto';

const SHOPIFY_DOMAIN_SUFFIX = '.myshopify.com';
const LOCAL_DEV_BYPASS_FLAG = 'SHOPIFY_MCP_ALLOW_INSECURE_LOCAL_DEV';

/**
 * Return the canonical hostname for a Shopify store that this bridge may call.
 * Shopify's custom domains are intentionally not accepted here: accepting them
 * would make this service an authenticated outbound proxy.
 */
export function normalizeShopifyShopDomain(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    throw new Error('Missing Shopify shop domain.');
  }

  let parsed;
  try {
    parsed = new URL(raw.includes('://') ? raw : `https://${raw}`);
  } catch {
    throw new Error('Shopify shop domain must be a valid HTTPS .myshopify.com hostname.');
  }

  if (
    parsed.protocol !== 'https:' ||
    parsed.username ||
    parsed.password ||
    parsed.port ||
    (parsed.pathname !== '/' && parsed.pathname !== '') ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error('Shopify shop domain must be a bare HTTPS .myshopify.com hostname.');
  }

  const hostname = parsed.hostname.toLowerCase().replace(/\.$/, '');
  const storeName = hostname.slice(0, -SHOPIFY_DOMAIN_SUFFIX.length);
  if (
    !hostname.endsWith(SHOPIFY_DOMAIN_SUFFIX) ||
    !storeName ||
    !/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(storeName)
  ) {
    throw new Error('Shopify shop domain must be a valid .myshopify.com hostname.');
  }

  return hostname;
}

/**
 * Ensure a Shopify MCP endpoint cannot leave the configured shop hostname.
 * node-fetch is also configured not to follow redirects, so authorization
 * headers never move to a different destination.
 */
export function validateShopifyMcpEndpoint(value, expectedShopDomain) {
  const expectedHost = normalizeShopifyShopDomain(expectedShopDomain);
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('Shopify endpoint is not a valid URL.');
  }

  if (
    parsed.protocol !== 'https:' ||
    parsed.username ||
    parsed.password ||
    parsed.port ||
    parsed.hostname.toLowerCase().replace(/\.$/, '') !== expectedHost
  ) {
    throw new Error('Shopify endpoint must use the configured .myshopify.com hostname.');
  }

  return parsed.toString();
}

/**
 * Discovery may advertise Shopify identity URLs, but it must never turn this
 * service into a client for an arbitrary issuer/token endpoint.
 */
export function validateShopifyIdentityEndpoint(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('Shopify identity endpoint is not a valid URL.');
  }

  const hostname = parsed.hostname.toLowerCase().replace(/\.$/, '');
  if (
    parsed.protocol !== 'https:' ||
    parsed.username ||
    parsed.password ||
    parsed.port ||
    !(hostname === 'shopify.com' || hostname.endsWith('.shopify.com'))
  ) {
    throw new Error('Shopify identity endpoint must be hosted by shopify.com.');
  }

  return parsed.toString();
}

export function insecureLocalDevAuthBypassEnabled(env = process.env) {
  return env.NODE_ENV === 'development' && env[LOCAL_DEV_BYPASS_FLAG] === 'true';
}

export function isValidMcpServiceAuthorization(authorization, expectedToken) {
  if (!expectedToken || typeof authorization !== 'string') {
    return false;
  }

  const match = /^Bearer\s+(.+)$/.exec(authorization);
  if (!match) {
    return false;
  }

  const supplied = Buffer.from(match[1]);
  const expected = Buffer.from(expectedToken);
  return supplied.length === expected.length && crypto.timingSafeEqual(supplied, expected);
}
