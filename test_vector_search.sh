#!/bin/bash
# Test Vector Search once the Atlas index is Active

echo "════════════════════════════════════════════════════════════════"
echo "  TESTING VECTOR SEARCH - Run this after index is ACTIVE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "⏳ First, check your Atlas index status:"
echo "   1. Go to MongoDB Atlas"
echo "   2. Click 'Search' in sidebar"
echo "   3. Find 'vector_index' on 'knowledge_base'"
echo "   4. Status should be 'Active' (not 'Initial Sync')"
echo ""
read -p "Is the index status 'Active'? (y/n): " ready

if [[ $ready != "y" ]]; then
    echo "❌ Please wait for index to become Active, then run this script again."
    exit 1
fi

echo ""
echo "✅ Testing RAG with Vector Search..."
echo ""

# Test query
curl -s -X POST http://localhost:8000/api/v1/messages/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me faucets under 5000 rupees",
    "user_id": "test-vector-search",
    "conversation_id": "test-vector-001",
    "agent_id": "f168131d-7833-4f9c-ac8e-8a19b22c16f3"
  }' | python3 -m json.tool

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  CHECK API LOGS FOR:"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "✅ GOOD signs:"
echo "   - 'Vector search completed' (not 'Vector search error')"
echo "   - 'Retrieved 50 candidates from vector search'"
echo "   - 'context_used: 10+' in response metadata"
echo "   - Multiple product recommendations with prices"
echo ""
echo "❌ BAD signs:"
echo "   - 'Vector search error'"
echo "   - 'Index not found'"
echo "   - 'context_used: 1' (should be 10+)"
echo ""
echo "════════════════════════════════════════════════════════════════"
