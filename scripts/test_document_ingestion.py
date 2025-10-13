"""
Test Document Ingestion
Uploads sample documents to test the RAG pipeline
"""

import os
import asyncio
import uuid
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import structlog

logger = structlog.get_logger()


# Sample documents for testing
SAMPLE_DOCUMENTS = [
    {
        "doc_id": "essco-faucet-install-001",
        "chunk_id": str(uuid.uuid4()),
        "title": "Kitchen Faucet Installation Guide",
        "content": """
To install your Essco kitchen faucet, follow these steps:
1. Turn off the water supply valves under the sink
2. Remove the old faucet if present
3. Clean the mounting surface thoroughly
4. Position the new faucet and gasket
5. Secure with mounting nuts from below
6. Connect supply lines (hot and cold)
7. Turn on water and check for leaks
8. Test all functions including spray mode

Important: Use plumber's tape on threaded connections. Tighten connections hand-tight plus 1/4 turn.
        """.strip(),
        "section": "Installation",
        "url": "https://essco.com/support/faucet-installation",
        "metadata": {
            "content_type": "manual",
            "brand_id": "essco-bathware",
            "product_category": "faucets",
            "sku": "ESSCO-FAUCET-001",
            "language": "en"
        },
        "created_at": datetime.utcnow()
    },
    {
        "doc_id": "essco-faucet-troubleshoot-001",
        "chunk_id": str(uuid.uuid4()),
        "title": "Faucet Troubleshooting - Low Water Pressure",
        "content": """
If you're experiencing low water pressure from your faucet:

Possible Causes:
- Clogged aerator screen
- Partially closed supply valves
- Sediment in supply lines
- Clogged cartridge

Solutions:
1. Remove and clean the aerator - unscrew the tip and rinse the screen
2. Check that supply valves are fully open
3. Inspect supply lines for kinks or blockages
4. If problems persist, the cartridge may need cleaning or replacement

Most low pressure issues are resolved by cleaning the aerator, which should be done every 3-6 months.
        """.strip(),
        "section": "Troubleshooting",
        "url": "https://essco.com/support/troubleshooting/low-pressure",
        "metadata": {
            "content_type": "faq",
            "brand_id": "essco-bathware",
            "product_category": "faucets",
            "language": "en"
        },
        "created_at": datetime.utcnow()
    },
    {
        "doc_id": "essco-faucet-warranty-001",
        "chunk_id": str(uuid.uuid4()),
        "title": "Faucet Warranty Information",
        "content": """
Essco Bathware Faucet Warranty

Lifetime Limited Warranty:
- Covers defects in materials and workmanship
- Valid for original purchaser and original installation
- Covers faucet body, cartridge, and finish (excluding normal wear)

What's Not Covered:
- Damage from improper installation
- Damage from water quality issues (hard water, sediment)
- Normal wear and tear
- Commercial use

To File a Claim:
1. Contact Essco customer service at 1-800-ESSCO-01
2. Provide proof of purchase and photos
3. Our team will evaluate and process your claim
4. Approved claims receive free replacement parts

Warranty registration: essco.com/warranty-registration
        """.strip(),
        "section": "Warranty",
        "url": "https://essco.com/warranty/faucets",
        "metadata": {
            "content_type": "policy",
            "brand_id": "essco-bathware",
            "product_category": "faucets",
            "language": "en"
        },
        "created_at": datetime.utcnow()
    },
    {
        "doc_id": "essco-shower-install-001",
        "chunk_id": str(uuid.uuid4()),
        "title": "Shower System Installation",
        "content": """
Installing Your Essco Shower System:

Pre-Installation Requirements:
- Rough-in valve should be installed during construction
- Wall must be finished and waterproofed
- Access to plumbing behind wall required

Installation Steps:
1. Install the valve trim kit
2. Connect the shower head arm and head
3. Install handheld shower bracket if included
4. Connect diverter if using multiple outlets
5. Seal all wall penetrations with silicone
6. Turn on water and test all functions
7. Adjust temperature limit stop as needed

Professional installation recommended for valve replacement. DIY suitable for trim kit replacement only.
        """.strip(),
        "section": "Installation",
        "url": "https://essco.com/support/shower-installation",
        "metadata": {
            "content_type": "manual",
            "brand_id": "essco-bathware",
            "product_category": "showers",
            "sku": "ESSCO-SHOWER-001",
            "language": "en"
        },
        "created_at": datetime.utcnow()
    },
    {
        "doc_id": "essco-maintenance-001",
        "chunk_id": str(uuid.uuid4()),
        "title": "General Maintenance Tips",
        "content": """
Keeping Your Essco Products in Top Condition:

Daily Care:
- Wipe down after use with soft cloth
- Remove water spots promptly
- Avoid abrasive cleaners

Monthly Maintenance:
- Clean aerators and shower heads
- Check for leaks around connections
- Inspect supply line connections

Quarterly:
- Deep clean with mild soap solution
- Check and tighten mounting hardware
- Lubricate moving parts if needed

Recommended Cleaners:
- Mild dish soap and water
- White vinegar for mineral deposits
- Avoid: Bleach, ammonia, abrasive pads

Regular maintenance extends product life and maintains appearance.
        """.strip(),
        "section": "Maintenance",
        "url": "https://essco.com/support/maintenance",
        "metadata": {
            "content_type": "article",
            "brand_id": "essco-bathware",
            "product_category": "general",
            "language": "en"
        },
        "created_at": datetime.utcnow()
    }
]


