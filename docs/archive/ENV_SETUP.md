# Environment Configuration Guide

This guide explains how to set up environment variables for the Agent Builder Platform.

## 🚀 Quick Start

### 1. Copy Example Files

```bash
# Root configuration
cp .env.example .env

# API configuration
cp apps/api/.env.example apps/api/.env

# Widget configuration
cp apps/widget/.env.example apps/widget/.env

# Admin dashboard configuration
cp apps/admin/.env.example apps/admin/.env
```

### 2. Generate Required Keys

```bash
# Generate SECRET_KEY and JWT_SECRET
openssl rand -hex 32

# Generate PII_ENCRYPTION_KEY (Python required)
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

### 3. Update Configuration Files

Edit each `.env` file and replace placeholder values with your actual credentials.

---

## 📋 Configuration Files

### Root `.env`
**Location:** `/agent-builder/.env`  
**Purpose:** Shared configuration for all applications

**Required Variables:**
- `MONGODB_URI` - MongoDB Atlas connection string
- `SECRET_KEY` - Application secret key
- `PII_ENCRYPTION_KEY` - Encryption key for sensitive data

### API `.env`
**Location:** `/agent-builder/apps/api/.env`  
**Purpose:** Backend API server configuration

**Required Variables:**
- `OPENAI_API_KEY` - OpenAI API key for LLM
- `VOYAGE_API_KEY` - Voyage AI key for embeddings
- `MONGODB_URI` - MongoDB connection string
- `PII_ENCRYPTION_KEY` - PII encryption key (32-byte base64)

**Optional Variables:**
- `QWEN_API_KEY` - Alternative LLM provider
- `REDIS_URL` - Redis for caching (optional, MongoDB fallback)

### Widget `.env`
**Location:** `/agent-builder/apps/widget/.env`  
**Purpose:** React widget configuration

**Required Variables:**
- `VITE_API_BASE_URL` - API server URL
- `VITE_API_WS_URL` - WebSocket server URL

### Admin `.env`
**Location:** `/agent-builder/apps/admin/.env`  
**Purpose:** Admin dashboard configuration

**Required Variables:**
- `REACT_APP_API_BASE_URL` - API server URL
- `REACT_APP_JWT_SECRET` - JWT secret for authentication

---

## 🔑 Obtaining API Keys

### MongoDB Atlas
1. Sign up at https://www.mongodb.com/cloud/atlas
2. Create a cluster
3. Get connection string from **Connect** → **Connect your application**
4. Replace `<username>` and `<password>` in the connection string

### OpenAI API Key
1. Sign up at https://platform.openai.com/
2. Navigate to **API Keys**
3. Create a new secret key
4. Copy and save securely (it won't be shown again)

### Voyage AI API Key
1. Sign up at https://www.voyageai.com/
2. Navigate to **API Keys**
3. Create a new API key
4. Copy the key (format: `pa-...`)

### Redis (Optional)
- **Local:** Install Redis and use `redis://localhost:6379`
- **Cloud:** Use services like Redis Cloud, AWS ElastiCache, or Upstash
- **Not Required:** MongoDB fallback is available

---

## 🔒 Security Best Practices

### 1. Never Commit Secrets
- `.env` files are in `.gitignore` - they should **never** be committed
- Use `.env.example` files as templates
- Share credentials securely (1Password, AWS Secrets Manager, etc.)

