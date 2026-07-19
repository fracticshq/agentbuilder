import type { ActivityControl, ActivityState, ActivityStep, PlaceCandidate, StreamingMessage } from '../types';

// This timeline is a GENERAL capability for every agent in the builder. It maps
// the standard streaming events that any agent emits (context_*, tool_*,
// skill_*, status, connector_*, rag_context) into ordered steps. Nothing here is
// specific to one agent template — labels fall back to whatever the backend
// sends, so a brand-new agent surfaces its real activity with zero extra config.

export const EMPTY_ACTIVITY: ActivityState = { steps: [], disambiguation: undefined, prompt: undefined };

// Keep the widget generic. Humanized labels should come from backend activity
// envelopes, not template-specific frontend mappings.
const ENDPOINT_LABELS: Record<string, string> = {};

type StreamingMetadata = Record<string, unknown>;

function isMetadata(value: unknown): value is StreamingMetadata {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return value ? String(value) : '';
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function isActivityControl(value: unknown): value is ActivityControl {
  return isMetadata(value)
    && typeof value.type === 'string'
    && typeof value.id === 'string'
    && typeof value.label === 'string';
}

function getActivityControls(value: unknown): ActivityControl[] {
  return Array.isArray(value) ? value.filter(isActivityControl) : [];
}

function getPlaceCandidates(value: unknown): PlaceCandidate[] {
  if (!Array.isArray(value)) return [];

  return value.filter(isMetadata).map((candidate) => {
    const name = optionalString(candidate.name);
    const adminRegion = optionalString(candidate.adminRegion);
    const country = optionalString(candidate.country);
    return {
      placeId: optionalString(candidate.placeId),
      label: stringValue(candidate.label) || [name, adminRegion, country].filter(Boolean).join(', '),
      name,
      adminRegion,
      country,
    };
  });
}

function connectorLabel(meta: StreamingMetadata, fallback: string): string {
  const id = stringValue(meta.endpoint_id);
  return ENDPOINT_LABELS[id] || stringValue(meta.endpoint_name) || stringValue(meta.connector_name) || fallback;
}

// Orchestrator tool steps key/label by tool_name (e.g.
// "tool_context_vedika_lal_kitab_lalkitab_chart" or "skill_knowledge_qa").
function toolKey(meta: StreamingMetadata, fallback: string): string {
  return stringValue(meta.step_id || meta.tool_id || meta.tool_name || fallback);
}

function toolLabel(meta: StreamingMetadata, fallback: string): string {
  const name = stringValue(meta.tool_name);
  // A connector tool embeds the endpoint id at the end → reuse friendly labels.
  for (const key of Object.keys(ENDPOINT_LABELS)) {
    if (name.endsWith(key)) return ENDPOINT_LABELS[key];
  }
  if (name) {
    const cleaned = name
      .replace(/^tool_context_[a-z0-9]+_[a-z0-9]+_/i, '')
      .replace(/^(tool_|skill_)/i, '')
      .replace(/_/g, ' ')
      .trim();
    if (cleaned) return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
  }
  return fallback;
}

function latencyDetail(meta: StreamingMetadata): string | undefined {
  const ms = Number(meta.latency_ms);
  if (!Number.isFinite(ms) || ms <= 0) return undefined;
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function upsert(steps: ActivityStep[], id: string, patch: Partial<ActivityStep>): ActivityStep[] {
  const next = steps.slice();
  const i = next.findIndex((s) => s.id === id);
  if (i >= 0) next[i] = { ...next[i], ...patch };
  else next.push({ id, label: '', status: 'running', ...patch });
  return next;
}

function activityStatus(status: unknown): ActivityStep['status'] {
  if (status === 'completed') return 'done';
  if (status === 'failed') return 'error';
  return 'running';
}

/**
 * Fold one streaming event into the activity-timeline state. Pure and
 * deterministic so it can be unit-tested and replayed. Returns the same
 * reference for events that don't affect the timeline (content/metadata/etc).
 */
export function reduceActivity(state: ActivityState, chunk: StreamingMessage): ActivityState {
  const meta = chunk.metadata || {};
  const content = chunk.content || '';
  let steps = state.steps;

  switch (chunk.type) {
    case 'activity': {
      const activity = isMetadata(meta.activity) ? meta.activity : meta;
      if (activity.visibility && activity.visibility !== 'public') {
        return state;
      }
      const id = stringValue(activity.activity_id || activity.id || activity.kind || content || 'activity');
      const controls = getActivityControls(activity.controls);
      steps = upsert(steps, id, {
        label: stringValue(activity.label) || content || 'Working',
        detail: stringValue(activity.summary) || undefined,
        status: activityStatus(activity.status),
      });
      if (activity.kind === 'user_input_request' && controls.length) {
        return {
          steps,
          disambiguation: state.disambiguation,
          prompt: {
            question: stringValue(activity.summary) || stringValue(activity.label) || content || 'Please choose an option.',
            controls,
          },
        };
      }
      break;
    }

    case 'context_start':
      steps = upsert(steps, 'context', { label: 'Loading agent context', status: 'running' });
      break;
    case 'context_result':
      steps = upsert(steps, 'context', { label: 'Agent context loaded', status: 'done' });
      break;

    case 'geocode_start':
      steps = upsert(steps, 'geocode', { label: content || 'Resolving birthplace…', status: 'running' });
      break;
    case 'geocode_result':
      steps = upsert(steps, 'geocode', {
        label: content || 'Birthplace resolved',
        status: meta.success === false ? 'error' : 'done',
      });
      break;

    case 'connector_start': {
      const id = `conn:${meta.endpoint_id || meta.endpoint_name || content}`;
      steps = upsert(steps, id, { label: connectorLabel(meta, content), status: 'running' });
      break;
    }
    case 'connector_result':
    case 'connector_error': {
      const id = `conn:${meta.endpoint_id || meta.endpoint_name || content}`;
      const ok = chunk.type === 'connector_result' && meta.success !== false;
      steps = upsert(steps, id, {
        label: connectorLabel(meta, content),
        status: ok ? 'done' : 'error',
        detail: latencyDetail(meta),
      });
      break;
    }

    case 'api_context':
      steps = upsert(steps, 'api_context', { label: 'Calculated context ready', status: 'done' });
      break;

    case 'rag_context':
      steps = upsert(steps, 'rag', { label: content || 'Reading the knowledge base', status: 'done' });
      break;

    case 'tool_start':
      steps = upsert(steps, `tool:${toolKey(meta, content)}`, { label: toolLabel(meta, content || 'Running tool…'), status: 'running' });
      break;
    case 'tool_result':
      steps = upsert(steps, `tool:${toolKey(meta, content)}`, {
        label: toolLabel(meta, content || 'Tool finished'),
        status: meta.success === false ? 'error' : 'done',
        detail: latencyDetail(meta),
      });
      break;
    case 'tool_error':
      steps = upsert(steps, `tool:${toolKey(meta, content)}`, { label: toolLabel(meta, content || 'Tool error'), status: 'error' });
      break;

    case 'skill_start':
      steps = upsert(steps, `tool:${toolKey(meta, content)}`, { label: toolLabel(meta, content || 'Running skill…'), status: 'running' });
      break;
    case 'skill_result':
      steps = upsert(steps, `tool:${toolKey(meta, content)}`, { label: toolLabel(meta, content || 'Skill finished'), status: meta.success === false ? 'error' : 'done' });
      break;

    case 'status':
      // A transient, single rolling status line (e.g. "Synthesizing your reading…").
      steps = upsert(steps, 'status', { label: content || 'Working…', status: 'running' });
      break;

    case 'place_disambiguation': {
      const candidates = getPlaceCandidates(meta.candidates);
      return { steps, disambiguation: { question: content, candidates }, prompt: state.prompt };
    }

    default:
      return state; // content / final_answer / metadata / done / error / missing_input
  }

  return { steps, disambiguation: state.disambiguation, prompt: state.prompt };
}

/** Mark every still-running step as done — used when the answer starts streaming. */
export function finalizeActivity(state: ActivityState): ActivityState {
  if (!state.steps.some((s) => s.status === 'running')) return state;
  return {
    ...state,
    steps: state.steps.map((s) => (s.status === 'running' ? { ...s, status: 'done' } : s)),
  };
}
