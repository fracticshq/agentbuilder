import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  KeyIcon,
  LockClosedIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline';
import { catalogApi } from '../../api/catalog';
import type { CatalogSyncConfig, CatalogSyncJob } from '../../api/catalog';

interface SyncSettingsModalProps {
  brandId: string;
  sourceType?: string;
  sourceUrl?: string;
  accessToken?: string;
  onClose: () => void;
  onChanged?: (config: CatalogSyncConfig) => void;
}

function getErrorMessage(error: any, fallback: string): string {
  return error?.response?.data?.detail || error?.message || fallback;
}

export default function SyncSettingsModal({
  brandId,
  sourceType = 'shopify',
  sourceUrl = '',
  accessToken = '',
  onClose,
  onChanged,
}: SyncSettingsModalProps) {
  const [storeUrl, setStoreUrl] = useState(sourceUrl);
  const [token, setToken] = useState(accessToken);
  const [fallbackCurrency, setFallbackCurrency] = useState('');
  const [autoSync, setAutoSync] = useState(false);
  const [frequency, setFrequency] = useState('manual');
  const [config, setConfig] = useState<CatalogSyncConfig | null>(null);
  const [job, setJob] = useState<CatalogSyncJob | null>(null);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    catalogApi.getSyncConfig(brandId).then((next) => {
      if (cancelled) return;
      setConfig(next);
      setStoreUrl(next.source_url || sourceUrl);
      setFallbackCurrency(next.fallback_currency || '');
      setAutoSync(Boolean(next.auto_sync));
      setFrequency(next.sync_frequency || 'manual');
    }).catch((loadError) => {
      if (!cancelled) setError(getErrorMessage(loadError, 'Failed to load Shopify sync settings.'));
    });
    return () => { cancelled = true; };
  }, [brandId, sourceUrl]);

  useEffect(() => {
    if (!job?.job_id || job.status === 'completed' || job.status === 'error') return;
    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      try {
        const next = await catalogApi.getJob(job.job_id, brandId);
        if (!cancelled) setJob(next);
      } catch (pollError) {
        if (!cancelled) setError(getErrorMessage(pollError, 'Failed to check sync status.'));
      }
    }, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [brandId, job]);

  useEffect(() => {
    if (!job || job.status === 'processing') return;
    if (job.status === 'completed') {
      setNotice(`Sync complete: ${job.counts?.products_upserted ?? 0} products updated.`);
      catalogApi.getSyncConfig(brandId).then((next) => {
        setConfig(next);
        onChanged?.(next);
      }).catch(() => undefined);
    } else if (job.status === 'error') {
      setError(job.error || 'Shopify sync failed.');
    }
  }, [brandId, job, onChanged]);

  const status = job?.status || config?.last_sync_status || 'idle';
  const syncInFlight = ['queued', 'running', 'processing'].includes(status);
  const counts = job?.counts || config?.last_sync_counts;
  const progress = useMemo(() => {
    const processed = job?.processed || 0;
    const total = job?.total || 0;
    return total > 0 ? Math.min((processed / total) * 100, 100) : 0;
  }, [job]);

  const persistConfig = async () => {
    const next = await catalogApi.updateSyncConfig(brandId, {
      source_type: sourceType,
      source_url: storeUrl.trim(),
      ...(token.trim() ? { access_token: token.trim() } : {}),
      fallback_currency: fallbackCurrency.trim() || null,
      auto_sync: autoSync,
      sync_frequency: frequency,
    });
    setConfig(next);
    setToken('');
    onChanged?.(next);
    return next;
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await persistConfig();
      setSaved(true);
      setNotice('Settings saved. The Admin API token is encrypted and will not be shown again.');
      window.setTimeout(() => setSaved(false), 2200);
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Failed to save Shopify sync settings.'));
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    setNotice(null);
    try {
      await persistConfig();
      const nextJob = await catalogApi.startSync(brandId);
      setJob({ job_id: nextJob.job_id, status: nextJob.status, deduplicated: nextJob.deduplicated, results: [] });
      if (nextJob.deduplicated) setNotice('A catalog sync is already running for this brand; following the existing job.');
    } catch (startError) {
      setError(getErrorMessage(startError, 'Failed to start Shopify sync.'));
    } finally {
      setStarting(false);
    }
  };

  const hasToken = Boolean(config?.access_token_configured || token.trim());
  const isProcessing = syncInFlight || starting || saving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 p-4">
      <div className="max-h-[min(760px,calc(100dvh-2rem))] w-full max-w-2xl overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-5">
          <div>
            <div className="flex items-center gap-2">
              <KeyIcon className="h-5 w-5 text-gray-700" />
              <h2 className="text-base font-semibold text-gray-950">Shopify Catalog Sync</h2>
            </div>
            <p className="mt-1 text-sm leading-5 text-gray-500">
              Save the store connection for this brand, then run an authenticated Admin API sync.
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" aria-label="Close sync settings">
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_150px]">
            <label className="block">
              <span className="text-sm font-medium text-gray-800">Shopify store URL</span>
              <input
                value={storeUrl}
                onChange={(event) => setStoreUrl(event.target.value)}
                placeholder="store.myshopify.com"
                disabled={isProcessing}
                className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-600 focus:ring-1 focus:ring-gray-600 disabled:bg-gray-50"
              />
              <span className="mt-1 block text-xs leading-5 text-gray-500">Use the canonical `.myshopify.com` store root only. The API normalizes it to HTTPS and refuses custom domains for token-bound syncs.</span>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-gray-800">Fallback currency</span>
              <input
                value={fallbackCurrency}
                onChange={(event) => setFallbackCurrency(event.target.value.toUpperCase())}
                placeholder="INR"
                maxLength={3}
                disabled={isProcessing}
                className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm uppercase outline-none focus:border-gray-600 focus:ring-1 focus:ring-gray-600 disabled:bg-gray-50"
              />
              <span className="mt-1 block text-xs leading-5 text-gray-500">Only used if Shopify does not return currency.</span>
            </label>
          </div>

          <label className="block">
            <span className="flex items-center gap-2 text-sm font-medium text-gray-800">
              <LockClosedIcon className="h-4 w-4 text-gray-500" />
              Shopify Admin API token
            </span>
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={config?.access_token_configured ? 'Token already configured; enter a replacement' : 'shpat_...'}
              autoComplete="new-password"
              disabled={isProcessing}
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-600 focus:ring-1 focus:ring-gray-600 disabled:bg-gray-50"
            />
            <span className="mt-1 block text-xs leading-5 text-gray-500">
              Stored encrypted. The dashboard only receives a configured/not-configured flag.
            </span>
          </label>

          {!hasToken && (
            <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm leading-5 text-amber-900">
              <ExclamationTriangleIcon className="mt-0.5 h-4 w-4 flex-none" />
              <span>An Admin API token is required before a production catalog sync can run. Save a token with read_products and read_inventory access.</span>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-gray-200 pt-4">
            <div>
              <p className="text-sm font-medium text-gray-800">Scheduled sync metadata</p>
              <p className="text-xs leading-5 text-gray-500">Save the preference for the configured scheduler.</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={autoSync}
              onClick={() => setAutoSync((value) => {
                const next = !value;
                if (next && frequency === 'manual') setFrequency('daily');
                return next;
              })}
              disabled={isProcessing}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoSync ? 'bg-gray-900' : 'bg-gray-200'} disabled:opacity-50`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${autoSync ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
          {autoSync && (
            <label className="block">
              <span className="text-sm font-medium text-gray-800">Frequency</span>
              <select value={frequency} onChange={(event) => setFrequency(event.target.value)} disabled={isProcessing} className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-gray-600 focus:ring-1 focus:ring-gray-600 disabled:bg-gray-50">
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
              </select>
            </label>
          )}

          {(job || config?.last_sync_status) && (
            <div className="border-y border-gray-200 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  {status === 'completed' ? <CheckCircleIcon className="h-5 w-5 text-emerald-600" /> : status === 'error' ? <ExclamationTriangleIcon className="h-5 w-5 text-red-600" /> : <ArrowPathIcon className="h-5 w-5 animate-spin text-gray-600" />}
                  <span className="text-sm font-semibold capitalize text-gray-900">{status}</span>
                </div>
                {job?.processed !== undefined && job.total !== undefined && job.total > 0 && <span className="font-mono text-xs text-gray-500">{job.processed}/{job.total} items</span>}
              </div>
              {syncInFlight && <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-gray-100"><div className="h-full rounded-full bg-gray-900 transition-[width] duration-300" style={{ width: `${progress}%` }} /></div>}
              {job?.warning && <p className="mt-3 text-xs leading-5 text-amber-800">{job.warning}</p>}
              {counts && (
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-gray-600 sm:grid-cols-4">
                  <span><strong className="block font-mono text-base text-gray-950">{counts.products_seen}</strong>Seen</span>
                  <span><strong className="block font-mono text-base text-gray-950">{counts.products_upserted}</strong>Updated</span>
                  <span><strong className="block font-mono text-base text-gray-950">{counts.products_marked_inactive}</strong>Inactive rows</span>
                  <span><strong className="block font-mono text-base text-gray-950">{counts.error_count}</strong>Errors</span>
                </div>
              )}
              {config?.last_synced_at && <p className="mt-3 text-xs text-gray-500">Last successful sync: {new Date(config.last_synced_at).toLocaleString()}</p>}
            </div>
          )}

          {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm leading-5 text-red-800">{error}</div>}
          {notice && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm leading-5 text-emerald-800">{notice}</div>}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-gray-200 bg-gray-50 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
          <button type="button" onClick={handleStart} disabled={isProcessing || !storeUrl.trim()} className="inline-flex items-center justify-center gap-2 rounded-md bg-gray-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 active:translate-y-px disabled:cursor-not-allowed disabled:bg-gray-300">
            <ArrowPathIcon className={`h-4 w-4 ${starting ? 'animate-spin' : ''}`} />
            {starting ? 'Starting…' : syncInFlight ? 'Sync in progress' : 'Save and sync now'}
          </button>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="rounded-md border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">Close</button>
            <button type="button" onClick={handleSave} disabled={isProcessing || !storeUrl.trim()} className="rounded-md border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-800 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50">{saved ? 'Saved' : saving ? 'Saving…' : 'Save settings'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
