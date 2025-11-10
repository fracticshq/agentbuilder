import React, { useState } from 'react';
import { PlusIcon, XMarkIcon } from '@heroicons/react/24/outline';
import type { ProductData } from '../../types/knowledge';

interface ProductMetadataFormProps {
  data: Partial<ProductData>;
  onChange: (data: Partial<ProductData>) => void;
  onUseTemplate?: (template: Partial<ProductData>) => void;
}

// Example templates
const productTemplates = {
  faucet: {
    sku: 'ESSCO-FAU-001',
    name: 'AquaFlow Chrome Faucet',
    price: 3499,
    currency: 'INR',
    category: 'faucets',
    image_url: 'https://example.com/products/aquaflow-chrome.jpg',
    product_url: 'https://essco.in/products/aquaflow-chrome-faucet',
    in_stock: true,
    features: ['chrome finish', 'ceramic disc valve', 'water-saving'],
  },
  showerHead: {
    sku: 'ESSCO-SHO-002',
    name: 'RainShower Premium Head',
    price: 5999,
    currency: 'INR',
    category: 'shower-heads',
    image_url: 'https://example.com/products/rainshower.jpg',
    product_url: 'https://essco.in/products/rainshower-premium',
    in_stock: true,
    features: ['rainfall effect', 'adjustable flow', '8-inch diameter'],
  },
};

export default function ProductMetadataForm({
  data,
  onChange,
  onUseTemplate,
}: ProductMetadataFormProps) {
  const [newFeature, setNewFeature] = useState('');

  const handleChange = (field: keyof ProductData, value: any) => {
    onChange({ ...data, [field]: value });
  };

  const addFeature = () => {
    if (!newFeature.trim()) return;
    
    const currentFeatures = data.features || [];
    handleChange('features', [...currentFeatures, newFeature.trim()]);
    setNewFeature('');
  };

  const removeFeature = (index: number) => {
    const currentFeatures = data.features || [];
    handleChange('features', currentFeatures.filter((_, i) => i !== index));
  };

  const loadTemplate = (template: Partial<ProductData>) => {
    if (onUseTemplate) {
      onUseTemplate(template);
    } else {
      onChange(template);
    }
  };

  return (
    <div className="space-y-6">
      {/* Template Selector */}
      <div className="rounded-md bg-gray-50 p-4">
        <h4 className="text-sm font-medium text-gray-900 mb-3">
          📋 Quick Start with Template
        </h4>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => loadTemplate(productTemplates.faucet)}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Faucet Example
          </button>
          <button
            type="button"
            onClick={() => loadTemplate(productTemplates.showerHead)}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Shower Head Example
          </button>
        </div>
      </div>

      {/* Basic Information */}
      <div className="border-t border-gray-200 pt-6">
        <h4 className="text-base font-semibold text-gray-900 mb-4">
          Basic Information
        </h4>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {/* SKU */}
          <div>
            <label htmlFor="sku" className="block text-sm font-medium text-gray-700">
              SKU <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="sku"
              required
              value={data.sku || ''}
              onChange={(e) => handleChange('sku', e.target.value)}
              placeholder="ESSCO-FAU-001"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              Unique product identifier (e.g., ESSCO-FAU-001)
            </p>
          </div>

          {/* Product Name */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700">
              Product Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="name"
              required
              value={data.name || ''}
              onChange={(e) => handleChange('name', e.target.value)}
              placeholder="AquaFlow Chrome Faucet"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* Price */}
          <div>
            <label htmlFor="price" className="block text-sm font-medium text-gray-700">
              Price <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              id="price"
              required
              value={data.price || ''}
              onChange={(e) => handleChange('price', parseInt(e.target.value))}
              placeholder="3499"
              min="0"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              Price in smallest currency unit (paise for INR, cents for USD)
            </p>
          </div>

          {/* Currency */}
          <div>
            <label htmlFor="currency" className="block text-sm font-medium text-gray-700">
              Currency <span className="text-red-500">*</span>
            </label>
            <select
              id="currency"
              required
              value={data.currency || 'INR'}
              onChange={(e) => handleChange('currency', e.target.value)}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            >
              <option value="INR">INR (₹)</option>
              <option value="USD">USD ($)</option>
              <option value="EUR">EUR (€)</option>
              <option value="GBP">GBP (£)</option>
            </select>
          </div>

          {/* Category */}
          <div>
            <label htmlFor="category" className="block text-sm font-medium text-gray-700">
              Category <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="category"
              required
              value={data.category || ''}
              onChange={(e) => handleChange('category', e.target.value)}
              placeholder="faucets"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              e.g., faucets, shower-heads, accessories
            </p>
          </div>

          {/* In Stock */}
          <div>
            <label htmlFor="in_stock" className="block text-sm font-medium text-gray-700">
              Availability
            </label>
            <div className="mt-2">
              <label className="inline-flex items-center">
                <input
                  type="checkbox"
                  id="in_stock"
                  checked={data.in_stock !== false}
                  onChange={(e) => handleChange('in_stock', e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="ml-2 text-sm text-gray-700">In Stock</span>
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* URLs */}
      <div className="border-t border-gray-200 pt-6">
        <h4 className="text-base font-semibold text-gray-900 mb-4">
          Links & Media
        </h4>

        <div className="space-y-4">
          {/* Image URL */}
          <div>
            <label htmlFor="image_url" className="block text-sm font-medium text-gray-700">
              Image URL
            </label>
            <input
              type="url"
              id="image_url"
              value={data.image_url || ''}
              onChange={(e) => handleChange('image_url', e.target.value)}
              placeholder="https://example.com/products/image.jpg"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* Product URL */}
          <div>
            <label htmlFor="product_url" className="block text-sm font-medium text-gray-700">
              Product Page URL
            </label>
            <input
              type="url"
              id="product_url"
              value={data.product_url || ''}
              onChange={(e) => handleChange('product_url', e.target.value)}
              placeholder="https://essco.in/products/aquaflow-faucet"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="border-t border-gray-200 pt-6">
        <h4 className="text-base font-semibold text-gray-900 mb-4">
          Features & Specifications
        </h4>

        <div className="flex gap-2">
          <input
            type="text"
            value={newFeature}
            onChange={(e) => setNewFeature(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), addFeature())}
            placeholder="Add a feature (e.g., 'chrome finish')"
            className="flex-1 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
          />
          <button
            type="button"
            onClick={addFeature}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            <PlusIcon className="h-5 w-5" />
          </button>
        </div>

        {data.features && data.features.length > 0 && (
          <ul className="mt-4 space-y-2">
            {data.features.map((feature, index) => (
              <li
                key={index}
                className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-2"
              >
                <span className="text-sm text-gray-700">{feature}</span>
                <button
                  type="button"
                  onClick={() => removeFeature(index)}
                  className="text-gray-400 hover:text-red-500"
                >
                  <XMarkIcon className="h-5 w-5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <p className="mt-2 text-xs text-gray-500">
          Add key features and specifications that help users find this product
        </p>
      </div>

      {/* Help Text */}
      <div className="rounded-md bg-yellow-50 p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-yellow-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3">
            <p className="text-sm text-yellow-700">
              <strong>Important:</strong> This structured data ensures the AI shows accurate product 
              information without hallucinating SKUs, prices, or features. Fill in as many fields as possible 
              for best results.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
