export interface LlmModelOption {
  id: string;
  name: string;
  description: string;
}

export interface LlmProviderOption {
  id: string;
  name: string;
  models: LlmModelOption[];
}

export const llmProviders: LlmProviderOption[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    models: [
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini', description: 'Fast and cost-effective' },
      { id: 'gpt-4o', name: 'GPT-4o', description: 'Most capable model' },
      { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: 'Good balance of cost and performance' },
    ],
  },
  {
    id: 'azure_openai',
    name: 'Azure OpenAI',
    models: [
      { id: 'gpt-5.4-mini', name: 'GPT-5.4 Mini', description: 'Azure OpenAI deployment for fast GPT-5.4 responses' },
    ],
  },
  {
    id: 'qwen',
    name: 'Qwen (Alibaba Cloud)',
    models: [
      { id: 'qwen-turbo', name: 'Qwen Turbo', description: 'Fast and efficient' },
      { id: 'qwen-plus', name: 'Qwen Plus', description: 'Enhanced capabilities' },
      { id: 'qwen-max', name: 'Qwen Max', description: 'Most advanced model' },
    ],
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    models: [
      { id: 'claude-3-haiku', name: 'Claude 3 Haiku', description: 'Fast and lightweight' },
      { id: 'claude-3-sonnet', name: 'Claude 3 Sonnet', description: 'Balanced performance' },
      { id: 'claude-3-opus', name: 'Claude 3 Opus', description: 'Most capable model' },
    ],
  },
];

export function getProviderOption(providerId?: string): LlmProviderOption | undefined {
  return llmProviders.find((provider) => provider.id === providerId);
}

export function getProviderLabel(providerId?: string): string {
  if (!providerId) {
    return 'Not set';
  }
  return getProviderOption(providerId)?.name || providerId;
}

export function getDefaultModel(providerId?: string): string {
  return getProviderOption(providerId)?.models[0]?.id || '';
}

export function getAvailableModels(providerId?: string, currentModel?: string): LlmModelOption[] {
  const models = [...(getProviderOption(providerId)?.models || [])];
  if (currentModel && !models.some((model) => model.id === currentModel)) {
    models.unshift({
      id: currentModel,
      name: currentModel,
      description: 'Current saved model/deployment',
    });
  }
  return models;
}

export function getModelLabel(providerId?: string, modelId?: string): string {
  if (!modelId) {
    return 'Not set';
  }
  const model = getAvailableModels(providerId, modelId).find((entry) => entry.id === modelId);
  return model?.name || modelId;
}
