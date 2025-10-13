import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Create axios instance
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

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
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  agent_id?: string;
  filename: string;
  file_type: string;
  file_size: number;
  content?: string;
  metadata: {
    title?: string;
    category?: string;
    tags?: string[];
    document_type?: 'product_data' | 'category_data' | 'faq_data' | 'dealer_data' | 'area_representative_data' | 'office_data' | 'manual' | 'policy' | 'other';
  };
  embedding_status: 'pending' | 'processing' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
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
  update: (id: string, data: Partial<CreateAgentRequest>) => 
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
    try {
      const response = await brandApi.list();
      return response.data;
    } catch (error) {
      // Return mock data if API is not available
      console.warn('API not available, using mock data:', error);
      return [
        {
          id: '1',
          name: 'Essco Bathware',
          slug: 'essco-bathware',
          description: 'Premium bathroom solutions company',
          industry: 'Manufacturing',
          website: 'https://essco.com',
          logo_url: undefined,
          contact_info: { email: 'contact@essco.com' },
          brand_voice: { 
            tone: 'professional' as const, 
            style: 'helpful' as const, 
            personality: ['knowledgeable', 'patient'],
            language_style: 'clear and concise'
          },
          colors: { primary: '#2563eb', secondary: '#64748b', accent: '#f59e0b' },
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ];
    }
  },
  getBrand: async (id: string) => {
    try {
      const response = await brandApi.get(id);
      return response.data;
    } catch (error) {
      console.warn('API not available, using mock data');
      return {
        id: '1',
        name: 'Essco Bathware',
        slug: 'essco-bathware',
        description: 'Premium bathroom solutions company',
        industry: 'Manufacturing',
        website: 'https://essco.com',
        logo_url: undefined,
        contact_info: { email: 'contact@essco.com' },
        brand_voice: { 
          tone: 'professional' as const, 
          style: 'helpful' as const, 
          personality: ['knowledgeable', 'patient'],
          language_style: 'clear and concise'
        },
        colors: { primary: '#2563eb', secondary: '#64748b', accent: '#f59e0b' },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };
    }
  },
  createBrand: async (data: CreateBrandRequest) => {
    try {
      const response = await brandApi.create(data);
      return response.data;
    } catch (error) {
      console.warn('API not available, simulating brand creation');
      return {
        id: Math.random().toString(),
        ...data,
        slug: data.name.toLowerCase().replace(/\s+/g, '-'),
        contact_info: {},
        brand_voice: { 
          tone: 'professional' as const, 
          style: 'helpful' as const, 
          personality: [],
          language_style: 'clear and concise'
        },
        colors: { primary: '#2563eb', secondary: '#64748b', accent: '#f59e0b' },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }
  },
  updateBrand: async (id: string, data: Partial<CreateBrandRequest>) => {
    try {
      const response = await brandApi.update(id, data);
      return response.data;
    } catch (error) {
      console.warn('API not available, simulating brand update');
      return {
        id,
        ...data,
        slug: data.name?.toLowerCase().replace(/\s+/g, '-') || 'brand',
        name: data.name || 'Brand',
        description: data.description || '',
        industry: data.industry || '',
        contact_info: {},
        brand_voice: { 
          tone: 'professional' as const, 
          style: 'helpful' as const, 
          personality: [],
          language_style: 'clear and concise'
        },
        colors: { primary: '#2563eb', secondary: '#64748b', accent: '#f59e0b' },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: new Date().toISOString(),
      };
    }
  },
  deleteBrand: async (id: string) => {
    try {
      await brandApi.delete(id);
    } catch (error) {
      console.warn('API not available, simulating brand deletion');
    }
  },
  
  // Agents
  getAgents: async (brandId?: string) => {
    try {
      const response = await agentApi.list(brandId);
      return response.data;
    } catch (error) {
      console.warn('API not available, using mock data');
      return [
        {
          id: '1',
          brand_id: '1',
          name: 'Customer Support Agent',
          slug: 'customer-support',
          description: 'Helps customers with product inquiries and support',
          configuration: {
            llm: { provider: 'openai', model: 'gpt-4o-mini', temperature: 0.7, max_tokens: 1000 },
            embedding: { provider: 'voyage', model: 'voyage-large-2-instruct' },
            rag: { enabled: true, top_k: 5, similarity_threshold: 0.7, knowledge_base_id: 'kb-1' },
            features: { websockets: true, file_upload: true, conversation_memory: true, typing_indicators: true },
            security: { rate_limiting: true, content_filtering: true, session_timeout: 1800 }
          },
          system_prompt: 'You are a helpful customer support agent for Essco Bathware.',
          status: 'active' as const,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
        {
          id: '2',
          brand_id: '1',
          name: 'Sales Assistant',
          slug: 'sales-assistant',
          description: 'Assists with product recommendations and sales inquiries',
          configuration: {
            llm: { provider: 'openai', model: 'gpt-4o-mini', temperature: 0.8, max_tokens: 800 },
            embedding: { provider: 'voyage', model: 'voyage-large-2-instruct' },
            rag: { enabled: true, top_k: 3, similarity_threshold: 0.8, knowledge_base_id: 'kb-1' },
            features: { websockets: true, file_upload: false, conversation_memory: true, typing_indicators: true },
            security: { rate_limiting: true, content_filtering: true, session_timeout: 1800 }
          },
          system_prompt: 'You are a sales assistant specializing in bathroom products.',
          status: 'draft' as const,
          created_at: '2024-01-02T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        },
      ];
    }
  },
  getAgent: async (id: string) => {
    try {
      const response = await agentApi.get(id);
      return response.data;
    } catch (error) {
      console.warn('API not available, using mock data');
      return {
        id: '1',
        brand_id: '1',
        name: 'Customer Support Agent',
        slug: 'customer-support',
        description: 'Helps customers with product inquiries and support',
        configuration: {
          llm: { provider: 'openai', model: 'gpt-4o-mini', temperature: 0.7, max_tokens: 1000 },
          embedding: { provider: 'voyage', model: 'voyage-large-2-instruct' },
          rag: { enabled: true, top_k: 5, similarity_threshold: 0.7, knowledge_base_id: 'kb-1' },
          features: { websockets: true, file_upload: true, conversation_memory: true, typing_indicators: true },
          security: { rate_limiting: true, content_filtering: true, session_timeout: 1800 }
        },
        system_prompt: 'You are a helpful customer support agent for Essco Bathware.',
        status: 'active' as const,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };
    }
  },
  createAgent: async (data: CreateAgentRequest) => {
    try {
      const response = await agentApi.create(data);
      return response.data;
    } catch (error) {
      console.warn('API not available, simulating agent creation');
      return {
        id: Math.random().toString(),
        ...data,
        slug: data.name.toLowerCase().replace(/\s+/g, '-'),
        status: 'draft' as const,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }
  },
  updateAgent: async (id: string, data: Partial<CreateAgentRequest>) => {
    try {
      const response = await agentApi.update(id, data);
      return response.data;
    } catch (error) {
      console.warn('API not available, simulating agent update');
      return {
        id,
        brand_id: data.brand_id || '1',
        name: data.name || 'Agent',
        slug: data.name?.toLowerCase().replace(/\s+/g, '-') || 'agent',
        description: data.description || '',
        configuration: data.configuration || {},
        system_prompt: data.system_prompt || '',
        status: 'draft' as const,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: new Date().toISOString(),
      };
    }
  },
  deleteAgent: async (id: string) => {
    try {
      await agentApi.delete(id);
    } catch (error) {
      console.warn('API not available, simulating agent deletion');
    }
  },
};

// Document/Knowledge Base API
export const documentApi = {
  uploadDocuments: async (files: File[], metadata?: { category?: string; tags?: string[]; document_type?: string; agent_id?: string }) => {
    try {
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
      
      // Add metadata if provided
      if (metadata) {
        formData.append('metadata', JSON.stringify(metadata));
      }

      const response = await apiClient.post('/api/v1/ingest/documents', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      return response.data;
    } catch (error) {
      console.error('Document upload failed:', error);
      // Mock response for demo
      return {
        job_id: `mock-job-${Date.now()}`,
        status: 'processing',
        message: 'Documents uploaded and processing started (mock)',
        documents_count: files.length,
      };
    }
  },

  getKnowledgeDocuments: async (agentId?: string): Promise<KnowledgeDocument[]> => {
    try {
      const url = agentId ? `/api/v1/ingest/documents?agent_id=${agentId}` : '/api/v1/ingest/documents';
      const response = await apiClient.get(url);
      return response.data;
    } catch (error) {
      console.warn('API not available, using mock knowledge documents');
      // Mock documents for demo
      return [
        {
          id: 'doc-1',
          agent_id: agentId,
          filename: 'product_data.json',
          file_type: 'application/json',
          file_size: 15420,
          metadata: {
            title: 'Essco Product Data',
            category: 'products',
            document_type: 'product_data',
            tags: ['products', 'essco', 'bathware'],
          },
          embedding_status: 'completed',
          created_at: '2024-01-01T10:00:00Z',
          updated_at: '2024-01-01T10:00:00Z',
        },
        {
          id: 'doc-2',
          agent_id: agentId,
          filename: 'essco_faq.json',
          file_type: 'application/json',
          file_size: 8930,
          metadata: {
            title: 'Essco FAQ Data',
            category: 'support',
            document_type: 'faq_data',
            tags: ['faq', 'support', 'essco'],
          },
          embedding_status: 'completed',
          created_at: '2024-01-01T11:00:00Z',
          updated_at: '2024-01-01T11:00:00Z',
        },
        {
          id: 'doc-3',
          agent_id: agentId,
          filename: 'dealers_data.json',
          file_type: 'application/json',
          file_size: 12350,
          metadata: {
            title: 'Essco Dealer Information',
            category: 'dealers',
            document_type: 'dealer_data',
            tags: ['dealers', 'locations', 'essco'],
          },
          embedding_status: 'processing',
          created_at: '2024-01-01T12:00:00Z',
          updated_at: '2024-01-01T12:00:00Z',
        },
      ];
    }
  },

  deleteDocument: async (docId: string): Promise<void> => {
    try {
      await apiClient.delete(`/api/v1/ingest/documents/${docId}`);
    } catch (error) {
      console.warn('API not available, simulating document deletion');
    }
  },

  getJobStatus: async (jobId: string) => {
    try {
      const response = await apiClient.get(`/api/v1/ingest/status/${jobId}`);
      return response.data;
    } catch (error) {
      console.warn('API not available, simulating job status');
      return {
        job_id: jobId,
        status: 'completed',
        progress: 100,
        message: 'Processing completed successfully (mock)',
      };
    }
  },
};
