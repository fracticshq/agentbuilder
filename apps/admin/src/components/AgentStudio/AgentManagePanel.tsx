import React from 'react';
import {
  ArrowTopRightOnSquareIcon,
  CheckCircleIcon,
  CircleStackIcon,
  CommandLineIcon,
  PuzzlePieceIcon,
  ShieldCheckIcon,
} from '@heroicons/react/24/outline';
import type { AgentStudioCommonProps } from './types';

interface AgentManagePanelProps extends AgentStudioCommonProps {
  agentId: string;
  onOpenConsole: () => void;
}

function SummaryRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-gray-100 py-3 last:border-b-0">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-gray-400">{icon}</span>
        <span className="truncate text-sm font-medium text-gray-700">{label}</span>
      </div>
      <span className="shrink-0 rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">{value}</span>
    </div>
  );
}

export default function AgentManagePanel({ data, agentId, onOpenConsole }: AgentManagePanelProps) {
  const selectedSkills = data.selected_skill_ids?.length || 0;
  const selectedTools = data.selected_tool_ids?.length || 0;
  const knowledgeState = data.data_source === 'rag' || data.rag_enabled ? 'Enabled' : 'Off';
  const apiState = data.api_data_source_enabled ? 'Configured' : 'Off';
  const memoryState = data.conversation_memory ? 'Short-term on' : 'Off';

  return (
    <aside className="space-y-4">
      <section className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-4">
          <p className="text-sm font-semibold text-gray-950">Configuration Summary</p>
          <p className="mt-1 text-xs leading-5 text-gray-500">
            This page edits the saved agent configuration. Runtime testing and live traces are available in Agent Console.
          </p>
        </div>
        <div className="px-4">
          <SummaryRow icon={<CircleStackIcon className="h-4 w-4" />} label="Knowledge" value={knowledgeState} />
          <SummaryRow icon={<PuzzlePieceIcon className="h-4 w-4" />} label="Skills" value={`${selectedSkills} selected`} />
          <SummaryRow icon={<CommandLineIcon className="h-4 w-4" />} label="Tools / APIs" value={apiState !== 'Off' ? apiState : `${selectedTools} selected`} />
          <SummaryRow icon={<ShieldCheckIcon className="h-4 w-4" />} label="Memory" value={memoryState} />
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-gray-950 text-white">
            <CommandLineIcon className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-950">Agent Console</p>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              Test streaming answers, inspect context, and watch skills, tools, memory, and API data source activity in real time.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onOpenConsole}
          disabled={!agentId}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-gray-950 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
        >
          <ArrowTopRightOnSquareIcon className="h-4 w-4" />
          Open Console
        </button>
      </section>

      <section className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
        <div className="flex items-start gap-2">
          <CheckCircleIcon className="mt-0.5 h-4 w-4 text-emerald-700" />
          <p className="text-xs leading-5 text-emerald-800">
            Saved changes here are what the widget, Agent API, export package, and console use as the single source of truth.
          </p>
        </div>
      </section>
    </aside>
  );
}
