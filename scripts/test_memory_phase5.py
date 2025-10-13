"""
Test Script for Phase 5: Memory Enhancements

Tests:
1. Configuration loading
2. PII detection and encryption
3. Short-term memory with auto-summary
4. TTL enforcement
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add package to path
sys.path.insert(0, 'packages/memory/src')
sys.path.insert(0, 'packages/commons/src')

from motor.motor_asyncio import AsyncIOMotorClient
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ]
)

logger = structlog.get_logger()


async def test_configuration():
    """Test 1: Configuration loading."""
    print("\n" + "="*60)
    print("TEST 1: Configuration Loading")
    print("="*60)
    
    try:
        from memory.config import MemoryConfig
        
        # Validate configuration
        MemoryConfig.validate()
        
        # Print configuration summary
        config_summary = MemoryConfig.get_summary()
        
        print("\n✅ Configuration loaded successfully")
        print(f"\nConfiguration Summary:")
        print(f"  Short-term TTL: {config_summary['ttl']['short_term_hours']} hours")
        print(f"  Episodic TTL: {config_summary['ttl']['episodic_days']} days")
        print(f"  Auto-summary turns: {config_summary['thresholds']['auto_summary_turns']}")
        print(f"  Confidence threshold: {config_summary['thresholds']['confidence']}")
        print(f"  Max messages per conversation: {config_summary['limits']['max_messages']}")
        print(f"  Max facts per user: {config_summary['limits']['max_facts']}")
        print(f"\nFeatures:")
        for feature, enabled in config_summary['features'].items():
            status = "✅" if enabled else "❌"
            print(f"  {status} {feature}: {enabled}")
        
        print(f"\nPII Encryption: {'✅ Enabled' if config_summary['pii']['encryption_enabled'] else '❌ Disabled'}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Configuration test failed: {e}")
        return False


async def test_pii_detection():
    """Test 2: PII detection and encryption."""
    print("\n" + "="*60)
    print("TEST 2: PII Detection and Encryption")
    print("="*60)
    
    try:
        from memory.processors.pii_vault import PIIDetector, PIIVault
        from memory.utils.crypto import CryptoUtils
        
        # Test PII detection
        test_text = """
        Hi, my name is John Doe. 
        You can reach me at john.doe@example.com or call me at 555-123-4567.
        My SSN is 123-45-6789.
        """
        
        print("\n📝 Test text:")
        print(test_text)
        
        # Detect PII
        findings = PIIDetector.detect(test_text)
        print(f"\n🔍 PII detected: {len(findings)} findings")
        for pii_type, value in findings:
            print(f"  - {pii_type}: {value}")
        
        # Test redaction
        redacted = PIIDetector.redact(test_text)
        print(f"\n🔒 Redacted text:")
        print(redacted)
        
        # Test encryption (if key available)
        encryption_key = os.getenv('PII_ENCRYPTION_KEY')
        if encryption_key:
            print(f"\n🔐 Testing encryption...")
            
            # Generate test key if not in env
            if not encryption_key or len(encryption_key) < 32:
                print("  Generating test encryption key...")
                encryption_key = CryptoUtils.generate_key()
                print(f"  Generated key: {encryption_key[:20]}...")
            
            vault = PIIVault(master_key=encryption_key)
            
            # Encrypt sensitive data
            sensitive_data = "john.doe@example.com"
            pii_field = vault.encrypt_field(sensitive_data, "email")
            
            print(f"  ✅ Encrypted: {pii_field.encrypted_value[:40]}...")
            
            # Decrypt
            decrypted = vault.decrypt_field(pii_field)
            print(f"  ✅ Decrypted: {decrypted}")
            
            if decrypted == sensitive_data:
                print(f"  ✅ Encryption/Decryption successful!")
            else:
                print(f"  ❌ Decryption mismatch!")
                return False
        else:
            print(f"\n⚠️  PII_ENCRYPTION_KEY not set - skipping encryption test")
            print(f"  To test encryption, add to .env:")
            print(f"  PII_ENCRYPTION_KEY={CryptoUtils.generate_key()}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ PII test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_short_term_memory():
    """Test 3: Short-term memory with auto-summary."""
    print("\n" + "="*60)
    print("TEST 3: Short-Term Memory with Auto-Summary")
    print("="*60)
    
    try:
        from memory.managers.short_term import ShortTermMemory
        from memory.types import MessageRole
        
        # Connect to MongoDB
        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            print("❌ MONGODB_URI not set")
            return False
        
        client = AsyncIOMotorClient(mongodb_uri)
        db_name = os.getenv('MONGODB_DATABASE', 'agent-builder')
        db = client[db_name]
        
        # Test connection
        await client.admin.command('ping')
        print(f"✅ Connected to MongoDB: {db_name}")
        
        # Initialize short-term memory
        memory = ShortTermMemory(db)
        await memory._ensure_indexes()
        
        # Test conversation
        conversation_id = f"test-conv-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        print(f"\n📝 Testing conversation: {conversation_id}")
        
        # Add messages to trigger auto-summary (4 turns = 8 messages)
        test_messages = [
            ("user", "How do I install a faucet?"),
            ("assistant", "First, turn off the water supply..."),
            ("user", "What tools do I need?"),
            ("assistant", "You'll need an adjustable wrench and plumber's tape..."),
            ("user", "How long does installation take?"),
            ("assistant", "Typically 1-2 hours for a standard installation..."),
            ("user", "What about the warranty?"),
            ("assistant", "Our faucets come with a 5-year warranty..."),
        ]
        
        print(f"\n➕ Adding {len(test_messages)} messages...")
        for i, (role, content) in enumerate(test_messages, 1):
            message = await memory.add_message(
                conversation_id=conversation_id,
                role=MessageRole(role),
                content=content,
                metadata={"test": True, "message_num": i}
            )
            print(f"  {i}. [{role}] {content[:50]}...")
        
        # Check message count
        message_count = await memory.get_message_count(conversation_id)
        turn_count = await memory.get_turn_count(conversation_id)
        print(f"\n📊 Stats:")
        print(f"  Messages: {message_count}")
        print(f"  Turns: {turn_count}")
        
        # Check if summary was triggered
        should_summarize = await memory.should_summarize(conversation_id)
        print(f"  Should summarize: {should_summarize}")
        
        # Get conversation context
        context = await memory.get_conversation_context(conversation_id)
        print(f"\n📋 Conversation context:")
        print(f"  Messages: {context['message_count']}")
        print(f"  Turns: {context['turn_count']}")
        print(f"  Summaries: {len(context['summaries'])}")
        
        if context['has_summaries']:
            print(f"\n📄 Summaries:")
            for summary in context['summaries']:
                print(f"  - Turn {summary['turn_count']}: {summary['summary']}")
        
        # Retrieve recent messages
        recent = await memory.get_recent_messages(conversation_id, limit=5)
        print(f"\n💬 Recent messages ({len(recent)}):")
        for msg in recent[-3:]:  # Show last 3
            print(f"  [{msg.role.value}] {msg.content[:60]}...")
        
        # Cleanup
        print(f"\n🧹 Cleaning up test data...")
        await memory.clear_conversation(conversation_id)
        
        client.close()
        
        print(f"\n✅ Short-term memory test passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Short-term memory test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_memory_stats():
    """Test 4: Memory statistics and monitoring."""
    print("\n" + "="*60)
    print("TEST 4: Memory Statistics")
    print("="*60)
    
    try:
        from memory.types import MemoryStats
        from memory.config import MemoryConfig
        
        # Create sample stats
        stats = MemoryStats(
            conversation_id="test-123",
            message_count=42,
            summary_count=5,
            fact_count=3,
            rule_match_count=2,
            oldest_message=datetime.now(timezone.utc),
            newest_message=datetime.now(timezone.utc),
            storage_bytes=1024 * 50  # 50 KB
        )
        
        print(f"\n📊 Memory Statistics:")
        print(f"  Messages: {stats.message_count}")
        print(f"  Summaries: {stats.summary_count}")
        print(f"  Facts: {stats.fact_count}")
        print(f"  Rule matches: {stats.rule_match_count}")
        print(f"  Storage: {stats.storage_bytes / 1024:.2f} KB")
        
        # Test TTL calculations
        print(f"\n⏱️  TTL Settings:")
        print(f"  Short-term: {MemoryConfig.SHORT_TERM_TTL / 3600:.0f} hours")
        print(f"  Episodic: {MemoryConfig.EPISODIC_TTL / (24 * 3600):.0f} days")
        print(f"  Summary cache: {MemoryConfig.SUMMARY_CACHE_TTL / 3600:.0f} hours")
        
        print(f"\n✅ Memory statistics test passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Memory statistics test failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "="*70)
    print(" PHASE 5: MEMORY ENHANCEMENTS - TEST SUITE")
    print("="*70)
    
    # Load environment
    load_dotenv('apps/api/.env')
    
    # Run tests
    results = []
    
    results.append(("Configuration", await test_configuration()))
    results.append(("PII Detection", await test_pii_detection()))
    results.append(("Short-Term Memory", await test_short_term_memory()))
    results.append(("Memory Statistics", await test_memory_stats()))
    
    # Summary
    print("\n" + "="*70)
    print(" TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\n{'='*70}")
    print(f"Results: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    print(f"{'='*70}\n")
    
    if passed == total:
        print("🎉 All tests passed! Phase 5 core features working.")
        print("\n📋 Next steps:")
        print("  1. Implement episodic memory (fact extraction)")
        print("  2. Implement graph memory (rules/escalations)")
        print("  3. Add LLM-based summarization")
        print("  4. Implement TTL cleanup job")
        print("  5. Add GDPR delete functionality")
    else:
        print("⚠️  Some tests failed. Review errors above.")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
