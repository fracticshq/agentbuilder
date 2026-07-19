import React, { useEffect, useRef, useState } from 'react';
import { catalogApi } from '../../../api/catalog';
import SyncSettingsModal from '../SyncSettingsModal';

interface ShopifyTabProps {
  brandId: string;
  onBack: () => void;
}

export default function ShopifyTab({ brandId, onBack }: ShopifyTabProps) {
  const [storeUrl, setStoreUrl] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [fallbackCurrency, setFallbackCurrency] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [totalItems, setTotalItems] = useState(0);
  const [syncCounts, setSyncCounts] = useState<{ products_upserted?: number; products_marked_inactive?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleFetch = async () => {
    if (!storeUrl.trim()) return;
    setStatus('loading');
    setError(null);
    setSyncCounts(null);
    setProgress(0);
    setTotalItems(0);
    try {
      const { job_id } = await catalogApi.importShopify(
        storeUrl.trim(),
        brandId,
        accessToken.trim() || undefined,
        fallbackCurrency.trim() || undefined,
      );
      pollRef.current = setInterval(async () => {
        try {
          const job = await catalogApi.getJob(job_id, brandId);
          setProgress(job.processed || 0);
          setTotalItems(job.total || 0);
          if (job.status === 'completed') {
            clearInterval(pollRef.current!);
            setSyncCounts(job.counts || null);
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
            Use an authenticated Admin API token for production catalog sync. This tab remains available for one-off imports.
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

      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_120px]">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Admin API token</label>
          <input
            type="password"
            value={accessToken}
            onChange={e => setAccessToken(e.target.value)}
            placeholder="shpat_..."
            disabled={status === 'loading'}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Fallback currency</label>
          <input
            value={fallbackCurrency}
            onChange={e => setFallbackCurrency(e.target.value.toUpperCase())}
            placeholder="INR"
            maxLength={3}
            disabled={status === 'loading'}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm uppercase focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
          />
        </div>
      </div>

      <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
        {accessToken.trim() ? 'The token is sent only to the encrypted sync configuration and is never returned in the dashboard.' : 'A saved Admin API token is required. Open Sync Settings to save one before starting a production catalog sync.'}
      </p>

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
            Catalog sync complete for {storeUrl}
          </p>
          <p className="text-xs text-green-700 mt-1">
            {syncCounts?.products_upserted ?? 0} product variants updated and {syncCounts?.products_marked_inactive ?? 0} stale variants deactivated. Products are already indexed; no field mapping or second import is needed.
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
            onClick={onBack}
            className="px-6 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
          >
            Back to upload methods
          </button>
        )}
      </div>

      {showSyncModal && (
        <SyncSettingsModal
          brandId={brandId}
          sourceType="shopify"
          sourceUrl={storeUrl}
          onClose={() => setShowSyncModal(false)}
        />
      )}
    </div>
  );
}
