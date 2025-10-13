# Phase 5: Memory Enhancements - Implementation Plan

**Start Date**: October 14, 2025  
**Estimated Duration**: 3-4 hours  
**Status**: 🚀 IN PROGRESS

---

## 🎯 Objectives

Implement the **4-layer memory architecture** from AGENTS.md:

1. **Short-Term Memory**: Rolling buffer with auto-summary (TTL 72h)
2. **Episodic Memory**: User facts/preferences with PII vaulting (TTL 90d)
3. **Semantic Memory**: Brand KB (already implemented via retrieval)
4. **Graph Memory**: Rules, policies, escalation patterns

---

## 📋 Requirements from AGENTS.md

### Memory Layers

#### 1. Short-Term Memory
- Rolling conversation buffer
- **Auto-summary every 4 turns** (compress old messages)
- **TTL: 72 hours**
- Store in Redis (fast access)
- Fallback to MongoDB if Redis unavailable

#### 2. Episodic Memory
- Store **user facts & preferences**
- **PII must be vaulted** (encrypted, separate collection)
- **Confidence threshold: ≥ 0.70** (only write if confident)
- **TTL: 90 days**
- **GDPR/CCPA delete support**
- Store in MongoDB

#### 3. Semantic Memory
- Brand knowledge base (documents, FAQs, manuals)
- ✅ **Already implemented** via retrieval package
- Version by `doc_id+section`

#### 4. Graph Memory
- Rules, policies, escalation triggers
- Store structured data (conditions → actions)
- Query by pattern matching
- Store in MongoDB

---

## 🏗️ Architecture

### File Structure
```
packages/memory/
├── AGENTS.md                    # ← Memory-specific rules
├── pyproject.toml
└── src/memory/
    ├── __init__.py              # Public API exports
    ├── types.py                 # ← NEW: Pydantic models
    ├── config.py                # ← NEW: Configuration
    ├── managers/
    │   ├── __init__.py
    │   ├── memory_manager.py    # ✅ Exists - enhance
    │   ├── short_term.py        # ← NEW: Implement
    │   ├── episodic.py          # ← NEW: Implement
    │   ├── semantic.py          # Delegate to retrieval
    │   └── graph.py             # ← NEW: Implement
    ├── adapters/
    │   ├── __init__.py
    │   ├── redis.py             # ✅ Exists - enhance
    │   └── mongo.py             # ✅ Exists - enhance
    ├── processors/
    │   ├── __init__.py
    │   ├── summarizer.py        # ← NEW: Auto-summary logic
    │   ├── pii_vault.py         # ← NEW: PII encryption
    │   └── entity_extractor.py  # ← NEW: Extract facts
    └── utils/
        ├── __init__.py
        ├── ttl_cleanup.py       # ← NEW: TTL enforcement
        └── crypto.py            # ← NEW: Encryption utils
```

---

## 📝 Implementation Steps

### Step 1: Core Types & Configuration (30 min)

#### 1.1 Create `types.py`
```python
# Memory types for all managers
- Message (role, content, timestamp, metadata)
- ConversationSummary (summary, turn_count, timestamp)
- EpisodicFact (fact, confidence, pii_encrypted, ttl)
- GraphRule (condition, action, priority)
- MemoryConfig (ttls, thresholds, limits)
```

#### 1.2 Create `config.py`
```python
# Configuration from environment
- SHORT_TERM_TTL = 72 * 3600  # 72 hours
- EPISODIC_TTL = 90 * 24 * 3600  # 90 days
- CONFIDENCE_THRESHOLD = 0.70
- AUTO_SUMMARY_TURNS = 4
- PII_ENCRYPTION_KEY (from env)
```

### Step 2: Short-Term Memory (45 min)

#### 2.1 Implement `managers/short_term.py`
- `add_message()` - append to conversation buffer
- `get_recent_messages(limit)` - fetch last N messages
- `should_summarize()` - check if 4 turns passed
- `trigger_summary()` - call summarizer
- `get_conversation_context()` - messages + summaries
- **Redis storage** with 72h TTL
- **Fallback to MongoDB** if Redis down

#### 2.2 Implement `processors/summarizer.py`
- `summarize_turns(messages)` - compress 4 turns
- Use LLM to create concise summary
- Store summary in short-term memory
- Clear old messages after summarization

### Step 3: PII Vaulting (45 min)

#### 3.1 Implement `processors/pii_vault.py`
- `encrypt_pii(text)` - AES-256 encryption
- `decrypt_pii(encrypted)` - decrypt for authorized access
- `detect_pii(text)` - identify PII patterns (regex/NER)
- `vault_field(value)` - encrypt sensitive fields
- **Store encryption key in environment** (not in DB)

#### 3.2 Implement `utils/crypto.py`
- AES-256-GCM encryption/decryption
- Key derivation from master key
- Secure random IV generation

### Step 4: Episodic Memory (45 min)

#### 4.1 Implement `managers/episodic.py`
- `extract_facts(messages)` - identify user preferences
- `store_fact(fact, confidence)` - only if confidence ≥ 0.70
- `get_user_facts(user_id)` - retrieve all facts
- `delete_user_data(user_id)` - GDPR compliance
- **PII fields encrypted** before storage
- **TTL: 90 days**

#### 4.2 Implement `processors/entity_extractor.py`
- Extract entities: name, location, preferences
- Assign confidence scores (0.0-1.0)
- Detect PII: email, phone, address, SSN
- Return structured facts

