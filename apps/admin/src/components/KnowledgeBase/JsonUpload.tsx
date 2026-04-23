import React, { useState } from 'react';
import { DocumentArrowUpIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import ShopifyTab from './tabs/ShopifyTab';
import JsonUrlTab from './tabs/JsonUrlTab';
import CsvUploadTab from './tabs/CsvUploadTab';
import ScrapeTab from './tabs/ScrapeTab';

interface JsonUploadProps {
  contentType: 'product' | 'dealer' | 'faq' | 'office' | 'category' | 'guide';
  onUpload: (data: any[]) => void;
  onBack: () => void;
  brandId?: string;
}

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  itemCount: number;
  preview: any[];
  fullData: any[];  // Store full data, not just preview
}

type UploadMethod = 'file' | 'paste' | 'json_url' | 'csv' | 'shopify' | 'scrape';

export default function JsonUpload({ contentType, onUpload, onBack, brandId = '' }: JsonUploadProps) {
  const [jsonFile, setJsonFile] = useState<File | null>(null);
  const [jsonText, setJsonText] = useState('');
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [uploadMethod, setUploadMethod] = useState<UploadMethod>('file');

  const isProduct = contentType === 'product';

  const validateJsonData = (data: any): ValidationResult => {
    const errors: string[] = [];
    const warnings: string[] = [];
    let items: any[] = [];

    // Check if data is an array
    if (!Array.isArray(data)) {
      if (typeof data === 'object' && data !== null) {
        // Try to find an array property
        const arrayProps = Object.keys(data).filter(key => Array.isArray(data[key]));
        if (arrayProps.length === 1) {
          items = data[arrayProps[0]];
          warnings.push(`Using array from property: ${arrayProps[0]}`);
        } else if (arrayProps.length > 1) {
          errors.push(`Multiple arrays found. Please provide a single array of ${contentType}s.`);
          return { valid: false, errors, warnings, itemCount: 0, preview: [], fullData: [] };
        } else {
          errors.push('JSON must contain an array of items');
          return { valid: false, errors, warnings, itemCount: 0, preview: [], fullData: [] };
        }
      } else {
        errors.push('JSON must be an array or object containing an array');
        return { valid: false, errors, warnings, itemCount: 0, preview: [], fullData: [] };
      }
    } else {
      items = data;
    }

    if (items.length === 0) {
      errors.push('JSON array is empty');
      return { valid: false, errors, warnings, itemCount: 0, preview: [], fullData: [] };
    }

    // Basic validation - just check items are objects
    // Field mapping will happen in the next step!
    items.forEach((item, index) => {
      if (typeof item !== 'object' || item === null) {
        errors.push(`Item ${index + 1}: Must be an object`);
        return;
      }
      
      // Check item has at least some fields
      if (Object.keys(item).length === 0) {
        errors.push(`Item ${index + 1}: Empty object`);
      }
    });

    const preview = items.slice(0, 3); // Show first 3 items

    return {
      valid: errors.length === 0,
      errors,
      warnings,
      itemCount: items.length,
      preview,
      fullData: items,  // Store ALL items, not just preview
    };
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setJsonFile(file);

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const data = JSON.parse(text);
        const result = validateJsonData(data);
        setValidationResult(result);
      } catch (error) {
        setValidationResult({
          valid: false,
          errors: [`Invalid JSON: ${error instanceof Error ? error.message : 'Parse error'}`],
          warnings: [],
          itemCount: 0,
          preview: [],
          fullData: [],
        });
      }
    };
    reader.readAsText(file);
  };

  const handlePasteJson = () => {
    try {
      const data = JSON.parse(jsonText);
      const result = validateJsonData(data);
      setValidationResult(result);
    } catch (error) {
      setValidationResult({
        valid: false,
        errors: [`Invalid JSON: ${error instanceof Error ? error.message : 'Parse error'}`],
        warnings: [],
        itemCount: 0,
        preview: [],
        fullData: [],
      });
    }
  };

  const handleContinue = () => {
    if (!validationResult?.valid) return;

    // Use fullData which contains ALL items, not just the preview
    const items = validationResult.fullData;

    if (items.length > 0) {
      process.env.NODE_ENV !== 'production' && console.log(`[JsonUpload] Passing ${items.length} items to mapper`);
      onUpload(items);
    }
  };

  const exampleJson = contentType === 'product' 
    ? `[
  {
    "product_id": "FAU-001",
    "product_title": "Chrome Bathroom Faucet",
    "cost": 3499,
    "product_type": "faucets"
  },
  {
    "product_id": "SHW-002",
    "product_title": "Rain Shower Head",
    "cost": 5999,
    "product_type": "showers"
  }
]`
    : `[
  {
    "dealer_id": "DLR-001",
    "dealer_name": "ABC Hardware",
    "location": "Mumbai",
    "contact": "+91-9876543210"
  }
]`;

  // Render new catalog tabs directly — they handle their own "Next" button
  if (uploadMethod === 'shopify') {
    return <ShopifyTab brandId={brandId} onUpload={onUpload} onBack={() => setUploadMethod('file')} />;
  }
  if (uploadMethod === 'json_url') {
    return <JsonUrlTab brandId={brandId} onUpload={onUpload} onBack={() => setUploadMethod('file')} />;
  }
  if (uploadMethod === 'csv') {
    return <CsvUploadTab brandId={brandId} onUpload={onUpload} onBack={() => setUploadMethod('file')} />;
  }
  if (uploadMethod === 'scrape') {
    return <ScrapeTab brandId={brandId} onUpload={onUpload} onBack={() => setUploadMethod('file')} />;
  }

  const baseTabs: { key: UploadMethod; label: string }[] = [
    { key: 'file', label: '📁 Upload File' },
    { key: 'paste', label: '📋 Paste JSON' },
  ];
  const productTabs: { key: UploadMethod; label: string }[] = [
    { key: 'json_url', label: '🔗 JSON URL' },
    { key: 'csv', label: '📊 CSV' },
    { key: 'shopify', label: '🛍️ Shopify' },
    { key: 'scrape', label: '🕷️ Scrape' },
  ];
  const tabs = isProduct ? [...baseTabs, ...productTabs] : baseTabs;

  return (
    <div className="space-y-6">
      {/* Upload Method Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex flex-wrap gap-x-2">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setUploadMethod(tab.key)}
              className={`${
                uploadMethod === tab.key
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              } whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Upload Method Content */}
      {uploadMethod === 'file' ? (
        <div>
          <label className="block w-full">
            <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-md hover:border-primary-400 cursor-pointer">
              <div className="space-y-1 text-center">
                <DocumentArrowUpIcon className="mx-auto h-12 w-12 text-gray-400" />
                <div className="flex text-sm text-gray-600">
                  <span className="relative cursor-pointer bg-white rounded-md font-medium text-primary-600 hover:text-primary-500">
                    Upload a JSON file
                  </span>
                  <input
                    type="file"
                    accept=".json"
                    onChange={handleFileUpload}
                    className="sr-only"
                  />
                </div>
                <p className="text-xs text-gray-500">JSON files only</p>
                {jsonFile && (
                  <p className="text-sm text-green-600 font-medium">
                    ✓ {jsonFile.name}
                  </p>
                )}
              </div>
            </div>
          </label>
        </div>
      ) : (
        <div>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-700">
              Paste your JSON data
            </label>
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              placeholder={exampleJson}
              rows={12}
              className="w-full px-3 py-2 border border-gray-300 rounded-md font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <button
            onClick={handlePasteJson}
            className="mt-3 px-4 py-2 bg-primary-600 text-white text-sm font-medium rounded-md hover:bg-primary-700"
          >
            Validate JSON
          </button>
        </div>
      )}

      {/* Example */}
      <details className="border border-gray-200 rounded-lg">
        <summary className="px-4 py-3 cursor-pointer font-medium text-gray-700 hover:bg-gray-50">
          💡 See Example JSON Format
        </summary>
        <div className="px-4 py-3 bg-gray-50 border-t border-gray-200">
          <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap">
            {exampleJson}
          </pre>
          <button
            onClick={() => {
              navigator.clipboard.writeText(exampleJson);
              alert('Copied to clipboard!');
            }}
            className="mt-2 text-xs text-primary-600 hover:text-primary-800"
          >
            📋 Copy Example
          </button>
        </div>
      </details>

      {/* Validation Results */}
      {validationResult && (
        <div>
          {validationResult.valid ? (
            <div className="rounded-md bg-green-50 p-4">
              <div className="flex">
                <CheckCircleIcon className="h-5 w-5 text-green-400" />
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-green-800">
                    ✅ JSON Valid!
                  </h3>
                  <div className="mt-2 text-sm text-green-700">
                    <p>Found {validationResult.itemCount} items</p>
                    {validationResult.warnings.length > 0 && (
                      <ul className="mt-1 list-disc pl-5">
                        {validationResult.warnings.map((warning, idx) => (
                          <li key={idx}>{warning}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-md bg-red-50 p-4">
              <div className="flex">
                <ExclamationTriangleIcon className="h-5 w-5 text-red-400" />
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">
                    Validation Errors
                  </h3>
                  <div className="mt-2 text-sm text-red-700">
                    <ul className="list-disc pl-5 space-y-1">
                      {validationResult.errors.map((error, idx) => (
                        <li key={idx}>{error}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Preview */}
          {validationResult.valid && validationResult.preview.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-gray-900 mb-2">
                Preview (First 3 Items)
              </h4>
              <div className="space-y-2">
                {validationResult.preview.map((item, idx) => (
                  <div key={idx} className="bg-gray-50 border border-gray-200 rounded p-3">
                    <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap">
                      {JSON.stringify(item, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-6 border-t border-gray-200">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          ← Back to Content Type
        </button>
        <button
          onClick={handleContinue}
          disabled={!validationResult?.valid}
          className={`px-6 py-2 text-sm font-medium text-white rounded-md ${
            validationResult?.valid
              ? 'bg-primary-600 hover:bg-primary-700'
              : 'bg-gray-300 cursor-not-allowed'
          }`}
        >
          Next: Map Fields →
        </button>
      </div>
    </div>
  );
}
