import type { AzureOpenAIDeployment, AzureOpenAIDeploymentsResponse } from '../api/client';

export interface LlmModelOption {
  id: string;
  name: string;
  description: string;
  stale?: boolean;
}

export const AZURE_OPENAI_PROVIDER = 'azure_openai';
export const AZURE_OPENAI_PROVIDER_LABEL = 'Azure OpenAI';

export function isAzureOpenAIProvider(providerId?: string): boolean {
  return providerId === AZURE_OPENAI_PROVIDER;
}

export function getProviderLabel(providerId?: string): string {
  if (!providerId) {
    return 'Not set';
  }
  return isAzureOpenAIProvider(providerId) ? AZURE_OPENAI_PROVIDER_LABEL : providerId;
}

export function formatDeploymentLabel(deployment: AzureOpenAIDeployment): string {
  const modelVersion = deployment.model_version ? ` (${deployment.model_version})` : '';
  return `${deployment.deployment_name} — ${deployment.model_name}${modelVersion}`;
}

export function getDefaultDeployment(
  catalog?: AzureOpenAIDeploymentsResponse,
  currentModel?: string
): string {
  if (currentModel) {
    return currentModel;
  }

  const deployments = catalog?.deployments || [];
  if (!deployments.length) {
    return '';
  }

  if (
    catalog?.default_deployment &&
    deployments.some((deployment) => deployment.deployment_name === catalog.default_deployment)
  ) {
    return catalog.default_deployment;
  }

  return deployments[0]?.deployment_name || '';
}

export function getAzureDeploymentOptions(
  deployments: AzureOpenAIDeployment[],
  currentModel?: string
): LlmModelOption[] {
  const options: LlmModelOption[] = deployments.map((deployment) => ({
    id: deployment.deployment_name,
    name: formatDeploymentLabel(deployment),
    description: deployment.sku_name || deployment.provisioning_state,
  }));

  if (currentModel && !deployments.some((deployment) => deployment.deployment_name === currentModel)) {
    options.unshift({
      id: currentModel,
      name: `Current saved deployment (not currently discovered): ${currentModel}`,
      description: 'Preserved from the saved agent configuration',
      stale: true,
    });
  }

  return options;
}

export function getModelLabel(
  providerId?: string,
  modelId?: string,
  deployments?: AzureOpenAIDeployment[]
): string {
  if (!modelId) {
    return 'Not set';
  }

  if (!isAzureOpenAIProvider(providerId)) {
    return modelId;
  }

  const deployment = deployments?.find((entry) => entry.deployment_name === modelId);
  return deployment ? formatDeploymentLabel(deployment) : modelId;
}
