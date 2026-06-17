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
        self.last_searched: Dict[str, str] = {}
        self.cart_id: Optional[str] = None
        self.checkout_url: Optional[str] = None
        self.cart_lines: List[Dict[str, Any]] = []
        self.conversation: List[Dict[str, Any]] = []
        self.prompt_runtime_context: Dict[str, Any] = {}
        self.active_product_focus: List[Dict[str, Any]] = []
        self.product_reference_map: Dict[str, Dict[str, Any]] = {}
        self.last_user_query: Optional[str] = None
        self.last_search_query: Optional[str] = None
        self.last_constraints: Dict[str, Any] = {}
        self.rerank_results: List[Dict[str, Any]] = []
        self.resolved_reference: Optional[Dict[str, Any]] = None
        self.pending_clarification_response: Optional[str] = None

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
                "checkout_url": self.checkout_url,
                "cart_lines": self.cart_lines,
                "captured_ids": self.captured_ids,
                "last_searched": self.last_searched,
                "active_product_focus": self.active_product_focus,
                "product_reference_map": self.product_reference_map,
                "last_user_query": self.last_user_query,
                "last_search_query": self.last_search_query,
                "last_constraints": self.last_constraints,
                "commerce_intent": self.last_constraints,
                "rerank_results": self.rerank_results,
                "resolved_reference": self.resolved_reference,
                "original_query": self.last_user_query,
                "search_query": self.last_search_query,
            }
        )

    def _initialize_session_state(self, chat_history: Optional[List[Dict]], context: Optional[Dict]):
        """Load persistent state and reconstruct conversation history."""
        session_state = (context or {}).get("session_state", {})
        self.cart_id = session_state.get("cart_id")
        self.checkout_url = session_state.get("checkout_url")
        self.cart_lines = session_state.get("cart_lines", [])
        self.captured_ids = session_state.get("captured_ids", {})
        self.last_searched = session_state.get("last_searched", {})
        self.active_product_focus = session_state.get("active_product_focus", [])
        self.product_reference_map = session_state.get("product_reference_map", {})
        self.last_user_query = session_state.get("last_user_query")
        self.last_search_query = session_state.get("last_search_query")
        self.last_constraints = session_state.get("last_constraints", {})
        self.rerank_results = session_state.get("rerank_results", [])
        self.resolved_reference = None
        self.pending_clarification_response = None
        self.prompt_runtime_context = (context or {}).get("prompt_runtime", {})
        
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

                if iteration == 1:
                    confirmed_cart_add = self._get_confirmed_cart_add()
                    if self.pending_clarification_response:
                        logger.info("shopify_reference_clarification_needed", resolved_reference=self.resolved_reference)
                        return self.pending_clarification_response, tool_results_map
                    proactive_call = None if confirmed_cart_add else self._get_proactive_catalog_search()
                    first_pass_call = confirmed_cart_add or proactive_call
                    if first_pass_call:
                        tool_name = first_pass_call["tool_name"]
                        tool_input = first_pass_call.get("tool_input") or {}
                        event_name = "shopify_confirmed_cart_add" if confirmed_cart_add else "shopify_proactive_catalog_search"
                        logger.info(event_name, tool=tool_name, input=tool_input)
                        if on_status and callable(on_status):
                            try:
                                res = on_status(self._get_status_message(tool_name))
                                if res is not None and inspect.isawaitable(res):
                                    await res
                            except Exception as status_err:
                                logger.warning("status_callback_failed", error=str(status_err))

                        tool_result = await self._execute_tool_action(tool_name, tool_input)
                        tool_results_map[tool_name] = tool_result
                        logger.info(
                            f"{event_name}_result",
                            tool=tool_name,
                            success=tool_result.success,
                            error=tool_result.error,
                            products=len((tool_result.metadata or {}).get("products") or []),
                        )
                        self.conversation.append({
                            "role": "assistant",
                            "content": json.dumps(first_pass_call),
                        })
                        content = tool_result.error if not tool_result.success else self._format_tool_output(tool_result.data)
                        self.conversation.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": content,
                        })
                        if confirmed_cart_add:
                            self.conversation.append({
                                "role": "system",
                                "content": "The referenced product has been added to the cart. Respond with a concise confirmation using the cart context; do not call update_cart again for the same item.",
                            })
                
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

    def _get_confirmed_cart_add(self) -> Optional[Dict[str, Any]]:
        """Resolve pronoun-based add-to-cart requests from the Shopify session focus only."""
        if not self.tools.get("update_cart"):
            return None

        last_user_msg = self._get_last_user_message()
        if not last_user_msg:
            return None

        lowered = last_user_msg.lower().strip()
        explicit_reference = bool(re.search(r"\b(add|put|place)\s+(it|this|that|one)\b", lowered))
        cart_reference = bool(re.search(r"\b(add|put|place)\s+(it|this|that|one)?\s*(to|in|into)\s+(my\s+)?cart\b", lowered))
        ordinal_reference = bool(re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\s+(one|product|item)?\b", lowered))
        price_reference = bool(re.search(r"\b(cheapest|cheaper|lowest price|least expensive|expensive|priciest|costliest|highest price)\b", lowered))
        short_confirmation = lowered in {
            "yes",
            "yes please",
            "ok",
            "okay",
            "sure",
            "do it",
            "add it",
            "add this",
            "add that",
            "add to cart",
            "add it to cart",
        }
        has_add_intent = any(kw in lowered for kw in ["add", "put", "place", "cart", "buy", "purchase", "yes", "ok", "do it"])
        title_reference = self._find_focus_by_title(lowered) if has_add_intent else None
        if not (explicit_reference or cart_reference or ordinal_reference or price_reference or short_confirmation or title_reference):
            return None

        resolved = self._resolve_product_reference(last_user_msg)
        self.resolved_reference = resolved

        if resolved.get("status") != "resolved":
            self.pending_clarification_response = self._build_reference_clarification(resolved)
            return None

        product = resolved.get("product") or {}
        title = str(product.get("name") or product.get("title") or "this product")
        variant_id = str(product.get("variant_id") or product.get("id") or "")
        if not variant_id:
            self.pending_clarification_response = f"I found {title}, but I do not have a valid variant ID to add it to the cart. Please choose another product."
            return None

        logger.info("shopify_confirmed_cart_add_resolved", title=title, variant_id=variant_id)
        return {
            "tool_name": "update_cart",
            "tool_input": {
                "add_items": [
                    {
                        "product_variant_id": variant_id,
                        "quantity": 1,
                        "title": title,
                    }
                ]
            },
        }

    def _get_last_user_message(self) -> str:
        for msg in reversed(self.conversation):
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""

    def _focus_products(self) -> List[Dict[str, Any]]:
        products = [p for p in self.active_product_focus if isinstance(p, dict)]
        if products:
            return products
        fallback = []
        for idx, (title, variant_id) in enumerate((self.last_searched or self.captured_ids).items(), start=1):
            fallback.append({
                "rank": idx,
                "name": title,
                "title": title,
                "variant_id": variant_id,
                "id": variant_id,
            })
        return fallback

    def _find_focus_by_title(self, lowered_message: str) -> Optional[Dict[str, Any]]:
        best_product = None
        best_score = 0.0
        message_tokens = self._tokens(lowered_message)
        for product in self._focus_products():
            product_tokens = self._tokens(str(product.get("name") or product.get("title") or ""))
            if not product_tokens:
                continue
            common = message_tokens.intersection(product_tokens)
            score = len(common) / max(1, len(product_tokens))
            if score > best_score:
                best_score = score
                best_product = product
        return best_product if best_score >= 0.45 else None

    def _tokens(self, value: str) -> set:
        stopwords = {
            "the", "a", "an", "to", "cart", "product", "item", "items", "one", "this", "that",
            "it", "add", "put", "place", "buy", "show", "me", "please", "for", "with", "and", "or",
        }
        return {
            token for token in re.sub(r"[^a-z0-9\s-]", " ", value.lower()).split()
            if token and token not in stopwords
        }

    def _to_price(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            return self._to_price(value.get("amount"))
        try:
            return float(str(value).replace(",", "").replace("₹", "").strip())
        except (TypeError, ValueError):
            return None

    def _display_price(self, value: Any) -> Any:
        price = self._to_price(value)
        if price is None:
            return value
        display_price = price / 100 if price >= 10000 else price
        return int(display_price) if float(display_price).is_integer() else round(display_price, 2)

    def _resolve_product_reference(self, message: str) -> Dict[str, Any]:
        lowered = message.lower().strip()
        products = self._focus_products()
        if not products:
            return {"status": "no_focus", "confidence": 0.0, "reason": "No active product focus exists."}

        ordinal_map = {
            "first": 1, "1st": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
        }
        for label, position in ordinal_map.items():
            if re.search(rf"\b{label}\b", lowered):
                if len(products) >= position:
                    return self._resolved(products[position - 1], 0.98, f"Matched ordinal reference: {label}.")
                return {"status": "ambiguous", "confidence": 0.0, "reason": f"The {label} product is not available in the current focus."}
        if re.search(r"\blast\b", lowered):
            return self._resolved(products[-1], 0.95, "Matched last product reference.")

        priced_products = [p for p in products if self._to_price(p.get("price")) is not None]
        if priced_products and re.search(r"\b(cheapest|cheaper|lowest price|least expensive)\b", lowered):
            return self._resolved(min(priced_products, key=lambda p: self._to_price(p.get("price")) or 0), 0.94, "Matched lowest-price reference.")
        if priced_products and re.search(r"\b(expensive|priciest|costliest|highest price)\b", lowered):
            return self._resolved(max(priced_products, key=lambda p: self._to_price(p.get("price")) or 0), 0.92, "Matched highest-price reference.")

        title_match = self._find_focus_by_title(lowered)
        if title_match:
            return self._resolved(title_match, 0.88, "Matched product title from active focus.")

        if re.search(r"\b(it|this|that|this product|that product|add to cart|do it|yes|ok|okay)\b", lowered):
            return self._resolved(products[0], 0.82, "Matched active top product reference.")

        return {"status": "ambiguous", "confidence": 0.0, "reason": "Reference did not uniquely match a product."}

    def _resolved(self, product: Dict[str, Any], confidence: float, reason: str) -> Dict[str, Any]:
        return {
            "status": "resolved",
            "confidence": confidence,
            "reason": reason,
            "product": product,
            "variant_id": product.get("variant_id") or product.get("id"),
            "product_name": product.get("name") or product.get("title"),
        }

    def _build_reference_clarification(self, resolved: Dict[str, Any]) -> str:
        products = self._focus_products()[:5]
        if not products:
            return "Which product should I add to your cart? Please mention the product name or ask me to show options again."
        options = []
        for idx, product in enumerate(products, start=1):
            name = product.get("name") or product.get("title") or f"Product {idx}"
            price = product.get("price")
            currency = product.get("currency") or ""
            price_text = f" ({currency} {self._display_price(price)})" if price not in (None, "") else ""
            options.append(f"{idx}. {name}{price_text}")
        return "Which product should I add to your cart?\n" + "\n".join(options)

    def _get_proactive_catalog_search(self) -> Optional[Dict[str, Any]]:
        """Search first for product-intent queries so commerce answers are grounded."""
        if self.tools.get("search_catalog"):
            tool_name = "search_catalog"
        elif self.tools.get("search_shop_catalog"):
            tool_name = "search_shop_catalog"
        else:
            return None

        last_user_msg = self._get_last_user_message()
        if not last_user_msg:
            return None

        lowered = last_user_msg.lower()
        cart_only_terms = {"cart", "checkout", "remove", "delete", "quantity", "order status", "my order"}
        if any(term in lowered for term in cart_only_terms):
            return None

        product_terms = {
            "product", "products", "recommend", "show", "find", "search", "price",
            "prices", "cost", "available", "stock", "in stock", "buy", "add",
            "pendant", "bracelet", "bangle", "earring", "necklace", "ring",
            "dress", "shirt", "top", "bottom", "jewelry", "jewellery",
        }
        if not any(term in lowered for term in product_terms):
            return None

        constraints = self._extract_shopping_constraints(last_user_msg)
        query = self._build_search_query(last_user_msg, constraints)
        self.last_user_query = last_user_msg
        self.last_search_query = query
        self.last_constraints = constraints

        return {
            "tool_name": tool_name,
            "tool_input": {
                "query": query,
                "pagination": {"limit": 20},
                "context": {
                    "original_query": last_user_msg,
                    "constraints": constraints,
                },
                "signals": {
                    "source": "nova_shopify_agent",
                    "preserve_full_intent": True,
                },
            },
        }

    def _extract_shopping_constraints(self, query: str) -> Dict[str, Any]:
        lowered = query.lower()
        constraints: Dict[str, Any] = {
            "product_type": None,
            "attributes": [],
            "occasion": None,
            "budget": None,
            "preferences": [],
            "negative_constraints": [],
            "recipient_context": None,
        }

        product_types = ["earrings", "earring", "necklace", "ring", "bracelet", "bangle", "pendant", "dress", "shirt", "top", "bottom", "jewelry", "jewellery"]
        for term in product_types:
            if term in lowered:
                constraints["product_type"] = term
                break

        attribute_terms = ["heart", "drop", "wedding", "bridal", "lightweight", "simple", "minimal", "statement", "gold", "silver", "pearl", "diamond", "floral", "daily", "party", "office", "gift"]
        for term in attribute_terms:
            if term in lowered:
                if term in {"wedding", "bridal", "party", "office", "daily"} and not constraints["occasion"]:
                    constraints["occasion"] = term
                else:
                    constraints["attributes"].append(term)

        pref_patterns = {
            "lightweight": r"\blight\s*weight|lightweight\b",
            "not flashy": r"\bnot\s+(too\s+)?flashy\b|\bsubtle\b",
            "budget friendly": r"\bbudget\b|\baffordable\b",
        }
        for label, pattern in pref_patterns.items():
            if re.search(pattern, lowered):
                constraints["preferences"].append(label)

        for neg in re.findall(r"\b(?:not|no|avoid|without)\s+([a-z0-9 -]{2,30})", lowered):
            cleaned = re.sub(r"\b(for|with|and|or|under|below|above|over)\b.*$", "", neg).strip()
            if cleaned:
                constraints["negative_constraints"].append(cleaned)

        budget_match = re.search(r"(?:under|below|less than|upto|up to|within)\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.\d+)?)", lowered)
        if budget_match:
            constraints["budget"] = {
                "operator": "max",
                "amount": float(budget_match.group(1).replace(",", "")),
                "currency": "INR" if "₹" in lowered or "inr" in lowered or "rs" in lowered else None,
            }

        recipient_match = re.search(r"\b(?:for|gift for)\s+(wife|husband|mother|mom|sister|friend|girlfriend|boyfriend|bride|wedding gift)\b", lowered)
        if recipient_match:
            constraints["recipient_context"] = recipient_match.group(1)

        constraints["attributes"] = sorted(set(constraints["attributes"]))
        constraints["preferences"] = sorted(set(constraints["preferences"]))
        constraints["negative_constraints"] = sorted(set(constraints["negative_constraints"]))
        return constraints

    def _build_search_query(self, query: str, constraints: Dict[str, Any]) -> str:
        lowered = query.lower()
        cleaned = re.sub(
            r"\b(can you|could you|would you|do you have|show me|find me|search for|look for|give me|please show|please find|recommend|show|find|search|give|please|from the store|include prices?|products?|product|items?|some|any|can|could|would|you|me|for|with|and|or)\b",
            " ",
            lowered,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[^a-z0-9\s-]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        important_terms = [constraints.get("product_type") or ""]
        important_terms.extend(constraints.get("attributes") or [])
        if constraints.get("occasion"):
            important_terms.append(constraints["occasion"])
        merged = " ".join([cleaned, *important_terms])
        tokens = []
        for token in merged.split():
            if token not in tokens:
                tokens.append(token)
        return " ".join(tokens).strip() or query

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
                            common = {w for w in common if w not in {"the", "a", "an", "to", "cart", "product", "item", "yes", "ok", "this", "that", "it"}}
                            return len(common) > 0

                        # 1. Check last_searched FIRST (priority for "yes" / confirmation / pronouns)
                        # For affirmative intents like "yes", "ok", "do it", try to find what the assistant just said
                        assistant_last_msg = ""
                        for msg in reversed(self.conversation):
                            if msg["role"] == "assistant":
                                assistant_last_msg = str(msg.get("content", "")).lower()
                                break

                        for title, gid in self.last_searched.items():
                            title_lower = title.lower()
                            is_affir = bool(item_str in ("yes", "ok", "it", "this", "that", "add it", "add this", "add that", "this product", "add this product", "do it"))
                            is_ment = bool(str(title_lower) in str(assistant_last_msg))
                            if is_match(title) or (is_affir and is_ment):
                                existing_id = gid
                                logger.info("shopify_resolved_from_last_searched_mention", title=title, gid=gid)
                                break
                        
                        # 2. Case where user says "yes" but we didn't match the title in the assistant's text
                        # (Maybe the assistant used a generic name). Fallback to the first item in last_searched.
                        if not existing_id and item_str in ["yes", "ok", "it", "this", "that", "add it", "add this", "add that", "this product", "add this product", "do it"]:
                             focus = self._resolve_product_reference(item_str)
                             if focus.get("status") == "resolved":
                                 existing_id = focus.get("variant_id")
                                 logger.info("shopify_resolved_from_focus_fallback", product=focus.get("product_name"))

                        # 3. Check broad captured_ids if still no ID
                        if not existing_id:
                            for title, gid in self.captured_ids.items():
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
                self.cart_id = str(new_id)
            
            # Capture checkout URL
            new_url = cart.get("checkout_url") or cart.get("checkoutUrl")
            if new_url:
                self.checkout_url = str(new_url)
            
            # Store full lines for prompt injection
            self.cart_lines = cart.get("lines") or cart.get("line_items") or []

        # Capture Product/Variant IDs for future reference
        products = metadata.get("products", [])
        
        # Reset last_searched if this was a new search
        if tool_name in ("search_shop_catalog", "search_catalog"):
            self.last_searched = {}
            ranked_products = self._rerank_products(products)
            self.active_product_focus = ranked_products[:10]
            self.product_reference_map = self._build_product_reference_map(self.active_product_focus)
            self.rerank_results = [
                {
                    "rank": product.get("rank"),
                    "name": product.get("name"),
                    "variant_id": product.get("variant_id"),
                    "match_score": product.get("match_score"),
                    "matched_constraints": product.get("matched_constraints", []),
                    "missing_constraints": product.get("missing_constraints", []),
                    "reason": product.get("reason"),
                }
                for product in ranked_products[:10]
            ]
            metadata["products"] = ranked_products[:5]
            metadata["active_product_focus"] = self.active_product_focus
            metadata["product_reference_map"] = self.product_reference_map
            metadata["commerce_intent"] = self.last_constraints
            metadata["original_query"] = self.last_user_query
            metadata["search_query"] = self.last_search_query
            metadata["rerank_results"] = self.rerank_results
            products = metadata.get("products", [])

        for p in products:
            if not isinstance(p, dict): continue
            name = str(p.get("name") or p.get("title") or "").lower()
            v_id = p.get("variant_id") or p.get("id")
            if name and v_id:
                gid = str(v_id)
                self.captured_ids[name] = gid
                if tool_name in ("search_shop_catalog", "search_catalog"):
                    self.last_searched[name] = gid

    def _normalize_focus_product(self, product: Dict[str, Any], original_rank: int) -> Dict[str, Any]:
        name = str(product.get("name") or product.get("title") or product.get("sku") or f"Product {original_rank}")
        variant_id = str(product.get("variant_id") or product.get("id") or product.get("product_id") or "")
        normalized = dict(product)
        normalized.update({
            "rank": original_rank,
            "original_rank": original_rank,
            "name": name,
            "title": product.get("title") or name,
            "variant_id": variant_id,
            "id": product.get("id") or variant_id,
            "price": product.get("price"),
            "currency": product.get("currency"),
            "sku": product.get("sku"),
            "product_url": product.get("product_url") or product.get("url"),
            "image_url": product.get("image_url") or product.get("image"),
        })
        return normalized

    def _rerank_products(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(products, list):
            return []
        constraints = self.last_constraints or {}
        original_query_tokens = self._tokens(self.last_user_query or "")
        ranked: List[Dict[str, Any]] = []
        max_budget = (constraints.get("budget") or {}).get("amount") if isinstance(constraints.get("budget"), dict) else None
        desired_terms = set(constraints.get("attributes") or [])
        if constraints.get("product_type"):
            desired_terms.add(str(constraints["product_type"]))
        if constraints.get("occasion"):
            desired_terms.add(str(constraints["occasion"]))
        desired_terms.update(constraints.get("preferences") or [])

        for idx, raw_product in enumerate(products, start=1):
            if not isinstance(raw_product, dict):
                continue
            product = self._normalize_focus_product(raw_product, idx)
            product_text = " ".join(
                str(product.get(key) or "")
                for key in ("name", "title", "category", "sku", "description")
            ).lower()
            product_tokens = self._tokens(product_text)
            matched_terms = sorted(term for term in desired_terms if term and term.lower() in product_text)
            token_overlap = len(original_query_tokens.intersection(product_tokens))
            score = max(0.0, 1.0 - (idx - 1) * 0.03) + token_overlap * 0.08 + len(matched_terms) * 0.18
            missing_terms = sorted(term for term in desired_terms if term and term not in matched_terms)

            price = self._to_price(product.get("price"))
            if max_budget is not None and price is not None:
                budget = float(max_budget)
                comparable_price = price / 100 if budget and price > budget * 10 else price
                if comparable_price <= budget:
                    score += 0.35
                    matched_terms.append(f"under budget {max_budget:g}")
                else:
                    score -= 0.45
                    missing_terms.append(f"over budget {max_budget:g}")

            for negative in constraints.get("negative_constraints") or []:
                if negative and str(negative).lower() in product_text:
                    score -= 0.5
                    missing_terms.append(f"avoid {negative}")

            product["match_score"] = round(score, 3)
            product["matched_constraints"] = sorted(set(matched_terms))
            product["missing_constraints"] = sorted(set(missing_terms))[:5]
            if product["matched_constraints"]:
                product["reason"] = f"Matches {', '.join(product['matched_constraints'][:3])}."
            else:
                product["reason"] = "Relevant Shopify catalog result."
            ranked.append(product)

        ranked.sort(key=lambda p: (p.get("match_score") or 0), reverse=True)
        for idx, product in enumerate(ranked, start=1):
            product["rank"] = idx
        return ranked

    def _build_product_reference_map(self, products: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        reference_map: Dict[str, Dict[str, Any]] = {}
        for product in products:
            keys = {
                str(product.get("rank") or ""),
                str(product.get("name") or "").lower(),
                str(product.get("title") or "").lower(),
                str(product.get("sku") or "").lower(),
                str(product.get("variant_id") or ""),
                str(product.get("id") or ""),
            }
            for key in keys:
                if key:
                    reference_map[key] = product
        return reference_map

    def _build_reasoning_prompt(self) -> str:
        """Construct the few-shot prompting context with mandatory next-step hints for adds."""
        text = ""
        # Performance optimization: Keep last 8 messages for focus
        context_window = self.conversation[-8:]
        
        # Detect if we should chain an add
        last_msg = context_window[-1] if context_window else None
        is_tool_after_search = False
        if last_msg and last_msg["role"] == "tool" and last_msg.get("name") in ("search_shop_catalog", "search_catalog"):
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
            elif role == "system":
                text += f"System: {content}\n"
        
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
        """Combine base system prompt with Shopify-specific rules."""
        base_prompt = self.system_prompt or "You are a helpful AI assistant."
        
        # 1. Format the ACTIVE focus (most recent search)
        active_focus_ctx = ""
        if self.active_product_focus:
            lines = ["\n### 🎯 ACTIVE PRODUCT FOCUS (MOST RECENT RERANKED RESULTS):\n"]
            for product in self.active_product_focus[:5]:
                name = product.get("name") or product.get("title")
                gid = product.get("variant_id") or product.get("id")
                price = self._display_price(product.get("price"))
                score = product.get("match_score")
                lines.append(f"- #{product.get('rank')}: {name} (ID: {gid}, price: {price}, match: {score})\n")
            lines.append("--> If the user says 'this', 'it', 'that product', or gives an ordinal like 'second one', resolve against THIS ordered list.\n")
            active_focus_ctx = "".join(lines)
        elif self.last_searched:
            lines = ["\n### 🎯 ACTIVE PRODUCT FOCUS (MOST RECENT SEARCH):\n"]
            for title, gid in self.last_searched.items():
                lines.append(f"- {title} (ID: {gid})\n")
            lines.append("--> If the user says 'yes', 'add it', or 'ok', they mean THIS product.\n")
            active_focus_ctx = "".join(lines)

        # 2. Format the broader session history
        history_products_ctx = ""
        if self.captured_ids:
            lines = ["\n### 📚 SESSION PRODUCT HISTORY:\n"]
            all_recent = list(self.captured_ids.items())
            num_total = len(all_recent)
            for i in range(max(0, num_total - 10), num_total):
                name, gid = all_recent[i]
                if name not in self.last_searched:
                    lines.append(f"- {name} (ID: {gid})\n")
            history_products_ctx = "".join(lines)

        shopify_rules = f"""
You are a Shopify assistant. You help users find products and manage their shopping cart.
Current Cart ID: {self.cart_id or "None"}
{f"Checkout URL: {self.checkout_url}" if self.checkout_url else ""}
{self._get_cart_lines_context()}

Runtime Context:
{json.dumps(self.prompt_runtime_context, indent=2, sort_keys=True, default=str) if self.prompt_runtime_context else "None"}

Commerce Intent:
{json.dumps({"original_query": self.last_user_query, "search_query": self.last_search_query, "constraints": self.last_constraints}, indent=2, sort_keys=True, default=str)}

### STRICT TOOL-FIRST RULE
**NEVER** return conversational text like "I will add that now" or "One moment please" if you haven't invoked the JSON tool call yet.
If you are adding an item, the VERY FIRST THING YOU DO is return the JSON. Talk only AFTER the tool has succeeded.

### JSON INTERACTION SCHEMA
When you need to call a tool, you MUST return ONLY a JSON object with these EXACT keys:
{{
  "tool_name": "name_of_the_tool",
  "tool_input": {{ "key": "value" }}
}}

Examples:
- To search: {{"tool_name": "search_catalog", "tool_input": {{"query": "socks", "pagination": {{"limit": 5}}}}}}
- To add to cart: {{"tool_name": "update_cart", "tool_input": {{"add_items": [{{"product_variant_id": "gid://shopify/ProductVariant/123", "quantity": 1}}]}}}}
- To remove/decrement from cart: {{"tool_name": "update_cart", "tool_input": {{"remove_items": ["gid://shopify/CartLine/123"], "update_items": [{{"id": "gid://shopify/CartLine/456", "quantity": 1}}]}}}}

### SEQUENCING EXAMPLES
Example 1 (Direct Add Request):
User: "Add white socks"
Thought: {{"tool_name": "search_catalog", "tool_input": {{"query": "white socks", "pagination": {{"limit": 5}}}}}}
Tool Result: [{{"title": "White Socks", "variant_id": "gid://..."}}]
Thought: {{"tool_name": "update_cart", "tool_input": {{"add_items": [{{"product_variant_id": "gid://...", "quantity": 1}}]}}}}
Tool Result: {{"success": true}}
Thought: "I've added the white socks to your cart!"

Example 2 (Removal Request):
User: "Remove one white sock"
Thought: {{"tool_name": "get_cart", "tool_input": {{}}}}
Tool Result: {{"success": true, "metadata": {{"cart": {{"lines": [{{"id": "line_123", "quantity": 2, "merchandise": {{"title": "White Socks"}}}}]}}}}}}
Thought: {{"tool_name": "update_cart", "tool_input": {{"update_items": [{{"id": "line_123", "quantity": 1}}]}}}}
Tool Result: {{"success": true}}
Thought: "I've removed one pair of white socks. You now have 1 pair remaining."

## CONTEXT & FOCUS
{active_focus_ctx}{history_products_ctx}

### MANDATORY EXECUTION RULES
1. **YES / CONFIRMATION HANDLING**: If the user says "yes" or "ok" after a search, use the ID from 🎯 ACTIVE PRODUCT FOCUS. Return the `update_cart` JSON immediately.
2. **IMMEDIATE CHAINING**: If user says "add [product]" or "buy [product]":
   - Search if needed, then IMMEDIATELY call `update_cart` in the next iteration. 
   - NEVER ask "Would you like me to add it?" if they already ordered you to add.
   - **CRITICAL**: If the user only said "[product]" (e.g. "socks") without "add" or "buy", ONLY search. DO NOT add it yet.
3. **CART VERIFICATION**: Always `get_cart` before questions about your current cart items.
4. **REMOVAL / DECREMENT LOGIC**: If the user wants to "remove" or "delete" an item:
   - You MUST first call `get_cart` to see the current lines and their quantities.
   - If current quantity is 1: Use `update_cart` with `remove_items`: ["line_id"].
   - If current quantity > 1: Use `update_cart` with `update_items`: [{{"id": "line_id", "quantity": new_qty}}].
5. **CHECKOUT LINK**: Provide a Checkout URL only after `update_cart` or `get_cart` succeeds and a checkout URL is available. Do not mention checkout URLs for product search/recommendation answers.

### OUTPUT FORMAT
- To call a tool: Return ONLY the JSON object. No chat.
- Final Answer: Return ONLY natural language. No JSON.
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
