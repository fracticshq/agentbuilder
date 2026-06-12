import React, { useState } from 'react';
import JsonUpload from './JsonUpload';
import ContentTypeSelector from './ContentTypeSelector';
import JsonFieldMapper from './JsonFieldMapper';
import DocumentFileUpload from './DocumentFileUpload';
import { knowledgeApi } from '../../api/knowledge';
import type { ContentType, KnowledgeFolderSelection, UploadDocumentResponse } from '../../types/knowledge';

const isDev = process.env.NODE_ENV !== 'production';
type StructuredContentType = Exclude<ContentType, 'document'>;

interface WizardStep {
  id: number;
  title: string;
  description: string;
}

const steps: WizardStep[] = [
  { id: 1, title: 'Content Type', description: 'What type of data are you uploading?' },
  { id: 2, title: 'Upload Data', description: 'Upload documents or structured JSON data' },
  { id: 3, title: 'Map Fields', description: 'Map your fields to our schema' },
  { id: 4, title: 'Review & Upload', description: 'Preview and confirm upload' },
];

interface DocumentUploadWizardProps {
  brandId: string;
  agentId?: string;
  selectedFolder?: KnowledgeFolderSelection;
  onComplete: (response: UploadDocumentResponse) => void;
  onCancel: () => void;
}

