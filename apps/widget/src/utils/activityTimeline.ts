import type { ActivityState, ActivityStep, PlaceCandidate, StreamingMessage } from '../types';

// This timeline is a GENERAL capability for every agent in the builder. It maps
// the standard streaming events that any agent emits (context_*, tool_*,
// skill_*, status, connector_*, rag_context) into ordered steps. Nothing here is
// specific to one agent template — labels fall back to whatever the backend
// sends, so a brand-new agent surfaces its real activity with zero extra config.

export const EMPTY_ACTIVITY: ActivityState = { steps: [], disambiguation: undefined };

// Optional cosmetic nice-ups: friendlier verbs for a few well-known endpoint ids.
// Purely additive — any endpoint not listed uses the backend-supplied name.
const ENDPOINT_LABELS: Record<string, string> = {
  lalkitab_chart: 'Casting the Lal Kitab chart',
  lalkitab_remedies: 'Gathering remedies',
  lalkitab_totke: 'Gathering totke',
  lalkitab_predictions: 'Reading predictions',
  lalkitab_varshphal: 'Computing the varshphal',
  lalkitab_debts: 'Checking karmic debts',
  lalkitab_houses: 'Analysing the houses',
  lalkitab_lucky: 'Finding lucky factors',
};

function connectorLabel(meta: Record<string, any>, fallback: string): string {
  const id = String(meta.endpoint_id || '');
  return ENDPOINT_LABELS[id] || meta.endpoint_name || meta.connector_name || fallback;
}

function latencyDetail(meta: Record<string, any>): string | undefined {
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
      steps = upsert(steps, `tool:${meta.tool_id || content}`, { label: content || 'Running tool…', status: 'running' });
      break;
    case 'tool_result':
      steps = upsert(steps, `tool:${meta.tool_id || 'tool'}`, {
        label: content || 'Tool finished',
        status: meta.success === false ? 'error' : 'done',
      });
      break;
    case 'tool_error':
      steps = upsert(steps, `tool:${meta.tool_id || content}`, { label: content || 'Tool error', status: 'error' });
      break;

    case 'skill_start':
      steps = upsert(steps, `skill:${meta.skill_id || content}`, { label: content || 'Running skill…', status: 'running' });
      break;
    case 'skill_result':
      steps = upsert(steps, `skill:${meta.skill_id || content}`, { label: content || 'Skill finished', status: 'done' });
      break;

    case 'status':
      // A transient, single rolling status line (e.g. "Synthesizing your reading…").
      steps = upsert(steps, 'status', { label: content || 'Working…', status: 'running' });
      break;

    case 'place_disambiguation': {
      const candidates: PlaceCandidate[] = (meta.candidates || []).map((c: any) => ({
        placeId: c.placeId,
        label: c.label || [c.name, c.adminRegion, c.country].filter(Boolean).join(', '),
        name: c.name,
        adminRegion: c.adminRegion,
        country: c.country,
      }));
      return { steps, disambiguation: { question: content, candidates } };
    }

    default:
      return state; // content / final_answer / metadata / done / error / missing_input
  }

  return { steps, disambiguation: state.disambiguation };
}

/** Mark every still-running step as done — used when the answer starts streaming. */
export function finalizeActivity(state: ActivityState): ActivityState {
  if (!state.steps.some((s) => s.status === 'running')) return state;
  return {
    ...state,
    steps: state.steps.map((s) => (s.status === 'running' ? { ...s, status: 'done' } : s)),
  };
}
