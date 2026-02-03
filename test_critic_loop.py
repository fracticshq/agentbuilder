#!/usr/bin/env python3
"""
Test SOTA Agentic Framework with Critic Loop
Tests: Plan -> Execute -> Critic Validation -> Retry/Synthesize
"""
import asyncio
import sys
import os
sys.path.append(os.path.abspath("packages/tools/src"))
sys.path.append(os.path.abspath("packages/agent_runtime/src"))
sys.path.append(os.path.abspath("packages/llm/src"))

from llm.providers.base import LLMProvider, LLMResponse
from tools.registry import ToolRegistry
from tools.types import BaseTool, ToolResult
from agent_runtime.orchestrator import Orchestrator

# Mock Critic (simplified ResponseValidator)
class MockCritic:
    """Simulates ResponseValidator for testing"""
    
    def __init__(self, should_fail_first=False):
        self.should_fail_first = should_fail_first
        self.call_count = 0
    
    async def validate_response(self, response, query_intent, catalog_products=None, catalog_dealers=None):
        self.call_count += 1
        
        # Mock validation result
        class ValidationResult:
            def __init__(self, is_valid, confidence, issues, sanitized_response):
                self.is_valid = is_valid
                self.confidence = confidence
                self.issues = issues
                self.sanitized_response = sanitized_response
        
        # First call fails if configured
        if self.should_fail_first and self.call_count == 1:
            print("   [MockCritic] ❌ REJECTING answer (first attempt)")
            return ValidationResult(
                is_valid=False,
                confidence=0.3,
                issues=["Contains unverified warranty term", "Missing citations"],
                sanitized_response=None  # Force retry
            )
        
        # Subsequent calls or normal mode passes
        print(f"   [MockCritic] ✅ APPROVING answer (attempt #{self.call_count})")
        return ValidationResult(
            is_valid=True,
            confidence=0.95,
            issues=[],
            sanitized_response=None
        )

# Mock LLM
class MockLLM(LLMProvider):
    def __init__(self):
        self.call_count = 0
        
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.call_count += 1
        
        # Planning prompt
        if "You are an expert Planning Agent" in prompt:
            print(f"   [MockLLM] Planning (call #{self.call_count})")
            return LLMResponse(content='''
            ```json
            {
                "goal": "Find warranty information",
                "steps": [
                    {
                        "id": 1,
                        "thought": "Search knowledge base for warranty policies",
                        "tool_name": "mock_search",
                        "tool_input": {"query": "warranty"}
                    }
                ]
            }
            ```
            ''')
        
        # Retry with feedback
        elif "previous answer had the following issues" in prompt:
            print(f"   [MockLLM] 🔄 Retry with Critic feedback (call #{self.call_count})")
            return LLMResponse(content="The warranty for faucets is 10 years, as verified in our official warranty policy document (Reference: WP-2024-01).")
        
        # Synthesis
        else:
            print(f"   [MockLLM] Synthesis (call #{self.call_count})")
            return LLMResponse(content="The warranty is 10 years.")
    
    async def stream(self, prompt: str, **kwargs):
        yield "Test"
    
    async def health_check(self) -> bool:
        return True

# Mock Tool
class MockSearchTool(BaseTool):
    name = "mock_search"
    description = "Mock search tool"
    parameters_schema = {"type": "object", "properties": {}, "required": []}
    
    async def run(self, **kwargs) -> ToolResult:
        print("   [MockTool] Executing search...")
        return ToolResult(
            success=True,
            data="Found warranty information: Standard 10-year warranty on all products.",
            metadata={}
        )

async def test_with_critic():
    print("\n" + "="*70)
    print("🧪 TEST 1: Normal Flow (Critic Approves First Answer)")
    print("="*70)
    
    llm = MockLLM()
    registry = ToolRegistry()
    registry.register(MockSearchTool())
    critic = MockCritic(should_fail_first=False)
    
    orchestrator = Orchestrator(llm=llm, tools=registry, critic=critic)
    
    result = await orchestrator.run("What is the warranty?")
    
    print("\n📊 Results:")
    print(f"   Answer: {result.answer}")
    print(f"   Validation Passed: {result.metadata.get('validation_passed', 'N/A')}")
    print(f"   Validation Confidence: {result.metadata.get('validation_confidence', 'N/A')}")
    print(f"   LLM Calls: {llm.call_count}")
    print(f"   Critic Calls: {critic.call_count}")
    
    assert result.success, "Test 1 should succeed"
    assert result.metadata.get('validation_passed') == True, "Validation should pass"
    print("\n✅ TEST 1 PASSED\n")

async def test_with_critic_retry():
    print("\n" + "="*70)
    print("🧪 TEST 2: Self-Correction Flow (Critic Rejects, Then Approves)")
    print("="*70)
    
    llm = MockLLM()
    registry = ToolRegistry()
    registry.register(MockSearchTool())
    critic = MockCritic(should_fail_first=True)  # Reject first answer
    
    orchestrator = Orchestrator(llm=llm, tools=registry, critic=critic)
    
    result = await orchestrator.run("What is the warranty?")
    
    print("\n📊 Results:")
    print(f"   Answer: {result.answer}")
    print(f"   Validation Passed: {result.metadata.get('validation_passed', 'N/A')}")
    print(f"   Validation Issues: {result.metadata.get('validation_issues', [])}")
    print(f"   LLM Calls: {llm.call_count} (should be 3: plan + synthesis + retry)")
    print(f"   Critic Calls: {critic.call_count} (should be 2: initial + after retry)")
    
    assert result.success, "Test 2 should succeed after retry"
    assert llm.call_count == 3, f"Expected 3 LLM calls, got {llm.call_count}"
    assert critic.call_count == 2, f"Expected 2 Critic calls, got {critic.call_count}"
    print("\n✅ TEST 2 PASSED - Self-correction working!\n")

async def main():
    print("\n🚀 Testing SOTA Agentic Framework with Critic Loop")
    print("="*70)
    
    try:
        await test_with_critic()
        await test_with_critic_retry()
        
        print("\n" + "="*70)
        print("🎉 ALL TESTS PASSED!")
        print("="*70)
        print("\n✨ SOTA Agentic Framework Features Verified:")
        print("   ✅ Plan-and-Execute Orchestrator")
        print("   ✅ Tool Registry & Execution")
        print("   ✅ Critic-based Validation")
        print("   ✅ Autonomous Self-Correction (Retry on failure)")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
