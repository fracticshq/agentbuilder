import { describe, expect, it } from 'vitest';
import {
  getConversationStorageKey,
  isTruthyQueryFlag,
  shouldAutoOpenFromSearch,
} from './bootstrap';

describe('widget bootstrap helpers', () => {
  it('treats common query flag variants as truthy', () => {
    expect(isTruthyQueryFlag('1')).toBe(true);
    expect(isTruthyQueryFlag('true')).toBe(true);
    expect(isTruthyQueryFlag('YES')).toBe(true);
    expect(isTruthyQueryFlag('on')).toBe(true);
    expect(isTruthyQueryFlag('0')).toBe(false);
    expect(isTruthyQueryFlag('false')).toBe(false);
    expect(isTruthyQueryFlag(null)).toBe(false);
  });

  it('auto-opens preview when open or preview flags are set', () => {
    expect(shouldAutoOpenFromSearch('?agent_id=essco&open=1')).toBe(true);
    expect(shouldAutoOpenFromSearch('?agent_id=essco&preview=true')).toBe(true);
    expect(shouldAutoOpenFromSearch('?agent_id=essco')).toBe(false);
  });

  it('scopes conversation storage to the active agent', () => {
    expect(getConversationStorageKey('agent-1')).toBe('agent_widget_conversation_id_agent-1');
    expect(getConversationStorageKey(undefined)).toBe('agent_widget_conversation_id');
  });
});
