(function () {
  var script = document.currentScript;
  if (!script) return;

  var agentId = script.getAttribute('data-agent-id');
  if (!agentId) {
    console.error('[AgentBuilder] Missing data-agent-id on embed script.');
    return;
  }

  var existingFrame = document.getElementById('agentbuilder-widget-frame');
  if (existingFrame) {
    existingFrame.parentNode && existingFrame.parentNode.removeChild(existingFrame);
  }

  var scriptUrl = new URL(script.src, window.location.href);
  var configuredWidgetUrl = script.getAttribute('data-widget-url');
  var widgetBaseUrl = configuredWidgetUrl ? new URL(configuredWidgetUrl, window.location.href) : scriptUrl;
  widgetBaseUrl.pathname = widgetBaseUrl.pathname.replace(/\/embed\.js$/, '/');
  widgetBaseUrl.search = '';
  widgetBaseUrl.hash = '';

  var widgetUrl = new URL(widgetBaseUrl.href);
  widgetUrl.searchParams.set('agent_id', agentId);
  widgetUrl.searchParams.set('embedded', '1');

  if (script.getAttribute('data-open') === 'true') {
    widgetUrl.searchParams.set('open', '1');
  }

  var frame = document.createElement('iframe');
  frame.id = 'agentbuilder-widget-frame';
  frame.title = script.getAttribute('data-title') || 'AI chat assistant';
  frame.src = widgetUrl.href;
  frame.allow = 'clipboard-write';
  frame.setAttribute('aria-live', 'polite');

  var side = script.getAttribute('data-side') === 'left' ? 'left' : 'right';
  var bottom = script.getAttribute('data-bottom') || '0';
  var sideOffset = script.getAttribute('data-offset') || '0';

  Object.assign(frame.style, {
    position: 'fixed',
    bottom: bottom,
    width: '104px',
    height: '104px',
    border: '0',
    background: 'transparent',
    colorScheme: 'normal',
    zIndex: script.getAttribute('data-z-index') || '2147483000',
    overflow: 'hidden',
    transition: 'width 180ms ease, height 180ms ease',
  });
  frame.style[side] = sideOffset;

  function setFrameSize(state) {
    var isExpanded = Boolean(state && state.isExpanded);
    var isOpen = Boolean(state && state.isOpen);

    if (isExpanded) {
      frame.style.width = '100vw';
      frame.style.height = '100vh';
      frame.style.bottom = '0';
      frame.style[side] = '0';
      return;
    }

    frame.style.bottom = bottom;
    frame.style[side] = sideOffset;
    if (isOpen) {
      frame.style.width = 'min(420px, 100vw)';
      frame.style.height = 'min(760px, 100vh)';
    } else {
      frame.style.width = '104px';
      frame.style.height = '104px';
    }
  }

  window.addEventListener('message', function (event) {
    if (event.source !== frame.contentWindow) return;
    if (event.origin !== widgetBaseUrl.origin) return;
    if (!event.data || event.data.type !== 'agentbuilder-widget-state') return;
    setFrameSize(event.data);
  });

  document.body.appendChild(frame);
})();
