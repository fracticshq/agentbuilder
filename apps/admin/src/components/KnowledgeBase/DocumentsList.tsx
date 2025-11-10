import React, { useState, useEffect } from 'react';
import { TrashIcon, DocumentTextIcon, ArrowPathIcon } from '@heroicons/react/24/outline';
import { knowledgeApi } from '../../api/knowledge';
import type { DocumentSummary, ContentType } from '../../types/knowledge';

interface DocumentsListProps {
  brandId: string;
  contentType?: ContentType;
  onRefresh?: () => void;
}

export default function DocumentsList({ brandId, contentType, onRefresh }: DocumentsListProps) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);

  const fetchDocuments = async () => {
    try {
      console.log('[DocumentsList] Fetching documents for:', { brandId, contentType });
      setLoading(true);
      setError(null);
      const docs = await knowledgeApi.getDocuments(brandId, contentType);
      console.log('[DocumentsList] Fetched documents:', { count: docs.length, docs });
      setDocuments(docs);
    } catch (err: any) {
      console.error('[DocumentsList] Failed to fetch documents:', err);
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, contentType]);

  const handleDelete = async (docId: string, docName: string) => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm(`Are you sure you want to delete "${docName}"? This will remove all associated chunks and cannot be undone.`)) {
      return;
    }

    try {
      setDeletingDocId(docId);
      await knowledgeApi.deleteDocument(docId, brandId);
      
      // Remove from local state
      setDocuments(prev => prev.filter(doc => doc.doc_id !== docId));
      
      // Notify parent
      if (onRefresh) {
        onRefresh();
      }
    } catch (err: any) {
      console.error('Failed to delete document:', err);
      alert(`Failed to delete document: ${err.message}`);
    } finally {
      setDeletingDocId(null);
    }
  };

  const handleRefresh = () => {
    fetchDocuments();
    if (onRefresh) {
      onRefresh();
    }
  };

  const getContentTypeBadgeColor = (type: string) => {
    const colors: Record<string, string> = {
      product: 'bg-blue-100 text-blue-800',
      dealer: 'bg-green-100 text-green-800',
      faq: 'bg-purple-100 text-purple-800',
      office: 'bg-yellow-100 text-yellow-800',
      category: 'bg-pink-100 text-pink-800',
      guide: 'bg-indigo-100 text-indigo-800',
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  const formatDate = (dateString: string) => {
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateString;
    }
  };

  if (loading) {
    return (
      <div className="bg-white shadow rounded-lg p-8">
        <div className="flex items-center justify-center">
          <ArrowPathIcon className="h-6 w-6 text-gray-400 animate-spin mr-2" />
          <span className="text-gray-600">Loading documents...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-red-800">Error loading documents</h3>
            <p className="mt-1 text-sm text-red-700">{error}</p>
            <button
              onClick={handleRefresh}
              className="mt-2 text-sm font-medium text-red-800 hover:text-red-900"
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="bg-white shadow rounded-lg p-8 text-center">
        <DocumentTextIcon className="mx-auto h-12 w-12 text-gray-400" />
        <h3 className="mt-2 text-sm font-medium text-gray-900">No documents found</h3>
        <p className="mt-1 text-sm text-gray-500">
          {contentType 
            ? `No ${contentType} documents uploaded yet.`
            : 'Upload your first document to get started.'
          }
        </p>
        <div className="mt-4 text-xs text-gray-400 bg-gray-50 rounded p-2">
          <p>Brand ID: {brandId}</p>
          {contentType && <p>Content Type: {contentType}</p>}
          <p className="mt-1 italic">Check browser console for API logs</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-5 sm:px-6 border-b border-gray-200 flex justify-between items-center">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Uploaded Documents</h3>
          <p className="mt-1 text-sm text-gray-500">
            {documents.length} document{documents.length !== 1 ? 's' : ''} in knowledge base
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          <ArrowPathIcon className="h-4 w-4 mr-1.5" />
          Refresh
        </button>
      </div>

      <ul className="divide-y divide-gray-200">
        {documents.map((doc) => (
          <li key={doc.doc_id} className="px-4 py-4 hover:bg-gray-50">
            <div className="flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <DocumentTextIcon className="h-5 w-5 text-gray-400 flex-shrink-0" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {doc.title || doc.doc_id}
                      </p>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getContentTypeBadgeColor(doc.content_type)}`}>
                        {doc.content_type}
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-4 text-xs text-gray-500">
                      {doc.created_at && <span>Uploaded: {formatDate(doc.created_at)}</span>}
                      {doc.item_count && (
                        <span className="font-medium">{doc.item_count} {doc.content_type}s</span>
                      )}
                      {doc.chunks_count && (
                        <span>{doc.chunks_count} chunks</span>
                      )}
                    </div>

                    {/* No metadata preview needed since we're showing uploads, not individual items */}
                  </div>
                </div>
              </div>

              <div className="ml-4 flex-shrink-0">
                <button
                  onClick={() => handleDelete(doc.doc_id, doc.title || doc.doc_id)}
                  disabled={deletingDocId === doc.doc_id}
                  className="inline-flex items-center px-3 py-1.5 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-white hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {deletingDocId === doc.doc_id ? (
                    <>
                      <ArrowPathIcon className="h-4 w-4 mr-1.5 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    <>
                      <TrashIcon className="h-4 w-4 mr-1.5" />
                      Delete
                    </>
                  )}
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
