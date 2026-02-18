# to run this file use: python -m llm.providers.shopify.shopify_orchestrator
#from S G:\fractics\agentbuilder\packages\llm\src>
import asyncio
import json
import re
from typing import List, Dict, Any

from llm.providers.shopify.shopify_config import get_openai_provider
from llm.providers.shopify.shopify_mcp_client import ShopifyMCPClient


AVAILABLE_TOOLS = [
    "search_products_tool",
    "get_product_tool",
    "search_orders_tool",
    "get_order_tool",
    "create_cart_tool",
    "add_to_cart_tool",
    "get_cart_tool",
    "get_shop_info_tool",
    "remove_from_cart_tool",
    "update_cart_quantity_tool",
    ]


try:
    from agent_runtime.orchestrator import AgentResult
except ImportError:
    class AgentResult:
        def __init__(self, answer: str, metadata: dict):
            self.answer = answer
            self.metadata = metadata

class ShopifyAgent:

    def __init__(self, shop_url: str = None, storefront_token: str = None, admin_token: str = None, cart_id: str = None, system_prompt: str = None):
        self.provider = get_openai_provider()
        self.mcp = ShopifyMCPClient(
            shop_url=shop_url,
            storefront_token=storefront_token,
            admin_token=admin_token,
            cart_id=cart_id
        )
        self.conversation: List[Dict[str, Any]] = []
        self.cart_id = cart_id
        self.system_prompt = system_prompt

    async def run(self, query: str = None, chat_history: List[Dict] = None, context: Dict = None, **kwargs):
        """Orchestrator interface compatibility."""
        # Ensure connection (idempotent)
        await self.mcp.connect()

        # Only reset conversation if we're starting fresh (no existing state)
        # This preserves tool results between requests
        if not hasattr(self, 'conversation') or self.conversation is None:
            self.conversation = []

        # Build conversation from history if provided
        if chat_history:
             # Convert generic roles to Shopify agent roles
            for msg in chat_history:
                 # Include user, assistant, AND tool messages
                if msg.get("role") not in ["user", "assistant", "tool"]:
                    continue
                
                conv_msg = {
                    "role": msg["role"],
                    "content": msg["content"]
                }
                
                # Tool messages need the 'name' field
                if msg.get("role") == "tool" and msg.get("name"):
                    conv_msg["name"] = msg["name"]
                    
                self.conversation.append(conv_msg)
        
        # If context is provided (new memory system), try to extract recent messages
        elif context and "memory" in context:
             recent_messages = context["memory"].get("recent_messages", [])
             for msg in recent_messages:
                  # Handle Message object or dict
                  role = msg.role.value if hasattr(msg, "role") else msg.get("role")
                  content = msg.content if hasattr(msg, "content") else msg.get("content")
                  
                  if role == "user":
                       self.conversation.append({"role": "user", "content": content})
                  elif role == "assistant":
                       self.conversation.append({"role": "assistant", "content": content})
                  elif role == "tool":
                       name = msg.name if hasattr(msg, "name") else msg.get("name")
                       self.conversation.append({"role": "tool", "name": name, "content": content})


        # Add the current user query if it's not already the last message
        if query:
            # Check if last message is same as query (deduplication)
            if not self.conversation or self.conversation[-1].get("content") != query or self.conversation[-1].get("role") != "user":
                self.conversation.append({
                    "role": "user",
                    "content": query
                })
        
        # Run agent loop in headless mode
        response_text, tool_results = await self._agent_loop(headless=True)
        
        # Return standard AgentResult
        return AgentResult(
            answer=response_text,
            metadata={
                "steps_executed": 1, 
                "tool_results": tool_results,
                "plan": {"goal": query},
                "cart_id": self.cart_id  # ✅ return cart_id so it can be persisted
            }
        )

    async def chat(self):
        print("🛍 Shopify AI Agent Ready (type 'exit' to quit)\n")

        # ✅ CONNECT ONCE
        await self.mcp.connect()

        try:
            while True:
                user_input = input("You: ")

                if user_input.lower() in ["exit", "quit"]:
                    break

                self.conversation.append({
                    "role": "user",
                    "content": user_input
                })

                await self._agent_loop()

        finally:
            # ✅ CLEAN SHUTDOWN (fixes your async generator crash)
            await self.mcp.disconnect()

    async def _agent_loop(self, headless: bool = False):
        tool_results_map = {}
        
        while True:
            # Ask LLM for next message
            response = await self.provider.generate(
                prompt=self._build_prompt(),
                system_prompt=self._system_prompt()
            )
            message = response.content.strip()

            # Parse tool call from message
            tool_call = self._parse_tool_call(message)

            if tool_call:
                tool_name = tool_call["tool_name"]
                tool_input = tool_call["tool_input"] or {}

                # Auto-inject cartId if missing
                if self.cart_id and isinstance(tool_input, dict):
                    if "cartId" not in tool_input or not tool_input["cartId"]:  # ✅ Inject if missing OR empty
                        # Clean cart_id if it has leading Junk (from some older logs)
                        clean_id = self.cart_id.lstrip("/")
                        tool_input["cartId"] = clean_id
                        if not headless:
                            print(f"🔧 Injected Cart ID: {clean_id}")
                        else:
                            print(f"🔧 [Headless] Injected Cart ID: {self.cart_id}")

                if not headless:
                    print(f"\n🔧 Calling Tool → {tool_name}")
                    print(f"📦 Input → {tool_input}")
                else:
                    # Log in headless mode too for debugging
                    print(f"🔧 [Headless] Tool: {tool_name} | Input: {tool_input}")

                # --- Special handling for adding to cart ---
                if tool_name == "add_to_cart_tool":
                    # Ensure cart exists
                    if not self.cart_id:
                        cart = await self.mcp.call_tool("create_cart_tool", {})
                        #self.cart_id = cart.get("id", "").split("?")[0]
                        self.cart_id = cart.get("id", "")  # Keep the full ID including the key
                        if not headless:
                            print(f"🛒 Created new cart → {self.cart_id}")

                    # Ensure variant ID exists
                    if not tool_input.get("merchandiseId") and tool_input.get("product"):
                        product = tool_input["product"]
                        tool_input["merchandiseId"] = product["variants"][0]["id"]

                    # Ensure cartId is passed
                    tool_input["cartId"] = self.cart_id

                    # Prompt user for quantity if missing (handle headless)
                    if "quantity" not in tool_input or not tool_input["quantity"]:
                        if headless:
                             tool_input["quantity"] = 1 # Default for headless
                        else:
                            title = tool_input.get("product", {}).get("title", tool_input.get("merchandiseId", "item"))
                            qty = input(f"How many of '{title}' would you like to add? ")
                            try:
                                tool_input["quantity"] = int(qty)
                            except ValueError:
                                tool_input["quantity"] = 1

                # Call the tool
                try:
                    if tool_name == "get_cart_tool" and not tool_input.get("cartId"):
                        result = {"lines": {"edges": []}, "id": "", "checkoutUrl": ""}
                    else:
                        result = await self.mcp.call_tool(tool_name, tool_input)
                except Exception as e:
                    # Gracefully handle tool errors allowing LLM to recover
                    result = {"error": str(e), "success": False}
                    if not headless:
                        print(f"❌ Tool Error: {str(e)}")

                # Capture cart or add_to_cart state
                is_success = True
                if isinstance(result, dict) and result.get("success") is False:
                    is_success = False
                
                if is_success:
                    self._capture_state(tool_name, result)

                tool_results_map[tool_name] = result

                if tool_name == "get_cart_tool":
                    lines = result.get("lines", {}).get("edges", [])
                    if lines:
                        cart_summary = "\n🛒 Your cart contains:\n"
                        for line in lines:
                            item = line["node"]
                            merchandise = item.get("merchandise", {})
                            product_title = merchandise.get("product", {}).get("title") or merchandise.get("title") or "Item"
                            qty = item.get("quantity", 1)
                            cart_summary += f"- {product_title}\n"
                        
                        if not headless:
                            print(cart_summary)
                    else:
                        if not headless:
                            print("🛒 Your cart is currently empty.")

                # Store tool output in conversation
                self.conversation.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(result)
                })
                
                continue  # Continue loop for next LLM reasoning

            else:
                # Regular assistant output
                if not headless:
                    print(f"\n {message}\n")
                
                self.conversation.append({
                    "role": "assistant",
                    "content": message
                })
                
                if headless:
                    return message, tool_results_map
                return




    def _build_prompt(self) -> str:
        text = ""

        for msg in self.conversation:
            if msg["role"] == "user":
                text += f"User: {msg['content']}\n"
            elif msg["role"] == "assistant":
                text += f"Assistant: {msg['content']}\n"
            elif msg["role"] == "tool":
                text += f"Tool ({msg['name']}): {msg['content']}\n"

        text += "\nAssistant:"
        return text

    def _system_prompt(self) -> str:
        tools_list = "\n".join([f"- {tool}" for tool in AVAILABLE_TOOLS])

        base_prompt = self.system_prompt or "You are a Shopify store shopping assistant."

        return f"""
    {base_prompt}
    
    Current Cart ID: {self.cart_id or "None"}
    
    ⚠️ MANDATORY TOOL USAGE - READ THIS FIRST ⚠️
    You MUST call the appropriate tool BEFORE responding in these situations:
    1. User mentions a product name (e.g., "socks", "pants") → MUST call search_products_tool and SHOW details. DO NOT add to cart unless explicitly asked.
    2. User says "add [item] to cart" or "buy [item]" → MUST call search_products_tool then add_to_cart_tool
    3. User says "cart details" or "show cart" → MUST call get_cart_tool
    4. User says "remove [item]" or "remove all" → MUST call get_cart_tool to get lineIds, then remove_from_cart_tool
    
    DO NOT respond with text like "I have added..." or "I have removed..." UNLESS you just called the tool and saw the result.
    If you respond without calling a tool first, you are HALLUCINATING and FAILING your task.

     You are a Shopify store shopping assistant.

    IMPORTANT:
    You do NOT have access to product knowledge unless it is retrieved using tools.
    You must NEVER answer product-related questions from general knowledge.

    You MUST call tools whenever:
    - A product name is mentioned
    - A user asks about a product
    - A user wants to search for items
    - A user wants to buy something
    - A user says "add to cart"
    - A user asks for product details

    You can call tools by returning STRICT JSON in this format ONLY:

    {{
    "tool_name": "one of {AVAILABLE_TOOLS}",
    "tool_input": {{ JSON arguments }}
    }}

    Available tools:
    {tools_list}

    STRICT RULES:
    - If calling a tool → return ONLY valid JSON.
    - Do NOT include explanation text when calling a tool.
    - Never mix text and JSON.
    - If product info is needed → ALWAYS call search_products_tool first.
    - If user wants to buy:
        1. search_products_tool
        2. create_cart_tool (if no cart exists)
        3. add_to_cart_tool using merchandiseId (variant ID)
    - If user wants to remove items:
        1. get_cart_tool (to find lineIds)
        2. remove_from_cart_tool
    - If user wants to update quantity:
        1. get_cart_tool (to find lineId)
        2. update_cart_quantity_tool (quantity=0 removes the item)
    - If no products are found, inform the user politely.
    - To view the cart → always use get_cart_tool
    - To view past orders → use search_orders_tool or get_order_tool


    Behavior Guidelines:
    - You are connected to a live Shopify store.
    - All product knowledge must come from tool results.
    - Do not hallucinate products.
    - When asked about a product, provide key details (price, variants) first.
    - Only add items to the cart if the user explicitly asks to "add to cart" or "buy".
    """



    def _parse_tool_call(self, message: str):
        """
        Extract and parse tool call JSON from LLM response.
        Handles direct JSON, markdown blocks, and embedded JSON (including nested).
        """
        # 1. Try parsing the whole message as JSON
        clean_msg = message.strip()
        try:
            parsed = json.loads(clean_msg)
            if "tool_name" in parsed and "tool_input" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

        # 2. Try finding JSON in markdown blocks
        # First try non-greedy for simple blocks
        match = re.search(r"```json\s*({.*?})\s*```", message, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if "tool_name" in parsed and "tool_input" in parsed:
                    return parsed
            except json.JSONDecodeError:
                # If non-greedy failed, it might be nested. Try greedy within the block.
                block_match = re.search(r"```json\s*({.*})\s*```", message, re.DOTALL)
                if block_match:
                    try:
                        parsed = json.loads(block_match.group(1))
                        if "tool_name" in parsed and "tool_input" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        pass

        # 3. Try finding any JSON-like structure
        # Find all starts of JSON objects
        for start_match in re.finditer(r"{", message):
            start_pos = start_match.start()
            # Find all ends of JSON objects from the end of the string
            for end_match in re.finditer(r"}", message[start_pos:]):
                end_pos = start_pos + end_match.end()
                try:
                    candidate = message[start_pos:end_pos]
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "tool_name" in parsed and "tool_input" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue

        return None

    def _capture_state(self, tool_name: str, result: dict):
        """Monitor tool results to capture and persist state like Cart IDs."""
        if not isinstance(result, dict):
            return

        # List of tools that return a cart object (Storefront API)
        cart_tools = [
            "create_cart_tool",
            "add_to_cart_tool",
            "get_cart_tool",
            "remove_from_cart_tool",
            "update_cart_quantity_tool"
        ]

        if tool_name in cart_tools:
            try:
                # Storefront API cart objects have an 'id' and 'checkoutUrl'
                if result.get("id"):
                    # Clean the ID (strip leading slashes or formatting junk)
                    self.cart_id = result["id"].lstrip("/")
                    print(f"🛒 Syncing Cart ID → {self.cart_id}")
                
                if result.get("checkoutUrl"):
                    # Optional: log for visibility but usually we want to keep it in the session
                    # print(f"🔗 Checkout URL available")
                    pass
            except Exception as e:
                print(f"Failed to capture cart state from {tool_name}: {e}")



