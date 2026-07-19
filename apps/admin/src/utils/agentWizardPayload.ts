import type { CreateAgentRequest } from '../api/client';
import type { ContextConnector } from '../components/AgentStudio/types';
import { AZURE_OPENAI_PROVIDER } from './llmOptions';
import {
  buildCapabilityConfig,
  parseRequiredInputsText,
  parseStructuredField,
  parseToolRecipesText,
  serializeContextConnectors,
} from './agentWizardCodecs';

export interface AgentWizardData {
  name: string;
  description: string;
  brand_id: string;
  agent_template: string;
  purpose: string;
  role: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  system_prompt: string;
  personality_traits: string[];
  communication_style: string;
  response_format: string;
  prompt_rules: string;
  data_source_policy: string;
  runtime_variables_schema: string;
  documents: Array<{
    id: string;
    filename: string;
    size: number;
    type: string;
    status: 'uploading' | 'processing' | 'ready' | 'error';
    file?: File;
  }>;
  chunking_strategy: string;
  chunk_size: number;
  chunk_overlap: number;
  rag_enabled: boolean;
  embedding_provider: string;
  embedding_model: string;
  top_k: number;
  similarity_threshold: number;
  rerank_enabled: boolean;
  rerank_top_k: number;
  context_window: number;
  data_source: 'rag' | 'shopify' | 'none';
  shopify_shop_url: string;
  shopify_client_id: string;
  shopify_client_secret: string;
  shopify_client_secret_configured: boolean;
  shopify_sync_enabled: boolean;
  shopify_mcp_enabled: boolean;
  shopify_integration_mode: 'hybrid_catalog_rag_mcp' | 'storefront_ucp_mcp' | 'admin_catalog_sync';
  shopify_agent_profile_url: string;
  commerce_default_currency: string;
  commerce_currency_policy: string;
  commerce_source_display_policy: 'cards_only' | 'hide_sources' | 'show_sources';
  commerce_product_top_k: number;
  commerce_max_product_cards: number;
  commerce_include_out_of_stock: boolean;
  commerce_taxonomy_json: string;
  api_data_source_enabled: boolean;
  api_data_source_name: string;
  api_data_source_url: string;
  api_data_source_auth_header: string;
  api_data_source_auth_header_configured: boolean;
  api_data_source_usage: string;
  context_connectors: ContextConnector[];
  url_context_boost_enabled: boolean;
  artifacts_config: Record<string, { enabled: boolean; options?: Record<string, any> }>;
  selected_skill_ids: string[];
  selected_tool_ids: string[];
  agent_api_enabled: boolean;
  agent_api_key_ids: string[];
  agent_api_allowed_origins: string;
  agent_api_require_key: boolean;
  websockets: boolean;
  file_upload: boolean;
  human_takeover: boolean;
  conversation_memory: boolean;
  long_term_memory: boolean;
  auto_compaction: boolean;
  context_window_messages: number;
  typing_indicators: boolean;
  response_streaming: boolean;
  widget_enabled: boolean;
  show_sources: boolean;
  show_product_cards: boolean;
  activity_mode: 'basic' | 'advanced';
  activity_persistence: 'temporary' | 'persistent';
  conversation_policy_goal: string;
  conversation_planner_model: string;
  conversation_required_inputs: string;
  conversation_tool_recipes: string;
  conversation_question_required: boolean;
  conversation_hide_internal_sources: boolean;
  conversation_answer_style: string;
  context_cache_enabled: boolean;
  context_invalidation_fields: string;
  rate_limiting: boolean;
  content_filtering: boolean;
  session_timeout: number;
  max_conversation_length: number;
  allowed_file_types: string[];
  max_file_size: number;
}

export const defaultCommerceTaxonomy = {
  categories: [],
  attributes: [],
  synonyms: {},
};

