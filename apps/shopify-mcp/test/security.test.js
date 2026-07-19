import assert from 'node:assert/strict';
import test from 'node:test';

import {
  insecureLocalDevAuthBypassEnabled,
  isValidMcpServiceAuthorization,
  normalizeShopifyShopDomain,
  validateShopifyMcpEndpoint,
} from '../src/security.js';

test('Shopify MCP accepts only a canonical myshopify shop domain', () => {
  assert.equal(normalizeShopifyShopDomain('https://Store-1.myshopify.com/'), 'store-1.myshopify.com');
  for (const unsafeDomain of [
    'https://example.com',
    'https://store.myshopify.com.evil.example',
    'http://store.myshopify.com',
    'https://store.myshopify.com/path',
    'https://127.0.0.1',
  ]) {
    assert.throws(() => normalizeShopifyShopDomain(unsafeDomain));
  }
});

test('Shopify MCP endpoints cannot escape the configured shop host', () => {
  const expectedShop = 'store.myshopify.com';
  assert.equal(
    validateShopifyMcpEndpoint('https://store.myshopify.com/api/mcp', expectedShop),
    'https://store.myshopify.com/api/mcp',
  );
  assert.throws(() => validateShopifyMcpEndpoint('https://other.myshopify.com/api/mcp', expectedShop));
  assert.throws(() => validateShopifyMcpEndpoint('https://127.0.0.1/api/mcp', expectedShop));
});

test('MCP service authorization uses a bearer token and local bypass is explicit', () => {
  assert.equal(isValidMcpServiceAuthorization('Bearer shared-secret', 'shared-secret'), true);
  assert.equal(isValidMcpServiceAuthorization('Bearer wrong-secret', 'shared-secret'), false);
  assert.equal(isValidMcpServiceAuthorization(undefined, 'shared-secret'), false);
  assert.equal(insecureLocalDevAuthBypassEnabled({ NODE_ENV: 'development' }), false);
  assert.equal(
    insecureLocalDevAuthBypassEnabled({ NODE_ENV: 'development', SHOPIFY_MCP_ALLOW_INSECURE_LOCAL_DEV: 'true' }),
    true,
  );
  assert.equal(
    insecureLocalDevAuthBypassEnabled({ NODE_ENV: 'production', SHOPIFY_MCP_ALLOW_INSECURE_LOCAL_DEV: 'true' }),
    false,
  );
});
