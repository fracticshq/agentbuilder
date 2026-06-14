export function getWidgetBaseUrl(): string {
  const runtimeWidgetUrl = window.__APP_CONFIG__?.WIDGET_BASE_URL;
  const envWidgetUrl = process.env.REACT_APP_WIDGET_URL;
  return (runtimeWidgetUrl || envWidgetUrl || 'http://localhost:5174').replace(/\/+$/, '');
}

export function buildWidgetUrl(agentId: string): string {
  return `${getWidgetBaseUrl()}/?agent_id=${encodeURIComponent(agentId)}&open=1`;
}

export function buildEmbedCode(widgetBaseUrl: string, agentId: string): string {
  return `<script src="${widgetBaseUrl}/embed.js" data-agent-id="${agentId}" async></script>`;
}

export function getWidgetChannel(configuration?: any) {
  const channel = configuration?.channels?.widget || {};
  const features = configuration?.features || {};
  const enabled = channel.enabled ?? true;

  return {
    enabled,
    previewEnabled: channel.preview_enabled ?? enabled,
    allowedOrigins: Array.isArray(channel.allowed_origins) ? channel.allowed_origins : [],
    showSources: channel.show_sources ?? features.show_sources ?? false,
    showProductCards: channel.show_product_cards ?? features.show_product_cards ?? true,
    humanTakeover: channel.human_takeover ?? features.human_takeover ?? false,
  };
}
