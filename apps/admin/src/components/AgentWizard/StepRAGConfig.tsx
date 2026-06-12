import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, AgentApiKey, SkillDefinition, ToolDefinition } from '../../api/client';

interface StepRAGConfigProps {
  data: {
    agent_template?: string;
    data_source: 'rag' | 'shopify' | 'none';
    shopify_shop_url: string;
    shopify_access_token: string;
    shopify_access_token_configured?: boolean;
    embedding_provider: string;
    embedding_model: string;
    top_k: number;
    similarity_threshold: number;
    rerank_enabled: boolean;
    rerank_top_k: number;
    context_window: number;
    data_source_policy: string;
    runtime_variables_schema: string;
    selected_skill_ids: string[];
    selected_tool_ids: string[];
    agent_api_enabled: boolean;
    agent_api_key_ids: string[];
    agent_api_allowed_origins: string;
    agent_api_require_key: boolean;
  };
  brandId?: string;
  onChange: (field: string, value: string | number | boolean | string[]) => void;
}

const embeddingProviders = [
  {
    id: 'voyage',
    name: 'Voyage AI',
    models: [
      { id: 'voyage-large-2', name: 'Voyage Large 2', description: 'Best performance' },
      { id: 'voyage-code-2', name: 'Voyage Code 2', description: 'Optimized for code' },
      { id: 'voyage-2', name: 'Voyage 2', description: 'Balanced performance' },
    ]
  },
  {
    id: 'openai',
    name: 'OpenAI',
    models: [
      { id: 'text-embedding-3-large', name: 'Text Embedding 3 Large', description: 'Highest quality' },
      { id: 'text-embedding-3-small', name: 'Text Embedding 3 Small', description: 'Good performance, lower cost' },
      { id: 'text-embedding-ada-002', name: 'Ada 002', description: 'Legacy model' },
    ]
  },
  {
    id: 'cohere',
    name: 'Cohere',
    models: [
      { id: 'embed-english-v3.0', name: 'Embed English v3.0', description: 'Latest English model' },
      { id: 'embed-multilingual-v3.0', name: 'Embed Multilingual v3.0', description: 'Supports multiple languages' },
    ]
  }
];

function capabilityId(item: Record<string, any>): string {
  return String(item.id || item.key || item.slug || item.name || '');
}

