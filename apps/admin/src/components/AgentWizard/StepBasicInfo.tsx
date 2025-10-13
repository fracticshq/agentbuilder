import React from 'react';

interface StepBasicInfoProps {
  data: {
    name: string;
    description: string;
    brand_id: string;
    purpose: string;
    role: string;
  };
  onChange: (field: string, value: string) => void;
  brands: Array<{ id: string; name: string }>;
}

export default function StepBasicInfo({ data, onChange, brands }: StepBasicInfoProps) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">Basic Information</h3>
        <p className="mt-1 text-sm text-gray-600">
          Set up the fundamental details for your AI agent.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label htmlFor="name" className="block text-sm font-medium text-gray-700">
            Agent Name *
          </label>
          <input
            type="text"
            id="name"
            value={data.name}
            onChange={(e) => onChange('name', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
            placeholder="e.g., Customer Support Bot"
            required
          />
        </div>

        <div>
          <label htmlFor="brand" className="block text-sm font-medium text-gray-700">
            Brand *
          </label>
          <select
            id="brand"
            value={data.brand_id}
            onChange={(e) => onChange('brand_id', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
            required
          >
            <option value="">Select a brand</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="description" className="block text-sm font-medium text-gray-700">
          Description *
        </label>
        <textarea
          id="description"
          rows={3}
          value={data.description}
          onChange={(e) => onChange('description', e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          placeholder="Brief description of what this agent does..."
          required
        />
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label htmlFor="purpose" className="block text-sm font-medium text-gray-700">
            Primary Purpose
          </label>
          <select
            id="purpose"
            value={data.purpose}
            onChange={(e) => onChange('purpose', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          >
            <option value="">Select purpose</option>
            <option value="customer_support">Customer Support</option>
            <option value="sales_assistant">Sales Assistant</option>
            <option value="technical_support">Technical Support</option>
            <option value="product_expert">Product Expert</option>
            <option value="booking_assistant">Booking Assistant</option>
            <option value="general_assistant">General Assistant</option>
          </select>
        </div>

        <div>
          <label htmlFor="role" className="block text-sm font-medium text-gray-700">
            Agent Role
          </label>
          <select
            id="role"
            value={data.role}
            onChange={(e) => onChange('role', e.target.value)}
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
          >
            <option value="">Select role</option>
            <option value="assistant">Assistant</option>
            <option value="consultant">Consultant</option>
            <option value="advisor">Advisor</option>
            <option value="specialist">Specialist</option>
            <option value="representative">Representative</option>
          </select>
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800">
              Agent Name Guidelines
            </h3>
            <div className="mt-2 text-sm text-blue-700">
              <ul className="list-disc pl-5 space-y-1">
                <li>Use descriptive names that indicate the agent's function</li>
                <li>Keep it concise (2-4 words)</li>
                <li>Avoid special characters or numbers</li>
                <li>Consider your brand voice when naming</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
