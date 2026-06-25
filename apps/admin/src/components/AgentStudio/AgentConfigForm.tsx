import React from 'react';
import {
  AdjustmentsHorizontalIcon,
  SparklesIcon,
} from '@heroicons/react/24/outline';
import { AZURE_OPENAI_PROVIDER_LABEL, getAzureDeploymentOptions } from '../../utils/llmOptions';
import type { AgentStudioFormProps } from './types';

const templates = [
  { id: 'generic', name: 'General Assistant' },
  { id: 'astrology_lalkitab', name: 'Astrology / LalKitab Advisor' },
  { id: 'customer_support', name: 'Customer Support' },
  { id: 'research', name: 'Research Analyst' },
  { id: 'sales', name: 'Sales Assistant' },
  { id: 'hr', name: 'HR Assistant' },
  { id: 'legal', name: 'Legal Assistant' },
  { id: 'coding', name: 'Coding Assistant' },
  { id: 'operations', name: 'Operations Assistant' },
  { id: 'ecommerce_sales', name: 'Ecommerce Sales Agent' },
  { id: 'ecommerce', name: 'Ecommerce Assistant' },
];

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="flex items-center gap-1 text-sm font-medium text-gray-800">
        {label}
        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-gray-300 text-[10px] text-gray-500">i</span>
      </span>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-xs leading-5 text-gray-500">{hint}</p>}
    </label>
  );
}

const inputClass = 'block w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm outline-none transition focus:border-gray-500 focus:ring-1 focus:ring-gray-500 disabled:bg-gray-50 disabled:text-gray-500';

