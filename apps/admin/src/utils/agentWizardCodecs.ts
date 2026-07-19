import type {
  ContextConnector,
  ContextConnectorEndpoint,
  ContextConnectorMethod,
} from '../components/AgentStudio/types';

type UnknownRecord = Record<string, unknown>;

export type CapabilityIdField = 'skill_id' | 'tool_id';

export interface CapabilitySelectionConfig extends UnknownRecord {
  enabled: boolean;
  selected: string[];
}

export interface RequiredConversationInput {
  id: string;
  label: string;
  type: string;
  required: true;
  aliases: string[];
}

export interface SerializedContextConnectorEndpoint {
  id: string;
  name: string;
  enabled: boolean;
  method: ContextConnectorMethod;
  url_template: string;
  required_user_fields: string[];
  headers: Record<string, unknown>;
  query_schema: Record<string, unknown> | string;
  body_schema: Record<string, unknown> | string;
  response_mapping: Record<string, unknown> | string;
  timeout_seconds?: number;
  max_response_chars?: number;
  retry_count?: number;
  execution_order?: number;
  requires_prior_endpoint: string | null;
  payload_mode?: 'wrapped' | 'flat_body';
  field_mapping: Record<string, string>;
  runtime_required_fields: string[];
  tool_description: string;
}

export type SerializedRawHeaderAuth =
  | { type: 'raw_header'; auth_header: string }
  | { type: 'raw_header'; auth_header_configured: boolean };

export interface SerializedContextConnector {
  id: string;
  name: string;
  type: 'http_api' | 'mcp';
  enabled: boolean;
  revoked: boolean;
  domain_allowlist: string[];
  input_resolution: ContextConnector['input_resolution'];
  headers: Record<string, unknown>;
  timeout_seconds?: number;
  max_response_chars?: number;
  retry_count?: number;
  auth: SerializedRawHeaderAuth;
  usage_policy: string;
  endpoint?: string;
  transport?: string;
  mcp?: Record<string, unknown>;
  discovered_tools?: ContextConnector['discovered_tools'];
  allowed_tools?: string[];
  last_discovered_at?: string | null;
  endpoints: SerializedContextConnectorEndpoint[];
}

const CAPABILITY_RESERVED_KEYS = new Set([
  'enabled',
  'selected',
  'selected_skill_ids',
  'selected_tool_ids',
  'enabled_skills',
  'enabled_tools',
]);

