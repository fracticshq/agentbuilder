import { vi, type Mock } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import DocumentsList from './DocumentsList';
import { knowledgeApi } from '../../api/knowledge';

vi.mock('../../api/knowledge', () => ({
  knowledgeApi: {
    getDocuments: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

const mockGetDocuments = knowledgeApi.getDocuments as Mock;

beforeEach(() => {
  mockGetDocuments.mockReset();
});

test('loads and renders uploaded documents for the authenticated dashboard', async () => {
  mockGetDocuments.mockResolvedValue([
    {
      doc_id: 'doc-1',
      title: 'Essco Shower Catalog',
      content_type: 'product',
      chunks_count: 12,
      item_count: 5,
      created_at: '2026-04-23T00:00:00Z',
    },
  ]);

  render(<DocumentsList brandId="brand-123" />);

  expect(screen.getByText(/Loading documents/i)).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByText('Essco Shower Catalog')).toBeInTheDocument();
  });

  expect(mockGetDocuments).toHaveBeenCalledWith('brand-123', undefined);
});

test('shows an error state and lets the operator retry', async () => {
  mockGetDocuments
    .mockRejectedValueOnce(new Error('Authentication required'))
    .mockResolvedValueOnce([]);

  render(<DocumentsList brandId="brand-123" contentType="faq" />);

  await waitFor(() => {
    expect(screen.getByText(/Error loading documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Authentication required/i)).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('button', { name: /Try again/i }));

  await waitFor(() => {
    expect(mockGetDocuments).toHaveBeenCalledTimes(2);
  });
});
