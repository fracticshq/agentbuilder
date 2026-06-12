import React from 'react';
import {
  ArrowLeftIcon,
  ClockIcon,
  CodeBracketIcon,
  CommandLineIcon,
  CubeTransparentIcon,
  DocumentArrowDownIcon,
} from '@heroicons/react/24/outline';

interface AgentStudioShellProps {
  mode: 'create' | 'manage';
  title: string;
  subtitle?: string;
  saving?: boolean;
  canExport?: boolean;
  onBack: () => void;
  onSave: () => void;
  onViewJson: () => void;
  onAgentApi: () => void;
  onOpenConsole?: () => void;
  onVersionHistory: () => void;
  onExport: () => void;
  left: React.ReactNode;
  middle: React.ReactNode;
  right: React.ReactNode;
}

function HeaderButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex h-9 items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export default function AgentStudioShell({
  mode,
  title,
  subtitle,
  saving,
  canExport,
  onBack,
  onSave,
  onViewJson,
  onAgentApi,
  onOpenConsole,
  onVersionHistory,
  onExport,
  left,
  middle,
  right,
}: AgentStudioShellProps) {
  return (
    <div className="mx-auto max-w-[1680px]">
      <div className="mb-4 flex flex-col gap-3 border-b border-gray-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            aria-label="Back to agents"
          >
            <ArrowLeftIcon className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-2xl font-bold text-gray-900">{title}</h1>
              <span className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">
                {mode === 'create' ? 'Draft' : 'Live config'}
              </span>
            </div>
            {subtitle && <p className="mt-1 truncate text-sm text-gray-500">{subtitle}</p>}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {mode === 'manage' && onOpenConsole && (
            <HeaderButton onClick={onOpenConsole}>
              <CommandLineIcon className="h-4 w-4" />
              Open Console
            </HeaderButton>
          )}
          {mode === 'manage' && (
            <HeaderButton onClick={onVersionHistory}>
              <ClockIcon className="h-4 w-4" />
              Version History
            </HeaderButton>
          )}
          <HeaderButton onClick={onViewJson}>
            <CodeBracketIcon className="h-4 w-4" />
            View JSON
          </HeaderButton>
          <HeaderButton onClick={onAgentApi}>
            <CubeTransparentIcon className="h-4 w-4" />
            Agent API
          </HeaderButton>
          {mode === 'manage' && (
            <HeaderButton onClick={onExport} disabled={!canExport}>
              <DocumentArrowDownIcon className="h-4 w-4" />
              Export
            </HeaderButton>
          )}
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="inline-flex h-9 items-center justify-center rounded-md bg-primary-600 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-500 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {saving ? 'Saving...' : mode === 'create' ? 'Create' : 'Update'}
          </button>
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-150px)] gap-4 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[minmax(520px,1fr)_300px_520px]">
        <section className="min-w-0 border-r border-gray-200 pr-4">{left}</section>
        <section className="min-w-0 border-r border-gray-200 pr-4">{middle}</section>
        <section className="min-w-0 xl:col-span-2 2xl:col-span-1">{right}</section>
      </div>
    </div>
  );
}
