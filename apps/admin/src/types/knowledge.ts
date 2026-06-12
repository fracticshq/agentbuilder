// TypeScript types for Knowledge Base documents

export type ContentType = 'product' | 'dealer' | 'faq' | 'office' | 'category' | 'guide' | 'document';

export interface ProductData {
  sku: string;
  name: string;
  price: number;           // Integer (paise/cents)
  currency: string;         // e.g., "INR", "USD"
  category: string;
  image_url?: string;
  product_url?: string;
  in_stock: boolean;
  features: string[];
}

export interface DealerData {
  dealer_id: string;
  name: string;
  city: string;
  state?: string;
  phone: string;
  email?: string;
  address?: string;
}

export interface KnowledgeDocument {
  _id?: string;
  doc_id: string;
  chunk_id?: string;
  content: string;
  content_type: ContentType;
  product_data?: ProductData;
  dealer_data?: DealerData;
  title: string;
  metadata: {
    brand_id: string;
    [key: string]: any;
  };
  created_at?: string;
  updated_at?: string;
}

// Response from list_documents API (grouped by job_id/upload)
export interface DocumentSummary {
  doc_id: string;           // job_id for new uploads, doc_id for old documents
  title: string;            // e.g., "380 products uploaded" or legacy product name
  content_type: string;
  chunks_count: number;     // Total chunks in this upload batch
  item_count: number;       // Number of unique products/dealers in this batch
  created_at?: string;
  is_legacy?: boolean;      // True for old documents without job_id
  status?: 'ready' | 'processing' | 'error';
  folder_id?: string | null;
  folder_path?: string;
  path?: string;
}

export interface DocumentPreviewSample {
  chunk_id?: string;
  title?: string;
  content?: string;
  content_type?: string;
  product_data?: ProductData;
  dealer_data?: DealerData;
  metadata?: Record<string, any>;
}

export interface DocumentPreview {
  doc_id: string;
  title: string;
  content_type: string;
  item_count: number;
  chunks_count: number;
  created_at?: string;
  status: 'ready' | 'processing' | 'error';
  samples: DocumentPreviewSample[];
}

export interface UploadDocumentRequest {
  file: File;
  content_type: ContentType;
  product_data?: ProductData;
  dealer_data?: DealerData;
  brand_id: string;
  agent_id?: string;
  folder_id?: string | null;
  folder_path?: string;
}

export interface UploadDocumentResponse {
  success: boolean;
  job_id: string;
  message: string;
  items_count: number;
  status: string;
}

export interface UploadJobStatus {
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
}

export type KnowledgeItemKind = 'folder' | 'document' | 'file';
export type KnowledgeItemStatus = 'ready' | 'processing' | 'error' | 'pending';

export interface KnowledgeFolderSelection {
  id?: string | null;
  path: string;
  name?: string;
}

export interface KnowledgeItem {
  id: string;
  name: string;
  kind: KnowledgeItemKind;
  path: string;
  parent_id?: string | null;
  content_type?: string;
  chunks_count?: number;
  item_count?: number;
  status?: KnowledgeItemStatus;
  created_at?: string;
  updated_at?: string;
  size_bytes?: number;
  source_doc_id?: string;
  metadata?: Record<string, any>;
}

export interface KnowledgeFolderNode {
  id: string | null;
  name: string;
  path: string;
  parent_id?: string | null;
  children?: KnowledgeFolderNode[];
  items?: KnowledgeItem[];
  documents?: DocumentSummary[];
}

export interface KnowledgeTreeResponse {
  root: KnowledgeFolderNode;
  items?: KnowledgeItem[];
  documents?: DocumentSummary[];
}

export interface CreateKnowledgeFolderRequest {
  name: string;
  brand_id?: string;
  parent_id?: string | null;
  parent_path?: string;
}

export interface MoveKnowledgeItemRequest {
  brand_id?: string;
  parent_id?: string | null;
  folder_path?: string;
}

export interface RenameKnowledgeItemRequest {
  brand_id?: string;
  name: string;
}

export interface RetrieveKnowledgeRequest {
  query: string;
  brand_id?: string;
  agent_id?: string;
  folder_id?: string | null;
  folder_path?: string;
  top_k?: number;
  score_threshold?: number;
}

export interface RetrievedKnowledgeChunk {
  id?: string;
  doc_id?: string;
  title?: string;
  content: string;
  score?: number;
  path?: string;
  metadata?: Record<string, any>;
}

export interface RetrieveKnowledgeResponse {
  query: string;
  results: RetrievedKnowledgeChunk[];
}
