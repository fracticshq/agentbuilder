import React, { useState } from 'react';
import { CheckCircleIcon, ExclamationTriangleIcon, ClipboardDocumentIcon } from '@heroicons/react/24/outline';

interface StepReviewProps {
  data: any;
  onTest: () => void;
  onDeploy: () => void;
  isDeploying: boolean;
  brands: Array<{ id: string; name: string }>;
  agentId?: string; // Add agentId prop
}

export default function StepReview({ data, onTest, onDeploy, isDeploying, brands, agentId }: StepReviewProps) {
  const [showYaml, setShowYaml] = useState(false);
  const [testMessage, setTestMessage] = useState('');
  const [testResponse, setTestResponse] = useState('');
  const [isTestLoading, setIsTestLoading] = useState(false);

  const selectedBrand = brands.find(b => b.id === data.brand_id);

  // Generate YAML configuration
  const generateYAML = () => {
    const config = {
      agent: {
        name: data.name,
        description: data.description,
        brand_id: data.brand_id,
        version: "1.0.0"
      },
      llm: {
        provider: data.provider,
        model: data.model,
        temperature: data.temperature,
        max_tokens: data.max_tokens,
        top_p: data.top_p,
        frequency_penalty: data.frequency_penalty,
        presence_penalty: data.presence_penalty
      },
      system_prompt: data.system_prompt,
      personality: {
        traits: data.personality_traits || [],
        communication_style: data.communication_style,
        response_format: data.response_format
      },
      rag: data.rag_enabled ? {
        enabled: true,
        embedding: {
          provider: data.embedding_provider,
          model: data.embedding_model
        },
        retrieval: {
          top_k: data.top_k,
          similarity_threshold: data.similarity_threshold,
          context_window: data.context_window,
          rerank: {
            enabled: data.rerank_enabled,
            top_k: data.rerank_top_k
          }
        },
        chunking: {
          strategy: data.chunking_strategy,
          chunk_size: data.chunk_size,
          chunk_overlap: data.chunk_overlap
        }
      } : { enabled: false },
      features: {
        websockets: data.websockets,
        file_upload: data.file_upload ? {
          enabled: true,
          allowed_types: data.allowed_file_types || [],
          max_size_mb: data.max_file_size
        } : { enabled: false },
        conversation_memory: data.conversation_memory,
        typing_indicators: data.typing_indicators,
        response_streaming: data.response_streaming
      },
      security: {
        rate_limiting: data.rate_limiting,
        content_filtering: data.content_filtering,
        session_timeout_minutes: data.session_timeout,
        max_conversation_length: data.max_conversation_length
      }
    };

    return JSON.stringify(config, null, 2);
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(generateYAML());
    // You could add a toast notification here
  };

  const handleTest = async () => {
    if (!testMessage.trim()) return;
    
    // Check if agent is deployed
    if (!agentId) {
      setTestResponse(
        `⚠️ Agent Testing Not Available\n\n` +
        `This agent hasn't been deployed yet, so live testing is not possible.\n\n` +
        `What you can do:\n` +
        `1. Click "Deploy Agent" below to create the agent\n` +
        `2. After deployment, come back to edit the agent\n` +
        `3. You'll then be able to test with real API responses\n\n` +
        `For now, you can review the configuration in the YAML tab.`
      );
      return;
    }
    
    setIsTestLoading(true);
    setTestResponse('');
    
    try {
      // Use the real messaging API to test the agent
      const apiBaseUrl = process.env.REACT_APP_API_URL || 'http://localhost:8000';
      
      console.log('🧪 Testing agent with message:', testMessage);
      console.log('📡 Agent ID:', agentId);
      console.log('📡 API URL:', `${apiBaseUrl}/api/v1/messages/`);
      
      const response = await fetch(`${apiBaseUrl}/api/v1/messages/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: testMessage,
          agent_id: agentId, // Use actual agent ID
          session_id: `test-${Date.now()}`,
          user_id: 'test-user',
          page_context: {
            url: window.location.href,
            title: 'Agent Test - Admin Dashboard',
          },
        }),
      });

      console.log('📨 Response status:', response.status);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('❌ API error response:', errorText);
        throw new Error(`API responded with status ${response.status}: ${errorText}`);
      }

      const result = await response.json();
      console.log('✅ Test response:', result);
      
      // Extract the response text
      const responseText = result.response || result.message || JSON.stringify(result);
      setTestResponse(responseText);
      
    } catch (error) {
      console.error('❌ Test error:', error);
      
      // Provide helpful error messages
      if (error instanceof Error) {
        if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
          setTestResponse(
            `⚠️ Cannot connect to API server.\n\n` +
            `Make sure the API is running at ${process.env.REACT_APP_API_URL || 'http://localhost:8000'}\n\n` +
            `Expected endpoint: /api/v1/messages/\n\n` +
            `To start the API:\n` +
            `1. Open terminal\n` +
            `2. cd apps/api\n` +
            `3. python run.py`
          );
        } else if (error.message.includes('500')) {
          setTestResponse(
            `⚠️ Server Error (500)\n\n` +
            `The API encountered an error processing your request.\n\n` +
            `Common causes:\n` +
            `- Agent configuration is incomplete\n` +
            `- LLM provider API keys not set\n` +
            `- Database connection issues\n` +
            `- RAG is enabled but no documents uploaded\n\n` +
            `Check the API logs for more details:\n` +
            `tail -f apps/api/logs/api.log`
          );
        } else if (error.message.includes('404')) {
          setTestResponse(
            `⚠️ Agent Not Found (404)\n\n` +
            `The agent with ID "${agentId}" doesn't exist in the database.\n\n` +
            `This usually means:\n` +
            `1. The agent was deleted\n` +
            `2. The agent ID is invalid\n` +
            `3. Database connection issue\n\n` +
            `Try deploying the agent again.`
          );
        } else {
          setTestResponse(
            `Error: ${error.message}\n\n` +
            `Please check:\n` +
            `- API server is running\n` +
            `- Agent configuration is valid\n` +
            `- LLM provider credentials are set\n` +
            `- Database is accessible`
          );
        }
      } else {
        setTestResponse('Unknown error occurred during testing');
      }
    } finally {
      setIsTestLoading(false);
    }
  };

  // Validation checks
  const validationChecks = [
    {
      name: 'Basic Information',
      valid: data.name && data.description && data.brand_id,
      message: data.name && data.description && data.brand_id ? 'Complete' : 'Missing required fields'
    },
    {
      name: 'LLM Configuration',
      valid: data.provider && data.model,
      message: data.provider && data.model ? 'Model configured' : 'Provider and model required'
    },
    {
      name: 'System Prompt',
      valid: data.system_prompt && data.system_prompt.length > 50,
      message: data.system_prompt && data.system_prompt.length > 50 ? 'Detailed prompt provided' : 'System prompt too short'
    },
    {
      name: 'RAG Setup',
      valid: !data.rag_enabled || (data.embedding_provider && data.embedding_model),
      message: !data.rag_enabled ? 'RAG disabled' : (data.embedding_provider && data.embedding_model ? 'RAG configured' : 'RAG enabled but missing configuration')
    },
    {
      name: 'Knowledge Base',
      valid: !data.rag_enabled || data.documents?.length > 0,
      message: !data.rag_enabled ? 'Not using RAG' : (data.documents?.length > 0 ? `${data.documents.length} documents uploaded` : 'No documents uploaded')
    }
  ];

  const allValid = validationChecks.every(check => check.valid);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">Review & Deploy</h3>
        <p className="mt-1 text-sm text-gray-600">
          Review your agent configuration and test it before deployment.
        </p>
      </div>

      {/* Configuration Summary */}
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <h4 className="text-base font-medium text-gray-900 mb-4">Configuration Summary</h4>
        
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <h5 className="text-sm font-medium text-gray-700">Basic Info</h5>
            <div className="mt-1 text-sm text-gray-600">
              <p><strong>Name:</strong> {data.name || 'Not set'}</p>
              <p><strong>Brand:</strong> {selectedBrand?.name || 'Not selected'}</p>
              <p><strong>Purpose:</strong> {data.purpose || 'Not specified'}</p>
            </div>
          </div>

          <div>
            <h5 className="text-sm font-medium text-gray-700">LLM Settings</h5>
            <div className="mt-1 text-sm text-gray-600">
              <p><strong>Provider:</strong> {data.provider || 'Not set'}</p>
              <p><strong>Model:</strong> {data.model || 'Not set'}</p>
              <p><strong>Temperature:</strong> {data.temperature}</p>
            </div>
          </div>

          <div>
            <h5 className="text-sm font-medium text-gray-700">Features</h5>
            <div className="mt-1 text-sm text-gray-600">
              <p><strong>RAG:</strong> {data.rag_enabled ? 'Enabled' : 'Disabled'}</p>
              <p><strong>File Upload:</strong> {data.file_upload ? 'Enabled' : 'Disabled'}</p>
              <p><strong>Memory:</strong> {data.conversation_memory ? 'Enabled' : 'Disabled'}</p>
            </div>
          </div>

          <div>
            <h5 className="text-sm font-medium text-gray-700">Security</h5>
            <div className="mt-1 text-sm text-gray-600">
              <p><strong>Rate Limiting:</strong> {data.rate_limiting ? 'Enabled' : 'Disabled'}</p>
              <p><strong>Content Filter:</strong> {data.content_filtering ? 'Enabled' : 'Disabled'}</p>
              <p><strong>Session Timeout:</strong> {data.session_timeout}min</p>
            </div>
          </div>
        </div>
      </div>

      {/* Validation Checks */}
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <h4 className="text-base font-medium text-gray-900 mb-4">Pre-deployment Checks</h4>
        
        <div className="space-y-3">
          {validationChecks.map((check, index) => (
            <div key={index} className="flex items-center">
              {check.valid ? (
                <CheckCircleIcon className="h-5 w-5 text-green-500" />
              ) : (
                <ExclamationTriangleIcon className="h-5 w-5 text-yellow-500" />
              )}
              <span className="ml-3 text-sm">
                <span className="font-medium text-gray-900">{check.name}:</span>
                <span className={`ml-1 ${check.valid ? 'text-green-600' : 'text-yellow-600'}`}>
                  {check.message}
                </span>
              </span>
            </div>
          ))}
        </div>

        {!allValid && (
          <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
            <p className="text-sm text-yellow-800">
              Some configuration items need attention before deployment. Please review the items above.
            </p>
          </div>
        )}
      </div>

      {/* Test Interface */}
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-base font-medium text-gray-900">Test Your Agent</h4>
          {agentId ? (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
              Testing Available
            </span>
          ) : (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
              Deploy First to Test
            </span>
          )}
        </div>
        
        <div className="space-y-4">
          <div>
            <label htmlFor="test_message" className="block text-sm font-medium text-gray-700">
              Test Message
            </label>
            <div className="mt-1 flex rounded-md shadow-sm">
              <input
                type="text"
                id="test_message"
                value={testMessage}
                onChange={(e) => setTestMessage(e.target.value)}
                className="flex-1 rounded-l-md border-gray-300 focus:border-primary-500 focus:ring-primary-500"
                placeholder="Type a message to test your agent..."
              />
              <button
                onClick={handleTest}
                disabled={!testMessage.trim() || isTestLoading}
                className="inline-flex items-center px-4 py-2 border border-l-0 border-gray-300 rounded-r-md bg-primary-50 text-sm font-medium text-primary-700 hover:bg-primary-100 focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500 disabled:opacity-50"
              >
                {isTestLoading ? 'Testing...' : 'Test'}
              </button>
            </div>
          </div>

          {testResponse && (
            <div className="p-4 bg-gray-50 rounded-md">
              <p className="text-sm font-medium text-gray-900 mb-2">Agent Response:</p>
              <p className="text-sm text-gray-700">{testResponse}</p>
            </div>
          )}
        </div>
      </div>

      {/* Configuration Export */}
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-base font-medium text-gray-900">Configuration Export</h4>
          <div className="flex space-x-2">
            <button
              onClick={() => setShowYaml(!showYaml)}
              className="text-sm text-primary-600 hover:text-primary-800"
            >
              {showYaml ? 'Hide' : 'Show'} Configuration
            </button>
            <button
              onClick={copyToClipboard}
              className="inline-flex items-center text-sm text-primary-600 hover:text-primary-800"
            >
              <ClipboardDocumentIcon className="h-4 w-4 mr-1" />
              Copy
            </button>
          </div>
        </div>

        {showYaml && (
          <pre className="text-xs bg-gray-900 text-gray-100 p-4 rounded-md overflow-x-auto">
            {generateYAML()}
          </pre>
        )}
      </div>

      {/* Deploy Button */}
      <div className="flex justify-end">
        <button
          onClick={onDeploy}
          disabled={!allValid || isDeploying}
          className={`inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 ${
            allValid && !isDeploying
              ? 'bg-primary-600 hover:bg-primary-700'
              : 'bg-gray-400 cursor-not-allowed'
          }`}
        >
          {isDeploying ? (
            <>
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Deploying...
            </>
          ) : (
            'Deploy Agent'
          )}
        </button>
      </div>
    </div>
  );
}
