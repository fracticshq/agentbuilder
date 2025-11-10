import React, { useState } from 'react';
import { PlusIcon } from '@heroicons/react/24/outline';
import DocumentUploadWizard from '../components/KnowledgeBase/DocumentUploadWizard';

export default function KnowledgeBase() {
  const [showWizard, setShowWizard] = useState(false);
  
  // TODO: Get brand from context/URL params
  const brandId = 'essco-bathware';

  const handleUploadComplete = () => {
    setShowWizard(false);
    // TODO: Refresh document list
    alert('Document uploaded successfully!');
  };

  if (showWizard) {
    return (
      <div>
        <DocumentUploadWizard
          brandId={brandId}
          onComplete={handleUploadComplete}
          onCancel={() => setShowWizard(false)}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="sm:flex sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Knowledge Base</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage documents and structured knowledge for your AI agents
          </p>
        </div>
        <div className="mt-4 sm:mt-0">
          <button
            onClick={() => setShowWizard(true)}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            <PlusIcon className="h-5 w-5 mr-2" />
            Upload Document
          </button>
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-3">
        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <svg
                  className="h-6 w-6 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Total Documents
                  </dt>
                  <dd className="text-3xl font-semibold text-gray-900">
                    24
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <svg
                  className="h-6 w-6 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"
                  />
                </svg>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Products
                  </dt>
                  <dd className="text-3xl font-semibold text-gray-900">
                    12
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <svg
                  className="h-6 w-6 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"
                  />
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                </svg>
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">
                    Dealers
                  </dt>
                  <dd className="text-3xl font-semibold text-gray-900">
                    8
                  </dd>
                </dl>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Empty State / Document List */}
      <div className="mt-8 bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <div className="text-center py-12">
            <svg
              className="mx-auto h-12 w-12 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">
              No documents yet
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              Get started by uploading your first knowledge base document.
            </p>
            <div className="mt-6">
              <button
                onClick={() => setShowWizard(true)}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
              >
                <PlusIcon className="h-5 w-5 mr-2" />
                Upload Your First Document
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Information Panel */}
      <div className="mt-6 rounded-md bg-blue-50 p-6">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-6 w-6 text-blue-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3 flex-1">
            <h3 className="text-sm font-medium text-blue-800">
              Why structured metadata matters
            </h3>
            <div className="mt-2 text-sm text-blue-700">
              <p>
                Adding structured metadata (like product SKUs, prices, and dealer contacts) 
                ensures your AI agent provides <strong>accurate, hallucination-free responses</strong>. 
                Without it, the AI might invent product details or incorrect contact information.
              </p>
              <ul className="mt-2 list-disc pl-5 space-y-1">
                <li><strong>Products:</strong> Exact SKUs, prices, and features prevent the AI from making up product details</li>
                <li><strong>Dealers:</strong> Verified contact information ensures users get real phone numbers and addresses</li>
                <li><strong>FAQs & Guides:</strong> General content doesn't need structured data and will be processed automatically</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
