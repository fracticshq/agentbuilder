/**
 * Activity client — fire-and-forget event tracking.
 * Never throws; errors are silently swallowed so tracking never breaks the chat flow.
 */

const API_BASE = 'http://localhost:8000';

export interface TrackEventOptions {
  event_type: string;
  actor_type: 'user' | 'agent' | 'system';
  actor_id: string;
  agent_id: string;
  conversation_id: string;
  session_id?: string;
  payload?: Record<string, unknown>;
  page_context?: { url: string; title?: string };
}

export async function trackEvent(opts: TrackEventOptions): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/v1/activity/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    });
  } catch {
    // Intentionally swallowed — tracking must never surface errors to users.
  }
}
