# AGENTS.md — Chat Widget SDK (apps/widget)

> **Scope:** Embeddable chat widget for the Agent Builder Platform

---

## 1. Widget Overview
This is an embeddable chat widget that provides:
- **Real-time chat interface** with streaming responses
- **Page context awareness** (URL, title, content extraction)
- **Citation display** with source links
- **Responsive design** for mobile and desktop
- **Easy integration** via script tag or npm package

### Architecture
- **React + TypeScript** for component development
- **Vite** for fast development and optimized builds
- **WebSocket/SSE** for real-time communication
- **Tailwind CSS** for styling
- **Zustand** for state management

---

## 2. Integration Methods

### Script Tag Integration
```html
<script src="https://cdn.agent-builder.com/widget.js"></script>
<script>
  AgentWidget.init({
    apiUrl: 'https://api.agent-builder.com',
    userId: 'user-123',
    theme: 'light',
    position: 'bottom-right'
  });
</script>
```

### NPM Package Integration
```bash
npm install @agent-builder/widget
```

```typescript
import { AgentWidget } from '@agent-builder/widget';

AgentWidget.init({
  apiUrl: 'http://localhost:8000',
  userId: 'user-123',
  pageContext: {
    extractContent: true,
    includeMetadata: true
  }
});
```

---

## 3. Features

### Core Functionality
- **Chat Interface:** Clean, intuitive chat UI
- **Streaming Responses:** Real-time message streaming
- **Citation Display:** Source references with confidence scores
- **Page Context:** Automatic page content extraction
- **Mobile Responsive:** Works on all device sizes

### Customization
- **Themes:** Light, dark, custom CSS variables
- **Positioning:** Bottom-right, bottom-left, sidebar
- **Branding:** Custom colors, logos, messaging
- **Behavior:** Auto-open, greeting messages, triggers
- **Preview URLs:** Admin preview links may pass `?agent_id=...&open=1` so standalone widget previews open immediately for the selected agent

---

## 4. Development

### Local Development
```bash
cd apps/widget
npm install
npm run dev
```

### Building for Production
```bash
npm run build
npm run preview
```

### Testing
```bash
npm run test
npm run test:e2e
```

---

## 5. Configuration Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `apiUrl` | string | Required | Backend API URL |
| `userId` | string | Required | Unique user identifier |
| `theme` | 'light' \| 'dark' | 'light' | Widget theme |
| `position` | 'bottom-right' \| 'bottom-left' | 'bottom-right' | Widget position |
| `pageContext.extractContent` | boolean | true | Extract page content |
| `pageContext.includeMetadata` | boolean | true | Include page metadata |
| `autoOpen` | boolean | false | Auto-open on page load |
| `greeting` | string | null | Initial greeting message |

---

## 6. Integration Notes

- Uses shared API from Phase 5 backend
- Implements citation-first responses
- Follows "No source → No answer" principle
- Real-time streaming via WebSocket/SSE fallback
- Page context extraction for better responses

**End of widget AGENTS.md.** 
