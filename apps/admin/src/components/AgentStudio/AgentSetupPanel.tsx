import React from 'react';
import {
  BoltIcon,
  CheckCircleIcon,
  CircleStackIcon,
  RocketLaunchIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline';
import type { AgentStudioData } from './types';

interface AgentSetupPanelProps {
  data: AgentStudioData;
  saving?: boolean;
  onCreate: () => void;
}

function Step({ complete, label, detail, icon }: { complete: boolean; label: string; detail: string; icon: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <div className={`mt-0.5 inline-flex h-7 w-7 flex-none items-center justify-center rounded-full ${complete ? 'bg-gray-950 text-white' : 'bg-gray-100 text-gray-500'}`}>
        {complete ? <CheckCircleIcon className="h-4 w-4" /> : icon}
      </div>
      <div>
        <p className="text-sm font-semibold text-gray-950">{label}</p>
        <p className="mt-1 text-sm leading-5 text-gray-500">{detail}</p>
      </div>
    </div>
  );
}

export default function AgentSetupPanel({ data, saving, onCreate }: AgentSetupPanelProps) {
  const hasIdentity = Boolean(data.name && data.description && data.brand_id);
  const hasModel = Boolean(data.model && data.role && data.system_prompt);
  const hasCapabilities = Boolean(
    data.selected_tool_ids.length ||
    data.selected_skill_ids.length ||
    data.data_source === 'rag' ||
    data.agent_api_enabled
  );

  return (
    <aside className="flex min-h-[520px] flex-col justify-center rounded-md border border-gray-100 bg-white px-8 py-10">
      <div className="mx-auto mb-6 inline-flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 text-gray-700">
        <RocketLaunchIcon className="h-7 w-7" />
      </div>
      <h2 className="text-center text-xl font-semibold tracking-tight text-gray-950">Start Building</h2>
      <div className="mt-8 space-y-7">
        <Step
          complete={hasIdentity}
          label="Define identity"
          detail="Name the agent, choose its workspace brand, and describe what it should do."
          icon={<BoltIcon className="h-4 w-4" />}
        />
        <Step
          complete={hasModel}
          label="Choose LLM & role"
          detail="Select the deployed model and define the agent's role and instructions."
          icon={<CircleStackIcon className="h-4 w-4" />}
        />
        <Step
          complete={hasCapabilities}
          label="Enable capabilities"
          detail="Add knowledge, skills, tools, memory, API access, or safety controls."
          icon={<WrenchScrewdriverIcon className="h-4 w-4" />}
        />
      </div>
      <button
        type="button"
        onClick={onCreate}
        disabled={saving || !hasIdentity || !hasModel}
        className="mx-auto mt-10 inline-flex h-10 items-center justify-center rounded-md bg-gray-950 px-6 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
      >
        {saving ? 'Creating...' : 'Create'}
      </button>
    </aside>
  );
}
