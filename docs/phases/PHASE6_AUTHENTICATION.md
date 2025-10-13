# Phase 6: Authentication & Security

## 🎯 Objectives

Implement a comprehensive authentication and authorization system with:
1. JWT (JSON Web Token) authentication
2. API key management for programmatic access
3. Rate limiting per user/API key
4. Role-Based Access Control (RBAC)
5. Security middleware and dependencies

---

## 📋 Implementation Plan

### 1. JWT Authentication System
- [x] JWT token generation and validation
- [x] User authentication endpoints (login, register, refresh)
- [x] Password hashing with bcrypt
- [x] Token refresh mechanism
- [x] JWT dependency for protected routes

### 2. API Key Management
- [x] API key generation and storage
- [x] API key authentication
- [x] API key scopes and permissions
- [x] API key rotation and revocation
- [x] API key rate limiting

### 3. Rate Limiting
- [x] Redis-based rate limiter
- [x] Per-user rate limiting
- [x] Per-API-key rate limiting
- [x] Per-IP rate limiting
- [x] Configurable limits by endpoint

### 4. Role-Based Access Control (RBAC)
- [x] User roles (admin, user, viewer)
- [x] Permission system
- [x] Role-based route protection
- [x] Brand-level access control

### 5. Security Features
- [x] Password strength validation
- [x] Account lockout after failed attempts
- [x] Security headers middleware
- [x] Request validation
- [x] Audit logging

---

## 🏗️ Architecture

### Authentication Flow

```
┌──────────────────────────────────────────────────────────┐
│                    Client Request                        │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│              Authentication Middleware                   │
│  ├─ Check Authorization Header                          │
│  ├─ Validate JWT Token OR API Key                       │
│  └─ Extract User/API Key Info                           │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│                Rate Limiting Check                       │
│  ├─ Check Redis for rate limit status                   │
│  ├─ Increment request counter                           │
│  └─ Return 429 if limit exceeded                        │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│            Authorization Check (RBAC)                    │
│  ├─ Check user role                                     │
│  ├─ Check resource permissions                          │
│  └─ Return 403 if unauthorized                          │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│                  Process Request                         │
│  └─ Execute business logic                              │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│              Audit Log (if enabled)                      │
│  └─ Log request, user, action, result                   │
└──────────────────────────────────────────────────────────┘
```

---

## 📦 Components

### 1. Authentication Module
**Location:** `apps/api/app/auth/`

```
auth/
├── __init__.py
├── jwt.py              # JWT token operations
├── password.py         # Password hashing/validation
├── api_keys.py         # API key management
├── dependencies.py     # FastAPI dependencies
├── middleware.py       # Auth middleware
└── models.py           # Auth data models
```

### 2. Security Module
**Location:** `apps/api/app/security/`

```
security/
├── __init__.py
├── rate_limiter.py     # Rate limiting logic
├── rbac.py             # Role-based access control
├── permissions.py      # Permission definitions
└── audit.py            # Audit logging
```

### 3. API Endpoints
**Location:** `apps/api/app/api/v1/auth/`

```
auth/
├── __init__.py
├── login.py            # Login endpoint
├── register.py         # User registration
├── tokens.py           # Token management
└── api_keys.py         # API key endpoints
```

---

## 🗄️ Database Schema

### Users Collection
```javascript
{
  _id: ObjectId,
  email: string,              // Unique
  username: string,           // Unique
  password_hash: string,      // bcrypt hash
  full_name: string,
  role: string,               // admin, user, viewer
  brands: [string],           // Brand IDs user has access to
  is_active: boolean,
  is_verified: boolean,
  failed_login_attempts: int,
  locked_until: datetime,
  last_login: datetime,
  created_at: datetime,
  updated_at: datetime,
  metadata: object
}
```

### API Keys Collection
```javascript
{
  _id: ObjectId,
  key_id: string,            // Public identifier (first 8 chars of key)
  key_hash: string,          // Hashed API key
  user_id: ObjectId,         // Owner
  name: string,              // User-friendly name
  scopes: [string],          // Permissions (read, write, admin)
  brand_ids: [string],       // Accessible brands
  rate_limit: {
    requests_per_minute: int,
    requests_per_day: int
  },
  usage: {
    total_requests: int,
    last_used: datetime
  },
  is_active: boolean,
  expires_at: datetime,
  created_at: datetime,
  revoked_at: datetime
}
```

