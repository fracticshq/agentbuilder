import React, { useCallback } from 'react';
import { DocumentArrowUpIcon, DocumentTextIcon, TrashIcon } from '@heroicons/react/24/outline';
import { documentApi } from '../../api/client';

interface StepKnowledgeBaseProps {
  data: {
    documents: Array<{
      id: string;
      filename: string;
      size: number;
      type: string;
      status: 'uploading' | 'processing' | 'ready' | 'error';
      file?: File;
    }>;
    chunking_strategy: string;
    chunk_size: number;
    chunk_overlap: number;
  };
  onChange: (field: string, value: any) => void;
  agentId?: string;
}

const allowedFileTypes = [
  '.pdf', '.docx', '.doc', '.txt', '.md', '.rtf', '.json'
];

const chunkingStrategies = [
  { 
    id: 'semantic', 
    name: 'Semantic Chunking', 
    description: 'Intelligent chunking based on content meaning',
    recommended: true
  },
  { 
    id: 'fixed', 
    name: 'Fixed Size', 
    description: 'Split into chunks of fixed token length'
  },
  { 
    id: 'paragraph', 
    name: 'Paragraph-based', 
    description: 'Split at natural paragraph boundaries'
  },
  { 
    id: 'sentence', 
    name: 'Sentence-based', 
    description: 'Split at sentence boundaries'
  }
];

