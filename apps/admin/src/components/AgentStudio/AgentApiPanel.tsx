import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { XMarkIcon } from '@heroicons/react/24/outline';
import { api, AgentApiKey } from '../../api/client';
import type { AgentStudioData } from './types';

interface AgentApiPanelProps {
  open: boolean;
  agentId?: string;
  brandId?: string;
  data: AgentStudioData;
  onChange: (field: string, value: any) => void;
  onClose: () => void;
}

export default function AgentApiPanel({ open, agentId, brandId, data, onChange, onClose }: AgentApiPanelProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('Default integration key');
  const [error, setError] = useState('');

  const { data: keys = [] } = useQuery<AgentApiKey[]>({
    queryKey: ['admin', 'agent-api-keys', agentId || 'new', brandId || 'all'],
    queryFn: () => api.getAgentApiKeys({ agentId, brandId }),
    enabled: open,
  });

  const createKey = useMutation({
    mutationFn: () => api.createAgentApiKey({
      name,
      agent_id: agentId || null,
      brand_id: brandId || null,
      scopes: ['agents:read', 'messages:write', 'messages:stream', 'sessions:create', 'sessions:read'],
    }),
    onSuccess: async (key) => {
      setError('');
      if (key.key_id || key.id) {
        const nextKeyId = key.key_id || key.id;
        onChange('agent_api_key_ids', Array.from(new Set([...(data.agent_api_key_ids || []), nextKeyId])));
      }
      await queryClient.invalidateQueries({ queryKey: ['admin', 'agent-api-keys'] });
    },
    onError: (createError: any) => setError(createError?.message || 'Failed to create Agent API key.'),
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => api.revokeAgentApiKey(keyId),
    onSuccess: async () => {
      setError('');
      await queryClient.invalidateQueries({ queryKey: ['admin', 'agent-api-keys'] });
    },
    onError: (revokeError: any) => setError(revokeError?.message || 'Failed to revoke Agent API key.'),
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
      <div className="max-h-[84vh] w-full max-w-2xl overflow-hidden rounded-md bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-950">Agent API</h2>
            <p className="mt-1 text-xs text-gray-500">Create scoped keys for external systems.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900" aria-label="Close Agent API panel">
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[72vh] space-y-5 overflow-auto p-4">
          <div className="rounded-md border border-gray-200 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">Enable Agent API</p>
                <p className="mt-1 text-xs text-gray-500">Allow scoped API key access for this agent.</p>
              </div>
              <button
                type="button"
                onClick={() => onChange('agent_api_enabled', !data.agent_api_enabled)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${data.agent_api_enabled ? 'bg-gray-950' : 'bg-gray-200'}`}
              >
                <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${data.agent_api_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
              placeholder="Key name"
            />
            <button
              type="button"
              onClick={() => createKey.mutate()}
              disabled={!agentId || !name.trim() || createKey.isPending}
              className="rounded-md bg-gray-950 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
            >
              Create Key
            </button>
          </div>

          {!agentId && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Save the agent before creating agent-scoped API keys.
            </p>
          )}
          {error && <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

          <div className="space-y-2">
            {keys.length === 0 ? (
              <div className="rounded-md border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">No API keys yet.</div>
            ) : keys.map((key) => {
              const keyId = key.id || key.key_id || '';
              return (
                <div key={keyId || key.name} className="flex items-center justify-between gap-3 rounded-md border border-gray-200 px-3 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-gray-900">{key.name}</p>
                    <p className="mt-1 font-mono text-xs text-gray-500">{key.masked_key || keyId}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => keyId && revokeKey.mutate(keyId)}
                    disabled={!keyId || revokeKey.isPending}
                    className="rounded-md border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </div>
              );
            })}
          </div>

          <div className="rounded-md bg-gray-950 p-4 font-mono text-xs leading-5 text-gray-100">
            curl -X POST /api/v1/agent-api/messages \<br />
            &nbsp;&nbsp;-H "x-agent-api-key: YOUR_KEY" \<br />
            &nbsp;&nbsp;-d '{`{"agent_id":"${agentId || 'agent_id'}","message":"Hello"}`}'
          </div>
        </div>
      </div>
    </div>
  );
}