### 2. Use Strong Keys
```bash
# Generate strong random keys
openssl rand -hex 32

# For PII encryption (base64 encoded)
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

### 3. Rotate Keys Regularly
- Change API keys every 90 days
- Rotate JWT secrets on security incidents
- Update PII encryption keys carefully (requires data re-encryption)

### 4. Environment-Specific Configuration
- **Development:** Use separate API keys, lower rate limits
- **Staging:** Mirror production config, use test data
- **Production:** Strong secrets, strict CORS, enable monitoring

### 5. Secure Storage
- **Local Development:** Use `.env` files (never commit)
- **CI/CD:** Use GitHub Secrets, GitLab CI/CD variables
- **Production:** Use AWS Secrets Manager, Azure Key Vault, or similar

---

## 📁 File Locations

```
agent-builder/
├── .env                      # Root config (shared)
├── .env.example             # Root config template ✅
├── apps/
│   ├── api/
│   │   ├── .env            # API config
│   │   └── .env.example    # API config template ✅
│   ├── widget/
│   │   ├── .env            # Widget config
│   │   └── .env.example    # Widget config template ✅
│   └── admin/
│       ├── .env            # Admin config
│       └── .env.example    # Admin config template ✅
```

**✅ = Safe to commit**  
**🔒 = Never commit (in .gitignore)**

---

## 🧪 Testing Configuration

### Validate API Configuration
```bash
cd apps/api
python -c "
from dotenv import load_dotenv
import os

load_dotenv()

print('✅ OPENAI_API_KEY:', '✓' if os.getenv('OPENAI_API_KEY') else '✗')
print('✅ VOYAGE_API_KEY:', '✓' if os.getenv('VOYAGE_API_KEY') else '✗')
print('✅ MONGODB_URI:', '✓' if os.getenv('MONGODB_URI') else '✗')
print('✅ PII_ENCRYPTION_KEY:', '✓' if os.getenv('PII_ENCRYPTION_KEY') else '✗')
"
```

### Test MongoDB Connection
```bash
cd apps/api
python -c "
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test_mongo():
    client = AsyncIOMotorClient(os.getenv('MONGODB_URI'))
    try:
        await client.admin.command('ping')
        print('✅ MongoDB connection successful!')
    except Exception as e:
        print(f'❌ MongoDB connection failed: {e}')
    finally:
        client.close()

asyncio.run(test_mongo())
"
```

---

## 🆘 Troubleshooting

### Issue: "Environment variable not found"
**Solution:** Ensure `.env` file exists and contains the required variable.

```bash
# Check if .env file exists
ls -la apps/api/.env

# Verify variable is set
grep OPENAI_API_KEY apps/api/.env
```

### Issue: "Invalid MongoDB connection string"
**Solution:** Verify connection string format:
```
mongodb+srv://username:password@cluster.mongodb.net/database?options
```

### Issue: "PII encryption key invalid"
**Solution:** Generate a new 32-byte base64 key:
```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

### Issue: "CORS error in widget"
**Solution:** Add widget URL to `CORS_ALLOW_ORIGINS` in API `.env`:
```properties
CORS_ALLOW_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

---

## 🔄 Migration Guide

### Updating from Old Configuration
If you have existing `.env` files without Phase 5 memory configuration:

```bash
# Add Phase 5 memory configuration
cat >> apps/api/.env << 'EOF'

# =============================================================================
# Memory System Configuration (Phase 5)
# =============================================================================

# PII Encryption (32-byte key, base64 encoded)
PII_ENCRYPTION_KEY=$(python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())")

# Memory TTLs (in seconds)
SHORT_TERM_TTL=259200          # 72 hours
EPISODIC_TTL=7776000           # 90 days
SUMMARY_CACHE_TTL=86400        # 24 hours

# Memory Thresholds
CONFIDENCE_THRESHOLD=0.70
AUTO_SUMMARY_TURNS=4

# Feature Flags
ENABLE_AUTO_SUMMARY=true
ENABLE_PII_VAULTING=true
ENABLE_FACT_EXTRACTION=true
ENABLE_GRAPH_RULES=true

EOF
```

---

## 📚 Related Documentation

- [AGENTS.md](../AGENTS.md) - System architecture and contracts
- [PHASE5_FINAL.md](../PHASE5_FINAL.md) - Memory system documentation
- [README.md](../README.md) - Project overview

---

## 🤝 Need Help?

- Check the [Troubleshooting](#-troubleshooting) section above
- Review error logs in `apps/api/server.log`
- Verify all required services are running (MongoDB, Redis)
- Ensure API keys are valid and have sufficient credits

---

**Last Updated:** October 14, 2024  
**Version:** 1.0.0 (Phase 5)
