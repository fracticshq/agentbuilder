import {
  buildAgentWizardPayload,
  type AgentWizardData,
} from './agentWizardPayload';

function buildAgentData(overrides: Partial<AgentWizardData> = {}): AgentWizardData {
  return {
    name: 'Store Assistant',
    description: 'Helps shoppers choose products.',
    brand_id: 'brand-1',
    agent_template: 'ecommerce_sales',
    purpose: 'Recommend the right products.',
    role: 'Sales advisor',
    provider: 'openai',
    model: 'deployment-gpt-5',
    temperature: 0.4,
    max_tokens: 1200,
    top_p: 0.9,
    frequency_penalty: 0.1,
    presence_penalty: 0.2,
    system_prompt: 'Use only approved catalog information.',
    personality_traits: ['helpful'],
    communication_style: 'concise',
    response_format: 'markdown',
    prompt_rules: '{"grounding":"required"}',
    data_source_policy: '{"default_sources":["catalog"]}',
    runtime_variables_schema: '{"page_context":{"type":"object"}}',
    documents: [],
    chunking_strategy: 'semantic',
    chunk_size: 400,
    chunk_overlap: 50,
    rag_enabled: true,
    embedding_provider: 'voyage',
    embedding_model: 'voyage-3',
    top_k: 8,
    similarity_threshold: 0.72,
    rerank_enabled: true,
    rerank_top_k: 4,
    context_window: 2400,
    data_source: 'shopify',
    shopify_shop_url: 'https://shop.example.test',
    shopify_client_id: 'client-id',
    shopify_client_secret: 'test-secret-value',
    shopify_client_secret_configured: true,
    shopify_sync_enabled: true,
    shopify_mcp_enabled: true,
    shopify_integration_mode: 'hybrid_catalog_rag_mcp',
    shopify_agent_profile_url: 'https://shop.example.test/agent.json',
    commerce_default_currency: ' inr ',
    commerce_currency_policy: 'catalog_first_config_fallback',
    commerce_source_display_policy: 'cards_only',
    commerce_product_top_k: 10,
    commerce_max_product_cards: 6,
    commerce_include_out_of_stock: true,
    commerce_taxonomy_json: '{"categories":["speakers"]}',
    api_data_source_enabled: false,
    api_data_source_name: '',
    api_data_source_url: '',
    api_data_source_auth_header: '',
    api_data_source_auth_header_configured: false,
    api_data_source_usage: '',
    context_connectors: [{
      id: 'availability-api',
      type: 'http',
      name: 'Availability API',
      enabled: true,
      auth_header: 'Authorization: Bearer test-token',
      auth_header_configured: true,
      usage: 'Use for availability.',
      tool_description: 'Fetch availability.',
      endpoints: [{
        id: 'availability',
        name: 'Availability',
        method: 'GET',
        url: 'https://inventory.example.test/availability',
        enabled: true,
        required_fields: ['sku'],
      }],
    }],
    url_context_boost_enabled: true,
    artifacts_config: { product_comparison: { enabled: true } },
    selected_skill_ids: ['knowledge_qa'],
    selected_tool_ids: ['catalog_search'],
    agent_api_enabled: true,
    agent_api_key_ids: ['key-1'],
    agent_api_allowed_origins: 'https://shop.example.test,\nhttps://preview.example.test',
    agent_api_require_key: true,
    websockets: true,
    file_upload: true,
    human_takeover: true,
    conversation_memory: true,
    long_term_memory: true,
    auto_compaction: true,
    context_window_messages: 16,
    typing_indicators: true,
    response_streaming: true,
    widget_enabled: true,
    show_sources: false,
    show_product_cards: true,
    activity_mode: 'advanced',
    activity_persistence: 'persistent',
    conversation_policy_goal: 'Find the best product.',
    conversation_planner_model: 'planner-gpt-5',
    conversation_required_inputs: 'budget:Budget:number\nroom:Room:text',
    conversation_tool_recipes: '[{"id":"catalog-first"}]',
    conversation_question_required: true,
    conversation_hide_internal_sources: true,
    conversation_answer_style: 'consultative',
    context_cache_enabled: true,
    context_invalidation_fields: 'budget, room',
    rate_limiting: true,
    content_filtering: true,
    session_timeout: 60,
    max_conversation_length: 80,
    allowed_file_types: ['application/pdf'],
    max_file_size: 25,
    ...overrides,
  };
}

