#!/usr/bin/env python3
"""
Drop ALL data from MongoDB to start fresh.
This will delete everything and prepare for brand-specific database architecture.
"""

import sys
from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv('apps/api/.env')

def drop_all_data():
    """Drop all collections to start fresh."""
    
    mongo_uri = os.getenv('MONGODB_URI')
    client = MongoClient(mongo_uri)
    
    # Check all databases
    print("📊 Current MongoDB Databases:")
    for db_name in client.list_database_names():
        if db_name not in ['admin', 'local', 'config']:
            db = client[db_name]
            collections = db.list_collection_names()
            print(f"\n  Database: {db_name}")
            for coll in collections:
                count = db[coll].count_documents({})
                print(f"    - {coll}: {count} documents")
    
    print(f"\n{'='*80}")
    print("⚠️  WARNING: This will DELETE ALL DATA")
    print(f"{'='*80}\n")
    
    response = input("Type 'DELETE ALL' to confirm: ")
    
    if response != 'DELETE ALL':
        print("\n❌ Cancelled. No data was deleted.")
        return False
    
    # Drop all non-system databases
    print("\n🗑️  Dropping databases...")
    for db_name in client.list_database_names():
        if db_name not in ['admin', 'local', 'config']:
            print(f"  Dropping: {db_name}")
            client.drop_database(db_name)
    
    print("\n✅ All data dropped successfully!")
    print("\n📋 Next Steps:")
    print("  1. Update code to use brand-specific databases")
    print("  2. Re-upload product data via Admin Dashboard")
    print("  3. Test product cards in widget")
    
    return True

if __name__ == '__main__':
    success = drop_all_data()
    sys.exit(0 if success else 1)
