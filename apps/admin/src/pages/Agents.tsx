import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { PlusIcon, CpuChipIcon, TrashIcon, PencilIcon, CheckCircleIcon, XCircleIcon, ArrowTopRightOnSquareIcon, ClipboardDocumentIcon } from '@heroicons/react/24/outline';
import { api, Agent } from '../api/client';
import { ApiError, showErrorAlert } from '../api/errorHandler';
import { getModelLabel, getProviderLabel } from '../utils/llmOptions';
import { buildEmbedCode, buildWidgetUrl, getWidgetBaseUrl, getWidgetChannel } from '../utils/widget';

export default function Agents() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [deploymentSuccess, setDeploymentSuccess] = useState<{
    id: string;
    name: string;
    url: string;
  } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  // Check for deployment success from navigation state
  useEffect(() => {
    if (location.state?.deployedAgent) {
      setDeploymentSuccess(location.state.deployedAgent);
      // Clear the state
      window.history.replaceState({}, document.title);
    }
  }, [location]);

  // Fetch agents from API
  const { data: agents = [], isLoading, error } = useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: () => api.getAgents(),
  });

  const { data: azureDeployments } = useQuery({
    queryKey: ['admin', 'azure-openai-deployments'],
    queryFn: api.getAzureDeployments,
    staleTime: 60_000,
    retry: false,
  });

  // Mutation for changing agent status
  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'active' | 'inactive' | 'draft' }) =>
      api.updateAgent(id, { status } as any),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    },
    onError: (error) => {
      console.error('Failed to update agent status:', error);
      showErrorAlert(error as Error);
    },
  });

  // Mutation for deleting agent
  const deleteAgentMutation = useMutation({
    mutationFn: (id: string) => api.deleteAgent(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    },
    onError: (error) => {
      console.error('Failed to delete agent:', error);
      showErrorAlert(error as Error);
    },
  });

  const toggleAgentStatus = (agent: Agent) => {
    const newStatus = agent.status === 'active' ? 'inactive' : 'active';
    updateStatusMutation.mutate({ id: agent.id, status: newStatus });
  };

  const widgetUrlFor = (agentId: string) => buildWidgetUrl(agentId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary-600 border-r-transparent"></div>
          <p className="mt-2 text-sm text-gray-600">Loading agents...</p>
        </div>
      </div>
    );
  }

  if (error) {
    const apiError = error as ApiError;
    return (
      <div className="rounded-md bg-red-50 p-4">
        <div className="flex">
          <div className="ml-3 flex-1">
            <h3 className="text-sm font-medium text-red-800">Error loading agents</h3>
            <div className="mt-2 text-sm text-red-700">
              <p>{apiError.message || (error as Error).message}</p>
              {apiError.details && (
                <p className="mt-1 text-xs text-red-600">{apiError.details}</p>
              )}
            </div>
            <div className="mt-4">
              <button
                onClick={() => queryClient.invalidateQueries({ queryKey: ['agents'] })}
                className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
              >
                Try Again
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Deployment Success Banner */}
      {deploymentSuccess && (
        <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <CheckCircleIcon className="h-5 w-5 flex-none text-emerald-600" />
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-gray-900">
                Agent "{deploymentSuccess.name}" deployed
              </h3>
              <p className="mt-1 text-sm text-gray-600">
                Your agent is live. Embed the widget on your site or open the preview to test it.
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <a
                  href={deploymentSuccess.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-500"
                >
                  <ArrowTopRightOnSquareIcon className="h-4 w-4" />
                  Open widget preview
                </a>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(deploymentSuccess.url);
                    setCopied(`deploy-url-${deploymentSuccess.id}`);
                    window.setTimeout(() => setCopied(null), 2000);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50"
                >
                  <ClipboardDocumentIcon className="h-4 w-4" />
                  {copied === `deploy-url-${deploymentSuccess.id}` ? 'Copied' : 'Copy URL'}
                </button>
              </div>
            </div>
            <button
              onClick={() => setDeploymentSuccess(null)}
              className="flex-none rounded-md px-2 py-1 text-sm font-medium text-gray-500 hover:bg-white hover:text-gray-900"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-bold text-gray-900">Agents</h1>
          <p className="mt-2 text-sm text-gray-700">
            Manage your AI agents and their configurations. {agents.length > 0 && `(${agents.length} agent${agents.length !== 1 ? 's' : ''})`}
          </p>
        </div>
        <div className="mt-4 sm:ml-16 sm:mt-0 sm:flex-none">
          <Link
            to="/agents/new"
            className="inline-flex items-center gap-x-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500"
          >
            <PlusIcon className="-ml-0.5 h-5 w-5" aria-hidden="true" />
            New Agent
          </Link>
        </div>
      </div>

      {agents.length === 0 ? (
        <div className="text-center py-12">
          <CpuChipIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-semibold text-gray-900">No agents</h3>
          <p className="mt-1 text-sm text-gray-500">Get started by creating your first AI agent.</p>
          <div className="mt-6">
            <Link
              to="/agents/new"
              className="inline-flex items-center gap-x-1.5 rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500"
            >
              <PlusIcon className="-ml-0.5 h-5 w-5" aria-hidden="true" />
              Create Agent
            </Link>
          </div>
        </div>
      ) : (
        <div className="mt-8">
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent: Agent) => (
              <div
                key={agent.id}
                className="relative flex flex-col bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex-1 p-6">
                  <div className="flex items-center justify-between mb-4">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      agent.status === 'active' 
                        ? 'bg-green-100 text-green-800' 
                        : agent.status === 'draft'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      {agent.status}
                    </span>
                    <CpuChipIcon className="h-8 w-8 text-gray-400" />
                  </div>
                  
                  <h3 className="text-lg font-semibold text-gray-900 mb-2">
                    {agent.name}
                  </h3>
                  
                  <p className="text-sm text-gray-600 mb-4 line-clamp-2">
                    {agent.description || 'No description provided'}
                  </p>
                  
                  {(() => {
                    const widget = getWidgetChannel(agent.configuration);
                    const widgetReady = agent.status === 'active' && widget.enabled;
                    const widgetUrl = widgetUrlFor(agent.id);
                    const embedCode = buildEmbedCode(getWidgetBaseUrl(), agent.id);

                    return (
                      <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Widget</p>
                          <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                            widgetReady
                              ? 'bg-emerald-50 text-emerald-700'
                              : agent.status !== 'active'
                                ? 'bg-amber-50 text-amber-700'
                                : 'bg-gray-100 text-gray-600'
                          }`}>
                            {widgetReady ? 'Ready' : agent.status !== 'active' ? 'Activate first' : 'Disabled'}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {widgetReady ? (
                            <a
                              href={widgetUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 rounded-md bg-primary-600 px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-500"
                            >
                              <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5" />
                              Open widget
                            </a>
                          ) : agent.status !== 'active' ? (
                            <button
                              onClick={() => toggleAgentStatus(agent)}
                              disabled={updateStatusMutation.isPending}
                              className="inline-flex items-center gap-1.5 rounded-md border border-amber-200 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-50 disabled:opacity-50"
                            >
                              <CheckCircleIcon className="h-3.5 w-3.5" />
                              Activate to use widget
                            </button>
                          ) : (
                            <Link
                              to={`/agents/${agent.id}/edit`}
                              className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
                            >
                              <PencilIcon className="h-3.5 w-3.5" />
                              Enable in Manage Agent
                            </Link>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              navigator.clipboard.writeText(widgetUrl);
                              setCopied(`url-${agent.id}`);
                              window.setTimeout(() => setCopied(null), 2000);
                            }}
                            disabled={!widgetReady}
                            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <ClipboardDocumentIcon className="h-3.5 w-3.5" />
                            {copied === `url-${agent.id}` ? 'Copied URL' : 'Copy URL'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              navigator.clipboard.writeText(embedCode);
                              setCopied(`embed-${agent.id}`);
                              window.setTimeout(() => setCopied(null), 2000);
                            }}
                            disabled={!widgetReady}
                            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <ClipboardDocumentIcon className="h-3.5 w-3.5" />
                            {copied === `embed-${agent.id}` ? 'Copied embed' : 'Copy embed'}
                          </button>
                        </div>
                      </div>
                    );
                  })()}
                  
                  <div className="text-xs text-gray-500">
                    <p>Created: {new Date(agent.created_at).toLocaleDateString()}</p>
                    {agent.configuration?.llm && (
                      <p className="mt-1">
                        Model: {getProviderLabel(agent.configuration.llm.provider)} / {getModelLabel(agent.configuration.llm.provider, agent.configuration.llm.model, azureDeployments?.deployments)}
                      </p>
                    )}
                  </div>
                </div>
                
                <div className="border-t border-gray-200 px-6 py-3 flex items-center justify-between bg-gray-50 rounded-b-lg">
                  <div className="flex items-center space-x-3">
                    <Link
                      to={`/agents/${agent.id}/edit`}
                      className="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-700"
                    >
                      <PencilIcon className="h-4 w-4 mr-1" />
                      Edit
                    </Link>
                    <button
                      onClick={() => toggleAgentStatus(agent)}
                      disabled={updateStatusMutation.isPending}
                      className={`inline-flex items-center text-sm font-medium ${
                        agent.status === 'active'
                          ? 'text-yellow-600 hover:text-yellow-700'
                          : 'text-green-600 hover:text-green-700'
                      } disabled:opacity-50`}
                    >
                      {agent.status === 'active' ? (
                        <>
                          <XCircleIcon className="h-4 w-4 mr-1" />
                          Deactivate
                        </>
                      ) : (
                        <>
                          <CheckCircleIcon className="h-4 w-4 mr-1" />
                          Activate
                        </>
                      )}
                    </button>
                  </div>
                  <button
                    onClick={() => {
                      if (window.confirm(`Are you sure you want to delete "${agent.name}"?`)) {
                        deleteAgentMutation.mutate(agent.id);
                      }
                    }}
                    disabled={deleteAgentMutation.isPending}
                    className="inline-flex items-center text-sm font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                  >
                    <TrashIcon className="h-4 w-4 mr-1" />
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
