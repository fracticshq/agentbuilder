/**
 * YAML Configuration Generator for AI Agents
 * 
 * Converts wizard form data into properly formatted YAML configuration files
 * that match the agent configuration schema defined in AGENTS.md
 */

export interface AgentConfig {
  // Basic Info
  name: string;
  description: string;
  brand_id: string;
  purpose?: string;
  role?: string;
  
  // LLM Config
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  top_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  
  // System Prompt
  system_prompt: string;
  personality_traits?: string[];
  communication_style?: string;
  response_format?: string;
  
  // RAG Config
  rag_enabled: boolean;
  embedding_provider?: string;
  embedding_model?: string;
  top_k?: number;
  similarity_threshold?: number;
  rerank_enabled?: boolean;
  rerank_top_k?: number;
  context_window?: number;
  chunking_strategy?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  
  // Features
  websockets?: boolean;
  file_upload?: boolean;
  conversation_memory?: boolean;
  typing_indicators?: boolean;
  response_streaming?: boolean;
  allowed_file_types?: string[];
  max_file_size?: number;
  
  // Security
  rate_limiting?: boolean;
  content_filtering?: boolean;
  session_timeout?: number;
  max_conversation_length?: number;
}

/**
 * Generate a JSON configuration object from agent data
 */
export function generateConfigObject(data: AgentConfig): Record<string, any> {
  const config: Record<string, any> = {
    metadata: {
      name: data.name,
      description: data.description,
      brand_id: data.brand_id,
      version: "1.0.0",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
  };

  // Add optional metadata fields
  if (data.purpose) {
    config.metadata.purpose = data.purpose;
  }
  if (data.role) {
    config.metadata.role = data.role;
  }

  // LLM Configuration
  config.configuration = {
    llm: {
      provider: data.provider,
      model: data.model,
      temperature: data.temperature,
      max_tokens: data.max_tokens,
    }
  };

  // Add optional LLM parameters
  if (data.top_p !== undefined && data.top_p !== 1.0) {
    config.configuration.llm.top_p = data.top_p;
  }
  if (data.frequency_penalty !== undefined && data.frequency_penalty !== 0.0) {
    config.configuration.llm.frequency_penalty = data.frequency_penalty;
  }
  if (data.presence_penalty !== undefined && data.presence_penalty !== 0.0) {
    config.configuration.llm.presence_penalty = data.presence_penalty;
  }

  // System Prompt
  config.system_prompt = data.system_prompt;

  // Personality Configuration
  if (data.personality_traits?.length || data.communication_style || data.response_format) {
    config.configuration.personality = {};
    
    if (data.personality_traits?.length) {
      config.configuration.personality.traits = data.personality_traits;
    }
    if (data.communication_style) {
      config.configuration.personality.communication_style = data.communication_style;
    }
    if (data.response_format) {
      config.configuration.personality.response_format = data.response_format;
    }
  }

  // RAG Configuration
  if (data.rag_enabled) {
    config.configuration.rag = {
      enabled: true,
      embedding: {
        provider: data.embedding_provider || 'voyage',
        model: data.embedding_model || 'voyage-large-2-instruct',
      },
      retrieval: {
        top_k: data.top_k || 5,
        similarity_threshold: data.similarity_threshold || 0.7,
        context_window: data.context_window || 2000,
      },
      chunking: {
        strategy: data.chunking_strategy || 'semantic',
        chunk_size: data.chunk_size || 400,
        chunk_overlap: data.chunk_overlap || 50,
      }
    };

    // Add reranking if enabled
    if (data.rerank_enabled) {
      config.configuration.rag.retrieval.rerank = {
        enabled: true,
        top_k: data.rerank_top_k || 3,
      };
    }
  } else {
    config.configuration.rag = { enabled: false };
  }

  // Features Configuration
  config.configuration.features = {
    websockets: data.websockets ?? true,
    conversation_memory: data.conversation_memory ?? true,
    typing_indicators: data.typing_indicators ?? true,
    response_streaming: data.response_streaming ?? true,
  };

  // File upload configuration
  if (data.file_upload) {
    config.configuration.features.file_upload = {
      enabled: true,
      allowed_types: data.allowed_file_types || ['pdf', 'txt', 'md', 'docx'],
      max_size_mb: data.max_file_size || 10,
    };
  } else {
    config.configuration.features.file_upload = { enabled: false };
  }

  // Security Configuration
  config.configuration.security = {
    rate_limiting: data.rate_limiting ?? true,
    content_filtering: data.content_filtering ?? true,
    session_timeout_minutes: data.session_timeout || 30,
    max_conversation_length: data.max_conversation_length || 50,
  };

  return config;
}

/**
 * Generate YAML string from agent configuration
 */
export function generateYAML(data: AgentConfig): string {
  const config = generateConfigObject(data);
  return convertToYAML(config, 0);
}

/**
 * Convert a JavaScript object to YAML format
 * (Simple implementation - for production, consider using a library like js-yaml)
 */
function convertToYAML(obj: any, indent: number = 0): string {
  const spaces = '  '.repeat(indent);
  let yaml = '';

  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined) {
      continue;
    }

    if (typeof value === 'object' && !Array.isArray(value)) {
      yaml += `${spaces}${key}:\n`;
      yaml += convertToYAML(value, indent + 1);
    } else if (Array.isArray(value)) {
      yaml += `${spaces}${key}:\n`;
      const arrayItems = value.map(item => {
        if (typeof item === 'object') {
          return `${spaces}  -\n${convertToYAML(item, indent + 2)}`;
        } else {
          return `${spaces}  - ${formatValue(item)}\n`;
        }
      }).join('');
      yaml += arrayItems;
    } else {
      yaml += `${spaces}${key}: ${formatValue(value)}\n`;
    }
  }

  return yaml;
}

