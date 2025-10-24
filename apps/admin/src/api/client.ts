import axios from 'axios';
import { handleApiError } from './errorHandler';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Create axios instance
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add response interceptor for consistent error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiError = handleApiError(error);
    return Promise.reject(apiError);
  }
);

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
  colors?: any;
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
}

export interface CreateAgentRequest {
  brand_id: string;
  name: string;
  description: string;
  system_prompt: string;
  configuration: any;
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
    console.log('🔍 Fetching documents with params:', params);
    
    const response = await apiClient.get<{ documents: any[], count: number }>('/api/v1/ingest/documents', { params });
    
    console.log('📥 Documents API response:', response.data);
    
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
    
    console.log('✨ Transformed documents:', transformed);
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
