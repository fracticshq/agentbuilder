import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

import DocumentsList from './DocumentsList';
import { knowledgeApi } from '../../api/knowledge';
import { useAdminApiKey } from '../../hooks/useAdminApiKey';

jest.mock('../../api/knowledge', () => ({
  knowledgeApi: {
    getDocuments: jest.fn(),
  },
}));

jest.mock('../../hooks/useAdminApiKey', () => ({
  useAdminApiKey: jest.fn(),
}));

const mockGetDocuments = knowledgeApi.getDocuments as jest.Mock;
const mockUseAdminApiKey = useAdminApiKey as jest.Mock;

beforeEach(() => {
  mockGetDocuments.mockReset();
  mockUseAdminApiKey.mockReset();
  mockUseAdminApiKey.mockReturnValue(true);
});

test('shows admin key guidance instead of an auth error when no admin key is saved', async () => {
  mockUseAdminApiKey.mockReturnValue(false);

  render(<DocumentsList brandId="essco-bathware" />);

  await waitFor(() => {
    expect(screen.getByText(/Admin write access key required/i)).toBeInTheDocument();
  });

  expect(screen.getByText(/Save the admin key in the top bar to load and manage knowledge base documents/i)).toBeInTheDocument();
  expect(mockGetDocuments).not.toHaveBeenCalled();
});
