import axios from 'axios';
import { handleApiError } from './errorHandler';

declare global {
  interface Window {
    __APP_CONFIG__?: {
      API_BASE_URL?: string;
    };
  }
}

const runtimeConfig = window.__APP_CONFIG__ || {};
const API_BASE_URL = runtimeConfig.API_BASE_URL || process.env.REACT_APP_API_URL || window.location.origin;
const ADMIN_API_KEY_STORAGE_KEY = 'agentbuilder.admin_api_key';

export function getAdminApiKey(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  return window.sessionStorage.getItem(ADMIN_API_KEY_STORAGE_KEY) || '';
}

export function setAdminApiKey(value: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  const trimmedValue = value.trim();
  if (trimmedValue) {
    window.sessionStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, trimmedValue);
    return;
  }
  window.sessionStorage.removeItem(ADMIN_API_KEY_STORAGE_KEY);
}

export function clearAdminApiKey(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.sessionStorage.removeItem(ADMIN_API_KEY_STORAGE_KEY);
}

// Create axios instance
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const adminApiKey = getAdminApiKey();
  if (adminApiKey) {
    config.headers = config.headers || {};
    config.headers['X-Admin-Key'] = adminApiKey;
  } else if (config.headers && 'X-Admin-Key' in config.headers) {
    delete config.headers['X-Admin-Key'];
  }
  return config;
});

// Add response interceptor for consistent error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiError = handleApiError(error);
    return Promise.reject(apiError);
  }
);

// Brand identity / widget theme — stored inside Brand.colors
export interface BrandIdentity {
  primary_color?: string;          // e.g. "#00c864"
  default_mode?: 'dark' | 'light'; // admin-chosen mode, no user toggle
  chat_logo_dark_url?: string;     // logo shown in bubble/hero on dark background
  chat_logo_light_url?: string;    // logo shown in bubble/hero on light background
  hero_title?: string;             // e.g. "I'm Antara AI"
  hero_subtitle?: string;          // e.g. "Ask me anything about senior living"
  suggestion_chips?: string;       // comma-separated quick-prompt chips
  cycling_categories?: string;     // comma-separated categories that animate in the subtitle
  dark_bg_gradient?: string;       // CSS gradient override for dark panel
  light_bg_gradient?: string;      // CSS gradient override for light panel
  hide_nova_logo?: boolean;        // hide the NOVA platform wordmark in widget topbar
}

// Types
export interface Brand {
  id: string;
  name: string;
  slug: string;
  description: string;
  logo_url?: string;
  website?: string;
  industry: string;
  contact_info?: any;
  brand_voice?: any;
  colors?: BrandIdentity;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  id: string;
  brand_id: string;
  name: string;
  slug: string;
  description: string;
  configuration: any;
  system_prompt: string;
  status: 'draft' | 'active' | 'inactive';
  metadata?: {
    purpose?: string;
    role?: string;
  };
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  // Fields from backend aggregation
  filename: string;
  agent_id?: string;
  job_id?: string;
  chunks_count?: number;
  created_at?: string;
  content_type?: string;
  
  // Legacy fields (for compatibility)
  id?: string;
  file_type?: string;
  file_size?: number;
  content?: string;
  metadata?: {
    title?: string;
    category?: string;
    tags?: string[];
    document_type?: 'product_data' | 'category_data' | 'faq_data' | 'dealer_data' | 'area_representative_data' | 'office_data' | 'manual' | 'policy' | 'other';
  };
  embedding_status?: 'pending' | 'processing' | 'completed' | 'failed';
  updated_at?: string;
}

export interface DocumentUploadRequest {
  files: File[];
  metadata?: {
    category?: string;
    tags?: string[];
    document_type?: string;
  };
}

export interface CreateBrandRequest {
  name: string;
  description: string;
  industry: string;
  website?: string;
  logo_url?: string;
  colors?: BrandIdentity;
}

export interface CreateAgentRequest {
  brand_id: string;
  name: string;
  description: string;
  system_prompt: string;
  configuration: any;
  status?: 'active' | 'inactive' | 'draft';
  metadata?: {
    purpose?: string;
    role?: string;
  };
}

export interface UpdateAgentRequest {
  brand_id?: string;
  name?: string;
  description?: string;
  system_prompt?: string;
  configuration?: any;
  status?: 'active' | 'inactive' | 'draft';
  metadata?: {
    purpose?: string;
    role?: string;
  };
}

export interface AzureOpenAIDeployment {
  deployment_name: string;
  model_name: string;
  model_version?: string | null;
  provisioning_state: string;
  sku_name?: string | null;
}

export interface AzureOpenAIDeploymentsResponse {
  provider: 'azure_openai';
  default_deployment?: string | null;
  deployments: AzureOpenAIDeployment[];
}

// Brand API
export const brandApi = {
  list: () => apiClient.get<Brand[]>('/api/v1/admin/brands/'),
  get: (id: string) => apiClient.get<Brand>(`/api/v1/admin/brands/${id}`),
  create: (data: CreateBrandRequest) => apiClient.post<Brand>('/api/v1/admin/brands/', data),
  update: (id: string, data: Partial<CreateBrandRequest>) => 
    apiClient.put<Brand>(`/api/v1/admin/brands/${id}`, data),
  delete: (id: string) => apiClient.delete(`/api/v1/admin/brands/${id}`),
};

