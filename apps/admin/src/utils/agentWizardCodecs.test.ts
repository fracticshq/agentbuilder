import {
  buildCapabilityConfig,
  createVedikaLalKitabConnector,
  extractSelectedCapabilityIds,
  normalizeConnectorsForStudio,
  normalizeLalKitabEndpointUrl,
  serializeContextConnectors,
} from './agentWizardCodecs';

describe('agent wizard codecs', () => {
  it('normalizes a legacy HTTP API data source and serializes its connector contract', () => {
    const [connector] = normalizeConnectorsForStudio({
      api_data_source: {
        name: 'Weather lookup',
        url: 'https://weather.example.test/v1/forecast',
        enabled: true,
        auth_header: 'Authorization: Bearer secret',
        usage: 'Use for current weather only.',
      },
    });

    expect(connector).toMatchObject({
      id: 'legacy_api_data_source',
      type: 'http',
      name: 'Weather lookup',
      enabled: true,
      domain_allowlist: ['weather.example.test'],
      endpoints: [{
        id: 'default',
        method: 'POST',
        url: 'https://weather.example.test/v1/forecast',
      }],
    });

    expect(serializeContextConnectors([connector])).toMatchObject([{
      id: 'legacy_api_data_source',
      type: 'http_api',
      auth: { type: 'raw_header', auth_header: 'Authorization: Bearer secret' },
      usage_policy: 'Use for current weather only.',
      endpoints: [{
        id: 'default',
        url_template: 'https://weather.example.test/v1/forecast',
        required_user_fields: [],
      }],
    }]);
  });

  it('normalizes and serializes MCP connector metadata without HTTP endpoints', () => {
    const [connector] = normalizeConnectorsForStudio({
      context_connectors: [{
        id: 'catalog-mcp',
        type: 'mcp',
        name: 'Catalog MCP',
        enabled: true,
        auth: { auth_header: 'Authorization: Bearer mcp-token' },
        mcp: {
          endpoint: 'https://mcp.example.test/catalog',
          transport: 'sse',
          server_name: 'catalog',
        },
        discovered_tools: [{ name: 'search_catalog', description: 'Search catalog products.' }],
        allowed_tools: ['search_catalog'],
        last_discovered_at: '2026-07-18T00:00:00Z',
        endpoints: [{ id: 'ignored-http-endpoint' }],
      }],
    });

    expect(connector).toMatchObject({
      type: 'mcp',
      endpoint: 'https://mcp.example.test/catalog',
      transport: 'sse',
      auth_header: 'Authorization: Bearer mcp-token',
      allowed_tools: ['search_catalog'],
      endpoints: [{ id: 'ignored-http-endpoint', method: 'POST' }],
    });

    expect(serializeContextConnectors([connector])).toMatchObject([{
      id: 'catalog-mcp',
      type: 'mcp',
      endpoint: 'https://mcp.example.test/catalog',
      transport: 'sse',
      mcp: {
        endpoint: 'https://mcp.example.test/catalog',
        transport: 'sse',
        server_name: 'catalog',
      },
      discovered_tools: [{ name: 'search_catalog' }],
      allowed_tools: ['search_catalog'],
      endpoints: [],
    }]);
  });

  it('creates and normalizes the Lal Kitab connector endpoints', () => {
    const connector = createVedikaLalKitabConnector();

    expect(connector).toMatchObject({
      id: 'vedika_lal_kitab',
      type: 'http',
      domain_allowlist: ['api.vedika.io'],
    });
    expect(connector.endpoints).toHaveLength(8);
    expect(connector.endpoints.find(endpoint => endpoint.id === 'lalkitab_chart')).toMatchObject({
      execution_order: 1,
      requires_prior_endpoint: null,
      payload_mode: 'flat_body',
    });

    const [normalized] = normalizeConnectorsForStudio({
      context_connectors: [{
        id: 'vedika_lal_kitab',
        name: 'Vedika Lal Kitab',
        enabled: true,
        endpoints: [{
          id: 'lalkitab_remedies',
          url_template: 'https://api.vedika.io/v1/lal-kitab/remedies',
        }],
      }],
    });
    expect(normalized.endpoints[0]).toMatchObject({
      url: 'https://api.vedika.io/v2/astrology/lalkitab/remedies',
      execution_order: 2,
      requires_prior_endpoint: 'lalkitab_chart',
      field_mapping: { birth_date: 'date', birth_time: 'time' },
    });
    expect(normalizeLalKitabEndpointUrl('external_lookup', 'https://example.test/lookup'))
      .toBe('https://example.test/lookup');
  });

  it('round-trips selected skills and tools while preserving their entry metadata', () => {
    const skills = {
      knowledge: { skill_id: 'knowledge_qa', enabled: true, priority: 1 },
      api: { skill_id: 'api_data_lookup', enabled: false },
      selected_skill_ids: ['stale-value'],
    };
    const selectedSkills = extractSelectedCapabilityIds(skills, 'skill_id');
    expect(selectedSkills).toEqual(['stale-value']);

    const persistedSkills = buildCapabilityConfig(skills, ['knowledge_qa', 'api_data_lookup', 'knowledge_qa'], 'skill_id');
    expect(persistedSkills).toMatchObject({
      enabled: true,
      selected: ['knowledge_qa', 'api_data_lookup'],
      knowledge: { skill_id: 'knowledge_qa', enabled: true, priority: 1 },
      api: { skill_id: 'api_data_lookup', enabled: true },
    });
    expect(extractSelectedCapabilityIds(persistedSkills, 'skill_id'))
      .toEqual(['knowledge_qa', 'api_data_lookup']);

    const persistedTools = buildCapabilityConfig({
      search: { tool_id: 'catalog_search', enabled: true },
      order: { tool_id: 'order_status', enabled: true },
    }, ['order_status'], 'tool_id');
    expect(extractSelectedCapabilityIds(persistedTools, 'tool_id')).toEqual(['order_status']);
    expect(persistedTools).toMatchObject({
      search: { enabled: false },
      order: { enabled: true },
      selected: ['order_status'],
    });
  });
});
