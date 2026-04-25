import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, documentApi, Agent, KnowledgeDocument } from '../api/client';

const isDev = process.env.NODE_ENV !== 'production';

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

function getWidgetBaseUrl(): string {
  const runtimeWidgetUrl = window.__APP_CONFIG__?.WIDGET_BASE_URL;
  const envWidgetUrl = process.env.REACT_APP_WIDGET_URL;
  return (runtimeWidgetUrl || envWidgetUrl || 'http://localhost:5174').replace(/\/+$/, '');
}

function buildEmbedCode(widgetBaseUrl: string, agentId: string): string {
  return `<script src="${widgetBaseUrl}/embed.js" data-agent-id="${agentId}" async></script>`;
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadProgress, setUploadProgress] = useState<{ [key: string]: number }>({});
  const [selectedDocumentType, setSelectedDocumentType] = useState<string>('other');
  const [copiedEmbed, setCopiedEmbed] = useState(false);

  useEffect(() => {
    if (id) {
      loadAgentData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

    const fileArray = Array.from(files);
    const newProgress: { [key: string]: number } = {};

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
          const updated = { ...prev };
          Object.keys(updated).forEach(key => {
            if (updated[key] < 90) {
              updated[key] = Math.min(updated[key] + 15, 90);
            }
          });
          return updated;
        });
      }, 300);

      // Upload files
      await documentApi.uploadDocuments(fileArray, {
        agent_id: id,
        document_type: selectedDocumentType,
        category: 'knowledge_base',
      });

      // Complete progress
      clearInterval(progressInterval);
      setUploadProgress(prev => {
        const updated = { ...prev };
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
        const updated = { ...prev };
        Object.keys(updated).forEach(key => {
          updated[key] = -1;
        });
        return updated;
      });
    } finally {
      // Upload finished
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

  isDev && console.log('🔧 AgentDetail rendering with agent:', agent.id, agent.name);
  isDev && console.log('📄 Documents count:', documents.length);

  const widgetBaseUrl = getWidgetBaseUrl();
  const embedCode = buildEmbedCode(widgetBaseUrl, agent.id);

  const handleCopyEmbedCode = async () => {
    try {
      await navigator.clipboard.writeText(embedCode);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = embedCode;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }

    setCopiedEmbed(true);
    window.setTimeout(() => setCopiedEmbed(false), 2000);
  };

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
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${agent.status === 'active'
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

      {/* Embed Widget */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Embed Widget</h2>
            <p className="text-gray-600 mt-1">
              Add this script before the closing body tag on any website.
            </p>
          </div>
          <button
            type="button"
            onClick={handleCopyEmbedCode}
            className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            {copiedEmbed ? 'Copied' : 'Copy Script'}
          </button>
        </div>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-gray-950 p-4 text-sm text-gray-100">
          <code>{embedCode}</code>
        </pre>
        <p className="mt-3 text-sm text-gray-500">
          Widget URL: {widgetBaseUrl}
        </p>
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
                          className={`h-2 rounded-full transition-all duration-300 ${progress === -1
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
                <div key={doc.id || doc.job_id || doc.filename} className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
                  <div className="flex items-center space-x-4">
                    <div className="text-3xl">
                      {getFileTypeIcon(doc.file_type || doc.content_type || 'application/octet-stream', doc.metadata?.document_type)}
                    </div>
                    <div className="flex-1">
                      <div className="font-semibold text-gray-900">{doc.filename}</div>
                      <div className="text-sm text-gray-600">
                        {doc.metadata?.title || 'No title'}
                      </div>
                      <div className="flex items-center space-x-4 mt-1">
                        {doc.file_size && (
                          <span className="text-xs text-gray-500">
                            {(doc.file_size / 1024).toFixed(1)} KB
                          </span>
                        )}
                        {doc.chunks_count && (
                          <span className="text-xs text-gray-500">
                            {doc.chunks_count} chunks
                          </span>
                        )}
                        {doc.metadata?.document_type && (
                          <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                            {DocumentTypeLabels[doc.metadata.document_type as keyof typeof DocumentTypeLabels] || doc.metadata.document_type}
                          </span>
                        )}
                        {doc.embedding_status && (
                          <span className={`px-2 py-1 text-xs rounded-full ${doc.embedding_status === 'completed' ? 'bg-green-100 text-green-800' :
                            doc.embedding_status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                              doc.embedding_status === 'failed' ? 'bg-red-100 text-red-800' :
                                'bg-gray-100 text-gray-800'
                            }`}>
                            {doc.embedding_status}
                          </span>
                        )}
                      </div>
                      {doc.metadata?.tags && doc.metadata.tags.length > 0 && (
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
                      onClick={() => handleDeleteDocument(doc.id || doc.job_id || doc.filename)}
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

      {/* Technical Configuration Section */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-2xl font-semibold text-gray-900">🔧 Technical Configuration</h2>
          <p className="text-gray-600 mt-1">Vector database, embeddings, and storage architecture</p>
        </div>

        <div className="p-6 space-y-6">
          {/* Vector Database Configuration */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">🗄️</span>
              Vector Database
            </h3>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm font-medium text-blue-900">Database:</span>
                  <p className="text-sm text-blue-700 mt-1">MongoDB Atlas Vector Search</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-blue-900">Collection:</span>
                  <p className="text-sm text-blue-700 mt-1"><code className="bg-blue-100 px-2 py-0.5 rounded">knowledge_base</code></p>
                </div>
                <div>
                  <span className="text-sm font-medium text-blue-900">Index Type:</span>
                  <p className="text-sm text-blue-700 mt-1">KNN Vector (Cosine Similarity)</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-blue-900">Index Name:</span>
                  <p className="text-sm text-blue-700 mt-1"><code className="bg-blue-100 px-2 py-0.5 rounded">vector_index</code></p>
                </div>
              </div>
              <div className="pt-2 border-t border-blue-200">
                <span className="text-sm font-medium text-blue-900">Agent Filter:</span>
                <p className="text-sm text-blue-700 mt-1 font-mono">
                  {`{ agent_id: "${agent.id}" }`}
                </p>
              </div>
            </div>
          </div>

          {/* Embeddings Configuration */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">🧬</span>
              Embeddings Model
            </h3>
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm font-medium text-purple-900">Provider:</span>
                  <p className="text-sm text-purple-700 mt-1">
                    {agent.configuration?.rag?.embedding?.provider || 'Voyage AI'}
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-purple-900">Model:</span>
                  <p className="text-sm text-purple-700 mt-1">
                    <code className="bg-purple-100 px-2 py-0.5 rounded">
                      {agent.configuration?.rag?.embedding?.model || 'voyage-large-2-instruct'}
                    </code>
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-purple-900">Dimensions:</span>
                  <p className="text-sm text-purple-700 mt-1">1024 (Voyage Large)</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-purple-900">Similarity:</span>
                  <p className="text-sm text-purple-700 mt-1">Cosine Similarity</p>
                </div>
              </div>
              <div className="pt-2 border-t border-purple-200">
                <span className="text-sm font-medium text-purple-900">API Endpoint:</span>
                <p className="text-sm text-purple-700 mt-1 font-mono text-xs">
                  https://api.voyageai.com/v1/embeddings
                </p>
              </div>
            </div>
          </div>

          {/* Document Storage & Chunking */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">📦</span>
              Document Processing
            </h3>
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm font-medium text-green-900">Chunking Strategy:</span>
                  <p className="text-sm text-green-700 mt-1">
                    {agent.configuration?.rag?.chunking?.strategy || 'Fixed Size with Overlap'}
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-green-900">Chunk Size:</span>
                  <p className="text-sm text-green-700 mt-1">
                    {agent.configuration?.rag?.chunking?.chunk_size || 500} characters
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-green-900">Chunk Overlap:</span>
                  <p className="text-sm text-green-700 mt-1">
                    {agent.configuration?.rag?.chunking?.chunk_overlap || 50} characters
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-green-900">Total Documents:</span>
                  <p className="text-sm text-green-700 mt-1 font-semibold">
                    {documents.length} files
                  </p>
                </div>
              </div>
              <div className="pt-2 border-t border-green-200">
                <span className="text-sm font-medium text-green-900">Total Chunks:</span>
                <p className="text-sm text-green-700 mt-1">
                  {documents.reduce((sum, doc) => sum + (doc.chunks_count || 0), 0)} embedded chunks
                </p>
              </div>
            </div>
          </div>

          {/* RAG Configuration */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">🔍</span>
              Retrieval Configuration
            </h3>
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm font-medium text-orange-900">RAG Enabled:</span>
                  <p className="text-sm text-orange-700 mt-1">
                    {agent.configuration?.rag?.enabled ? '✅ Yes' : '❌ No'}
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-orange-900">Top-K Results:</span>
                  <p className="text-sm text-orange-700 mt-1">
                    {agent.configuration?.rag?.retrieval?.top_k || 5} chunks
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-orange-900">Similarity Threshold:</span>
                  <p className="text-sm text-orange-700 mt-1">
                    {agent.configuration?.rag?.retrieval?.similarity_threshold || 0.7}
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium text-orange-900">Context Window:</span>
                  <p className="text-sm text-orange-700 mt-1">
                    {agent.configuration?.rag?.retrieval?.context_window || 4000} tokens
                  </p>
                </div>
              </div>
              {agent.configuration?.rag?.retrieval?.rerank?.enabled && (
                <div className="pt-2 border-t border-orange-200">
                  <span className="text-sm font-medium text-orange-900">Reranking:</span>
                  <p className="text-sm text-orange-700 mt-1">
                    ✅ Enabled - Top {agent.configuration.rag.retrieval.rerank.top_k || 3} reranked
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Document Details with IDs */}
          {documents.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <span className="text-2xl">📄</span>
                Document Details & IDs
              </h3>
              <div className="bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-100">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                        Filename
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                        Job ID
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                        Chunks
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                        Uploaded
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {documents.map((doc, idx) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm text-gray-900 font-medium">
                          {doc.filename}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 font-mono text-xs">
                          {doc.job_id || doc.id || 'N/A'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {doc.chunks_count || 0} chunks
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {doc.created_at ? new Date(doc.created_at).toLocaleString() : 'N/A'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* MongoDB Query Examples */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">💻</span>
              MongoDB Query Examples
            </h3>
            <div className="space-y-3">
              <div className="bg-gray-900 text-green-400 rounded-lg p-4 font-mono text-xs overflow-x-auto">
                <div className="text-gray-400 mb-2">{'// Find all chunks for this agent'}</div>
                <div>db.knowledge_base.find({'{'} agent_id: "{agent.id}" {'}'})</div>
              </div>
              <div className="bg-gray-900 text-green-400 rounded-lg p-4 font-mono text-xs overflow-x-auto">
                <div className="text-gray-400 mb-2">{'// Count total chunks'}</div>
                <div>db.knowledge_base.countDocuments({'{'} agent_id: "{agent.id}" {'}'})</div>
              </div>
              <div className="bg-gray-900 text-green-400 rounded-lg p-4 font-mono text-xs overflow-x-auto">
                <div className="text-gray-400 mb-2">{'// Vector search example (Atlas Search)'}</div>
                <div>{`db.knowledge_base.aggregate([
  {
    $vectorSearch: {
      index: "vector_index",
      path: "embeddings",
      queryVector: [...], // 1024-dim vector
      numCandidates: 100,
      limit: 5,
      filter: { agent_id: "${agent.id}" }
    }
  }
])`}</div>
              </div>
            </div>
          </div>

          {/* Storage Architecture Diagram */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <span className="text-2xl">🏗️</span>
              Storage Architecture
            </h3>
            <div className="bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg p-6">
              <div className="space-y-4 text-sm">
                <div className="flex items-center gap-3">
                  <div className="bg-blue-500 text-white px-3 py-2 rounded font-semibold text-xs">
                    1. Upload
                  </div>
                  <div className="flex-1 text-gray-700">
                    Documents uploaded via <code className="bg-white px-2 py-0.5 rounded">/api/v1/ingest/documents</code>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="bg-purple-500 text-white px-3 py-2 rounded font-semibold text-xs">
                    2. Chunk
                  </div>
                  <div className="flex-1 text-gray-700">
                    Text extracted and split into {agent.configuration?.rag?.chunking?.chunk_size || 500}-char chunks with {agent.configuration?.rag?.chunking?.chunk_overlap || 50}-char overlap
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="bg-green-500 text-white px-3 py-2 rounded font-semibold text-xs">
                    3. Embed
                  </div>
                  <div className="flex-1 text-gray-700">
                    Each chunk → Voyage AI API → 1024-dimensional vector embedding
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="bg-orange-500 text-white px-3 py-2 rounded font-semibold text-xs">
                    4. Store
                  </div>
                  <div className="flex-1 text-gray-700">
                    Chunks + embeddings stored in MongoDB Atlas <code className="bg-white px-2 py-0.5 rounded">knowledge_base</code> collection
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="bg-red-500 text-white px-3 py-2 rounded font-semibold text-xs">
                    5. Query
                  </div>
                  <div className="flex-1 text-gray-700">
                    User query → embedding → vector search → top-k chunks → LLM context
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
