import React, { useState, useEffect } from 'react';
import { PlusIcon } from '@heroicons/react/24/outline';
import DocumentUploadWizard from '../KnowledgeBase/DocumentUploadWizard';
import DocumentsList from '../KnowledgeBase/DocumentsList';
import { knowledgeApi } from '../../api/knowledge';

const isDev = process.env.NODE_ENV !== 'production';

interface StepKnowledgeBaseProps {
  data: {
    documents: Array<{
      id: string;
      filename: string;
      size: number;
      type: string;
      status: 'uploading' | 'processing' | 'ready' | 'error';
      file?: File;
    }>;
    chunking_strategy: string;
    chunk_size: number;
    chunk_overlap: number;
  };
  onChange: (field: string, value: any) => void;
  agentId?: string;
  brandId?: string;
}

export default function StepKnowledgeBase({ data, onChange, agentId, brandId }: StepKnowledgeBaseProps) {
  const [showWizard, setShowWizard] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [resolvedBrandId, setResolvedBrandId] = useState<string | null>(null);

  // Resolve brand slug from agent ID if needed
  useEffect(() => {
    const resolveBrand = async () => {
      // If we have an agentId, ALWAYS resolve through API (don't trust brandId prop)
      if (agentId) {
        try {
          const clientModule = await import('../../api/client');
          const resp = await clientModule.agentApi.get(agentId);
          const agent = resp.data as any;
          // Always use brand_id (UUID) for consistency — storage key must not change between create and edit
          const slug = (agent && (agent.brand_id || agent.brand_slug)) || null;
          isDev && console.log('[StepKnowledgeBase] Resolved agent to brand:', { agentId, brandSlug: slug });
          setResolvedBrandId(slug);
        } catch (err) {
          console.warn('[StepKnowledgeBase] Failed to resolve agent -> brand', err);
          setResolvedBrandId(brandId || null); // fallback to brandId
        }
      } else if (brandId) {
        // No agentId, just use brandId directly
        isDev && console.log('[StepKnowledgeBase] Using brandId directly:', brandId);
        setResolvedBrandId(brandId);
      }
    };

    resolveBrand();
  }, [brandId, agentId]);

  // Fetch documents count to update validation (depends on resolvedBrandId)
  useEffect(() => {
    const fetchDocumentsCount = async () => {
      // Wait for resolvedBrandId to be set
      if (!resolvedBrandId) {
        isDev && console.log('[StepKnowledgeBase] Waiting for brand resolution...');
        return;
      }

      try {
        isDev && console.log('[StepKnowledgeBase] Fetching documents for brand:', resolvedBrandId);
        const docs = await knowledgeApi.getDocuments(resolvedBrandId);
        isDev && console.log('[StepKnowledgeBase] Fetched documents:', docs.length);
        // Update the data with fetched documents for validation
        onChange('documents', docs.map(doc => ({
          id: doc.doc_id,
          filename: doc.title || doc.doc_id,
          size: doc.chunks_count || 0,
          type: doc.content_type,
          status: 'ready' as const
        })));
      } catch (error) {
        console.error('[StepKnowledgeBase] Failed to fetch documents:', error);
        // Set empty array on error to avoid validation issues
        onChange('documents', []);
      }
    };

    fetchDocumentsCount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedBrandId, refreshKey]); // Fetch when resolvedBrandId changes

  const handleUploadComplete = () => {
    setShowWizard(false);
    setRefreshKey(prev => prev + 1); // Trigger documents list refresh and re-fetch count
  };

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1);
  };

  if (showWizard) {
    // Wait for brand resolution before showing wizard
    if (!resolvedBrandId) {
      return (
        <div className="max-w-6xl">
          <div className="bg-white shadow rounded-lg p-8">
            <div className="flex items-center justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              <span className="ml-3 text-gray-600">Preparing upload...</span>
            </div>
          </div>
        </div>
      );
    }
    
    return (
      <div className="max-w-6xl">
        <DocumentUploadWizard
          brandId={resolvedBrandId}
          onComplete={handleUploadComplete}
          onCancel={() => setShowWizard(false)}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Knowledge Base</h2>
        <p className="mt-2 text-sm text-gray-600">
          Upload documents with structured metadata to prevent AI hallucinations
        </p>
      </div>

      <div className="mb-6">
        <button
          onClick={() => setShowWizard(true)}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700"
        >
          <PlusIcon className="h-5 w-5 mr-2" />
          Upload Document with Structured Metadata
        </button>
      </div>

      {/* Documents List - only show after brand resolution */}
      {resolvedBrandId ? (
        <DocumentsList 
          brandId={resolvedBrandId}
          onRefresh={handleRefresh}
          key={refreshKey}
        />
      ) : (
        <div className="bg-white shadow rounded-lg p-8">
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            <span className="ml-3 text-gray-600">Loading documents...</span>
          </div>
        </div>
      )}
    </div>
  );
}
