import React from 'react';

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

const providers = [
  { 
    id: 'openai', 
    name: 'OpenAI',
    models: [
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', description: 'Fast and cost-effective' },
      { id: 'gpt-4o', name: 'GPT-4o', description: 'Most capable model' },
      { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: 'Good balance of cost and performance' },
    ]
  },
  {
    id: 'azure_openai',
    name: 'Azure OpenAI',
    models: [
      { id: 'gpt-5.4-mini', name: 'GPT-5.4 Mini', description: 'Azure OpenAI deployment for fast GPT-5.4 responses' },
    ]
  },
  { 
    id: 'qwen', 
    name: 'Qwen (Alibaba Cloud)',
    models: [
      { id: 'qwen-turbo', name: 'Qwen Turbo', description: 'Fast and efficient' },
      { id: 'qwen-plus', name: 'Qwen Plus', description: 'Enhanced capabilities' },
      { id: 'qwen-max', name: 'Qwen Max', description: 'Most advanced model' },
    ]
  },
  { 
    id: 'anthropic', 
    name: 'Anthropic',
    models: [
      { id: 'claude-3-haiku', name: 'Claude 3 Haiku', description: 'Fast and lightweight' },
      { id: 'claude-3-sonnet', name: 'Claude 3 Sonnet', description: 'Balanced performance' },
      { id: 'claude-3-opus', name: 'Claude 3 Opus', description: 'Most capable model' },
    ]
  }
];

export default function StepLLMConfig({ data, onChange }: StepLLMConfigProps) {
  const selectedProvider = providers.find(p => p.id === data.provider);
  const availableModels = selectedProvider?.models || [];

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">LLM Configuration</h3>
        <p className="mt-1 text-sm text-gray-600">
          Choose the language model provider and configure its parameters.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label htmlFor="provider" className="block text-sm font-medium text-gray-700">
            Provider *
          </label>
          <select
            id="provider"
            value={data.provider}
            onChange={(e) => {
              onChange('provider', e.target.value);
              // Reset model when provider changes
              onChange('model', '');
            }}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
            required
          >
            <option value="">Select a provider</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="model" className="block text-sm font-medium text-gray-700">
            Model *
          </label>
          <select
            id="model"
            value={data.model}
            onChange={(e) => onChange('model', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
            disabled={!data.provider}
            required
          >
            <option value="">Select a model</option>
            {availableModels.map((model) => (
              <option key={model.id} value={model.id}>
                {model.name} - {model.description}
              </option>
            ))}
          </select>
        </div>
      </div>

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
