# Agent Builder Platform - Roadmap

**Last Updated**: October 25, 2025  
**Current Version**: 1.0 (Fully Functional)

---

## 🎯 Future Improvements

### 1. Widget - Expandable Full Screen & Responsive Design

**Priority**: High  
**Estimated Effort**: 3-4 days  
**Status**: Planned

#### Features

- **Expandable Widget**
  - Toggle button to expand widget to full screen
  - Smooth CSS transitions (scale, opacity)
  - Preserve scroll position when toggling
  - ESC key to collapse back to widget mode
  - Remember user preference (localStorage)

- **Responsive Design**
  - Mobile (< 640px): Full screen by default, no widget mode
  - Tablet (640px - 1024px): Expandable widget, optimized layout
  - Desktop (> 1024px): Current widget + expandable option
  - Touch-friendly controls for mobile/tablet
  - Adaptive font sizes and spacing

- **Layout Improvements**
  - Message bubbles: Responsive width (80% on mobile, 70% on desktop)
  - Input area: Fixed bottom with safe area for mobile keyboards
  - Header: Collapsible on scroll for more message space
  - Citation cards: Stack vertically on mobile, grid on desktop

#### Implementation Plan

**Files to Modify:**
```
apps/widget/
├── src/
│   ├── components/
│   │   ├── ChatWidget.tsx          # Add expand/collapse logic
│   │   ├── MessageList.tsx         # Responsive message layout
│   │   ├── MessageInput.tsx        # Mobile-optimized input
│   │   └── CitationCard.tsx        # Responsive citation display
│   ├── styles/
│   │   ├── widget.css              # Media queries and transitions
│   │   └── responsive.css          # NEW - Device-specific styles
│   ├── hooks/
│   │   └── useFullscreen.ts        # NEW - Fullscreen state management
│   └── store/
│       └── widgetStore.ts          # Add isExpanded state
```

**Technical Details:**

```typescript
// useFullscreen.ts
export const useFullscreen = () => {
  const [isExpanded, setIsExpanded] = useState(() => {
    // Load from localStorage
    return localStorage.getItem('widget_expanded') === 'true';
  });

  const toggleExpanded = () => {
    const newState = !isExpanded;
    setIsExpanded(newState);
    localStorage.setItem('widget_expanded', String(newState));
  };

  // ESC key listener
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isExpanded) {
        setIsExpanded(false);
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isExpanded]);

  return { isExpanded, toggleExpanded };
};
```

**CSS Approach:**

```css
/* Responsive breakpoints */
@media (max-width: 640px) {
  .chat-widget {
    /* Mobile: Full screen always */
    width: 100vw !important;
    height: 100vh !important;
    max-width: none !important;
    border-radius: 0 !important;
  }
}

@media (min-width: 641px) and (max-width: 1024px) {
  .chat-widget {
    /* Tablet: Expandable with animations */
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  
  .chat-widget.expanded {
    width: 100vw;
    height: 100vh;
    max-width: none;
    border-radius: 0;
  }
}

@media (min-width: 1025px) {
  .chat-widget {
    /* Desktop: Widget with expand option */
    width: 400px;
    height: 600px;
  }
  
  .chat-widget.expanded {
    width: 90vw;
    height: 90vh;
    max-width: 1400px;
  }
}
```

**Testing Checklist:**
- [ ] Mobile (iPhone, Android): Full screen, no widget mode
- [ ] Tablet (iPad): Expandable widget works
- [ ] Desktop: Toggle between widget and full screen
- [ ] Transitions smooth on all devices
- [ ] ESC key collapses on desktop
- [ ] Preference persists in localStorage
- [ ] Touch gestures work on mobile/tablet

---

### 2. BM25 Threshold Optimization

**Priority**: Medium  
**Estimated Effort**: 1-2 days  
**Status**: Planned

#### Problem

Current similarity threshold is `0.7`, which is too high for BM25 scores (typically 0.002-0.004). This causes only 1 chunk to be used instead of 10, reducing RAG quality when vector search is unavailable.

