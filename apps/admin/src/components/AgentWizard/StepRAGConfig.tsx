import React from 'react';

interface StepRAGConfigProps {
  data: {
    rag_enabled: boolean;
    embedding_provider: string;
    embedding_model: string;
    top_k: number;
    similarity_threshold: number;
    rerank_enabled: boolean;
    rerank_top_k: number;
    context_window: number;
  };
  onChange: (field: string, value: string | number | boolean) => void;
}

const embeddingProviders = [
  {
    id: 'voyage',
    name: 'Voyage AI',
    models: [
      { id: 'voyage-large-2', name: 'Voyage Large 2', description: 'Best performance' },
      { id: 'voyage-code-2', name: 'Voyage Code 2', description: 'Optimized for code' },
      { id: 'voyage-2', name: 'Voyage 2', description: 'Balanced performance' },
    ]
  },
  {
    id: 'openai',
    name: 'OpenAI',
    models: [
      { id: 'text-embedding-3-large', name: 'Text Embedding 3 Large', description: 'Highest quality' },
      { id: 'text-embedding-3-small', name: 'Text Embedding 3 Small', description: 'Good performance, lower cost' },
      { id: 'text-embedding-ada-002', name: 'Ada 002', description: 'Legacy model' },
    ]
  },
  {
    id: 'cohere',
    name: 'Cohere',
    models: [
      { id: 'embed-english-v3.0', name: 'Embed English v3.0', description: 'Latest English model' },
      { id: 'embed-multilingual-v3.0', name: 'Embed Multilingual v3.0', description: 'Supports multiple languages' },
    ]
  }
];

export default function StepRAGConfig({ data, onChange }: StepRAGConfigProps) {
  const selectedProvider = embeddingProviders.find(p => p.id === data.embedding_provider);
  const availableModels = selectedProvider?.models || [];

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">RAG Configuration</h3>
        <p className="mt-1 text-sm text-gray-600">
          Configure how your agent retrieves and uses knowledge from documents.
        </p>
      </div>

      {/* Enable RAG */}
      <div className="flex items-center">
        <input
          id="rag_enabled"
          type="checkbox"
          checked={data.rag_enabled}
          onChange={(e) => onChange('rag_enabled', e.target.checked)}
          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
        />
        <label htmlFor="rag_enabled" className="ml-2 block text-sm text-gray-900">
          Enable Retrieval-Augmented Generation (RAG)
        </label>
      </div>

      {data.rag_enabled && (
        <>
          {/* Embedding Configuration */}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <label htmlFor="embedding_provider" className="block text-sm font-medium text-gray-700">
                Embedding Provider *
              </label>
              <select
                id="embedding_provider"
                value={data.embedding_provider}
                onChange={(e) => {
                  onChange('embedding_provider', e.target.value);
                  onChange('embedding_model', ''); // Reset model when provider changes
                }}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                required
              >
                <option value="">Select provider</option>
                {embeddingProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="embedding_model" className="block text-sm font-medium text-gray-700">
                Embedding Model *
              </label>
              <select
                id="embedding_model"
                value={data.embedding_model}
                onChange={(e) => onChange('embedding_model', e.target.value)}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                disabled={!data.embedding_provider}
                required
              >
                <option value="">Select model</option>
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} - {model.description}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Retrieval Parameters */}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label htmlFor="top_k" className="block text-sm font-medium text-gray-700">
                Top K Results
              </label>
              <input
                type="number"
                id="top_k"
                min="1"
                max="20"
                value={data.top_k}
                onChange={(e) => onChange('top_k', parseInt(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                Number of relevant chunks to retrieve (1-20)
              </p>
            </div>

            <div>
              <label htmlFor="similarity_threshold" className="block text-sm font-medium text-gray-700">
                Similarity Threshold
              </label>
              <div className="mt-1">
                <input
                  type="range"
                  id="similarity_threshold"
                  min="0"
                  max="1"
                  step="0.05"
                  value={data.similarity_threshold}
                  onChange={(e) => onChange('similarity_threshold', parseFloat(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>Loose (0)</span>
                  <span className="font-medium">{data.similarity_threshold}</span>
                  <span>Strict (1)</span>
                </div>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Minimum similarity score for relevant results
              </p>
            </div>

            <div>
              <label htmlFor="context_window" className="block text-sm font-medium text-gray-700">
                Context Window
              </label>
              <input
                type="number"
                id="context_window"
                min="500"
                max="4000"
                step="100"
                value={data.context_window}
                onChange={(e) => onChange('context_window', parseInt(e.target.value))}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                Maximum tokens for retrieved context
              </p>
            </div>
          </div>

          {/* Reranking Configuration */}
          <div className="space-y-4">
            <div className="flex items-center">
              <input
                id="rerank_enabled"
                type="checkbox"
                checked={data.rerank_enabled}
                onChange={(e) => onChange('rerank_enabled', e.target.checked)}
                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
              />
              <label htmlFor="rerank_enabled" className="ml-2 block text-sm text-gray-900">
                Enable result reranking for better relevance
              </label>
            </div>

            {data.rerank_enabled && (
              <div className="ml-6">
                <label htmlFor="rerank_top_k" className="block text-sm font-medium text-gray-700">
                  Rerank Top K
                </label>
                <input
                  type="number"
                  id="rerank_top_k"
                  min="1"
                  max={Math.min(data.top_k, 10)}
                  value={data.rerank_top_k}
                  onChange={(e) => onChange('rerank_top_k', parseInt(e.target.value))}
                  className="mt-1 block w-32 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Number of results to rerank (max {Math.min(data.top_k, 10)})
                </p>
              </div>
            )}
          </div>

          {/* Performance Recommendations */}
          <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-blue-800">
                  Recommended Settings
                </h3>
                <div className="mt-2 text-sm text-blue-700">
                  <ul className="list-disc pl-5 space-y-1">
                    <li><strong>Top K:</strong> Start with 5-7 results for most use cases</li>
                    <li><strong>Similarity Threshold:</strong> 0.7-0.8 for balanced relevance</li>
                    <li><strong>Context Window:</strong> 2000-3000 tokens for comprehensive context</li>
                    <li><strong>Reranking:</strong> Enable for better accuracy with slight latency increase</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {/* Quality vs Performance Trade-offs */}
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-yellow-800">
                  Performance Considerations
                </h3>
                <div className="mt-2 text-sm text-yellow-700">
                  <ul className="list-disc pl-5 space-y-1">
                    <li>Higher Top K = More context but slower responses</li>
                    <li>Lower similarity threshold = More results but less precision</li>
                    <li>Reranking improves quality but adds 100-200ms latency</li>
                    <li>Larger context windows increase LLM costs</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {!data.rag_enabled && (
        <div className="bg-gray-50 border border-gray-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-gray-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-gray-800">
                RAG Disabled
              </h3>
              <div className="mt-2 text-sm text-gray-700">
                <p>
                  Your agent will rely only on its training data and system prompt. 
                  Enable RAG to give your agent access to uploaded documents and specialized knowledge.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
