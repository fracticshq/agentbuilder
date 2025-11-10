# Brand-Specific Database Architecture Implementation

## Overview

This implementation provides **complete data isolation** between brands by using dedicated MongoDB databases for each brand. This ensures:

- ✅ **Complete data isolation** between brands
- ✅ **Independent scaling** per brand  
- ✅ **Better security** (no cross-brand data leakage)
- ✅ **Easier backup/restore** per brand
- ✅ **Cleaner data management** and compliance

## Database Structure

```
MongoDB Atlas Cluster
├── system/                       ← System database
│   ├── brands                   ← Brand registry and metadata
│   ├── users                    ← Global user accounts  
│   ├── agents                   ← Agent configurations (centralized)
│   └── audit_logs               ← System-wide audit trail
│
├── essco-bathware/              ← Brand-specific database
│   ├── knowledge_base           ← Document chunks + embeddings
│   ├── conversations            ← Chat history
│   ├── short_term_memory        ← Rolling conversation buffer
│   ├── episodic_memory          ← User facts/preferences (PII vaulted)
│   ├── semantic_memory          ← Knowledge base versioning
│   └── graph_memory             ← Rules, policies, escalations
│
├── acme-corp/                   ← Another brand's database
│   ├── knowledge_base
│   ├── conversations
│   └── ...
│
└── demo-brand/
    └── ...
```

## Environment Variables

Add to your `.env` file:

```bash
# MongoDB Configuration
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/
MONGO_SYSTEM_DB=system                    # System database name (optional, defaults to "system")

# Existing variables remain the same
VOYAGE_API_KEY=your-voyage-key
OPENAI_API_KEY=your-openai-key
# ... etc
```

## API Changes

### Connection Manager

The connection manager now supports multiple databases:

```python
# Get system database (brands, users, agents)
system_db = connection_manager.get_system_db()

# Get brand-specific database
brand_db = connection_manager.get_brand_db("essco-bathware")

# Get brand database by agent ID (automatic brand lookup)
brand_db = await connection_manager.get_brand_db_by_agent_id(agent_id)
```

### Agents Collection

Agents are now stored in the **system database** with brand association:

```json
{
  "id": "essco-agent-001",
  "name": "Essco Bathware Assistant", 
  "brand_slug": "essco-bathware",
  "system_prompt": "...",
  "configuration": {...},
  "status": "active"
}
```

### Brand Data Isolation

All brand-specific data is stored in separate databases:

- **Knowledge Base**: `essco-bathware.knowledge_base`
- **Conversations**: `essco-bathware.conversations`
- **Memory**: `essco-bathware.episodic_memory`, etc.

## Migration Process

### 1. Setup New Database Structure

Run the setup script to create the new database architecture:

```bash
# Create system database and sample brands
python scripts/setup_brand_databases.py --brands essco-bathware,acme-corp --create-sample-data
```

### 2. Migrate Existing Data (Optional)

If you have existing data in a single database, migrate it:

```bash
# Analyze existing data structure (dry run)
python scripts/migrate_to_brand_databases.py --source-db agent-builder --dry-run

# Execute migration 
python scripts/migrate_to_brand_databases.py --source-db agent-builder --execute
```

## Code Changes Made

### 1. Connection Manager (`apps/api/app/connections.py`)

- Added `system_db` and `brand_db_cache` properties
- New methods: `get_system_db()`, `get_brand_db()`, `get_brand_db_by_agent_id()`
- Database connection caching for performance

### 2. Message Service (`apps/api/app/services/message_service.py`)

- Updated to initialize brand-specific database per agent
- Memory systems now use brand databases
- Agent configuration loaded from system database

### 3. Ingestion Service (`apps/api/app/services/ingestion_service.py`)

- Document chunks stored in brand-specific `knowledge_base` collections
- Agent-based database routing for document retrieval

### 4. Admin API Endpoints

- **Brands API** (`apps/api/app/api/v1/admin/brands.py`): Uses system database
- **Agents API** (`apps/api/app/api/v1/admin/agents.py`): Uses system database

### 5. Configuration (`apps/api/app/config.py`)

- Added `MONGO_SYSTEM_DB` environment variable
- Legacy `MONGODB_DATABASE` marked as deprecated

## Benefits

### 1. Data Isolation
Each brand's data is completely separate - no risk of cross-brand data leakage.

### 2. Scalability
- Independent database scaling per brand
- Separate connection pools and resources
- Brand-specific performance optimization

### 3. Security & Compliance
- Brand data isolation for regulatory compliance
- Easier data deletion for GDPR/CCPA requests
- Separate backup and restore policies

### 4. Operational Benefits
- Brand-specific maintenance windows
- Independent database migrations
- Clearer monitoring and alerting

## Database Indexes

Each brand database includes optimized indexes:

```javascript
// Knowledge base (vector search)
db.knowledge_base.createIndex({"embeddings": "2dsphere"})
db.knowledge_base.createIndex({"doc_id": 1})
db.knowledge_base.createIndex({"metadata.sku": 1})

// Conversations
db.conversations.createIndex({"conversation_id": 1})
db.conversations.createIndex({"user_id": 1, "timestamp": -1})

// Memory systems
db.episodic_memory.createIndex({"user_id": 1, "confidence": -1})
db.short_term_memory.createIndex({"conversation_id": 1, "timestamp": 1})
```

## Monitoring

### Database Usage

Check database sizes and document counts:

```javascript
// System database stats
use system
db.stats()
db.brands.countDocuments()
db.agents.countDocuments()

// Brand database stats  
use "essco-bathware"
db.stats()
db.knowledge_base.countDocuments()
db.conversations.countDocuments()
```

### Performance Monitoring

- Monitor connection pool usage per brand
- Track query performance across brand databases
- Set up alerts for database-specific metrics

## Backwards Compatibility

### Legacy Support

The implementation includes backwards compatibility:

- `get_mongodb_db()` method still works (deprecated warning)
- Existing single-database deployments continue to function
- Gradual migration path available

### Migration Strategy

1. **Phase 1**: Deploy new code (backwards compatible)
2. **Phase 2**: Run migration scripts during maintenance
3. **Phase 3**: Update environment variables
4. **Phase 4**: Remove legacy database references

## Troubleshooting

### Common Issues

**Agent not found error:**
```
ValueError: Agent not found: agent-id
```
- Ensure agent exists in system database
- Check agent has `brand_slug` field

**Database connection issues:**
```
RuntimeError: MongoDB not connected
```
- Verify `MONGODB_URI` is set correctly
- Check network connectivity to MongoDB Atlas

**Missing brand database:**
- Run setup script to create brand databases
- Verify brand exists in system.brands collection

### Debug Queries

```javascript
// Check agent-to-brand mapping
db.agents.find({}, {id: 1, brand_slug: 1, name: 1})

// Verify brand databases exist
show databases

// Count documents per brand
use "essco-bathware"
db.knowledge_base.countDocuments()
```

## Next Steps

1. **Deploy**: Update production environment variables
2. **Monitor**: Set up database monitoring for new structure
3. **Optimize**: Fine-tune indexes based on usage patterns  
4. **Scale**: Add new brands using the setup script
5. **Backup**: Configure brand-specific backup strategies

---

**Implementation Complete!** ✅

Your Agent Builder Platform now supports complete brand data isolation while maintaining high performance and operational flexibility.