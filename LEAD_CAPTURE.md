# Lead Capture — Full Architecture

How the conversational inquiry/lead-capture feature works end-to-end, from
admin configuration through widget interaction to email delivery.

---

## 1. Overview

The lead-capture feature lets any AI agent collect contact details from a
visitor in a natural multi-turn conversation and email them to the brand owner,
with no CRM required. It is controlled by a single per-agent toggle in the
Admin → Agent Studio → Skills panel ("Lead Capture · Via Email · No CRM").

When enabled, every product card in the widget shows a **"Send Inquiry for
Price →"** button. Clicking it — or typing a purchase-intent phrase like
"send inquiry" / "request a quote" — starts an automatic, deterministic
multi-turn flow that collects 7 required fields in two conversational batches,
shows a confirmation summary, and on approval sends an email to the configured
recipient.

---

## 2. Files Involved

| Layer | File | Responsibility |
|---|---|---|
| Admin UI | `apps/admin/src/components/AgentStudio/AgentCapabilityRail.tsx` | "Lead Capture · Via Email · No CRM" skill toggle |
| Admin UI | `apps/admin/src/components/AgentStudio/AgentConfigForm.tsx` | Recipient email, confirm-before-send, success message fields |
| Admin save | `apps/admin/src/utils/agentWizardPayload.ts` | Serialises `inquiry.*` fields into agent configuration payload |
| Public API | `apps/api/app/api/v1/endpoints/public.py` | Exposes `inquiry.enabled` in `/api/v1/public/agents/{id}` |
| Widget bootstrap | `apps/widget/src/App.tsx` | Reads `inquiry.enabled`, sets `showInquiry` state |
| Widget UI | `apps/widget/src/components/ProductCard.tsx` | Renders "Send Inquiry for Price →" button, calls `onSendInquiry` on click |
| Widget UI | `apps/widget/src/components/MessageBubble.tsx` | Passes `onSendInquiry` prop down to ProductCard |
| Widget UI | `apps/widget/src/components/ChatWindow.tsx` | Provides `onSendMessage` as the `onSendInquiry` implementation |
| Orchestration | `apps/api/app/services/message_service.py` | All inquiry orchestration: trigger detection, pending state, field parsing, tool wiring |
| Tool | `packages/tools/src/tools/builtin/inquiry_tool.py` | Field batching, validation, confirmation logic, callback invocation |
| Persistence | `apps/api/app/services/inquiry_service.py` | Saves inquiry doc to brand-isolated MongoDB collection |
| Delivery | `apps/api/app/services/inquiry_delivery_service.py` | Sends email via SMTP in a worker thread |
| Config | `apps/api/app/config.py` | SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL/USE_TLS, INQUIRY_FALLBACK_RECIPIENT |

---

## 3. Configuration (Admin Panel)

### Enable the skill

1. Open **Agent Studio** for any agent.
2. In the **Skills** rail, click **"Lead Capture · Via Email · No CRM"** to toggle it on.
3. This sets `configuration.inquiry.enabled = true` in the agent's MongoDB document (system DB → `agents` collection).

### Inquiry config fields stored

```json
{
  "inquiry": {
    "enabled": true,
    "recipient_email": "owner@brand.com",
    "confirm_before_send": true,
    "success_message": "Your inquiry has been sent. Our team will reach out shortly!"
  }
}
```

- **`recipient_email`** — where the email is sent. Falls back to `INQUIRY_FALLBACK_RECIPIENT` env var if empty.
- **`confirm_before_send`** — default `true`. When true the agent shows a summary and waits for the user to confirm before sending.
- **`success_message`** — shown to the user after successful delivery.

---

## 4. Widget Bootstrap — How the Flag Reaches the Frontend

```
App.tsx (useEffect on agentId)
  │
  ├─ GET /api/v1/public/agents/{agent_id}
  │      └─ public.py: _public_agent_config()
  │             reads configuration.inquiry → exposes {enabled, recipient_email, ...}
  │
  ├─ setShowInquiry(agent.configuration.inquiry.enabled === true)
  │
  └─ passes showInquiry={showInquiry} → ChatWindow → MessageBubble
```

The `inquiry` block is deliberately kept in the public config response so the
widget can show/hide the button without an authenticated request.

---

## 5. Product Card Button

**`apps/widget/src/components/ProductCard.tsx`**

Two independent buttons are rendered:

```
┌────────────────────────┐
│  Learn More →          │   shown when product has a URL (ctaUrl)
│  Send Inquiry for Price│   shown when showInquiry=true AND onSendInquiry is provided
└────────────────────────┘
```

When the user clicks **"Send Inquiry for Price →"**:

