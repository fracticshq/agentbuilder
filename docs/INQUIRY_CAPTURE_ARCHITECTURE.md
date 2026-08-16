# Inquiry Capture — Full Architecture

## What It Is

Inquiry Capture is a **conversational lead collection feature** built into NOVA agents.
Instead of pointing users to a contact form, the agent collects their details through
natural conversation, confirms the data with them, then emails the inquiry directly to
the brand owner.

Designed for B2B catalogs with no fixed prices (e.g. A&D Instruments, industrial
equipment, made-to-order products) where the buying intent is "contact us for a quote"
rather than "add to cart".

---

## Technologies Used

| Layer | Technology |
|-------|-----------|
| Admin UI | React 19, TypeScript, Tailwind CSS |
| Agent Config persistence | MongoDB Atlas (`agent-builder.agents` collection) |
| Runtime trigger | Python FastAPI → LLM orchestrator |
| Email delivery | Python `smtplib` (SMTP, async-safe via `asyncio.to_thread`) |
| PII safety | structlog — contact fields never logged, only `inquiry_id` |
| State management | Admin: Zustand + React Query |

---

## Files Involved

```
agentbuilder/
│
├── apps/admin/src/
│   ├── components/AgentStudio/
│   │   ├── AgentConfigForm.tsx          ← UI: Inquiry Capture toggle + fields
│   │   └── types.ts                     ← TypeScript types for inquiry fields
│   ├── utils/
│   │   └── agentWizardPayload.ts        ← Serializes inquiry config → agent doc
│   └── hooks/
│       └── useAgentWizardController.ts  ← Default state for inquiry fields
│
└── apps/api/app/
    └── services/
        └── inquiry_delivery_service.py  ← Email delivery engine
```

---

## Data Flow — Step by Step

```
┌─────────────────────────────────────────────────────────────────┐
│  ADMIN PANEL (Agent Config)                                     │
│                                                                 │
│  1. Admin toggles ON "Enable conversational inquiry capture"    │
│  2. Sets recipient_email = "owner@brand.com"                    │
│  3. Optionally sets confirm_before_send = true                  │
│  4. Sets success_message = "We'll get back to you shortly"      │
│  5. Saves agent → stored in MongoDB agents collection as:       │
│                                                                 │
│     configuration.inquiry = {                                   │
│       enabled: true,                                            │
│       recipient_email: "owner@brand.com",                       │
│       confirm_before_send: true,                                │
│       success_message: "...",                                   │
│       delivery_method: "email"                                  │
│     }                                                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  WIDGET (User conversation)                                     │
│                                                                 │
│  6. User says: "I want to buy a GF-3000 balance"                │
│     or "Can I get a quote?" or "How much does it cost?"         │
│                                                                 │
│  7. LLM orchestrator detects purchase/quote intent              │
│     (keywords: quote / pricing / buy / contact sales)           │
│                                                                 │
│  8. Agent calls submit_inquiry tool conversationally,           │
│     collecting these fields one by one:                         │
│       - Product Name                                            │
│       - Name                                                    │
│       - Phone                                                   │
│       - Email                                                   │
│       - City                                                    │
│       - Country                                                 │
│       - Query / Requirements                                    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  CONFIRMATION STEP (if confirm_before_send = true)              │
│                                                                 │
│  9. Agent shows a summary:                                      │
│     "Here's what I have:                                        │
│      Product: GF-3000 Precision Balance                         │
│      Name: Rahul Sharma                                         │
│      Phone: +91 98765 43210                                     │
│      Email: rahul@lab.com                                       │
│      City: Mumbai                                               │
│      Country: India                                             │
│      Query: Need pricing for 3 units                            │
│      Shall I submit this?"                                      │
│                                                                 │
│  10. User says "Yes" → proceeds to delivery                     │
│      User says "No" / edits → agent re-collects                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  inquiry_delivery_service.py                                    │
│                                                                 │
│  11. InquiryDeliveryService.send() called with:                 │
│      {                                                          │
│        inquiry_id: "uuid",                                      │
│        conversation_id: "conv_xxx",                             │
│        brand_slug: "aand-instruments",                          │
│        contact: {                                               │
│          name, phone, email, city, country                      │
│        },                                                       │
│        product_context: { name, sku },                          │
│        requirements: "Need pricing for 3 units"                 │
│      }                                                          │
│                                                                 │
│  12. _resolve_recipient() → picks recipient_email from          │
│      agent config OR falls back to INQUIRY_FALLBACK_RECIPIENT   │
│                                                                 │
│  13. Validates SMTP config is present                           │
│      (SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD)                  │
│                                                                 │
│  14. Builds email:                                              │
│      Subject: "New Inquiry: GF-3000 — aand-instruments"        │
│      Body: formatted plain text (see below)                     │
│                                                                 │
│  15. asyncio.to_thread() → runs smtplib in worker thread        │
│      (prevents blocking the asyncio event loop)                 │
│      15s hard timeout enforced                                  │
│                                                                 │
│  16. smtplib.SMTP connects → optional STARTTLS → login          │
│      → sendmail → DeliveryResult(success=True)                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  AGENT RESPONSE                                                 │
│                                                                 │
│  17. On success → agent shows success_message to user           │
│  18. On failure (SMTP error, timeout, no recipient) →           │
│      agent apologizes and suggests contacting directly          │
│  19. PII RULE: inquiry_id + brand_slug logged only,             │
│      name/phone/email NEVER appear in logs                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Email Format Sent to Brand Owner

```
New inquiry received via the AI assistant.