#### Solution

Implement **conditional thresholds** based on retrieval method:

```python
# apps/api/app/services/message_service.py

class RetrievalConfig:
    # Vector search threshold (high precision)
    VECTOR_SIMILARITY_THRESHOLD = 0.7
    
    # BM25 threshold (lower, accounts for scoring scale)
    BM25_SIMILARITY_THRESHOLD = 0.001  # Much lower for BM25
    
    # Hybrid threshold (balanced)
    HYBRID_SIMILARITY_THRESHOLD = 0.5

async def retrieve_context(self, query: str, agent_id: str) -> List[Chunk]:
    # Determine which retrieval methods are available
    has_vector_index = await self.check_vector_index_exists()
    
    if has_vector_index:
        # Use high threshold for vector search
        threshold = RetrievalConfig.VECTOR_SIMILARITY_THRESHOLD
        chunks = await self.hybrid_retrieval(query, agent_id, threshold)
    else:
        # Use low threshold for BM25-only
        threshold = RetrievalConfig.BM25_SIMILARITY_THRESHOLD
        chunks = await self.bm25_retrieval(query, agent_id, threshold)
    
    logger.info(
        "Retrieval completed",
        method="hybrid" if has_vector_index else "bm25",
        threshold=threshold,
        chunks_retrieved=len(chunks)
    )
    
    return chunks
```

#### Implementation Plan

**Files to Modify:**
```
apps/api/app/
├── services/
│   └── message_service.py         # Add conditional threshold logic
├── config.py                       # Add threshold configuration
└── api/v1/endpoints/
    └── messages.py                 # Expose threshold in response metadata
```

**Configuration:**

```python
# apps/api/app/config.py

class Settings(BaseSettings):
    # ... existing settings
    
    # Retrieval thresholds
    VECTOR_SIMILARITY_THRESHOLD: float = 0.7
    BM25_SIMILARITY_THRESHOLD: float = 0.001
    HYBRID_SIMILARITY_THRESHOLD: float = 0.5
    
    # Auto-detect and adjust
    AUTO_THRESHOLD_ADJUSTMENT: bool = True
```

**Testing:**
- [ ] Test with vector index active: Should use 0.7 threshold
- [ ] Test with vector index disabled: Should use 0.001 threshold
- [ ] Verify 10 chunks retrieved in both cases
- [ ] Compare response quality (BM25-only vs Hybrid)
- [ ] Monitor logs for threshold being applied

---

### 3. Frontend Agent ID from URL

**Priority**: Medium  
**Estimated Effort**: 2-3 days  
**Status**: Planned

#### Features

Allow different agents per page by reading `agent_id` from URL parameters or `data-agent-id` attribute.

#### Implementation

**Option 1: URL Parameter**

```html
<!-- Different agents on different pages -->
<script src="https://yoursite.com/widget.js?agent=essco-agent"></script>
<script src="https://yoursite.com/widget.js?agent=support-agent"></script>
```

**Option 2: Data Attribute**

```html
<!-- Embed widget with custom agent -->
<div id="chat-widget" data-agent-id="f168131d-7833-4f9c-ac8e-8a19b22c16f3"></div>
```

**Option 3: JavaScript API**

```javascript
// Initialize widget with specific agent
window.AgentWidget.init({
  agentId: 'f168131d-7833-4f9c-ac8e-8a19b22c16f3',
  apiUrl: 'http://localhost:8000',
  theme: 'light'
});
```

**Implementation Code:**

