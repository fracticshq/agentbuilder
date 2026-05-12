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
        system_prompt: Optional[str] = None,
        agent_profile_url: Optional[str] = None
    ):
        super().__init__(llm, tools, critic, system_prompt)
        # Unified Session State
        self.state = {
            "captured_ids": {},    # All seen IDs (name -> gid)
            "last_searched": {},   # IDs from the last search only
            "cart_id": None,
            "checkout_url": None,
            "cart_lines": [],
            "agent_profile_url": agent_profile_url or "https://shopify.dev/ucp/agent-profiles/examples/2026-04-08/valid-with-capabilities.json"
        }
        self.conversation: List[Dict[str, Any]] = []
        self.prompt_runtime_context: Dict[str, Any] = {}
        
        # Memory & Knowledge
        self.memory = {
            "user_facts": [],
            "summaries": [],
            "matched_rules": []
        }
        self.retrieval_context = None

    async def run(
        self, 
        query: str, 
        chat_history: Optional[List[Dict[str, Any]]] = None, 
        context: Optional[Dict] = None,
        on_status: Optional[Any] = None
    ) -> AgentResult:
        """Main entry point for the Shopify Orchestrator."""
        logger.info("shopify_orchestrator_run", query=query)
        
        # 1. Reconstruct state from context and history
        self._hydrate_session(chat_history, context)
        
        # 2. Add current query
        self.conversation.append({"role": "user", "content": query})
        
        # 3. Iterative reasoning loop
        final_answer, tool_results = await self._agent_loop(on_status)
        
        # 4. Return result with persisted state
        return AgentResult(
            answer=final_answer,
            metadata={
                "steps_executed": len(tool_results), 
                "tool_results": tool_results,
                **self.state
            }
        )

    def _hydrate_session(self, chat_history: Optional[List[Dict]], context: Optional[Dict]):
        """Load persistent state and reconstruct conversation history."""
        ctx = context or {}
        session = ctx.get("session_state", {})
        
        # Update core state
        self.state.update({
            "cart_id": session.get("cart_id"),
            "checkout_url": session.get("checkout_url"),
            "cart_lines": session.get("cart_lines", []),
            "captured_ids": session.get("captured_ids", {}),
            "last_searched": session.get("last_searched", {}),
        })
        
        # Update runtime context
        self.prompt_runtime_context = ctx.get("prompt_runtime", {})
        
        # Load agent profile URL priority: session > context > default
        self.state["agent_profile_url"] = session.get("agent_profile_url") or ctx.get("agent_profile_url") or self.state["agent_profile_url"]
        
        # Load Matrix Memory
        mem_ctx = ctx.get("memory", {})
        self.memory.update({
            "user_facts": mem_ctx.get("user_facts", []),
            "summaries": mem_ctx.get("summaries", []),
            "matched_rules": mem_ctx.get("matched_rules", [])
        })

        # Load Vector Retrieval Context
        self.retrieval_context = ctx.get("retrieval")

        # Reconstruct chat history
        self.conversation = []
        if chat_history:
            for msg in chat_history:
                role, content = msg.get("role"), msg.get("content")
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
        cart_id = self.state.get("cart_id")
        if cart_id:
            for key in ["cart_id", "cartId"]:
                if key in tool_input and not tool_input[key]:
                    tool_input[key] = cart_id
            if tool_name in ["update_cart", "get_cart"] and "cart_id" not in tool_input:
                tool_input["cart_id"] = cart_id
        
        # If calling get_cart/update_cart without a cart_id, it might fail or create a new one.
        if tool_name in ["get_cart", "update_cart"] and not tool_input.get("cart_id"):
            logger.warning("shopify_executing_without_cart_id", tool=tool_name, current_input=tool_input)
        
        # 2. Resolve IDs and normalize keys for update_cart
        if tool_name == "update_cart":
            # Normalize flat input (e.g. {"variant_id": "...", "quantity": 1}) into add_items list
            if "add_items" not in tool_input and "lines" not in tool_input:
                variant_id = None
                for key in ["product_variant_id", "merchandiseId", "merchandise_id", "variant_id", "variantId", "id"]:
                    if key in tool_input:
                        variant_id = tool_input.pop(key)
                        break
                if variant_id:
                    tool_input["add_items"] = [{"product_variant_id": variant_id, "quantity": tool_input.pop("quantity", 1)}]

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
                        # Extract intent from item description
                        item_str = str(item.get("title") or item.get("name") or str(item)).lower()
                        
                        # Helper to check if item_str refers to the title
                        def is_match(title_str: str) -> bool:
                            title_lower = title_str.lower()
                            # Direct inclusion
                            if title_lower in item_str or item_str in title_lower:
                                return True
                            # Keyword match
                            item_tokens = set(item_str.replace("{", "").replace("}", "").replace("'", "").split())
                            title_tokens = set(title_lower.split())
                            common = item_tokens.intersection(title_tokens)
                            common = {w for w in common if w not in {"the", "a", "an", "to", "cart", "product", "item", "yes", "ok"}}
                            return len(common) > 0

                        # 1. Check last_searched FIRST (priority for "yes" / confirmation / pronouns)
                        # For affirmative intents like "yes", "ok", "do it", try to find what the assistant just said
                        assistant_last_msg = ""
                        for msg in reversed(self.conversation):
                            if msg["role"] == "assistant":
                                assistant_last_msg = str(msg.get("content", "")).lower()
                                break

                        for title, gid in self.state["last_searched"].items():
                            title_lower = title.lower()
                            is_affir = bool(item_str in ("yes", "ok", "it", "add it", "do it"))
                            is_ment = bool(str(title_lower) in str(assistant_last_msg))
                            if is_match(title) or (is_affir and is_ment):
                                existing_id = gid
                                logger.info("shopify_resolved_from_last_searched_mention", title=title, gid=gid)
                                break
                        
                        # 2. Case where user says "yes" but we didn't match the title in the assistant's text
                        if not existing_id and item_str in ["yes", "ok", "it", "add it", "do it"]:
                             if self.state["last_searched"]:
                                 existing_id = list(self.state["last_searched"].values())[0]
                                 logger.info("shopify_resolved_from_last_searched_fallback")
 
                        # 3. Check broad captured_ids if still no ID
                        if not existing_id:
                            for title, gid in self.state["captured_ids"].items():
                                if is_match(title):
                                    existing_id = gid
                                    logger.info("shopify_resolved_from_captured_ids", title=title, gid=gid)
                                    break

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
                        raise ValueError(f"Missing variant ID for '{product_name}'. You MUST call 'search_catalog' first to find the correct variant ID.")

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
                self.state["cart_id"] = str(new_id)
            
            # Capture checkout URL
            new_url = cart.get("checkout_url") or cart.get("checkoutUrl")
            if new_url:
                self.state["checkout_url"] = str(new_url)
            
            # Store full lines for prompt injection
            self.state["cart_lines"] = cart.get("lines") or cart.get("line_items") or []

        # Capture Product/Variant IDs for future reference
        products = metadata.get("products", [])
        
        # Reset last_searched if this was a new search
        if tool_name == "search_catalog":
            self.state["last_searched"] = {}

        for p in products:
            if not isinstance(p, dict): continue
            name = str(p.get("name") or p.get("title") or "").lower()
            gid = str(p.get("variant_id") or p.get("id") or "")
            
            if name and gid:
                self.state["captured_ids"][name] = gid
                if tool_name == "search_catalog":
                    self.state["last_searched"][name] = gid

    def _build_reasoning_prompt(self) -> str:
        """Construct the few-shot prompting context with mandatory next-step hints for adds."""
        text = ""
        # Performance optimization: Keep last 8 messages for focus
        context_window = self.conversation[-8:]
        
        # Detect if we should chain an add
        last_msg = context_window[-1] if context_window else None
        is_tool_after_search = False
        if last_msg and last_msg["role"] == "tool" and last_msg.get("name") == "search_catalog":
            is_tool_after_search = True
            
        # Refine: Only chain if the user's intent was to ADD/BUY or CONFIRM
        has_add_intent = False
        has_remove_intent = False
        last_user_msg = ""
        
        # Resolve user msg safely
        for msg in reversed(self.conversation):
            if msg.get("role") == "user":
                last_user_msg = str(msg.get("content", "")).lower()
                break
        
        if is_tool_after_search and last_user_msg:
            # Keywords that imply adding
            has_add_intent = any(kw in last_user_msg for kw in ["add", "buy", "cart", "put in", "purchase", "yes", "ok", "do it"])

        # Detect removal intent
        if last_user_msg:
            has_remove_intent = any(kw in last_user_msg for kw in ["remove", "delete", "decrease", "minus", "less", "reduce"])

        for msg in context_window:
            role = str(msg.get("role", ""))
            content = str(msg.get("content", ""))
            if role == "user":
                text += f"User: {content}\n"
            elif role == "assistant":
                text += f"Assistant: {content}\n"
            elif role == "tool":
                t_name = str(msg.get("name", "unknown"))
                text += f"Tool ({t_name}): {content}\n"
        
        if is_tool_after_search and has_add_intent:
            text += "\n[SYSTEM NOTE]: You just found the product and the user wants to add it. You MUST now return the 'update_cart' JSON immediately. ⛔ DO NOT chat or say 'One moment'. Just return the JSON."
        elif is_tool_after_search:
            text += "\n[SYSTEM NOTE]: You just found the product. If the user only asked to see/search, DO NOT add it yet. Ask if they want to add it."
        
        if has_remove_intent:
            # Check if we already have the cart info in the last few messages
            has_recent_cart = any(str(m.get("role")) == "tool" and str(m.get("name")) in ["get_cart", "update_cart"] for m in context_window)
            if not has_recent_cart:
                text += "\n[SYSTEM NOTE]: The user wants to remove/decrease an item. You MUST call 'get_cart' first to find the correct line_id and current quantity. ⛔ DO NOT chat first."

        return str(text) + "\nAssistant:"

    def _get_cart_lines_context(self) -> str:
        """Format current cart items for prompt injection."""
        if not self.cart_lines:
            return ""
        
        ctx = "\n### 🛒 CURRENT CART ITEMS (for removal/updates):\n"
        for line in self.cart_lines:
            if not isinstance(line, dict): continue
            line_id = str(line.get("id") or "unknown")
            qty = line.get("quantity", 0)
            merch = line.get("merchandise") or {}
            title = merch.get("title") or merch.get("name") or "Product"
            ctx += f"- {title} (ID: {line_id}, Qty: {qty})\n"
        return ctx

    def _get_combined_system_prompt(self) -> str:
        """Assembles the final system prompt from modular components."""
        base_prompt = self.system_prompt or "You are a helpful AI assistant."
        
        sections = [
            base_prompt,
            "## SHOPIFY CAPABILITIES",
            f"Current Cart ID: {self.state['cart_id'] or 'None'}",
            f"Checkout URL: {self.state['checkout_url'] or 'None'}",
            self._get_knowledge_context(),
            self._get_cart_context(),
            self._get_memory_context(),
            self._get_focus_context(),
            self._get_execution_rules(),
            "### JSON INTERACTION SCHEMA",
            self._get_json_schema(),
            "### KNOWLEDGE-FIRST REASONING",
            "Trust retrieved knowledge as your primary source. Use tools only for real-time stock/price or when knowledge is missing."
        ]
        
        return "\n\n".join(s for s in sections if s)

    def _get_knowledge_context(self) -> str:
        """Inject vector search results (KB Chunks)."""
        if not self.retrieval_context or not hasattr(self.retrieval_context, "chunks"):
            return ""
        
        chunks = self.retrieval_context.chunks
        if not chunks:
            return ""
            
        ctx = "### 📚 RETRIEVED KNOWLEDGE (Ground Truth)\n"
        for i, chunk in enumerate(chunks[:8]): # Limit to top 8 chunks
            content = chunk.get("content") if isinstance(chunk, dict) else getattr(chunk, "content", str(chunk))
            source = chunk.get("metadata", {}).get("source", "Knowledge Base") if isinstance(chunk, dict) else "Knowledge Base"
            ctx += f"[Source: {source}]\n{content}\n---\n"
        return ctx

    def _get_cart_context(self) -> str:
        if not self.state["cart_lines"]:
            return "Cart is currently empty."
        
        ctx = "### 🛒 CURRENT CART ITEMS\n"
        for line in self.state["cart_lines"]:
            if not isinstance(line, dict): continue
            merch = line.get("merchandise") or {}
            title = merch.get("title") or merch.get("name") or "Product"
            ctx += f"- {title} (Line ID: {line.get('id')}, Qty: {line.get('quantity', 0)})\n"
        return ctx

    def _get_focus_context(self) -> str:
        ctx = ""
        if self.state["last_searched"]:
            ctx += "### 🎯 ACTIVE PRODUCT FOCUS\n"
            for title, gid in self.state["last_searched"].items():
                ctx += f"- {title} (ID: {gid})\n"
            ctx += "--> If user says 'yes' or 'add it', they refer to these.\n"
        
        if self.state["captured_ids"]:
            ctx += "### 📚 SESSION HISTORY\n"
            history = list(self.state["captured_ids"].items())[-5:]
            for name, gid in history:
                if name not in self.state["last_searched"]:
                    ctx += f"- {name} (ID: {gid})\n"
        return ctx

    def _get_memory_context(self) -> str:
        """Matrix Memory Layer Integration."""
        facts = self.memory.get("user_facts", [])
        summaries = self.memory.get("summaries", [])
        if not facts and not summaries:
            return ""

        ctx = "### 🧠 USER MEMORY & PREFERENCES\n"
        if facts:
            ctx += "KNOWN FACTS:\n"
            for f in facts:
                text = f.get("fact_text") or f.get("content")
                if text: ctx += f"- {text}\n"
        
        if summaries:
            ctx += "\nSTORY SO FAR:\n"
            text = summaries[0].get("summary_text") or summaries[0].get("content")
            if text: ctx += f"{text}\n"
        return ctx

    def _get_execution_rules(self) -> str:
        return """### ⛔ MANDATORY EXECUTION RULES
1. **TOOL-FIRST**: Return JSON tool calls IMMEDIATELY before any chat response.
2. **YES/OK HANDLING**: After a search, 'yes' implies adding the active focus product.
3. **CART VERIFICATION**: Call 'get_cart' before removing or updating items if line_id is unknown.
4. **CHECKOUT**: Always provide the checkout_url in final answers if items are in the cart."""

    def _get_json_schema(self) -> str:
        return f"""You MUST return a JSON object to call tools:
{{
  "tool_name": "name",
  "tool_input": {{ "arg": "val" }}
}}
Example Search: {{"tool_name": "search_catalog", "tool_input": {{"meta": {{"ucp-agent": {{"profile": "{self.state['agent_profile_url']}"}}}}, "catalog": {{"query": "socks"}}}}}}"""

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
