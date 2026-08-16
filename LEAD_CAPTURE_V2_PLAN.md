# Lead Capture V2 — Architecture Plan

Upgrade the current conversational batch-collection flow to:
1. An in-widget structured form (no PII ever touches the LLM)
2. LLM-level intent intelligence (knows when to open the form vs show products)
3. Post-inquiry context reset (knows when the inquiry is done and to resume normal mode)

---

## Problems with V1 (Current)

| Problem | Root cause |
|---|---|
| After inquiry sent, next product query returns "not enough verified info" | `inquiry_pending = {submitted: true}` in last assistant message — `_load_inquiry_pending_state` returns `{}` correctly, but the agent still has no "normal mode" signal — it can end up in a partially-cleared state where the response_validator or planner still sees inquiry context from the prompt history |
| LLM doesn't decide intelligently to open inquiry vs show products | Harness uses `INQUIRY_TRIGGER_PATTERN` (regex) only — no LLM judgment about user intent |
| PII (name, phone, email) flows through the LLM writer | `_parse_inquiry_fields_from_message` → `resolved_inputs` → `evidence` JSON in `_generate_planner_agent_result` prompt |
| Conversational batch collection is fragile across models | Regex heuristic parser works but has edge cases; multiple turns to collect 6 fields is friction |
| No field-level input validation on frontend | Email regex, phone digit check is backend-only — user gets error only after submitting |

---

## What We Already Have (Keep As-Is)

- `InquiryService` — MongoDB persistence (brand-isolated) ✅
- `InquiryDeliveryService` — SMTP email in worker thread ✅
- `_submit_inquiry` in `message_service.py` — save + deliver callback ✅
- `InquiryTool` registered per-agent when `inquiry.enabled=true` ✅
- Admin panel toggle (Lead Capture · Via Email · No CRM) ✅
- `inquiry.enabled` exposed in public agent config ✅
- Product card "Request a Quote →" button → `onSendInquiry` callback ✅
- `INQUIRY_TRIGGER_PATTERN` for regex-based trigger detection ✅

---

## V2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         WIDGET (Frontend)                           │
│                                                                     │
│  ┌──────────────────┐    ┌──────────────────────────────────────┐   │
│  │  Chat messages   │    │         InquiryFormModal             │   │
│  │                  │    │  ┌──────────┐  ┌───────────────────┐│   │
│  │  [product cards] │    │  │  Name *  │  │  Phone * (10 dig) ││   │
│  │  [agent replies] │    │  ├──────────┤  ├───────────────────┤│   │
│  │                  │    │  │  Email * │  │  Country (select) ││   │
│  └──────────────────┘    │  ├──────────┤  ├───────────────────┤│   │
│                           │  │  City *  │  │  Query            ││   │
│  [Request a Quote →]─────►│  └──────────┘  └───────────────────┘│   │
│                           │                                        │   │
│  Agent intent signal ────►│  [Submit]          [Skip]             │   │
│  (openInquiryForm event)  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                    │ Submit (fields only, never via LLM)
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                POST /api/v1/inquiry/submit                          │
│                (new dedicated endpoint — no LLM involved)           │
│                                                                     │
│   inquiry_service.save_inquiry()                                    │
│   inquiry_delivery_service.send()                                   │
│   return {success, inquiry_id}                                      │
└─────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
              Email delivered to brand owner
              Inquiry persisted in brand MongoDB
```

---

## Part 1 — LLM Intent Intelligence

### Problem
After inquiry is submitted, "show me amplifiers" gets the low-confidence error
because the response_validator still sees `inquiry_submitted:true` context from
the previous turn in the evidence chain.

### Fix A — Post-Inquiry Context Reset (Immediate, Small)

In `_load_inquiry_pending_state`, when it finds `{submitted: true}`, also set
a `post_inquiry_reset` flag on the `MessageService` instance so `_adapt_turn_plan_for_inquiry`
knows: **do not inject submit_inquiry, do not filter tool plan, treat next turn as fully normal**.

Additionally, after a submitted inquiry, write a lightweight marker into
short-term memory that the session is back in "product assist" mode.

**File:** `apps/api/app/services/message_service.py`
**Change:** 3 lines in `_load_inquiry_pending_state` + 1 line in `_adapt_turn_plan_for_inquiry`

### Fix B — LLM Intent Signal (New, Medium)

Instead of only using `INQUIRY_TRIGGER_PATTERN` (regex), add a second path where
the LLM planner itself can signal intent `"open_inquiry_form"` as an action type.

The agent's system prompt gains one new rule:

```
When the user expresses any of these intents — wants pricing details, requests a
quotation, wants to talk to a human / customer support, wants to know availability,
says "contact me", "call me", "follow up" — set action="open_inquiry_form" in
your plan. Do NOT try to collect fields yourself. The widget will show the form.

