import { apiClient } from './client';
import type { 
  KnowledgeDocument,
  DocumentSummary,
  UploadDocumentRequest, 
  UploadDocumentResponse,
  ContentType,
  ProductData,
  DealerData
} from '../types/knowledge';

export const knowledgeApi = {
  /**
   * Upload a document to the knowledge base with structured metadata
   */
  async uploadDocument(data: UploadDocumentRequest): Promise<UploadDocumentResponse> {
    const formData = new FormData();
    formData.append('file', data.file);
    formData.append('content_type', data.content_type);
    formData.append('brand_id', data.brand_id);
    
    if (data.product_data) {
      formData.append('product_data', JSON.stringify(data.product_data));
    }
    
    if (data.dealer_data) {
      formData.append('dealer_data', JSON.stringify(data.dealer_data));
    }

    const response = await apiClient.post<UploadDocumentResponse>(
      '/api/v1/knowledge/upload',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );

    return response.data;
  },

  /**
   * Bulk upload products or dealers from JSON
   */
  async bulkUploadJson(data: {
    content_type: 'product' | 'dealer';
    items: Array<ProductData | DealerData>;
    brand_id: string;
  }): Promise<UploadDocumentResponse> {
    const response = await apiClient.post<UploadDocumentResponse>(
      '/api/v1/knowledge/bulk-upload',
      data
    );

    return response.data;
  },

  /**
   * Get upload job status
   */
  async getJobStatus(jobId: string): Promise<{
    job_id: string;
    status: 'pending' | 'processing' | 'completed' | 'error';
    progress: {
      type?: string;
      processed_items?: number;
      total_items?: number;
      processed_chunks?: number;
      total_chunks?: number;
    };
    error?: string;
  }> {
    const response = await apiClient.get(`/api/v1/knowledge/jobs/${jobId}`);
    return response.data;
  },

  /**
   * Get all documents for a brand
   */
  async getDocuments(brandId: string, contentType?: ContentType): Promise<DocumentSummary[]> {
    const params = new URLSearchParams({ brand_id: brandId });
    if (contentType) {
      params.append('content_type', contentType);
    }

    const response = await apiClient.get<{documents: DocumentSummary[]}>(
      `/api/v1/knowledge/documents?${params.toString()}`
    );

    return response.data.documents;
  },

  /**
   * Get a single document by ID
   */
  async getDocument(docId: string): Promise<KnowledgeDocument> {
    const response = await apiClient.get<KnowledgeDocument>(
      `/api/v1/knowledge/documents/${docId}`
    );

    return response.data;
  },

  /**
   * Delete a document
   */
  async deleteDocument(docId: string, brandId: string): Promise<void> {
    await apiClient.delete(`/api/v1/knowledge/documents/${docId}?brand_id=${brandId}`);
  },

  /**
   * Update document metadata
   */
  async updateDocument(
    docId: string, 
    updates: Partial<KnowledgeDocument>
  ): Promise<KnowledgeDocument> {
    const response = await apiClient.patch<KnowledgeDocument>(
      `/api/v1/knowledge/documents/${docId}`,
      updates
    );

    return response.data;
  },
};
