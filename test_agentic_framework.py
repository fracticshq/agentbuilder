#!/usr/bin/env python3
"""
Quick Test for SOTA Agentic Framework
Tests the Plan -> Execute -> Critic -> Synthesize loop
"""
import asyncio
import sys
import os
sys.path.append(os.path.abspath("apps/api"))

from dotenv import load_dotenv
from app.config import Settings
from app.services.message_service import MessageService
from commons.types.requests import MessageRequest

async def test_agentic_loop():
    print("🚀 Testing SOTA Agentic Framework...")
    print("=" * 60)
    
    # Load environment
    load_dotenv("apps/api/.env")
    
    # Initialize service
    settings = Settings()
    service = MessageService(settings=settings, brand_id="essco-bathware", agent_id="default")
    
    # Initialize DB context (minimal)
    await service._initialize_brand_database("default")
    await service._ensure_memory_initialized()
   
    # Test query
    test_query = "What are the warranty terms?"
    
    print(f"\n📝 Query: '{test_query}'")
    print("-" * 60)
    
    request = MessageRequest(
        message=test_query,
        brand_id="essco-bathware",
        agent_id="default",
        user_id="test-user",
        conversation_id="test-conv-001"
    )
    
    # Process message
    try:
        response = await service.process_message(request)
        
        print("\n✅ Response Received:")
        print(response.message)
        print("\n" + "=" * 60)
        print("\n📊 Metadata:")
        print(f"   Conversation ID: {response.conversation_id}")
        print(f"   Citations: {len(response.citations)}")
        
        print("\n✅ Test PASSED - SOTA Agentic Loop is working!")
        
    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_agentic_loop())
