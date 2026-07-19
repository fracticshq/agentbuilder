import { vi, type Mocked } from 'vitest';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import Settings from './Settings';
import { runtimeSettingsApi } from '../api/client';

vi.mock('axios', () => ({
  __esModule: true,
  default: {
    isAxiosError: vi.fn(() => false),
    create: vi.fn(() => ({
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    })),
  },
}));

vi.mock('../api/client', () => ({
  runtimeSettingsApi: {
    get: vi.fn(),
    update: vi.fn(),
    test: vi.fn(),
  },
}));

const mockRuntimeSettingsApi = runtimeSettingsApi as Mocked<typeof runtimeSettingsApi>;

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <Settings />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockRuntimeSettingsApi.get.mockReset();
  mockRuntimeSettingsApi.update.mockReset();
  mockRuntimeSettingsApi.test.mockReset();
});

test('renders a visible connection test action for supported sections', async () => {
  mockRuntimeSettingsApi.get.mockResolvedValue({
    data: {
      sections: [
        {
          id: 'azure_openai',
          title: 'Azure OpenAI',
          description: 'Manage Azure OpenAI keys and deployment settings.',
          supports_connection_test: true,
          fields: [
            {
              key: 'azure_openai_api_key',
              label: 'Azure OpenAI API Key',
              description: 'Used for inference requests.',
              input_type: 'password',
              secret: true,
              required: true,
              configured: true,
              source: 'stored',
              masked_value: 'az-123456789012345678901234567890',
            },
          ],
        },
      ],
    },
  } as any);

  renderSettings();

  expect(await screen.findByText('Azure OpenAI')).toBeInTheDocument();
  expect(screen.getByText('Connection test')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Test Connection' })).toBeInTheDocument();
});

test('shows the section test result after the action is triggered', async () => {
  mockRuntimeSettingsApi.get.mockResolvedValue({
    data: {
      sections: [
        {
          id: 'voyage',
          title: 'Voyage',
          description: 'Manage embeddings and rerank credentials.',
          supports_connection_test: true,
          fields: [
            {
              key: 'voyage_api_key',
              label: 'Voyage API Key',
              description: 'Used for embeddings and reranking.',
              input_type: 'password',
              secret: true,
              required: true,
              configured: true,
              source: 'environment',
              masked_value: 'vo-123456789012345678901234567890',
            },
          ],
        },
      ],
    },
  } as any);

  mockRuntimeSettingsApi.test.mockResolvedValue({
    data: {
      status: 'healthy',
      results: [
        {
          section: 'voyage',
          status: 'healthy',
          detail: 'Voyage credentials look healthy.',
        },
      ],
    },
  } as any);

  renderSettings();

  fireEvent.click(await screen.findByRole('button', { name: 'Test Connection' }));

  await waitFor(() => {
    expect(screen.getByText('Voyage credentials look healthy.')).toBeInTheDocument();
  });
});
