# Skills — LLM Skill/Tool Registry Spec

This file documents the skill/tool-based capabilities the LLM planner can call.
**It is a human-readable design spec only — nothing at runtime reads this
file.** The actual runtime source of truth is code:

- `apps/api/app/services/skill_registry.py` (`BuiltInSkillRegistry`) — generic,
  config-driven skills (knowledge_qa, product_recommendation, lead_capture, etc.)
- `packages/tools/src/tools/builtin/*.py` — dedicated `BaseTool` subclasses with
  real behavior (retrieval, inquiry form, catalog search)
- `apps/api/app/services/message_service.py::_register_configured_capabilities`
  — decides which tools/skills get registered per agent, per turn
- `packages/tools/src/tools/registry.py` (`ToolRegistry`) — holds the tools
  actually registered for the current agent and exposes their JSON schemas to
  the LLM planner via `get_tool_schemas()`

Whenever a skill/tool is added or changed, update this file to match — it is
the reviewable spec, the code is the executable contract.

---

## Skill: Open Inquiry Form (`open_inquiry_form`)

**Category:** conversion / lead capture
**Registered as:** a dedicated `BaseTool` (`OpenInquiryFormTool`), not a
generic `BuiltInSkillTool` — it has real trigger behavior, not just an echo.
**File:** `packages/tools/src/tools/builtin/open_inquiry_form_tool.py`

### Gating (hard requirement)

This tool is registered **only** when the agent's configuration has:
```json
{ "inquiry": { "enabled": true } }
```
See `_register_configured_capabilities` in `message_service.py`. If
`inquiry.enabled` is `false` or missing:
- The tool is never added to `self.tool_registry` for that agent.
- The LLM planner never sees it in its tool list (`_tool_schemas_for_planner`)
  and has no way to call it.
- The regex fallback (`INQUIRY_TRIGGER_PATTERN` in `_adapt_turn_plan_for_inquiry`)
  is also skipped — it explicitly checks `self.tool_registry.get("open_inquiry_form")`
  and returns immediately if the tool isn't registered.

Net effect: with `inquiry.enabled=false`, the entire inquiry feature is
completely inert for that agent — no tool call path, no regex fallback, no
form ever opens, regardless of what the user types.

### What the tool does and does not do

- **Does:** signals intent only. Returns `{open_inquiry_form: true, product_name, product_sku, reason}`
  in its `ToolResult.metadata`. This is used to short-circuit the response
  (`_open_inquiry_form_short_circuit` in `message_service.py`) straight to a
  one-line acknowledgement, and to set `metadata.open_inquiry_form=true` /
  `metadata.product_name` on the API response so the widget renders the
  inline `InquiryFormModal`.
- **Does not:** collect or see any PII (name, phone, email, city, country).
  Those fields are entered by the user directly in the widget form and sent
  to a separate, dedicated endpoint (`POST /api/v1/inquiry/submit`) that never
  goes through the LLM. This tool call and the PII submission are two fully
  separate code paths — PII never enters an LLM prompt.
- **Does not:** persist anything to the database itself. Persistence
  (`InquiryService.save_inquiry`) and delivery (`InquiryDeliveryService`) are
  triggered only by the form submission endpoint, not by this tool.

### When the LLM should call it (intent detection)

The full instruction lives in the tool's own `description` field (read by the
LLM at call time via `get_tool_schemas()`), summarized here:

**Call `open_inquiry_form` when the user's message means:**
- "request a quote", "send inquiry", "send an inquiry for this"
- "I want to buy this", "I want to purchase", "place an order"
- "can someone call me", "contact me", "contact sales", "talk to a human",
  "talk to support", "connect me with your team", "speak to an agent"
- "I need bulk pricing", "what's the pricing for 50 units", "wholesale
  pricing", "price breakdown", "custom quote"
- The message is the product-card button click text: "Request a quote for
  `<product>`"

**Do NOT call it when the user is:**
- Asking what a product is, its price, specs, availability, or comparing
  products — these must go through `knowledge_search` / `search_catalog` /
  `search_shop_catalog` (RAG retrieval / MCP commerce tools) as normal.
  **Product search and Q&A must always work through those tools regardless
  of whether the inquiry skill exists** — `open_inquiry_form` is a separate,
  additive capability, never a gate in front of retrieval.
- Making general conversation, greeting, or asking an unrelated question.
- Already in the middle of the inline form flow (the widget owns that UI
  state — the tool is not called again for the same request).
