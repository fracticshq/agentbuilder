import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { beforeEach, describe, expect, it, vi, type Mocked } from 'vitest';

import { api, type Agent } from '../api/client';
import { knowledgeApi } from '../api/knowledge';
import { useAgentWizardController } from './useAgentWizardController';

vi.mock('../api/client', () => ({
  api: {
    getBrands: vi.fn(),
    getAzureDeployments: vi.fn(),
    getAgent: vi.fn(),
    createAgent: vi.fn(),
    updateAgent: vi.fn(),
  },
}));

vi.mock('../api/knowledge', () => ({
  knowledgeApi: {
    getDocuments: vi.fn(),
  },
}));

const mockApi = api as Mocked<typeof api>;
const mockKnowledgeApi = knowledgeApi as Mocked<typeof knowledgeApi>;

function buildAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    brand_id: 'brand-id',
    name: 'Saved Agent',
    slug: 'saved-agent',
    description: 'A saved agent.',
    configuration: {},
    system_prompt: 'Use approved information.',
    status: 'active',
    created_at: '2026-07-20T00:00:00.000Z',
    updated_at: '2026-07-20T00:00:00.000Z',
    ...overrides,
  };
}

function renderController(id?: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return renderHook(() => useAgentWizardController(id), { wrapper: Wrapper });
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  vi.spyOn(console, 'log').mockImplementation(() => undefined);
  mockApi.getBrands.mockResolvedValue([]);
  mockApi.getAzureDeployments.mockResolvedValue({
    provider: 'azure_openai',
    deployments: [],
  });
  mockApi.getAgent.mockReset();
  mockKnowledgeApi.getDocuments.mockResolvedValue([]);
});

describe('useAgentWizardController', () => {
  it('restores and persists a new-agent draft with Azure-only LLM state', async () => {
    localStorage.setItem('agent_wizard_draft', JSON.stringify({
      data: {
        name: 'Draft Agent',
        provider: 'openai',
        model: 'gpt-4.1',
      },
    }));

    const { result } = renderController();

    await waitFor(() => {
      expect(result.current.agentData.name).toBe('Draft Agent');
    });
    expect(result.current.agentData.provider).toBe('azure_openai');
    expect(result.current.agentData.model).toBe('');
    expect(mockApi.getAgent).not.toHaveBeenCalled();

    act(() => {
      result.current.updateStepData('name', 'Updated Draft Agent');
    });

    await waitFor(() => {
      const draft = JSON.parse(localStorage.getItem('agent_wizard_draft') || '{}');
      expect(draft.data.name).toBe('Updated Draft Agent');
      expect(draft.data.provider).toBe('azure_openai');
    });
  });

  it('ignores the local draft when editing and hydrates the saved agent instead', async () => {
    localStorage.setItem('agent_wizard_draft', JSON.stringify({
      data: { name: 'Do Not Use This Draft' },
    }));
    mockApi.getAgent.mockResolvedValue(buildAgent({ name: 'Persisted Agent' }));

    const { result } = renderController('agent-1');

    await waitFor(() => {
      expect(result.current.agentData.name).toBe('Persisted Agent');
    });
    expect(mockApi.getAgent).toHaveBeenCalledWith('agent-1');
    expect(JSON.parse(localStorage.getItem('agent_wizard_draft') || '{}').data.name).toBe('Do Not Use This Draft');
  });

  it('uses brand_slug before brand_id when hydrating documents', async () => {
    mockApi.getAgent.mockResolvedValue(buildAgent({
      brand_id: 'brand-id',
      brand_slug: 'brand-slug',
    }));
    mockKnowledgeApi.getDocuments.mockResolvedValue([
      {
        doc_id: 'document-1',
        title: 'Product guide',
        content_type: 'document',
        chunks_count: 12,
        item_count: 1,
      },
    ]);

    const { result } = renderController('agent-1');

    await waitFor(() => {
      expect(mockKnowledgeApi.getDocuments).toHaveBeenCalledWith('brand-slug');
      expect(result.current.agentData.documents).toEqual([
        expect.objectContaining({
          id: 'document-1',
          filename: 'Product guide',
          size: 12,
          type: 'document',
          status: 'ready',
        }),
      ]);
    });
  });

  it('defaults a new wizard to the discovered Azure deployment', async () => {
    mockApi.getAzureDeployments.mockResolvedValue({
      provider: 'azure_openai',
      default_deployment: 'gpt-5.4-mini',
      deployments: [
        {
          deployment_name: 'gpt-5.4-mini',
          model_name: 'gpt-5.4-mini',
          provisioning_state: 'Succeeded',
        },
      ],
    });

    const { result } = renderController();

    await waitFor(() => {
      expect(result.current.agentData.provider).toBe('azure_openai');
      expect(result.current.agentData.model).toBe('gpt-5.4-mini');
    });
  });

  it('preserves masked-secret indicators while normalizing saved LLM configuration to Azure', async () => {
    mockApi.getAgent.mockResolvedValue(buildAgent({
      configuration: {
        llm: { provider: 'openai', model: 'gpt-4.1' },
        data_source: 'shopify',
        shopify: {
          client_secret_configured: true,
        },
        api_data_source: {
          auth_header_configured: true,
        },
      },
    }));

    const { result } = renderController('agent-1');

    await waitFor(() => {
      expect(result.current.agentData.provider).toBe('azure_openai');
      expect(result.current.agentData.model).toBe('');
      expect(result.current.agentData.shopify_client_secret).toBe('');
      expect(result.current.agentData.shopify_client_secret_configured).toBe(true);
      expect(result.current.agentData.api_data_source_auth_header).toBe('');
      expect(result.current.agentData.api_data_source_auth_header_configured).toBe(true);
    });
  });
});
