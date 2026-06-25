import { describe, it, expect } from 'vitest';
import { reduceActivity, finalizeActivity, EMPTY_ACTIVITY } from './activityTimeline';
import type { StreamingMessage } from '../types';

function ev(type: string, content = '', metadata: Record<string, any> = {}): StreamingMessage {
  return { type: type as StreamingMessage['type'], content, conversation_id: 'c', metadata };
}

describe('reduceActivity', () => {
  it('ignores content/metadata/done without changing state', () => {
    const s = reduceActivity(EMPTY_ACTIVITY, ev('content', 'hello'));
    expect(s).toBe(EMPTY_ACTIVITY);
  });

  it('pairs context_start and context_result into one step', () => {
    let s = reduceActivity(EMPTY_ACTIVITY, ev('context_start'));
    expect(s.steps).toHaveLength(1);
    expect(s.steps[0].status).toBe('running');
    s = reduceActivity(s, ev('context_result'));
    expect(s.steps).toHaveLength(1);
    expect(s.steps[0].status).toBe('done');
  });

  it('keys connector steps by endpoint_id so start/result update the same row', () => {
    let s = reduceActivity(EMPTY_ACTIVITY, ev('connector_start', 'Checking configured source', { endpoint_id: 'custom_endpoint' }));
    s = reduceActivity(s, ev('connector_result', 'Configured source returned context', { endpoint_id: 'custom_endpoint', success: true, latency_ms: 1636 }));
    expect(s.steps).toHaveLength(1);
    expect(s.steps[0].label).toBe('Configured source returned context');
    expect(s.steps[0].status).toBe('done');
    expect(s.steps[0].detail).toBe('1.6s');
  });

  it('marks connector_error as error', () => {
    let s = reduceActivity(EMPTY_ACTIVITY, ev('connector_start', 'x', { endpoint_id: 'lalkitab_remedies' }));
    s = reduceActivity(s, ev('connector_error', 'failed', { endpoint_id: 'lalkitab_remedies', success: false }));
    expect(s.steps[0].status).toBe('error');
  });

  it('works generically for any agent via tool/skill/status events', () => {
    let s = reduceActivity(EMPTY_ACTIVITY, ev('tool_start', 'Searching catalog', { tool_id: 'catalog' }));
    s = reduceActivity(s, ev('tool_result', 'Found 3 products', { tool_id: 'catalog' }));
    s = reduceActivity(s, ev('status', 'Synthesizing…'));
    expect(s.steps.map((x) => x.status)).toEqual(['done', 'running']);
    expect(s.steps[0].label).toBe('Found 3 products');
  });

  it('renders generic public activity envelopes and controls', () => {
    const s = reduceActivity(
      EMPTY_ACTIVITY,
      ev('activity', 'Need a few details', {
        activity: {
          activity_id: 'input:missing',
          kind: 'user_input_request',
          status: 'waiting_for_user',
          visibility: 'public',
          label: 'Need a few details',
          summary: 'Please share your budget.',
          controls: [{ type: 'number', id: 'budget', label: 'Budget' }],
        },
      }),
    );
    expect(s.steps[0].label).toBe('Need a few details');
    expect(s.steps[0].status).toBe('running');
    expect(s.prompt?.controls[0].id).toBe('budget');
  });

  it('ignores console-only activity envelopes in the public widget', () => {
    const s = reduceActivity(
      EMPTY_ACTIVITY,
      ev('activity', 'Connector called', {
        activity: {
          activity_id: 'console:connector',
          kind: 'connector_call',
          status: 'completed',
          visibility: 'console',
          label: 'Vedika API call',
        },
      }),
    );
    expect(s).toBe(EMPTY_ACTIVITY);
  });

  it('captures place_disambiguation candidates', () => {
    const s = reduceActivity(
      EMPTY_ACTIVITY,
      ev('place_disambiguation', 'Which one?', {
        candidates: [
          { placeId: 'IN', label: 'Hyderabad, Telangana, India' },
          { placeId: 'PK', label: 'Hyderabad, Sindh, Pakistan' },
        ],
      }),
    );
    expect(s.disambiguation?.candidates).toHaveLength(2);
    expect(s.disambiguation?.question).toBe('Which one?');
  });
});

describe('finalizeActivity', () => {
  it('flips running steps to done', () => {
    let s = reduceActivity(EMPTY_ACTIVITY, ev('connector_start', 'x', { endpoint_id: 'lalkitab_chart' }));
    s = finalizeActivity(s);
    expect(s.steps[0].status).toBe('done');
  });
});
