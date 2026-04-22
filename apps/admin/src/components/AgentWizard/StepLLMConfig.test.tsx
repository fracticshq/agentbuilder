import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import StepLLMConfig from './StepLLMConfig';
import { api } from '../../api/client';

jest.mock('../../api/client', () => ({
  api: {
    getAzureDeployments: jest.fn(),
  },
}));

const mockGetAzureDeployments = api.getAzureDeployments as jest.Mock;

function renderStep(initialData?: Partial<React.ComponentProps<typeof StepLLMConfig>['data']>) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const baseData = {
    provider: 'azure_openai',
    model: '',
    temperature: 0.7,
    max_tokens: 2000,
    top_p: 1,
    frequency_penalty: 0,
    presence_penalty: 0,
    ...initialData,
  };

  function Harness() {
    const [data, setData] = React.useState(baseData);
    return (
      <QueryClientProvider client={queryClient}>
        <StepLLMConfig
          data={data}
          onChange={(field, value) =>
            setData((prev) => ({
              ...prev,
              [field]: value,
            }))
          }
        />
        <div data-testid="provider-value">{data.provider}</div>
        <div data-testid="model-value">{data.model}</div>
      </QueryClientProvider>
    );
  }

  return render(<Harness />);
}

beforeEach(() => {
  mockGetAzureDeployments.mockReset();
});

test('renders Azure deployments and auto-selects the configured default deployment', async () => {
  mockGetAzureDeployments.mockResolvedValue({
    provider: 'azure_openai',
    default_deployment: 'gpt-5.4-mini',
    deployments: [
      {
        deployment_name: 'gpt-5.4-mini',
        model_name: 'gpt-5.4-mini',
        model_version: '2025-04-14',
        provisioning_state: 'Succeeded',
        sku_name: 'Standard',
      },
    ],
  });

  renderStep();

  expect(screen.getByText(/Fetching Azure OpenAI deployments/i)).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByTestId('provider-value')).toHaveTextContent('azure_openai');
    expect(screen.getByTestId('model-value')).toHaveTextContent('gpt-5.4-mini');
  });

  expect(screen.getByText('Azure OpenAI')).toBeInTheDocument();
  expect(screen.getByRole('option', { name: /gpt-5\.4-mini — gpt-5\.4-mini \(2025-04-14\)/i })).toBeInTheDocument();
});

test('preserves the saved deployment when it is no longer discovered', async () => {
  mockGetAzureDeployments.mockResolvedValue({
    provider: 'azure_openai',
    default_deployment: 'gpt-5.4-mini',
    deployments: [
      {
        deployment_name: 'gpt-5.4-mini',
        model_name: 'gpt-5.4-mini',
        model_version: '2025-04-14',
        provisioning_state: 'Succeeded',
        sku_name: 'Standard',
      },
    ],
  });

  renderStep({ model: 'legacy-deployment' });

  await waitFor(() => {
    expect(screen.getByRole('option', { name: /Current saved deployment \(not currently discovered\): legacy-deployment/i })).toBeInTheDocument();
  });

  expect(screen.getByTestId('model-value')).toHaveTextContent('legacy-deployment');
});

test('shows an inline retry state when deployment discovery fails', async () => {
  mockGetAzureDeployments
    .mockRejectedValueOnce(new Error('Azure ARM unavailable'))
    .mockResolvedValueOnce({
      provider: 'azure_openai',
      default_deployment: 'gpt-5.4-mini',
      deployments: [
        {
          deployment_name: 'gpt-5.4-mini',
          model_name: 'gpt-5.4-mini',
          model_version: '2025-04-14',
          provisioning_state: 'Succeeded',
          sku_name: 'Standard',
        },
      ],
    });

  renderStep();

  await waitFor(() => {
    expect(screen.getByText(/Could not load Azure deployments/i)).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('button', { name: /Retry/i }));

  await waitFor(() => {
    expect(screen.getByTestId('model-value')).toHaveTextContent('gpt-5.4-mini');
  });
});

test('shows the empty state when no Azure deployments are available', async () => {
  mockGetAzureDeployments.mockResolvedValue({
    provider: 'azure_openai',
    default_deployment: null,
    deployments: [],
  });

  renderStep();

  await waitFor(() => {
    expect(screen.getByText(/No Azure OpenAI deployments are currently available/i)).toBeInTheDocument();
  });
});