function Switch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border border-gray-200 bg-white px-3 py-3">
      <div>
        <p className="text-sm font-semibold text-gray-900">{label}</p>
        <p className="mt-1 text-xs leading-5 text-gray-500">{description}</p>
      </div>
      <button
        type="button"
        onClick={onChange}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${checked ? 'bg-gray-950' : 'bg-gray-200'}`}
        aria-pressed={checked}
      >
        <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </button>
    </div>
  );
}

export default function AgentConfigForm({
  data,
  onChange,
  brands,
  deployments,
  deploymentsLoading,
}: AgentStudioFormProps) {
  const modelOptions = getAzureDeploymentOptions(deployments, data.model);
  const isEcommerce = data.agent_template === 'ecommerce' || data.agent_template === 'ecommerce_sales';
  const showShopifySetup = isEcommerce || data.data_source === 'shopify' || data.selected_tool_ids?.includes('shopify');
  const cleanShopDomain = data.shopify_shop_url.replace(/^https?:\/\//, '').replace(/\/$/, '');
  const storefrontMcpEndpoint = cleanShopDomain ? `https://${cleanShopDomain}/api/mcp` : 'https://your-store.myshopify.com/api/mcp';
  const ucpMcpEndpoint = cleanShopDomain ? `https://${cleanShopDomain}/api/ucp/mcp` : 'https://your-store.myshopify.com/api/ucp/mcp';

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Name">
          <input
            value={data.name}
            onChange={(event) => onChange('name', event.target.value)}
            className={inputClass}
            placeholder="Agent name"
          />
        </Field>

        <Field label="Brand">
          <select
            value={data.brand_id}
            onChange={(event) => onChange('brand_id', event.target.value)}
            className={inputClass}
          >
            <option value="">Select brand</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>{brand.name}</option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Description">
        <input
          value={data.description}
          onChange={(event) => onChange('description', event.target.value)}
          className={inputClass}
          placeholder="Agent description"
        />
      </Field>

      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Agent Type">
          <select
            value={data.agent_template}
            onChange={(event) => onChange('agent_template', event.target.value)}
            className={inputClass}
          >
            {templates.map((template) => (
              <option key={template.id} value={template.id}>{template.name}</option>
            ))}
          </select>
        </Field>

        <Field label="Provider">
          <div className="flex h-10 items-center rounded-md border border-gray-200 bg-gray-50 px-3 text-sm text-gray-700">
            {AZURE_OPENAI_PROVIDER_LABEL}
          </div>
        </Field>

        <Field label="Model">
          <select
            value={data.model}
            onChange={(event) => onChange('model', event.target.value)}
            disabled={deploymentsLoading || (!modelOptions.length && !data.model)}
            className={inputClass}
          >
            <option value="">{deploymentsLoading ? 'Loading deployments...' : 'Select model'}</option>
            {modelOptions.map((option) => (
              <option key={option.id} value={option.id}>{option.name}</option>
            ))}
          </select>
        </Field>
      </div>

      <div className="rounded-md border border-gray-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-950">Agent Instructions</h2>
            <p className="mt-1 text-xs text-gray-500">Define the agent's operating role, goal, and behavior.</p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <SparklesIcon className="h-4 w-4" />
            Improve
          </button>
        </div>

        <div className="space-y-4">
          <Field label="Agent Role">
            <input
              value={data.role}
              onChange={(event) => onChange('role', event.target.value)}
              className={inputClass}
              placeholder="You are an expert assistant..."
            />
          </Field>

          <Field label="Agent Goal">
            <input
              value={data.purpose}
              onChange={(event) => onChange('purpose', event.target.value)}
              className={inputClass}
              placeholder="Your goal is to..."
            />
          </Field>

          <Field label="Agent Instructions">
            <textarea
              value={data.system_prompt}
              onChange={(event) => onChange('system_prompt', event.target.value)}
              className={`${inputClass} min-h-[220px] resize-y leading-6`}
              placeholder="Write the rules, steps, and tone this agent should follow."
            />
          </Field>
        </div>
      </div>

      <Field label="Examples (Optional)">
        <textarea
          value={data.response_format}
          onChange={(event) => onChange('response_format', event.target.value)}
          className={`${inputClass} min-h-[88px] resize-y leading-6`}
          placeholder="Enter an example output, tone sample, or response format."
        />
      </Field>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-gray-200 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-gray-900">Manager Agent</p>
              <p className="mt-1 text-xs leading-5 text-gray-500">Route tasks to other agents when orchestration is configured.</p>
            </div>
            <button
              type="button"
              onClick={() => onChange('human_takeover', !data.human_takeover)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${data.human_takeover ? 'bg-gray-950' : 'bg-gray-200'}`}
              aria-pressed={data.human_takeover}
            >
              <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${data.human_takeover ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>
        </div>

        <div className="rounded-md border border-gray-200 p-4">
          <div className="flex items-start gap-3">
            <AdjustmentsHorizontalIcon className="mt-0.5 h-5 w-5 text-gray-400" />
            <div>
              <p className="text-sm font-semibold text-gray-900">Runtime Controls</p>
              <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-gray-500">
                <span>Temperature: {data.temperature}</span>
                <span>Max tokens: {data.max_tokens}</span>
                <span>Top P: {data.top_p}</span>
                <span>Timeout: {data.session_timeout}m</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {showShopifySetup && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Shopify Commerce Layer</h3>
              <p className="mt-1 text-xs leading-5 text-gray-500">
                Configure this agent for a specific store. Hybrid mode uses NOVA catalog RAG for product discovery and Shopify MCP/UCP for cart and live commerce actions.
              </p>
            </div>
            <span className={`shrink-0 rounded px-2 py-1 text-xs font-medium ${data.data_source === 'shopify' ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-700'}`}>
              {data.data_source === 'shopify' ? 'Active' : 'Off'}
            </span>
          </div>

          <div className="mt-3">
            <Switch
              checked={data.data_source === 'shopify'}
              onChange={() => onChange('data_source', data.data_source === 'shopify' ? 'none' : 'shopify')}
              label="Use Shopify commerce"
              description="Turns on the commerce path: Agent -> NOVA catalog/RAG + MCP/UCP -> Shopify -> Store."
            />
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <label className={`rounded-md border px-3 py-3 ${data.shopify_integration_mode === 'hybrid_catalog_rag_mcp' ? 'border-gray-950 bg-white' : 'border-gray-200 bg-white'}`}>
              <div className="flex items-start gap-2">
                <input
                  type="radio"
                  checked={data.shopify_integration_mode === 'hybrid_catalog_rag_mcp'}
                  onChange={() => {
                    onChange('shopify_integration_mode', 'hybrid_catalog_rag_mcp');
                    onChange('shopify_sync_enabled', true);
                    onChange('shopify_mcp_enabled', true);
                    onChange('data_source', 'shopify');
                  }}
                  className="mt-1"
                />
                <div>
                  <p className="text-sm font-semibold text-gray-900">Hybrid catalog + MCP</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">Recommended. NOVA understands catalog nuance; Shopify handles cart, checkout, and live commerce actions.</p>
                </div>
              </div>
            </label>
            <label className={`rounded-md border px-3 py-3 ${data.shopify_integration_mode === 'storefront_ucp_mcp' ? 'border-gray-950 bg-white' : 'border-gray-200 bg-white'}`}>
              <div className="flex items-start gap-2">
                <input
                  type="radio"
                  checked={data.shopify_integration_mode === 'storefront_ucp_mcp'}
                  onChange={() => {
                    onChange('shopify_integration_mode', 'storefront_ucp_mcp');
                    onChange('shopify_mcp_enabled', true);
                    onChange('data_source', 'shopify');
                  }}
                  className="mt-1"
                />
                <div>
                  <p className="text-sm font-semibold text-gray-900">MCP / UCP only</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">Use only Shopify's agent-ready endpoints. Best for actions, weaker for broad product discovery.</p>
                </div>
              </div>
            </label>
            <label className={`rounded-md border px-3 py-3 ${data.shopify_integration_mode === 'admin_catalog_sync' ? 'border-gray-950 bg-white' : 'border-gray-200 bg-white'}`}>
              <div className="flex items-start gap-2">
                <input
                  type="radio"
                  checked={data.shopify_integration_mode === 'admin_catalog_sync'}
                  onChange={() => {
                    onChange('shopify_integration_mode', 'admin_catalog_sync');
                    onChange('shopify_mcp_enabled', false);
                    onChange('data_source', 'shopify');
                  }}
                  className="mt-1"
                />
                <div>
                  <p className="text-sm font-semibold text-gray-900">Catalog RAG only</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">Use synced product knowledge for recommendations without live cart actions.</p>
                </div>
              </div>
            </label>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <input
              value={data.shopify_shop_url}
              onChange={(event) => {
                onChange('shopify_shop_url', event.target.value);
                if (event.target.value.trim() && data.data_source !== 'shopify') {
                  onChange('data_source', 'shopify');
                }
              }}
              className={inputClass}
              placeholder="your-store.myshopify.com"
            />
            <input
              value={data.shopify_agent_profile_url}
              onChange={(event) => onChange('shopify_agent_profile_url', event.target.value)}
              className={inputClass}
              placeholder="UCP agent profile URL"
            />
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <input
              value={data.shopify_client_id}
              onChange={(event) => onChange('shopify_client_id', event.target.value)}
              className={inputClass}
              placeholder="Shopify app client ID"
            />
            <input
              type="password"
              value={data.shopify_client_secret}
              onChange={(event) => onChange('shopify_client_secret', event.target.value)}
              className={inputClass}
              placeholder={data.shopify_client_secret_configured ? 'Client secret configured' : 'Shopify app client secret'}
            />
          </div>

          <div className="mt-3 rounded-md border border-gray-200 bg-white px-3 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Resolved commerce endpoints</p>
            <div className="mt-2 space-y-1 font-mono text-xs text-gray-600">
              <p className="truncate">Storefront MCP: {storefrontMcpEndpoint}</p>
              <p className="truncate">UCP Catalog MCP: {ucpMcpEndpoint}</p>
            </div>
            <p className="mt-2 text-xs leading-5 text-gray-500">
              Storefront MCP can browse products, carts, checkout, and policies for this store. Customer/account actions use the app client credentials during OAuth.
            </p>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Switch
              checked={data.shopify_sync_enabled}
              onChange={() => onChange('shopify_sync_enabled', !data.shopify_sync_enabled)}
              label="Use cached catalog boost"
              description="Optional secondary retrieval cache. Full OAuth-based sync can be wired after app credential exchange is implemented."
            />
            <Switch
              checked={data.shopify_mcp_enabled}
              onChange={() => onChange('shopify_mcp_enabled', !data.shopify_mcp_enabled)}
              label="Enable live actions"
              description="Expose Shopify MCP tools when customer/session auth is available. Catalog answers still work without this."
            />
          </div>

          {data.data_source === 'shopify' && !data.shopify_shop_url && (
            <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              Shopify is active but setup is incomplete. Add the store domain so NOVA can resolve the Storefront MCP and UCP endpoints.
            </p>
          )}
        </div>
      )}

      {data.agent_template === 'astrology_lalkitab' && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-semibold text-gray-900">LalKitab Launch Notes</h3>
          <p className="mt-1 text-xs leading-5 text-gray-500">
            Configure the astrology API in Agent Tools, then instruct the agent to ask for missing birth date,
            time, and place before giving chart-specific guidance.
          </p>
        </div>
      )}

      <div className="rounded-md border border-gray-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Conversation Behavior</h3>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              Define what NOVA should collect before answering and how much internal runtime detail should be shown to users.
            </p>
          </div>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field label="Goal">
            <input
              className={inputClass}
              value={data.conversation_policy_goal || ''}
              onChange={(event) => onChange('conversation_policy_goal', event.target.value)}
              placeholder="Help users choose the right product, answer support questions, or give astrology guidance"
            />
          </Field>

          <Field label="Answer style">
            <input
              className={inputClass}
              value={data.conversation_answer_style || 'helpful'}
              onChange={(event) => onChange('conversation_answer_style', event.target.value)}
              placeholder="helpful, human_astrologer, consultative_sales"
            />
          </Field>

          <Field label="Planner model">
            <input
              className={inputClass}
              value={data.conversation_planner_model || ''}
              onChange={(event) => onChange('conversation_planner_model', event.target.value)}
              placeholder="Optional, e.g. gpt-5.5-low"
            />
          </Field>
        </div>

        <div className="mt-3">
          <Field
            label="Required inputs"
            hint="One per line as id:label:type. Example: birth_date:birth date:date"
          >
            <textarea
              className={`${inputClass} min-h-[92px]`}
              value={data.conversation_required_inputs || ''}
              onChange={(event) => onChange('conversation_required_inputs', event.target.value)}
              placeholder={'budget:budget:number\nuse_case:use case:text'}
            />
          </Field>
        </div>

        <div className="mt-3">
          <Field
            label="Tool recipes"
            hint="JSON array. Use this for ordered tool dependencies such as chart-first, then intent-relevant endpoints."
          >
            <textarea
              className={`${inputClass} min-h-[112px] font-mono text-xs`}
              value={data.conversation_tool_recipes || ''}
              onChange={(event) => onChange('conversation_tool_recipes', event.target.value)}
              placeholder={'[{ "id": "recipe", "steps": [{ "tool_id": "knowledge_search", "order": 1 }] }]'}
            />
          </Field>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Switch
            checked={Boolean(data.conversation_question_required)}
            onChange={() => onChange('conversation_question_required', !data.conversation_question_required)}
            label="Require a user question"
            description="If users only share details, the agent confirms them and asks what they want to know."
          />
          <Switch
            checked={data.conversation_hide_internal_sources !== false}
            onChange={() => onChange('conversation_hide_internal_sources', data.conversation_hide_internal_sources === false)}
            label="Hide internal runtime details"
            description="Keep API, RAG, connector, and tool details out of public answers. Agent Console still shows trace."
          />
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Switch
            checked={data.context_cache_enabled !== false}
            onChange={() => onChange('context_cache_enabled', data.context_cache_enabled === false)}
            label="Cache evidence in conversation"
            description="Reuse expensive lookup/retrieval results for follow-up questions in the same session."
          />
          <Field label="Cache invalidation fields">
            <input
              className={inputClass}
              value={data.context_invalidation_fields || ''}
              onChange={(event) => onChange('context_invalidation_fields', event.target.value)}
              placeholder="birth_date, birth_time, birth_place"
            />
          </Field>
        </div>
      </div>
    </div>
  );
}
