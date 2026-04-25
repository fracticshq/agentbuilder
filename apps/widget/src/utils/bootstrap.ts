export function isTruthyQueryFlag(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }

  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

export function shouldAutoOpenFromSearch(search: string): boolean {
  const params = new URLSearchParams(search);
  return isTruthyQueryFlag(params.get('open')) || isTruthyQueryFlag(params.get('preview'));
}

export function getConversationStorageKey(agentId: string | null | undefined): string {
  return agentId ? `agent_widget_conversation_id_${agentId}` : 'agent_widget_conversation_id';
}
