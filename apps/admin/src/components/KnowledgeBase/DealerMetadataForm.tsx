import React from 'react';
import type { DealerData } from '../../types/knowledge';

interface DealerMetadataFormProps {
  data: Partial<DealerData>;
  onChange: (data: Partial<DealerData>) => void;
  onUseTemplate?: (template: Partial<DealerData>) => void;
}

// Example templates
const dealerTemplates = {
  mumbai: {
    dealer_id: 'DEALER-MUM-001',
    name: 'ABC Hardware Distributors',
    city: 'Mumbai',
    state: 'Maharashtra',
    phone: '+91-22-12345678',
    email: 'contact@abchardware.com',
    address: '123 MG Road, Andheri East, Mumbai - 400069',
  },
  delhi: {
    dealer_id: 'DEALER-DEL-002',
    name: 'XYZ Bathware Solutions',
    city: 'New Delhi',
    state: 'Delhi',
    phone: '+91-11-87654321',
    email: 'info@xyzbathware.in',
    address: '456 Connaught Place, New Delhi - 110001',
  },
};

export default function DealerMetadataForm({
  data,
  onChange,
  onUseTemplate,
}: DealerMetadataFormProps) {
  const handleChange = (field: keyof DealerData, value: string) => {
    onChange({ ...data, [field]: value });
  };

  const loadTemplate = (template: Partial<DealerData>) => {
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
            onClick={() => loadTemplate(dealerTemplates.mumbai)}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Mumbai Dealer Example
          </button>
          <button
            type="button"
            onClick={() => loadTemplate(dealerTemplates.delhi)}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Delhi Dealer Example
          </button>
        </div>
      </div>

      {/* Basic Information */}
      <div className="border-t border-gray-200 pt-6">
        <h4 className="text-base font-semibold text-gray-900 mb-4">
          Dealer Information
        </h4>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {/* Dealer ID */}
          <div>
            <label htmlFor="dealer_id" className="block text-sm font-medium text-gray-700">
              Dealer ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="dealer_id"
              required
              value={data.dealer_id || ''}
              onChange={(e) => handleChange('dealer_id', e.target.value)}
              placeholder="DEALER-MUM-001"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
            <p className="mt-1 text-xs text-gray-500">
              Unique dealer identifier (e.g., DEALER-MUM-001)
            </p>
          </div>

          {/* Dealer Name */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700">
              Dealer Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="name"
              required
              value={data.name || ''}
              onChange={(e) => handleChange('name', e.target.value)}
              placeholder="ABC Hardware Distributors"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* City */}
          <div>
            <label htmlFor="city" className="block text-sm font-medium text-gray-700">
              City <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="city"
              required
              value={data.city || ''}
              onChange={(e) => handleChange('city', e.target.value)}
              placeholder="Mumbai"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* State */}
          <div>
            <label htmlFor="state" className="block text-sm font-medium text-gray-700">
              State / Province
            </label>
            <input
              type="text"
              id="state"
              value={data.state || ''}
              onChange={(e) => handleChange('state', e.target.value)}
              placeholder="Maharashtra"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* Phone */}
          <div>
            <label htmlFor="phone" className="block text-sm font-medium text-gray-700">
              Phone Number <span className="text-red-500">*</span>
            </label>
            <input
              type="tel"
              id="phone"
              required
              value={data.phone || ''}
              onChange={(e) => handleChange('phone', e.target.value)}
              placeholder="+91-22-12345678"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>

          {/* Email */}
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email Address
            </label>
            <input
              type="email"
              id="email"
              value={data.email || ''}
              onChange={(e) => handleChange('email', e.target.value)}
              placeholder="contact@dealer.com"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            />
          </div>
        </div>

        {/* Address */}
        <div className="mt-6">
          <label htmlFor="address" className="block text-sm font-medium text-gray-700">
            Full Address
          </label>
          <textarea
            id="address"
            rows={3}
            value={data.address || ''}
            onChange={(e) => handleChange('address', e.target.value)}
            placeholder="123 MG Road, Andheri East, Mumbai - 400069"
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
          />
        </div>
      </div>

      {/* Help Text */}
      <div className="rounded-md bg-blue-50 p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-blue-400"
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
          <div className="ml-3">
            <p className="text-sm text-blue-700">
              <strong>💡 Tip:</strong> This structured data helps users find dealers near them. 
              The AI will use this exact information to provide accurate contact details and locations 
              without making anything up.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
