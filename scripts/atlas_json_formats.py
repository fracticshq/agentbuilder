#!/usr/bin/env python3
"""
MongoDB Atlas Vector Search Index - All Possible JSON Formats

This script shows EVERY JSON format that different Atlas versions might accept.
Try each one in the JSON Editor until one works.
"""

import json

print("=" * 80)
print("MONGODB ATLAS VECTOR SEARCH INDEX - ALL JSON FORMATS")
print("=" * 80)
print("\nTry these formats in order. Copy/paste into Atlas JSON Editor.\n")
print("Database: agent-builder")
print("Collection: knowledge_base")
print("Index Name: vector_index (set in UI field, NOT in JSON)")
print("=" * 80)

# Format 1: Simple fields array (most common for newer Atlas)
format1 = {
    "fields": [
        {
            "type": "vector",
            "path": "embeddings",
            "numDimensions": 1024,
            "similarity": "cosine"
        }
    ]
}

print("\n📋 FORMAT 1: Simple Fields Array (Try this FIRST)")
print("-" * 80)
print(json.dumps(format1, indent=2))
print("\nInstructions:")
print("1. Go to Atlas → Search → Create Search Index")
print("2. Select 'JSON Editor'")
print("3. Set Index Name field to: vector_index")
print("4. Database: agent-builder, Collection: knowledge_base")
print("5. Paste the JSON above")
print("6. Click Create")

# Format 2: Fields array with filter fields
format2 = {
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
        }
    ]
}

print("\n📋 FORMAT 2: Fields Array with Filters (Try if FORMAT 1 fails)")
print("-" * 80)
print(json.dumps(format2, indent=2))

# Format 3: Mappings structure (older Atlas versions)
format3 = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "embeddings": {
                "type": "knnVector",
                "dimensions": 1024,
                "similarity": "cosine"
            }
        }
    }
}

print("\n📋 FORMAT 3: Mappings Structure (Try if FORMAT 2 fails)")
print("-" * 80)
print(json.dumps(format3, indent=2))

# Format 4: Mappings with filter fields
format4 = {
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
            }
        }
    }
}

print("\n📋 FORMAT 4: Mappings with Filters (Try if FORMAT 3 fails)")
print("-" * 80)
print(json.dumps(format4, indent=2))

# Format 5: Minimal - just vector field
format5 = {
    "fields": [
        {
            "type": "vector",
            "path": "embeddings",
            "numDimensions": 1024,
            "similarity": "cosine"
        }
    ]
}

print("\n📋 FORMAT 5: Absolute Minimal (Last resort)")
print("-" * 80)
print(json.dumps(format5, indent=2))

# Format 6: With name and type (legacy format)
format6 = {
    "name": "vector_index",
    "type": "vectorSearch",
    "fields": [
        {
            "type": "vector",
            "path": "embeddings",
            "numDimensions": 1024,
            "similarity": "cosine"
        }
    ]
}

print("\n📋 FORMAT 6: With Name and Type (Legacy Atlas)")
print("-" * 80)
print(json.dumps(format6, indent=2))
print("\nNOTE: If using this format, you might need to REMOVE the Index Name")
print("from the UI field since it's in the JSON.")

print("\n" + "=" * 80)
print("TROUBLESHOOTING TIPS")
print("=" * 80)
print("""
If ALL formats fail, please provide:
1. The EXACT error message you're seeing
2. Your Atlas cluster tier (M0, M10, M2, etc.)
3. Whether you're on Atlas Shared/Dedicated/Serverless

Common errors and fixes:
- "Please define fields property" → Try FORMAT 1 or FORMAT 2
- "Invalid field type" → Try FORMAT 3 or FORMAT 4  
- "Unknown field: name" → Remove name/type from JSON, set in UI only
- "Unknown field: mappings" → Try FORMAT 1 or FORMAT 2
- "knnVector not supported" → Try "vector" instead of "knnVector"

Alternative: Use Atlas CLI
If the UI keeps failing, you can create the index via command line:

1. Install: brew install mongodb-atlas
2. Login: atlas auth login
3. Create: atlas clusters search indexes create --clusterName YOUR_CLUSTER --file index.json

Where index.json contains FORMAT 6 above.
""")

print("\n" + "=" * 80)
print("WHICH FORMAT TO TRY FIRST?")
print("=" * 80)
print("""
Based on your Atlas version:

✅ Atlas UI (2024+):        Try FORMAT 1 first
✅ Atlas UI (2023):         Try FORMAT 2 first  
✅ Atlas UI (2022 or older): Try FORMAT 3 or FORMAT 4
✅ Atlas Shared Tier (M0):   Try FORMAT 1 (minimal features)
✅ Atlas CLI:               Use FORMAT 6

If you're not sure, just try FORMAT 1 → FORMAT 2 → FORMAT 3 in order.
""")

# Save all formats to files for easy copy/paste
import os
output_dir = "/tmp/atlas_formats"
os.makedirs(output_dir, exist_ok=True)

for i, fmt in enumerate([format1, format2, format3, format4, format5, format6], 1):
    filepath = f"{output_dir}/format{i}.json"
    with open(filepath, 'w') as f:
        json.dump(fmt, f, indent=2)
    print(f"📁 Saved to: {filepath}")

print("\n✅ All formats saved to /tmp/atlas_formats/")
print("You can open these files and copy/paste directly into Atlas.\n")
