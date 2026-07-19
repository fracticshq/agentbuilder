import { vi, type Mock } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import DocumentFileUpload from './DocumentFileUpload';
import { knowledgeApi } from '../../api/knowledge';

vi.mock('../../api/knowledge', () => ({
  knowledgeApi: {
    uploadDocument: vi.fn(),
  },
}));

const mockUploadDocument = knowledgeApi.uploadDocument as Mock;

beforeEach(() => {
  mockUploadDocument.mockReset();
});

test('accepts document files and uploads them to the knowledge API', async () => {
  mockUploadDocument.mockResolvedValue({
    success: true,
    job_id: 'job-1',
    message: 'Uploaded',
    items_count: 1,
    status: 'completed',
  });
  const onComplete = vi.fn();

  render(<DocumentFileUpload brandId="brand-123" onComplete={onComplete} onBack={vi.fn()} />);

  const file = new File(['hello'], 'guide.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByTestId('document-file-input'), {
    target: { files: [file] },
  });

  expect(screen.getByText(/guide\.pdf/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /Upload Document/i }));

  await waitFor(() => {
    expect(mockUploadDocument).toHaveBeenCalledWith({
      file,
      content_type: 'document',
      brand_id: 'brand-123',
      folder_id: undefined,
      folder_path: '/',
    });
    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job-1' }));
  });
});

test('uploads documents into the selected folder path', async () => {
  mockUploadDocument.mockResolvedValue({
    success: true,
    job_id: 'job-folder',
    message: 'Uploaded',
    items_count: 1,
    status: 'completed',
  });

  render(
    <DocumentFileUpload
      brandId="brand-123"
      selectedFolder={{ id: 'folder-guides', path: '/guides', name: 'Guides' }}
      onComplete={vi.fn()}
      onBack={vi.fn()}
    />
  );

  const file = new File(['hello'], 'install.md', { type: 'text/markdown' });
  fireEvent.change(screen.getByTestId('document-file-input'), {
    target: { files: [file] },
  });

  fireEvent.click(screen.getByRole('button', { name: /Upload Document/i }));

  await waitFor(() => {
    expect(mockUploadDocument).toHaveBeenCalledWith({
      file,
      content_type: 'document',
      brand_id: 'brand-123',
      folder_id: 'folder-guides',
      folder_path: '/guides',
    });
  });
});

test('rejects unsupported file extensions before upload', () => {
  render(<DocumentFileUpload brandId="brand-123" onComplete={vi.fn()} onBack={vi.fn()} />);

  const file = new File(['{}'], 'data.json', { type: 'application/json' });
  fireEvent.change(screen.getByTestId('document-file-input'), {
    target: { files: [file] },
  });

  expect(screen.getByText(/Choose a PDF, DOCX, TXT, Markdown, HTML, or CSV file/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Upload Document/i })).toBeDisabled();
  expect(mockUploadDocument).not.toHaveBeenCalled();
});