export default function StepKnowledgeBase({ data, onChange, agentId }: StepKnowledgeBaseProps) {
  const handleFileUpload = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    
    for (const file of files) {
      // Validate file type
      const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!allowedFileTypes.includes(fileExtension)) {
        alert(`File type ${fileExtension} is not supported. Please upload: ${allowedFileTypes.join(', ')}`);
        continue;
      }

      // Validate file size (10MB limit)
      if (file.size > 10 * 1024 * 1024) {
        alert(`File ${file.name} is too large. Maximum size is 10MB.`);
        continue;
      }

      // Add to documents list with file object
      const newDocument = {
        id: Math.random().toString(36).substr(2, 9),
        filename: file.name,
        size: file.size,
        type: fileExtension,
        status: 'ready' as const, // Mark as ready for new uploads
        file: file // Store the actual File object for later upload
      };

      const updatedDocuments = [...data.documents, newDocument];
      onChange('documents', updatedDocuments);

      // Only upload immediately if we have an agentId (editing existing agent)
      if (agentId) {
        try {
          console.log('📤 Uploading file immediately (editing mode):', file.name);
          
          // Update status to uploading
          onChange('documents', updatedDocuments.map(doc => 
            doc.id === newDocument.id ? { ...doc, status: 'uploading' as const } : doc
          ));
          
          const result = await documentApi.uploadDocuments([file], {
            agent_id: agentId,
            category: 'knowledge_base',
            document_type: 'other'
          });

          console.log('✅ Upload result:', result);

          // Update status to processing
          const docsProcessing = updatedDocuments.map(doc => 
            doc.id === newDocument.id 
              ? { ...doc, status: 'processing' as const }
              : doc
          );
          onChange('documents', docsProcessing);

          // Simulate final ready state (in real app, you'd poll the job status)
          setTimeout(() => {
            const finalDocs = docsProcessing.map(doc => 
              doc.id === newDocument.id 
                ? { ...doc, status: 'ready' as const }
                : doc
            );
            onChange('documents', finalDocs);
          }, 2000);

        } catch (error) {
          console.error('❌ Upload failed:', error);
          // Mark as error
          const docsWithError = updatedDocuments.map(doc => 
            doc.id === newDocument.id 
              ? { ...doc, status: 'error' as const }
              : doc
          );
          onChange('documents', docsWithError);
          alert(`Failed to upload ${file.name}: ${(error as Error).message}`);
        }
      } else {
        // For new agents, documents will be uploaded after agent creation
        console.log(`📋 Queued file for upload after agent creation: ${file.name}`);
      }
    }

    // Reset input
    event.target.value = '';
  }, [data.documents, onChange, agentId]);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
  }, []);

  const handleDrop = useCallback(async (event: React.DragEvent) => {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files);
    
    // Process files
    for (const file of files) {
      // Validate file type
      const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!allowedFileTypes.includes(fileExtension)) {
        alert(`File type ${fileExtension} is not supported. Please upload: ${allowedFileTypes.join(', ')}`);
        continue;
      }

      // Validate file size (10MB limit)
      if (file.size > 10 * 1024 * 1024) {
        alert(`File ${file.name} is too large. Maximum size is 10MB.`);
        continue;
      }

      // Add to documents list with file object
      const newDocument = {
        id: Math.random().toString(36).substr(2, 9),
        filename: file.name,
        size: file.size,
        type: fileExtension,
        status: 'uploading' as const,
        file: file
      };

      const updatedDocuments = [...data.documents, newDocument];
      onChange('documents', updatedDocuments);

      // Actually upload the file to the API
      try {
        console.log('Uploading file:', file.name);
        const result = await documentApi.uploadDocuments([file], {
          agent_id: agentId,
          category: 'knowledge_base',
          document_type: 'other'
        });

        console.log('Upload result:', result);

        // Update status to processing
        const docsProcessing = updatedDocuments.map(doc => 
          doc.id === newDocument.id 
            ? { ...doc, status: 'processing' as const }
            : doc
        );
        onChange('documents', docsProcessing);

        // Simulate final ready state
        setTimeout(() => {
          const finalDocs = docsProcessing.map(doc => 
            doc.id === newDocument.id 
              ? { ...doc, status: 'ready' as const }
              : doc
          );
          onChange('documents', finalDocs);
        }, 2000);

      } catch (error) {
        console.error('Upload failed:', error);
        const docsWithError = updatedDocuments.map(doc => 
          doc.id === newDocument.id 
            ? { ...doc, status: 'error' as const }
            : doc
        );
        onChange('documents', docsWithError);
        alert(`Failed to upload ${file.name}: ${(error as Error).message}`);
      }
    }
  }, [data.documents, onChange, agentId]);

  const removeDocument = (documentId: string) => {
    const updatedDocuments = data.documents.filter(doc => doc.id !== documentId);
    onChange('documents', updatedDocuments);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'uploading': return 'text-blue-600 bg-blue-100';
      case 'processing': return 'text-yellow-600 bg-yellow-100';
      case 'ready': return 'text-green-600 bg-green-100';
      case 'error': return 'text-red-600 bg-red-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">Knowledge Base Setup</h3>
        <p className="mt-1 text-sm text-gray-600">
          Upload documents to give your agent specialized knowledge.
        </p>
      </div>

      {/* File Upload Area */}
      <div className="space-y-4">
        <label className="block text-sm font-medium text-gray-700">
          Upload Documents
        </label>
        
        <div
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-primary-400 transition-colors"
        >
          <DocumentArrowUpIcon className="mx-auto h-12 w-12 text-gray-400" />
          <div className="mt-4">
            <label htmlFor="file-upload" className="cursor-pointer">
              <span className="mt-2 block text-sm font-medium text-gray-900">
                Drop files here or click to upload
              </span>
              <span className="mt-1 block text-xs text-gray-500">
                Supported formats: {allowedFileTypes.join(', ')} (Max 10MB per file)
              </span>
              <input
                id="file-upload"
                name="file-upload"
                type="file"
                multiple
                accept={allowedFileTypes.join(',')}
                onChange={handleFileUpload}
                className="sr-only"
              />
            </label>
          </div>
        </div>
      </div>

      {/* Uploaded Documents */}
      {data.documents.length > 0 && (
        <div className="space-y-4">
          {/* Existing Documents from Database */}
          {data.documents.some(doc => !doc.file) && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                <DocumentTextIcon className="h-5 w-5 mr-2 text-blue-500" />
                Existing Documents ({data.documents.filter(doc => !doc.file).length})
                <span className="ml-2 text-xs text-gray-500">(Already uploaded to database)</span>
              </h4>
              <div className="space-y-2 border-l-4 border-blue-300 pl-4">
                {data.documents.filter(doc => !doc.file).map((doc) => (
                  <div key={doc.id} className="flex items-center justify-between p-3 bg-blue-50 rounded-lg border border-blue-200">
                    <div className="flex items-center space-x-3">
                      <DocumentTextIcon className="h-5 w-5 text-blue-600" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {doc.filename}
                          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                            ✓ In Database
                          </span>
                        </p>
                        <p className="text-xs text-gray-500">
                          {formatFileSize(doc.size)} • {doc.type.toUpperCase()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        ✓ Ready
                      </span>
                      <button
                        onClick={() => removeDocument(doc.id)}
                        className="text-gray-400 hover:text-red-500 transition-colors"
                        title="Remove from list (file remains in database)"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Newly Added Documents (Not yet uploaded) */}
          {data.documents.some(doc => doc.file) && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                <DocumentArrowUpIcon className="h-5 w-5 mr-2 text-yellow-500" />
                New Documents ({data.documents.filter(doc => doc.file).length})
                <span className="ml-2 text-xs text-gray-500">(Will be uploaded on save)</span>
              </h4>
              <div className="space-y-2 border-l-4 border-yellow-300 pl-4">
                {data.documents.filter(doc => doc.file).map((doc) => (
                  <div key={doc.id} className="flex items-center justify-between p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                    <div className="flex items-center space-x-3">
                      <DocumentTextIcon className="h-5 w-5 text-yellow-600" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {doc.filename}
                          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                            Queued
                          </span>
                        </p>
                        <p className="text-xs text-gray-500">
                          {formatFileSize(doc.size)} • {doc.type.toUpperCase()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(doc.status)}`}>
                        {doc.status === 'uploading' && '⏳ Uploading...'}
                        {doc.status === 'processing' && '⚙️ Processing...'}
                        {doc.status === 'ready' && '📋 Queued'}
                        {doc.status === 'error' && '❌ Error'}
                      </span>
                      <button
                        onClick={() => removeDocument(doc.id)}
                        className="text-gray-400 hover:text-red-500 transition-colors"
                        title="Remove document"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Chunking Configuration */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label htmlFor="chunking_strategy" className="block text-sm font-medium text-gray-700">
            Chunking Strategy
          </label>
          <select
            id="chunking_strategy"
            value={data.chunking_strategy}
            onChange={(e) => onChange('chunking_strategy', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          >
            <option value="">Select strategy</option>
            {chunkingStrategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.name} {strategy.recommended ? '(Recommended)' : ''}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-gray-500">
            How documents are split into searchable chunks
          </p>
        </div>

        <div>
          <label htmlFor="chunk_size" className="block text-sm font-medium text-gray-700">
            Chunk Size (tokens)
          </label>
          <input
            type="number"
            id="chunk_size"
            min="100"
            max="1000"
            step="50"
            value={data.chunk_size}
            onChange={(e) => onChange('chunk_size', parseInt(e.target.value))}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Recommended: 300-500 tokens
          </p>
        </div>

        <div>
          <label htmlFor="chunk_overlap" className="block text-sm font-medium text-gray-700">
            Chunk Overlap (tokens)
          </label>
          <input
            type="number"
            id="chunk_overlap"
            min="0"
            max="200"
            step="10"
            value={data.chunk_overlap}
            onChange={(e) => onChange('chunk_overlap', parseInt(e.target.value))}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Recommended: 50-100 tokens
          </p>
        </div>
      </div>

      {/* Selected Strategy Description */}
      {data.chunking_strategy && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-blue-800">
                {chunkingStrategies.find(s => s.id === data.chunking_strategy)?.name}
              </h3>
              <div className="mt-2 text-sm text-blue-700">
                <p>{chunkingStrategies.find(s => s.id === data.chunking_strategy)?.description}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-yellow-800">
              Knowledge Base Tips
            </h3>
            <div className="mt-2 text-sm text-yellow-700">
              <ul className="list-disc pl-5 space-y-1">
                <li>Upload high-quality, relevant documents for best results</li>
                <li>Remove sensitive or confidential information before uploading</li>
                <li>Well-structured documents (headings, lists) work better</li>
                <li>Start with 5-10 documents and add more as needed</li>
                <li>Test your agent after uploading to verify knowledge integration</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
