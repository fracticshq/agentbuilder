#!/usr/bin/env python3
"""
Phase 4 Multi-LLM Integration Test Suite
"""

import asyncio
import sys
import time
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent / "packages" / "commons" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "packages" / "llm" / "src"))

from llm import LLMFactory, GenerationRequest, ProviderType, LLMConfig


async def test_provider(provider_name: str, config: LLMConfig):
    """Test a specific LLM provider."""
    print(f"\n--- Testing {provider_name} Provider ---")
    
    try:
        # Create provider
        provider = LLMFactory.create_provider(config)
        print(f"✅ {provider_name} provider created")
        
        # Test health check
        health = await provider.health_check()
        print(f"Health: {health['status']} (latency: {health.get('latency_ms', 'N/A')}ms)")
        
        # Test generation
        request = GenerationRequest(
            prompt="What are the benefits of using AI in business?",
            context="This is a question about artificial intelligence applications.",
            max_tokens=100,
            temperature=0.7
        )
        
        print(f"Testing generation...")
        start_time = time.time()
        response = await provider.generate(request)
        latency_ms = (time.time() - start_time) * 1000
        
        print(f"Response ({latency_ms:.2f}ms):")
        print(f"  Text: {response.text[:100]}...")
        print(f"  Citations: {len(response.citations)}")
        print(f"  Tokens used: {response.tokens_used}")
        print(f"  Has safety info: {response.safety.disclaimer is not None}")
        print(f"  Follow-ups: {len(response.follow_up)}")
        
        # Test streaming
        print(f"Testing streaming...")
        stream_request = GenerationRequest(
            prompt="Count from 1 to 5",
            max_tokens=50,
            temperature=0.3
        )
        
        collected_tokens = []
        start_time = time.time()
        
        async for token in provider.generate_stream(stream_request):
            collected_tokens.append(token.text)
            if token.is_final:
                break
        
        stream_latency = (time.time() - start_time) * 1000
        streamed_text = "".join(collected_tokens[:-1])  # Exclude final empty token
        
        print(f"Streamed text ({stream_latency:.2f}ms): {streamed_text}")
        print(f"Tokens streamed: {len(collected_tokens)}")
        
        print(f"✅ {provider_name} tests completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ {provider_name} test failed: {str(e)}")
        return False


async def test_factory():
    """Test the LLM factory."""
    print("=== Testing LLM Factory ===")
    
    available_providers = LLMFactory.get_available_providers()
    print(f"Available providers: {[p.value for p in available_providers]}")
    
    if not available_providers:
        print("❌ No providers available")
        return False
    
    print(f"✅ {len(available_providers)} providers registered")
    return True


async def main():
    """Run all Phase 4 tests."""
    print("🚀 Phase 4 Multi-LLM Integration Tests")
    print("=" * 50)
    
    # Test factory
    factory_success = await test_factory()
    if not factory_success:
        print("\n❌ Factory tests failed")
        return
    
    # Test configurations
    test_configs = {
        "OpenAI": LLMConfig(
            provider=ProviderType.OPENAI,
            api_key="test-openai-key",
            model="gpt-4",
            max_tokens=200,
            temperature=0.7
        ),
        "Qwen": LLMConfig(
            provider=ProviderType.QWEN,
            api_key="test-qwen-key", 
            model="qwen-max",
            max_tokens=200,
            temperature=0.7
        )
    }
    
    # Test each available provider
    results = {}
    for provider_name, config in test_configs.items():
        if config.provider in LLMFactory.get_available_providers():
            results[provider_name] = await test_provider(provider_name, config)
        else:
            print(f"\n⏭️  Skipping {provider_name} (not available)")
            results[provider_name] = None
    
    # Summary
    print("\n" + "=" * 50)
    print("=== Test Summary ===")
    
    passed = sum(1 for success in results.values() if success is True)
    failed = sum(1 for success in results.values() if success is False)
    skipped = sum(1 for success in results.values() if success is None)
    
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    
    if failed == 0 and passed > 0:
        print("\n🎉 All tests passed! Phase 4 Multi-LLM integration is working correctly.")
    elif failed > 0:
        print(f"\n⚠️  {failed} test(s) failed. Check the errors above.")
    else:
        print("\n⚠️  No tests were run. Check provider availability.")


if __name__ == "__main__":
    asyncio.run(main())
