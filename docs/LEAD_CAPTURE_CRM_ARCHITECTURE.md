# Lead Capture & CRM Integration — Architecture Status

## Quick Answer

**Yes, there is CRM backend data.** `tool_registry.py` has full schema definitions for
HubSpot, Salesforce, Zendesk, Slack, Google Sheets, Airtable, Notion, Zapier and n8n.

**No, you cannot select or connect them yet from the admin UI.** Every one of these is
marked `publicly_available: False` and placed in `RETIRED_PROVIDER_TOOL_IDS` — they are
intentionally hidden from the admin panel and the runtime until a live executor is built
for each one. Their schemas exist only to safely handle/mask any previously-saved credentials.

**No webhook/CRM delivery path exists yet in the inquiry flow.** The
`InquiryDeliveryService` only implements email (SMTP). The comment "pluggable to CRM/webhook
later" appears in the code but the actual `delivery_method: "webhook"` branch raises
`"not implemented yet"`.

---

## What Exists Today — Completed

### 1. Tool Registry Schema (`apps/api/app/services/tool_registry.py`)

Full credential schemas are defined for all these providers:

| Provider | ID | Auth Type | Secret Fields | Status |
|----------|----|-----------|---------------|--------|
| Shopify | `shopify` | api_token | access_token, admin_access_token, customer_access_token | ✅ Live |
| HTTP Webhook | `http_webhook` | header_secret | secret, authorization_header | ✅ Live |
| HubSpot | `hubspot` | private_app_token | access_token | ❌ Retired/hidden |
| Salesforce | `salesforce` | api_credentials | client_secret, refresh_token, access_token | ❌ Retired/hidden |
| Zendesk | `zendesk` | api_token | api_token | ❌ Retired/hidden |
| Slack | `slack` | bot_token | bot_token, signing_secret | ❌ Retired/hidden |
| Google Sheets | `google_sheets` | service_account | service_account_json | ❌ Retired/hidden |
| Airtable | `airtable` | personal_access_token | personal_access_token | ❌ Retired/hidden |
| Notion | `notion` | integration_token | integration_token | ❌ Retired/hidden |
| Zapier Webhook | `zapier_webhook` | webhook_url | webhook_url, secret | ❌ Retired/hidden |
| n8n Webhook | `n8n_webhook` | webhook_url | webhook_url, secret | ❌ Retired/hidden |

The schemas handle credential encryption/masking. That's all they do right now.

### 2. Inquiry Delivery Service (`apps/api/app/services/inquiry_delivery_service.py`)

```
InquiryDeliveryService.send()
    ├── delivery_method = "email"  → ✅ FULLY IMPLEMENTED
    │       └── SMTP via asyncio.to_thread (non-blocking)
    │           - Reads SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD from env
    │           - 15s timeout enforced
    │           - PII-safe logging (inquiry_id only, no name/phone/email in logs)
    │
    └── delivery_method = anything else → ❌ Returns "not implemented yet"
```

### 3. Inquiry Config Shape (agent document, MongoDB)

```json
"inquiry": {
  "enabled": true,
  "recipient_email": "owner@brand.com",
  "delivery_method": "email",
  "webhook_url": null,
  "confirm_before_send": true,
  "success_message": "..."
}
```

`webhook_url` is in the data model but never used. The field exists as a placeholder.

### 4. Agent Config UI (`apps/admin/src/components/AgentStudio/AgentConfigForm.tsx`)

What is rendered:
- ✅ Enable/disable toggle
- ✅ Recipient email field
- ✅ Confirm before sending toggle
- ✅ Success message field
- ❌ No delivery method selector (email only, no dropdown)
- ❌ No webhook URL field
- ❌ No CRM selector
- ❌ No CRM credential fields

### 5. Lead Capture Skill (`apps/api/app/services/skill_registry.py`)

```python
{
    "id": "lead_capture",
    "name": "Lead Capture",
    "description": "Collect contact details and intent for handoff or CRM sync.",
    "category": "conversion",
    "enabled_by_default": False,
    "config_schema": {
        "required_fields": {
            "type": "array",
            "default": ["name", "phone"]
        },
        "consent_required": {"type": "boolean", "default": True}
    }
}
```

`BuiltInSkillTool.run()` — the actual execution — just returns the collected data
back to the LLM. There is no delivery, no CRM call, no email, no storage. It is a
stub that signals the LLM to collect leads, but does nothing with them afterward.

### 6. Settings (`apps/api/app/config.py`)

SMTP vars are fully defined and wired:
```python
SMTP_HOST: str = ""
SMTP_PORT: int = 587
SMTP_USERNAME: str = ""
SMTP_PASSWORD: str = ""
SMTP_FROM_EMAIL: str = ""
SMTP_USE_TLS: bool = True
INQUIRY_FALLBACK_RECIPIENT: str = ""
```

No CRM API key fields exist yet (no `HUBSPOT_ACCESS_TOKEN`, `SALESFORCE_CLIENT_ID`, etc.)

---

## What Is Missing — Not Yet Built

### For Webhook Delivery (next simplest step)