```ts
onSendInquiry(`Send inquiry for price of ${displayProduct.name}`)
```

This calls `onSendMessage` in `ChatWindow`, which:
1. Appends the text as a user chat bubble (visible in the UI)
2. Sends it to the backend WebSocket / HTTP endpoint as a normal user message

---

## 6. Backend — Turn 1: Trigger Detection

Every incoming message passes through `MessageService.stream_message` (WebSocket,
used by the widget) or `MessageService.process_message` (HTTP).

After the LLM planner runs, **`_adapt_turn_plan_for_inquiry`** is called:

```
_load_inquiry_pending_state(conversation_id)
    ↓ reads most recent assistant message metadata from short-term memory
    ↓ returns {} if no active inquiry (most-recent-first check)
    ↓
_adapt_turn_plan_for_inquiry(turn_plan, message, pending_state)
    ↓
    If pending_state is empty AND message matches INQUIRY_TRIGGER_PATTERN:
        → fresh trigger path (Turn 1)
        → wipe bogus contact fields LLM may have extracted from trigger text
        → extract product_name from trigger message ("Send inquiry for price of X" → "X")
        → inject {"tool_id": "submit_inquiry"} into turn_plan.tool_plan
        → returns modified turn_plan
```

**`INQUIRY_TRIGGER_PATTERN`** matches phrases like:
`send inquiry`, `send an inquiry`, `request a quote`, `get a quote`,
`want a quotation`, `contact sales`, `bulk order`, `want to buy`,
`have your team contact me`, `reach out to me`

---

## 7. Backend — Turns 2+: In-Flight Continuation

Once an inquiry is started, **every subsequent user message** is intercepted:

```
_load_inquiry_pending_state(conversation_id)
    ↓ finds inquiry_pending in most-recent assistant message metadata
    ↓ {resolved_inputs: {product_name, ...}, missing_input: [...], awaiting_confirmation: false}
    ↓
_adapt_turn_plan_for_inquiry(turn_plan, message, pending_state)
    ↓
    pending_state is non-empty (active inquiry):
    │
    ├─ INQUIRY_CANCEL_PATTERN matched ("cancel", "never mind", etc.)
    │     → clear tool_plan, set action=clarify, cancel message, mark _inquiry_cancelled
    │
    ├─ Parse user's message for the fields the tool last asked for:
    │     _parse_inquiry_fields_from_message(message, pending_state["missing_input"])
    │     → email extracted by regex (unambiguous)
    │     → phone extracted by regex (7+ digits required)
    │     → remaining comma-separated parts assigned positionally to remaining fields
    │     → merged into turn_plan.resolved_inputs alongside already-collected fields
    │
    ├─ awaiting_confirmation=true AND INQUIRY_AFFIRM_PATTERN matched?
    │     → set confirm=True in the submit_inquiry step input
    │
    └─ inject/keep submit_inquiry in tool_plan, reset action to "ready"
```

**`INQUIRY_CANCEL_PATTERN`**: `cancel`, `never mind`, `forget it`, `stop this`,
`not now`, `don't send`, `do not send`, `skip this`, `no longer`

**`INQUIRY_AFFIRM_PATTERN`**: `yes`, `yeah`, `yep`, `correct`, `confirmed`,
`go ahead`, `please send`, `send it`, `that's right`, `looks good`, `sounds good`, `okay`

---

## 8. Tool Registration

At agent config load time (`_register_configured_capabilities`):

```python
if inquiry_config.get("enabled"):
    inquiry_tool = InquiryTool(
        brand_slug=self.brand_id,
        brand_id=...,
        agent_id=...,
        conversation_id=None,         # set per-turn by _configure_inquiry_tool_for_turn
        agent_config=config,
        submit_callback=self._submit_inquiry,   # bound to MessageService instance
    )
    self.tool_registry.register(inquiry_tool)
```

Per-turn, `_configure_inquiry_tool_for_turn` sets:
- `tool.conversation_id` = current conversation ID
- `tool.active_product_focus` = product currently being discussed (from session_state)

---

## 9. Tool Execution — `inquiry_tool.py`

`InquiryTool.run(payload, confirm)` is called by `_execute_planner_tool_plan`
with the merged payload (remembered_inputs + parsed fields from this turn).

### Field collection state machine

