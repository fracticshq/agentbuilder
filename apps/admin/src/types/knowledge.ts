// TypeScript types for Knowledge Base documents

export type ContentType = 'product' | 'dealer' | 'faq' | 'office' | 'category' | 'guide';

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
}

export interface UploadDocumentRequest {
  file: File;
  content_type: ContentType;
  product_data?: ProductData;
  dealer_data?: DealerData;
  brand_id: string;
}

export interface UploadDocumentResponse {
  success: boolean;
  job_id: string;
  message: string;
  items_count: number;
  status: string;
}