describe('buildAgentWizardPayload', () => {
  it('serializes the complete commerce agent configuration and preserves edit-time metadata', () => {
    const payload = buildAgentWizardPayload(buildAgentData(), {
      domain: { verticals: ['retail'] },
      skills: { qa: { skill_id: 'knowledge_qa', enabled: false, priority: 1 } },
      tools: { search: { tool_id: 'catalog_search', enabled: false } },
      channels: {
        email: { enabled: true },
        widget: { allowed_origins: ['https://shop.example.test'], legacy_option: true },
      },
    });

    expect(payload).toMatchObject({
      brand_id: 'brand-1',
      name: 'Store Assistant',
      status: 'active',
      metadata: { purpose: 'Recommend the right products.', role: 'Sales advisor' },
    });
    expect(payload.configuration).toMatchObject({
      llm: {
        provider: 'azure_openai',
        model: 'deployment-gpt-5',
        temperature: 0.4,
        max_tokens: 1200,
        top_p: 0.9,
        frequency_penalty: 0.1,
        presence_penalty: 0.2,
      },
      prompt_layers: {
        rules: { grounding: 'required' },
        data_source_policy: { default_sources: ['catalog'] },
        runtime_variables_schema: { page_context: { type: 'object' } },
      },
      domain: { type: 'ecommerce', template: 'ecommerce_sales', verticals: ['retail'] },
      rag: {
        enabled: true,
        embedding: { provider: 'voyage', model: 'voyage-3' },
        retrieval: { top_k: 8, similarity_threshold: 0.72, context_window: 2400, rerank: { enabled: true, top_k: 4 } },
        chunking: { strategy: 'semantic', chunk_size: 400, chunk_overlap: 50 },
      },
      shopify: {
        shop_url: 'https://shop.example.test',
        client_id: 'client-id',
        client_secret: 'test-secret-value',
        integration_mode: 'hybrid_catalog_rag_mcp',
      },
      commerce: {
        enabled: true,
        default_currency: 'INR',
        display_policy: { cards_only: true, show_sources: false, show_product_cards: true },
        retrieval: { product_top_k: 10, max_product_cards: 6, include_out_of_stock: true },
        taxonomy: { categories: ['speakers'] },
      },
      conversation_policy: {
        required_inputs: [
          { id: 'budget', label: 'Budget', type: 'number', required: true, aliases: [] },
          { id: 'room', label: 'Room', type: 'text', required: true, aliases: [] },
        ],
        tool_recipes: [{ id: 'catalog-first' }],
        context_policy: { use_knowledge_when_needed: true, use_connectors_when_needed: true },
        memory_policy: { cache_evidence: true, invalidation_fields: ['budget', 'room'] },
        allowed_capabilities: ['knowledge_qa', 'catalog_search'],
      },
      agent_api: {
        allowed_origins: ['https://shop.example.test', 'https://preview.example.test'],
      },
      channels: {
        email: { enabled: true },
        widget: {
          allowed_origins: ['https://shop.example.test'],
          legacy_option: true,
          enabled: true,
          preview_enabled: true,
          activity_mode: 'advanced',
          activity_persistence: 'persistent',
        },
      },
      features: {
        file_upload: { enabled: true, allowed_types: ['application/pdf'], max_size_mb: 25 },
      },
      memory: {
        short_term: { auto_compaction: true, window_messages: 16 },
        long_term: { enabled: true, status: 'enabled' },
      },
      skills: { selected: ['knowledge_qa'], qa: { enabled: true, priority: 1 } },
      tools: { selected: ['catalog_search'], search: { enabled: true } },
    });
    expect(payload.configuration.context_connectors).toMatchObject([{
      id: 'availability-api',
      type: 'http_api',
      auth: { type: 'raw_header', auth_header: 'Authorization: Bearer test-token' },
    }]);
  });

  it('retains saved commerce and artifact configuration for a non-commerce edit', () => {
    const savedCommerce = { enabled: true, default_currency: 'USD' };
    const savedArtifacts = { product_comparison: { enabled: true, options: { compact: true } } };
    const payload = buildAgentWizardPayload(buildAgentData({
      agent_template: 'generic',
      data_source: 'none',
      rag_enabled: false,
      artifacts_config: {},
      file_upload: false,
      long_term_memory: false,
    }), {
      commerce: savedCommerce,
      artifacts: savedArtifacts,
    });

    expect(payload.configuration.domain).toEqual({ type: 'generic', template: 'generic', verticals: [] });
    expect(payload.configuration.rag).toEqual({ enabled: false });
    expect(payload.configuration.shopify).toBeUndefined();
    expect(payload.configuration.commerce).toBe(savedCommerce);
    expect(payload.configuration.artifacts).toBe(savedArtifacts);
    expect(payload.configuration.features.file_upload).toEqual({ enabled: false });
    expect(payload.configuration.memory.long_term).toEqual({ enabled: false, status: 'needs_privacy_setup' });
  });
});
