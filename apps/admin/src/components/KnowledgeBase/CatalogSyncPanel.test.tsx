import { vi, type Mock } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import CatalogSyncPanel from './CatalogSyncPanel';
import { catalogApi } from '../../api/catalog';

vi.mock('../../api/catalog', () => ({
  catalogApi: {
    getSyncConfig: vi.fn(),
    updateSyncConfig: vi.fn(),
    startSync: vi.fn(),
    getJob: vi.fn(),
  },
}));

const mockGetSyncConfig = catalogApi.getSyncConfig as Mock;
const mockUpdateSyncConfig = catalogApi.updateSyncConfig as Mock;

beforeEach(() => {
  vi.clearAllMocks();
  mockGetSyncConfig.mockResolvedValue({
    source_type: 'shopify',
    source_url: 'https://celavilifestyle.com',
    access_token_configured: true,
    last_sync_status: 'completed',
    last_synced_at: '2026-07-18T08:00:00Z',
    last_sync_counts: {
      products_seen: 4,
      products_upserted: 4,
      products_marked_inactive: 1,
      error_count: 0,
    },
  });
  mockUpdateSyncConfig.mockResolvedValue({
    source_url: 'https://celavilifestyle.com',
    access_token_configured: true,
  });
});

test('shows brand catalog status and opens encrypted sync settings', async () => {
  render(<CatalogSyncPanel brandId="brand-1" brandName="Celavi Lifestyle" />);

  expect(await screen.findByText('Catalog Sync')).toBeInTheDocument();
  expect((await screen.findAllByText('4')).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: /Manage sync/i }));

  expect(await screen.findByRole('heading', { name: /Shopify Catalog Sync/i })).toBeInTheDocument();
  expect(await screen.findByPlaceholderText(/Token already configured/i)).toBeInTheDocument();
});

test('saves the store URL and never requires the redacted token value', async () => {
  render(<CatalogSyncPanel brandId="brand-1" />);
  fireEvent.click(await screen.findByRole('button', { name: /Manage sync/i }));
  fireEvent.click(await screen.findByRole('button', { name: /Save settings/i }));

  await waitFor(() => expect(mockUpdateSyncConfig).toHaveBeenCalledWith(
    'brand-1',
    expect.objectContaining({
      source_type: 'shopify',
      source_url: 'https://celavilifestyle.com',
    }),
  ));
  expect(mockUpdateSyncConfig.mock.calls[0][1]).not.toHaveProperty('access_token');
});