```
run() called with merged payload
│
├─ ALL_MISSING = [f for f in REQUIRED_FIELDS if value is empty]
│
├─ all_missing non-empty?
│     │
│     ├─ only product_name missing → ask for product_name (auto-fill failed)
│     │
│     ├─ BATCH_1 (name, phone) not yet done?
│     │     → return ToolResult(success=False, missing_input=["name","phone"])
│     │
│     └─ BATCH_1 done, BATCH_2 (email, city, country, query) incomplete?
│           → return ToolResult(success=False, missing_input=[remaining BATCH_2 fields])
│
├─ all fields present → validate email format + phone format
│     → if invalid: return ToolResult(success=False, invalid_fields=[...])
│
├─ confirm_before_send=true AND confirm=false?
│     → return ToolResult(success=True, data="AWAITING_CONFIRMATION",
│                          metadata={awaiting_confirmation:true, summary:{...}})
│
└─ all fields valid + confirmed (or confirm_before_send=false)
      → call submit_callback(merged_fields, agent_config)
      → returns ToolResult(success=True, data=success_message,
                           metadata={inquiry_submitted:true, ...})
```

### Required fields (7 total)

| Field | Batch | Never asked from user? |
|---|---|---|
| `product_name` | Auto | Yes — auto-filled from trigger message / active_product_focus |
| `name` | Batch 1 | No |
| `phone` | Batch 1 | No |
| `email` | Batch 2 | No |
| `city` | Batch 2 | No |
| `country` | Batch 2 | No |
| `query` | Batch 2 | No |

---

## 10. LLM Response Generation

After the tool runs, `_generate_planner_agent_result` synthesises the user-facing
response. The system prompt includes hard rules:

- If `missing_input` list in metadata → **ask for exactly those fields, nothing else**
- If `awaiting_confirmation: true` → **show summary, ask "Shall I send this?"**
- If `inquiry_submitted: true` → **confirm sent, team will follow up**

The claim-evidence guard (`response_validator.py`) is tuned to pass
inquiry-related responses (tool-reported structured state is counted as evidence,
bare list markers / introductory lines / quoted example text are excluded from
factual-claim detection).

---

## 11. Pending State Persistence

After each turn, the inquiry state is saved into the assistant message's
short-term memory metadata so the next turn can resume:

```python
# metadata written to short_term.add_message(..., metadata={...})
"inquiry_pending": {
    "resolved_inputs": {"product_name": "X", "name": "Y", "phone": "Z", ...},
    "missing_input": ["email", "city", "country", "query"],
    "awaiting_confirmation": False
}
```

On the next turn, `_load_inquiry_pending_state` reads the **most recent
assistant message** only. If that message has no `inquiry_pending` (i.e. the
agent replied to something else in between), the inquiry is considered
interrupted and returns `{}` — preventing an old abandoned inquiry from
hijacking unrelated future messages.

Terminal markers:
- `{"submitted": True}` — inquiry was sent; never resume
- `{"cancelled": True}` — user cancelled; never resume

---

## 12. Submission — `_submit_inquiry` in MessageService

```python
async def _submit_inquiry(self, payload: dict, agent_config: dict) -> dict:
    # 1. Persist to MongoDB (brand-isolated DB)
    inquiry_doc = await self.inquiry_service.save_inquiry(
        brand_slug=..., contact={name, phone, email, city, country},
        requirements=payload["query"],
        product_context={name: payload["product_name"], ...}
    )

    # 2. Deliver (SMTP email, non-blocking thread)
    delivery = await self.inquiry_delivery_service.send(inquiry_doc, agent_config)

    # 3. Mark delivered or failed in MongoDB
    if delivery.success:
        await self.inquiry_service.mark_delivered(...)
    else:
        await self.inquiry_service.mark_failed(...)

    return {"success": delivery.success, "inquiry_id": ..., "delivered": delivery.success}
```

---

## 13. Email Delivery — `InquiryDeliveryService`

```
_send_email() runs in asyncio.to_thread (non-blocking, 15s timeout)
│
├─ recipient = agent_config.inquiry.recipient_email
│              OR env var INQUIRY_FALLBACK_RECIPIENT
│
├─ subject = "New Inquiry: {product_name} — {brand_slug}"
│
├─ body (plain text):
│     Product: {name} (SKU: {sku})
│     Name / Phone / Email / City / Country
│     Query: {requirements}
│     Inquiry ID / Conversation ID / Brand
│
└─ sent via smtplib.SMTP → STARTTLS → login → sendmail
```

SMTP settings come from env vars:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=sender@gmail.com
SMTP_PASSWORD=app-password
SMTP_FROM_EMAIL=sender@gmail.com
SMTP_USE_TLS=true
INQUIRY_FALLBACK_RECIPIENT=fallback@brand.com
```

---

## 14. MongoDB Persistence — `InquiryService`

Inquiries are stored in the **brand's own database** (brand-isolated):

```
MongoDB Atlas
└── {brand-slug}/                     ← brand-isolated database
    └── inquiries                     ← collection
        └── {
              inquiry_id: uuid,
              brand_id, brand_slug, agent_id, conversation_id,
              status: "submitted" | "delivered" | "delivery_failed",
              product_context: { name, sku },
              contact: { name, phone, email, city, country },
              requirements: "user's query text",
              delivery: { method, delivered_at, error },
              created_at, updated_at
            }
