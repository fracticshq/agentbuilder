import { vi, type Mock } from 'vitest';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { api } from '../../api/client';
import AgentConfigForm from './AgentConfigForm';
import type { AgentStudioData } from './types';

vi.mock('../../api/client', () => ({
  api: {
    getArtifactTypes: vi.fn(),
  },
}));

const artifactDefinition = {
  id: 'kundali_chart',
  name: 'Kundali Chart',
  description: 'Visual Lal Kitab chart.',
  applies_to_templates: ['astrology_lalkitab'],
  default_enabled: true,
  options_schema: {
    type: 'object',
    properties: {
      style: {
        type: 'string',
        enum: ['north_indian'],
        default: 'north_indian',
        description: 'Chart drawing style.',
      },
    },
  },
  default_options: { style: 'north_indian' },
};

function makeData(
  agent_template = 'astrology_lalkitab',
  artifacts_config: AgentStudioData['artifacts_config'] = {},
): AgentStudioData {
  return {
    name: 'Lal Kitab Agent',
    description: 'Astrology assistant',
    brand_id: 'brand-1',
    agent_template,
    purpose: 'Give Lal Kitab guidance',
    role: 'Astrologer',
    provider: 'azure_openai',
    model: 'gpt-5.4-mini',
    temperature: 0.7,
    max_tokens: 2000,
    top_p: 1,
    frequency_penalty: 0,
    presence_penalty: 0,
    system_prompt: '',
    communication_style: 'helpful',
    response_format: '',
    data_source: 'none',
    rag_enabled: false,
    selected_skill_ids: [],
    selected_tool_ids: [],
    agent_api_enabled: false,
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
    shopify_integration_mode: 'hybrid_catalog_rag_mcp',
    shopify_agent_profile_url: '',
    commerce_default_currency: '',
    commerce_currency_policy: 'catalog_first_config_fallback',
    commerce_source_display_policy: 'cards_only',
    commerce_product_top_k: 8,
    commerce_max_product_cards: 5,
    commerce_include_out_of_stock: false,
    commerce_taxonomy_json: '{"categories":[]}',
    api_data_source_enabled: false,
    api_data_source_name: '',
    api_data_source_url: '',
    api_data_source_auth_header: '',
    api_data_source_auth_header_configured: false,
    api_data_source_usage: '',
    url_context_boost_enabled: true,
    artifacts_config,
  };
}

function renderForm(data = makeData(), onChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AgentConfigForm
        data={data}
        onChange={onChange}
        brands={[{
          id: 'brand-1',
          name: 'Test Brand',
          slug: 'test-brand',
          description: '',
          industry: 'astrology',
          created_at: '',
          updated_at: '',
        }]}
        deployments={[]}
      />
    </QueryClientProvider>,
  );
  return onChange;
}

beforeEach(() => {
  (api.getArtifactTypes as Mock).mockReset();
});

test('loads Lal Kitab artifacts for a legacy alias and persists a toggle without dropping options', async () => {
  (api.getArtifactTypes as Mock).mockResolvedValue([artifactDefinition]);
  const onChange = renderForm(makeData('lal_kitab', {
    kundali_chart: { enabled: true, options: { style: 'north_indian' } },
  }));

  expect(await screen.findByText('Chat Artifacts')).toBeInTheDocument();
  expect(await screen.findByText('Kundali Chart')).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Kundali Chart style' })).toHaveValue('north_indian');
  expect(screen.getByRole('button', { name: 'Toggle Kundali Chart' })).toHaveAttribute('aria-pressed', 'true');

  fireEvent.click(screen.getByRole('button', { name: 'Toggle Kundali Chart' }));

  expect(onChange).toHaveBeenCalledWith('artifacts_config', {
    kundali_chart: { enabled: false, options: { style: 'north_indian' } },
  });
});

test('shows artifact API errors and retries instead of rendering an empty section', async () => {
  (api.getArtifactTypes as Mock)
    .mockRejectedValueOnce(new Error('Request failed with status 503'))
    .mockResolvedValueOnce([artifactDefinition]);
  renderForm();

  expect(await screen.findByRole('alert')).toHaveTextContent('Request failed with status 503');
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

  await waitFor(() => {
    expect(screen.getByText('Kundali Chart')).toBeInTheDocument();
  });
  expect(api.getArtifactTypes).toHaveBeenCalledTimes(2);
});