// Agent API
export const agentApi = {
  list: (brandId?: string) => {
    const params = brandId ? { brand_id: brandId } : {};
    return apiClient.get<Agent[]>('/api/v1/admin/agents/', { params });
  },
  get: (id: string) => apiClient.get<Agent>(`/api/v1/admin/agents/${id}`),
  create: (data: CreateAgentRequest) => apiClient.post<Agent>('/api/v1/admin/agents/', data),
  update: (id: string, data: Partial<UpdateAgentRequest>) => 
    apiClient.put<Agent>(`/api/v1/admin/agents/${id}`, data),
  delete: (id: string) => apiClient.delete(`/api/v1/admin/agents/${id}`),
};

export const llmApi = {
  getAzureDeployments: () =>
    apiClient.get<AzureOpenAIDeploymentsResponse>('/api/v1/admin/llm/azure/deployments'),
};

// Catalog API
export const catalogApi = {
  syncShopify: (data: { brand_id: string; store_url: string; access_token?: string }) => 
    apiClient.post<{ job_id: string; status: string }>('/api/v1/catalog/import/shopify', data),
};

// Health check
export const healthApi = {
  check: () => apiClient.get('/health'),
};

// Combined API object for easier importing
export const api = {
  // Brands
  getBrands: async () => {
    const response = await brandApi.list();
    return response.data;
  },
  getBrand: async (id: string) => {
    const response = await brandApi.get(id);
    return response.data;
  },
  createBrand: async (data: CreateBrandRequest) => {
    const response = await brandApi.create(data);
    return response.data;
  },
  updateBrand: async (id: string, data: Partial<CreateBrandRequest>) => {
    const response = await brandApi.update(id, data);
    return response.data;
  },
  deleteBrand: async (id: string) => {
    await brandApi.delete(id);
  },
  
  // Agents
  getAgents: async (brandId?: string) => {
    const response = await agentApi.list(brandId);
    return response.data;
  },
  getAgent: async (id: string) => {
    const response = await agentApi.get(id);
    return response.data;
  },
  createAgent: async (data: CreateAgentRequest) => {
    const response = await agentApi.create(data);
    return response.data;
  },
  updateAgent: async (id: string, data: Partial<UpdateAgentRequest>) => {
    const response = await agentApi.update(id, data);
    return response.data;
  },
  deleteAgent: async (id: string) => {
    await agentApi.delete(id);
  },

  getAzureDeployments: async () => {
    const response = await llmApi.getAzureDeployments();
    return response.data;
  },
  
  // Catalog
  syncShopify: async (data: { brand_id: string; store_url: string; access_token?: string }) => {
    const response = await catalogApi.syncShopify(data);
    return response.data;
  },
};

// Document/Knowledge Base API
export const documentApi = {
  uploadDocuments: async (files: File[], metadata?: { category?: string; tags?: string[]; document_type?: string; agent_id?: string }) => {
    const formData = new FormData();
    
    // Add files to FormData
    Array.from(files).forEach((file) => {
      // Set correct MIME type for JSON files
      if (file.name.endsWith('.json')) {
        const jsonFile = new File([file], file.name, { type: 'application/json' });
        formData.append('files', jsonFile);
      } else {
        formData.append('files', file);
      }
    });
    
    // Add metadata if provided (especially agent_id)
    if (metadata?.agent_id) {
      // Pass agent_id as query parameter for proper storage
      const params = new URLSearchParams();
      params.append('agent_id', metadata.agent_id);
      
      const response = await apiClient.post(`/api/v1/ingest/documents?${params.toString()}`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      return response.data;
    }
    
    // If no agent_id, upload without it
    const response = await apiClient.post('/api/v1/ingest/documents', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    
    return response.data;
  },

  getKnowledgeDocuments: async (agentId?: string): Promise<KnowledgeDocument[]> => {
    const params = agentId ? { agent_id: agentId } : {};
    process.env.NODE_ENV !== 'production' && console.log('🔍 Fetching documents with params:', params);
    
    const response = await apiClient.get<{ documents: any[], count: number }>('/api/v1/ingest/documents', { params });
    
    process.env.NODE_ENV !== 'production' && console.log('📥 Documents API response:', response.data);
    
    // Transform API response to match KnowledgeDocument interface
    const transformed = response.data.documents.map((doc: any) => ({
      id: doc._id || doc.filename,
      agent_id: doc.agent_id,
      filename: doc.filename,
      file_type: doc.content_type || 'application/json',
      file_size: 0, // Not available from aggregation
      metadata: {
        title: doc.filename,
        category: 'knowledge',
        tags: [],
        document_type: 'other' as const,
      },
      embedding_status: 'completed' as const,
      created_at: doc.created_at || new Date().toISOString(),
      updated_at: doc.created_at || new Date().toISOString(),
    }));
    
    process.env.NODE_ENV !== 'production' && console.log('✨ Transformed documents:', transformed);
    return transformed;
  },

  deleteDocument: async (docId: string): Promise<void> => {
    await apiClient.delete(`/api/v1/ingest/documents/${docId}`);
  },

  getJobStatus: async (jobId: string) => {
    const response = await apiClient.get(`/api/v1/ingest/status/${jobId}`);
    return response.data;
  },
};