/**
 * Format a value for YAML output
 */
function formatValue(value: any): string {
  if (typeof value === 'string') {
    // Check if string needs quotes
    if (value.includes('\n') || value.includes(':') || value.includes('#')) {
      // Multi-line string
      return `|\n${value.split('\n').map(line => '  ' + line).join('\n')}`;
    }
    return `"${value}"`;
  }
  if (typeof value === 'boolean') {
    return value.toString();
  }
  if (typeof value === 'number') {
    return value.toString();
  }
  return String(value);
}

/**
 * Download YAML configuration as a file
 */
export function downloadYAML(data: AgentConfig): void {
  const yaml = generateYAML(data);
  const blob = new Blob([yaml], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${data.name.toLowerCase().replace(/\s+/g, '-')}-agent.yaml`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Copy YAML configuration to clipboard
 */
export async function copyYAMLToClipboard(data: AgentConfig): Promise<boolean> {
  try {
    const yaml = generateYAML(data);
    await navigator.clipboard.writeText(yaml);
    return true;
  } catch (error) {
    console.error('Failed to copy to clipboard:', error);
    return false;
  }
}

/**
 * Generate a compact JSON representation (for API calls)
 */
export function generateAPIPayload(data: AgentConfig): Record<string, any> {
  return {
    brand_id: data.brand_id,
    name: data.name,
    description: data.description,
    system_prompt: data.system_prompt,
    metadata: {
      purpose: data.purpose,
      role: data.role,
    },
    configuration: {
      llm: {
        provider: data.provider,
        model: data.model,
        temperature: data.temperature,
        max_tokens: data.max_tokens,
        top_p: data.top_p,
        frequency_penalty: data.frequency_penalty,
        presence_penalty: data.presence_penalty,
      },
      personality: {
        traits: data.personality_traits || [],
        communication_style: data.communication_style,
        response_format: data.response_format,
      },
      rag: data.rag_enabled ? {
        enabled: true,
        embedding: {
          provider: data.embedding_provider,
          model: data.embedding_model,
        },
        retrieval: {
          top_k: data.top_k,
          similarity_threshold: data.similarity_threshold,
          context_window: data.context_window,
          rerank: {
            enabled: data.rerank_enabled,
            top_k: data.rerank_top_k,
          },
        },
        chunking: {
          strategy: data.chunking_strategy,
          chunk_size: data.chunk_size,
          chunk_overlap: data.chunk_overlap,
        },
      } : {
        enabled: false,
      },
      features: {
        websockets: data.websockets,
        file_upload: data.file_upload ? {
          enabled: true,
          allowed_types: data.allowed_file_types || [],
          max_size_mb: data.max_file_size || 10,
        } : {
          enabled: false,
        },
        conversation_memory: data.conversation_memory,
        typing_indicators: data.typing_indicators,
        response_streaming: data.response_streaming,
      },
      security: {
        rate_limiting: data.rate_limiting,
        content_filtering: data.content_filtering,
        session_timeout: data.session_timeout,
        max_conversation_length: data.max_conversation_length,
      },
    },
  };
}

/**
 * Validate agent configuration
 */
export function validateAgentConfig(data: Partial<AgentConfig>): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  // Required fields
  if (!data.name?.trim()) {
    errors.push('Agent name is required');
  }
  if (!data.description?.trim()) {
    errors.push('Agent description is required');
  }
  if (!data.brand_id) {
    errors.push('Brand selection is required');
  }
  if (!data.provider) {
    errors.push('LLM provider is required');
  }
  if (!data.model) {
    errors.push('LLM model is required');
  }
  if (!data.system_prompt?.trim()) {
    errors.push('System prompt is required');
  }

  // Validate numeric ranges
  if (data.temperature !== undefined && (data.temperature < 0 || data.temperature > 2)) {
    errors.push('Temperature must be between 0 and 2');
  }
  if (data.max_tokens !== undefined && data.max_tokens < 1) {
    errors.push('Max tokens must be at least 1');
  }
  if (data.top_p !== undefined && (data.top_p < 0 || data.top_p > 1)) {
    errors.push('Top-p must be between 0 and 1');
  }

  // RAG validation
  if (data.rag_enabled) {
    if (!data.embedding_provider) {
      errors.push('Embedding provider is required when RAG is enabled');
    }
    if (!data.embedding_model) {
      errors.push('Embedding model is required when RAG is enabled');
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
