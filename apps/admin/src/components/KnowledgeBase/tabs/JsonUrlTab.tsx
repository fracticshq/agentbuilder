import React, { useState } from 'react';
import { catalogApi } from '../../../api/catalog';

const FORMAT_LABELS: Record<string, string> = {
  shopify: '🛍️ Shopify',
  woocommerce: '🛒 WooCommerce',
  schema_org: '📋 schema.org',
  generic: '📄 Generic (field mapping required)',
};

interface JsonUrlTabProps {
  brandId: string;
  onUpload: (data: any[]) => void;
  onBack: () => void;
}

export default function JsonUrlTab({ brandId, onUpload, onBack }: JsonUrlTabProps) {
  const [url, setUrl] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [items, setItems] = useState<any[]>([]);
  const [detectedFormat, setDetectedFormat] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFetch = async () => {
    if (!url.trim()) return;
    setStatus('loading');
    setError(null);
    setItems([]);
    setDetectedFormat(null);
    try {
      const result = await catalogApi.importJsonFeed(url.trim(), brandId);
      setItems(result.items);
      setDetectedFormat(result.detected_format);
      setStatus('done');
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Fetch failed');
      setStatus('error');
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Import from JSON URL</h3>
        <p className="text-xs text-gray-500 mt-0.5">
          Paste a direct URL to a JSON product feed. Format is auto-detected.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Feed URL <span className="text-red-500">*</span>
        </label>
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleFetch()}
            placeholder="https://catalog.example.com/feed.json"
            disabled={status === 'loading'}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50"
          />
          <button
            onClick={handleFetch}
            disabled={!url.trim() || status === 'loading'}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md disabled:bg-gray-300 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {status === 'loading' ? (
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Fetching…
              </span>
            ) : 'Fetch'}
          </button>
        </div>
        <p className="mt-1 text-xs text-gray-400">
          Supports Shopify, WooCommerce, schema.org, and generic JSON arrays.
        </p>
      </div>

      {status === 'error' && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-sm text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {status === 'done' && (
        <div className="rounded-md bg-green-50 border border-green-200 p-4 space-y-1">
          <p className="text-sm text-green-800 font-medium">
            ✅ {items.length} items loaded
          </p>
          {detectedFormat && (
            <p className="text-xs text-green-700">
              Detected format: <span className="font-medium">{FORMAT_LABELS[detectedFormat] ?? detectedFormat}</span>
            </p>
          )}
          {detectedFormat === 'generic' && (
            <p className="text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded px-2 py-1 mt-2">
              ⚠️ Generic format — you'll map the fields in the next step.
            </p>
          )}
        </div>
      )}

      <div className="flex justify-between pt-4 border-t border-gray-200">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          ← Back to Content Type
        </button>
        {status === 'done' && (
          <button
            onClick={() => onUpload(items)}
            className="px-6 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
          >
            Next: Map Fields →
          </button>
        )}
      </div>
    </div>
  );
}