When the user is searching for products, comparing options, or asking general
questions — set action="ready" and answer normally.
```

The planner output `action="open_inquiry_form"` is caught in
`_adapt_turn_plan_for_inquiry` (no LLM text generation needed — just a signal).
The API response includes `metadata.open_inquiry_form = true` and the widget
opens the form directly.

**Files:**
- `apps/api/app/services/agent_turn_planner.py` — add `open_inquiry_form` to valid actions
- `apps/api/app/services/message_service.py` — handle the new action in `_adapt_turn_plan_for_inquiry`, include `open_inquiry_form` flag in streaming metadata
- `apps/widget/src/components/ChatWindow.tsx` — listen for `open_inquiry_form` in message metadata and open the modal

### Intent decision table (what LLM learns)

| User says | LLM action |
|---|---|
| "show me speakers" | `ready` — product search |
| "what is the price of X" | `ready` — RAG retrieval |
| "request a quote for X" | `open_inquiry_form` |
| "I want to buy this" | `open_inquiry_form` |
| "can someone call me" | `open_inquiry_form` |
| "contact sales" | `open_inquiry_form` |
| "I need bulk pricing" | `open_inquiry_form` |
| "after inquiry: show me amplifiers" | `ready` — post-inquiry reset active |

---

## Part 2 — In-Widget Structured Form (No PII to LLM)

### Why a Form Instead of Conversational Collection

| | Current (Conversational) | V2 (Form) |
|---|---|---|
| PII exposure to LLM | Name/phone/email in LLM prompt evidence | Never — form submits directly to API |
| Validation | Backend only, error after submit | Frontend: phone digits-only, email regex, required fields |
| Friction | 4 chat turns (trigger + 2 batches + confirm) | 1 interaction: fill + submit |
| Country input | Free text, parsing errors | Dropdown (ISO 3166-1 country list) |
| User abandonment | User must type cancel | Skip button — closes form, resumes chat |

### New Component: `InquiryFormModal`

**File:** `apps/widget/src/components/InquiryFormModal.tsx` (new)

```tsx
interface InquiryFormModalProps {
  isOpen: boolean
  productName: string          // pre-filled from click context, not editable
  agentId: string
  conversationId: string
  apiUrl: string
  onSuccess: (message: string) => void   // shows success in chat
  onSkip: () => void                     // closes form, no action
}
```

### Form Fields with Validation

| Field | Type | Frontend Validation | Required |
|---|---|---|---|
| Product Name | Text (read-only, pre-filled) | — | Auto |
| Name | Text | Non-empty | Yes |
| Phone | Text | Digits + `+`, `-`, `()`, space only; 7–15 digits; no letters | Yes |
| Email | Email input | Native `type="email"` + regex `/.+@.+\..+/` | Yes |
| City | Text | Non-empty | Yes |
| Country | Select dropdown (ISO country list) | Must select | Yes |
| Query | Textarea | Optional — shows "Submit" if empty, no block | No |

### Buttons

- **Submit** — enabled only when Name, Phone, Email, City, Country are all valid. Disabled + grey otherwise.
- **Skip** — always visible. Closes the modal, appends a soft message to chat: "No problem! Let me know if you need anything else."

### Form Submission (Direct to API — No LLM)

On Submit:

```ts
POST /api/v1/inquiry/submit
Content-Type: application/json

{
  "agent_id": "...",
  "conversation_id": "...",
  "product_name": "Denon Home 150",
  "name": "Rishabh",           // PII never touches LLM
  "phone": "9140000987",
  "email": "r@example.com",
  "city": "Delhi",
  "country": "India",
  "query": "want pricing for 10 units"
}
```

Response: `{ success: true, message: "Your inquiry has been sent..." }`

The widget then:
1. Closes the modal
2. Appends the success message as an assistant chat bubble
3. Continues in normal product-search mode

---

## Part 3 — New API Endpoint

**File:** `apps/api/app/api/v1/endpoints/inquiry.py` (new)

```
POST /api/v1/inquiry/submit
  ├─ Validate required fields (Pydantic schema)
  ├─ Resolve brand_slug from agent_id
  ├─ inquiry_service.save_inquiry(...)
  ├─ inquiry_delivery_service.send(...)
  └─ return {success, inquiry_id, message}
