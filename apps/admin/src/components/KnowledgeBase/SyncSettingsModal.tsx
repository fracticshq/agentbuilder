import React, { useEffect, useState } from 'react';
import { XMarkIcon } from '@heroicons/react/24/outline';
import { catalogApi } from '../../api/catalog';

interface SyncSettingsModalProps {
  brandId: string;
  sourceType: string;
  sourceUrl: string;
  clientId?: string;
  clientSecret?: string;
  onClose: () => void;
}

export default function SyncSettingsModal({
  brandId,
  sourceType,
  sourceUrl,
  clientId,
  clientSecret,
  onClose,
}: SyncSettingsModalProps) {
  const [autoSync, setAutoSync] = useState(false);
  const [frequency, setFrequency] = useState('daily');
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    catalogApi.getSyncConfig(brandId).then(cfg => {
      if (cfg) {
        setAutoSync(cfg.auto_sync ?? false);
        setFrequency(cfg.sync_frequency ?? 'daily');
        setLastSynced(cfg.last_synced_at ?? null);
      }
    }).catch(() => {});
  }, [brandId]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await catalogApi.updateSyncConfig(brandId, {
        source_type: sourceType,
        source_url: sourceUrl,
        client_id: clientId,
        client_secret: clientSecret,
        auto_sync: autoSync,
        sync_frequency: frequency,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleManualSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    setError(null);
    try {
      const result = await catalogApi.manualSync(brandId);
      if (result.status === 'completed') {
        setSyncResult(`✅ Sync complete — ${result.raw_count ?? result.items?.length ?? '?'} products updated`);
      } else {
        setSyncResult(`⏳ Sync started (job: ${result.job_id}). Products will update shortly.`);
      }
      setLastSynced(new Date().toISOString());
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold text-gray-900">⚙️ Sync Configuration</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Source info */}
        <div className="mb-5 px-3 py-2 bg-gray-50 rounded-md text-xs text-gray-600">
          <span className="font-medium">Source:</span>{' '}
          <span className="font-mono">{sourceUrl}</span>
          <span className="ml-2 px-1.5 py-0.5 bg-gray-200 rounded text-gray-700 capitalize">{sourceType}</span>
        </div>

        {/* Auto-sync toggle */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm font-medium text-gray-900">Auto-Sync</p>
            <p className="text-xs text-gray-500">Automatically re-import products on a schedule</p>
          </div>
          <button
            onClick={() => setAutoSync(v => !v)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              autoSync ? 'bg-primary-600' : 'bg-gray-200'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                autoSync ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {/* Frequency */}
        {autoSync && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Sync Frequency</label>
            <select
              value={frequency}
              onChange={e => setFrequency(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
        )}

        {/* Last synced */}
        {lastSynced && (
          <p className="text-xs text-gray-500 mb-4">
            Last synced: {new Date(lastSynced).toLocaleString()}
          </p>
        )}

        {/* Error */}
        {error && (
          <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
            {error}
          </div>
        )}

        {/* Sync result */}
        {syncResult && (
          <div className="mb-4 text-sm text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">
            {syncResult}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-gray-100">
          <button
            onClick={handleManualSync}
            disabled={syncing}
            className="px-4 py-2 text-sm font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 border border-primary-200 rounded-md disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {syncing && (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
            )}
            {syncing ? 'Syncing…' : '↻ Manual Resync'}
          </button>

          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Close
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md disabled:opacity-50"
            >
              {saved ? '✓ Saved' : saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
