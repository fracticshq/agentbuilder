import React, { useState } from 'react';
import {
  promptTemplates,
  PromptTemplate,
  getTemplatesByCategory,
  getAvailableIndustries,
  getAvailableUseCases,
  getAvailableTones,
  searchTemplates,
  applyTemplateVariables,
} from '../utils/prompt-templates';
import { MagnifyingGlassIcon, SparklesIcon } from '@heroicons/react/24/outline';

interface PromptTemplatesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectTemplate: (template: string) => void;
  brandName?: string;
}

export default function PromptTemplatesModal({
  isOpen,
  onClose,
  onSelectTemplate,
  brandName,
}: PromptTemplatesModalProps) {
  const [selectedCategory, setSelectedCategory] = useState<'all' | 'industry' | 'use-case' | 'tone'>('all');
  const [selectedFilter, setSelectedFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<PromptTemplate | null>(null);
  const [templateVariables, setTemplateVariables] = useState<Record<string, string>>({});

  if (!isOpen) return null;

  const filteredTemplates = (() => {
    let templates = searchQuery
      ? searchTemplates(searchQuery)
      : selectedCategory === 'all'
      ? promptTemplates
      : getTemplatesByCategory(selectedCategory);

    if (selectedFilter && selectedCategory !== 'all') {
      templates = templates.filter((t: PromptTemplate) => {
        if (selectedCategory === 'industry') return t.industry === selectedFilter;
        if (selectedCategory === 'use-case') return t.useCase === selectedFilter;
        if (selectedCategory === 'tone') return t.tone === selectedFilter;
        return true;
      });
    }

    return templates;
  })();

  const handleSelectTemplate = (template: PromptTemplate) => {
    setSelectedTemplate(template);
    // Pre-fill brand name if available
    if (brandName) {
      setTemplateVariables(prev => ({ ...prev, brand_name: brandName }));
    }
  };

  const handleApplyTemplate = () => {
    if (!selectedTemplate) return;

    const finalPrompt = selectedTemplate.variables && Object.keys(templateVariables).length > 0
      ? applyTemplateVariables(selectedTemplate.template, templateVariables)
      : selectedTemplate.template;

    onSelectTemplate(finalPrompt);
    handleClose();
  };

  const handleClose = () => {
    setSelectedCategory('all');
    setSelectedFilter('');
    setSearchQuery('');
    setSelectedTemplate(null);
    setTemplateVariables({});
    onClose();
  };

  const getFilterOptions = () => {
    switch (selectedCategory) {
      case 'industry':
        return getAvailableIndustries();
      case 'use-case':
        return getAvailableUseCases();
      case 'tone':
        return getAvailableTones();
      default:
        return [];
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Backdrop */}
        <div
          className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
          onClick={handleClose}
        />

        {/* Modal */}
        <div className="relative bg-white rounded-lg shadow-xl max-w-6xl w-full max-h-[90vh] overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <SparklesIcon className="w-6 h-6 text-primary-600" />
                <h2 className="text-2xl font-bold text-gray-900">System Prompt Templates</h2>
              </div>
              <button
                onClick={handleClose}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex h-[calc(90vh-120px)]">
            {/* Left Sidebar - Template List */}
            <div className="w-1/2 border-r border-gray-200 flex flex-col">
              {/* Search & Filters */}
              <div className="p-4 border-b border-gray-200 space-y-3">
                {/* Search */}
                <div className="relative">
                  <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search templates..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>

                {/* Category Tabs */}
                <div className="flex space-x-2">
                  {['all', 'industry', 'use-case', 'tone'].map((category) => (
                    <button
                      key={category}
                      onClick={() => {
                        setSelectedCategory(category as any);
                        setSelectedFilter('');
                      }}
                      className={`px-3 py-1 text-sm font-medium rounded-md ${
                        selectedCategory === category
                          ? 'bg-primary-100 text-primary-700'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {category.charAt(0).toUpperCase() + category.slice(1).replace('-', ' ')}
                    </button>
                  ))}
                </div>

                {/* Filter Dropdown */}
                {selectedCategory !== 'all' && (
                  <select
                    value={selectedFilter}
                    onChange={(e) => setSelectedFilter(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  >
                    <option value="">All {selectedCategory}s</option>
                    {getFilterOptions().map((option: string) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Template List */}
              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {filteredTemplates.length === 0 ? (
                  <div className="text-center py-12 text-gray-500">
                    <SparklesIcon className="w-12 h-12 mx-auto mb-3 text-gray-400" />
                    <p>No templates found</p>
                    <p className="text-sm mt-1">Try adjusting your search or filters</p>
                  </div>
                ) : (
                  filteredTemplates.map((template: PromptTemplate) => (
                    <button
                      key={template.id}
                      onClick={() => handleSelectTemplate(template)}
                      className={`w-full text-left p-4 rounded-lg border-2 transition-colors ${
                        selectedTemplate?.id === template.id
                          ? 'border-primary-500 bg-primary-50'
                          : 'border-gray-200 hover:border-gray-300 bg-white'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <h3 className="font-semibold text-gray-900">{template.name}</h3>
                          <p className="text-sm text-gray-600 mt-1">{template.description}</p>
                          <div className="flex flex-wrap gap-2 mt-2">
                            {template.industry && (
                              <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-700">
                                {template.industry}
                              </span>
                            )}
                            {template.useCase && (
                              <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-700">
                                {template.useCase}
                              </span>
                            )}
                            {template.tone && (
                              <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-purple-100 text-purple-700">
                                {template.tone}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Right Panel - Preview & Variables */}
            <div className="w-1/2 flex flex-col">
              {selectedTemplate ? (
                <>
                  {/* Variables Input */}
                  {selectedTemplate.variables && selectedTemplate.variables.length > 0 && (
                    <div className="p-4 border-b border-gray-200 bg-gray-50">
                      <h3 className="text-sm font-semibold text-gray-900 mb-3">
                        Template Variables
                      </h3>
                      <p className="text-xs text-gray-600 mb-3">
                        Fill in these variables to customize the template for your brand:
                      </p>
                      <div className="space-y-2">
                        {selectedTemplate.variables.map((variable: string) => (
                          <div key={variable}>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              {variable.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase())}
                            </label>
                            <input
                              type="text"
                              value={templateVariables[variable] || ''}
                              onChange={(e) =>
                                setTemplateVariables((prev) => ({
                                  ...prev,
                                  [variable]: e.target.value,
                                }))
                              }
                              placeholder={`Enter ${variable.replace(/_/g, ' ')}`}
                              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Template Preview */}
                  <div className="flex-1 overflow-y-auto p-4">
                    <h3 className="text-sm font-semibold text-gray-900 mb-3">Preview</h3>
                    <div className="prose prose-sm max-w-none bg-white border border-gray-200 rounded-lg p-4">
                      <pre className="whitespace-pre-wrap text-sm text-gray-800 font-mono">
                        {selectedTemplate.variables && Object.keys(templateVariables).length > 0
                          ? applyTemplateVariables(selectedTemplate.template, templateVariables)
                          : selectedTemplate.template}
                      </pre>
                    </div>
                  </div>

                  {/* Apply Button */}
                  <div className="p-4 border-t border-gray-200">
                    <button
                      onClick={handleApplyTemplate}
                      className="w-full inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
                    >
                      <SparklesIcon className="w-5 h-5 mr-2" />
                      Use This Template
                    </button>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-gray-500">
                  <div className="text-center">
                    <SparklesIcon className="w-16 h-16 mx-auto mb-4 text-gray-400" />
                    <p className="text-lg font-medium">Select a template to preview</p>
                    <p className="text-sm mt-2">Choose from industry-specific, use-case, or tone templates</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
