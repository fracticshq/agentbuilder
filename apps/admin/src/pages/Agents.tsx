import React from 'react';
import { Link } from 'react-router-dom';
import { PlusIcon, CpuChipIcon } from '@heroicons/react/24/outline';

export default function Agents() {
  return (
    <div>
      <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-bold text-gray-900">Agents</h1>
          <p className="mt-2 text-sm text-gray-700">
            Manage your AI agents and their configurations.
          </p>
        </div>
        <div className="mt-4 sm:ml-16 sm:mt-0 sm:flex-none">
          <Link
            to="/agents/new"
            className="inline-flex items-center gap-x-1_5 rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500"
          >
            <PlusIcon className="-ml-0.5 h-5 w-5" aria-hidden="true" />
            New Agent
          </Link>
        </div>
      </div>

      <div className="text-center py-12">
        <CpuChipIcon className="mx-auto h-12 w-12 text-gray-400" />
        <h3 className="mt-2 text-sm font-semibold text-gray-900">No agents</h3>
        <p className="mt-1 text-sm text-gray-500">Get started by creating your first AI agent.</p>
        <div className="mt-6">
          <Link
            to="/agents/new"
            className="inline-flex items-center gap-x-1_5 rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500"
          >
            <PlusIcon className="-ml-0.5 h-5 w-5" aria-hidden="true" />
            Create Agent
          </Link>
        </div>
      </div>
    </div>
  );
}
