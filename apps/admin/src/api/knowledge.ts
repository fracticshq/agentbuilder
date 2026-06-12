import { apiClient } from './client';
import type { 
  KnowledgeDocument,
  DocumentPreview,
  DocumentSummary,
  UploadDocumentRequest, 
  UploadDocumentResponse,
  UploadJobStatus,
  ContentType,
  ProductData,
  DealerData,
  CreateKnowledgeFolderRequest,
  KnowledgeTreeResponse,
  MoveKnowledgeItemRequest,
  RenameKnowledgeItemRequest,
  RetrieveKnowledgeRequest,
  RetrieveKnowledgeResponse
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
    if (data.agent_id) {
      formData.append('agent_id', data.agent_id);
    }
    if (data.folder_id) {
      formData.append('folder_id', data.folder_id);
    }
    if (data.folder_path) {
      formData.append('folder_path', data.folder_path);
    }
    
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
    folder_id?: string | null;
    folder_path?: string;
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
  async getJobStatus(jobId: string): Promise<UploadJobStatus> {
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
   * Get source metadata and representative records/chunks for preview
   */
  async getDocumentPreview(docId: string, brandId: string): Promise<DocumentPreview> {
    const params = new URLSearchParams({ brand_id: brandId });
    const response = await apiClient.get<{document: DocumentPreview}>(
      `/api/v1/knowledge/documents/${docId}/preview?${params.toString()}`
    );

    return response.data.document;
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

  /**
   * Get filesystem-style knowledge tree for a brand.
   */
  async getTree(brandId?: string): Promise<KnowledgeTreeResponse> {
    const params = new URLSearchParams();
    if (brandId) {
      params.append('brand_id', brandId);
    }

    const query = params.toString();
    const response = await apiClient.get<KnowledgeTreeResponse>(
      `/api/v1/knowledge/tree${query ? `?${query}` : ''}`
    );

    return response.data;
  },

  /**
   * Create a folder in the knowledge filesystem.
   */
  async createFolder(data: CreateKnowledgeFolderRequest) {
    const response = await apiClient.post('/api/v1/knowledge/folders', data);
    return response.data;
  },

  /**
   * Move a folder or document to another folder.
   */
  async moveItem(itemId: string, data: MoveKnowledgeItemRequest) {
    const response = await apiClient.patch(
      `/api/v1/knowledge/items/${encodeURIComponent(itemId)}/move`,
      data
    );
    return response.data;
  },

  /**
   * Rename a folder or document.
   */
  async renameItem(itemId: string, data: RenameKnowledgeItemRequest) {
    const response = await apiClient.patch(
      `/api/v1/knowledge/items/${encodeURIComponent(itemId)}/rename`,
      data
    );
    return response.data;
  },

  /**
   * Delete a folder or document from the knowledge filesystem.
   */
  async deleteItem(itemId: string, brandId?: string): Promise<void> {
    const params = new URLSearchParams();
    if (brandId) {
      params.append('brand_id', brandId);
    }

    await apiClient.delete(
      `/api/v1/knowledge/items/${encodeURIComponent(itemId)}${params.toString() ? `?${params.toString()}` : ''}`
    );
  },

  /**
   * Test retrieval against the current knowledge filesystem context.
   */
  async retrieve(data: RetrieveKnowledgeRequest): Promise<RetrieveKnowledgeResponse> {
    const response = await apiClient.post<RetrieveKnowledgeResponse>(
      '/api/v1/knowledge/retrieve',
      data
    );

    return response.data;
  },
};
