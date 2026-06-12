import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BeakerIcon,
  CircleStackIcon,
  CommandLineIcon,
  MagnifyingGlassIcon,
  ShieldCheckIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline';
import { api, SkillDefinition, ToolDefinition } from '../../api/client';
import type { AgentStudioCommonProps } from './types';

function Toggle({
  enabled,
  disabled,
  onChange,
}: {
  enabled: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 flex-none items-center rounded-full transition ${
        enabled ? 'bg-primary-600' : 'bg-gray-200'
      } disabled:cursor-not-allowed disabled:opacity-50`}
      aria-pressed={enabled}
    >
      <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${
        enabled ? 'translate-x-5' : 'translate-x-0.5'
      }`} />
    </button>
  );
}

function FeatureRow({
  name,
  detail,
  enabled,
  disabled,
  badge,
  onToggle,
}: {
  name: string;
  detail?: string;
  enabled: boolean;
  disabled?: boolean;
  badge?: string;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-md border border-gray-200 bg-white px-3 py-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="truncate text-sm font-medium text-gray-800">{name}</p>
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-gray-300 text-[10px] text-gray-500">i</span>
          </div>
          {detail && <p className="mt-1 truncate text-xs text-gray-500">{detail}</p>}
        </div>
        {badge ? (
          <span className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">{badge}</span>
        ) : (
          <Toggle enabled={enabled} disabled={disabled} onChange={onToggle} />
        )}
      </div>
    </div>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-600">{title}</h3>
        <div className="h-px flex-1 bg-gray-200" />
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function RegistryRow({
  id,
  name,
  description,
  selected,
  status,
  onToggle,
}: {
  id: string;
  name: string;
  description?: string;
  selected: boolean;
  status?: string;
  onToggle: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onToggle(id)}
      className={`block w-full rounded-md border px-3 py-3 text-left transition ${
        selected ? 'border-primary-600 bg-primary-50 text-gray-900' : 'border-gray-200 bg-white text-gray-900 hover:border-gray-300 hover:bg-gray-50'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-sm font-semibold">{name}</p>
        <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${
          selected
            ? 'bg-primary-100 text-primary-700'
            : status === 'Ready'
              ? 'bg-emerald-50 text-emerald-700'
              : status === 'Needs setup'
                ? 'bg-amber-50 text-amber-700'
                : 'bg-gray-100 text-gray-600'
        }`}>
          {selected ? 'Selected' : status || 'Available'}
        </span>
      </div>
      {description && (
        <p className={`mt-1 line-clamp-2 text-xs leading-5 ${selected ? 'text-gray-600' : 'text-gray-500'}`}>
          {description}
        </p>
      )}
    </button>
  );
}

export default function AgentCapabilityRail({ data, onChange }: AgentStudioCommonProps) {
  const [tab, setTab] = useState<'features' | 'tools'>('features');
  const [search, setSearch] = useState('');

  const { data: skills = [] } = useQuery<SkillDefinition[]>({
    queryKey: ['admin', 'skills'],
    queryFn: api.getSkills,
  });
  const { data: tools = [] } = useQuery<ToolDefinition[]>({
    queryKey: ['admin', 'tools'],
    queryFn: api.getTools,
  });

  const selectedSkills = new Set(data.selected_skill_ids || []);
  const selectedTools = new Set(data.selected_tool_ids || []);
  const query = search.trim().toLowerCase();

  const filteredSkills = useMemo(() => skills.filter((skill) => {
    const haystack = `${skill.name} ${skill.id} ${skill.description || ''}`.toLowerCase();
    return !query || haystack.includes(query);
  }), [query, skills]);

  const filteredTools = useMemo(() => tools.filter((tool) => {
    const haystack = `${tool.name} ${tool.id} ${tool.description || ''}`.toLowerCase();
    return !query || haystack.includes(query);
  }), [query, tools]);

  const toggleArrayValue = (field: 'selected_skill_ids' | 'selected_tool_ids', id: string) => {
    const current = new Set(data[field] || []);
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    onChange(field, Array.from(current));
  };

  const toggleKnowledge = () => {
    const enabled = data.data_source === 'rag' || data.rag_enabled;
    onChange('rag_enabled', !enabled);
    onChange('data_source', enabled ? 'none' : 'rag');
    onChange('show_sources', !enabled);
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 rounded-md bg-gray-100 p-1">
        <button
          type="button"
          onClick={() => setTab('features')}
          className={`rounded px-3 py-2 text-sm font-medium ${tab === 'features' ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
        >
          Agent Features
        </button>
        <button
          type="button"
          onClick={() => setTab('tools')}
          className={`rounded px-3 py-2 text-sm font-medium ${tab === 'tools' ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
        >
          Agent Tools
        </button>
      </div>

      <label className="relative block">
        <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="w-full rounded-md border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
          placeholder={tab === 'features' ? 'Search features...' : 'Search tools...'}
        />
      </label>

      {tab === 'features' ? (
        <div className="max-h-[calc(100vh-230px)] space-y-5 overflow-auto pr-1">
          <Section icon={<CircleStackIcon className="h-4 w-4 text-gray-500" />} title="Core Features">
            <FeatureRow name="Knowledge Base" detail={data.data_source === 'rag' ? 'Uses attached/workspace sources for retrieval' : 'Attach sources from Knowledge Base'} enabled={data.data_source === 'rag' || data.rag_enabled} onToggle={toggleKnowledge} />
            <FeatureRow name="Data Query" detail={data.api_data_source_enabled ? 'External API context configured' : 'Use Agent Tools to configure an API source'} enabled={data.api_data_source_enabled} badge={data.api_data_source_enabled ? undefined : 'Beta'} disabled={!data.api_data_source_enabled} onToggle={() => onChange('api_data_source_enabled', !data.api_data_source_enabled)} />
            <FeatureRow name="URL Context Boost" detail="Use the current page URL and metadata" enabled={data.url_context_boost_enabled} onToggle={() => onChange('url_context_boost_enabled', !data.url_context_boost_enabled)} />
            <FeatureRow name="Short Term Memory" detail="Use recent turns and summaries within the conversation" enabled={data.conversation_memory} onToggle={() => onChange('conversation_memory', !data.conversation_memory)} />
            <FeatureRow name="Long Term Memory" detail="Remember user facts across conversations (PII-vaulted, 90-day TTL, GDPR delete supported)" enabled={data.long_term_memory} onToggle={() => onChange('long_term_memory', !data.long_term_memory)} />
            <FeatureRow name="Humanizer" enabled={data.typing_indicators} onToggle={() => onChange('typing_indicators', !data.typing_indicators)} />
          </Section>

          <Section icon={<ShieldCheckIcon className="h-4 w-4 text-gray-500" />} title="Safe & Responsible AI">
            <FeatureRow name="Responsible AI" enabled={data.content_filtering} onToggle={() => onChange('content_filtering', !data.content_filtering)} />
            <FeatureRow name="Reflection" enabled={false} badge="Coming Soon" disabled onToggle={() => {}} />
            <FeatureRow name="Groundedness" enabled={data.show_sources} onToggle={() => onChange('show_sources', !data.show_sources)} />
            <FeatureRow name="Context Relevance" enabled={false} badge="Coming Soon" disabled onToggle={() => {}} />
            <FeatureRow name="Fairness & Bias" enabled={false} badge="Coming Soon" disabled onToggle={() => {}} />
          </Section>

          <Section icon={<BeakerIcon className="h-4 w-4 text-gray-500" />} title="Skills">
            {filteredSkills.length === 0 ? (
              <div className="rounded-md border border-dashed border-gray-200 p-4 text-sm text-gray-500">No skills found.</div>
            ) : filteredSkills.map((skill) => (
              <RegistryRow
                key={skill.id}
                id={skill.id}
                name={skill.name || skill.id}
                description={skill.description}
                selected={selectedSkills.has(skill.id)}
                status={selectedSkills.has(skill.id) ? 'Ready' : 'Available'}
                onToggle={(skillId) => toggleArrayValue('selected_skill_ids', skillId)}
              />
            ))}
          </Section>
        </div>
      ) : (
        <div className="max-h-[calc(100vh-230px)] space-y-2 overflow-auto pr-1">
          <Section icon={<CommandLineIcon className="h-4 w-4 text-gray-500" />} title="API Data Source">
            <div className="rounded-md border border-gray-200 bg-white p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-gray-900">External API Context</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">Configure one allowlisted HTTP source the agent can use for context, such as astrology, pricing, inventory, or operational data.</p>
                </div>
                <Toggle
                  enabled={data.api_data_source_enabled}
                  onChange={() => onChange('api_data_source_enabled', !data.api_data_source_enabled)}
                />
              </div>
              <div className="space-y-2">
                <input
                  value={data.api_data_source_name}
                  onChange={(event) => onChange('api_data_source_name', event.target.value)}
                  className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                  placeholder="Astrology API for Lal Kitab"
                />
                <input
                  value={data.api_data_source_url}
                  onChange={(event) => onChange('api_data_source_url', event.target.value)}
                  className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                  placeholder="https://api.example.com/lal-kitab"
                />
                <input
                  value={data.api_data_source_auth_header}
                  onChange={(event) => onChange('api_data_source_auth_header', event.target.value)}
                  className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                  placeholder={data.api_data_source_auth_header_configured ? 'Authorization header configured' : 'Authorization: Bearer ...'}
                />
                <textarea
                  value={data.api_data_source_usage}
                  onChange={(event) => onChange('api_data_source_usage', event.target.value)}
                  className="min-h-[76px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                  placeholder="When answering Lal Kitab questions, fetch birth chart inputs, remedies, and planetary context from this API."
                />
              </div>
            </div>
          </Section>

          <Section icon={<WrenchScrewdriverIcon className="h-4 w-4 text-gray-500" />} title="Popular Tools">
            {filteredTools.length === 0 ? (
              <div className="rounded-md border border-dashed border-gray-200 p-4 text-sm text-gray-500">No tools found.</div>
            ) : filteredTools.map((tool) => (
              <RegistryRow
                key={tool.id}
                id={tool.id}
                name={tool.name || tool.id}
                description={tool.description || (tool.auth_required ? 'Requires credentials before live execution.' : 'Registry tool')}
                selected={selectedTools.has(tool.id)}
                status={tool.executor_available ? 'Ready' : (tool.auth_required ? 'Needs setup' : 'Registry-only')}
                onToggle={(toolId) => toggleArrayValue('selected_tool_ids', toolId)}
              />
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}