```typescript
// apps/widget/src/main.tsx

// Read agent ID from multiple sources (priority order)
function getAgentId(): string {
  // 1. URL parameter (?agent=xxx)
  const urlParams = new URLSearchParams(window.location.search);
  const urlAgent = urlParams.get('agent');
  if (urlAgent) return urlAgent;
  
  // 2. Data attribute (data-agent-id="xxx")
  const widgetEl = document.getElementById('chat-widget');
  const dataAgent = widgetEl?.getAttribute('data-agent-id');
  if (dataAgent) return dataAgent;
  
  // 3. Script tag parameter
  const scriptTag = document.currentScript as HTMLScriptElement;
  const scriptAgent = scriptTag?.getAttribute('data-agent');
  if (scriptAgent) return scriptAgent;
  
  // 4. Default fallback
  return 'f168131d-7833-4f9c-ac8e-8a19b22c16f3';
}

const config: WidgetConfig = {
  apiUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  agentId: getAgentId(),  // ← Dynamic agent ID
  theme: 'light',
  position: 'bottom-right',
  autoOpen: false,
};
```

**Files to Modify:**
```
apps/widget/
├── src/
│   ├── main.tsx                   # Add agent ID detection
│   ├── utils/
│   │   └── agentDetection.ts     # NEW - Agent ID extraction logic
│   └── types/
│       └── index.ts              # Update WidgetConfig interface
└── public/
    └── embed.js                  # NEW - Easy embed script
```

**Embed Script Example:**

```javascript
// apps/widget/public/embed.js
(function() {
  const script = document.currentScript;
  const agentId = script.getAttribute('data-agent') || 'default-agent';
  const apiUrl = script.getAttribute('data-api-url') || 'http://localhost:8000';
  
  // Load widget with custom config
  const widgetScript = document.createElement('script');
  widgetScript.src = '/widget.js';
  widgetScript.setAttribute('data-agent-id', agentId);
  widgetScript.setAttribute('data-api-url', apiUrl);
  document.body.appendChild(widgetScript);
})();
```

**Usage Examples:**

```html
<!-- Example 1: E-commerce site -->
<script src="https://cdn.yoursite.com/widget.js" 
        data-agent="ecommerce-support"></script>

<!-- Example 2: Documentation site -->
<script src="https://cdn.yoursite.com/widget.js" 
        data-agent="docs-assistant"></script>

<!-- Example 3: Different agents per product page -->
<script src="https://cdn.yoursite.com/widget.js" 
        data-agent="product-specialist-{{product_id}}"></script>
```

**Testing:**
- [ ] URL parameter works: `?agent=test-agent`
- [ ] Data attribute works: `data-agent-id="xxx"`
- [ ] Script tag works: `<script data-agent="xxx">`
- [ ] Fallback to default if none provided
- [ ] Multiple widgets on same page with different agents
- [ ] Agent ID properly sent in API requests

---

### 4. Streaming Response

**Priority**: High  
**Estimated Effort**: 3-4 days  
**Status**: Planned

#### Features

Real-time streaming of AI responses instead of waiting for complete response.

#### Implementation

**Backend (Already Partially Supported):**

```python
# apps/api/app/api/v1/endpoints/messages.py

@router.post("/stream")
async def stream_message(
    request: MessageRequest,
    message_service: MessageService = Depends(get_message_service)
):
    """Stream message response token by token."""
    
    async def generate():
        try:
            # Stream from LLM
            async for chunk in message_service.stream_response(request):
                # Send Server-Sent Events
                yield f"data: {json.dumps(chunk)}\n\n"
            
            # Send done signal
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Streaming error", error=str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

**Frontend (Widget):**

```typescript
// apps/widget/src/utils/apiClient.ts

