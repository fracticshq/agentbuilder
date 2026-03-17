"""
Shopify Specialized Orchestrator - SOTA 2026 Iterative Reasoning Loop.
"""

import json
import re
import asyncio
import structlog
import inspect
from typing import Dict, Any, List, Optional, Tuple
from .orchestrator import Orchestrator, AgentResult
from tools.types import ToolResult

logger = structlog.get_logger(__name__)

class ShopifyOrchestrator(Orchestrator):
    """
    Specialized Orchestrator for Shopify.
    Handles Shopify-specific data structures, iterative tool chaining, and state management.
    """
    
    def __init__(
        self, 
        llm: Any, 
        tools: Any, 
        critic: Optional[Any] = None, 
        system_prompt: Optional[str] = None
    ):
        super().__init__(llm, tools, critic, system_prompt)
        # Context to track found products/variants for natural language reference
        self.captured_ids: Dict[str, str] = {}
        self.cart_id: Optional[str] = None
        self.conversation: List[Dict[str, Any]] = []

    async def run(
        self, 
        query: str, 
        chat_history: Optional[List[Dict[str, Any]]] = None, 
        context: Optional[Dict] = None,
        on_status: Optional[Any] = None
    ) -> AgentResult:
        """
        Main entry point for the Shopify Orchestrator.
        """
        logger.info("shopify_orchestrator_run", query=query)
        
        # 1. Reset/Initialize state for this turn
        self._initialize_session_state(chat_history, context)
        
        # 2. Add current query
        self.conversation.append({"role": "user", "content": query})
        
        # 3. Execute the iterative agent loop
        final_answer, tool_results = await self._agent_loop(on_status)
        
        # 4. Return standard AgentResult with persisted state in metadata
        return AgentResult(
            answer=final_answer,
            metadata={
                "steps_executed": len(tool_results), 
                "tool_results": tool_results,
                "cart_id": self.cart_id,
                "captured_ids": self.captured_ids
            }
        )

    def _initialize_session_state(self, chat_history: Optional[List[Dict]], context: Optional[Dict]):
        """Load persistent state and reconstruct conversation history."""
        session_state = (context or {}).get("session_state", {})
        self.cart_id = session_state.get("cart_id")
        self.captured_ids = session_state.get("captured_ids", {})
        
        self.conversation = []
        if chat_history:
            for msg in chat_history:
                role = msg.get("role")
                content = msg.get("content")
                if role and content:
                    conv_msg = {"role": role, "content": content}
                    if role == "tool" and msg.get("name"):
                        conv_msg["name"] = msg["name"]
                    self.conversation.append(conv_msg)

    async def _agent_loop(self, on_status: Optional[Any] = None) -> Tuple[str, Dict[str, ToolResult]]:
        """Core iterative loop for reasoning and acting."""
        tool_results_map: Dict[str, ToolResult] = {}
        iteration = 0
        max_iterations = 6
        last_tool_call = None

        while iteration < max_iterations:
            iteration += 1
            try:
                logger.info("shopify_agent_loop_iteration", iteration=iteration)
                
                # A. Get next action from LLM
                message, tool_call = await self._get_next_action()
                logger.info("shopify_agent_thought", iteration=iteration, message=message, tool_call=tool_call)

                if not tool_call:
                    # No tool call - this is the final final answer
                    logger.info("shopify_final_answer_reached")
                    self.conversation.append({"role": "assistant", "content": message})
                    return message, tool_results_map

                # B. Execute the tool call
                if tool_call == last_tool_call:
                    logger.warning("shopify_loop_detected", tool=tool_call["tool_name"])
                    break
                last_tool_call = tool_call

                tool_name = tool_call["tool_name"]
                tool_input = tool_call.get("tool_input") or {}

                if on_status and callable(on_status):
                    try:
                        res = on_status(self._get_status_message(tool_name))
                        if res is not None:
                            if inspect.isawaitable(res):
                                await res
                    except Exception as status_err:
                        logger.warning("status_callback_failed", error=str(status_err))

                # C. Perform action & capture results
                tool_result = await self._execute_tool_action(tool_name, tool_input)
                tool_results_map[tool_name] = tool_result
                logger.info("shopify_tool_result", tool=tool_name, success=tool_result.success, error=tool_result.error)

                # D. Record interaction
                self.conversation.append({"role": "assistant", "content": message})
                
                # Use error message if success is false
                content = tool_result.error if not tool_result.success else self._format_tool_output(tool_result.data)
                self.conversation.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": content
                })
            except Exception as loop_err:
                logger.error("shopify_agent_loop_error", iteration=iteration, error=str(loop_err))
                # Feed error back to LLM to allow one last chance to recover
                self.conversation.append({"role": "tool", "name": "system", "content": f"System Error: {str(loop_err)}"})
                if iteration >= max_iterations:
                    break

        logger.warning("shopify_agent_loop_max_iterations_or_loop")
        return "I've run into an issue processing your request. Could you please specify which product or action you'd like me to take?", tool_results_map

    async def _get_next_action(self) -> Tuple[str, Optional[Dict]]:
        """Consult the LLM to decide the next step."""
        prompt = self._build_reasoning_prompt()
        system_prompt = self._get_combined_system_prompt()
        
        logger.debug("shopify_generating_action", prompt=prompt)
        response = await self.llm.generate(prompt=prompt, system_prompt=system_prompt)
        message = response.content.strip()
        
        return message, self._parse_tool_call(message)

    async def _execute_tool_action(self, tool_name: str, tool_input: Dict[str, Any]) -> ToolResult:
        """Preprocess, execute, and postprocess a tool call."""
        try:
            # 1. Resolve IDs from cache and inject cart_id
            self._preprocess_input(tool_name, tool_input)
            
            logger.info("shopify_executing_tool", tool=tool_name, input=tool_input)
            
            # 2. Call the registry
            tool = self.tools.get(tool_name)
            if not tool:
                logger.error("shopify_tool_not_found", tool_name=tool_name)
                return ToolResult(success=False, data=None, error=f"Tool '{tool_name}' not found.")
                
            result = await tool.run(**tool_input)
            logger.info("shopify_tool_result_raw", tool=tool_name, success=result.success, error=result.error)
            
            # 3. Capture state from result (cart_id, products, etc.)
            if result.success:
                self._capture_result_state(tool_name, result)
            return result
        except Exception as e:
            logger.error("shopify_tool_execution_failed", tool=tool_name, error=str(e))
            return ToolResult(success=False, data=None, error=str(e))

    def _preprocess_input(self, tool_name: str, tool_input: Dict[str, Any]):
        """Inject state and resolve natural language references to GIDs."""
        if self.cart_id:
            for key in ["cart_id", "cartId"]:
                if key in tool_input and not tool_input[key]:
                    tool_input[key] = self.cart_id
            if tool_name in ["update_cart", "get_cart"] and "cart_id" not in tool_input:
                tool_input["cart_id"] = self.cart_id
        
        # If calling get_cart/update_cart without a cart_id, it might fail or create a new one.
        # We handle this by letting the tool itself decide, but we log a warning.
        if tool_name in ["get_cart", "update_cart"] and not tool_input.get("cart_id"):
            logger.warning("shopify_executing_without_cart_id", tool=tool_name, current_input=tool_input)
        
        # 2. Resolve IDs and normalize keys for update_cart
        if tool_name == "update_cart":
            # The Shopify MCP tool expects 'add_items' (List) and 'product_variant_id' (GID)
            items = tool_input.get("add_items") or tool_input.get("lines")
            if items and isinstance(items, list):
                tool_input["add_items"] = items
                tool_input.pop("lines", None)
                
                for item in items:
                    if not isinstance(item, dict): continue
                    
                    # Detect existing variant ID
                    existing_id = None
                    for key in ["product_variant_id", "merchandiseId", "merchandise_id", "variant_id", "variantId", "id"]:
                        val = item.get(key)
                        if val and isinstance(val, str) and val.startswith("gid://"):
                            existing_id = val
                            break
                    
                    # Resolution logic if no GID found
                    if not existing_id:
                        item_str = str(item).lower()
                        for title, gid in self.captured_ids.items():
                            if title in item_str or any(word in title for word in item_str.split()):
                                existing_id = gid
                                logger.info("shopify_resolved_id", title=title, gid=gid)
                                break
                        
                        if not existing_id and len(self.captured_ids) == 1:
                            existing_id = list(self.captured_ids.values())[0]
                            logger.info("shopify_fallback_id")

                    # Final normalization to 'product_variant_id'
                    if existing_id:
                        item["product_variant_id"] = existing_id
                        # Cleanup other keys
                        for key in ["lines", "merchandiseId", "merchandise_id", "variant_id", "variantId", "id"]:
                            if key != "product_variant_id":
                                item.pop(key, None)
                    else:
                        logger.warning("shopify_missing_id_for_item", item=item)

                    # Ensure quantity is integer
                    if "quantity" in item:
                        try: item["quantity"] = int(item["quantity"])
                        except: item["quantity"] = 1
                
                # Final validation pass
                for item in tool_input["add_items"]:
                    pvid = item.get("product_variant_id")
                    if not pvid or not str(pvid).startswith("gid://"):
                        product_name = item.get("title") or item.get("product_name") or "the product"
                        raise ValueError(f"Missing variant ID for '{product_name}'. You MUST call 'search_shop_catalog' first to find the correct variant ID.")

        # 3. Strip any remaining None/null/empty strings to prevent tool failures
        # Specifically target 'cart_id' and 'cartId' if they are invalid
        for key in ["cart_id", "cartId"]:
            val = tool_input.get(key)
            if val is None or val == "" or str(val).lower() == "none" or str(val).lower() == "null":
                tool_input.pop(key, None)
                logger.info("shopify_stripped_invalid_cart_id", key=key)

        # General strip for any other None values
        keys_to_remove = [k for k, v in tool_input.items() if v is None or v == "null"]
        if keys_to_remove:
            logger.info("shopify_stripping_keys", keys=keys_to_remove)
        for k in keys_to_remove:
            tool_input.pop(k, None)

    def _capture_result_state(self, tool_name: str, result: ToolResult):
        """Update orchestrator state based on tool outputs."""
        metadata = result.metadata or {}
        
        # Capture Cart ID
        cart = metadata.get("cart")
        if cart and isinstance(cart, dict):
            new_id = cart.get("cart_id") or cart.get("id")
            if new_id:
                self.cart_id = str(new_id)

        # Capture Product/Variant IDs for future reference
        products = metadata.get("products", [])
        for p in products:
            if not isinstance(p, dict): continue
            name = str(p.get("name") or p.get("title") or "").lower()
            v_id = p.get("variant_id") or p.get("id")
            if name and v_id:
                self.captured_ids[name] = str(v_id)

    def _build_reasoning_prompt(self) -> str:
        """Construct the few-shot prompting context."""
        text = ""
        # Keep last 10 messages for focus
        for msg in self.conversation[-10:]:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                text += f"User: {content}\n"
            elif role == "assistant":
                text += f"Assistant: {content}\n"
            elif role == "tool":
                text += f"Tool ({msg.get('name', 'unknown')}): {content}\n"
        
        text += "\nAssistant:"
        return text

    def _get_combined_system_prompt(self) -> str:
        """Combine base system prompt with Shopify-specific rules."""
        base_prompt = self.system_prompt or "You are a helpful AI assistant."
        
        shopify_rules = f"""
You are a Shopify assistant. You help users find products, answer questions about policies, and manage their shopping cart.
Current Cart ID: {self.cart_id or "None"}

⚠️ MANDATORY TOOL USAGE RULES ⚠️
1. ALWAYS verify the current cart state by calling `get_cart` before answering any questions about what is in the cart. DO NOT rely on your memory or previous turns.
2. To browse products → Use `search_shop_catalog(query, context)`.
3. To check policies/FAQs/shipping/returns → Use `search_shop_policies_and_faqs(query, context)`.
4. To see the current cart items (e.g. "what's in my cart?", "cart info") → Use `get_cart(cart_id)`.
5. To add or remove items → Use `update_cart(cart_id, add_items)`.

STRICT OUTPUT FORMAT:
1. To call a tool → You MUST return ONLY a JSON object. No conversational text.
   Example: {{"tool_name": "search_shop_catalog", "tool_input": {{"query": "socks", "context": "browsing"}}}}
2. For the final answer → You MUST return natural language. DO NOT return raw JSON.
   Example: "I found some white cricket socks for you! Would you like me to add them to your cart?"

CRITICAL GUIDELINES:
- **IMMEDIATE ACTION**: If the user says "add [product] to cart", "buy [product]", or "add it", and you have found the product/variant → You MUST call `update_cart` immediately in the VERY NEXT iteration. DO NOT ask "Would you like me to add these?". Just do it.
- DO NOT say "Done" or "I have added..." UNLESS you have executed `update_cart` in a previous iteration of THIS turn and received a successful response.
- DO NOT report cart items UNLESS you have executed `get_cart` in THIS turn.
- IF a user asks to add something you haven't searched for yet (e.g. "add socks") → You MUST first call `search_shop_catalog`.
- IF a user asks to remove something → You MUST first call `get_cart`, then call `update_cart` with a negative quantity for that specific variant ID.
- IF you do not have a Cart ID yet and need to add an item → Omit the `cart_id` parameter entirely from `update_cart` to create a new cart.
- ONLY add items to the cart if the user explicitly says "add", "buy", "yes" (after you suggested adding), or "I want this".
- NEVER ask the user for "GIDs" or "IDs". Use the names you see in the tool results.

CHAINING EXAMPLES:
1. User: "Add white socks" -> Action: `search_shop_catalog` -> (Observes result) -> Thought: I see the variant ID. Now I'll add it. -> Action: `update_cart` -> (Observes result) -> Final Answer: "Done! I've added them."
2. User: "What's in my cart?" -> Action: `get_cart` -> (Observes result) -> Final Answer: "You have white socks in your cart."
"""
        return f"{base_prompt}\n\n{shopify_rules}"

    def _get_status_message(self, tool_name: str) -> str:
        """Map tool names to user-friendly status updates."""
        if "search" in tool_name: return "Searching catalog..."
        if "cart" in tool_name: return "Updating your cart..."
        if "details" in tool_name: return "Fetching product details..."
        return f"Executing {tool_name}..."

    def _format_tool_output(self, data: Any) -> str:
        """Format data for LLM consumption."""
        if isinstance(data, str): return data
        return json.dumps(data)

    def _parse_tool_call(self, message: str) -> Optional[Dict]:
        """Extract JSON tool call from LLM response."""
        clean_msg = message.strip()
        
        # 1. Direct JSON
        try:
            parsed = json.loads(clean_msg)
            if isinstance(parsed, dict) and "tool_name" in parsed: 
                return parsed
        except: pass

        # 2. Markdown Block
        match = re.search(r"```json\s*({.*?})\s*```", message, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict) and "tool_name" in parsed: 
                    return parsed
            except: pass
            
        # 3. Embedded JSON
        start_idx = message.find('{')
        if start_idx != -1:
            end_idx = message.rfind('}')
            if end_idx > start_idx:
                try:
                    candidate = message[start_idx:end_idx+1]
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "tool_name" in parsed:
                        return parsed
                except: pass
        
        return None
