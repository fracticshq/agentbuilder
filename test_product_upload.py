#!/usr/bin/env python3
"""
Test product upload directly to see any errors.
"""
import asyncio
import httpx

async def test_upload():
    url = "http://localhost:8000/api/v1/knowledge/bulk-upload"
    
    data = {
        "content_type": "product",
        "brand_id": "essco-bathware",  # Use simple string, not UUID
        "items": [
            {
                "sku": "TEST-001",
                "name": "Test Product",
                "price": 1000,
                "currency": "INR",
                "category": "Test Category",
                "in_stock": True,
                "features": ["Feature 1", "Feature 2"],
                "image_url": "https://example.com/test.jpg",
                "product_url": "https://example.com/test"
            }
        ]
    }
    
    print("📤 Sending test upload...")
    print(f"URL: {url}")
    print(f"Data: {data}")
    print()
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=data)
        
        print(f"✅ Response status: {response.status_code}")
        print(f"Response body: {response.json()}")
        
        if response.status_code == 200:
            job_id = response.json()["job_id"]
            print(f"\n⏳ Waiting 5 seconds for background processing...")
            await asyncio.sleep(5)
            
            # Check job status
            status_response = await client.get(f"http://localhost:8000/api/v1/knowledge/jobs/{job_id}")
            print(f"\n📊 Job status: {status_response.json()}")

if __name__ == "__main__":
    asyncio.run(test_upload())