### Step 5: Graph Memory (30 min)

#### 5.1 Implement `managers/graph.py`
- `add_rule(condition, action, priority)` - store rules
- `match_rules(context)` - pattern matching
- `get_escalations(keywords)` - safety triggers
- **Examples**:
  - "gas smell" → escalate to emergency
  - "visible sparking" → escalate to technician
  - warranty question → fetch policy

### Step 6: TTL Cleanup (30 min)

#### 6.1 Implement `utils/ttl_cleanup.py`
- Background job to delete expired records
- MongoDB TTL indexes (automatic)
- Redis TTL (automatic)
- Manual cleanup for episodic memory (90d)
- Log cleanup operations

### Step 7: Enhanced Memory Manager (30 min)

#### 7.1 Update `managers/memory_manager.py`
- Integrate all 4 memory layers
- Orchestrate memory operations
- Handle fallbacks (Redis → MongoDB)
- Unified API for message service

### Step 8: Testing (30 min)

#### 8.1 Create `test_memory_phase5.py`
- Test short-term with auto-summary
- Test PII vaulting (encrypt/decrypt)
- Test episodic fact extraction
- Test graph rule matching
- Test TTL cleanup
- Test GDPR delete

---

## 🔒 Security Requirements

### PII Handling
- ✅ **Never** log raw PII
- ✅ Encrypt PII **before** MongoDB storage
- ✅ Store encryption key in **environment** only
- ✅ Use AES-256-GCM (authenticated encryption)
- ✅ Redact PII in traces/logs

### GDPR Compliance
- ✅ `delete_user_data(user_id)` - delete all episodic facts
- ✅ TTL enforcement (90 days)
- ✅ Audit log for data access
- ✅ User consent tracking (optional)

### Rate Limiting
- ✅ Max 1000 messages per conversation
- ✅ Max 100 facts per user
- ✅ Summary generation: max 1 per 4 turns

---

## 📊 Success Criteria

### Functional
- ✅ Short-term memory stores & retrieves messages
- ✅ Auto-summary triggered every 4 turns
- ✅ PII encrypted before storage
- ✅ Episodic facts extracted with confidence ≥ 0.70
- ✅ Graph rules match patterns correctly
- ✅ TTL cleanup removes expired data
- ✅ GDPR delete works end-to-end

### Performance
- ✅ Message add: <50ms (P95)
- ✅ Message retrieve: <100ms (P95)
- ✅ Fact extraction: <500ms (P95)
- ✅ PII encryption: <10ms per field
- ✅ Summary generation: <2s (uses LLM)

### Security
- ✅ No PII in logs/traces
- ✅ Encryption keys not in code/DB
- ✅ PII fields always encrypted
- ✅ GDPR delete verified

---

## 🔧 Dependencies

### Python Packages (add to pyproject.toml)
```toml
[project]
dependencies = [
    "motor>=3.7.0",           # MongoDB async
    "redis>=5.0.0",           # Redis client
    "cryptography>=41.0.0",   # AES encryption
    "pydantic>=2.12.0",       # Data validation
    "structlog>=25.4.0",      # Logging
    "python-dotenv>=1.1.0",   # Environment
    "spacy>=3.7.0",           # NER (optional)
]
```

### Environment Variables
```bash
# Memory Configuration
SHORT_TERM_TTL=259200          # 72 hours
EPISODIC_TTL=7776000           # 90 days
CONFIDENCE_THRESHOLD=0.70
AUTO_SUMMARY_TURNS=4

# PII Vaulting
PII_ENCRYPTION_KEY=<generate-strong-key>  # 32 bytes, base64

# Storage
MONGODB_URI=mongodb+srv://...
REDIS_URL=redis://localhost:6379

# LLM for Summarization
OPENAI_API_KEY=sk-...
SUMMARY_MODEL=gpt-4o-mini
```

---

## 📈 Progress Tracking

### Step 1: Core Types ⏳
- [ ] Create `types.py` with Pydantic models
- [ ] Create `config.py` with environment loading
- [ ] Update `__init__.py` exports

### Step 2: Short-Term Memory ⏳
- [ ] Implement `short_term.py`
- [ ] Implement `summarizer.py`
- [ ] Test with Redis + MongoDB fallback

### Step 3: PII Vaulting ⏳
- [ ] Implement `pii_vault.py`
- [ ] Implement `crypto.py`
- [ ] Test encryption/decryption

### Step 4: Episodic Memory ⏳
- [ ] Implement `episodic.py`
- [ ] Implement `entity_extractor.py`
- [ ] Test fact extraction & confidence

### Step 5: Graph Memory ⏳
- [ ] Implement `graph.py`
- [ ] Add safety escalation rules
- [ ] Test pattern matching

### Step 6: TTL Cleanup ⏳
- [ ] Implement `ttl_cleanup.py`
- [ ] Configure MongoDB TTL indexes
- [ ] Test cleanup operations

### Step 7: Memory Manager ⏳
- [ ] Enhance `memory_manager.py`
- [ ] Integrate all 4 layers
- [ ] Test unified API

### Step 8: Testing ⏳
- [ ] Create comprehensive test suite
- [ ] Validate all requirements
- [ ] Performance benchmarks

---

## 🎯 Next Steps

1. **Start with Step 1**: Create core types and config
2. **Proceed sequentially**: Each step builds on previous
3. **Test incrementally**: Validate after each component
4. **Update AGENTS.md**: Document memory behavior

---

**Let's begin with Step 1!** 🚀