export default function StepRAGConfig({ data, brandId, onChange }: StepRAGConfigProps) {
  const queryClient = useQueryClient();
  const selectedProvider = embeddingProviders.find(p => p.id === data.embedding_provider);
  const availableModels = selectedProvider?.models || [];
  const isEcommerceTemplate = data.agent_template === 'ecommerce';
  
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [newApiKeyName, setNewApiKeyName] = useState('Default integration key');
  const [createdApiKey, setCreatedApiKey] = useState<string | null>(null);
  const [agentApiError, setAgentApiError] = useState<string | null>(null);

  const { data: skills = [], isLoading: skillsLoading } = useQuery<SkillDefinition[]>({
    queryKey: ['admin', 'skills'],
    queryFn: api.getSkills,
    staleTime: 60_000,
    retry: false,
  });

  const { data: tools = [], isLoading: toolsLoading } = useQuery<ToolDefinition[]>({
    queryKey: ['admin', 'tools'],
    queryFn: api.getTools,
    staleTime: 60_000,
    retry: false,
  });

  const { data: apiKeys = [], isLoading: apiKeysLoading } = useQuery<AgentApiKey[]>({
    queryKey: ['admin', 'agent-api-keys', brandId || 'all'],
    queryFn: () => api.getAgentApiKeys({ brandId }),
    staleTime: 60_000,
    retry: false,
  });

  const createApiKeyMutation = useMutation({
    mutationFn: () => api.createAgentApiKey({
      name: newApiKeyName.trim() || 'Default integration key',
      brand_id: brandId || null,
    }),
    onSuccess: async (key) => {
      setAgentApiError(null);
      setCreatedApiKey(key.api_key || null);
      await queryClient.invalidateQueries({ queryKey: ['admin', 'agent-api-keys'] });
      const keyId = key.key_id || key.id;
      if (keyId && !data.agent_api_key_ids.includes(keyId)) {
        onChange('agent_api_key_ids', [...data.agent_api_key_ids, keyId]);
      }
    },
    onError: (error: any) => {
      setAgentApiError(error?.message || 'Failed to create Agent API key.');
    },
  });

  const revokeApiKeyMutation = useMutation({
    mutationFn: (keyId: string) => api.revokeAgentApiKey(keyId),
    onSuccess: async (_key, keyId) => {
      setAgentApiError(null);
      onChange('agent_api_key_ids', data.agent_api_key_ids.filter(id => id !== keyId));
      await queryClient.invalidateQueries({ queryKey: ['admin', 'agent-api-keys'] });
    },
    onError: (error: any) => {
      setAgentApiError(error?.message || 'Failed to revoke Agent API key.');
    },
  });

  const toggleValue = (field: 'selected_skill_ids' | 'selected_tool_ids' | 'agent_api_key_ids', value: string) => {
    const current = data[field] || [];
    onChange(
      field,
      current.includes(value)
        ? current.filter(item => item !== value)
        : [...current, value]
    );
  };

  const handleShopifySync = async () => {
    if (!brandId) {
       alert("Please complete the basic information step and save the agent first, to link it to a brand.");
       return;
    }
    if (!data.shopify_shop_url) {
      alert("Please enter a Shop URL.");
      return;
    }
    setIsSyncing(true);
    setSyncStatus('Starting catalog sync...');
    try {
      const resp = await api.syncShopify({
        brand_id: brandId,
        store_url: data.shopify_shop_url,
        access_token: data.shopify_access_token || undefined,
      });
      setSyncStatus(`Sync initiated. Job ID: ${resp.job_id}`);
    } catch (e: any) {
      console.error(e);
      setSyncStatus(`Sync failed: ${e.message || 'Unknown error'}`);
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 pb-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-primary-700">Agent runtime</p>
            <h3 className="mt-1 text-xl font-semibold text-gray-950">Tools & Sources</h3>
            <p className="mt-1 text-sm text-gray-600">
              Configure retrieval, skills, registry tools, and external API access from one compact control surface.
            </p>
          </div>
          <div className="hidden rounded-md border border-gray-200 bg-white px-3 py-2 text-right text-xs text-gray-500 sm:block">
            <p className="font-semibold text-gray-900">{data.selected_skill_ids.length + data.selected_tool_ids.length}</p>
            <p>capabilities enabled</p>
          </div>
        </div>
      </div>

      {/* Data Source Selection */}
      <fieldset>
        <legend className="sr-only">Data Source</legend>
        <div className="space-y-4">

          <div className="flex items-center">
            <input
              id="source_rag"
              name="data_source"
              type="radio"
              checked={data.data_source === 'rag'}
              onChange={() => onChange('data_source', 'rag')}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
            />
            <label htmlFor="source_rag" className="ml-3 block text-sm font-medium text-gray-700">
              Retrieval-Augmented Generation (Upload Custom Documents)
            </label>
          </div>
          <div className="flex items-center">
            <input
              id="source_shopify"
              name="data_source"
              type="radio"
              disabled={!isEcommerceTemplate}
              checked={data.data_source === 'shopify'}
              onChange={() => onChange('data_source', 'shopify')}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 disabled:opacity-40"
            />
            <label htmlFor="source_shopify" className={`ml-3 block text-sm font-medium ${isEcommerceTemplate ? 'text-gray-700' : 'text-gray-400'}`}>
              Shopify Store Integration {isEcommerceTemplate ? '' : '(Ecommerce template only)'}
            </label>
          </div>
        </div>
      </fieldset>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-md border border-gray-200 bg-white p-4 shadow-sm">
          <div className="mb-3">
            <h4 className="text-sm font-medium text-gray-900">Skills</h4>
            <p className="mt-1 text-xs text-gray-500">
              Select packaged behavior modules for this agent.
            </p>
          </div>
          {skillsLoading ? (
            <p className="text-sm text-gray-500">Loading skills...</p>
          ) : skills.length === 0 ? (
            <p className="text-sm text-gray-500">No skills endpoint data available yet.</p>
          ) : (
            <div className="space-y-2">
              {skills.map((skill) => {
                const id = capabilityId(skill);
                if (!id) return null;
                return (
                  <label key={id} className="flex items-start gap-3 rounded-md border border-gray-200 bg-gray-50 p-3 transition-colors hover:border-primary-200 hover:bg-white">
                    <input
                      type="checkbox"
                      checked={data.selected_skill_ids.includes(id)}
                      onChange={() => toggleValue('selected_skill_ids', id)}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    <span>
                      <span className="block text-sm font-medium text-gray-900">{skill.name || id}</span>
                      {skill.description && <span className="block text-xs text-gray-500">{skill.description}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <div className="rounded-md border border-gray-200 bg-white p-4 shadow-sm">
          <div className="mb-3">
            <h4 className="text-sm font-medium text-gray-900">Tools</h4>
            <p className="mt-1 text-xs text-gray-500">
              Enable callable tools exposed to the runtime planner.
            </p>
          </div>
          {toolsLoading ? (
            <p className="text-sm text-gray-500">Loading tools...</p>
          ) : tools.length === 0 ? (
            <p className="text-sm text-gray-500">No tools endpoint data available yet.</p>
          ) : (
            <div className="space-y-2">
              {tools.map((tool) => {
                const id = capabilityId(tool);
                if (!id) return null;
                return (
                  <label key={id} className="flex items-start gap-3 rounded-md border border-gray-200 bg-gray-50 p-3 transition-colors hover:border-primary-200 hover:bg-white">
                    <input
                      type="checkbox"
                      checked={data.selected_tool_ids.includes(id)}
                      onChange={() => toggleValue('selected_tool_ids', id)}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    <span>
                      <span className="block text-sm font-medium text-gray-900">{tool.name || id}</span>
                      {tool.description && <span className="block text-xs text-gray-500">{tool.description}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-md border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-medium text-gray-900">Agent API</h4>
            <p className="mt-1 text-xs text-gray-500">
              Create scoped keys for server-to-server sessions, messages, and streaming.
            </p>
          </div>
          <input
            id="agent_api_enabled"
            type="checkbox"
            checked={data.agent_api_enabled}
            onChange={(event) => onChange('agent_api_enabled', event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
        </div>

        {data.agent_api_enabled && (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[1.1fr_0.9fr]">
            <div>
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Allowed keys</p>
                <span className="text-xs text-gray-400">{data.agent_api_key_ids.length} selected</span>
              </div>
              {apiKeysLoading ? (
                <p className="text-sm text-gray-500">Loading API keys...</p>
              ) : apiKeys.length === 0 ? (
                <p className="rounded-md bg-gray-50 p-3 text-sm text-gray-500">
                  No agent API keys endpoint data available yet.
                </p>
              ) : (
                <div className="space-y-2">
                  {apiKeys.map((key) => {
                    const id = String(key.key_id || key.id || key.name || '');
                    if (!id) return null;
                    return (
                      <div key={id} className="flex items-start justify-between gap-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                        <label className="flex min-w-0 flex-1 items-start gap-3">
                          <input
                            type="checkbox"
                            checked={data.agent_api_key_ids.includes(id)}
                            onChange={() => toggleValue('agent_api_key_ids', id)}
                            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium text-gray-900">{key.name || id}</span>
                            <span className="block truncate font-mono text-xs text-gray-500">
                              {key.masked_key || key.key_id || id}
                            </span>
                            {key.is_active === false && (
                              <span className="mt-1 inline-flex rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                                Revoked
                              </span>
                            )}
                          </span>
                        </label>
                        {key.key_id && key.is_active !== false && (
                          <button
                            type="button"
                            onClick={() => revokeApiKeyMutation.mutate(key.key_id!)}
                            disabled={revokeApiKeyMutation.isPending}
                            className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:border-red-200 hover:text-red-700 disabled:opacity-50"
                          >
                            Revoke
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {createdApiKey && (
                <div className="mt-3 rounded-md border border-green-200 bg-green-50 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-green-800">Copy now</p>
                  <p className="mt-1 break-all font-mono text-xs text-green-900">{createdApiKey}</p>
                </div>
              )}
              {agentApiError && (
                <p className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{agentApiError}</p>
              )}
            </div>
            <div className="space-y-4">
              <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
                <label htmlFor="agent_api_key_name" className="block text-sm font-medium text-gray-700">
                  New key name
                </label>
                <div className="mt-2 flex gap-2">
                  <input
                    id="agent_api_key_name"
                    type="text"
                    value={newApiKeyName}
                    onChange={(event) => setNewApiKeyName(event.target.value)}
                    className="block min-w-0 flex-1 rounded-md border-gray-300 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500"
                  />
                  <button
                    type="button"
                    onClick={() => createApiKeyMutation.mutate()}
                    disabled={createApiKeyMutation.isPending}
                    className="rounded-md bg-gray-950 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
                  >
                    {createApiKeyMutation.isPending ? 'Creating' : 'Create'}
                  </button>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  The full key is shown once after creation.
                </p>
              </div>
              <div>
                <label htmlFor="agent_api_allowed_origins" className="block text-sm font-medium text-gray-700">
                  Allowed origins
                </label>
                <textarea
                  id="agent_api_allowed_origins"
                  rows={4}
                  value={data.agent_api_allowed_origins}
                  onChange={(event) => onChange('agent_api_allowed_origins', event.target.value)}
                  placeholder="https://example.com"
                  className="mt-1 block w-full rounded-md border-gray-300 text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500"
                />
                <p className="mt-1 text-xs text-gray-500">Separate origins with commas or new lines.</p>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={data.agent_api_require_key}
                  onChange={(event) => onChange('agent_api_require_key', event.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                Require API key for direct calls
              </label>
            </div>
          </div>
        )}
      </div>

      {/* Shopify Configuration */}
      {data.data_source === 'shopify' && (
        <div className="space-y-6 border-t border-gray-200 pt-6">
          <h4 className="text-md font-medium text-gray-900">Shopify Connection</h4>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <label htmlFor="shopify_shop_url" className="block text-sm font-medium text-gray-700">
                Shopify Store URL *
              </label>
              <input
                type="url"
                id="shopify_shop_url"
                placeholder="https://your-store.myshopify.com"
                value={data.shopify_shop_url}
                onChange={(e) => onChange('shopify_shop_url', e.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                required
              />
            </div>
            <div>
              <label htmlFor="shopify_access_token" className="block text-sm font-medium text-gray-700">
                Access Token (Optional)
              </label>
              <input
                type="password"
                id="shopify_access_token"
                placeholder="shpat_..."
                value={data.shopify_access_token}
                onChange={(e) => onChange('shopify_access_token', e.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                {data.shopify_access_token_configured
                  ? 'A token is already saved for this agent. Enter a new token only to replace it.'
                  : 'Required for store-specific Shopify tools and private catalogs.'}
              </p>
            </div>
          </div>
          
          <div className="bg-gray-50 p-4 rounded-md">
            <div className="flex items-center justify-between">
              <div>
                <h5 className="text-sm font-medium text-gray-900">Sync Product Catalog</h5>
                <p className="text-sm text-gray-500 mt-1">Import products into AgentBuilder for this brand.</p>
                {syncStatus && <p className="text-sm font-semibold mt-2 text-primary-600">{syncStatus}</p>}
              </div>
              <button
                type="button"
                className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
                onClick={handleShopifySync}
                disabled={isSyncing || !data.shopify_shop_url}
              >
                {isSyncing ? 'Syncing...' : 'Sync Now'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RAG Configuration */}
      {data.data_source === 'rag' && (
        <div className="space-y-6 border-t border-gray-200 pt-6">
          <h4 className="text-md font-medium text-gray-900">Embedding Settings</h4>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <label htmlFor="embedding_provider" className="block text-sm font-medium text-gray-700">
                Embedding Provider *
              </label>
              <select
                id="embedding_provider"
                value={data.embedding_provider}
                onChange={(e) => {
                  onChange('embedding_provider', e.target.value);
                  onChange('embedding_model', ''); // Reset model when provider changes
                }}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                required
              >
                <option value="">Select provider</option>
                {embeddingProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="embedding_model" className="block text-sm font-medium text-gray-700">
                Embedding Model *
              </label>
              <select
                id="embedding_model"
                value={data.embedding_model}
                onChange={(e) => onChange('embedding_model', e.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                disabled={!data.embedding_provider}
                required
              >
                <option value="">Select model</option>
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} - {model.description}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <h4 className="text-md font-medium text-gray-900">Retrieval Parameters</h4>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label htmlFor="top_k" className="block text-sm font-medium text-gray-700">
                Top K Results
              </label>
              <input
                type="number"
                id="top_k"
                min="1"
                max="20"
                value={data.top_k}
                onChange={(e) => onChange('top_k', parseInt(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                Number of relevant chunks to retrieve (1-20)
              </p>
            </div>

            <div>
              <label htmlFor="similarity_threshold" className="block text-sm font-medium text-gray-700">
                Similarity Threshold
              </label>
              <div className="mt-1">
                <input
                  type="range"
                  id="similarity_threshold"
                  min="0"
                  max="1"
                  step="0.05"
                  value={data.similarity_threshold}
                  onChange={(e) => onChange('similarity_threshold', parseFloat(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>Loose (0)</span>
                  <span className="font-medium">{data.similarity_threshold}</span>
                  <span>Strict (1)</span>
                </div>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Minimum similarity score
              </p>
            </div>

            <div>
              <label htmlFor="context_window" className="block text-sm font-medium text-gray-700">
                Context Window
              </label>
              <input
                type="number"
                id="context_window"
                min="500"
                max="4000"
                step="100"
                value={data.context_window}
                onChange={(e) => onChange('context_window', parseInt(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                Max tokens for retrieved context
              </p>
            </div>
          </div>

          <h4 className="text-md font-medium text-gray-900">Reranking</h4>
          <div className="space-y-4">
            <div className="flex items-center">
              <input
                id="rerank_enabled"
                type="checkbox"
                checked={data.rerank_enabled}
                onChange={(e) => onChange('rerank_enabled', e.target.checked)}
                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
              />
              <label htmlFor="rerank_enabled" className="ml-2 block text-sm text-gray-900">
                Enable result reranking for better relevance
              </label>
            </div>

            {data.rerank_enabled && (
              <div className="ml-6">
                <label htmlFor="rerank_top_k" className="block text-sm font-medium text-gray-700">
                  Rerank Top K
                </label>
                <input
                  type="number"
                  id="rerank_top_k"
                  min="1"
                  max={Math.min(data.top_k, 10)}
                  value={data.rerank_top_k}
                  onChange={(e) => onChange('rerank_top_k', parseInt(e.target.value))}
                  className="mt-1 block w-32 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Must be ≤ Top K (max {Math.min(data.top_k, 10)})
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="space-y-6 border-t border-gray-200 pt-6">
        <div>
          <h4 className="text-md font-medium text-gray-900">Data Source Policy</h4>
          <p className="mt-1 text-sm text-gray-600">
            Define which approved sources this agent can use for different tasks.
          </p>
        </div>

        <div>
          <label htmlFor="data_source_policy" className="block text-sm font-medium text-gray-700">
            knowledge/index.yaml policy
          </label>
          <textarea
            id="data_source_policy"
            rows={8}
            value={data.data_source_policy}
            onChange={(e) => onChange('data_source_policy', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 font-mono text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500"
            spellCheck={false}
          />
          <p className="mt-1 text-xs text-gray-500">
            JSON is recommended. Plain text is also accepted and will be stored as a policy note.
          </p>
        </div>

        <div>
          <label htmlFor="runtime_variables_schema" className="block text-sm font-medium text-gray-700">
            Runtime variable schema
          </label>
          <textarea
            id="runtime_variables_schema"
            rows={8}
            value={data.runtime_variables_schema}
            onChange={(e) => onChange('runtime_variables_schema', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 font-mono text-sm shadow-sm focus:border-primary-500 focus:ring-primary-500"
            spellCheck={false}
          />
          <p className="mt-1 text-xs text-gray-500">
            These variables are appended at request time, keeping the main prompt stable for caching.
          </p>
        </div>
      </div>

    </div>
  );
}
