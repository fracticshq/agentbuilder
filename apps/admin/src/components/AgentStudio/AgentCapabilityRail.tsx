import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BeakerIcon,
  BoltIcon,
  CircleStackIcon,
  CommandLineIcon,
  KeyIcon,
  LinkIcon,
  MagnifyingGlassIcon,
  NoSymbolIcon,
  PlusIcon,
  ShieldCheckIcon,
  TrashIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline';
import { agentConnectorsApi, api, SkillDefinition, ToolDefinition } from '../../api/client';
import type {
  AgentStudioCommonProps,
  ContextConnector,
  ContextConnectorEndpoint,
  ContextConnectorMethod,
  McpDiscoveredTool,
} from './types';

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

const CONNECTOR_METHODS: ContextConnectorMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

function makeConnectorId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

function splitRequiredFields(value: string): string[] {
  return Array.from(new Set(
    value
      .split(/[\n,]/)
      .map(field => field.trim())
      .filter(Boolean)
  ));
}

function splitDomainAllowlist(value: string): string[] {
  return Array.from(new Set(
    value
      .split(/[\n,]/)
      .map(host => host.trim().replace(/^https?:\/\//, '').split('/')[0])
      .filter(Boolean)
  ));
}

function formatJsonValue(value: any): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return '{}';
  }
}

function parseJsonInput(value: string): any {
  try {
    return JSON.parse(value || '{}');
  } catch {
    return value;
  }
}

function sampleConnectorPayload(endpoint?: ContextConnectorEndpoint): Record<string, any> {
  if (!endpoint) {
    return {};
  }
  if (endpoint.id?.startsWith('lalkitab_')) {
    return {
      datetime: '1987-07-16T15:26:00',
      latitude: 28.6139,
      longitude: 77.209,
      timezone: '+05:30',
      language: 'en',
    };
  }
  return {};
}

function createEmptyEndpoint(url = ''): ContextConnectorEndpoint {
  return {
    id: makeConnectorId('endpoint'),
    name: 'Default endpoint',
    method: 'GET',
    url,
    enabled: true,
    required_fields: [],
    description: '',
    headers: {},
    query_schema: {},
    body_schema: {},
    response_mapping: {},
    timeout_seconds: 20,
    max_response_chars: 12000,
    retry_count: 0,
    execution_order: undefined,
    requires_prior_endpoint: null,
    payload_mode: 'wrapped',
    field_mapping: {},
    runtime_required_fields: [],
  };
}

function createEmptyConnector(data: AgentStudioCommonProps['data']): ContextConnector {
  return {
    id: makeConnectorId('connector'),
    type: 'http',
    name: data.api_data_source_name || '',
    enabled: Boolean(data.api_data_source_enabled),
    auth_header: data.api_data_source_auth_header || '',
    auth_header_configured: Boolean(data.api_data_source_auth_header_configured),
    usage: data.api_data_source_usage || '',
    tool_description: data.api_data_source_usage || '',
    domain_allowlist: [],
    input_resolution: {},
    headers: {},
    timeout_seconds: 20,
    max_response_chars: 12000,
    retry_count: 0,
    endpoints: [createEmptyEndpoint(data.api_data_source_url || '')],
  };
}

