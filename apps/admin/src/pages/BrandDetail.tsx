import React from 'react';
import { useParams } from 'react-router-dom';

export default function BrandDetail() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Brand Detail</h1>
      <p className="mt-2 text-sm text-gray-600">
        Brand ID: {id}
      </p>
      <div className="mt-8 bg-white shadow rounded-lg p-6">
        <p className="text-gray-500">Brand detail view coming soon...</p>
      </div>
    </div>
  );
}
