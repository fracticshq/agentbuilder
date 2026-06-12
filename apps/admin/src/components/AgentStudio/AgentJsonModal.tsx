import React from 'react';
import { XMarkIcon } from '@heroicons/react/24/outline';

interface AgentJsonModalProps {
  open: boolean;
  title: string;
  data: unknown;
  onClose: () => void;
}

export default function AgentJsonModal({ open, title, data, onClose }: AgentJsonModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
      <div className="max-h-[84vh] w-full max-w-4xl overflow-hidden rounded-md bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-950">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
            aria-label="Close JSON modal"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>
        <pre className="max-h-[72vh] overflow-auto bg-gray-950 p-4 text-xs leading-5 text-gray-100">
          <code>{JSON.stringify(data, null, 2)}</code>
        </pre>
      </div>
    </div>
  );
}
