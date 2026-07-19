import { vi, type Mock } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import KnowledgeExplorer from './KnowledgeExplorer';
import { knowledgeApi } from '../../api/knowledge';

vi.mock('../../api/knowledge', () => ({
  knowledgeApi: {
    getTree: vi.fn(),
    getDocuments: vi.fn(),
    createFolder: vi.fn(),
    moveItem: vi.fn(),
    renameItem: vi.fn(),
    deleteItem: vi.fn(),
    retrieve: vi.fn(),
  },
}));

const mockGetTree = knowledgeApi.getTree as Mock;
const mockRetrieve = knowledgeApi.retrieve as Mock;

beforeEach(() => {
  vi.clearAllMocks();
});

test('renders folders, selected folder files, and uploads into the selected path', async () => {
  const onUpload = vi.fn();
  mockGetTree.mockResolvedValue({
    root: {
      id: null,
      name: 'Knowledge Base',
      path: '/',
      children: [
        {
          id: 'guides',
          name: 'Guides',
          path: '/guides',
          children: [],
          items: [
            {
              id: 'doc-1',
              name: 'Install Manual',
              kind: 'document',
              path: '/guides/Install Manual',
              content_type: 'guide',
              chunks_count: 8,
              item_count: 1,
              status: 'ready',
            },
          ],
        },
      ],
      documents: [
        {
          doc_id: 'root-doc',
          title: 'Root FAQ',
          content_type: 'faq',
          chunks_count: 3,
          item_count: 1,
        },
      ],
    },
  });

  render(<KnowledgeExplorer brandId="brand-123" onUpload={onUpload} />);

  await waitFor(() => {
    expect(screen.getAllByText('Guides').length).toBeGreaterThan(0);
    expect(screen.getByText('Root FAQ')).toBeInTheDocument();
  });

  fireEvent.click(screen.getAllByRole('button', { name: 'Guides' })[0]);

  await waitFor(() => {
    expect(screen.getByText('Install Manual')).toBeInTheDocument();
  });

  fireEvent.click(screen.getByRole('button', { name: /Upload/i }));

  expect(onUpload).toHaveBeenCalledWith({
    id: 'guides',
    path: '/guides',
    name: 'Guides',
  });
});

test('runs retrieval scoped to the selected folder', async () => {
  mockGetTree.mockResolvedValue({
    root: {
      id: null,
      name: 'Knowledge Base',
      path: '/',
      children: [],
      items: [],
    },
  });
  mockRetrieve.mockResolvedValue({
    query: 'warranty',
    results: [
      {
        id: 'result-1',
        title: 'Warranty Policy',
        content: 'Covered for two years from purchase.',
        score: 0.821,
        path: '/Warranty Policy',
      },
    ],
  });

  render(<KnowledgeExplorer brandId="brand-123" onUpload={vi.fn()} />);

  fireEvent.change(await screen.findByPlaceholderText(/Ask what this folder should answer/i), {
    target: { value: 'warranty' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Test Retrieval/i }));

  await waitFor(() => {
    expect(mockRetrieve).toHaveBeenCalledWith({
      query: 'warranty',
      brand_id: 'brand-123',
      folder_id: null,
      folder_path: '/',
      top_k: 5,
    });
    expect(screen.getByText('Warranty Policy')).toBeInTheDocument();
  });
});
