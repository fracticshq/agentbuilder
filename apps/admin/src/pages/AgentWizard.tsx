import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, documentApi } from '../api/client';
import { showErrorAlert } from '../api/errorHandler';
import AgentApiPanel from '../components/AgentStudio/AgentApiPanel';
import AgentCapabilityRail from '../components/AgentStudio/AgentCapabilityRail';
import AgentConfigForm from '../components/AgentStudio/AgentConfigForm';
import AgentJsonModal from '../components/AgentStudio/AgentJsonModal';
import AgentManagePanel from '../components/AgentStudio/AgentManagePanel';
import AgentSetupPanel from '../components/AgentStudio/AgentSetupPanel';
import AgentStudioShell from '../components/AgentStudio/AgentStudioShell';
import VersionHistoryPanel from '../components/AgentStudio/VersionHistoryPanel';
import { useAgentWizardController } from '../hooks/useAgentWizardController';
import {
  parseRequiredInputsText,
  parseStructuredField,
  parseToolRecipesText,
  serializeContextConnectors,
} from '../utils/agentWizardCodecs';
import { buildAgentWizardPayload, defaultCommerceTaxonomy } from '../utils/agentWizardPayload';
import { buildWidgetUrl } from '../utils/widget';

const isDev = import.meta.env.DEV;

