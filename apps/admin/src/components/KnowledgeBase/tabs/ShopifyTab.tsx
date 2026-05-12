import React, { useEffect, useRef, useState } from 'react';
import { catalogApi } from '../../../api/catalog';
import SyncSettingsModal from '../SyncSettingsModal';

interface ShopifyTabProps {
  brandId: string;
  onUpload: (data: any[]) => void;
  onBack: () => void;
}

export default function ShopifyTab({ brandId, onUpload, onBack }: ShopifyTabProps) {
  const [storeUrl, setStoreUrl] = useState('');
  const [showTokenField, setShowTokenField] = useState(false);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [totalItems, setTotalItems] = useState(0);
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleFetch = async () => {
    if (!storeUrl.trim()) return;
    setStatus('loading');
    setError(null);
    setItems([]);
    setProgress(0);
    setTotalItems(0);
    try {
      const { job_id } = await catalogApi.importShopify(
        storeUrl.trim(),
        brandId,
        clientId.trim() || undefined,
        clientSecret.trim() || undefined
      );
      pollRef.current = setInterval(async () => {
        try {
          const job = await catalogApi.getJob(job_id);
          setProgress(job.processed || 0);
          setTotalItems(job.total || 0);
          if (job.status === 'completed') {
            clearInterval(pollRef.current!);
            setItems(job.items || []);
            setStatus('done');
          } else if (job.status === 'error') {
            clearInterval(pollRef.current!);
            setError(job.error || 'Fetch failed');
            setStatus('error');
          }
        } catch {
          clearInterval(pollRef.current!);
          setError('Lost connection while fetching. Please try again.');
          setStatus('error');
        }
      }, 2000);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to start import');
      setStatus('error');
    }
  };

  return (
    <div className="space-y-5">
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Sync from Shopify</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Fetches all products via <code className="bg-gray-100 px-1 rounded">/products.json</code>. No API key needed for public stores.
          </p>
        </div>
        {status === 'done' && (
          <button
            onClick={() => setShowSyncModal(true)}
            className="text-xs text-primary-600 hover:text-primary-800 font-medium flex items-center gap-1"
          >
            ⚙️ Sync Settings
          </button>
        )}
      </div>

      {/* Store URL */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Store URL <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={storeUrl}
          onChange={e => setStoreUrl(e.target.value)}
          placeholder="mystore.myshopify.com"
          disabled={status === 'loading'}
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
        />
      </div>

      {/* Private store toggle */}
      <div>
        <button
          type="button"
          onClick={() => setShowTokenField(v => !v)}
          className="text-sm text-primary-600 hover:text-primary-800 font-medium"
        >
          {showTokenField ? '▾' : '▸'} My store is private / password-protected
        </button>
        {showTokenField && (
          <div className="mt-3 space-y-4">
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">
                Shopify Client ID
              </label>
              <input
                type="password"
                value={clientId}
                onChange={e => setClientId(e.target.value)}
                placeholder="Shopify API Key"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">
                Shopify Client Secret
              </label>
              <input
                type="password"
                value={clientSecret}
                onChange={e => setClientSecret(e.target.value)}
                placeholder="Shopify Shared Secret"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <p className="text-xs text-gray-500">
              Find these in Shopify Partner Dashboard.
            </p>
          </div>
        )}
      </div>

      {/* Progress */}
      {status === 'loading' && (
        <div className="rounded-md bg-blue-50 border border-blue-200 p-4">
          <div className="flex items-center gap-3">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
            <span className="text-sm text-blue-800">
              {totalItems > 0 ? `Fetched ${progress} products…` : 'Connecting to store…'}
            </span>
          </div>
          {totalItems > 0 && (
            <div className="mt-2 h-1.5 rounded-full bg-blue-200">
              <div
                className="h-1.5 rounded-full bg-primary-600 transition-all duration-300"
                style={{ width: `${Math.min((progress / Math.max(totalItems, 1)) * 100, 99)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {status === 'error' && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-sm text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Done */}
      {status === 'done' && (
        <div className="rounded-md bg-green-50 border border-green-200 p-4">
          <p className="text-sm text-green-800 font-medium">
            ✅ {items.length} products fetched from {storeUrl}
          </p>
          <p className="text-xs text-green-700 mt-1">
            Review and map fields in the next step.
          </p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-4 border-t border-gray-200">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          ← Back to Content Type
        </button>
        {status !== 'done' ? (
          <button
            onClick={handleFetch}
            disabled={!storeUrl.trim() || status === 'loading'}
            className="px-6 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {status === 'loading' ? 'Fetching…' : 'Fetch Products'}
          </button>
        ) : (
          <button
            onClick={() => onUpload(items)}
            className="px-6 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
          >
            Next: Map Fields →
          </button>
        )}
      </div>

      {showSyncModal && (
        <SyncSettingsModal
          brandId={brandId}
          sourceType="shopify"
          sourceUrl={storeUrl}
          clientId={clientId || undefined}
          clientSecret={clientSecret || undefined}
          onClose={() => setShowSyncModal(false)}
        />
      )}
    </div>
  );
}
