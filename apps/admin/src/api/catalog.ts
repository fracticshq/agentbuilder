import { apiClient } from './client';

export interface CatalogSyncCounts {
  products_seen: number;
  products_upserted: number;
  products_marked_inactive: number;
  error_count: number;
}

export interface CatalogSyncConfig {
  source_type?: string;
  source_url?: string;
  fallback_currency?: string | null;
  auto_sync?: boolean;
  sync_frequency?: string;
  enabled?: boolean;
  access_token_configured?: boolean;
  last_sync_status?: 'processing' | 'completed' | 'error' | string;
  last_sync_job_id?: string;
  last_sync_started_at?: string;
  last_sync_completed_at?: string;
  last_synced_at?: string;
  last_sync_error?: string | null;
  last_sync_counts?: CatalogSyncCounts;
}

export interface CatalogSyncJob {
  job_id: string;
  brand_id?: string;
  source_url?: string;
  status: 'queued' | 'running' | 'processing' | 'completed' | 'error' | 'cancelled' | string;
  phase?: string;
  deduplicated?: boolean;
  processed?: number;
  total?: number;
  page?: number;
  items?: any[];
  results: any[];
  warning?: string | null;
  error?: string | null;
  counts?: CatalogSyncCounts;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}

export interface CatalogSyncUpdate {
  source_type: string;
  source_url: string;
  access_token?: string;
  fallback_currency?: string | null;
  auto_sync: boolean;
  sync_frequency: string;
}

export const catalogApi = {
  importShopify: async (
    storeUrl: string,
    brandId: string,
    accessToken?: string,
    fallbackCurrency?: string,
  ) => {
    const response = await apiClient.post('/api/v1/catalog/import/shopify', {
      store_url: storeUrl,
      brand_id: brandId,
      access_token: accessToken || null,
      fallback_currency: fallbackCurrency || null,
    });
    return response.data as { job_id: string; status: string; deduplicated?: boolean };
  },

  importJsonFeed: async (url: string, brandId: string) => {
    const response = await apiClient.post('/api/v1/catalog/import/json-feed', {
      url,
      brand_id: brandId,
    });
    return response.data as { items: any[]; detected_format: string; raw_count: number };
  },

  importCsv: async (file: File, brandId: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('brand_id', brandId);
    const response = await apiClient.post('/api/v1/catalog/import/csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data as { items: any[]; detected_format: string; raw_count: number };
  },

  importScrape: async (urls: string[], brandId: string) => {
    const response = await apiClient.post('/api/v1/catalog/import/scrape', {
      urls,
      brand_id: brandId,
    });
    return response.data as { job_id: string; status: string };
  },

  getJob: async (jobId: string, brandId?: string) => {
    const response = await apiClient.get<CatalogSyncJob>(`/api/v1/catalog/jobs/${jobId}`, {
      params: brandId ? { brand_id: brandId } : undefined,
    });
    return response.data;
  },

  getSyncConfig: async (brandId: string) => {
    const response = await apiClient.get<CatalogSyncConfig>(`/api/v1/catalog/sync-config/${brandId}`);
    return response.data;
  },

  updateSyncConfig: async (brandId: string, config: CatalogSyncUpdate) => {
    const response = await apiClient.put<CatalogSyncConfig>(`/api/v1/catalog/sync-config/${brandId}`, config);
    return response.data;
  },

  startSync: async (brandId: string) => {
    const response = await apiClient.post<{ job_id: string; status: string; deduplicated?: boolean }>(
      `/api/v1/catalog/sync/${brandId}`,
    );
    return response.data;
  },

  // Kept as a compatibility alias for the legacy Shopify tab/modal.
  manualSync: async (brandId: string) => catalogApi.startSync(brandId),
};