export function buildAgentWizardPayload(
  agentData: AgentWizardData,
  existingConfiguration: Record<string, any> = {},
): CreateAgentRequest {
  const existingDomain = existingConfiguration.domain && typeof existingConfiguration.domain === 'object'
    ? existingConfiguration.domain
    : {};
  const isCommerceAgent = agentData.agent_template === 'ecommerce'
    || agentData.agent_template === 'ecommerce_sales'
    || agentData.data_source === 'shopify';
  const configuredDefaultCurrency = (agentData.commerce_default_currency || '').trim().toUpperCase();
  const commerceConfig = isCommerceAgent ? {
    enabled: true,
    default_currency: configuredDefaultCurrency || undefined,
    currency_policy: agentData.commerce_currency_policy || 'catalog_first_config_fallback',
    display_policy: {
      source_display_policy: agentData.commerce_source_display_policy || 'cards_only',
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
  } : existingConfiguration.commerce;

  return {
    brand_id: agentData.brand_id,
    name: agentData.name,
    description: agentData.description,
    system_prompt: agentData.system_prompt,
    status: 'active',
    metadata: {
      purpose: agentData.purpose,
      role: agentData.role,
    },
    configuration: {
      llm: {
        provider: AZURE_OPENAI_PROVIDER,
        model: agentData.model,
        temperature: agentData.temperature,
        max_tokens: agentData.max_tokens,
        top_p: agentData.top_p,
        frequency_penalty: agentData.frequency_penalty,
        presence_penalty: agentData.presence_penalty,
      },
      personality: {
        traits: agentData.personality_traits || [],
        communication_style: agentData.communication_style,
        response_format: agentData.response_format,
      },
      prompt_layers: {
        version: 'layers:v1',
        soul: agentData.system_prompt,
        duties: {
          name: agentData.name,
          description: agentData.description,
          brand_id: agentData.brand_id,
          purpose: agentData.purpose,
          role: agentData.role,
        },
        rules: parseStructuredField(agentData.prompt_rules, {}),
        data_source_policy: parseStructuredField(agentData.data_source_policy, {}),
        runtime_variables_schema: parseStructuredField(agentData.runtime_variables_schema, {}),
      },
      manifest: {
        version: 'agentbuilder/v1',
        kind: 'agent',
        portable: true,
      },
      domain: {
        type: (agentData.agent_template === 'ecommerce' || agentData.agent_template === 'ecommerce_sales')
          ? 'ecommerce'
          : (agentData.agent_template === 'astrology_lalkitab' ? 'astrology' : 'generic'),
        template: agentData.agent_template || 'generic',
        verticals: Array.isArray(existingDomain.verticals) ? existingDomain.verticals : [],
      },
      rag: (agentData.data_source === 'rag' || (agentData.data_source === 'shopify' && agentData.shopify_integration_mode !== 'storefront_ucp_mcp')) ? {
        enabled: true,
        embedding: {
          provider: agentData.embedding_provider,
          model: agentData.embedding_model,
        },
        retrieval: {
          top_k: agentData.top_k,
          similarity_threshold: agentData.similarity_threshold,
          context_window: agentData.context_window,
          rerank: {
            enabled: agentData.rerank_enabled,
            top_k: agentData.rerank_top_k,
          },
        },
        chunking: {
          strategy: agentData.chunking_strategy,
          chunk_size: agentData.chunk_size,
          chunk_overlap: agentData.chunk_overlap,
        },
      } : {
        enabled: false,
      },
      data_source: agentData.data_source,
      shopify: agentData.data_source === 'shopify' ? {
        shop_url: agentData.shopify_shop_url,
        client_id: agentData.shopify_client_id,
        client_secret: agentData.shopify_client_secret,
        sync_enabled: agentData.shopify_sync_enabled,
        mcp_enabled: agentData.shopify_mcp_enabled,
        integration_mode: agentData.shopify_integration_mode,
        agent_profile_url: agentData.shopify_agent_profile_url,
      } : undefined,
      commerce: commerceConfig,
      artifacts: (agentData.artifacts_config && Object.keys(agentData.artifacts_config).length)
        ? agentData.artifacts_config
        : existingConfiguration.artifacts,
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
          use_connectors_when_needed: (agentData.context_connectors || []).some(connector => connector.enabled && !connector.revoked),
        },
        memory_policy: {
          cache_evidence: agentData.context_cache_enabled,
          invalidation_fields: agentData.context_invalidation_fields
            .split(',')
            .map(field => field.trim())
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
      memory: {
        short_term: {
          enabled: agentData.conversation_memory,
          mode: 'conversation_history',
          retention: 'session',
          auto_compaction: agentData.auto_compaction,
          window_messages: agentData.context_window_messages,
        },
        long_term: {
          enabled: agentData.long_term_memory,
          status: agentData.long_term_memory ? 'enabled' : 'needs_privacy_setup',
        },
      },
      skills: buildCapabilityConfig(existingConfiguration.skills, agentData.selected_skill_ids, 'skill_id'),
      tools: buildCapabilityConfig(existingConfiguration.tools, agentData.selected_tool_ids, 'tool_id'),
      agent_api: {
        enabled: agentData.agent_api_enabled,
        key_ids: agentData.agent_api_key_ids,
        allowed_origins: agentData.agent_api_allowed_origins
          .split(/[\n,]/)
          .map(origin => origin.trim())
          .filter(Boolean),
        require_key: agentData.agent_api_require_key,
      },
      channels: {
        ...(existingConfiguration.channels || {}),
        widget: {
          ...((existingConfiguration.channels || {}).widget || {}),
          enabled: agentData.widget_enabled,
          preview_enabled: agentData.widget_enabled,
          allowed_origins: ((existingConfiguration.channels || {}).widget || {}).allowed_origins || [],
          show_sources: agentData.show_sources,
          show_product_cards: agentData.show_product_cards,
          human_takeover: agentData.human_takeover,
          activity_mode: agentData.activity_mode,
          activity_persistence: agentData.activity_persistence,
        },
      },
      features: {
        websockets: agentData.websockets,
        file_upload: agentData.file_upload ? {
          enabled: true,
          allowed_types: agentData.allowed_file_types || [],
          max_size_mb: agentData.max_file_size || 10,
        } : {
          enabled: false,
        },
        conversation_memory: agentData.conversation_memory,
        human_takeover: agentData.human_takeover,
        typing_indicators: agentData.typing_indicators,
        response_streaming: agentData.response_streaming,
        show_sources: agentData.show_sources,
        show_product_cards: agentData.show_product_cards,
      },
      security: {
        rate_limiting: agentData.rate_limiting,
        content_filtering: agentData.content_filtering,
        session_timeout: agentData.session_timeout,
        max_conversation_length: agentData.max_conversation_length,
      },
    },
  };
}