async sendMessageStream(
  request: { content: string; context?: PageContext; userId?: string },
  conversationId?: string,
  agentId?: string,
  onToken?: (token: string) => void,
  onComplete?: (message: Message) => void
): Promise<void> {
  const requestBody = {
    message: request.content,
    user_id: request.userId || 'anonymous',
    conversation_id: conversationId,
    agent_id: agentId,
    page_context: request.context,
  };

  const response = await fetch(`${this.baseUrl}/api/v1/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  });

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullMessage = '';

  while (true) {
    const { done, value } = await reader!.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') {
          onComplete?.({
            id: crypto.randomUUID(),
            content: fullMessage,
            role: 'assistant',
            timestamp: new Date().toISOString(),
          });
          return;
        }

        try {
          const chunk = JSON.parse(data);
          if (chunk.token) {
            fullMessage += chunk.token;
            onToken?.(chunk.token);
          }
        } catch (e) {
          console.error('Parse error:', e);
        }
      }
    }
  }
}
```

**UI Component:**

```typescript
// apps/widget/src/components/MessageList.tsx

const MessageBubble = ({ message, isStreaming }: Props) => {
  return (
    <div className={`message ${message.role}`}>
      <div className="content">
        {message.content}
        {isStreaming && <span className="cursor">▊</span>}
      </div>
    </div>
  );
};
```

**Files to Modify:**
```
apps/api/app/
├── api/v1/endpoints/
│   └── messages.py               # Add /stream endpoint
└── services/
    └── message_service.py        # Add stream_response method

apps/widget/src/
├── utils/
│   └── apiClient.ts              # Add streaming support
├── components/
│   ├── MessageList.tsx           # Show streaming cursor
│   └── MessageBubble.tsx         # Render tokens as they arrive
└── hooks/
    └── useStreamingMessage.ts    # NEW - Streaming state management
```

**Testing:**
- [ ] Tokens arrive in real-time (not all at once)
- [ ] Cursor blinks during streaming
- [ ] Citations appear after streaming completes
- [ ] Error handling during stream interruption
- [ ] Works with slow network connections
- [ ] Memory/performance with long responses

---

### 5. Enhanced Citations UI

**Priority**: Medium  
**Estimated Effort**: 2-3 days  
**Status**: Planned

#### Features

**Inline Citations:**
```
The Essco Premium Faucet costs ₹4,500 [1] and features 
chrome finish [2] with a 5-year warranty [3].

References:
[1] Product Catalog, page 24
[2] Product Specifications, Section 2.3
[3] Warranty Terms, Article 5
```

**Citation Preview:**
- Hover over citation number → tooltip with excerpt
- Click citation → expand full context in modal
- Highlight relevant text in citation source

**Citation Grouping:**
- Group by document type (products, FAQs, policies)
- Show relevance score for each citation
- Link to original document if available

#### Implementation

**Backend Response Format:**

```json
{
  "content": "The Essco Premium Faucet costs ₹4,500 {{cite:1}} and features chrome finish {{cite:2}}.",
  "citations": [
    {
      "id": 1,
      "title": "Product Catalog",
      "excerpt": "Essco Premium Faucet - Chrome Finish - ₹4,500",
      "source": "product_catalog.json",
      "page": 24,
      "relevance_score": 0.95,
      "url": "https://essco.com/products/premium-faucet"
    },
    {
      "id": 2,
      "title": "Product Specifications",
      "excerpt": "Chrome finish with anti-corrosion coating...",
      "source": "specifications.pdf",
      "section": "2.3",
      "relevance_score": 0.87
    }
  ]
}
```

**Frontend Components:**

```typescript
// apps/widget/src/components/Citations/InlineCitation.tsx
export const InlineCitation = ({ id, citation }: Props) => {
  const [showPreview, setShowPreview] = useState(false);

  return (
    <span 
      className="inline-citation"
      onMouseEnter={() => setShowPreview(true)}
      onMouseLeave={() => setShowPreview(false)}
      onClick={() => openCitationModal(citation)}
    >
      [{id}]
      {showPreview && (
        <div className="citation-preview">
          <h4>{citation.title}</h4>
          <p>{citation.excerpt}</p>
          <span className="relevance">
            Relevance: {(citation.relevance_score * 100).toFixed(0)}%
          </span>
        </div>
      )}
    </span>
  );
};
```

```typescript
// apps/widget/src/components/Citations/CitationModal.tsx
export const CitationModal = ({ citation, onClose }: Props) => {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <header>
          <h3>{citation.title}</h3>
          <button onClick={onClose}>×</button>
        </header>
        
        <div className="citation-body">
          <div className="metadata">
            <span>Source: {citation.source}</span>
            <span>Page: {citation.page}</span>
            <span>Relevance: {citation.relevance_score}</span>
          </div>
          
          <div className="excerpt">
            <p>{citation.excerpt}</p>
          </div>
          
          {citation.url && (
            <a href={citation.url} target="_blank">
              View Full Document →
            </a>
          )}
        </div>
      </div>
    </div>
  );
};
```

**Files to Create/Modify:**
```
apps/widget/src/
├── components/
│   ├── Citations/
│   │   ├── InlineCitation.tsx       # NEW - [1] style citations
│   │   ├── CitationModal.tsx        # NEW - Full citation view
│   │   ├── CitationPreview.tsx      # NEW - Hover tooltip
│   │   └── CitationList.tsx         # NEW - All citations list
│   └── MessageBubble.tsx            # Parse and render inline citations
└── utils/
    └── citationParser.ts            # NEW - Parse {{cite:X}} markers
```

**CSS Styling:**

```css
/* Inline citations */
.inline-citation {
  color: #2563eb;
  font-size: 0.85em;
  vertical-align: super;
  cursor: pointer;
  padding: 0 2px;
  border-radius: 2px;
  transition: background 0.2s;
}

.inline-citation:hover {
  background: #dbeafe;
}

/* Citation preview tooltip */
.citation-preview {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  min-width: 300px;
  max-width: 400px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  z-index: 1000;
}

/* Citation modal */
.citation-modal {
  max-width: 600px;
  max-height: 80vh;
  overflow-y: auto;
}

.citation-body {
  padding: 20px;
}

.metadata {
  display: flex;
  gap: 16px;
  font-size: 0.875rem;
  color: #6b7280;
  margin-bottom: 16px;
}

.excerpt {
  background: #f9fafb;
  padding: 16px;
  border-radius: 6px;
  border-left: 3px solid #2563eb;
}
```

**Testing:**
- [ ] Inline citations render correctly
- [ ] Hover shows preview tooltip
- [ ] Click opens modal with full citation
- [ ] Multiple citations in same message
- [ ] Citations grouped by type
- [ ] Relevance scores displayed
- [ ] External links open in new tab

---

## 📅 Implementation Timeline

### Phase 1: Core UX Improvements (2 weeks)
- Week 1: Widget expandable + responsive design
- Week 2: Streaming response implementation

### Phase 2: Enhanced Features (1.5 weeks)
- Week 3-4: Enhanced citations UI
- Week 4: Frontend agent ID from URL

### Phase 3: Optimizations (0.5 weeks)
- Week 4: BM25 threshold optimization

### Total Estimated Time: 4 weeks

---

## 🎯 Success Metrics

### Widget Improvements
- [ ] Works on mobile (iOS Safari, Android Chrome)
- [ ] Works on tablet (iPad, Android tablets)
- [ ] Smooth 60fps animations
- [ ] Load time < 2s on 3G

### Streaming
- [ ] First token arrives < 500ms
- [ ] Tokens stream smoothly (no buffering)
- [ ] User can interrupt/cancel stream

### Citations
- [ ] Citations visible and clickable
- [ ] Preview loads < 100ms
- [ ] Modal accessible (keyboard navigation)

### BM25 Optimization
- [ ] 10 chunks retrieved (not 1)
- [ ] Response quality improves 20%+
- [ ] Works without vector index

---

## 🔄 Current Status Summary

**Completed** ✅
- RAG system with vector search
- Memory persistence (short-term, episodic, graph)
- Admin dashboard CRUD
- Knowledge base storage
- Widget with agent_id support

**In Progress** 🔄
- None (all current tasks complete)

**Planned** 📋
1. Widget expandable & responsive
2. BM25 threshold optimization
3. Frontend agent_id from URL
4. Streaming response
5. Enhanced citations UI

---

**Last Updated**: October 25, 2025  
**Next Review**: November 1, 2025
