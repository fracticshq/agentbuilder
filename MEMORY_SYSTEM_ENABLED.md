# 🧠 Memory System Enabled - Widget Update

## ✅ What Was Fixed

The widget was **"forgetful"** because it wasn't sending persistent identifiers to the API. Each message was treated as a new conversation.

### Changes Made:

1. **Persistent User ID** (localStorage)
   - Generated once per browser: `user_{timestamp}_{random}`
   - Stored in `localStorage` - survives page refreshes
   - Enables episodic memory to track user facts across sessions

2. **Persistent Conversation ID** (sessionStorage)
   - Generated once per session: `conv_{timestamp}_{random}`
   - Stored in `sessionStorage` - survives page refreshes within same session
   - Enables short-term memory to remember conversation history

3. **Updated API Calls**
   - Now sends: `user_id`, `conversation_id`, `agent_id`
   - Previously only sent: `agent_id`

### Files Modified:

- `apps/widget/src/App.tsx`:
  - Added `userId` state with localStorage persistence
  - Added `conversationId` from store with sessionStorage persistence
  - Updated `handleSendMessage()` to pass both IDs to API

- `apps/widget/src/utils/apiClient.ts`:
  - Updated `sendMessage()` to accept `userId` in request
  - Now sends `user_id` instead of hardcoded 'anonymous'

---

## 🧪 How to Test Memory

### Method 1: Use the Widget (Recommended)

1. **Open widget** at http://localhost:5173 (or 5174)
2. **Clear browser data** to start fresh (or use incognito)
3. **Send these messages in order:**

   ```
   Message 1: "My name is Anant and I am looking to renovate my bathroom."
   Message 2: "My budget is around 50,000 rupees."
   Message 3: "What is my name?"          ← Should remember "Anant"
   Message 4: "What budget did I mention?" ← Should remember "50,000"
   ```

4. **Refresh the page** and ask again:
   ```
   Message 5: "What is my name?"
   ```
   Should still remember because conversation_id persists in sessionStorage!

### Method 2: Run Test Script

```bash
./test_memory_system.sh
```

This script:
- Creates a test conversation
- Sends 4 messages in sequence
- Tests if agent remembers name and budget
- Shows memory operations in API logs

---

## 📊 What Memory Components Are Active

### 1. Short-Term Memory (Conversation History)
- **Storage**: MongoDB `short_term_memory` collection
- **Retention**: 72 hours TTL
- **Triggered**: Every message
- **Function**: 
  - Stores last 10 messages per conversation
  - Auto-summarizes every 4 turns
  - Provides context to LLM

### 2. Episodic Memory (User Facts)
- **Storage**: MongoDB `episodic_memory` collection
- **Retention**: 90 days TTL
- **Triggered**: When confidence ≥ 0.70
- **Function**:
  - Extracts facts: name, preferences, budget, etc.
  - Encrypts PII (names, contact info)
  - Retrieved for personalization

### 3. Graph Memory (Rules & Policies)
- **Storage**: MongoDB `agents` collection
- **Retention**: Permanent
- **Triggered**: Pattern matching on query
- **Function**:
  - Warranty policies
  - Escalation rules
  - Safety alerts

---

## 🔍 How to Verify Memory is Working

### Check Browser Storage:

**localStorage** (survives page refresh):
```javascript
localStorage.getItem('agent_widget_user_id')
// Example: "user_1730000000_abc123xyz"
```

**sessionStorage** (cleared on tab close):
```javascript
sessionStorage.getItem('agent_widget_conversation_id')
// Example: "conv_1730000000_def456uvw"
```

### Check API Logs:

You should see these log messages:

```
✅ "Storing message in short-term memory"
✅ "Retrieved 10 recent messages from short-term"
✅ "Extracted user facts: [...]"
✅ "Retrieved user facts for user_id=..."
```

### Check MongoDB:

```javascript
// Short-term memory
db.short_term_memory.find({ conversation_id: "conv_..." })

// Episodic memory
db.episodic_memory.find({ user_id: "user_..." })

// Should see stored messages and extracted facts
```

---

## 🎯 Expected Behavior

### First Conversation:
```
User: "My name is Anant"
Bot:  "Hello Anant! How can I help you today?"

User: "What is my name?"
Bot:  "Your name is Anant."
```

### After Page Refresh (same session):
```
User: "Do you remember my name?"
Bot:  "Yes, your name is Anant."
```

### After Closing Tab (new session):
```
User: "Do you remember me?"
Bot:  "Yes! You're Anant. [Based on episodic memory]"
```

---

## 🔄 Memory Lifecycle

### Message Flow with Memory:

```
1. User sends message
   ↓
2. API receives: user_id, conversation_id, agent_id
   ↓
3. Load short-term memory (last 10 messages)
   ↓
4. Load episodic memory (user facts)
   ↓
5. Load graph memory (rules/policies)
   ↓
6. RAG retrieval (documents)
   ↓
7. Build context: memories + documents + system prompt
   ↓
8. LLM generates response
   ↓
9. Store message in short-term memory
   ↓
10. Extract facts → episodic memory (if confidence ≥ 0.70)
   ↓
11. Return response to user
```

---

## 🚀 What This Enables

Now that memory is working, the agent can:

✅ **Remember user's name** across messages
✅ **Recall preferences** (budget, style, etc.)
✅ **Reference previous questions** in the conversation
✅ **Provide personalized recommendations**
✅ **Build context** over multiple interactions
✅ **Persist facts** across page refreshes (same session)
✅ **Track long-term user history** (episodic memory, 90 days)

---

## 🔧 Configuration

### Adjust Memory Settings:

**Short-Term Memory TTL:**
```python
# packages/memory/src/memory/managers/short_term.py
ttl_seconds = 72 * 3600  # 72 hours (default)
```

**Episodic Memory TTL:**
```python
# packages/memory/src/memory/managers/episodic.py
ttl_seconds = 90 * 24 * 3600  # 90 days (default)
```

**Fact Extraction Confidence:**
```python
# apps/api/app/services/message_service.py
if confidence >= 0.70:  # Only store high-confidence facts
```

**Summary Trigger:**
```python
# packages/memory/src/memory/managers/short_term.py
if message_count >= 4:  # Summarize every 4 turns
```

---

## 📝 Widget Storage Keys

The widget uses these browser storage keys:

- **`agent_widget_user_id`** (localStorage)
  - Purpose: Persistent user identification
  - Lifetime: Until manually cleared
  - Format: `user_{timestamp}_{random}`

- **`agent_widget_conversation_id`** (sessionStorage)
  - Purpose: Current conversation tracking
  - Lifetime: Until tab/window closed
  - Format: `conv_{timestamp}_{random}`

---

## 🎉 Summary

**Before Fix:**
- ❌ Each message was a new conversation
- ❌ No memory of previous messages
- ❌ No personalization
- ❌ Agent was "forgetful"

**After Fix:**
- ✅ Persistent conversation across messages
- ✅ Remembers user facts (name, budget, preferences)
- ✅ Conversation history maintained
- ✅ Personalized responses
- ✅ Memory survives page refreshes (same session)

**The agent is no longer forgetful! 🧠**
