import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowPathIcon,
  BoltIcon,
  CircleStackIcon,
  CommandLineIcon,
  PaperAirplaneIcon,
  ShieldCheckIcon,
} from '@heroicons/react/24/outline';
import { API_BASE_URL, getAccessToken } from '../../api/client';

interface AgentInferenceTesterProps {
  agentId?: string;
  agentName?: string;
  streamEndpoint?: string;
  conversationIdPrefix?: string;
}

interface Citation {
  doc_id?: string;
  title?: string;
  url?: string;
  confidence?: number;
  snippet?: string;
}

interface ProductResult {
  id?: string;
  variant_id?: string;
  sku?: string;
  name?: string;
  title?: string;
  price?: number;
  currency?: string;
  product_url?: string;
  url?: string;
  image_url?: string;
}

interface DealerResult {
  id?: string;
  name?: string;
  city?: string;
  state?: string;
  phone?: string;
}

interface TraceEntry {
  label: string;
  detail: string;
  state: 'done' | 'active' | 'waiting' | 'error';
}

function parseSsePayload(raw: string): any | null {
  const trimmed = raw.trim();
  if (!trimmed || !trimmed.startsWith('data:')) {
    return null;
  }

  const json = trimmed
    .split('\n')
    .filter(line => line.startsWith('data:'))
    .map(line => line.replace(/^data:\s?/, ''))
    .join('\n');

  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function compactTrace(entries: TraceEntry[]): TraceEntry[] {
  const seen = new Map<string, TraceEntry>();
  entries.forEach(entry => seen.set(`${entry.label}:${entry.detail}`, entry));
  return Array.from(seen.values()).slice(-8);
}

function formatProductPrice(price?: number, currency?: string): string | null {
  if (typeof price !== 'number' || price <= 0) return null;

  // Catalog and Shopify results store monetary values in the smallest currency
  // unit so exports stay integer-safe across providers.
  const displayPrice = price / 100;
  if (!currency) {
    return displayPrice.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(displayPrice);
  } catch {
    return `${currency} ${displayPrice.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

export default function AgentInferenceTester({
  agentId,
  agentName,
  streamEndpoint,
  conversationIdPrefix = 'admin-console',
}: AgentInferenceTesterProps) {
  const [tab, setTab] = useState<'chat' | 'activity'>('chat');
  const [message, setMessage] = useState('');
  const [submittedMessage, setSubmittedMessage] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [contextUsed, setContextUsed] = useState<number | null>(null);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [products, setProducts] = useState<ProductResult[]>([]);
  const [dealers, setDealers] = useState<DealerResult[]>([]);
  const [trace, setTrace] = useState<TraceEntry[]>([
    { label: 'Runtime', detail: 'Waiting for a test question', state: 'waiting' },
  ]);
  // Unique per console session so concurrent admins don't share conversation memory.
  const [sessionId, setSessionId] = useState(() => Math.random().toString(36).slice(2, 10));

  // Switching agents must not leak the previous agent's chat, trace, or citations.
  // Clear all per-conversation state and start a fresh session whenever agentId changes.
  useEffect(() => {
    setTab('chat');
    setMessage('');
    setSubmittedMessage('');
    setAnswer('');
    setError('');
    setLatencyMs(null);
    setLoading(false);
    setCitations([]);
    setProducts([]);
    setDealers([]);
    setContextUsed(null);
    setConfidence(null);
    setTrace([{ label: 'Runtime', detail: 'Waiting for a test question', state: 'waiting' }]);
    setSessionId(Math.random().toString(36).slice(2, 10));
  }, [agentId]);

  const displayLatency = useMemo(() => {
    if (latencyMs === null) return '-';
    return `${(latencyMs / 1000).toFixed(2)}s`;
  }, [latencyMs]);

  const addTrace = (entry: TraceEntry) => {
    setTrace(prev => compactTrace([...prev, entry]));
  };

  const reset = () => {
    setSubmittedMessage('');
    setAnswer('');
    setError('');
    setLatencyMs(null);
    setCitations([]);
    setProducts([]);
    setDealers([]);
    setContextUsed(null);
    setConfidence(null);
    setTrace([{ label: 'Runtime', detail: 'Waiting for a test question', state: 'waiting' }]);
  };

  const send = async () => {
    const prompt = message.trim();
    if (!agentId || !prompt) return;

    const started = performance.now();
    setLoading(true);
    setError('');
    setAnswer('');
    setSubmittedMessage(prompt);
    setCitations([]);
    setProducts([]);
    setDealers([]);
    setContextUsed(null);
    setConfidence(null);
    setTrace([
      { label: 'Request', detail: 'Preparing admin inference session', state: 'done' },
      { label: 'Context', detail: 'Loading agent configuration and enabled capabilities', state: 'active' },
    ]);

    try {
      const response = await fetch(`${API_BASE_URL}${streamEndpoint || '/api/v1/messages/stream'}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        },
        body: JSON.stringify({
          agent_id: agentId,
          message: prompt,
          conversation_id: `${conversationIdPrefix}-${agentId}-${sessionId}`,
          user_id: 'admin-console',
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Streaming request failed with ${response.status}`);
      }

      addTrace({ label: 'Retrieval', detail: 'Searching knowledge, skills, memory, and tool registry', state: 'active' });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';

        frames.forEach((frame) => {
          const payload = parseSsePayload(frame);
          if (!payload) return;

          if (payload.type === 'content') {
            setAnswer(prev => `${prev}${payload.content || ''}`);
          } else if (payload.type === 'status') {
            addTrace({ label: 'Working', detail: payload.content || 'Agent is working', state: 'active' });
          } else if (payload.type === 'context_start') {
            addTrace({ label: 'Context', detail: payload.content || 'Loading context', state: 'active' });
          } else if (payload.type === 'context_result') {
            addTrace({ label: 'Context', detail: payload.content || 'Context ready', state: 'done' });
            const pageUrl = payload.metadata?.page_context?.url;
            if (pageUrl) {
              addTrace({ label: 'Page', detail: pageUrl, state: 'done' });
            }
            const apiName = payload.metadata?.api_data_source?.name;
            if (payload.metadata?.api_data_source?.enabled && apiName) {
              addTrace({ label: 'API Data', detail: `${apiName} enabled`, state: 'done' });
            }
          } else if (payload.type === 'skill_start') {
            addTrace({ label: 'Skill', detail: payload.content || payload.metadata?.tool_name || 'Running skill', state: 'active' });
          } else if (payload.type === 'skill_result') {
            addTrace({ label: 'Skill', detail: payload.content || payload.metadata?.tool_name || 'Skill complete', state: payload.metadata?.success === false ? 'error' : 'done' });
          } else if (payload.type === 'tool_start') {
            addTrace({ label: 'Tool', detail: payload.content || payload.metadata?.tool_name || 'Running tool', state: 'active' });
          } else if (payload.type === 'tool_result') {
            const toolName = payload.metadata?.tool_name;
            const productCount = Array.isArray(payload.products) ? payload.products.length : 0;
            const dealerCount = Array.isArray(payload.dealers) ? payload.dealers.length : 0;
            const detail = payload.content
              || [
                toolName ? `${toolName} complete` : 'Tool complete',
                productCount ? `${productCount} product${productCount === 1 ? '' : 's'}` : '',
                dealerCount ? `${dealerCount} dealer${dealerCount === 1 ? '' : 's'}` : '',
              ].filter(Boolean).join(' · ');
            addTrace({ label: 'Tool', detail, state: payload.metadata?.success === false ? 'error' : 'done' });
          } else if (payload.type === 'tool_error') {
            addTrace({ label: 'Tool', detail: payload.content || 'Tool failed', state: 'error' });
          } else if (payload.type === 'done') {
            addTrace({ label: 'Answer', detail: payload.content || 'Run complete', state: 'done' });
          } else if (payload.type === 'metadata') {
            addTrace({ label: 'Metadata', detail: payload.content || 'Runtime metadata received', state: 'done' });
          } else if (payload.type === 'error') {
            setError(payload.content || 'Streaming error');
            addTrace({ label: 'Error', detail: payload.content || 'Streaming error', state: 'error' });
          }

          if (Array.isArray(payload.citations) && payload.citations.length) {
            setCitations(payload.citations);
            addTrace({ label: 'Context', detail: `${payload.citations.length} citation source${payload.citations.length === 1 ? '' : 's'} attached`, state: 'done' });
          }
          if (typeof payload.context_used === 'number') {
            setContextUsed(payload.context_used);
          }
          if (typeof payload.confidence_score === 'number') {
            setConfidence(payload.confidence_score);
          }
          if (Array.isArray(payload.products) && payload.products.length) {
            setProducts(payload.products);
            addTrace({ label: 'Tool data', detail: `${payload.products.length} product result${payload.products.length === 1 ? '' : 's'} returned`, state: 'done' });
          }
          const commerceMeta = payload.metadata || {};
          if (commerceMeta.original_query && commerceMeta.search_query) {
            addTrace({ label: 'Search intent', detail: `${commerceMeta.original_query} -> ${commerceMeta.search_query}`, state: 'done' });
          }
          if (Array.isArray(commerceMeta.rerank_results) && commerceMeta.rerank_results.length) {
            const top = commerceMeta.rerank_results[0];
            addTrace({ label: 'Rerank', detail: `Top match: ${top.name || 'Product'}${top.match_score ? ` (${Math.round(top.match_score * 100)} score)` : ''}`, state: 'done' });
          }
          if (commerceMeta.resolved_reference?.status === 'resolved') {
            addTrace({ label: 'Reference', detail: `${commerceMeta.resolved_reference.product_name || 'Product'} resolved for cart action`, state: 'done' });
          }
          if (Array.isArray(commerceMeta.active_product_focus) && commerceMeta.active_product_focus.length) {
            addTrace({ label: 'Product focus', detail: `${commerceMeta.active_product_focus.length} focused product${commerceMeta.active_product_focus.length === 1 ? '' : 's'} kept for follow-up references`, state: 'done' });
          }
          if (Array.isArray(payload.dealers) && payload.dealers.length) {
            setDealers(payload.dealers);
            addTrace({ label: 'Tool data', detail: `${payload.dealers.length} dealer result${payload.dealers.length === 1 ? '' : 's'} returned`, state: 'done' });
          }
        });
      }

      addTrace({ label: 'Answer', detail: 'Streaming response complete', state: 'done' });
      setMessage('');
    } catch (sendError: any) {
      setError(sendError?.message || 'The streaming test could not be sent.');
      addTrace({ label: 'Error', detail: sendError?.message || 'The streaming test could not be sent.', state: 'error' });
    } finally {
      setLatencyMs(performance.now() - started);
      setLoading(false);
    }
  };

  return (
    <aside className="overflow-hidden rounded-lg border border-gray-200 bg-white text-gray-900 shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Nova Agent Console</p>
          <h2 className="mt-1 text-sm font-semibold text-gray-900">{agentName || 'Saved agent'}</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${loading ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-gray-200 bg-gray-50 text-gray-500'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${loading ? 'animate-pulse bg-emerald-500' : 'bg-gray-400'}`} />
            {loading ? 'streaming' : 'ready'}
          </span>
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-gray-200 p-2 text-gray-500 hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
            aria-label="Reset console"
          >
            <ArrowPathIcon className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="grid min-h-[620px] lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="border-r border-gray-200 bg-gray-50 p-4">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Session</p>
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <div className="rounded-md border border-gray-200 bg-white px-3 py-2">
                <p className="text-gray-500">Latency</p>
                <p className="mt-1 font-medium text-gray-900">{displayLatency}</p>
              </div>
              <div className="rounded-md border border-gray-200 bg-white px-3 py-2">
                <p className="text-gray-500">Context</p>
                <p className="mt-1 font-medium text-gray-900">{contextUsed ?? '-'}</p>
              </div>
              <div className="rounded-md border border-gray-200 bg-white px-3 py-2">
                <p className="text-gray-500">Confidence</p>
                <p className="mt-1 font-medium text-gray-900">{confidence === null ? '-' : `${Math.round(confidence * 100)}%`}</p>
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">What Nova Used</p>
            <div className="mt-3 space-y-2">
              {products.length === 0 && dealers.length === 0 && citations.length === 0 && trace.filter(entry => entry.state !== 'waiting').length === 0 ? (
                <div className="rounded-md border border-dashed border-gray-300 bg-white px-3 py-5 text-xs leading-5 text-gray-500">
                  Citations, retrieved files, API results, and skill outputs will appear here during a run.
                </div>
              ) : null}

              {products.slice(0, 5).map((product, index) => {
                const productName = product.name || product.title || product.sku || `Product ${index + 1}`;
                const price = formatProductPrice(product.price, product.currency);
                const url = product.product_url || product.url;
                return (
                  <div key={`${product.id || product.variant_id || product.sku || productName}-${index}`} className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2">
                    <p className="line-clamp-2 text-xs font-semibold text-emerald-800">{productName}</p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-[11px] font-medium text-emerald-700">{price || 'Catalog product'}</p>
                      {url && (
                        <a href={url} target="_blank" rel="noreferrer" className="text-[11px] font-medium text-emerald-700 underline">
                          View
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}

              {dealers.slice(0, 4).map((dealer, index) => (
                <div key={`${dealer.id || dealer.name || index}`} className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2">
                  <p className="truncate text-xs font-semibold text-blue-800">{dealer.name || `Dealer ${index + 1}`}</p>
                  <p className="mt-1 text-[11px] text-blue-700">{[dealer.city, dealer.state, dealer.phone].filter(Boolean).join(' · ') || 'Dealer result'}</p>
                </div>
              ))}

              {citations.map((citation, index) => (
                <div key={`${citation.doc_id || citation.title || index}`} className="rounded-md border border-primary-200 bg-primary-50 px-3 py-2">
                  <p className="truncate text-xs font-semibold text-primary-700">
                    {citation.title || citation.doc_id || `Context ${index + 1}`}
                  </p>
                  {citation.snippet && <p className="mt-1 line-clamp-3 text-xs leading-5 text-gray-600">{citation.snippet}</p>}
                  {typeof citation.confidence === 'number' && (
                    <p className="mt-2 text-[11px] font-medium text-primary-600">{Math.round(citation.confidence * 100)}% confidence</p>
                  )}
                </div>
              ))}

              {trace.filter(entry => entry.state !== 'waiting').slice(-4).map((entry, index) => (
                <div key={`${entry.label}-${entry.detail}-${index}`} className="rounded-md border border-gray-200 bg-white px-3 py-2">
                  <p className="text-xs font-semibold text-gray-800">{entry.label}</p>
                  <p className="mt-1 line-clamp-3 text-[11px] leading-5 text-gray-500">{entry.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-col">
          <div className="grid grid-cols-2 gap-1 border-b border-gray-200 bg-gray-100 p-1">
            <button
              type="button"
              onClick={() => setTab('chat')}
              className={`rounded px-3 py-2 text-sm font-medium ${tab === 'chat' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
            >
              Chat
            </button>
            <button
              type="button"
              onClick={() => setTab('activity')}
              className={`rounded px-3 py-2 text-sm font-medium ${tab === 'activity' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
            >
              Activity
            </button>
          </div>

          {tab === 'activity' ? (
            <div className="flex-1 overflow-auto p-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Realtime Work Trace</p>
              <div className="space-y-2">
                {trace.map((entry, index) => (
                  <div key={`${entry.label}-${entry.detail}-${index}`} className="flex gap-3 rounded-md border border-gray-200 bg-gray-50 px-3 py-3">
                    <span className={`mt-1 h-2 w-2 rounded-full ${
                      entry.state === 'active' ? 'animate-pulse bg-emerald-500' :
                      entry.state === 'done' ? 'bg-primary-500' :
                      entry.state === 'error' ? 'bg-red-500' :
                      'bg-gray-300'
                    }`} />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-900">{entry.label}</p>
                      <p className="mt-1 text-sm leading-5 text-gray-600">{entry.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex-1 overflow-auto p-4">
              <div className="mb-4 flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-600">
                  <ShieldCheckIcon className="h-3.5 w-3.5" />
                  Guardrails active
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-600">
                  <CircleStackIcon className="h-3.5 w-3.5" />
                  Memory/context visible
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-600">
                  <CommandLineIcon className="h-3.5 w-3.5" />
                  API/skill trace ready
                </span>
              </div>

              {submittedMessage && (
                <div className="ml-auto max-w-[80%] rounded-lg border border-primary-200 bg-primary-50 px-4 py-3 text-sm leading-6 text-gray-900">
                  {submittedMessage}
                </div>
              )}

              {(answer || loading) && (
                <div className="mt-4 max-w-[88%] rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-gray-500">
                    <BoltIcon className="h-3.5 w-3.5" />
                    Nova Agent
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-6 text-gray-900">
                    {answer}
                    {loading && <span className="ml-1 inline-block h-4 w-1 animate-pulse bg-primary-500 align-text-bottom" />}
                  </p>
                </div>
              )}

              {error && (
                <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700">
                  {error}
                </div>
              )}

              {!submittedMessage && !answer && !agentId && (
                <div className="rounded-md border border-dashed border-gray-300 px-4 py-10 text-center text-sm text-gray-500">
                  Save this agent before running inference tests.
                </div>
              )}
            </div>
          )}

          <div className="border-t border-gray-200 bg-gray-50 p-3">
            <div className="mb-3 flex flex-wrap gap-2">
              {['What context are you using?', 'Call the configured API data source', 'Show the active skills'].map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => setMessage(prompt)}
                  className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 hover:border-gray-300 hover:text-gray-900"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <div className="flex items-end gap-2 rounded-md border border-gray-200 bg-white p-2 focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500">
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={2}
                className="min-h-[44px] flex-1 resize-none border-0 bg-transparent p-1 text-sm text-gray-900 outline-none placeholder:text-gray-400"
                placeholder="Ask Nova Agent anything..."
              />
              <button
                type="button"
                onClick={send}
                disabled={!agentId || !message.trim() || loading}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-primary-600 text-white hover:bg-primary-500 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400"
                aria-label="Send test message"
              >
                <PaperAirplaneIcon className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