- Trying to cancel/skip ("never mind", "cancel that", "skip this") — handled
  as a normal reply, `INQUIRY_CANCEL_PATTERN` catches this deterministically
  in `_adapt_turn_plan_for_inquiry` as a safety net.

### Arguments (all optional)

| Field | Type | Purpose |
|---|---|---|
| `product_name` | string | Product being discussed, if any. Pre-labels the form. |
| `product_sku` | string | SKU/product code, if known. |
| `reason` | string | Internal note only (e.g. `quote_request`, `bulk_pricing`). Never shown to the user. |

### Output contract

```json
{
  "success": true,
  "data": {"open_inquiry_form": true, "product_name": "...", "product_sku": "...", "reason": "..."},
  "metadata": {"tool_id": "open_inquiry_form", "open_inquiry_form": true, "product_name": "...", "product_sku": "...", "reason": "..."}
}
```

`message_service.py` reads `metadata.open_inquiry_form` to short-circuit and
to populate the widget-facing response `metadata.open_inquiry_form` /
`metadata.product_name` (both the sync `MessageResponse` and the streaming
`StreamingMessageResponse` `metadata`/`final_answer` events).

### Interaction with other tools / retrieval / MCP

- This tool is **additive**, not a gate. `knowledge_search`, `search_catalog`,
  `search_shop_catalog`, and any MCP/context-connector tools remain fully
  registered and callable in the exact same turn regardless of whether
  `open_inquiry_form` is also registered. The planner picks whichever tool(s)
  fit the message; a product-question turn should never touch
  `open_inquiry_form`, and an inquiry-intent turn should never touch
  retrieval/MCP tools instead of this one.
- If the LLM calls `open_inquiry_form` alongside other tools in the same
  `tool_plan`, `_generate_planner_agent_result` still short-circuits on it
  (see `_open_inquiry_form_short_circuit`) — opening the form always wins the
  final response for that turn once it fires, since sending the form is a
  terminal UI action for the turn.
- A typed trigger the LLM misses (rare, but possible on some providers) is
  still caught by the `INQUIRY_TRIGGER_PATTERN` regex fallback in
  `_adapt_turn_plan_for_inquiry` — but only when the tool is registered
  (`inquiry.enabled=true`), keeping the "off means fully inert" guarantee.

### Removed: legacy prompt-based intent field

Previously the LLM planner (`agent_turn_planner.py`) had a hardcoded
`intent="open_inquiry_form"` enum value with a bespoke paragraph of trigger
phrases baked into the prompt, and `_coerce_plan` mapped it directly to
`action="open_inquiry_form"` without any tool call. This has been **removed**:
- `VALID_INTENTS` no longer includes `"open_inquiry_form"`.
- The bespoke trigger-phrase paragraph is removed from the prompt.
- The LLM now expresses this intent the same way as every other capability:
  `intent="tool_use"` with `open_inquiry_form` in `tool_plan`, using the tool's
  own `description` (this file mirrors it) to decide when it applies.

This makes the mechanism generic — any future skill (dealer_locator,
human_handoff, etc.) can follow the same pattern: a real `BaseTool` with a
detailed `description`, registered conditionally, with no special-cased
`intent` string or prompt paragraph required.

---

## Adding a new skill/tool (checklist)

1. Decide: generic config-driven skill (`skill_registry.py::BUILT_IN_SKILLS`)
   or dedicated behavior (`packages/tools/src/tools/builtin/<name>_tool.py`
   subclassing `BaseTool`). Prefer dedicated behavior if the tool needs to do
   something specific (not just echo back its input).
2. Write a `description` detailed enough that the LLM can decide when to call
   it vs. not, including explicit negative examples (when NOT to call it) and
   its relationship to other tools (does it gate them, or is it additive?).
3. Register it in `_register_configured_capabilities` (`message_service.py`),
   gated on the relevant agent config flag if it should be opt-in.
4. If the tool result needs special handling (short-circuit, metadata
   propagation to the widget, etc.), add that in `_generate_planner_agent_result`
   or wherever `tool_results` are consumed — do not add a new hardcoded
   `intent` value to `agent_turn_planner.py` unless there is no way to express
   the behavior as a tool call.
5. Document the skill in this file (gating, when-to-call, when-not-to-call,
   arguments, output contract, interaction with other tools).
