import React from 'react';
import { XMarkIcon } from '@heroicons/react/24/outline';

interface VersionHistoryPanelProps {
  open: boolean;
  onClose: () => void;
}

export default function VersionHistoryPanel({ open, onClose }: VersionHistoryPanelProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
      <div className="w-full max-w-lg overflow-hidden rounded-md bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-950">Version History</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900" aria-label="Close version history">
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>
        <div className="p-4">
          <div className="rounded-md border border-dashed border-gray-300 p-8 text-center">
            <p className="text-sm font-medium text-gray-900">Version history is ready for backend wiring.</p>
            <p className="mt-2 text-sm leading-6 text-gray-500">
              This surface is intentionally present so saved agent revisions can plug in without another layout change.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
