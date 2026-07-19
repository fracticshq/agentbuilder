import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowPathIcon,
  CheckCircleIcon,
  CircleStackIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
  FolderIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from '@heroicons/react/24/outline';
import DocumentUploadWizard from '../KnowledgeBase/DocumentUploadWizard';
import { agentApi, brandApi } from '../../api/client';
import { knowledgeApi } from '../../api/knowledge';
import type {
  DocumentPreview,
  DocumentPreviewSample,
  DocumentSummary,
  UploadDocumentResponse,
  UploadJobStatus,
} from '../../types/knowledge';

const isDev = import.meta.env.DEV;

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

const typeLabels: Record<string, string> = {
  product: 'Products',
  dealer: 'Dealers',
  faq: 'FAQ',
  guide: 'Docs',
  office: 'Office',
  category: 'Categories',
};

function normalizeType(type?: string): string {
  return type || 'document';
}

function labelForType(type?: string): string {
  const normalized = normalizeType(type);
  return typeLabels[normalized] || normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function formatDate(value?: string): string {
  if (!value) return 'Unknown';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function mergeDocuments(documents: DocumentSummary[]): DocumentSummary[] {
  const byId = new Map<string, DocumentSummary>();
  documents.forEach((doc) => {
    const existing = byId.get(doc.doc_id);
    if (!existing || (doc.chunks_count || 0) > (existing.chunks_count || 0)) {
      byId.set(doc.doc_id, { ...doc, status: doc.status || 'ready' });
    }
  });

  return Array.from(byId.values()).sort((a, b) =>
    String(b.created_at || '').localeCompare(String(a.created_at || ''))
  );
}

function mapDocumentsForWizard(docs: DocumentSummary[]) {
  return docs.map(doc => ({
    id: doc.doc_id,
    filename: doc.title || doc.doc_id,
    size: doc.chunks_count || 0,
    type: doc.content_type,
    status: 'ready' as const,
  }));
}

function StatTile({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-3">
      <div className={`mb-1 h-1 w-8 rounded-full ${tone}`} />
      <p className="text-2xl font-semibold text-gray-900">{value}</p>
      <p className="text-xs font-medium text-gray-500">{label}</p>
    </div>
  );
}

function SourceSample({ sample }: { sample: DocumentPreviewSample }) {
  if (sample.product_data) {
    const product = sample.product_data;
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-gray-900">{product.name}</p>
            <p className="mt-1 text-xs text-gray-500">SKU: {product.sku}</p>
          </div>
          <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
            {product.category}
          </span>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-gray-500">Price</dt>
            <dd className="font-medium text-gray-900">{product.price} {product.currency}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">Stock</dt>
            <dd className="font-medium text-gray-900">{product.in_stock ? 'In stock' : 'Out of stock'}</dd>
          </div>
        </dl>
        {product.features?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {product.features.slice(0, 6).map((feature) => (
              <span key={feature} className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600">
                {feature}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (sample.dealer_data) {
    const dealer = sample.dealer_data;
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="text-sm font-semibold text-gray-900">{dealer.name}</p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-gray-500">Dealer ID</dt>
            <dd className="font-medium text-gray-900">{dealer.dealer_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">City</dt>
            <dd className="font-medium text-gray-900">{dealer.city}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">Phone</dt>
            <dd className="font-medium text-gray-900">{dealer.phone}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">State</dt>
            <dd className="font-medium text-gray-900">{dealer.state || 'Unknown'}</dd>
          </div>
        </dl>
        {dealer.address && <p className="mt-3 text-sm text-gray-600">{dealer.address}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="mb-2 text-sm font-semibold text-gray-900">{sample.title || sample.chunk_id || 'Sample chunk'}</p>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-gray-950 p-3 text-xs leading-5 text-gray-100">
        {sample.content || 'No content preview available.'}
      </pre>
    </div>
  );
}

export default function StepKnowledgeBase({ data, onChange, agentId, brandId }: StepKnowledgeBaseProps) {
  const [showWizard, setShowWizard] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [resolvedBrandId, setResolvedBrandId] = useState<string | null>(null);
  const [brandAliases, setBrandAliases] = useState<string[]>([]);
  const [uploadJob, setUploadJob] = useState<UploadJobStatus | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    const resolveBrand = async () => {
      if (agentId) {
        try {
          const resp = await agentApi.get(agentId);
          const agent = resp.data as any;
          const aliases = [agent?.brand_slug, agent?.brand_id, brandId].filter(Boolean) as string[];
          let primaryBrand = agent?.brand_slug || agent?.brand_id || brandId || null;

          if (agent?.brand_id) {
            try {
              const brandResp = await brandApi.get(agent.brand_id);
              if (brandResp.data?.slug) {
                primaryBrand = brandResp.data.slug;
                aliases.unshift(brandResp.data.slug);
              }
              if (brandResp.data?.id) {
                aliases.push(brandResp.data.id);
              }
            } catch (brandErr) {
              isDev && console.warn('[StepKnowledgeBase] Brand lookup fallback:', brandErr);
            }
          }

          const uniqueAliases = Array.from(new Set(aliases));
          setResolvedBrandId(primaryBrand);
          setBrandAliases(uniqueAliases);
        } catch (err) {
          console.warn('[StepKnowledgeBase] Failed to resolve agent -> brand', err);
          setResolvedBrandId(brandId || null);
          setBrandAliases(brandId ? [brandId] : []);
        }
      } else if (brandId) {
        try {
          const brandResp = await brandApi.get(brandId);
          const primaryBrand = brandResp.data?.slug || brandId;
          setResolvedBrandId(primaryBrand);
          setBrandAliases(Array.from(new Set([primaryBrand, brandResp.data?.id, brandId].filter(Boolean) as string[])));
        } catch {
          setResolvedBrandId(brandId);
          setBrandAliases([brandId]);
        }
      }
    };

    resolveBrand();
  }, [brandId, agentId]);

  useEffect(() => {
    const fetchDocuments = async () => {
      if (!resolvedBrandId) return;

      try {
        setDocumentsLoading(true);
        setDocumentsError(null);
        const lookupIds = brandAliases.length > 0 ? brandAliases : [resolvedBrandId];
        const results = await Promise.allSettled(lookupIds.map(id => knowledgeApi.getDocuments(id)));
        const docs = mergeDocuments(results.flatMap(result => result.status === 'fulfilled' ? result.value : []));
        setDocuments(docs);
        onChange('documents', mapDocumentsForWizard(docs));
      } catch (error: any) {
        console.error('[StepKnowledgeBase] Failed to fetch documents:', error);
        setDocuments([]);
        onChange('documents', []);
        setDocumentsError(error?.message || 'Failed to load documents');
      } finally {
        setDocumentsLoading(false);
      }
    };

    fetchDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedBrandId, brandAliases.join('|'), refreshKey]);

  useEffect(() => {
    if (!documents.length) {
      setSelectedDocId(null);
      return;
    }
    if (!selectedDocId || !documents.some(doc => doc.doc_id === selectedDocId)) {
      setSelectedDocId(documents[0].doc_id);
    }
  }, [documents, selectedDocId]);

  useEffect(() => {
    if (!uploadJob?.job_id || uploadJob.status === 'completed' || uploadJob.status === 'error') {
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        const nextStatus = await knowledgeApi.getJobStatus(uploadJob.job_id);
        if (cancelled) return;

        setUploadJob(nextStatus);
        if (nextStatus.status === 'completed') {
          setRefreshKey(prev => prev + 1);
        }
      } catch (error: any) {
        if (cancelled) return;
        setUploadJob(prev => prev ? {
          ...prev,
          status: 'error',
          error: error?.message || 'Failed to check upload status',
        } : prev);
      }
    }, 1500);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [uploadJob]);

  useEffect(() => {
    const fetchPreview = async () => {
      if (!selectedDocId || !resolvedBrandId) {
        setPreview(null);
        return;
      }

      try {
        setPreviewLoading(true);
        setPreviewError(null);
        const nextPreview = await knowledgeApi.getDocumentPreview(selectedDocId, resolvedBrandId);
        setPreview(nextPreview);
      } catch (error: any) {
        setPreview(null);
        setPreviewError(error?.message || 'Failed to load preview');
      } finally {
        setPreviewLoading(false);
      }
    };

    fetchPreview();
  }, [selectedDocId, resolvedBrandId]);

  const handleUploadComplete = (response: UploadDocumentResponse) => {
    setShowWizard(false);
    setUploadJob({
      job_id: response.job_id,
      status: response.status === 'completed' ? 'completed' : 'processing',
      progress: {
        type: 'bulk',
        processed_items: 0,
        total_items: response.items_count,
        processed_chunks: 0,
        total_chunks: 0,
      },
    });

    if (response.status === 'completed') {
      setRefreshKey(prev => prev + 1);
    }
  };

  const filteredDocuments = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return documents;
    return documents.filter(doc => {
      const haystack = `${doc.title || ''} ${doc.doc_id} ${doc.content_type || ''}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [documents, searchQuery]);

  const groupedDocuments = useMemo(() => {
    return filteredDocuments.reduce<Record<string, DocumentSummary[]>>((groups, doc) => {
      const type = normalizeType(doc.content_type);
      groups[type] = groups[type] || [];
      groups[type].push(doc);
      return groups;
    }, {});
  }, [filteredDocuments]);

  const stats = useMemo(() => {
    const products = documents.filter(doc => doc.content_type === 'product').length;
    const dealers = documents.filter(doc => doc.content_type === 'dealer').length;
    const faq = documents.filter(doc => doc.content_type === 'faq').length;
    const docs = documents.filter(doc => !['product', 'dealer', 'faq'].includes(doc.content_type || '')).length;
    return { products, dealers, faq, docs };
  }, [documents]);

  const selectedDocument = documents.find(doc => doc.doc_id === selectedDocId) || null;

  if (showWizard) {
    if (!resolvedBrandId) {
      return (
        <div className="rounded-lg border border-gray-200 bg-white p-8">
          <div className="flex items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-600" />
            <span className="ml-3 text-gray-600">Preparing upload...</span>
          </div>
        </div>
      );
    }

    return (
      <div className="max-w-6xl">
        <DocumentUploadWizard
          brandId={resolvedBrandId}
          agentId={agentId}
          onComplete={handleUploadComplete}
          onCancel={() => setShowWizard(false)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Knowledge</h2>
          <p className="mt-1 text-sm text-gray-600">
            Verify the knowledge/ workspace: uploaded sources, records, and chunks before moving to review.
          </p>
        </div>
        <button
          onClick={() => {
            setUploadJob(null);
            setShowWizard(true);
          }}
          className="inline-flex items-center justify-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          <PlusIcon className="mr-2 h-5 w-5" />
          Upload Data
        </button>
      </div>

      {uploadJob && (
        <div className={`rounded-lg border p-4 ${
          uploadJob.status === 'error'
            ? 'border-red-200 bg-red-50'
            : uploadJob.status === 'completed'
              ? 'border-green-200 bg-green-50'
              : 'border-blue-200 bg-blue-50'
        }`}>
          <div className="flex items-start gap-3">
            {uploadJob.status === 'error' ? (
              <ExclamationTriangleIcon className="mt-0.5 h-5 w-5 text-red-600" />
            ) : uploadJob.status === 'completed' ? (
              <CheckCircleIcon className="mt-0.5 h-5 w-5 text-green-600" />
            ) : (
              <div className="mt-0.5 h-5 w-5 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
            )}
            <div>
              <p className={`text-sm font-medium ${
                uploadJob.status === 'error'
                  ? 'text-red-900'
                  : uploadJob.status === 'completed'
                    ? 'text-green-900'
                    : 'text-blue-900'
              }`}>
                {uploadJob.status === 'completed'
                  ? 'Upload completed'
                  : uploadJob.status === 'error'
                    ? 'Upload failed'
                    : 'Processing upload'}
              </p>
              <p className={`mt-1 text-sm ${
                uploadJob.status === 'error'
                  ? 'text-red-700'
                  : uploadJob.status === 'completed'
                    ? 'text-green-700'
                    : 'text-blue-700'
              }`}>
                {uploadJob.status === 'error'
                  ? uploadJob.error || 'The upload job failed.'
                  : uploadJob.status === 'completed'
                    ? 'The workspace has been refreshed.'
                    : `${uploadJob.progress.processed_items || 0}/${uploadJob.progress.total_items || 0} items processed, ${uploadJob.progress.processed_chunks || 0} chunks embedded.`}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="grid min-h-[680px] grid-cols-1 lg:grid-cols-[320px_1fr]">
          <aside className="border-b border-gray-200 bg-gray-50 lg:border-b-0 lg:border-r">
            <div className="space-y-4 p-4">
              <div className="relative">
                <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-2.5 h-5 w-5 text-gray-400" />
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Search sources..."
                  className="w-full rounded-md border border-gray-300 bg-white py-2 pl-10 pr-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <StatTile label="Products" value={stats.products} tone="bg-blue-500" />
                <StatTile label="Dealers" value={stats.dealers} tone="bg-emerald-500" />
                <StatTile label="FAQ" value={stats.faq} tone="bg-violet-500" />
                <StatTile label="Docs" value={stats.docs} tone="bg-amber-500" />
              </div>

              <div className="space-y-3">
                {documentsLoading ? (
                  <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-8">
                    <ArrowPathIcon className="mr-2 h-5 w-5 animate-spin text-gray-400" />
                    <span className="text-sm text-gray-600">Loading sources...</span>
                  </div>
                ) : documentsError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                    {documentsError}
                  </div>
                ) : filteredDocuments.length === 0 ? (
                  <div className="rounded-lg border border-gray-200 bg-white p-6 text-center">
                    <DocumentTextIcon className="mx-auto h-10 w-10 text-gray-300" />
                    <p className="mt-2 text-sm font-medium text-gray-900">No sources found</p>
                    <p className="mt-1 text-xs text-gray-500">
                      Upload data or adjust your search.
                    </p>
                  </div>
                ) : (
                  Object.entries(groupedDocuments).map(([type, docs]) => (
                    <div key={type}>
                      <div className="mb-1 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                        <FolderIcon className="h-4 w-4 text-gray-400" />
                        {labelForType(type)}
                        <span className="ml-auto rounded-full bg-gray-200 px-2 py-0.5 text-gray-600">{docs.length}</span>
                      </div>
                      <div className="space-y-1">
                        {docs.map((doc) => {
                          const selected = doc.doc_id === selectedDocId;
                          return (
                            <button
                              key={doc.doc_id}
                              type="button"
                              onClick={() => setSelectedDocId(doc.doc_id)}
                              className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                                selected
                                  ? 'border-primary-200 bg-primary-50'
                                  : 'border-transparent bg-white hover:border-gray-200 hover:bg-gray-100'
                              }`}
                            >
                              <div className="flex items-start gap-2">
                                <DocumentTextIcon className={`mt-0.5 h-5 w-5 ${selected ? 'text-primary-600' : 'text-gray-400'}`} />
                                <div className="min-w-0 flex-1">
                                  <p className="truncate text-sm font-medium text-gray-900">{doc.title || doc.doc_id}</p>
                                  <p className="mt-0.5 text-xs text-gray-500">
                                    {doc.item_count || 0} items · {doc.chunks_count || 0} chunks
                                  </p>
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </aside>

          <main className="bg-white">
            {!selectedDocument ? (
              <div className="flex h-full min-h-[480px] items-center justify-center p-8 text-center">
                <div>
                  <CircleStackIcon className="mx-auto h-12 w-12 text-gray-300" />
                  <p className="mt-3 text-sm font-medium text-gray-900">No source selected</p>
                  <p className="mt-1 text-sm text-gray-500">Select a source from the sidebar to preview it.</p>
                </div>
              </div>
            ) : (
              <div className="flex h-full flex-col">
                <div className="border-b border-gray-200 px-6 py-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                          {labelForType(selectedDocument.content_type)}
                        </span>
                        <span className="rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700">
                          {selectedDocument.status || 'ready'}
                        </span>
                      </div>
                      <h3 className="text-lg font-semibold text-gray-900">{selectedDocument.title || selectedDocument.doc_id}</h3>
                      <p className="mt-1 text-xs font-mono text-gray-500">{selectedDocument.doc_id}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setRefreshKey(prev => prev + 1)}
                      className="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <ArrowPathIcon className="mr-2 h-4 w-4" />
                      Refresh
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 border-b border-gray-200 px-6 py-4 md:grid-cols-4">
                  <div>
                    <p className="text-xs font-medium text-gray-500">Content Type</p>
                    <p className="mt-1 text-sm font-semibold text-gray-900">{labelForType(selectedDocument.content_type)}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-gray-500">Items</p>
                    <p className="mt-1 text-sm font-semibold text-gray-900">{preview?.item_count ?? selectedDocument.item_count ?? 0}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-gray-500">Chunks</p>
                    <p className="mt-1 text-sm font-semibold text-gray-900">{preview?.chunks_count ?? selectedDocument.chunks_count ?? 0}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-gray-500">Uploaded</p>
                    <p className="mt-1 text-sm font-semibold text-gray-900">{formatDate(preview?.created_at || selectedDocument.created_at)}</p>
                  </div>
                </div>

                <div className="flex-1 overflow-auto bg-gray-50 p-6">
                  {previewLoading ? (
                    <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-10">
                      <ArrowPathIcon className="mr-2 h-5 w-5 animate-spin text-gray-400" />
                      <span className="text-sm text-gray-600">Loading preview...</span>
                    </div>
                  ) : previewError ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                      {previewError}
                    </div>
                  ) : preview?.samples?.length ? (
                    <div>
                      <div className="mb-3 flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-gray-900">Sample Records</h4>
                        <span className="text-xs text-gray-500">{preview.samples.length} shown</span>
                      </div>
                      <div className="space-y-3">
                        {preview.samples.map((sample, index) => (
                          <SourceSample key={sample.chunk_id || index} sample={sample} />
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-gray-200 bg-white p-10 text-center">
                      <DocumentTextIcon className="mx-auto h-10 w-10 text-gray-300" />
                      <p className="mt-2 text-sm font-medium text-gray-900">No preview available</p>
                      <p className="mt-1 text-sm text-gray-500">The source exists, but no sample chunks were returned.</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
