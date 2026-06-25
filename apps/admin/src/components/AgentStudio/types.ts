import type { AzureOpenAIDeployment, Brand } from '../../api/client';

export type ContextConnectorMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ContextConnectorEndpoint {
  id: string;
  name: string;
  method: ContextConnectorMethod;
  url: string;
  enabled: boolean;
  required_fields: string[];
  description?: string;
  headers?: Record<string, any>;
  query_schema?: Record<string, any> | string;
  body_schema?: Record<string, any> | string;
  response_mapping?: Record<string, any> | string;
  timeout_seconds?: number;
  max_response_chars?: number;
  retry_count?: number;
  execution_order?: number;
  requires_prior_endpoint?: string | null;
  payload_mode?: 'wrapped' | 'flat_body';
  field_mapping?: Record<string, string>;
  runtime_required_fields?: string[];
}

export interface McpDiscoveredTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, any>;
  parameters_schema?: Record<string, any>;
}

export interface ContextConnector {
  id: string;
  type: 'http' | 'mcp';
  name: string;
  enabled: boolean;
  auth_header: string;
  auth_header_configured: boolean;
  usage: string;
  tool_description: string;
  domain_allowlist?: string[];
  input_resolution?: {
    resolve_known_places?: boolean;
    confirm_understood_details?: boolean;
    missing_input_strategy?: 'ask_follow_up' | 'strict_fields';
  };
  headers?: Record<string, any>;
  timeout_seconds?: number;
  max_response_chars?: number;
  retry_count?: number;
  endpoint?: string;
  transport?: string;
  mcp?: Record<string, any>;
  discovered_tools?: McpDiscoveredTool[];
  allowed_tools?: string[];
  last_discovered_at?: string | null;
  revoked?: boolean;
  endpoints: ContextConnectorEndpoint[];
  created_at?: string;
  updated_at?: string;
}

export interface AgentStudioData {
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
  communication_style: string;
  response_format: string;
  data_source: 'rag' | 'shopify' | 'none';
  rag_enabled: boolean;
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
  typing_indicators: boolean;
  response_streaming: boolean;
  widget_enabled: boolean;
  show_sources: boolean;
  show_product_cards: boolean;
  conversation_policy_goal?: string;
  conversation_planner_model?: string;
  conversation_required_inputs?: string;
  conversation_tool_recipes?: string;
  conversation_question_required?: boolean;
  conversation_hide_internal_sources?: boolean;
  conversation_answer_style?: string;
  context_cache_enabled?: boolean;
  context_invalidation_fields?: string;
  rate_limiting: boolean;
  content_filtering: boolean;
  session_timeout: number;
  max_conversation_length: number;
  shopify_shop_url: string;
  shopify_client_id: string;
  shopify_client_secret: string;
  shopify_client_secret_configured: boolean;
  shopify_sync_enabled: boolean;
  shopify_mcp_enabled: boolean;
  shopify_integration_mode: 'hybrid_catalog_rag_mcp' | 'storefront_ucp_mcp' | 'admin_catalog_sync';
  shopify_agent_profile_url: string;
  api_data_source_enabled: boolean;
  api_data_source_name: string;
  api_data_source_url: string;
  api_data_source_auth_header: string;
  api_data_source_auth_header_configured: boolean;
  api_data_source_usage: string;
  context_connectors?: ContextConnector[];
  url_context_boost_enabled: boolean;
}

export interface AgentStudioCommonProps {
  data: AgentStudioData;
  onChange: (field: string, value: any) => void;
  agentId?: string;
}

export interface AgentStudioFormProps extends AgentStudioCommonProps {
  brands: Brand[];
  deployments: AzureOpenAIDeployment[];
  deploymentsLoading?: boolean;
}