function normalizeConnector(connector: Partial<ContextConnector>, data: AgentStudioCommonProps['data']): ContextConnector {
  const endpoints = Array.isArray(connector.endpoints) && connector.endpoints.length > 0
    ? connector.endpoints
    : [createEmptyEndpoint(data.api_data_source_url || '')];

  return {
    id: connector.id || makeConnectorId('connector'),
    type: connector.type === 'mcp' ? 'mcp' : 'http',
    name: connector.name ?? data.api_data_source_name ?? '',
    enabled: connector.enabled ?? Boolean(data.api_data_source_enabled),
    auth_header: connector.auth_header ?? data.api_data_source_auth_header ?? '',
    auth_header_configured: Boolean(connector.auth_header_configured ?? data.api_data_source_auth_header_configured),
    usage: connector.usage ?? data.api_data_source_usage ?? '',
    tool_description: connector.tool_description ?? connector.usage ?? data.api_data_source_usage ?? '',
    domain_allowlist: Array.isArray(connector.domain_allowlist) ? connector.domain_allowlist : [],
    input_resolution: connector.input_resolution || {},
    headers: connector.headers || {},
    timeout_seconds: connector.timeout_seconds ?? 20,
    max_response_chars: connector.max_response_chars ?? 12000,
    retry_count: connector.retry_count ?? 0,
    endpoint: connector.endpoint || '',
    transport: connector.transport || connector.mcp?.transport || 'http',
    mcp: connector.mcp || {},
    discovered_tools: Array.isArray(connector.discovered_tools) ? connector.discovered_tools : [],
    allowed_tools: Array.isArray(connector.allowed_tools) ? connector.allowed_tools : [],
    last_discovered_at: connector.last_discovered_at || null,
    revoked: Boolean(connector.revoked),
    endpoints: endpoints.map((endpoint, index) => ({
      id: endpoint.id || makeConnectorId('endpoint'),
      name: endpoint.name || `Endpoint ${index + 1}`,
      method: endpoint.method || 'GET',
      url: endpoint.url || '',
      enabled: endpoint.enabled ?? true,
      required_fields: Array.isArray(endpoint.required_fields) ? endpoint.required_fields : [],
      description: endpoint.description || '',
      headers: endpoint.headers || {},
      query_schema: endpoint.query_schema || {},
      body_schema: endpoint.body_schema || {},
      response_mapping: endpoint.response_mapping || {},
      timeout_seconds: endpoint.timeout_seconds ?? 20,
      max_response_chars: endpoint.max_response_chars ?? 12000,
      retry_count: endpoint.retry_count ?? 0,
      execution_order: endpoint.execution_order,
      requires_prior_endpoint: endpoint.requires_prior_endpoint ?? null,
      payload_mode: endpoint.payload_mode,
      field_mapping: endpoint.field_mapping || {},
      runtime_required_fields: Array.isArray(endpoint.runtime_required_fields) ? endpoint.runtime_required_fields : [],
    })),
  };
}