### Refresh Tokens Collection
```javascript
{
  _id: ObjectId,
  token_hash: string,        // Hashed refresh token
  user_id: ObjectId,
  expires_at: datetime,
  is_revoked: boolean,
  created_at: datetime,
  revoked_at: datetime,
  device_info: string
}
```

### Rate Limits (Redis)
```
rate_limit:user:{user_id}:{endpoint}:{window}
rate_limit:api_key:{key_id}:{endpoint}:{window}
rate_limit:ip:{ip_address}:{endpoint}:{window}
```

---

## 🔐 Security Features

### 1. Password Requirements
- Minimum 8 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 number
- At least 1 special character

### 2. Account Lockout
- Lock account after 5 failed login attempts
- Lock duration: 15 minutes
- Reset counter on successful login

### 3. JWT Configuration
- Access Token: 30 minutes expiry
- Refresh Token: 7 days expiry
- Algorithm: HS256
- Claims: user_id, email, role, brands

### 4. API Key Format
```
ab_live_1234567890abcdef1234567890abcdef
├── ab_      Prefix
├── live_    Environment
└── ...      32-char random hex
```

### 5. Rate Limiting Tiers
```python
FREE_TIER = {
    "requests_per_minute": 10,
    "requests_per_day": 1000
}

PRO_TIER = {
    "requests_per_minute": 60,
    "requests_per_day": 10000
}

ENTERPRISE_TIER = {
    "requests_per_minute": 300,
    "requests_per_day": 100000
}
```

---

## 🔧 Configuration

### Environment Variables

```env
# JWT Configuration
JWT_SECRET_KEY=your-super-secret-jwt-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Password Configuration
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=true
PASSWORD_REQUIRE_LOWERCASE=true
PASSWORD_REQUIRE_NUMBERS=true
PASSWORD_REQUIRE_SPECIAL=true

# Account Security
MAX_LOGIN_ATTEMPTS=5
ACCOUNT_LOCKOUT_DURATION_MINUTES=15

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_REQUESTS_PER_DAY=10000
RATE_LIMIT_STRATEGY=sliding_window

# API Keys
API_KEY_PREFIX=ab
API_KEY_LENGTH=32
API_KEY_DEFAULT_EXPIRY_DAYS=365

# Security Headers
ENABLE_SECURITY_HEADERS=true
ENABLE_CORS=true
ENABLE_AUDIT_LOGGING=true
```

---

## 🧪 Testing Plan

### Unit Tests
- [ ] JWT token generation/validation
- [ ] Password hashing/verification
- [ ] API key generation/validation
- [ ] Rate limiter logic
- [ ] RBAC permission checks

### Integration Tests
- [ ] Login flow
- [ ] Token refresh flow
- [ ] API key authentication
- [ ] Rate limiting enforcement
- [ ] Permission-based access

### Security Tests
- [ ] Token tampering
- [ ] Expired token handling
- [ ] Invalid credentials
- [ ] Rate limit bypass attempts
- [ ] RBAC bypass attempts

---

## 📊 Success Metrics

- [ ] JWT authentication working
- [ ] API key authentication working
- [ ] Rate limiting enforced
- [ ] RBAC permissions enforced
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Security audit passed

---

## 🚀 Implementation Order

1. **Auth Core** (2-3 hours)
   - JWT operations
   - Password hashing
   - User models

2. **API Keys** (1-2 hours)
   - API key generation
   - API key authentication
   - Key management endpoints

3. **Rate Limiting** (1-2 hours)
   - Redis-based limiter
   - Per-user/key/IP limits
   - Middleware integration

4. **RBAC** (1 hour)
   - Role definitions
   - Permission checks
   - Route protection

5. **Auth Endpoints** (2 hours)
   - Login/Register
   - Token refresh
   - API key CRUD

6. **Testing** (2 hours)
   - Unit tests
   - Integration tests
   - Security tests

**Total Estimated Time:** 9-12 hours

---

## 📚 Dependencies

```txt
# Authentication
PyJWT==2.8.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6

# Security
python-jose[cryptography]==3.3.0
cryptography==41.0.7

# Rate Limiting
redis==5.0.1
aioredis==2.0.1
```

---

## 🎯 Next Steps After Phase 6

1. **Phase 7:** Observability & Monitoring
2. **Phase 8:** Deployment & CI/CD
3. **Phase 9:** Performance Optimization
4. **Phase 10:** Production Hardening

---

**Status:** Ready to implement  
**Priority:** High - Required for production  
**Complexity:** Medium  
**Dependencies:** Redis, MongoDB