```

No LLM involved. No authentication required (public endpoint, widget session
token validated same as `/api/v1/messages/ws`).

**No change to `InquiryTool`, `InquiryService`, or `InquiryDeliveryService`** —
the endpoint just calls them directly, bypassing the tool layer.

---

## Part 4 — What Changes in the Backend (message_service.py)

### Remove from `_adapt_turn_plan_for_inquiry`
- `_parse_inquiry_fields_from_message` — no longer needed (form collects fields)
- `_BATCH_1` / `_BATCH_2` logic in `inquiry_tool.py` — no longer needed
- `INQUIRY_AFFIRM_PATTERN` — no longer needed (no confirmation turn)
- `_collect_inquiry_pending_state` / `_load_inquiry_pending_state` for field state — replaced by form submit

### Keep
- `INQUIRY_TRIGGER_PATTERN` — regex fallback for typed triggers (not all users click the button)
- `_adapt_turn_plan_for_inquiry` — still handles typed triggers, now sets `open_inquiry_form=True` in metadata instead of calling the tool
- Post-inquiry reset logic — clears state after form submission so next turn is normal

### New: Post-Submit Reset Signal

When `POST /api/v1/inquiry/submit` succeeds, the widget sets a local flag
`inquiryJustCompleted = true`. On the very next WebSocket message, the API
includes `"inquiry_just_completed": true` in the request metadata. The
message_service reads this and:
1. Does NOT call `_adapt_turn_plan_for_inquiry`
2. Clears any `inquiry_pending` from session state
3. Processes the message as a completely normal turn

---

## Part 5 — Files to Create / Modify

### New files
| File | What |
|---|---|
| `apps/widget/src/components/InquiryFormModal.tsx` | The form component |
| `apps/widget/src/components/CountrySelect.tsx` | Reusable ISO country dropdown |
| `apps/widget/src/styles/inquiry-form.css` | Form styles matching widget theme |
| `apps/api/app/api/v1/endpoints/inquiry.py` | `POST /api/v1/inquiry/submit` endpoint |

### Modified files
| File | Change |
|---|---|
| `apps/widget/src/components/ChatWindow.tsx` | Import + control `InquiryFormModal`, pass `productName` on trigger, handle `open_inquiry_form` metadata signal |
| `apps/widget/src/components/MessageBubble.tsx` | Pass `open_inquiry_form` metadata signal up to ChatWindow |
| `apps/widget/src/components/ProductCard.tsx` | "Request a Quote →" now calls `onOpenInquiryForm(productName)` instead of `onSendInquiry(message)` |
| `apps/widget/src/App.tsx` | Wire `showInquiry` to `InquiryFormModal` open/close state |
| `apps/api/app/services/message_service.py` | Add post-inquiry reset, handle `open_inquiry_form` action, remove batch-collection harness |
| `apps/api/app/services/agent_turn_planner.py` | Add `open_inquiry_form` to valid actions list |
| `apps/api/app/api/v1/router.py` | Register new inquiry router |
| `apps/api/app/api/v1/endpoints/__init__.py` | Export inquiry router |

### Unchanged files (keep exactly as-is)
- `packages/tools/src/tools/builtin/inquiry_tool.py`
- `apps/api/app/services/inquiry_service.py`
- `apps/api/app/services/inquiry_delivery_service.py`
- `apps/api/app/config.py` (SMTP settings unchanged)
- Admin panel components (toggle, config form)

---

## Part 6 — Complete V2 Flow (Example)

```
── Scenario A: Button click ──────────────────────────────────────────

User clicks "Request a Quote →" on "Denon Home 150 Wireless Speaker"
    │
    ▼
ProductCard calls onOpenInquiryForm("Denon Home 150 Wireless Speaker")
    │
    ▼
ChatWindow opens InquiryFormModal(productName="Denon Home 150 Wireless Speaker")
    │
    ▼
User fills: Name, Phone, Email, City, Country, Query (optional)
    │
    ├─ Phone validated frontend: digits only, 7-15 digits
    ├─ Email validated frontend: must contain @ and .
    ├─ Country: dropdown selection
    └─ Submit button: enabled only when required fields valid
    │
    ▼
