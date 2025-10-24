"""
Verify and display the required MongoDB Atlas Vector Search index configuration.
The index must be created manually through the MongoDB Atlas UI.
"""

import json

# Full index configuration (for reference)
full_index_config = {
    "name": "vector_index",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embeddings",
                "numDimensions": 1024,
                "similarity": "cosine"
            },
            {
                "type": "filter",
                "path": "agent_id"
            },
            {
                "type": "filter",
                "path": "doc_id"
            },
            {
                "type": "filter",  
                "path": "metadata.content_type"
            }
        ]
    }
}

# JSON Editor format (what you actually paste in Atlas)
json_editor_format = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "embeddings": {
                "type": "knnVector",
                "dimensions": 1024,
                "similarity": "cosine"
            },
            "agent_id": {
                "type": "token"
            },
            "doc_id": {
                "type": "token"
            },
            "metadata": {
                "type": "document",
                "fields": {
                    "content_type": {
                        "type": "token"
                    }
                }
            }
        }
    }
}

print("=" * 80)
print("MONGODB ATLAS VECTOR SEARCH INDEX CONFIGURATION")
print("=" * 80)
print("\nDatabase: agent-builder")
print("Collection: knowledge_base")
print("Index Name: vector_index")
print("\n" + "=" * 80)
print("PASTE THIS IN ATLAS JSON EDITOR:")
print("=" * 80)
print(json.dumps(json_editor_format, indent=2))
print("\n" + "=" * 80)
print("FULL INDEX CONFIGURATION (FOR REFERENCE):")
print("=" * 80)
print(json.dumps(full_index_config, indent=2))
print("\n" + "=" * 80)
print("INSTRUCTIONS:")
print("=" * 80)
print("""
METHOD 1: JSON EDITOR (Use the format above)
1. Go to: https://cloud.mongodb.com
2. Navigate to: Data Services > Browse Collections
3. Select database: agent-builder
4. Select collection: knowledge_base
5. Click on "Search Indexes" tab (NOT "Indexes")
6. Click "Create Search Index"
7. Choose "JSON Editor"
8. Index Name field: vector_index
9. Paste ONLY the "PASTE THIS IN ATLAS JSON EDITOR" format above
   (WITHOUT the "name" and "type" fields - they go in UI fields!)
10. Click "Next" > "Create Search Index"

METHOD 2: VISUAL EDITOR (Easier!)
1. Go to: https://cloud.mongodb.com
2. Navigate to: Data Services > Browse Collections
3. Select database: agent-builder
4. Select collection: knowledge_base
5. Click on "Search Indexes" tab
6. Click "Create Search Index"
7. Choose "Visual Editor"
8. Index Name: vector_index
9. Click "Next"
10. Add Vector Field:
    - Field Name: embeddings
    - Dimensions: 1024
    - Similarity: cosine
11. Add Filter Fields (click "+ Add Field" for each):
    - agent_id (type: token)
    - doc_id (type: token)
    - metadata.content_type (type: token)
12. Click "Create Search Index"

IMPORTANT: 
- Index creation takes 2-5 minutes
- Wait for status to change from "Initial Sync" to "Active"
- Refresh the page to check status
""")
print("=" * 80)