Product: GF-3000 Precision Balance (SKU: GF-3000)

Contact details:
  Name:    Rahul Sharma
  Phone:   +91 98765 43210
  Email:   rahul@lab.com
  City:    Mumbai
  Country: India

Query:
  Need pricing and availability for 3 units for QC lab

Inquiry ID: 550e8400-e29b-41d4-a716-446655440000
Conversation ID: conv_abc123
Brand: aand-instruments
```

---

## Lead Capture Skill vs Inquiry Capture — Difference

| | Inquiry Capture | Lead Capture Skill |
|--|--|--|
| Where configured | Agent Config → Inquiry Capture section | Agent Features → Skills tab |
| File | `AgentConfigForm.tsx` + `inquiry_delivery_service.py` | `skill_registry.py` (`id: lead_capture`) |
| What it does | Full conversational flow + email delivery | Collects name/phone, passes to orchestrator as tool result — **no email delivery built in** |
| Output | Sends email to recipient immediately | Returns structured data to the LLM for it to use/log |
| Intent trigger | Quote / pricing / buy / contact sales | Broader lead intent |
| Config options | Recipient email, confirm step, success message | `required_fields`, `consent_required` |
| Status | Fully implemented | Skeleton — `BuiltInSkillTool.run()` returns the data but has no downstream action wired yet |

**Recommendation:** Use Inquiry Capture for A&D Instruments / B2B quote use cases.
Deselect the Lead Capture skill to avoid duplication.

---

## Environment Variables Required

Add these to `.env.docker` to make email delivery work:

```env
# SMTP for inquiry emails
SMTP_HOST=smtp.gmail.com          # or your provider
SMTP_PORT=587
SMTP_USERNAME=youremail@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=noreply@yourbrand.com
SMTP_USE_TLS=true

# Fallback if agent has no recipient_email set
INQUIRY_FALLBACK_RECIPIENT=admin@yourbrand.com
```

---

## How to Enable (Step by Step)

1. Add SMTP env vars above to `.env.docker`
2. Restart API: `docker compose up -d api`
3. NOVA Admin → Agent → Config tab → scroll to **Inquiry Capture** section
4. Toggle ON "Enable conversational inquiry capture"
5. Enter recipient email (e.g. `sales@aand-instruments.in`)
6. Keep "Confirm before sending" ON (recommended)
7. Set success message (e.g. "Your inquiry has been sent. Our team will contact you within 24 hours.")
8. Save the agent
9. Go to Agent Features → Skills → **deselect Lead Capture** to avoid duplication
10. Test in widget: say "I want a quote for your moisture analyzer"

---

## What Happens if SMTP is Not Configured

The `_send_email` method returns `DeliveryResult(success=False, error="SMTP is not configured")`
and logs a warning. The agent will tell the user the inquiry could not be submitted and
suggest contacting the brand directly. No crash, no data loss — the conversation continues.
