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

export default function AgentConfigForm({
  data,
  onChange,
  brands,
  deployments,
  deploymentsLoading,
}: AgentStudioFormProps) {
  const modelOptions = getAzureDeploymentOptions(deployments, data.model);
  const isEcommerce = data.agent_template === 'ecommerce' || data.agent_template === 'ecommerce_sales';

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

      {isEcommerce && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-semibold text-gray-900">Ecommerce Source</h3>
          <p className="mt-1 text-xs text-gray-500">Optional store configuration for ecommerce-specific agents.</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <input
              value={data.shopify_shop_url}
              onChange={(event) => onChange('shopify_shop_url', event.target.value)}
              className={inputClass}
              placeholder="Shopify shop URL"
            />
            <input
              type="password"
              value={data.shopify_access_token}
              onChange={(event) => onChange('shopify_access_token', event.target.value)}
              className={inputClass}
              placeholder={data.shopify_access_token_configured ? 'Token configured' : 'Access token'}
            />
          </div>
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
    </div>
  );
}
