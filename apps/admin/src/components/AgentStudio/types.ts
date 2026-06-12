import type { AzureOpenAIDeployment, Brand } from '../../api/client';

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
  show_sources: boolean;
  show_product_cards: boolean;
  rate_limiting: boolean;
  content_filtering: boolean;
  session_timeout: number;
  max_conversation_length: number;
  shopify_shop_url: string;
  shopify_access_token: string;
  shopify_access_token_configured: boolean;
  api_data_source_enabled: boolean;
  api_data_source_name: string;
  api_data_source_url: string;
  api_data_source_auth_header: string;
  api_data_source_auth_header_configured: boolean;
  api_data_source_usage: string;
  url_context_boost_enabled: boolean;
}

export interface AgentStudioCommonProps {
  data: AgentStudioData;
  onChange: (field: string, value: any) => void;
}

export interface AgentStudioFormProps extends AgentStudioCommonProps {
  brands: Brand[];
  deployments: AzureOpenAIDeployment[];
  deploymentsLoading?: boolean;
}
