import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, documentApi, Agent, KnowledgeDocument } from '../api/client';

const DocumentTypeLabels = {
  product_data: 'Product Data',
  category_data: 'Category Data', 
  faq_data: 'FAQ Data',
  dealer_data: 'Dealer Data',
  area_representative_data: 'Sales Rep Data',
  office_data: 'Office Data',
  manual: 'Manual',
  policy: 'Policy',
  other: 'Other',
};

const DocumentTypeIcons = {
  product_data: '🛁',
  category_data: '📂',
  faq_data: '❓',
  dealer_data: '🏪',
  area_representative_data: '👤',
  office_data: '🏢',
  manual: '📖',
  policy: '📋',
  other: '📄',
};

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{[key: string]: number}>({});
  const [selectedDocumentType, setSelectedDocumentType] = useState<string>('other');

  useEffect(() => {
    if (id) {
      loadAgentData();
    }
  }, [id]);

  const loadAgentData = async () => {
    if (!id) return;
    
    setLoading(true);
    try {
      const [agentData, docsData] = await Promise.all([
        api.getAgent(id),
        documentApi.getKnowledgeDocuments(id),
      ]);
      setAgent(agentData);
      setDocuments(docsData);
    } catch (error) {
      console.error('Failed to load agent data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (files: FileList) => {
    if (!id || !files.length) return;

    setUploading(true);
    const fileArray = Array.from(files);
    const newProgress: {[key: string]: number} = {};

    try {
      // Initialize progress tracking
      fileArray.forEach((file) => {
        const fileKey = `${file.name}-${Date.now()}`;
        newProgress[fileKey] = 0;
      });
      setUploadProgress(newProgress);

      // Simulate progress for demo (replace with real upload progress)
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => {
          const updated = {...prev};
          Object.keys(updated).forEach(key => {
            if (updated[key] < 90) {
              updated[key] = Math.min(updated[key] + 15, 90);
            }
          });
          return updated;
        });
      }, 300);

      // Upload files
      const uploadResult = await documentApi.uploadDocuments(fileArray, {
        agent_id: id,
        document_type: selectedDocumentType,
        category: 'knowledge_base',
      });

      // Complete progress
      clearInterval(progressInterval);
      setUploadProgress(prev => {
        const updated = {...prev};
        Object.keys(updated).forEach(key => {
          updated[key] = 100;
        });
        return updated;
      });

      // Refresh documents list
      await loadAgentData();

      // Clear progress after delay
      setTimeout(() => {
        setUploadProgress({});
      }, 2000);

    } catch (error) {
      console.error('Failed to upload files:', error);
      // Set error state
      setUploadProgress(prev => {
        const updated = {...prev};
        Object.keys(updated).forEach(key => {
          updated[key] = -1;
        });
        return updated;
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!window.confirm('Are you sure you want to delete this document?')) return;
    
    try {
      await documentApi.deleteDocument(docId);
      setDocuments(prev => prev.filter(doc => doc.id !== docId));
    } catch (error) {
      console.error('Failed to delete document:', error);
    }
  };

  const getFileTypeIcon = (fileType: string, documentType?: string) => {
    if (documentType && DocumentTypeIcons[documentType as keyof typeof DocumentTypeIcons]) {
      return DocumentTypeIcons[documentType as keyof typeof DocumentTypeIcons];
    }
    
    switch (fileType) {
      case 'application/json': return '📊';
      case 'application/pdf': return '📄';
      case 'text/markdown': return '📝';
      case 'text/html': return '🌐';
      case 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': return '📄';
      default: return '📄';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="text-center py-12">
        <h1 className="text-2xl font-bold text-gray-900">Agent Not Found</h1>
        <p className="mt-2 text-gray-600">The agent you're looking for doesn't exist.</p>
        <Link to="/agents" className="mt-4 inline-block bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
          Back to Agents
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex" aria-label="Breadcrumb">
        <ol className="flex items-center space-x-4">
          <li>
            <Link to="/agents" className="text-gray-400 hover:text-gray-500">Agents</Link>
          </li>
          <li>
            <div className="flex items-center">
              <span className="text-gray-400 mx-2">/</span>
              <span className="text-gray-700 font-medium">{agent.name}</span>
            </div>
          </li>
        </ol>
      </nav>

      {/* Agent Header */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex justify-between items-start">
          <div className="flex-1">
            <h1 className="text-3xl font-bold text-gray-900">{agent.name}</h1>
            <p className="text-lg text-gray-600 mt-2">{agent.description}</p>
            <div className="flex items-center space-x-6 mt-4">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                agent.status === 'active' 
                  ? 'bg-green-100 text-green-800' 
                  : agent.status === 'draft'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {agent.status.charAt(0).toUpperCase() + agent.status.slice(1)}
              </span>
              <span className="text-sm text-gray-500">
                Created: {new Date(agent.created_at).toLocaleDateString()}
              </span>
              <span className="text-sm text-gray-500">
                Documents: {documents.length}
              </span>
            </div>
          </div>
          <div className="flex space-x-3">
            <button className="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition-colors">
              🧪 Test Agent
            </button>
            <Link 
              to={`/agents/${id}/edit`}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
            >
              ✏️ Edit Agent
            </Link>
          </div>
        </div>
      </div>

      {/* Knowledge Base Section */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-2xl font-semibold text-gray-900">Knowledge Base</h2>
          <p className="text-gray-600 mt-1">Upload JSON files and documents to train your Essco agent</p>
        </div>

        {/* Upload Section */}
        <div className="p-6 border-b border-gray-200">
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Document Type
            </label>
            <select
              value={selectedDocumentType}
              onChange={(e) => setSelectedDocumentType(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {Object.entries(DocumentTypeLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div
            className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-blue-400 hover:bg-blue-50 transition-colors cursor-pointer"
            onDrop={(e) => {
              e.preventDefault();
              const files = e.dataTransfer.files;
              if (files.length > 0) {
                handleFileUpload(files);
              }
            }}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.multiple = true;
              input.accept = '.json,.pdf,.md,.txt,.docx,.html';
              input.onchange = (e) => {
                const files = (e.target as HTMLInputElement).files;
                if (files) {
                  handleFileUpload(files);
                }
              };
              input.click();
            }}
          >
            <div className="space-y-3">
              <div className="text-5xl">📊</div>
              <div className="text-xl font-semibold text-gray-900">
                Drop your Essco JSON files here
              </div>
              <div className="text-sm text-gray-500 max-w-md mx-auto">
                Upload product_data.json, essco_faq.json, dealers_data.json, and other knowledge files.
                Also supports PDF, Markdown, Text, DOCX, HTML files.
              </div>
              <div className="text-xs text-gray-400">
                Click to browse or drag and drop files
              </div>
            </div>
          </div>

          {/* Upload Progress */}
          {Object.keys(uploadProgress).length > 0 && (
            <div className="mt-6 space-y-3">
              <h4 className="text-sm font-medium text-gray-900">Upload Progress</h4>
              {Object.entries(uploadProgress).map(([fileKey, progress]) => {
                const fileName = fileKey.split('-').slice(0, -1).join('-');
                return (
                  <div key={fileKey} className="flex items-center space-x-3">
                    <div className="flex-1">
                      <div className="text-sm font-medium text-gray-700">{fileName}</div>
                      <div className="w-full bg-gray-200 rounded-full h-2 mt-1">
                        <div
                          className={`h-2 rounded-full transition-all duration-300 ${
                            progress === -1 
                              ? 'bg-red-500' 
                              : progress === 100 
                              ? 'bg-green-500' 
                              : 'bg-blue-500'
                          }`}
                          style={{ width: `${Math.max(0, progress)}%` }}
                        />
                      </div>
                    </div>
                    <div className="text-sm font-medium">
                      {progress === -1 ? (
                        <span className="text-red-600">❌ Error</span>
                      ) : progress === 100 ? (
                        <span className="text-green-600">✅ Complete</span>
                      ) : (
                        <span className="text-blue-600">{progress}%</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Documents List */}
        <div className="p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-semibold text-gray-900">
              Uploaded Documents ({documents.length})
            </h3>
            {documents.length > 0 && (
              <button 
                onClick={loadAgentData}
                className="text-blue-600 hover:text-blue-800 text-sm font-medium"
              >
                🔄 Refresh
              </button>
            )}
          </div>
          
          {documents.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <div className="text-4xl mb-4">📂</div>
              <div className="text-lg font-medium">No documents uploaded yet</div>
              <div className="text-sm">Upload your first Essco JSON file to get started</div>
            </div>
          ) : (
            <div className="grid gap-4">
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
                  <div className="flex items-center space-x-4">
                    <div className="text-3xl">
                      {getFileTypeIcon(doc.file_type, doc.metadata.document_type)}
                    </div>
                    <div className="flex-1">
                      <div className="font-semibold text-gray-900">{doc.filename}</div>
                      <div className="text-sm text-gray-600">
                        {doc.metadata.title || 'No title'}
                      </div>
                      <div className="flex items-center space-x-4 mt-1">
                        <span className="text-xs text-gray-500">
                          {(doc.file_size / 1024).toFixed(1)} KB
                        </span>
                        {doc.metadata.document_type && (
                          <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                            {DocumentTypeLabels[doc.metadata.document_type as keyof typeof DocumentTypeLabels] || doc.metadata.document_type}
                          </span>
                        )}
                        <span className={`px-2 py-1 text-xs rounded-full ${
                          doc.embedding_status === 'completed' ? 'bg-green-100 text-green-800' :
                          doc.embedding_status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                          doc.embedding_status === 'failed' ? 'bg-red-100 text-red-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {doc.embedding_status}
                        </span>
                      </div>
                      {doc.metadata.tags && doc.metadata.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {doc.metadata.tags.map((tag, index) => (
                            <span key={index} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button 
                      className="text-blue-600 hover:text-blue-800 text-sm font-medium px-3 py-1 rounded border border-blue-200 hover:bg-blue-50"
                      onClick={() => {
                        // TODO: Implement document preview
                        alert(`Preview functionality for ${doc.filename} coming soon!`);
                      }}
                    >
                      👁️ Preview
                    </button>
                    <button 
                      className="text-red-600 hover:text-red-800 text-sm font-medium px-3 py-1 rounded border border-red-200 hover:bg-red-50"
                      onClick={() => handleDeleteDocument(doc.id)}
                    >
                      🗑️ Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* System Prompt Section */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">System Prompt</h3>
        <div className="bg-gray-50 rounded-lg p-4 max-h-64 overflow-y-auto">
          <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono">
            {agent.system_prompt}
          </pre>
        </div>
      </div>
    </div>
  );
}