class DocumentIngestion:
    """Test document ingestion into MongoDB."""
    
    def __init__(self):
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        db_name = os.getenv("MONGODB_DATABASE", "agent-builder")
        
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]
        self.collection = self.db["knowledge_base"]
        logger.info("Document ingestion initialized", database=db_name)
    
    async def clear_existing_documents(self):
        """Clear existing test documents."""
        result = await self.collection.delete_many({
            "metadata.brand_id": "essco-bathware"
        })
        logger.info(f"Cleared {result.deleted_count} existing documents")
    
    async def insert_documents(self, generate_embeddings: bool = False):
        """Insert sample documents."""
        logger.info(f"Inserting {len(SAMPLE_DOCUMENTS)} sample documents...")
        
        if generate_embeddings:
            # Generate embeddings using Voyage
            from retrieval.vector.voyage_client import VoyageClient
            
            try:
                voyage = VoyageClient()
                logger.info("Generating embeddings with Voyage AI...")
                
                texts = [doc["content"] for doc in SAMPLE_DOCUMENTS]
                embeddings = await voyage.embed_documents(texts)
                
                # Add embeddings to documents
                for doc, embedding in zip(SAMPLE_DOCUMENTS, embeddings):
                    doc["embeddings"] = embedding
                
                await voyage.close()
                logger.info("✅ Embeddings generated successfully")
                
            except Exception as e:
                logger.warning(
                    "Failed to generate embeddings, inserting without them",
                    error=str(e)
                )
        
        # Insert documents
        result = await self.collection.insert_many(SAMPLE_DOCUMENTS)
        logger.info(f"✅ Inserted {len(result.inserted_ids)} documents")
        
        return result.inserted_ids
    
    async def verify_documents(self):
        """Verify documents were inserted correctly."""
        logger.info("\n=== Verifying Documents ===")
        
        count = await self.collection.count_documents({
            "metadata.brand_id": "essco-bathware"
        })
        logger.info(f"Total Essco documents: {count}")
        
        # Sample one document
        sample = await self.collection.find_one({
            "metadata.brand_id": "essco-bathware"
        })
        
        if sample:
            logger.info(f"\nSample document:")
            logger.info(f"  Title: {sample.get('title')}")
            logger.info(f"  Content length: {len(sample.get('content', ''))} chars")
            logger.info(f"  Has embeddings: {'embeddings' in sample}")
            logger.info(f"  Content type: {sample.get('metadata', {}).get('content_type')}")
    
    async def test_text_search(self):
        """Test text search functionality."""
        logger.info("\n=== Testing Text Search ===")
        
        query = "install faucet"
        logger.info(f"Searching for: '{query}'")
        
        cursor = self.collection.find(
            {"$text": {"$search": query}},
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})]).limit(3)
        
        results = await cursor.to_list(length=3)
        
        if results:
            logger.info(f"Found {len(results)} results:")
            for i, result in enumerate(results, 1):
                logger.info(f"  {i}. {result.get('title')} (score: {result.get('score', 0):.2f})")
        else:
            logger.warning("No results found. Text index may not be created yet.")
            logger.info("Run: python scripts/setup_mongodb_indexes.py")
    
    async def run_all(self, clear_first: bool = True, with_embeddings: bool = False):
        """Run complete ingestion test."""
        try:
            if clear_first:
                await self.clear_existing_documents()
            
            await self.insert_documents(generate_embeddings=with_embeddings)
            await self.verify_documents()
            await self.test_text_search()
            
            logger.info("\n✅ Document ingestion test completed successfully!")
            
        except Exception as e:
            logger.error("Ingestion test failed", error=str(e), exc_info=True)
            raise
        finally:
            self.client.close()


async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test document ingestion")
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing documents first"
    )
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Generate embeddings using Voyage AI (requires VOYAGE_API_KEY)"
    )
    args = parser.parse_args()
    
    # Configure logging
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    ingestion = DocumentIngestion()
    await ingestion.run_all(
        clear_first=not args.no_clear,
        with_embeddings=args.with_embeddings
    )


if __name__ == "__main__":
    # Load environment variables
    from pathlib import Path
    env_file = Path(__file__).parent.parent / "apps" / "api" / ".env"
    
    if env_file.exists():
        print(f"Loading environment from {env_file}")
        from dotenv import load_dotenv
        load_dotenv(env_file)
    else:
        print("⚠️  No .env file found, using system environment variables")
    
    # Run ingestion
    asyncio.run(main())