POST /api/v1/inquiry/submit {name, phone, email, city, country, query, product_name, agent_id, conversation_id}
    │  ← PII never sent to LLM
    ▼
inquiry_service.save_inquiry() → MongoDB (brand-isolated)
inquiry_delivery_service.send() → SMTP email (asyncio.to_thread)
    │
    ▼
Widget: closes modal, appends assistant bubble:
    "Your inquiry has been sent. Our team will reach out to you shortly!"
    │
    ▼
Next user message: "show me amplifiers"
    → inquiryJustCompleted flag → post-inquiry reset → normal product search
    → agent shows product cards ✅

── Scenario B: Typed trigger ─────────────────────────────────────────

User types: "I need bulk pricing for 50 units"
    │
    ▼
INQUIRY_TRIGGER_PATTERN matches OR LLM planner sets action="open_inquiry_form"
    │
    ▼
API response includes metadata: {open_inquiry_form: true, product_name: "last_discussed_product"}
    │
    ▼
Widget receives → opens InquiryFormModal
    [same flow as Scenario A from here]

── Scenario C: Skip ──────────────────────────────────────────────────

User opens form → clicks [Skip]
    │
    ▼
Modal closes, no submission
Widget appends: "No problem! Let me know if you need anything else."
Conversation continues normally

── Scenario D: Post-inquiry product search ───────────────────────────

[inquiry just sent successfully]
User: "show me amplifiers"
    │
    ▼
inquiryJustCompleted=true in request metadata
message_service: skip _adapt_turn_plan_for_inquiry entirely
Run normal retrieval pipeline → return product cards ✅
```

---

## Part 7 — PII Architecture (Key Change from V1)

```
V1 (Current):
  User types "Rishabh, 9140000987"
      → _parse_inquiry_fields_from_message extracts name/phone
      → goes into turn_plan.resolved_inputs
      → goes into evidence JSON in _generate_planner_agent_result prompt
      → LLM sees "name: Rishabh, phone: 9140000987" in context  ← PII in LLM

V2 (New):
  User fills form in widget
      → POST /api/v1/inquiry/submit (fields only)
      → inquiry_service.save_inquiry() (MongoDB)
      → inquiry_delivery_service.send() (SMTP)
      → widget shows success message (hardcoded, not LLM-generated)
      → LLM never sees name/phone/email/city/country  ← No PII in LLM
```

The LLM only ever knows: "an inquiry was submitted for Product X". It never
sees the contact details.

---

## Part 8 — Implementation Order

1. **Fix post-inquiry reset** (`message_service.py`, ~10 lines) — fixes the immediate screenshot bug (product search fails after inquiry)
2. **New API endpoint** (`inquiry.py`, ~50 lines) — the direct submit path
3. **`InquiryFormModal` component** (`InquiryFormModal.tsx`, ~200 lines) — the form UI with validation
4. **`CountrySelect` component** (`CountrySelect.tsx`, ~50 lines) — ISO dropdown
5. **Wire form into ChatWindow/ProductCard** — replace `onSendInquiry` with `onOpenInquiryForm`
6. **LLM intent signal** (`agent_turn_planner.py` + `message_service.py`) — `open_inquiry_form` action
7. **Remove V1 batch harness** (`inquiry_tool.py`, `message_service.py`) — clean up batch/regex collection code

Steps 1-2 can be done independently. Steps 3-5 are the main UI work. Steps 6-7 are polish.

---

## Part 9 — What This Solves vs V1

| Issue | V1 | V2 |
|---|---|---|
| Product search fails after inquiry | ❌ Low-confidence fallback | ✅ Post-inquiry reset clears state |
| PII in LLM prompt | ❌ name/phone/email in evidence | ✅ Never — form submits direct to API |
| Field validation | ❌ Backend only | ✅ Frontend: phone regex, email type, country dropdown |
| Collection friction | ❌ 4 conversational turns | ✅ 1 form interaction |
| Country input errors | ❌ Free text | ✅ ISO dropdown |
| Intent intelligence | ❌ Regex only | ✅ Regex + LLM planner `open_inquiry_form` action |
| Skip / abandon | ❌ Must type "cancel" | ✅ Skip button, always visible |
| Multi-model reliability | ❌ Depends on LLM extracting fields | ✅ Form — model-agnostic |