export default function DocumentUploadWizard({
  brandId,
  agentId,
  selectedFolder,
  onComplete,
  onCancel,
}: DocumentUploadWizardProps) {
  const [uploadMode, setUploadMode] = useState<'document' | 'structured'>('document');
  const [currentStep, setCurrentStep] = useState(2);
  const [contentType, setContentType] = useState<ContentType | null>(null);
  const [jsonData, setJsonData] = useState<any[]>([]);
  const [mappedData, setMappedData] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Unused handlers removed

  const selectUploadMode = (mode: 'document' | 'structured') => {
    setUploadMode(mode);
    setCurrentStep(mode === 'document' ? 2 : 1);
    setContentType(null);
    setJsonData([]);
    setMappedData([]);
    setUploadError(null);
  };

  const handleContentTypeSelect = (type: ContentType) => {
    setContentType(type);
    setCurrentStep(2); // Auto-advance to JSON upload
  };

  const handleJsonUpload = (data: any[]) => {
    setJsonData(data);
    // Only go to field mapper for product/dealer which need structured data
    if (contentType === 'product' || contentType === 'dealer') {
      setCurrentStep(3); // Auto-advance to field mapper
    } else {
      // For other types (faq, office, category, guide), skip mapper and go straight to review
      setMappedData(data);
      setCurrentStep(4);
    }
  };

  const handleMappingComplete = (data: any[]) => {
    setMappedData(data);
    setCurrentStep(4); // Auto-advance to review
  };

  const handleUpload = async () => {
    if (!contentType || mappedData.length === 0) {
      console.error('[Upload] Validation failed:', { contentType, mappedDataLength: mappedData.length });
      setUploadError('Missing required data');
      return;
    }

    // Validate required fields based on content type
    const firstItem = mappedData[0];
    let missingFields: string[] = [];
    
    if (contentType === 'product') {
      const requiredFields = ['sku', 'name', 'price', 'currency', 'category'];
      missingFields = requiredFields.filter(field => !firstItem[field]);
      
      // Check if optional fields need defaults
      if (firstItem.in_stock === undefined) {
        console.warn('[Upload] in_stock missing, will default to true');
      }
      if (!firstItem.features || !Array.isArray(firstItem.features)) {
        console.warn('[Upload] features missing, will default to empty array');
      }
    } else if (contentType === 'dealer') {
      const requiredFields = ['dealer_id', 'name', 'city', 'phone'];
      missingFields = requiredFields.filter(field => !firstItem[field]);
    }
    
    if (missingFields.length > 0) {
      const error = `Validation error. Missing required fields: ${missingFields.join(', ')}`;
      console.error('[Upload] Field validation failed:', { missingFields, firstItem });
      setUploadError(error);
      return;
    }

    isDev && console.log('[Upload] Starting upload:', {
      contentType,
      itemCount: mappedData.length,
      brandId,
      firstItem: mappedData[0],
    });

    setUploading(true);
    setUploadError(null);

    try {
      // Add defaults for optional fields
      const itemsWithDefaults = mappedData.map(item => {
        if (contentType === 'product') {
          return {
            ...item,
            in_stock: item.in_stock !== undefined ? item.in_stock : true,
            features: Array.isArray(item.features) ? item.features : [],
            image_url: item.image_url || null,
            product_url: item.product_url || null,
          };
        }
        return item;
      });

      isDev && console.log('[Upload] Calling API with data:', {
        content_type: contentType,
        items: itemsWithDefaults,
        brand_id: brandId,
        firstItem: itemsWithDefaults[0],
      });

      const response = await knowledgeApi.bulkUploadJson({
        content_type: contentType as 'product' | 'dealer',
        items: itemsWithDefaults,
        brand_id: brandId,
        folder_id: selectedFolder?.id || undefined,
        folder_path: selectedFolder?.path || '/',
      });

      isDev && console.log('[Upload] API response received:', response);
      onComplete(response);
    } catch (error: any) {
      console.error('Upload failed:', error);
      
      // Extract detailed error message from backend
      let errorMessage = 'Upload failed';
      
      if (error.response?.data?.detail) {
        // Backend returned detailed error (e.g., "Item 1: Missing required product fields: currency")
        errorMessage = error.response.data.detail;
      } else if (error.message) {
        errorMessage = error.message;
      }
      
      setUploadError(errorMessage);
      
      // Show detailed alert with formatting
      alert(
        `Upload failed\n\n` +
        `Error: ${errorMessage}\n\n` +
        `Tips:\n` +
        `- Check that all required fields are mapped\n` +
        `- Products need: sku, name, price, currency, category\n` +
        `- Dealers need: dealer_id, name, city, phone\n` +
        `- Use "Fixed Value" mode for missing fields like currency`
      );
    } finally {
      setUploading(false);
    }
  };

  const renderStepContent = () => {
    if (uploadMode === 'document') {
      return (
        <div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">
            Upload Document
          </h2>
          <p className="text-sm text-gray-600 mb-6">
            Add PDF, DOCX, TXT, Markdown, HTML, or CSV files to <span className="font-mono">{selectedFolder?.path || '/'}</span> for retrieval.
          </p>
          <DocumentFileUpload
            brandId={brandId}
            agentId={agentId}
            selectedFolder={selectedFolder}
            onComplete={onComplete}
            onBack={() => selectUploadMode('structured')}
          />
        </div>
      );
    }

    switch (currentStep) {
      case 1:
        return (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              Select Structured Content Type
            </h2>
            <p className="text-sm text-gray-600 mb-6">
              Choose the structured data schema for JSON imports.
            </p>
            <ContentTypeSelector
              selectedType={contentType}
              onSelect={handleContentTypeSelect}
            />
          </div>
        );

      case 2:
        return (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              Upload Structured Data
            </h2>
            <p className="text-sm text-gray-600 mb-6">
              Upload a JSON file, paste JSON, or import from a supported catalog source.
              {(contentType === 'product' || contentType === 'dealer') && 
                " We'll auto-detect and map the fields in the next step."}
            </p>
            <JsonUpload
              contentType={contentType as StructuredContentType}
              onUpload={handleJsonUpload}
              onBack={() => setCurrentStep(1)}
              brandId={brandId}
            />
          </div>
        );

      case 3:
        return (
          <div>
            <JsonFieldMapper
              jsonData={jsonData}
              contentType={contentType as 'product' | 'dealer'}
              onMappingComplete={handleMappingComplete}
              onBack={() => setCurrentStep(2)}
            />
          </div>
        );

      // Step 4: Review & Upload
      case 4:
        isDev && console.log('[Review Step] Rendering review with:', {
          contentType,
          mappedDataLength: mappedData.length,
          brandId,
          uploading
        });
        
        return (
          <div>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">
              Review & Upload
            </h2>
            <p className="text-gray-600 mb-6">
              Review your data before uploading to the knowledge base.
            </p>

            {/* Summary */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
              <h3 className="text-sm font-semibold text-blue-900 mb-3">Upload Summary</h3>
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-blue-700 font-medium">Content Type:</dt>
                  <dd className="text-blue-900">{contentType}</dd>
                </div>
                <div>
                  <dt className="text-blue-700 font-medium">Total Items:</dt>
                  <dd className="text-blue-900">{mappedData.length}</dd>
                </div>
                <div>
                  <dt className="text-blue-700 font-medium">Brand ID:</dt>
                  <dd className="text-blue-900 font-mono text-xs">{brandId}</dd>
                </div>
                <div>
                  <dt className="text-blue-700 font-medium">Folder:</dt>
                  <dd className="text-blue-900 font-mono text-xs">{selectedFolder?.path || '/'}</dd>
                </div>
                <div>
                  <dt className="text-blue-700 font-medium">Fields Mapped:</dt>
                  <dd className="text-blue-900">
                    {mappedData.length > 0 ? Object.keys(mappedData[0]).length : 0}
                  </dd>
                </div>
              </dl>
            </div>

            {/* Preview */}
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">
                Preview (First 3 Items)
              </h3>
              <div className="space-y-3">
                {mappedData.slice(0, 3).map((item, idx) => (
                  <div
                    key={idx}
                    className="bg-gray-50 border border-gray-200 rounded-lg p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-gray-500">
                        Item {idx + 1}
                      </span>
                      {contentType === 'product' && item.sku && (
                        <span className="text-xs font-mono bg-gray-200 px-2 py-1 rounded">
                          {item.sku}
                        </span>
                      )}
                    </div>
                    <div className="text-xs font-mono text-gray-700 whitespace-pre-wrap">
                      {JSON.stringify(item, null, 2)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Error Display */}
            {uploadError && (
              <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-sm text-red-800">
                  <strong>Error:</strong> {uploadError}
                </p>
              </div>
            )}

            {/* Upload Button */}
            <div className="flex justify-between items-center pt-6 border-t border-gray-200">
              <button
                onClick={() => setCurrentStep(3)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
              >
                ← Back to Mapping
              </button>
              <button
                onClick={() => {
                  isDev && console.log('[Upload Button] Clicked! mappedData:', mappedData.length, 'items');
                  handleUpload();
                }}
                disabled={uploading}
                className={`px-6 py-2 text-sm font-medium text-white rounded-md ${
                  uploading
                    ? 'bg-gray-400 cursor-not-allowed'
                    : 'bg-green-600 hover:bg-green-700'
                }`}
              >
                {uploading ? 'Uploading...' : `Upload ${mappedData.length} Items →`}
              </button>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-8">
      {/* Progress Steps */}
      <div className="mb-8">
        <div className="mb-6 border-b border-gray-200">
          <nav className="-mb-px flex gap-6" aria-label="Upload type">
            <button
              type="button"
              onClick={() => selectUploadMode('document')}
              className={`whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium ${
                uploadMode === 'document'
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              Documents
            </button>
            <button
              type="button"
              onClick={() => selectUploadMode('structured')}
              className={`whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium ${
                uploadMode === 'structured'
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              Structured JSON
            </button>
          </nav>
        </div>
        <nav aria-label="Progress">
          <ol className="flex items-center">
            {(uploadMode === 'document' ? steps.slice(1, 2) : steps).map((step, idx, visibleSteps) => (
              <li
                key={step.id}
                className={`relative ${
                  idx !== visibleSteps.length - 1 ? 'flex-1 pr-8' : ''
                }`}
              >
                {/* Connector Line */}
                {idx !== visibleSteps.length - 1 && (
                  <div
                    className={`absolute top-4 left-4 -ml-px mt-0.5 h-0.5 w-full ${
                      currentStep > step.id ? 'bg-primary-600' : 'bg-gray-300'
                    }`}
                  />
                )}

                {/* Step Circle */}
                <div className="group relative flex items-start">
                  <span className="flex h-9 items-center">
                    <span
                      className={`relative z-10 flex h-8 w-8 items-center justify-center rounded-full ${
                        currentStep > step.id
                          ? 'bg-primary-600'
                          : currentStep === step.id
                          ? 'border-2 border-primary-600 bg-white'
                          : 'border-2 border-gray-300 bg-white'
                      }`}
                    >
                      {currentStep > step.id ? (
                        <svg
                          className="h-5 w-5 text-white"
                          fill="currentColor"
                          viewBox="0 0 20 20"
                        >
                          <path
                            fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                      ) : (
                        <span
                          className={`h-2.5 w-2.5 rounded-full ${
                            currentStep === step.id
                              ? 'bg-primary-600'
                              : 'bg-transparent'
                          }`}
                        />
                      )}
                    </span>
                  </span>
                  <span className="ml-4 flex min-w-0 flex-col">
                    <span
                      className={`text-sm font-medium ${
                        currentStep >= step.id
                          ? 'text-primary-600'
                          : 'text-gray-500'
                      }`}
                    >
                      {step.title}
                    </span>
                    <span className="text-xs text-gray-500">
                      {step.description}
                    </span>
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </nav>
      </div>

      {/* Step Content */}
      <div className="min-h-[400px]">{renderStepContent()}</div>

      {/* Cancel Button (always visible) */}
      <div className="mt-8 pt-6 border-t border-gray-200">
        <button
          onClick={onCancel}
          className="text-sm text-gray-600 hover:text-gray-900"
        >
          Cancel Upload
        </button>
      </div>
    </div>
  );
}