```

Indexes: `inquiry_id` (unique), `(agent_id, created_at)`, `conversation_id`

---

## 15. Complete Turn-by-Turn Flow (Example)

```
User clicks "Send Inquiry for Price →" on "Denon Home 150 Wireless Speaker" card
    │
    ▼
Widget sends: "Send inquiry for price of Denon Home 150 Wireless Speaker"
    │
    ▼ Turn 1 — Trigger
INQUIRY_TRIGGER_PATTERN matches → fresh trigger
product_name extracted from message text → "Denon Home 150 Wireless Speaker"
submit_inquiry called: BATCH_1 fields missing
    ← Agent: "Please share your Name and Phone number."

    ▼ Turn 2 — Batch 1 collection
User: "Rishabh, 9140000987"
_parse_inquiry_fields_from_message → {name: "Rishabh", phone: "9140000987"}
merged into resolved_inputs with product_name
submit_inquiry called: BATCH_1 done, BATCH_2 fields missing
    ← Agent: "Please share your Email, City, Country, and Query."

    ▼ Turn 3 — Batch 2 collection
User: "rishabh@gmail.com, Delhi, India, want pricing for 10 units"
_parse_inquiry_fields_from_message → {email, city, country, query}
all 7 fields collected → confirm_before_send=true, confirm=false
submit_inquiry returns AWAITING_CONFIRMATION with summary
    ← Agent: "Here are your details — [summary]. Shall I send this?"

    ▼ Turn 4 — Confirmation
User: "yes send it"
INQUIRY_AFFIRM_PATTERN matches → confirm=True injected
submit_inquiry called with confirm=True
    → _submit_inquiry:
          inquiry_service.save_inquiry() → MongoDB
          inquiry_delivery_service.send() → SMTP email (asyncio.to_thread)
          inquiry_service.mark_delivered()
    ← Agent: "Your inquiry has been sent. Our team will reach out shortly!"
```

---

## 16. Failure Handling

| Failure | Behaviour |
|---|---|
| SMTP not configured | Returns DeliveryResult(success=False, error="SMTP not configured") |
| SMTP timeout (>15s) | Caught by asyncio.wait_for, returns timeout error |
| SMTP error (auth/network) | Caught, inquiry still persisted in MongoDB with status=delivery_failed |
| No recipient email | Returns error "No recipient_email configured" |
| User cancels mid-flow | INQUIRY_CANCEL_PATTERN detected → `{cancelled:true}` persisted, never resumes |
| User abandons (changes topic) | Next product-search response has no `inquiry_pending` → `_load_inquiry_pending_state` returns `{}` → flow not resumed |

---

## 17. Cancellation

If the user types any cancel phrase at any point in the flow:

```
User: "cancel" / "never mind" / "forget it" / "don't send" / "stop this"
    │
    ▼
INQUIRY_CANCEL_PATTERN matched in _adapt_turn_plan_for_inquiry
    → turn_plan.tool_plan = []
    → action = "clarify"
    → response_text = "No problem, I've cancelled that inquiry."
    → raw_plan["_inquiry_cancelled"] = True
    → short_term memory stores: inquiry_pending = {cancelled: True}
    → _load_inquiry_pending_state returns {} on every subsequent turn
```

---

## 18. Key Design Decisions

**Why model-agnostic field parsing?**
The LLM planner inconsistently extracts contact fields from the user's reply
depending on the model. `_parse_inquiry_fields_from_message` uses regex + positional
comma-splitting so field collection works reliably regardless of which LLM model
the agent uses.

**Why deterministic tool injection?**
The LLM planner independently decides each turn whether to call `submit_inquiry`.
`_adapt_turn_plan_for_inquiry` overrides that decision deterministically whenever
an inquiry is in flight — the same pattern the codebase uses for Lal Kitab
chart-first flows. This prevents the "silent drop" where the LLM acknowledges
user input without calling the tool.

**Why most-recent-assistant-message check?**
If a user abandoned an inquiry and started a new product search, scanning all
8 recent messages would find the old `inquiry_pending` and hijack the new query.
Only checking the most recent assistant message means the flow is considered
interrupted the moment any non-inquiry response is stored.

**Why brand-isolated MongoDB?**
Inquiries are PII. Storing them in the brand's own DB (not a shared collection)
ensures complete data isolation — no cross-brand leakage, easier GDPR deletion.
