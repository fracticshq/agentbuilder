#!/bin/bash
# Test Memory System - Conversation Persistence

echo "════════════════════════════════════════════════════════════════"
echo "  🧠 TESTING MEMORY SYSTEM & CONVERSATION PERSISTENCE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "This test verifies that:"
echo "  ✅ Conversation history is remembered across messages"
echo "  ✅ User facts are extracted and stored in episodic memory"
echo "  ✅ Agent can recall information from earlier in the conversation"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

# Use a test conversation ID
CONV_ID="test-memory-conv-$(date +%s)"
USER_ID="test-memory-user"
AGENT_ID="f168131d-7833-4f9c-ac8e-8a19b22c16f3"

echo "📝 Test Configuration:"
echo "   User ID: $USER_ID"
echo "   Conversation ID: $CONV_ID"
echo "   Agent ID: $AGENT_ID"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

# Message 1: Introduce yourself with facts
echo "💬 MESSAGE 1: User introduces themselves"
echo "   Query: 'My name is Anant and I am looking to renovate my bathroom.'"
echo ""
curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"My name is Anant and I am looking to renovate my bathroom.\",
    \"user_id\": \"$USER_ID\",
    \"conversation_id\": \"$CONV_ID\",
    \"agent_id\": \"$AGENT_ID\"
  }" | python3 -c "import sys, json; data = json.load(sys.stdin); print('   Response:', data.get('content', '')[:200] + '...')"

echo ""
echo "────────────────────────────────────────────────────────────────"
echo ""
sleep 2

# Message 2: Ask about budget
echo "💬 MESSAGE 2: Mention budget preference"
echo "   Query: 'My budget is around 50,000 rupees.'"
echo ""
curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"My budget is around 50,000 rupees.\",
    \"user_id\": \"$USER_ID\",
    \"conversation_id\": \"$CONV_ID\",
    \"agent_id\": \"$AGENT_ID\"
  }" | python3 -c "import sys, json; data = json.load(sys.stdin); print('   Response:', data.get('content', '')[:200] + '...')"

echo ""
echo "────────────────────────────────────────────────────────────────"
echo ""
sleep 2

# Message 3: Ask if it remembers your name
echo "💬 MESSAGE 3: Test if agent remembers name from Message 1"
echo "   Query: 'What is my name?'"
echo ""
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"What is my name?\",
    \"user_id\": \"$USER_ID\",
    \"conversation_id\": \"$CONV_ID\",
    \"agent_id\": \"$AGENT_ID\"
  }")

echo "$RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print('   Response:', data.get('content', ''))"
echo ""

# Check if response contains the name
if echo "$RESPONSE" | grep -qi "anant"; then
    echo "   ✅ SUCCESS: Agent remembered the name 'Anant'!"
else
    echo "   ❌ FAILED: Agent did not remember the name"
fi

echo ""
echo "────────────────────────────────────────────────────────────────"
echo ""
sleep 2

# Message 4: Ask about budget
echo "💬 MESSAGE 4: Test if agent remembers budget from Message 2"
echo "   Query: 'What budget did I mention?'"
echo ""
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"What budget did I mention?\",
    \"user_id\": \"$USER_ID\",
    \"conversation_id\": \"$CONV_ID\",
    \"agent_id\": \"$AGENT_ID\"
  }")

echo "$RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print('   Response:', data.get('content', ''))"
echo ""

# Check if response contains the budget
if echo "$RESPONSE" | grep -qi "50,000\|50000\|fifty thousand"; then
    echo "   ✅ SUCCESS: Agent remembered the budget!"
else
    echo "   ❌ FAILED: Agent did not remember the budget"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  📊 CHECK API LOGS FOR:"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Memory operations you should see:"
echo "  ✅ 'Storing message in short-term memory'"
echo "  ✅ 'Retrieved X recent messages from short-term'"
echo "  ✅ 'Extracted user facts' (episodic memory)"
echo "  ✅ 'Retrieved user facts' (when asking about name/budget)"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "🧪 Test conversation ID: $CONV_ID"
echo "💾 Messages stored in MongoDB under this conversation_id"
echo ""
