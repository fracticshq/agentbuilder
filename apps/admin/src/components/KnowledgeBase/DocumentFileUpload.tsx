import React, { useState } from 'react';
import { CheckCircleIcon, DocumentArrowUpIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import { knowledgeApi } from '../../api/knowledge';
import type { KnowledgeFolderSelection, UploadDocumentResponse } from '../../types/knowledge';

const ACCEPTED_DOCUMENT_TYPES = '.pdf,.docx,.txt,.md,.markdown,.html,.htm,.csv';
const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'txt', 'md', 'markdown', 'html', 'htm', 'csv'];

interface DocumentFileUploadProps {
  brandId: string;
  agentId?: string;
  selectedFolder?: KnowledgeFolderSelection;
  onComplete: (response: UploadDocumentResponse) => void;
  onBack: () => void;
}

function formatFileSize(size: number): string {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isAcceptedDocument(file: File): boolean {
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  return ACCEPTED_EXTENSIONS.includes(extension);
}

export default function DocumentFileUpload({ brandId, agentId, selectedFolder, onComplete, onBack }: DocumentFileUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] || null;
    setError(null);

    if (!nextFile) {
      setFile(null);
      return;
    }

    if (!isAcceptedDocument(nextFile)) {
      setFile(null);
      setError('Choose a PDF, DOCX, TXT, Markdown, HTML, or CSV file.');
      return;
    }

    setFile(nextFile);
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Choose a document before uploading.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const response = await knowledgeApi.uploadDocument({
        file,
        content_type: 'document',
        brand_id: brandId,
        agent_id: agentId,
        folder_id: selectedFolder?.id || undefined,
        folder_path: selectedFolder?.path || '/',
      });
      onComplete(response);
    } catch (uploadError: any) {
      setError(uploadError?.details || uploadError?.message || 'Document upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <label className="block w-full">
        <div className="mt-1 flex justify-center rounded-md border-2 border-dashed border-gray-300 px-6 pb-6 pt-5 hover:border-primary-400">
          <div className="space-y-2 text-center">
            <DocumentArrowUpIcon className="mx-auto h-12 w-12 text-gray-400" />
            <div className="text-sm text-gray-600">
              <span className="relative cursor-pointer rounded-md bg-white font-medium text-primary-600 hover:text-primary-500">
                Choose a document file
              </span>
              <input
                type="file"
                accept={ACCEPTED_DOCUMENT_TYPES}
                onChange={handleFileChange}
                className="sr-only"
                data-testid="document-file-input"
              />
            </div>
            <p className="text-xs text-gray-500">PDF, DOCX, TXT, Markdown, HTML, or CSV</p>
            {file && (
              <div className="inline-flex items-center rounded-full bg-green-50 px-3 py-1 text-sm font-medium text-green-700">
                <CheckCircleIcon className="mr-1.5 h-4 w-4" />
                {file.name} · {formatFileSize(file.size)}
              </div>
            )}
          </div>
        </div>
      </label>

      {error && (
        <div className="rounded-md bg-red-50 p-4">
          <div className="flex">
            <ExclamationTriangleIcon className="h-5 w-5 text-red-400" />
            <p className="ml-3 text-sm text-red-700">{error}</p>
          </div>
        </div>
      )}

      <div className="rounded-md bg-blue-50 p-4">
        <p className="text-sm text-blue-800">
          Documents are uploaded to <span className="font-mono">{selectedFolder?.path || '/'}</span> and chunked for retrieval. Use structured JSON for product or dealer records that need exact field mapping.
        </p>
      </div>

      <div className="flex justify-between border-t border-gray-200 pt-6">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back
        </button>
        <button
          type="button"
          onClick={handleUpload}
          disabled={!file || uploading}
          className={`rounded-md px-6 py-2 text-sm font-medium text-white ${
            file && !uploading
              ? 'bg-primary-600 hover:bg-primary-700'
              : 'cursor-not-allowed bg-gray-300'
          }`}
        >
          {uploading ? 'Uploading...' : 'Upload Document'}
        </button>
      </div>
    </div>
  );
}