| # | What to build | File |
|---|---------------|------|
| 1 | `delivery_method: "webhook"` branch in `InquiryDeliveryService.send()` | `inquiry_delivery_service.py` |
| 2 | POST inquiry JSON to `webhook_url` using existing `_is_safe_external_url` SSRF guards | `inquiry_delivery_service.py` |
| 3 | Webhook URL field in Admin UI Inquiry Capture section | `AgentConfigForm.tsx` |
| 4 | Delivery method dropdown (email / webhook) in Admin UI | `AgentConfigForm.tsx` |
| 5 | Save `webhook_url` and `delivery_method` in `agentWizardPayload.ts` | `agentWizardPayload.ts` |

### For CRM Integration (HubSpot as example — same pattern for others)

| # | What to build | File |
|---|---------------|------|
| 1 | Remove `hubspot` from `RETIRED_PROVIDER_TOOL_IDS` | `tool_registry.py` |
| 2 | Build `HubSpotCrmTool(BaseTool)` — creates a contact + deal via HubSpot API v3 | New: `tools/builtin/hubspot_tool.py` |
| 3 | Add `delivery_method: "hubspot"` branch in `InquiryDeliveryService.send()` | `inquiry_delivery_service.py` |
| 4 | Add `HUBSPOT_ACCESS_TOKEN` to `Settings` in `config.py` | `config.py` |
| 5 | Add `HUBSPOT_ACCESS_TOKEN` to `.env.docker` | `.env.docker` |
| 6 | CRM selector dropdown in Admin UI Inquiry Capture section | `AgentConfigForm.tsx` |
| 7 | Per-CRM credential fields that appear when a CRM is selected | `AgentConfigForm.tsx` |
| 8 | Encrypt CRM credentials on save (same pattern as Shopify access token in `catalog.py`) | `agentWizardPayload.ts` |
| 9 | TypeScript types for new inquiry config fields | `types.ts` |

Repeat steps 2–5 for Salesforce, Zendesk, Google Sheets, Zapier, etc.

### For the Lead Capture Skill (make it actually do something)

| # | What to build | File |
|---|---------------|------|
| 1 | Connect `BuiltInSkillTool` for `lead_capture` to `InquiryDeliveryService` | `skill_registry.py` |
| 2 | Store captured lead in brand DB `leads` collection | New: `lead_service.py` |
| 3 | Wire delivery (email/webhook/CRM) same as Inquiry Capture | `skill_registry.py` |

### For the `submit_inquiry` Tool (not yet created at all)

Per `INQUIRY_MODE_PLAN.md` this tool needs to be built:

| # | What to build | File |
|---|---------------|------|
| 1 | `InquiryTool(BaseTool)` with slot-filling + confirm flow | New: `tools/builtin/inquiry_tool.py` |
| 2 | Register per-agent in `ToolRegistryService` | `tool_registry.py` |
| 3 | Wire into `message_service.py` per-turn tool registration | `message_service.py` |
| 4 | Persist inquiry to brand DB `inquiries` collection | New: `inquiry_service.py` |

### For the Admin UI (full CRM config panel)

| # | What to build | File |
|---|---------------|------|
| 1 | Delivery method dropdown: Email / Webhook / HubSpot / Salesforce / Google Sheets / Zapier | `AgentConfigForm.tsx` |
| 2 | Conditional fields that appear per delivery method selection | `AgentConfigForm.tsx` |
| 3 | Test delivery button (sends a dummy inquiry to verify config) | `AgentConfigForm.tsx` |
| 4 | Inquiries viewer page in admin (list all captured inquiries per brand) | New page |

---

## Architecture Completion Score

```
Feature                          Status        Completion
─────────────────────────────────────────────────────────
Inquiry UI toggle + fields       ✅ Done        100%
SMTP email delivery              ✅ Done        100%
CRM provider schemas defined     ✅ Done        100%
Inquiry data model (MongoDB)     ✅ Planned      60%  (schema in plan, no collection yet)
submit_inquiry tool              ❌ Not built     0%
Webhook delivery                 ❌ Not built     0%
HubSpot live integration         ❌ Not built     0%
Salesforce live integration      ❌ Not built     0%
Google Sheets live integration   ❌ Not built     0%
Zapier/n8n live integration      ❌ Not built     0%
Admin CRM selector UI            ❌ Not built     0%
CRM credential management UI     ❌ Not built     0%
Inquiries viewer page            ❌ Not built     0%
Lead Capture skill execution     ❌ Stub only    10%
```

---

## Recommended Build Order

### Phase 1 — Get working right now (email)
1. Add SMTP vars to `.env.docker`
2. Toggle on Inquiry Capture in agent config, set recipient email
3. Test conversational inquiry via widget → email arrives in inbox

### Phase 2 — Webhook (1-2 days of work)
1. Add webhook delivery branch to `InquiryDeliveryService`
2. Add webhook URL + delivery method fields to admin UI
3. Test with https://webhook.site (free, zero config)
4. Point at Zapier/n8n webhook for CRM-less lead routing

### Phase 3 — Native CRM (1 week per CRM)
1. Build `HubSpotCrmTool` — creates contact + deal via HubSpot API v3
2. Add `HUBSPOT_ACCESS_TOKEN` to settings + env
3. Add delivery_method: "hubspot" to `InquiryDeliveryService`
4. Add CRM selector + credentials UI in admin
5. Repeat for Salesforce, Google Sheets as needed

### Phase 4 — Full lead pipeline
1. Build `InquiryTool` (submit_inquiry)
2. Build `inquiry_service` (persist to MongoDB)
3. Build inquiries viewer page in admin
4. Connect Lead Capture skill to delivery service
