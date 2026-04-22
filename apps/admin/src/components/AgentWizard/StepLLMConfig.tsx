import React, { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, AzureOpenAIDeploymentsResponse } from '../../api/client';
import {
  AZURE_OPENAI_PROVIDER,
  AZURE_OPENAI_PROVIDER_LABEL,
  getAzureDeploymentOptions,
  getDefaultDeployment,
} from '../../utils/llmOptions';

interface StepLLMConfigProps {
  data: {
    provider: string;
    model: string;
    temperature: number;
    max_tokens: number;
    top_p: number;
    frequency_penalty: number;
    presence_penalty: number;
  };
  onChange: (field: string, value: string | number) => void;
}

export default function StepLLMConfig({ data, onChange }: StepLLMConfigProps) {
  const {
    data: deploymentCatalog,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<AzureOpenAIDeploymentsResponse>({
    queryKey: ['admin', 'azure-openai-deployments'],
    queryFn: api.getAzureDeployments,
    staleTime: 60_000,
    retry: false,
  });

  const availableDeployments = getAzureDeploymentOptions(
    deploymentCatalog?.deployments || [],
    data.model
  );
  const hasDiscoveredDeployments = Boolean(deploymentCatalog?.deployments?.length);

  useEffect(() => {
    if (data.provider !== AZURE_OPENAI_PROVIDER) {
      onChange('provider', AZURE_OPENAI_PROVIDER);
    }
  }, [data.provider, onChange]);

  useEffect(() => {
    if (data.model) {
      return;
    }

    const preferredDeployment = getDefaultDeployment(deploymentCatalog, data.model);
    if (preferredDeployment) {
      onChange('model', preferredDeployment);
    }
  }, [data.model, deploymentCatalog, onChange]);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">LLM Configuration</h3>
        <p className="mt-1 text-sm text-gray-600">
          This dashboard now uses Azure OpenAI deployments discovered from the backend.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Provider
          </label>
          <div className="mt-1 block w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-700 shadow-sm">
            {AZURE_OPENAI_PROVIDER_LABEL}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Provider selection is managed centrally through Azure OpenAI.
          </p>
        </div>

        <div>
          <label htmlFor="model" className="block text-sm font-medium text-gray-700">
            Azure Deployment *
          </label>
          <select
            id="model"
            value={data.model}
            onChange={(e) => onChange('model', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
            disabled={isLoading || (!availableDeployments.length && !data.model)}
            required
          >
            <option value="">
              {isLoading ? 'Loading Azure deployments...' : 'Select an Azure deployment'}
            </option>
            {availableDeployments.map((model) => (
              <option key={model.id} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-gray-500">
            Only deployments currently configured on your Azure OpenAI resource are shown here.
          </p>
        </div>
      </div>

      {isLoading && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          Fetching Azure OpenAI deployments from the backend.
        </div>
      )}

      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-sm font-medium text-red-900">
                Could not load Azure deployments
              </h4>
              <p className="mt-1 text-sm text-red-800">
                {error instanceof Error
                  ? error.message
                  : 'The backend could not discover Azure OpenAI deployments.'}
              </p>
            </div>
            <button
              type="button"
              onClick={() => refetch()}
              className="inline-flex items-center rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {!isLoading && !isError && !hasDiscoveredDeployments && !data.model && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
          No Azure OpenAI deployments are currently available. Configure a deployment on the Azure resource before continuing.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label htmlFor="temperature" className="block text-sm font-medium text-gray-700">
            Temperature
          </label>
          <div className="mt-1">
            <input
              type="range"
              id="temperature"
              min="0"
              max="2"
              step="0.1"
              value={data.temperature}
              onChange={(e) => onChange('temperature', parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>Conservative (0)</span>
              <span className="font-medium">{data.temperature}</span>
              <span>Creative (2)</span>
            </div>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Controls randomness in responses. Lower values are more focused and deterministic.
          </p>
        </div>

        <div>
          <label htmlFor="max_tokens" className="block text-sm font-medium text-gray-700">
            Max Tokens
          </label>
          <input
            type="number"
            id="max_tokens"
            min="100"
            max="4000"
            value={data.max_tokens}
            onChange={(e) => onChange('max_tokens', parseInt(e.target.value))}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Maximum length of the response (100-4000 tokens).
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div>
          <label htmlFor="top_p" className="block text-sm font-medium text-gray-700">
            Top P
          </label>
          <input
            type="range"
            id="top_p"
            min="0"
            max="1"
            step="0.05"
            value={data.top_p}
            onChange={(e) => onChange('top_p', parseFloat(e.target.value))}
            className="mt-1 w-full"
          />
          <div className="text-center text-xs text-gray-500 mt-1">{data.top_p}</div>
        </div>

        <div>
          <label htmlFor="frequency_penalty" className="block text-sm font-medium text-gray-700">
            Frequency Penalty
          </label>
          <input
            type="range"
            id="frequency_penalty"
            min="0"
            max="2"
            step="0.1"
            value={data.frequency_penalty}
            onChange={(e) => onChange('frequency_penalty', parseFloat(e.target.value))}
            className="mt-1 w-full"
          />
          <div className="text-center text-xs text-gray-500 mt-1">{data.frequency_penalty}</div>
        </div>

        <div>
          <label htmlFor="presence_penalty" className="block text-sm font-medium text-gray-700">
            Presence Penalty
          </label>
          <input
            type="range"
            id="presence_penalty"
            min="0"
            max="2"
            step="0.1"
            value={data.presence_penalty}
            onChange={(e) => onChange('presence_penalty', parseFloat(e.target.value))}
            className="mt-1 w-full"
          />
          <div className="text-center text-xs text-gray-500 mt-1">{data.presence_penalty}</div>
        </div>
      </div>

      <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-yellow-800">
              Configuration Tips
            </h3>
            <div className="mt-2 text-sm text-yellow-700">
              <ul className="list-disc pl-5 space-y-1">
                <li><strong>Temperature:</strong> Start with 0.7 for balanced responses</li>
                <li><strong>Max Tokens:</strong> 1000-2000 tokens work well for most use cases</li>
                <li><strong>Top P:</strong> Alternative to temperature, usually keep at 1.0</li>
                <li><strong>Penalties:</strong> Use small values (0.1-0.3) to reduce repetition</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
