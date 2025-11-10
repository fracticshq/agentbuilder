# Widget Configuration Guide

## Agent ID Detection (Auto-configured)

The widget automatically detects the agent ID using the following priority:

### 1. Config Prop (Highest Priority)
```tsx
import App from './App';

const config = {
  apiUrl: 'http://localhost:8000',
  agentId: 'your-agent-id-here',  // ← Explicitly set
  theme: 'light'
};

<App config={config} />
```

### 2. Data Attribute (Recommended for Embedded Widgets)
```html
<!-- Add data-agent-id attribute to script tag -->
<script 
  type="module" 
  src="https://your-domain.com/widget.js"
  data-agent-id="0f603b3f-3023-431a-95bd-3a6fff7cdfb9"
></script>
```

### 3. Auto-Fetch from API (Fallback)
If no agent ID is provided, the widget will:
1. Call `GET /api/v1/admin/agents/`
2. Use the first available agent
3. Log the selected agent to console

```
[Widget] Using first available agent: Essco Bathware 0f603b3f-3023-431a-95bd-3a6fff7cdfb9
```

## Full Configuration Example

```tsx
const config: WidgetConfig = {
  // API Configuration
  apiUrl: 'http://localhost:8000',
  
  // Agent Configuration (optional - auto-detected if not provided)
  agentId: '0f603b3f-3023-431a-95bd-3a6fff7cdfb9',
  
  // User Identification
  userId: 'user_12345',  // Optional, auto-generated if not provided
  
  // Appearance
  theme: 'light',  // 'light' | 'dark'
  position: 'bottom-right',  // 'bottom-right' | 'bottom-left' | 'sidebar'
  
  // Behavior
  autoOpen: false,  // Auto-open widget on page load
  greeting: 'Hi! How can I help you today?',
  
  // Branding
  branding: {
    primaryColor: '#2563eb',
    logo: 'https://example.com/logo.png',
    title: 'Customer Support'
  },
  
  // Page Context
  pageContext: {
    extractContent: true,  // Extract page content for context
    includeMetadata: true  // Include meta tags, schema.org data
  }
};
```

## Embedding the Widget

### Option A: Direct HTML Embed
```html
<!DOCTYPE html>
<html>
<head>
  <title>My Website</title>
</head>
<body>
  <!-- Your page content -->
  
  <!-- Widget will auto-fetch first available agent -->
  <div id="chat-widget"></div>
  <script type="module" src="https://your-cdn.com/widget.js"></script>
</body>
</html>
```

### Option B: With Specific Agent
```html
<!DOCTYPE html>
<html>
<head>
  <title>My Website</title>
</head>
<body>
  <!-- Your page content -->
  
  <!-- Specify agent via data attribute -->
  <div id="chat-widget"></div>
  <script 
    type="module" 
    src="https://your-cdn.com/widget.js"
    data-agent-id="0f603b3f-3023-431a-95bd-3a6fff7cdfb9"
  ></script>
</body>
</html>
```

### Option C: Programmatic Initialization
```html
<!DOCTYPE html>
<html>
<head>
  <title>My Website</title>
</head>
<body>
  <div id="chat-widget"></div>
  
  <script type="module">
    import { createRoot } from 'react-dom/client';
    import App from './widget/App.tsx';
    
    const config = {
      apiUrl: 'https://api.yourcompany.com',
      agentId: '0f603b3f-3023-431a-95bd-3a6fff7cdfb9',
      theme: 'dark',
      position: 'bottom-left'
    };
    
    createRoot(document.getElementById('chat-widget')).render(
      <App config={config} />
    );
  </script>
</body>
</html>
```

## Multi-Agent Deployment

If you have multiple agents (e.g., different departments or brands), you can deploy the same widget code with different agent IDs:

```html
<!-- Sales Department -->
<script 
  data-agent-id="agent-sales-001"
  src="https://cdn.company.com/widget.js"
></script>

<!-- Support Department -->
<script 
  data-agent-id="agent-support-002"
  src="https://cdn.company.com/widget.js"
></script>

<!-- Spanish Language Agent -->
<script 
  data-agent-id="agent-es-003"
  src="https://cdn.company.com/widget.js"
></script>
```

## Troubleshooting

### Widget shows "Agent is still loading"
- Check browser console for error messages
- Verify API is accessible: `curl http://localhost:8000/api/v1/admin/agents/`
- Ensure at least one agent exists in the database

### Widget uses wrong agent
Priority check:
1. Is `config.agentId` set? → Uses that
2. Is `data-agent-id` attribute present? → Uses that
3. Falls back to first agent from API

### How to check which agent is active
Open browser console and look for:
```
[Widget] Using first available agent: Essco Bathware 0f603b3f-3023-431a-95bd-3a6fff7cdfb9
```

## Best Practices

1. **Production**: Always specify `agentId` via config or data attribute
2. **Development**: Auto-fetch is convenient for testing
3. **Multi-tenant**: Use data attributes for different agents per page
4. **SPA**: Pass agentId via config prop for programmatic control
5. **CDN**: Host widget on CDN and use data attributes for configuration
