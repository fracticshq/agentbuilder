import { handleMcpRequest } from './src/mcp.js';
import * as shopify from './src/shopify.js';
import assert from 'assert';

// Mock Shopify functions
const mockEndpoints = {
  storefrontMcp: 'https://mock-shop.com/api/mcp',
  customerAccountMcp: 'https://mock-shop.com/customer/api/mcp',
  auth: { authorization_endpoint: 'https://mock-shop.com/auth' }
};

const mockStorefrontTools = [
  { name: 'search_shop_catalog', description: 'Search products' }
];

const mockCustomerTools = [
  { name: 'get_customer_profile', description: 'Get profile' }
];

async function runTests() {
  console.log('🧪 Starting Shopify MCP Hub Verification...');

  // Mock shopify.js
  shopify.discoverMcpEndpoints = async () => mockEndpoints;
  shopify.fetchTools = async (url) => {
    if (url === mockEndpoints.storefrontMcp) return mockStorefrontTools;
    if (url === mockEndpoints.customerAccountMcp) return mockCustomerTools;
    return [];
  };
  shopify.forwardMcpRequest = async (url, payload, headers) => {
    return { jsonrpc: '2.0', id: payload.id, result: { url, payload, headers } };
  };

  const session = { customer_access_token: 'valid-token' };
  const headers = { 'x-shopify-shop-url': 'mock-shop.com' };

  // Test 1: tools/list
  console.log('Testing tools/list...');
  const listResponse = await handleMcpRequest({
    jsonrpc: '2.0', id: 1, method: 'tools/list', params: {}
  }, session, headers);

  assert.strictEqual(listResponse.result.tools.length, 2);
  assert.strictEqual(listResponse.result.tools[0].name, 'search_shop_catalog');
  assert.strictEqual(listResponse.result.tools[1].name, 'get_customer_profile');
  console.log('✅ tools/list passed');

  // Test 2: tools/call (Storefront)
  console.log('Testing Storefront tool call...');
  const callSfResponse = await handleMcpRequest({
    jsonrpc: '2.0', id: 2, method: 'tools/call', 
    params: { name: 'search_shop_catalog', arguments: { query: 'test' } }
  }, session, headers);

  assert.strictEqual(callSfResponse.result.url, mockEndpoints.storefrontMcp);
  console.log('✅ Storefront tool call passed');

  // Test 3: tools/call (Customer Account)
  console.log('Testing Customer Account tool call...');
  const callCaResponse = await handleMcpRequest({
    jsonrpc: '2.0', id: 3, method: 'tools/call', 
    params: { name: 'get_customer_profile', arguments: {} }
  }, session, headers);

  assert.strictEqual(callCaResponse.result.url, mockEndpoints.customerAccountMcp);
  assert.strictEqual(callCaResponse.result.headers['Authorization'], 'Bearer valid-token');
  console.log('✅ Customer Account tool call passed');

  // Test 4: Auth Required Error
  console.log('Testing AuthRequiredError...');
  try {
    await handleMcpRequest({
      jsonrpc: '2.0', id: 4, method: 'tools/call', 
      params: { name: 'get_customer_profile', arguments: {} }
    }, {}, headers); // Empty session
    assert.fail('Should have thrown AuthRequiredError');
  } catch (err) {
    assert.strictEqual(err.name, 'AuthRequiredError');
    console.log('✅ AuthRequiredError passed');
  }

  console.log('\n✨ All tests passed successfully!');
}

runTests().catch(err => {
  console.error('❌ Tests failed:', err);
  process.exit(1);
});
