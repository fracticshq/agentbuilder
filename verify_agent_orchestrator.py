
import asyncio
import os
import sys
sys.path.append(os.path.abspath("apps/api"))

from dotenv import load_dotenv
load_dotenv("apps/api/.env")

from app.config import Settings
from app.services.message_service import MessageService
from agent_runtime.orchestrator import AgentResult


async def main():
    print("🚀 Starting Agent Orchestrator Verification...")
    
    # 1. Setup
    load_dotenv()
    # Mock settings with dummy keys since we are mocking the LLM
    class MockSettings(Settings):
        OPENAI_API_KEY: str = "sk-dummy-key"
        MONGO_URI: str = "mongodb://localhost:27017"
        DEFAULT_LLM_PROVIDER: str = "openai"
        OPENAI_MODEL: str = "gpt-4o"

    settings = MockSettings()
    

    # 2. Initialize Service with Mocks
    print("⚙️ Initializing MessageService with Mock LLM...")
    
    # Mock LLM Provider
    from llm.providers.base import LLMProvider, LLMResponse
    
    class MockLLM(LLMProvider):
        async def generate(self, prompt: str, **kwargs) -> LLMResponse:
            print(f"   [MockLLM] Received prompt length: {len(prompt)}")
            
            # If prompt looks like a planning prompt
            if "You are an expert Planning Agent" in prompt or "Plan:" in prompt:
                print("   [MockLLM] Returning Mock Plan")
                return LLMResponse(content='''
                ```json
                {
                    "goal": "Find warranty info",
                    "steps": [
                        {
                            "id": 1,
                            "thought": "I need to look up warranty policies.",
                            "tool_name": "knowledge_search",
                            "tool_input": {"query": "warranty policy for faucets"}
                        }
                    ]
                }
                ```
                ''')
            else:
                print("   [MockLLM] Returning Final Answer")
                return LLMResponse(content="The warranty for faucets is 10 years.")

        async def stream(self, prompt: str, **kwargs):
            yield "The warranty is 10 years."

        async def health_check(self) -> bool:
            return True

    try:
        service = MessageService(settings=settings, brand_id="test-brand", agent_id="test-agent")
        
        # Inject Mock LLM
        service.llm_provider = MockLLM(config=None)
        # Re-initialize Orchestrator with Mock LLM
        service.orchestrator.llm = service.llm_provider
        
        if not service.orchestrator:
            print("❌ Orchestrator failed to initialize in MessageService")
            return
        
        print(f"✅ Orchestrator Initialized: {service.orchestrator}")
        print(f"   - Tools Registered: {[t.name for t in service.tool_registry.list_tools()]}")

    except Exception as e:
        print(f"❌ Initialization Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Test Run (Dry Run / Planning only test if we don't want to consume too many tokens)
    # We will try a simple query
    query = "What is the warranty policy for faucets?"
    print(f"\n🧪 Testing Query: '{query}'")
    
    try:
        # We invoke the orchestrator directly to see the log output
        result: AgentResult = await service.orchestrator.run(query)
        
        print("\n📝 Result Received:")
        print(f"   Success: {result.success}")
        print(f"   Answer: {result.answer[:100]}...")
        print(f"   Metadata: {result.metadata.keys()}")
        
        if result.success:
            print("\n✅ Verification PASSED")
        else:
            print("\n❌ Verification FAILED (Success=False)")
            
    except Exception as e:
        print(f"\n❌ Execution Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
