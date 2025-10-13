import React from 'react';

interface StepFeaturesProps {
  data: {
    websockets: boolean;
    file_upload: boolean;
    conversation_memory: boolean;
    typing_indicators: boolean;
    response_streaming: boolean;
    rate_limiting: boolean;
    content_filtering: boolean;
    session_timeout: number;
    max_conversation_length: number;
    allowed_file_types: string[];
    max_file_size: number;
  };
  onChange: (field: string, value: string | number | boolean | string[]) => void;
}

const fileTypes = [
  { id: 'pdf', name: 'PDF Documents', extension: '.pdf' },
  { id: 'doc', name: 'Word Documents', extension: '.docx,.doc' },
  { id: 'txt', name: 'Text Files', extension: '.txt' },
  { id: 'md', name: 'Markdown Files', extension: '.md' },
  { id: 'csv', name: 'CSV Files', extension: '.csv' },
  { id: 'json', name: 'JSON Files', extension: '.json' },
  { id: 'image', name: 'Images', extension: '.jpg,.jpeg,.png,.gif' },
];

export default function StepFeatures({ data, onChange }: StepFeaturesProps) {
  const toggleFileType = (typeId: string) => {
    const current = data.allowed_file_types || [];
    const updated = current.includes(typeId)
      ? current.filter(t => t !== typeId)
      : [...current, typeId];
    onChange('allowed_file_types', updated);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">Features & Security</h3>
        <p className="mt-1 text-sm text-gray-600">
          Configure the features and security settings for your agent.
        </p>
      </div>

      {/* Core Features */}
      <div>
        <h4 className="text-sm font-medium text-gray-900 mb-3">Core Features</h4>
        <div className="space-y-3">
          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="websockets" className="text-sm font-medium text-gray-900">
                WebSocket Support
              </label>
              <p className="text-xs text-gray-500">
                Enable real-time communication for instant responses
              </p>
            </div>
            <input
              id="websockets"
              type="checkbox"
              checked={data.websockets}
              onChange={(e) => onChange('websockets', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>

          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="response_streaming" className="text-sm font-medium text-gray-900">
                Response Streaming
              </label>
              <p className="text-xs text-gray-500">
                Stream responses token by token for better user experience
              </p>
            </div>
            <input
              id="response_streaming"
              type="checkbox"
              checked={data.response_streaming}
              onChange={(e) => onChange('response_streaming', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>

          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="conversation_memory" className="text-sm font-medium text-gray-900">
                Conversation Memory
              </label>
              <p className="text-xs text-gray-500">
                Remember context from previous messages in the conversation
              </p>
            </div>
            <input
              id="conversation_memory"
              type="checkbox"
              checked={data.conversation_memory}
              onChange={(e) => onChange('conversation_memory', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>

          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="typing_indicators" className="text-sm font-medium text-gray-900">
                Typing Indicators
              </label>
              <p className="text-xs text-gray-500">
                Show typing indicators while the agent is thinking
              </p>
            </div>
            <input
              id="typing_indicators"
              type="checkbox"
              checked={data.typing_indicators}
              onChange={(e) => onChange('typing_indicators', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>
        </div>
      </div>

      {/* File Upload Configuration */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-medium text-gray-900">File Upload</h4>
          <input
            id="file_upload"
            type="checkbox"
            checked={data.file_upload}
            onChange={(e) => onChange('file_upload', e.target.checked)}
            className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
          />
        </div>

        {data.file_upload && (
          <div className="space-y-4 ml-4 border-l-2 border-gray-200 pl-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Allowed File Types
              </label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {fileTypes.map((type) => (
                  <div key={type.id} className="flex items-center">
                    <input
                      id={`file_type_${type.id}`}
                      type="checkbox"
                      checked={data.allowed_file_types?.includes(type.id) || false}
                      onChange={() => toggleFileType(type.id)}
                      className="h-3 w-3 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                    />
                    <label
                      htmlFor={`file_type_${type.id}`}
                      className="ml-2 text-xs text-gray-700"
                    >
                      {type.name}
                    </label>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <label htmlFor="max_file_size" className="block text-sm font-medium text-gray-700">
                Maximum File Size (MB)
              </label>
              <input
                type="number"
                id="max_file_size"
                min="1"
                max="100"
                value={data.max_file_size}
                onChange={(e) => onChange('max_file_size', parseInt(e.target.value))}
                className="mt-1 block w-32 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
              />
            </div>
          </div>
        )}
      </div>

      {/* Security Settings */}
      <div>
        <h4 className="text-sm font-medium text-gray-900 mb-3">Security & Limits</h4>
        <div className="space-y-3">
          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="rate_limiting" className="text-sm font-medium text-gray-900">
                Rate Limiting
              </label>
              <p className="text-xs text-gray-500">
                Limit the number of requests per user to prevent abuse
              </p>
            </div>
            <input
              id="rate_limiting"
              type="checkbox"
              checked={data.rate_limiting}
              onChange={(e) => onChange('rate_limiting', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>

          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <label htmlFor="content_filtering" className="text-sm font-medium text-gray-900">
                Content Filtering
              </label>
              <p className="text-xs text-gray-500">
                Filter inappropriate content in user messages and agent responses
              </p>
            </div>
            <input
              id="content_filtering"
              type="checkbox"
              checked={data.content_filtering}
              onChange={(e) => onChange('content_filtering', e.target.checked)}
              className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
            />
          </div>
        </div>
      </div>

      {/* Session Configuration */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label htmlFor="session_timeout" className="block text-sm font-medium text-gray-700">
            Session Timeout (minutes)
          </label>
          <input
            type="number"
            id="session_timeout"
            min="5"
            max="480"
            value={data.session_timeout}
            onChange={(e) => onChange('session_timeout', parseInt(e.target.value))}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            How long to keep conversations active (5-480 minutes)
          </p>
        </div>

        <div>
          <label htmlFor="max_conversation_length" className="block text-sm font-medium text-gray-700">
            Max Conversation Length
          </label>
          <input
            type="number"
            id="max_conversation_length"
            min="10"
            max="1000"
            value={data.max_conversation_length}
            onChange={(e) => onChange('max_conversation_length', parseInt(e.target.value))}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Maximum number of messages per conversation
          </p>
        </div>
      </div>

      {/* Feature Recommendations */}
      <div className="bg-green-50 border border-green-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-green-800">
              Recommended Configuration
            </h3>
            <div className="mt-2 text-sm text-green-700">
              <ul className="list-disc pl-5 space-y-1">
                <li><strong>Enable:</strong> WebSockets, Response Streaming, Conversation Memory</li>
                <li><strong>Security:</strong> Always enable Rate Limiting and Content Filtering</li>
                <li><strong>Session Timeout:</strong> 30-60 minutes for most use cases</li>
                <li><strong>File Upload:</strong> Only enable if your agent needs to process documents</li>
                <li><strong>Conversation Length:</strong> 50-100 messages for good performance</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* Performance Impact Warning */}
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
                <li>More features = higher server resource usage</li>
                <li>File upload increases storage requirements</li>
                <li>Longer conversations consume more memory</li>
                <li>Content filtering adds small latency to responses</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
