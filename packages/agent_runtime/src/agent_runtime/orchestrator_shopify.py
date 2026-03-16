"""
Shopify Specialized Orchestrator - SOTA 2026 Plan-and-Execute Runtime.
"""

import json
import structlog
from typing import Dict, Any, List, Optional
from .orchestrator import Orchestrator, AgentResult

logger = structlog.get_logger(__name__)

class ShopifyOrchestrator(Orchestrator):
    """
    Specialized Orchestrator for Shopify.
    Handles Shopify-specific data structures and authentication requirements.
    """
    
    def __init__(
        self, 
        llm: Any, 
        tools: Any, 
        critic: Optional[Any] = None, 
        system_prompt: Optional[str] = None
    ):
        super().__init__(llm, tools, critic, system_prompt)
        
        # Add Shopify-specific instructions to the system prompt if not present
        shopify_instructions = """
### Shopify Agent Instructions

**STOREFRONT TOOLS:**
1. `search_shop_catalog(query, context)` — Find products. REQUIRED: both `query` AND `context` (brief description of user intent).
2. `search_shop_policies_and_faqs(query, [context])` — Answer FAQs, return policies, store info.
3. `get_cart(cart_id)` — Retrieve current cart. Use the `cart_id` from a previous `update_cart` response.
4. `update_cart([cart_id], add_items)` — Add/update items in cart. `add_items` must be an array of objects with `product_variant_id` and `quantity`.
   - If no `cart_id`, a new cart is created. Extract the new `cart_id` from the result and carry it in future turns.
   - If `quantity` is not specified by the user, ALWAYS default it to 1.

**CART SESSION RULES:**
- After calling `update_cart`, extract the `cart_id` from the response and note it in your reasoning.
- On subsequent cart calls (update or get), ALWAYS pass the same `cart_id` so items accumulate.
- When the user says "add these", "add it", or similar, look at the conversation history for the previously discussed product's `variant_id`. NEVER guess or re-search unless the context is missing.

**PRODUCT IDENTITY:**
- When you search for products and find results, note the `product_variant_id` for each item.
- For `update_cart`, always use the exact `product_variant_id` from the search result, NOT the `product_id`.


**GENERAL:**
- Do NOT show generic answers if tool results are available. Use the tool results only.
- Only ask for confirmation before adding to cart if multiple products were found AND the user has NOT yet indicated which one they want. If the user has already said "yes", "the first one", "that one", or any clear affirmation in the current message or recent history, proceed directly to update_cart — do NOT re-search or re-confirm.
- When the user specifies a variant attribute (color, size, etc.) like "white cricket socks" or "size L shirt", 
  the plan MUST include BOTH the search step AND the update_cart step together. 
  Never plan only the search step and stop — that causes a hallucinated response. 
  Ambiguity only exists when NO variant is specified and multiple distinct variants are found.
"""
        if "Shopify Agent Instructions" not in self.system_prompt:
            self.system_prompt += "\n" + shopify_instructions

    async def run(
        self, 
        query: str, 
        chat_history: Optional[List[Dict[str, Any]]] = None, 
        context: Optional[Dict] = None,
        on_status: Optional[Any] = None
    ) -> AgentResult:
        """
        Specialized Shopify Run loop with multi-step variable resolution.
        """
        logger.info("shopify_orchestrator_start", query=query)
        scratchpad = []
        
        if on_status:
            await on_status("Planning actions...")

        # 1. PLANNING PHASE
        tool_schemas = json.dumps(self.tools.get_tool_schemas(), indent=2)
        history_text = "None"
        if chat_history:
            formatted_msgs = [f"{m.get('role', 'u')}: {m.get('content', '')}" for m in chat_history[-6:]]
            if formatted_msgs: history_text = "\n".join(formatted_msgs)

        # Inject session state (like cart_id) into the planner
        session_info = json.dumps(context.get("session_state", {}) if context else {}, indent=2)

        planning_prompt = f"""{self.system_prompt}

### Planning Phase
You are now acting as the Planning Agent. Break down the user's request into a step-by-step plan.

**SESSION STATE:**
{session_info}
(If a `cart_id` is present above, ALWAYS use it for cart-related tools.)

**CHAINING RULES:**
1. **MANDATORY CHAINING**: If the user specifies a variant (e.g., "white socks", "size L"), you MUST plan BOTH `search_shop_catalog` and `update_cart` in a single response. Never stop after search.
2. **RESOLVE FIRST**: If `last_search_results` is in SESSION STATE and the user is confirming (e.g., "yes", "add it"), you MUST use the variant from session state directly and plan ONLY 1 step: `update_cart`.
3. If the user wants to REMOVE an item, you MUST first call `get_cart` to find the correct line item ID (`line.id`) and then call `update_cart` with `remove_line_ids`.
4. Use the `{{{{step_N.attribute}}}}` syntax to pass data between steps.
   - Variant ID path: `{{{{step_1.products[0].variants[0].variant_id}}}}`
   - Cart ID path: `{{{{step_1.cart.id}}}}`
5. If a `cart_id` is provided in the **SESSION STATE** below, you MUST pass it to `update_cart` or `get_cart` to maintain the user's session.
6. **STRICT PARAMETERS**: ALWAYS check the 'Available Tools' list below for correct parameters. For `update_cart`, use `add_items` (list of objects) or `remove_line_ids` (list of strings).

**WHEN TO USE TOOLS:**
- get_cart → trigger on when user want to get cart information or if user wants to remove any item from cart.
  ALWAYS use cart_id from SESSION STATE. Never search catalog for cart queries.

**EXAMPLES:**
Query: "add white cricket socks to cart" (New Cart)
1. tool_name: search_shop_catalog, tool_input: {{"query": "cricket socks", "context": "user wants white variant"}}
2. tool_name: update_cart, tool_input: {{"add_items": [{{"product_variant_id": "{{{{step_1.products[0].variants[0].variant_id}}}}", "quantity": 1}}]}}

Query: "add black cricket socks to cart" (Existing Cart: gid://shopify/Cart/ABC)
1. tool_name: search_shop_catalog, tool_input: {{"query": "cricket socks", "context": "user wants black variant"}}
2. tool_name: update_cart, tool_input: {{"cart_id": "gid://shopify/Cart/ABC", "add_items": [{{"product_variant_id": "{{{{step_1.products[0].variants[0].variant_id}}}}", "quantity": 1}}]}}

Query: "add cricket socks to cart" (Ambiguous - Multiple variants exist)
→ Search first, then ASK which variant before planning update_cart.
1. tool_name: search_shop_catalog, tool_input: {{"query": "cricket socks", "context": "need to confirm variant"}}

Query: "remove cricket socks from my cart"
1. tool_name: get_cart, tool_input: {{"cart_id": "gid://shopify/Cart/123"}}
2. tool_name: update_cart, tool_input: {{"cart_id": "gid://shopify/Cart/123", "remove_line_ids": ["{{{{step_1.cart.lines[0].id}}}}"]}}

Query: "view cart" (Existing Cart: gid://shopify/Cart/ABC)
1. tool_name: get_cart, tool_input: {{"cart_id": "gid://shopify/Cart/ABC"}}

Query: "view cart" (No Cart in Session)
→ Return steps: [] and reply "You don't have an active cart yet."

Query: "yes" / "add the first one" (with last_search_results in SESSION STATE)
→ Use concrete variant ID from history. DO NOT call search again.
1. tool_name: update_cart, tool_input: {{"cart_id": "gid://shopify/Cart/ABC", "add_items": [{{"product_variant_id": "gid://shopify/ProductVariant/12345", "quantity": 1}}]}}

**STRICT RULES:**
- NEVER use placeholders like "<angle brackets>" or "PLACEHOLDER" in tool_input.
- Dynamic values must use `{{{{step_N.path}}}}` or the literal ID from SESSION STATE.
- If last_search_results exists and user affirms, exactly 1 step (update_cart) is required.
- Do NOT plan a search step if the variant ID is already known from history or session.

Conversation History:
{history_text}

User Request: {query}

Available Tools:
{tool_schemas}

Output JSON Format:
{{
  "goal": "Description",
  "steps": [
    {{ "id": 1, "thought": "Reasoning", "tool_name": "...", "tool_input": {{ ... }} }}
  ]
}}"""
        
        try:
            plan_response = await self.llm.generate(planning_prompt)
            content = plan_response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]
            
            logger.debug("shopify_plan_raw", content=content)
            
            try:
                plan_data = json.loads(content)
            except json.JSONDecodeError as je:
                # Robust fallback: try to find the first '{' and last '}'
                try:
                    start = content.find('{')
                    end = content.rfind('}')
                    if start != -1 and end != -1:
                        plan_data = json.loads(content[start:end+1])
                    else: raise je
                except:
                    logger.error("shopify_json_parse_failed", content=content)
                    raise je

            # DEBUG: Log plan data
            logger.info("shopify_plan_generated", steps=[
                {"id": s.get("id"), "tool": s.get("tool_name"), "input": s.get("tool_input")} 
                for s in plan_data.get("steps", [])
            ])  

            from llm.reasoning.planning import Plan # Import here to avoid issues
            plan = Plan(**plan_data)
        except Exception as e:
            logger.error("planning_failed", error=str(e))
            # Fallback to direct answer if planning fails
            response = await self.llm.generate(f"Please answer this directly: {query}")
            return AgentResult(answer=response.content, metadata={"fallback": True}, success=True)

        # 2. EXECUTION PHASE
        results = {}
        for step in plan.steps:
            if on_status:
                msg = f"Executing: {step.tool_name}..."
                if "search" in step.tool_name: msg = "Searching catalog..."
                elif "cart" in step.tool_name: msg = "Updating your cart..."
                await on_status(msg)

            # Resolve variables ({{step_1.products[0].variants[0].variant_id}})
            actual_input = step.tool_input.copy()
            
            # Validation: Ensure update_cart has required parameters
            if step.tool_name == "update_cart":
                if not actual_input.get("add_items") and not actual_input.get("remove_line_ids"):
                    logger.warning("skipping_empty_update_cart", step_id=step.id)
                    continue
                
                # Default quantity to 1 if missing
                if actual_input.get("add_items"):
                    for item in actual_input["add_items"]:
                        if not item.get("quantity"):
                            item["quantity"] = 1

            def resolve(obj):
                if isinstance(obj, str) and "{" in obj and "}" in obj:
                    import re
                    pattern = r"\{+(step_\d+)\.([^}]+?)\}+"
                    
                    def replacer(match):
                        step_ref = match.group(1).strip()
                        path_str = match.group(2).strip()
                        path = [p.strip() for p in path_str.split(".")]
                        try:
                            step_id = int(step_ref.split("_")[1])
                            if step_id not in results:
                                return match.group(0)
                            
                            curr = results[step_id].data
                            
                            # DEBUG: Log raw data
                            logger.debug("debug_resolve_step_data", step_id=step_id, raw_data=curr)

                            if isinstance(curr, str):
                                try: curr = json.loads(curr)
                                except: pass
                            
                            # DEBUG: Internal helper to resolve path for logging
                            def resolve_path(data, p_list):
                                try:
                                    c = data
                                    for p in p_list:
                                        if "[" in p:
                                            name, rest = p.split("[", 1)
                                            idx = int(rest[:-1])
                                            c = c.get(name, [])[idx]
                                        else: c = c.get(p)
                                    return c
                                except: return "PATH_NOT_FOUND"

                            # Log specific paths as requested by user
                            if step_id == 1:
                                path1 = ["products[0]", "variants[0]", "variant_id"]
                                path2 = ["products[0]", "product_variant_id"]
                                logger.debug("debug_resolve_v1", resolved=resolve_path(curr, path1))
                                logger.debug("debug_resolve_v2", resolved=resolve_path(curr, path2))

                            for p in path:
                                if "[" in p:
                                    name, rest = p.split("[", 1)
                                    idx = int(rest[:-1])
                                    curr = curr.get(name, [])[idx]
                                else:
                                    curr = curr.get(p)
                            return str(curr) if curr is not None else match.group(0)
                        except Exception as ex:
                            logger.warning("resolve_failed_exception", error=str(ex), ref=match.group(0))
                            return match.group(0)
                    
                    # Exact match for type preservation
                    exact_match = re.fullmatch(pattern, obj)
                    if exact_match:
                        step_ref = exact_match.group(1).strip()
                        path = [p.strip() for p in exact_match.group(2).split(".")]
                        try:
                            step_id = int(step_ref.split("_")[1])
                            
                            logger.info("resolve_attempt", step_id=step_id, 
                                data_type=type(results[step_id].data).__name__ if step_id in results else "MISSING",
                                data_keys=list(results[step_id].data.keys()) if (step_id in results and isinstance(results[step_id].data, dict)) else "NOT_DICT"
                            )

                            curr = results[step_id].data
                            if isinstance(curr, str):
                                try: curr = json.loads(curr)
                                except: pass
                            for p in path:
                                if "[" in p:
                                    name, rest = p.split("[", 1)
                                    idx = int(rest[:-1])
                                    curr = curr.get(name, [])[idx]
                                else:
                                    curr = curr.get(p)
                            return curr
                        except: return obj
                            
                    return re.sub(pattern, replacer, obj)
                elif isinstance(obj, dict): return {k: resolve(v) for k, v in obj.items()}
                elif isinstance(obj, list): return [resolve(i) for i in obj]
                return obj
            
            resolved_input = resolve(actual_input)
            logger.debug("plan_step_resolved_input", resolved=resolved_input)

            def clean_nulls(obj):
                """Remove None values and unresolved template strings from tool input."""
                if isinstance(obj, dict):
                    return {
                        k: clean_nulls(v) for k, v in obj.items()
                        if v is not None
                        and v != ""
                        and not (isinstance(v, str) and "{" in v)
                    }
                elif isinstance(obj, list):
                    return [clean_nulls(i) for i in obj]
                return obj

            resolved_input = clean_nulls(resolved_input)
            logger.info("shopify_resolved_input", tool=step.tool_name, input=resolved_input)

            logger.debug("clean_tool_input", tool=step.tool_name, input=resolved_input)

            tool = self.tools.get(step.tool_name)
            if not tool: continue

            try:
                result = await tool.run(**resolved_input)

                data = result.data
                if isinstance(data, str):
                    try: data = json.loads(data)
                    except: pass

                # Re-wrap with parsed data — ToolResult is immutable so mutation silently fails
                from tools.types import ToolResult
                results[step.id] = ToolResult(success=result.success, data=data, error=result.error)
                logger.info("tool_result_raw", tool=step.tool_name, data=data)
                
                scratchpad.append({
                    "step": step.id, "thought": step.thought, "action": step.tool_name,
                    "input": resolved_input, "observation": data
                })

                # 4. POST-PROCESSING (Extract and persist session state)
                if result.success and context:
                    # Persist search results
                    if step.tool_name == "search_shop_catalog":
                        if isinstance(data, dict) and "products" in data:
                            context.setdefault("session_state", {})["last_search_results"] = data["products"]
                            logger.info("last_search_results_persisted", count=len(data["products"]))
                    
                    # Persist cart_id
                    if step.tool_name == "update_cart":
                        new_cart_id = None
                        if isinstance(data, dict):
                            new_cart_id = (
                                data.get("cart", {}).get("id") or
                                data.get("cart_id") or
                                data.get("id")
                            )
                        
                        if new_cart_id:
                            context.setdefault("session_state", {})["cart_id"] = new_cart_id
                            logger.info("cart_id_persisted", cart_id=new_cart_id)
                        else:
                            logger.warning("cart_id_not_found_in_update_cart_response", data=data)

            except Exception as e:
                logger.error("tool_execution_failed", tool=step.tool_name, error=str(e), exc_info=True)
                from tools.types import ToolResult
                results[step.id] = ToolResult(success=False, data=None, error=str(e))

        # 3. SYNTHESIS
        if on_status: await on_status("Generating response...")
        final_answer = await self._synthesize_answer(query, scratchpad)
        
        return AgentResult(
            answer=final_answer,
            metadata={"plan": plan.dict(), "steps_executed": len(results), "tool_results": results}
        )

    async def _synthesize_answer(self, query: str, scratchpad: List[Dict]) -> str:
        """
        Overridden synthesis to specifically handle AuthRequired and Shopify product data.
        """
        # Check if any step returned an AuthRequired message
        auth_url = None
        for step in scratchpad:
            obs = step.get("observation", "")
            if isinstance(obs, str) and "Authentication required. Please log in:" in obs:
                auth_url = obs.split("Please log in: ")[-1].strip()
                break
        
        if auth_url:
            return f"I need you to authenticate with Shopify to access that information. Please log in here: {auth_url}\n\nOnce you've logged in, I'll be able to help you further!"

        # Otherwise use standard synthesis but with Shopify-aware prompt
        prompt = f"""
{self.system_prompt}

User Query: {query}

Execution History (ONLY source of truth):
{json.dumps(scratchpad, indent=2)}

STRICT RULES — violations are unacceptable:
1. ONLY use data from Execution History above. Never invent product names, 
   sizes, quantities, prices, or cart contents not present in tool results.
2. If update_cart succeeded, confirm ONLY the product name and variant from 
   that tool's result. Do NOT summarize the full cart unless get_cart was called.
3. If get_cart was called, show cart contents EXACTLY as returned by the tool.
4. If a tool returned an error, report it honestly. Never pretend it succeeded.
5. If no tool was called, answer conversationally without mentioning products.
6. NEVER describe an action that will happen in the future (e.g. "I'll add it now", 
   "Let me do that"). Only describe what the tools have ALREADY done. 
   If update_cart was not called, do NOT say anything was added to the cart.
"""
        response = await self.llm.generate(prompt)
        return response.content
