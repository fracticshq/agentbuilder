import { vi, type Mock } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AgentApiPanel from './AgentApiPanel';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    getAgentApiKeys: vi.fn(),
    createAgentApiKey: vi.fn(),
    revokeAgentApiKey: vi.fn(),
  },
}));

function renderPanel(onChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AgentApiPanel
        open
        agentId="agent-1"
        brandId="brand-1"
        data={{
          name: 'Agent',
          description: '',
          brand_id: 'brand-1',
          agent_template: 'generic',
          purpose: '',
          role: '',
          provider: 'openai',
          model: 'gpt-4o-mini',
          temperature: 0.7,
          max_tokens: 1000,
          top_p: 1,
          frequency_penalty: 0,
          presence_penalty: 0,
          system_prompt: '',
          communication_style: '',
          response_format: '',
          data_source: 'none',
          rag_enabled: false,
          selected_skill_ids: [],
          selected_tool_ids: [],
          agent_api_enabled: true,
          agent_api_key_ids: [],
          agent_api_allowed_origins: '',
          agent_api_require_key: true,
          websockets: true,
          file_upload: false,
          human_takeover: false,
          conversation_memory: true,
          long_term_memory: false,
          typing_indicators: true,
          response_streaming: true,
          widget_enabled: true,
          show_sources: true,
          show_product_cards: false,
          rate_limiting: true,
          content_filtering: true,
          session_timeout: 30,
          max_conversation_length: 100,
          shopify_shop_url: '',
          shopify_client_id: '',
          shopify_client_secret: '',
          shopify_client_secret_configured: false,
          shopify_sync_enabled: true,
          shopify_mcp_enabled: false,
          shopify_integration_mode: 'storefront_ucp_mcp',
          shopify_agent_profile_url: '',
          commerce_default_currency: '',
          commerce_currency_policy: 'catalog_first_config_fallback',
          commerce_source_display_policy: 'cards_only',
          commerce_product_top_k: 8,
          commerce_max_product_cards: 5,
          commerce_include_out_of_stock: false,
          commerce_taxonomy_json: '{ "categories": [], "attributes": [], "synonyms": {} }',
          api_data_source_enabled: false,
          api_data_source_name: '',
          api_data_source_url: '',
          api_data_source_auth_header: '',
          api_data_source_auth_header_configured: false,
          api_data_source_usage: '',
          url_context_boost_enabled: false,
        }}
        onChange={onChange}
        onClose={vi.fn()}
      />
    </QueryClientProvider>
  );
  return onChange;
}

test('creates Agent API keys with backend scopes and stores key_id in config', async () => {
  (api.getAgentApiKeys as Mock).mockResolvedValue([]);
  (api.createAgentApiKey as Mock).mockResolvedValue({
    id: 'uuid-doc-id',
    key_id: 'ab_agent_v1_12345678',
    name: 'Default integration key',
  });
  const onChange = renderPanel();

  fireEvent.click(screen.getByRole('button', { name: /create key/i }));

  await waitFor(() => {
    expect(api.createAgentApiKey).toHaveBeenCalledWith({
      name: 'Default integration key',
      agent_id: 'agent-1',
      brand_id: 'brand-1',
      scopes: ['agents:read', 'messages:write', 'messages:stream', 'sessions:create', 'sessions:read'],
    });
  });
  await waitFor(() => {
    expect(onChange).toHaveBeenCalledWith('agent_api_key_ids', ['ab_agent_v1_12345678']);
  });
});