export default function AgentWizard() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    agentData,
    brands,
    azureDeployments,
    existingAgent,
    updateStepData,
    createAgentMutation,
  } = useAgentWizardController(id);
  const [isDeploying, setIsDeploying] = useState(false);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [agentApiOpen, setAgentApiOpen] = useState(false);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleDeploy = async () => {
    setIsDeploying(true);
    try {
      const apiPayload = buildAgentWizardPayload(agentData, existingAgent?.configuration || {});

      isDev && console.log('🚀 Deploying agent with complete payload:', JSON.stringify(apiPayload, null, 2));
      const createdAgent = await createAgentMutation.mutateAsync(apiPayload);
      isDev && console.log('✅ Agent created successfully:', createdAgent);

      // Upload documents if any exist with File objects.
      isDev && console.log('📦 Checking documents:', agentData.documents);
      if (agentData.documents && agentData.documents.length > 0) {
        isDev && console.log('📄 Total documents:', agentData.documents.length);
        const filesToUpload = agentData.documents
          .filter((document): document is typeof document & { file: File } => {
            isDev && console.log('Document file availability', { hasFile: Boolean(document.file) });
            return Boolean(document.file);
          })
          .map((document) => document.file);

        isDev && console.log('📤 Files to upload:', filesToUpload.length, filesToUpload.map((file) => file.name));
        if (filesToUpload.length > 0) {
          isDev && console.log('📄 Uploading documents for agent:', createdAgent.id);
          try {
            const uploadResult = await documentApi.uploadDocuments(filesToUpload, {
              agent_id: createdAgent.id,
              category: 'knowledge_base',
              document_type: 'other',
            });
            isDev && console.log('✅ Documents uploaded successfully:', uploadResult);
          } catch (documentError) {
            console.error('❌ Failed to upload documents:', documentError);
            // Do not fail the agent deployment if document upload fails.
          }
        } else {
          isDev && console.log('ℹ️ No files with File objects to upload');
        }
      } else {
        isDev && console.log('ℹ️ No documents in agentData');
      }

      localStorage.removeItem('agent_wizard_draft');
      navigate(`/agents/${createdAgent.id}`, {
        state: {
          deployedAgent: {
            id: createdAgent.id,
            name: createdAgent.name,
            url: buildWidgetUrl(createdAgent.id),
          },
        },
      });
    } catch (error) {
      console.error('❌ Deploy error:', error);
      if (error instanceof Error) {
        showErrorAlert(error);
      } else {
        alert('An unexpected error occurred during deployment');
      }
    } finally {
      setIsDeploying(false);
    }
  };

  const handleExport = async () => {
    if (!id) return;
    setExportError(null);
    try {
      const blob = await api.exportAgentManifest(id);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${agentData.name || 'agent'}-manifest.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error: any) {
      setExportError(error?.message || 'Failed to export agent manifest.');
    }
  };

  const viewJsonData = {
    id: id || null,
    mode: id ? 'manage' : 'create',
    agent: {
      name: agentData.name,
      description: agentData.description,
      brand_id: agentData.brand_id,
      template: agentData.agent_template,
      purpose: agentData.purpose,
      role: agentData.role,
      system_prompt: agentData.system_prompt,
    },
    configuration: {
      llm: {
        provider: agentData.provider,
        model: agentData.model,
        temperature: agentData.temperature,
        max_tokens: agentData.max_tokens,
      },
      data_source: agentData.data_source,
      shopify: agentData.data_source === 'shopify' ? {
        shop_url: agentData.shopify_shop_url,
        client_id: agentData.shopify_client_id,
        client_secret_configured: agentData.shopify_client_secret_configured,
        sync_enabled: agentData.shopify_sync_enabled,
        mcp_enabled: agentData.shopify_mcp_enabled,
        integration_mode: agentData.shopify_integration_mode,
        agent_profile_url: agentData.shopify_agent_profile_url,
      } : undefined,
      commerce: (agentData.agent_template === 'ecommerce' || agentData.agent_template === 'ecommerce_sales' || agentData.data_source === 'shopify') ? {
        enabled: true,
        default_currency: (agentData.commerce_default_currency || '').trim().toUpperCase() || undefined,
        currency_policy: agentData.commerce_currency_policy || 'catalog_first_config_fallback',
        display_policy: {
          source_display_policy: agentData.commerce_source_display_policy,
          show_sources: agentData.show_sources,
          show_product_cards: agentData.show_product_cards,
          cards_only: agentData.commerce_source_display_policy === 'cards_only',
        },
        retrieval: {
          product_top_k: agentData.commerce_product_top_k,
          max_product_cards: agentData.commerce_max_product_cards,
          include_out_of_stock: agentData.commerce_include_out_of_stock,
        },
        taxonomy: parseStructuredField(agentData.commerce_taxonomy_json, defaultCommerceTaxonomy),
      } : undefined,
      artifacts: agentData.artifacts_config,
      skills: { selected: agentData.selected_skill_ids },
      tools: { selected: agentData.selected_tool_ids },
      agent_api: {
        enabled: agentData.agent_api_enabled,
        key_ids: agentData.agent_api_key_ids,
        allowed_origins: agentData.agent_api_allowed_origins,
        require_key: agentData.agent_api_require_key,
      },
      context_connectors: serializeContextConnectors(agentData.context_connectors),
      conversation_policy: {
        goal: agentData.conversation_policy_goal || agentData.purpose || agentData.description,
        planner_model: agentData.conversation_planner_model || undefined,
        required_inputs: parseRequiredInputsText(agentData.conversation_required_inputs),
        question_required: agentData.conversation_question_required,
        input_extraction_hints: {
          infer_unlabeled_values: true,
        },
        answer_style: agentData.conversation_answer_style || 'helpful',
        public_progress_style: {
          initial_label: 'Reading your message',
          initial_summary: 'I’m checking what is needed before answering.',
        },
        tool_recipes: parseToolRecipesText(agentData.conversation_tool_recipes),
        hide_internal_sources: agentData.conversation_hide_internal_sources,
        context_policy: {
          lazy_context: true,
          use_knowledge_when_needed: agentData.rag_enabled,
          use_connectors_when_needed: (agentData.context_connectors || []).some((connector) => connector.enabled && !connector.revoked),
        },
        memory_policy: {
          cache_evidence: agentData.context_cache_enabled,
          invalidation_fields: agentData.context_invalidation_fields
            .split(',')
            .map((field) => field.trim())
            .filter(Boolean),
        },
        allowed_capabilities: [
          ...(agentData.selected_skill_ids || []),
          ...(agentData.selected_tool_ids || []),
        ],
      },
      url_context_boost: {
        enabled: agentData.url_context_boost_enabled,
      },
      features: {
        conversation_memory: agentData.conversation_memory,
        file_upload: agentData.file_upload,
        human_takeover: agentData.human_takeover,
        response_streaming: agentData.response_streaming,
        show_sources: agentData.show_sources,
        content_filtering: agentData.content_filtering,
      },
      memory: {
        short_term: {
          enabled: agentData.conversation_memory,
          mode: 'conversation_history',
          retention: 'session',
        },
        long_term: {
          enabled: agentData.long_term_memory,
          status: agentData.long_term_memory ? 'enabled' : 'needs_privacy_setup',
        },
      },
    },
  };

  return (
    <>
      {exportError && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {exportError}
        </div>
      )}
      <AgentStudioShell
        mode={id ? 'manage' : 'create'}
        title={id ? 'Manage Nova Agent' : 'Create Nova Agent'}
        subtitle={agentData.name || 'Configure a generalized portable agent'}
        saving={isDeploying}
        canExport={Boolean(id)}
        onBack={() => navigate('/agents')}
        onSave={handleDeploy}
        onViewJson={() => setJsonOpen(true)}
        onAgentApi={() => setAgentApiOpen(true)}
        onOpenConsole={id ? () => navigate(`/agent-console/${id}`) : undefined}
        onVersionHistory={() => setVersionHistoryOpen(true)}
        onExport={handleExport}
        left={(
          <AgentConfigForm
            data={agentData}
            onChange={updateStepData}
            brands={brands}
            deployments={azureDeployments?.deployments || []}
          />
        )}
        middle={<AgentCapabilityRail data={agentData} onChange={updateStepData} agentId={id} />}
        right={id ? (
          <AgentManagePanel
            data={agentData}
            onChange={updateStepData}
            agentId={id}
            agentStatus={existingAgent?.status}
            onOpenConsole={() => navigate(`/agent-console/${id}`)}
          />
        ) : (
          <AgentSetupPanel data={agentData} saving={isDeploying} onCreate={handleDeploy} />
        )}
      />

      <AgentJsonModal
        open={jsonOpen}
        title="Agent Configuration JSON"
        data={viewJsonData}
        onClose={() => setJsonOpen(false)}
      />
      <AgentApiPanel
        open={agentApiOpen}
        agentId={id}
        brandId={agentData.brand_id}
        data={agentData}
        onChange={updateStepData}
        onClose={() => setAgentApiOpen(false)}
      />
      <VersionHistoryPanel
        open={versionHistoryOpen}
        onClose={() => setVersionHistoryOpen(false)}
      />
    </>
  );
}
