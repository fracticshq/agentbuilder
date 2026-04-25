import axios from 'axios';
import { handleApiError } from './errorHandler';

declare global {
  interface Window {
    __APP_CONFIG__?: {
      API_BASE_URL?: string;
      WIDGET_BASE_URL?: string;
    };
  }
}

const runtimeConfig = window.__APP_CONFIG__ || {};
const API_BASE_URL = runtimeConfig.API_BASE_URL || process.env.REACT_APP_API_URL || window.location.origin;
const AUTH_STORAGE_KEY = 'agentbuilder.auth_session';
export const AUTH_SESSION_CHANGED_EVENT = 'agentbuilder.auth_session_changed';

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  full_name?: string | null;
  role: string;
  brand_id?: string | null;
  disabled: boolean;
  created_at: string;
  updated_at?: string;
}

export interface AuthSession {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt: number;
  user?: AuthUser | null;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token?: string | null;
  token_type: string;
  expires_in: number;
}

export interface AuthConfigResponse {
  signup_enabled: boolean;
  google_enabled: boolean;
  google_client_id?: string | null;
}

function notifyAuthSessionChanged(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_CHANGED_EVENT, {
    detail: { authenticated: isAuthenticated() },
  }));
}

export function getStoredAuthSession(): AuthSession | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const rawValue = window.localStorage.getItem(AUTH_STORAGE_KEY);
  if (!rawValue) {
    return null;
  }

  try {
    return JSON.parse(rawValue) as AuthSession;
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

export function getAccessToken(): string {
  return getStoredAuthSession()?.accessToken || '';
}

export function isAuthenticated(): boolean {
  const session = getStoredAuthSession();
  if (!session?.accessToken) {
    return false;
  }
  return session.expiresAt > Date.now();
}

export function setStoredAuthSession(session: AuthSession): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
  notifyAuthSessionChanged();
}

export function updateStoredAuthUser(user: AuthUser | null): void {
  const session = getStoredAuthSession();
  if (!session) {
    return;
  }
  setStoredAuthSession({
    ...session,
    user,
  });
}

export function clearStoredAuthSession(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
  notifyAuthSessionChanged();
}

export function createAuthSession(
  tokenResponse: AuthTokenResponse,
  user?: AuthUser | null,
  fallbackRefreshToken?: string | null,
): AuthSession {
  return {
    accessToken: tokenResponse.access_token,
    refreshToken: tokenResponse.refresh_token || fallbackRefreshToken || null,
    expiresAt: Date.now() + tokenResponse.expires_in * 1000,
    user: user || null,
  };
}

// Create axios instance
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

const bareHttpClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const accessToken = getAccessToken();
  if (accessToken) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${accessToken}`;
  } else if (config.headers && 'Authorization' in config.headers) {
    delete config.headers.Authorization;
  }
  return config;
});

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const session = getStoredAuthSession();
  if (!session?.refreshToken) {
    clearStoredAuthSession();
    return null;
  }

  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = bareHttpClient
    .post<AuthTokenResponse>('/api/v1/auth/refresh', {
      refresh_token: session.refreshToken,
    })
    .then((response) => {
      const nextSession = createAuthSession(response.data, session.user || null, session.refreshToken);
      setStoredAuthSession(nextSession);
      return nextSession.accessToken;
    })
    .catch(() => {
      clearStoredAuthSession();
      return null;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

// Add response interceptor for consistent error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as typeof error.config & { _retry?: boolean };

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !String(originalRequest.url || '').includes('/api/v1/auth/')
    ) {
      originalRequest._retry = true;
      const nextAccessToken = await refreshAccessToken();
      if (nextAccessToken) {
        originalRequest.headers = originalRequest.headers || {};
        originalRequest.headers.Authorization = `Bearer ${nextAccessToken}`;
        return apiClient(originalRequest);
      }
    }

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

export interface RuntimeSettingOption {
  value: string;
  label: string;
}

export interface RuntimeSettingField {
  key: string;
  label: string;
  description: string;
  input_type: 'text' | 'password' | 'select';
  secret: boolean;
  required: boolean;
  configured: boolean;
  source: 'stored' | 'environment' | 'default';
  value?: string | null;
  masked_value?: string | null;
  updated_at?: string | null;
  options?: RuntimeSettingOption[];
}

export interface RuntimeSettingSection {
  id: string;
  title: string;
  description: string;
  supports_connection_test: boolean;
  fields: RuntimeSettingField[];
}

export interface RuntimeSettingsResponse {
  sections: RuntimeSettingSection[];
}

export interface RuntimeSettingsUpdateResponse {
  updated: Array<{
    key: string;
    action: 'updated' | 'cleared';
    section: string;
  }>;
  settings: RuntimeSettingsResponse;
}

export interface RuntimeSettingsTestRequest {
  sections?: string[];
  overrides?: Record<string, string | null>;
}

export interface RuntimeSettingsTestResponse {
  status: 'healthy' | 'unhealthy';
  results: Array<{
    section: string;
    status: 'healthy' | 'unhealthy';
    detail: string;
  }>;
}

export interface AuthRequest {
  email: string;
  password: string;
  full_name?: string;
}

export const authApi = {
  getConfig: () => bareHttpClient.get<AuthConfigResponse>('/api/v1/auth/config'),
  login: (data: AuthRequest) =>
    bareHttpClient.post<AuthTokenResponse>('/api/v1/auth/login', {
      username: data.email,
      password: data.password,
    }),
  register: (data: AuthRequest) =>
    bareHttpClient.post<AuthUser>('/api/v1/auth/register', {
      email: data.email,
      password: data.password,
      full_name: data.full_name,
    }),
  me: () => apiClient.get<AuthUser>('/api/v1/auth/me'),
  logout: () => apiClient.post('/api/v1/auth/logout'),
  forgotPassword: (email: string) =>
    bareHttpClient.post<{ message: string; reset_url?: string | null }>('/api/v1/auth/forgot-password', { email }),
  resetPassword: (token: string, newPassword: string) =>
    bareHttpClient.post<{ message: string }>('/api/v1/auth/reset-password', {
      token,
      new_password: newPassword,
    }),
  google: (credential: string) =>
    bareHttpClient.post<AuthTokenResponse>('/api/v1/auth/google', { credential }),
};

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

export const runtimeSettingsApi = {
  get: () => apiClient.get<RuntimeSettingsResponse>('/api/v1/admin/settings/runtime'),
  update: (updates: Record<string, string | null>) =>
    apiClient.put<RuntimeSettingsUpdateResponse>('/api/v1/admin/settings/runtime', { updates }),
  test: (payload: RuntimeSettingsTestRequest) =>
    apiClient.post<RuntimeSettingsTestResponse>('/api/v1/admin/settings/runtime/test', payload),
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