function isPlainObject(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function safeHostname(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

function uniqueStringArray(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  return Array.from(new Set(
    values
      .map(value => String(value || '').trim())
      .filter(Boolean),
  ));
}

function asRecord(value: unknown): UnknownRecord {
  return isPlainObject(value) ? value : {};
}

function asContextConnectorMethod(value: unknown): ContextConnectorMethod {
  return value as ContextConnectorMethod;
}

/** Parses a user-editable JSON field, returning its original text when invalid. */
export function parseStructuredField(value: string | null | undefined, fallback: unknown): unknown {
  if (!value?.trim()) {
    return fallback;
  }

  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

/** Converts a saved structured value into the text shown in the wizard editor. */
export function structuredFieldToText(value: unknown, fallback: unknown): string {
  if (value === undefined || value === null || value === '') {
    return JSON.stringify(fallback, null, 2);
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

export function extractSelectedCapabilityIds(config: unknown, idField: CapabilityIdField): string[] {
  if (Array.isArray(config)) {
    return uniqueStringArray(
      config.map(entry => {
        if (typeof entry === 'string') {
          return entry;
        }
        if (isPlainObject(entry) && entry.enabled !== false) {
          return entry[idField] || entry.id;
        }
        return '';
      }),
    );
  }

  if (!isPlainObject(config)) {
    return [];
  }

  const selected = uniqueStringArray(
    config.selected
      || config[`selected_${idField === 'skill_id' ? 'skill_ids' : 'tool_ids'}`]
      || config[idField === 'skill_id' ? 'enabled_skills' : 'enabled_tools'],
  );
  if (selected.length > 0) {
    return selected;
  }

  return uniqueStringArray(
    Object.entries(config).map(([key, value]) => {
      if (CAPABILITY_RESERVED_KEYS.has(key) || !isPlainObject(value) || !value.enabled) {
        return '';
      }
      return value[idField] || value.id || key;
    }),
  );
}

export function buildCapabilityConfig(
  existingConfig: unknown,
  selectedIds: readonly string[],
  idField: CapabilityIdField,
): CapabilitySelectionConfig {
  const selected = uniqueStringArray(selectedIds);
  const selectedSet = new Set(selected);
  const next: UnknownRecord = isPlainObject(existingConfig) ? { ...existingConfig } : {};

  Object.keys(next).forEach(key => {
    const value = next[key];
    if (CAPABILITY_RESERVED_KEYS.has(key) || !isPlainObject(value)) {
      return;
    }
    const entryId = String(value[idField] || value.id || key);
    next[key] = {
      ...value,
      [idField]: value[idField] || entryId,
      enabled: selectedSet.has(entryId),
    };
  });

  return {
    ...next,
    enabled: selected.length > 0,
    selected,
  };
}

export function requiredInputsToText(inputs: unknown): string {
  if (!Array.isArray(inputs)) return '';
  return inputs
    .filter((item): item is UnknownRecord => Boolean(item) && typeof item === 'object')
    .map(item => [item.id, item.label, item.type].filter(Boolean).join(':'))
    .join('\n');
}

export function parseRequiredInputsText(value: string | null | undefined): RequiredConversationInput[] {
  return (value || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const [id, label, type] = line.split(':').map(part => part.trim());
      return {
        id,
        label: label || id.replace(/_/g, ' '),
        type: type || 'text',
        required: true as const,
        aliases: [],
      };
    })
    .filter(item => item.id);
}

export function toolRecipesToText(recipes: unknown): string {
  if (!Array.isArray(recipes) || recipes.length === 0) return '';
  return JSON.stringify(recipes, null, 2);
}

export function parseToolRecipesText(value: string | null | undefined): unknown[] {
  const parsed = parseStructuredField(value, []);
  return Array.isArray(parsed) ? parsed : [];
}

export function createVedikaLalKitabConnector(): ContextConnector {
  const endpoints: ReadonlyArray<readonly [string, string, string]> = [
    ['lalkitab_chart', 'Lal Kitab Chart', 'Fetch calculated Lal Kitab chart context.'],
    ['lalkitab_debts', 'Lal Kitab Debts', 'Fetch Lal Kitab debts and karmic obligation context.'],
    ['lalkitab_houses', 'Lal Kitab Houses', 'Fetch Lal Kitab house interpretation context.'],
    ['lalkitab_lucky', 'Lal Kitab Lucky Factors', 'Fetch lucky colors, numbers, timing, and favorable factors.'],
    ['lalkitab_predictions', 'Lal Kitab Predictions', 'Fetch calculated Lal Kitab prediction context.'],
    ['lalkitab_remedies', 'Lal Kitab Remedies', 'Fetch Lal Kitab remedy recommendations.'],
    ['lalkitab_totke', 'Lal Kitab Totke', 'Fetch Lal Kitab totke/remedial action context.'],
    ['lalkitab_varshphal', 'Lal Kitab Varshphal', 'Fetch Lal Kitab annual chart/varshphal context.'],
  ];
  return {
    id: 'vedika_lal_kitab',
    type: 'http',
    name: 'Vedika Lal Kitab',
    enabled: true,
    auth_header: '',
    auth_header_configured: false,
    usage: 'Use only for calculated Lal Kitab astrology chart/remedy context. Build the Lal Kitab chart first, then call relevant secondary endpoints. Ask for birth date, birth time, and birth place; if geocoding is not configured, ask for latitude, longitude, and timezone.',
    tool_description: 'Call Vedika Lal Kitab APIs for calculated chart, remedy, prediction, lucky factor, totke, debts, houses, and varshphal context.',
    domain_allowlist: ['api.vedika.io'],
    input_resolution: {
      resolve_known_places: true,
      confirm_understood_details: true,
      missing_input_strategy: 'ask_follow_up',
    },
    timeout_seconds: 20,
    max_response_chars: 12000,
    retry_count: 1,
    endpoints: endpoints.map(([id, name, description]) => ({
      id,
      name,
      enabled: true,
      method: 'POST',
      url: `https://api.vedika.io/v2/astrology/lalkitab/${id.replace('lalkitab_', '')}`,
      required_fields: ['birth_date', 'birth_time', 'birth_place'],
      runtime_required_fields: ['datetime', 'latitude', 'longitude', 'timezone'],
      execution_order: id === 'lalkitab_chart' ? 1 : 2,
      requires_prior_endpoint: id === 'lalkitab_chart' ? null : 'lalkitab_chart',
      payload_mode: 'flat_body',
      field_mapping: {
        birth_date: 'date',
        birth_time: 'time',
      },
      description,
      body_schema: {
        type: 'object',
        properties: {
          datetime: { type: 'string', description: 'Birth datetime in ISO format, for example 1990-05-15T10:30:00.' },
          latitude: { type: 'number', description: 'Birthplace latitude.' },
          longitude: { type: 'number', description: 'Birthplace longitude.' },
          timezone: { type: 'string', description: 'Timezone offset, for example +05:30.' },
          language: { type: 'string' },
        },
        required: ['datetime', 'latitude', 'longitude', 'timezone'],
      },
      query_schema: {},
      response_mapping: {},
    })),
  };
}

export function normalizeLalKitabEndpointUrl(endpointId: string, url: string): string {
  if (!endpointId.startsWith('lalkitab_')) {
    return url;
  }
  const slug = endpointId.replace('lalkitab_', '');
  if (!url || url.includes('/v1/lal-kitab/')) {
    return `https://api.vedika.io/v2/astrology/lalkitab/${slug}`;
  }
  return url;
}

export function legacyApiDataSourceToConnector(apiDataSource: unknown): ContextConnector[] {
  if (!isPlainObject(apiDataSource) || !apiDataSource.url) {
    return [];
  }
  const url = apiDataSource.url as string;
  const hostname = safeHostname(url);
  return [{
    id: 'legacy_api_data_source',
    type: 'http',
    name: (apiDataSource.name || 'Legacy API Data Source') as string,
    enabled: Boolean(apiDataSource.enabled),
    auth_header: (apiDataSource.auth_header || '') as string,
    auth_header_configured: Boolean(apiDataSource.auth_header_configured),
    usage: (apiDataSource.usage || '') as string,
    tool_description: (apiDataSource.usage || 'Call the configured API data source.') as string,
    domain_allowlist: hostname ? [hostname] : [],
    endpoints: [{
      id: 'default',
      name: (apiDataSource.name || 'Default API Lookup') as string,
      method: 'POST',
      url,
      enabled: true,
      required_fields: [],
      description: (apiDataSource.usage || '') as string,
      body_schema: {},
      query_schema: {},
      response_mapping: {},
    }],
  }];
}

export function normalizeConnectorsForStudio(config: unknown): ContextConnector[] {
  const configRecord = asRecord(config);
  const connectors = Array.isArray(configRecord.context_connectors)
    ? configRecord.context_connectors
    : legacyApiDataSourceToConnector(configRecord.api_data_source);

  return connectors
    .filter(isPlainObject)
    .map((connector): ContextConnector => {
      const auth = asRecord(connector.auth);
      const mcp = asRecord(connector.mcp);
      const endpoints = Array.isArray(connector.endpoints) ? connector.endpoints : [];
      return {
        id: (connector.id || connector.name || 'connector') as string,
        type: connector.type === 'mcp' ? 'mcp' : 'http',
        name: (connector.name || connector.id || 'Context Connector') as string,
        enabled: Boolean(connector.enabled),
        auth_header: (connector.auth_header || auth.auth_header || '') as string,
        auth_header_configured: Boolean(connector.auth_header_configured || auth.auth_header_configured),
        usage: (connector.usage || connector.usage_policy || '') as string,
        tool_description: (connector.tool_description || connector.usage_policy || connector.usage || '') as string,
        domain_allowlist: (Array.isArray(connector.domain_allowlist) ? connector.domain_allowlist : []) as string[],
        input_resolution: (connector.input_resolution || {}) as ContextConnector['input_resolution'],
        headers: (connector.headers || {}) as Record<string, unknown>,
        timeout_seconds: connector.timeout_seconds as number | undefined,
        max_response_chars: connector.max_response_chars as number | undefined,
        retry_count: connector.retry_count as number | undefined,
        endpoint: (connector.endpoint || mcp.endpoint || '') as string,
        transport: (connector.transport || mcp.transport || 'http') as string,
        mcp: (connector.mcp || {}) as Record<string, unknown>,
        discovered_tools: (Array.isArray(connector.discovered_tools) ? connector.discovered_tools : []) as ContextConnector['discovered_tools'],
        allowed_tools: (Array.isArray(connector.allowed_tools) ? connector.allowed_tools : []) as string[],
        last_discovered_at: (connector.last_discovered_at || null) as string | null,
        revoked: Boolean(connector.revoked),
        endpoints: endpoints.map((endpointValue, index): ContextConnectorEndpoint => {
          const endpoint = asRecord(endpointValue);
          const endpointId = (endpoint.id || `endpoint_${index + 1}`) as string;
          const isLalKitabEndpoint = String(endpointId).startsWith('lalkitab_');
          return {
            id: endpointId,
            name: (endpoint.name || `Endpoint ${index + 1}`) as string,
            method: asContextConnectorMethod(endpoint.method || 'POST'),
            url: normalizeLalKitabEndpointUrl(String(endpointId), (endpoint.url || endpoint.url_template || '') as string),
            enabled: (endpoint.enabled ?? true) as boolean,
            required_fields: (endpoint.required_fields || endpoint.required_user_fields || []) as string[],
            description: (endpoint.description || endpoint.tool_description || '') as string,
            headers: (endpoint.headers || {}) as Record<string, unknown>,
            query_schema: (endpoint.query_schema || {}) as Record<string, unknown> | string,
            body_schema: (endpoint.body_schema || {}) as Record<string, unknown> | string,
            response_mapping: (endpoint.response_mapping || {}) as Record<string, unknown> | string,
            timeout_seconds: endpoint.timeout_seconds as number | undefined,
            max_response_chars: endpoint.max_response_chars as number | undefined,
            retry_count: endpoint.retry_count as number | undefined,
            execution_order: (endpoint.execution_order ?? (isLalKitabEndpoint ? (endpointId === 'lalkitab_chart' ? 1 : 2) : undefined)) as number | undefined,
            requires_prior_endpoint: (endpoint.requires_prior_endpoint ?? (isLalKitabEndpoint && endpointId !== 'lalkitab_chart' ? 'lalkitab_chart' : null)) as string | null,
            payload_mode: (endpoint.payload_mode || (isLalKitabEndpoint ? 'flat_body' : undefined)) as ContextConnectorEndpoint['payload_mode'],
            field_mapping: (endpoint.field_mapping || (isLalKitabEndpoint ? { birth_date: 'date', birth_time: 'time' } : {})) as Record<string, string>,
            runtime_required_fields: (endpoint.runtime_required_fields || (isLalKitabEndpoint ? ['datetime', 'latitude', 'longitude', 'timezone'] : [])) as string[],
          };
        }),
      };
    });
}

export function serializeContextConnectors(
  connectors: readonly ContextConnector[] | null | undefined,
): SerializedContextConnector[] {
  if (!Array.isArray(connectors)) {
    return [];
  }
  const connectorList = connectors as readonly ContextConnector[];
  return connectorList
    .filter(connector => connector && connector.name)
    .map((connector): SerializedContextConnector => {
      const common = {
        id: connector.id,
        name: connector.name,
        type: connector.type === 'mcp' ? 'mcp' as const : 'http_api' as const,
        enabled: Boolean(connector.enabled),
        revoked: Boolean(connector.revoked),
        domain_allowlist: connector.domain_allowlist || [],
        input_resolution: connector.input_resolution || {},
        headers: connector.headers || {},
        timeout_seconds: connector.timeout_seconds,
        max_response_chars: connector.max_response_chars,
        retry_count: connector.retry_count,
        auth: connector.auth_header
          ? { type: 'raw_header' as const, auth_header: connector.auth_header }
          : { type: 'raw_header' as const, auth_header_configured: connector.auth_header_configured },
        usage_policy: connector.usage || connector.tool_description || '',
      };

      if (connector.type === 'mcp') {
        return {
          ...common,
          type: 'mcp',
          endpoint: connector.endpoint,
          transport: connector.transport || 'http',
          mcp: {
            ...(connector.mcp || {}),
            endpoint: connector.endpoint,
            transport: connector.transport || connector.mcp?.transport || 'http',
          },
          discovered_tools: connector.discovered_tools || [],
          allowed_tools: connector.allowed_tools || [],
          last_discovered_at: connector.last_discovered_at || null,
          endpoints: [],
        };
      }

      return {
        ...common,
        type: 'http_api',
        endpoints: (connector.endpoints || [])
          .filter(endpoint => endpoint.url)
          .map((endpoint): SerializedContextConnectorEndpoint => ({
            id: endpoint.id,
            name: endpoint.name,
            enabled: endpoint.enabled ?? true,
            method: endpoint.method || 'POST',
            url_template: endpoint.url,
            required_user_fields: endpoint.required_fields || [],
            headers: endpoint.headers || {},
            query_schema: endpoint.query_schema || {},
            body_schema: endpoint.body_schema || {},
            response_mapping: endpoint.response_mapping || {},
            timeout_seconds: endpoint.timeout_seconds,
            max_response_chars: endpoint.max_response_chars,
            retry_count: endpoint.retry_count,
            execution_order: endpoint.execution_order,
            requires_prior_endpoint: endpoint.requires_prior_endpoint ?? null,
            payload_mode: endpoint.payload_mode,
            field_mapping: endpoint.field_mapping || {},
            runtime_required_fields: endpoint.runtime_required_fields || [],
            tool_description: endpoint.description || connector.tool_description || connector.usage || '',
          })),
      };
    });
}
