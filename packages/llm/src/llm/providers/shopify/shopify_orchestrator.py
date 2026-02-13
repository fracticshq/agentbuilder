# to run this file use: python -m llm.providers.shopify.shopify_orchestrator
#from S G:\fractics\agentbuilder\packages\llm\src>
import asyncio
import json
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

    "get_shop_info_tool",
    ]


class ShopifyAgent:

    def __init__(self):
        self.provider = get_openai_provider()
        self.mcp = ShopifyMCPClient()
        self.conversation: List[Dict[str, Any]] = []
        self.cart_id = None

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

    async def _agent_loop(self):
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
                # if self.cart_id and isinstance(tool_input, dict):
                #     if "cartId" in tool_input and not tool_input["cartId"]:
                #         tool_input["cartId"] = self.cart_id
                # Auto-inject cartId if missing
                if self.cart_id and isinstance(tool_input, dict):
                    if "cartId" not in tool_input or not tool_input["cartId"]:  # ✅ Inject if missing OR empty
                        tool_input["cartId"] = self.cart_id

                print(f"\n🔧 Calling Tool → {tool_name}")
                print(f"📦 Input → {tool_input}")

                # --- Special handling for adding to cart ---
                if tool_name == "add_to_cart_tool":
                    # Ensure cart exists
                    if not self.cart_id:
                        cart = await self.mcp.call_tool("create_cart_tool", {})
                        #self.cart_id = cart.get("id", "").split("?")[0]
                        self.cart_id = cart.get("id", "")  # Keep the full ID including the key
                        print(f"🛒 Created new cart → {self.cart_id}")

                    # Ensure variant ID exists
                    if not tool_input.get("merchandiseId") and tool_input.get("product"):
                        product = tool_input["product"]
                        tool_input["merchandiseId"] = product["variants"][0]["id"]

                    # Ensure cartId is passed
                    tool_input["cartId"] = self.cart_id

                    # Prompt user for quantity if missing
                    if "quantity" not in tool_input or not tool_input["quantity"]:
                        title = tool_input.get("product", {}).get("title", tool_input.get("merchandiseId", "item"))
                        qty = input(f"How many of '{title}' would you like to add? ")
                        try:
                            tool_input["quantity"] = int(qty)
                        except ValueError:
                            tool_input["quantity"] = 1


                # Call the tool
                result = await self.mcp.call_tool(tool_name, tool_input)

                # Capture cart or add_to_cart state
                self._capture_state(tool_name, result)

                if tool_name == "get_cart_tool":
                    lines = result.get("lines", {}).get("edges", [])
                    if lines:
                        print("\n🛒 Your cart contains:")
                        for line in lines:
                            item = line["node"]
                            merchandise = item.get("merchandise", {})
                            product_title = merchandise.get("product", {}).get("title") or merchandise.get("title") or "Item"
                            qty = item.get("quantity", 1)
                            print(f"- {product_title} x{qty}")
                    else:
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
                print(f"\n {message}\n")
                self.conversation.append({
                    "role": "assistant",
                    "content": message
                })
                break




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

        return f"""
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
    - If no products are found, inform the user politely.
    - To view the cart → always use get_cart_tool
    - To view past orders → use search_orders_tool or get_order_tool


    Behavior Guidelines:
    - You are connected to a live Shopify store.
    - All product knowledge must come from tool results.
    - Do not hallucinate products.
    - Be proactive and complete the shopping flow automatically.
    """



    def _parse_tool_call(self, message: str):
        try:
            parsed = json.loads(message)
            if "tool_name" in parsed and "tool_input" in parsed:
                return parsed
        except:
            return None
        return None

    def _capture_state(self, tool_name: str, result: dict):
        if tool_name == "create_cart_tool":
            try:
                cart_id = result["id"]
                self.cart_id = cart_id
                print(f"🛒 Stored Cart ID → {self.cart_id}")
                if result.get("checkoutUrl"):
                    print(f"🔗 Checkout → {result['checkoutUrl']}")
            except Exception as e:
                print(f"Failed to capture cart ID: {e}")

        # Also capture cart ID from add_to_cart responses
        if tool_name == "add_to_cart_tool" and isinstance(result, dict):
            if result.get("id"):
                self.cart_id = result["id"]
                print(f"🛒 Updated Cart ID → {self.cart_id}")
            if result.get("checkoutUrl"):
                print(f"🔗 Checkout → {result['checkoutUrl']}")



if __name__ == "__main__":
    asyncio.run(ShopifyAgent().chat())
