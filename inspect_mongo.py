
import os
import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient

# Add apps/api to path to import config
sys.path.append(os.path.join(os.getcwd(), "apps/api"))

from app import config

async def inspect_product():
    # Force load secrets
    config.settings = config.Settings()
    
    uri = config.settings.MONGODB_URI
    if not uri:
        print("Failed to load MONGODB_URI")
        return

    client = AsyncIOMotorClient(uri)
    db = client["essco-bathware"]
    collection = db["knowledge_base"]
    
    # Find a product chunk
    print("Searching for a product chunk...")
    doc = await collection.find_one({"content_type": "product"})
    
    if doc:
        print("\n--- Document Found ---")
        print(f"Content Type: {doc.get('content_type')}")
        print(f"Product Data keys: {doc.get('product_data', {}).keys()}")
        print("\n--- Product Data Content ---")
        import json
        # Handle datetime objects for json dump
        from datetime import datetime
        def default(o):
            if isinstance(o, datetime):
                return o.isoformat()
            return str(o)
            
        print(json.dumps(doc.get('product_data', {}), indent=2, default=default))
        
        print("\n--- Root Document Keys ---")
        print(doc.keys())
    else:
        print("No product chunk found.")

if __name__ == "__main__":
    asyncio.run(inspect_product())