export default function AgentCapabilityRail({ data, onChange, agentId }: AgentStudioCommonProps) {
  const [tab, setTab] = useState<'features' | 'tools' | 'connectors'>('features');
  const [search, setSearch] = useState('');
  const [discoveringMcp, setDiscoveringMcp] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [testingConnector, setTestingConnector] = useState(false);
  const [connectorTestResult, setConnectorTestResult] = useState<string | null>(null);

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

  const connectors = useMemo<ContextConnector[]>(() => {
    if (Array.isArray(data.context_connectors) && data.context_connectors.length > 0) {
      return data.context_connectors.map(connector => normalizeConnector(connector, data));
    }
    return [createEmptyConnector(data)];
  }, [data]);

  const primaryConnector = connectors[0];
  const isLalKitabConnector = primaryConnector.id === 'vedika_lal_kitab'
    || primaryConnector.name.toLowerCase().includes('lal kitab')
    || primaryConnector.endpoints.some(endpoint => endpoint.id?.startsWith('lalkitab_'));

  const updateConnectors = (nextConnectors: ContextConnector[]) => {
    const normalized = nextConnectors.length > 0
      ? nextConnectors.map(connector => normalizeConnector(connector, data))
      : [createEmptyConnector(data)];
    const primary = normalized.find(connector => connector.type === 'http') || normalized[0];
    const primaryEndpoint = primary?.endpoints?.[0];

    onChange('context_connectors', normalized);
    onChange('api_data_source_enabled', primary?.type === 'http' ? primary.enabled : false);
    onChange('api_data_source_name', primary?.type === 'http' ? primary.name : '');
    onChange('api_data_source_url', primary?.type === 'http' ? primaryEndpoint?.url || '' : '');
    onChange('api_data_source_auth_header', primary?.type === 'http' ? primary.auth_header : '');
    onChange('api_data_source_auth_header_configured', primary?.type === 'http' ? primary.auth_header_configured : false);
    onChange('api_data_source_usage', primary?.type === 'http' ? primary.usage || primary.tool_description : '');
  };

  const updatePrimaryConnector = (patch: Partial<ContextConnector>) => {
    updateConnectors([
      {
        ...primaryConnector,
        ...patch,
      },
      ...connectors.slice(1),
    ]);
  };

  const updateEndpoint = (endpointId: string, patch: Partial<ContextConnectorEndpoint>) => {
    updatePrimaryConnector({
      endpoints: primaryConnector.endpoints.map(endpoint => (
        endpoint.id === endpointId ? { ...endpoint, ...patch } : endpoint
      )),
    });
  };

  const addEndpoint = () => {
    updatePrimaryConnector({
      endpoints: [
        ...primaryConnector.endpoints,
        {
          ...createEmptyEndpoint(),
          name: `Endpoint ${primaryConnector.endpoints.length + 1}`,
        },
      ],
    });
  };

  const removeEndpoint = (endpointId: string) => {
    const endpoints = primaryConnector.endpoints.filter(endpoint => endpoint.id !== endpointId);
    updatePrimaryConnector({
      endpoints: endpoints.length > 0 ? endpoints : [createEmptyEndpoint()],
    });
  };

  const switchConnectorType = (type: 'http' | 'mcp') => {
    if (type === primaryConnector.type) {
      return;
    }
    updatePrimaryConnector(type === 'mcp'
      ? {
        type: 'mcp',
        name: primaryConnector.name || 'MCP Connector',
        endpoint: '',
        endpoints: [],
        discovered_tools: [],
        allowed_tools: [],
      }
      : {
        type: 'http',
        name: primaryConnector.name || 'HTTP Connector',
        endpoint: '',
        discovered_tools: [],
        allowed_tools: [],
        endpoints: [createEmptyEndpoint()],
      });
  };

  const toggleAllowedMcpTool = (toolName: string) => {
    const current = new Set(primaryConnector.allowed_tools || []);
    if (current.has(toolName)) {
      current.delete(toolName);
    } else {
      current.add(toolName);
    }
    updatePrimaryConnector({ allowed_tools: Array.from(current) });
  };

  const discoverMcpTools = async () => {
    if (!agentId || !primaryConnector.endpoint) {
      setMcpError(agentId ? 'Enter an MCP endpoint before discovery.' : 'Save the agent before live MCP discovery.');
      return;
    }
    setDiscoveringMcp(true);
    setMcpError(null);
    try {
      const result = await agentConnectorsApi.discover(agentId, {
        url: primaryConnector.endpoint,
        auth_header: primaryConnector.auth_header,
      });
      const discoveredTools = (result.discovered_tools || []) as McpDiscoveredTool[];
      updatePrimaryConnector({
        discovered_tools: discoveredTools,
        allowed_tools: discoveredTools.map(tool => tool.name).filter(Boolean),
        last_discovered_at: new Date().toISOString(),
      });
      if (discoveredTools.length === 0) {
        setMcpError('No tools were discovered from this MCP server.');
      }
    } catch (error: any) {
      setMcpError(error?.message || 'MCP discovery failed.');
    } finally {
      setDiscoveringMcp(false);
    }
  };

  const testPrimaryConnector = async () => {
    if (!agentId) {
      setConnectorTestResult('Save the agent before running a live connector test.');
      return;
    }
    const endpoint = primaryConnector.endpoints[0];
    if (primaryConnector.type === 'http' && !endpoint) {
      setConnectorTestResult('Add an HTTP endpoint before testing.');
      return;
    }
    setTestingConnector(true);
    setConnectorTestResult(null);
    try {
      const result = await agentConnectorsApi.test(agentId, primaryConnector.id, {
        endpoint_id: endpoint?.id,
        query: 'Test this configured connector.',
        payload: sampleConnectorPayload(endpoint),
      });
      setConnectorTestResult(result.success ? 'Connector test succeeded.' : `Connector test failed: ${result.error || 'unknown error'}`);
    } catch (error: any) {
      setConnectorTestResult(error?.message || 'Connector test failed.');
    } finally {
      setTestingConnector(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 rounded-md bg-gray-100 p-1">
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
        <button
          type="button"
          onClick={() => setTab('connectors')}
          className={`rounded px-3 py-2 text-sm font-medium ${tab === 'connectors' ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
        >
          Connectors
        </button>
      </div>

      {tab !== 'connectors' && (
        <label className="relative block">
          <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="w-full rounded-md border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
            placeholder={tab === 'features' ? 'Search features...' : 'Search tools...'}
          />
        </label>
      )}

      {tab === 'features' ? (
        <div className="max-h-[calc(100vh-230px)] space-y-5 overflow-auto pr-1">
          <Section icon={<CircleStackIcon className="h-4 w-4 text-gray-500" />} title="Core Features">
            <FeatureRow name="Knowledge Base" detail={data.data_source === 'rag' ? 'Uses attached/workspace sources for retrieval' : 'Attach sources from Knowledge Base'} enabled={data.data_source === 'rag' || data.rag_enabled} onToggle={toggleKnowledge} />
            <FeatureRow name="Public Widget" detail={data.widget_enabled ? 'Can be opened through the website widget when the agent is active' : 'Disable public widget preview/embed access'} enabled={data.widget_enabled} onToggle={() => onChange('widget_enabled', !data.widget_enabled)} />
            <FeatureRow name="Context Connector" detail={primaryConnector.enabled ? `${primaryConnector.type === 'mcp' ? 'MCP' : 'HTTP'} context configured` : 'Use Connectors to configure API or MCP context'} enabled={primaryConnector.enabled} onToggle={() => updatePrimaryConnector({ enabled: !primaryConnector.enabled })} />
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
      ) : tab === 'tools' ? (
        <div className="max-h-[calc(100vh-230px)] space-y-2 overflow-auto pr-1">
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
      ) : (
        <div className="max-h-[calc(100vh-230px)] space-y-4 overflow-auto pr-1">
          <Section icon={<CommandLineIcon className="h-4 w-4 text-gray-500" />} title="Context Connectors">
            <div className={`rounded-md border bg-white p-3 shadow-sm ${primaryConnector.revoked ? 'border-red-200' : 'border-gray-200'}`}>
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
	                    <p className="text-sm font-semibold text-gray-900">{primaryConnector.type === 'mcp' ? 'MCP Connector' : 'HTTP Connector'}</p>
                    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                      primaryConnector.revoked
                        ? 'bg-red-50 text-red-700'
                        : primaryConnector.enabled
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-gray-100 text-gray-600'
                    }`}>
                      {primaryConnector.revoked ? 'Revoked' : primaryConnector.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </div>
	                  <p className="mt-1 text-xs leading-5 text-gray-500">
	                    {primaryConnector.type === 'mcp'
	                      ? 'Discover and allowlist MCP tools the agent can call during inference.'
	                      : 'Allowlisted HTTP context the agent can call during inference.'}
	                  </p>
	                </div>
                <Toggle
                  enabled={primaryConnector.enabled}
                  disabled={primaryConnector.revoked}
                  onChange={() => updatePrimaryConnector({ enabled: !primaryConnector.enabled })}
                />
              </div>

	              <div className="mb-3 grid grid-cols-2 rounded-md bg-gray-100 p-1">
	                <button
	                  type="button"
	                  onClick={() => switchConnectorType('http')}
	                  className={`rounded px-3 py-2 text-xs font-semibold ${primaryConnector.type === 'http' ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
	                >
	                  HTTP API
	                </button>
	                <button
	                  type="button"
	                  onClick={() => switchConnectorType('mcp')}
	                  className={`rounded px-3 py-2 text-xs font-semibold ${primaryConnector.type === 'mcp' ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
	                >
	                  MCP Server
	                </button>
	              </div>

	              <div className="space-y-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-600">Name</span>
                  <input
                    value={primaryConnector.name}
                    onChange={(event) => updatePrimaryConnector({ name: event.target.value })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="Astrology API for Lal Kitab"
                  />
	                </label>

	                {primaryConnector.type === 'mcp' && (
	                  <div className="grid gap-2 sm:grid-cols-[112px_minmax(0,1fr)]">
	                    <label className="block">
	                      <span className="mb-1 block text-xs font-medium text-gray-600">Transport</span>
	                      <select
	                        value={primaryConnector.transport || 'http'}
	                        onChange={(event) => updatePrimaryConnector({
	                          transport: event.target.value,
	                          mcp: { ...(primaryConnector.mcp || {}), transport: event.target.value },
	                        })}
	                        className="w-full rounded-md border border-gray-200 bg-white px-2 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
	                      >
	                        <option value="http">HTTP</option>
	                        <option value="sse">SSE</option>
	                      </select>
	                    </label>
	                    <label className="block">
	                      <span className="mb-1 block text-xs font-medium text-gray-600">MCP endpoint</span>
	                      <input
	                        value={primaryConnector.endpoint || ''}
	                        onChange={(event) => updatePrimaryConnector({
	                          endpoint: event.target.value,
	                          mcp: { ...(primaryConnector.mcp || {}), endpoint: event.target.value },
	                        })}
	                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
	                        placeholder="https://mcp.example.com/mcp"
	                      />
	                    </label>
	                  </div>
	                )}

                <label className="block">
                  <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-600">
                    <KeyIcon className="h-3.5 w-3.5" />
                    Auth header
                  </span>
                  <input
                    value={primaryConnector.auth_header}
                    onChange={(event) => updatePrimaryConnector({
                      auth_header: event.target.value,
                      auth_header_configured: Boolean(event.target.value.trim()),
                      revoked: false,
                    })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder={primaryConnector.auth_header_configured ? 'Authorization header configured' : 'Authorization: Bearer ... or paste API key'}
                  />
                </label>

                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-600">Domain allowlist</span>
                  <input
                    value={(primaryConnector.domain_allowlist || []).join(', ')}
                    onChange={(event) => updatePrimaryConnector({ domain_allowlist: splitDomainAllowlist(event.target.value) })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="api.vedika.io, mcp.example.com"
                  />
                </label>

                {isLalKitabConnector && (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-600">Birth Input Handling</p>
                    <div className="mt-2 space-y-2">
                      <label className="flex items-start justify-between gap-3 rounded-md bg-white px-3 py-2">
                        <span>
                          <span className="block text-sm font-medium text-gray-800">Resolve known birth places</span>
                          <span className="mt-0.5 block text-xs leading-5 text-gray-500">
                            Convert common city names like Delhi into latitude, longitude, and timezone automatically.
                          </span>
                        </span>
                        <Toggle
                          enabled={primaryConnector.input_resolution?.resolve_known_places !== false}
                          onChange={() => updatePrimaryConnector({
                            input_resolution: {
                              ...(primaryConnector.input_resolution || {}),
                              resolve_known_places: primaryConnector.input_resolution?.resolve_known_places === false,
                              missing_input_strategy: 'ask_follow_up',
                            },
                          })}
                        />
                      </label>
                      <label className="flex items-start justify-between gap-3 rounded-md bg-white px-3 py-2">
                        <span>
                          <span className="block text-sm font-medium text-gray-800">Confirm understood details</span>
                          <span className="mt-0.5 block text-xs leading-5 text-gray-500">
                            Start answers by repeating the birth details NOVA used before interpreting API and RAG context.
                          </span>
                        </span>
                        <Toggle
                          enabled={primaryConnector.input_resolution?.confirm_understood_details !== false}
                          onChange={() => updatePrimaryConnector({
                            input_resolution: {
                              ...(primaryConnector.input_resolution || {}),
                              confirm_understood_details: primaryConnector.input_resolution?.confirm_understood_details === false,
                              missing_input_strategy: 'ask_follow_up',
                            },
                          })}
                        />
                      </label>
                    </div>
                  </div>
                )}

                <div className="grid gap-2 sm:grid-cols-3">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-gray-600">Timeout</span>
                    <input
                      type="number"
                      min={1}
                      max={60}
                      value={primaryConnector.timeout_seconds ?? 20}
                      onChange={(event) => updatePrimaryConnector({ timeout_seconds: Number(event.target.value) })}
                      className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-gray-600">Max chars</span>
                    <input
                      type="number"
                      min={1000}
                      max={50000}
                      value={primaryConnector.max_response_chars ?? 12000}
                      onChange={(event) => updatePrimaryConnector({ max_response_chars: Number(event.target.value) })}
                      className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-gray-600">Retries</span>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      value={primaryConnector.retry_count ?? 0}
                      onChange={(event) => updatePrimaryConnector({ retry_count: Number(event.target.value) })}
                      className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    />
                  </label>
                </div>

                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-600">Usage</span>
                  <textarea
                    value={primaryConnector.usage}
                    onChange={(event) => updatePrimaryConnector({
                      usage: event.target.value,
                      tool_description: primaryConnector.tool_description || event.target.value,
                    })}
                    className="min-h-[72px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="When answering Lal Kitab questions, fetch birth chart inputs, remedies, and planetary context from this API."
                  />
                </label>

                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-gray-600">Tool description</span>
                  <textarea
                    value={primaryConnector.tool_description}
                    onChange={(event) => updatePrimaryConnector({ tool_description: event.target.value })}
                    className="min-h-[60px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="Describe when this connector should be called and what context it returns."
                  />
                </label>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => updatePrimaryConnector({
                    auth_header: '',
                    auth_header_configured: false,
                    enabled: false,
                    revoked: true,
                  })}
                  className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50"
                >
                  <NoSymbolIcon className="h-4 w-4" />
                  Revoke
                </button>
                {primaryConnector.revoked && (
                  <button
                    type="button"
                    onClick={() => updatePrimaryConnector({ revoked: false })}
                    className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    Restore editing
                  </button>
                )}
                <button
                  type="button"
                  onClick={testPrimaryConnector}
                  disabled={testingConnector || primaryConnector.revoked}
                  className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <BoltIcon className="h-4 w-4" />
                  {testingConnector ? 'Testing...' : 'Test'}
                </button>
              </div>
              {connectorTestResult && (
                <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-700">
                  {connectorTestResult}
                </div>
              )}
            </div>
          </Section>

	          {primaryConnector.type === 'http' ? (
	          <Section icon={<LinkIcon className="h-4 w-4 text-gray-500" />} title="HTTP Endpoints">
            {primaryConnector.endpoints.map((endpoint, index) => (
              <div key={endpoint.id} className={`rounded-md border bg-white p-3 shadow-sm ${endpoint.enabled ? 'border-gray-200' : 'border-gray-100 opacity-80'}`}>
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-gray-900">{endpoint.name || `Endpoint ${index + 1}`}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                      <span>{endpoint.enabled ? 'Available to the agent' : 'Disabled for runtime calls'}</span>
                      {endpoint.id === 'lalkitab_chart' && (
                        <span className="rounded bg-primary-50 px-1.5 py-0.5 font-medium text-primary-700">Required first</span>
                      )}
                      {endpoint.requires_prior_endpoint && (
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-600">After chart</span>
                      )}
                      {endpoint.payload_mode === 'flat_body' && (
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700">Flat body</span>
                      )}
                    </div>
                  </div>
                  <Toggle
                    enabled={endpoint.enabled}
                    onChange={() => updateEndpoint(endpoint.id, { enabled: !endpoint.enabled })}
                  />
                </div>

                <div className="space-y-2">
                  <input
                    value={endpoint.name}
                    onChange={(event) => updateEndpoint(endpoint.id, { name: event.target.value })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder={`Endpoint ${index + 1}`}
                  />

                  <div className="grid gap-2 sm:grid-cols-[96px_minmax(0,1fr)]">
                    <select
                      value={endpoint.method}
                      onChange={(event) => updateEndpoint(endpoint.id, { method: event.target.value as ContextConnectorMethod })}
                      className="rounded-md border border-gray-200 bg-white px-2 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    >
                      {CONNECTOR_METHODS.map(method => (
                        <option key={method} value={method}>{method}</option>
                      ))}
                    </select>
                    <input
                      value={endpoint.url}
                      onChange={(event) => updateEndpoint(endpoint.id, { url: event.target.value })}
                      className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                      placeholder="https://api.example.com/lal-kitab"
                    />
                  </div>

                  <textarea
                    value={endpoint.description || ''}
                    onChange={(event) => updateEndpoint(endpoint.id, { description: event.target.value })}
                    className="min-h-[56px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="What this endpoint returns."
                  />

                  <input
                    value={endpoint.required_fields.join(', ')}
                    onChange={(event) => updateEndpoint(endpoint.id, { required_fields: splitRequiredFields(event.target.value) })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                    placeholder="Required fields: birth_date, birth_time, birth_place"
                  />

                  <div className="grid gap-2 sm:grid-cols-3">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-600">Timeout</span>
                      <input
                        type="number"
                        min={1}
                        max={60}
                        value={endpoint.timeout_seconds ?? primaryConnector.timeout_seconds ?? 20}
                        onChange={(event) => updateEndpoint(endpoint.id, { timeout_seconds: Number(event.target.value) })}
                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-600">Max chars</span>
                      <input
                        type="number"
                        min={1000}
                        max={50000}
                        value={endpoint.max_response_chars ?? primaryConnector.max_response_chars ?? 12000}
                        onChange={(event) => updateEndpoint(endpoint.id, { max_response_chars: Number(event.target.value) })}
                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-600">Retries</span>
                      <input
                        type="number"
                        min={0}
                        max={2}
                        value={endpoint.retry_count ?? primaryConnector.retry_count ?? 0}
                        onChange={(event) => updateEndpoint(endpoint.id, { retry_count: Number(event.target.value) })}
                        className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                      />
                    </label>
                  </div>

                  <details className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
                    <summary className="cursor-pointer text-xs font-semibold text-gray-600">Advanced schemas</summary>
                    <div className="mt-2 space-y-2">
                      <textarea
                        value={formatJsonValue(endpoint.query_schema)}
                        onChange={(event) => updateEndpoint(endpoint.id, { query_schema: parseJsonInput(event.target.value) })}
                        className="min-h-[64px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 font-mono text-xs outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                        placeholder="Query schema JSON"
                      />
                      <textarea
                        value={formatJsonValue(endpoint.body_schema)}
                        onChange={(event) => updateEndpoint(endpoint.id, { body_schema: parseJsonInput(event.target.value) })}
                        className="min-h-[64px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 font-mono text-xs outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                        placeholder="Body schema JSON"
                      />
                      <textarea
                        value={formatJsonValue(endpoint.response_mapping)}
                        onChange={(event) => updateEndpoint(endpoint.id, { response_mapping: parseJsonInput(event.target.value) })}
                        className="min-h-[64px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 font-mono text-xs outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                        placeholder="Response mapping JSON"
                      />
                      <textarea
                        value={formatJsonValue(endpoint.field_mapping)}
                        onChange={(event) => updateEndpoint(endpoint.id, { field_mapping: parseJsonInput(event.target.value) })}
                        className="min-h-[64px] w-full resize-y rounded-md border border-gray-200 px-3 py-2 font-mono text-xs outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                        placeholder="Field mapping JSON"
                      />
                    </div>
                  </details>
                </div>

                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    onClick={() => removeEndpoint(endpoint.id)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-600 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                  >
                    <TrashIcon className="h-4 w-4" />
                    Remove endpoint
                  </button>
                </div>
              </div>
            ))}

            <button
              type="button"
              onClick={addEndpoint}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-gray-300 bg-white px-3 py-3 text-sm font-semibold text-gray-700 hover:border-gray-400 hover:bg-gray-50"
            >
              <PlusIcon className="h-4 w-4" />
              Add endpoint
            </button>
	          </Section>
	          ) : (
	          <Section icon={<CommandLineIcon className="h-4 w-4 text-gray-500" />} title="MCP Tools">
	            <div className="rounded-md border border-gray-200 bg-white p-3 shadow-sm">
	              <div className="flex flex-wrap items-center justify-between gap-2">
	                <div>
	                  <p className="text-sm font-semibold text-gray-900">Tool Discovery</p>
	                  <p className="mt-1 text-xs text-gray-500">
	                    Discover tools from the MCP server, then select the exact tools this agent may use.
	                  </p>
	                </div>
	                <button
	                  type="button"
	                  onClick={discoverMcpTools}
	                  disabled={discoveringMcp || primaryConnector.revoked}
	                  className="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
	                >
	                  <MagnifyingGlassIcon className="h-4 w-4" />
	                  {discoveringMcp ? 'Discovering...' : 'Discover tools'}
	                </button>
	              </div>
	              {mcpError && (
	                <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
	                  {mcpError}
	                </div>
	              )}
	              {primaryConnector.last_discovered_at && (
	                <p className="mt-3 text-[11px] font-medium text-gray-500">
	                  Last discovered {new Date(primaryConnector.last_discovered_at).toLocaleString()}
	                </p>
	              )}
	            </div>

	            <div className="space-y-2">
	              {(primaryConnector.discovered_tools || []).length === 0 ? (
	                <div className="rounded-md border border-dashed border-gray-300 bg-white px-3 py-5 text-sm leading-6 text-gray-500">
	                  No MCP tools discovered yet. Save the agent, enter a reachable MCP endpoint, then run discovery.
	                </div>
	              ) : (primaryConnector.discovered_tools || []).map((tool) => {
	                const toolName = tool.name;
	                const selected = Boolean(toolName && (primaryConnector.allowed_tools || []).includes(toolName));
	                return (
	                  <button
	                    type="button"
	                    key={toolName}
	                    onClick={() => toolName && toggleAllowedMcpTool(toolName)}
	                    className={`block w-full rounded-md border px-3 py-3 text-left transition ${
	                      selected ? 'border-primary-600 bg-primary-50' : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
	                    }`}
	                  >
	                    <div className="flex items-center justify-between gap-2">
	                      <p className="truncate text-sm font-semibold text-gray-900">{toolName}</p>
	                      <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${
	                        selected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
	                      }`}>
	                        {selected ? 'Allowed' : 'Blocked'}
	                      </span>
	                    </div>
	                    {tool.description && <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{tool.description}</p>}
	                  </button>
	                );
	              })}
	            </div>
	          </Section>
	          )}
	        </div>
      )}
    </div>
  );
}
