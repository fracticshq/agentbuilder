import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api, Agent, Brand } from '../api/client';
import DocumentUploadWizard from '../components/KnowledgeBase/DocumentUploadWizard';
import KnowledgeExplorer from '../components/KnowledgeBase/KnowledgeExplorer';
import type { KnowledgeFolderSelection, UploadDocumentResponse } from '../types/knowledge';

export default function KnowledgeBase() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [showWizard, setShowWizard] = useState(false);
  const [selectedUploadFolder, setSelectedUploadFolder] = useState<KnowledgeFolderSelection>({
    id: null,
    path: '/',
    name: 'Knowledge Base',
  });
  const [refreshKey, setRefreshKey] = useState(0);

  const requestedAgentId = searchParams.get('agent_id') || undefined;
  const requestedBrandId = searchParams.get('brand_id') || undefined;

  const { data: brands = [], isLoading: brandsLoading } = useQuery<Brand[]>({
    queryKey: ['brands'],
    queryFn: api.getBrands,
  });
  const { data: agent } = useQuery<Agent>({
    queryKey: ['agent', requestedAgentId],
    queryFn: () => api.getAgent(requestedAgentId!),
    enabled: Boolean(requestedAgentId),
  });

  const brandId = agent?.brand_id || requestedBrandId || brands[0]?.id || '';
  const brand = brands.find(item => item.id === brandId);

  const handleUpload = (folder: KnowledgeFolderSelection) => {
    setSelectedUploadFolder(folder);
    setShowWizard(true);
  };

  const handleUploadComplete = (_response: UploadDocumentResponse) => {
    setShowWizard(false);
    setRefreshKey(prev => prev + 1);
  };

  if (showWizard) {
    return (
      <div className="max-w-6xl">
        <DocumentUploadWizard
          brandId={brandId}
          agentId={requestedAgentId}
          selectedFolder={selectedUploadFolder}
          onComplete={handleUploadComplete}
          onCancel={() => setShowWizard(false)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-950">Knowledge Scope</p>
          <p className="mt-1 text-xs leading-5 text-gray-500">
            Knowledge is stored at workspace/brand level and can be filtered or attached to a specific agent.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={brandId}
            disabled={brandsLoading || Boolean(requestedAgentId)}
            onChange={(event) => {
              const next = new URLSearchParams(searchParams);
              next.set('brand_id', event.target.value);
              next.delete('agent_id');
              setSearchParams(next);
            }}
            className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500 disabled:bg-gray-50 disabled:text-gray-500"
          >
            {brands.length === 0 ? (
              <option value="">No brand selected</option>
            ) : brands.map(item => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
          {requestedAgentId && (
            <span className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
              Agent: {agent?.name || requestedAgentId}
            </span>
          )}
        </div>
      </div>

      {brandId ? (
        <KnowledgeExplorer
          key={`${brandId}-${requestedAgentId || 'workspace'}-${refreshKey}`}
          brandId={brandId}
          brandName={brand?.name}
          agentId={requestedAgentId}
          agentName={agent?.name}
          mode={requestedAgentId ? 'agent' : 'workspace'}
          onUpload={handleUpload}
        />
      ) : (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center text-sm text-gray-500">
          Create or select a brand before managing knowledge.
        </div>
      )}
    </div>
  );
}
