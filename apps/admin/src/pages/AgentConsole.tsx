import React from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeftIcon,
  CircleStackIcon,
  CommandLineIcon,
  CubeTransparentIcon,
  ShieldCheckIcon,
} from '@heroicons/react/24/outline';
import { api, Agent } from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import AgentInferenceTester from '../components/AgentStudio/AgentInferenceTester';
import { canAccessAgentConsole } from '../utils/rbac';

function capabilityCount(agent?: Agent): string {
  const config = agent?.configuration || {};
  const skills = Array.isArray(config.skills?.selected) ? config.skills.selected.length : 0;
  const tools = Array.isArray(config.tools?.selected) ? config.tools.selected.length : 0;
  return `${skills} skills / ${tools} tools`;
}

export default function AgentConsole() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const allowed = canAccessAgentConsole(user);
  const { data: agents = [], isLoading, error } = useQuery<Agent[]>({
    queryKey: ['admin', 'console', 'agents'],
    queryFn: api.getConsoleAgents,
    enabled: allowed,
  });

  if (!allowed) {
    return <Navigate to="/dashboard" replace />;
  }

  const selectedAgent = agents.find(agent => agent.id === agentId);

  return (
    <div className="mx-auto max-w-[1680px] space-y-4">
      <div className="flex flex-col gap-3 border-b border-gray-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/agents')}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            aria-label="Back to agents"
          >
            <ArrowLeftIcon className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-2xl font-bold text-gray-900">Agent Console</h1>
              <span className="rounded bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">RBAC protected</span>
            </div>
            <p className="mt-1 truncate text-sm text-gray-500">
              Test, observe, and debug live agent runtime behavior.
            </p>
          </div>
        </div>
        {selectedAgent && (
          <Link
            to={`/agents/${selectedAgent.id}/edit`}
            className="inline-flex h-9 items-center justify-center rounded-md border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            Edit configuration
          </Link>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-4 py-3">
            <p className="text-sm font-semibold text-gray-900">Agents</p>
            <p className="mt-1 text-xs text-gray-500">Choose an agent to open its runtime console.</p>
          </div>
          <div className="max-h-[calc(100vh-210px)] overflow-auto p-2">
            {isLoading && (
              <div className="space-y-2 p-2">
                <div className="h-16 rounded bg-gray-100" />
                <div className="h-16 rounded bg-gray-100" />
              </div>
            )}
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                Failed to load console agents.
              </div>
            )}
            {!isLoading && agents.length === 0 && (
              <div className="rounded-md border border-dashed border-gray-200 p-4 text-sm text-gray-500">
                No agents are available yet.
              </div>
            )}
            <div className="space-y-2">
              {agents.map(agent => {
                const selected = agent.id === agentId;
                return (
                  <Link
                    key={agent.id}
                    to={`/agent-console/${agent.id}`}
                    className={`block rounded-md border p-3 transition ${
                      selected ? 'border-primary-600 bg-primary-50 text-gray-900' : 'border-gray-200 bg-white text-gray-900 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <span className={`inline-flex h-9 w-9 flex-none items-center justify-center rounded-md ${selected ? 'bg-primary-100 text-primary-700' : 'bg-gray-100'}`}>
                        <CubeTransparentIcon className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{agent.name}</p>
                        <p className={`mt-1 truncate text-xs ${selected ? 'text-gray-600' : 'text-gray-500'}`}>{agent.brand_slug || agent.brand_id}</p>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </aside>

        <main className="min-w-0">
          {!agentId ? (
            <div className="flex min-h-[620px] items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center">
              <div className="max-w-sm">
                <CommandLineIcon className="mx-auto h-10 w-10 text-gray-400" />
                <h2 className="mt-4 text-lg font-semibold text-gray-900">Select an agent</h2>
                <p className="mt-2 text-sm leading-6 text-gray-500">
                  Agent Console is separate from configuration. Pick a saved agent to stream a test answer and inspect runtime context.
                </p>
              </div>
            </div>
          ) : selectedAgent ? (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    <ShieldCheckIcon className="h-4 w-4" />
                    Status
                  </p>
                  <p className="mt-2 text-sm font-medium text-gray-900">{selectedAgent.status}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    <CircleStackIcon className="h-4 w-4" />
                    Context
                  </p>
                  <p className="mt-2 text-sm font-medium text-gray-900">{selectedAgent.configuration?.rag?.enabled ? 'Knowledge enabled' : 'Workspace only'}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    <CommandLineIcon className="h-4 w-4" />
                    Capabilities
                  </p>
                  <p className="mt-2 text-sm font-medium text-gray-900">{capabilityCount(selectedAgent)}</p>
                </div>
              </div>
              <AgentInferenceTester
                agentId={selectedAgent.id}
                agentName={selectedAgent.name}
                streamEndpoint={`/api/v1/admin/console/agents/${selectedAgent.id}/messages/stream`}
                conversationIdPrefix="agent-console"
              />
            </div>
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              This agent is not available to the current workspace or role.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
