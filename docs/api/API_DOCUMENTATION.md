# Agent Builder Platform - API Documentation

This document provides a comprehensive reference for the Agent Builder Platform's backend API.

---

## 1. Base URL & Authentication

- **Base URL**: `http://localhost:8000`
- **Authentication**:
  - **JWT Bearer Token**: Include `Authorization: Bearer <access_token>` in headers for protected routes.
  - **API Key**: Include `X-API-Key: <api_key>` in headers for API key-protected routes.

---

## 2. Authentication Endpoints

These endpoints manage user authentication, registration, and session management.

### `POST /auth/login`

Authenticates a user and returns JWT access and refresh tokens.

- **Request Body**:
  ```json
  {
    "username": "testuser",
    "password": "yoursecurepassword"
  }
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "access_token": "ey...",
    "refresh_token": "ey...",
    "token_type": "bearer"
  }
  ```
- **Error Responses**:
  - `401 Unauthorized`: Invalid credentials.
  - `429 Too Many Requests`: Account locked due to too many failed login attempts.

### `POST /auth/logout`

Logs out a user by revoking their refresh token. Requires authentication.

- **Request Body**: (empty)
- **Success Response (200 OK)**:
  ```json
  {
    "message": "Successfully logged out"
  }
  ```

### `POST /auth/register` (Not Implemented)

Registers a new user.

- **Request Body**:
  ```json
  {
    "username": "newuser",
    "email": "newuser@example.com",
    "password": "a-very-strong-password",
    "full_name": "New User"
  }
  ```
- **Success Response (201 Created)**:
  ```json
  {
    "id": "user_id...",
    "username": "newuser",
    "email": "newuser@example.com",
    "full_name": "New User",
    "role": "user"
  }
  ```

### `POST /auth/refresh` (Not Implemented)

Issues a new access token using a valid refresh token.

- **Request Body**:
  ```json
  {
    "refresh_token": "ey..."
  }
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "access_token": "ey...",
    "token_type": "bearer"
  }
  ```

### `GET /auth/me`

Retrieves the profile of the currently authenticated user.

- **Request Body**: (empty)
- **Success Response (200 OK)**:
  ```json
  {
    "id": "user_id...",
    "username": "testuser",
    "email": "testuser@example.com",
    "full_name": "Test User",
    "role": "admin",
    "disabled": false
  }
  ```

---

## 3. Messaging Endpoints

Endpoints for interacting with the conversational agent.

### `POST /api/v1/messages`

Sends a message to an agent and receives a response. This will be updated to a WebSocket endpoint for real-time streaming.

- **Request Body**:
  ```json
  {
    "conversation_id": "conv_123",
    "message": {
      "role": "user",
      "content": "Tell me about your return policy."
    },
    "agent_id": "agent_abc",
    "brand_id": "brand_xyz",
    "user_context": {
      "user_id": "user_456",
      "session_id": "session_789"
    }
  }
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "conversation_id": "conv_123",
    "response": {
      "role": "assistant",
      "content": "Our return policy allows returns within 30 days of purchase. [Source: return_policy.pdf, p. 1]",
      "citations": [
        {
          "source": "return_policy.pdf",
          "page": 1,
          "text": "..."
        }
      ]
    }
  }
  ```

### `GET /api/v1/messages/{conversation_id}`

Retrieves the message history for a given conversation.

- **Path Parameters**:
  - `conversation_id` (string): The ID of the conversation.
- **Success Response (200 OK)**:
  ```json
  {
    "conversation_id": "conv_123",
    "history": [
      { "role": "user", "content": "..." },
      { "role": "assistant", "content": "..." }
    ]
  }
  ```

### `DELETE /api/v1/messages/{conversation_id}`

Deletes a conversation and its associated memory.

- **Path Parameters**:
  - `conversation_id` (string): The ID of the conversation.
- **Success Response (204 No Content)**

---

## 4. Document Ingestion Endpoints

Endpoints for managing the knowledge base of agents.

### `POST /api/v1/ingest`

Uploads and ingests a single document for a specific brand.

- **Request Form Data**:
  - `file`: The document file to upload.
  - `brand_id`: The ID of the brand to associate the document with.
- **Success Response (202 Accepted)**:
  ```json
  {
    "job_id": "ingest_job_abc",
    "message": "Document ingestion started."
  }
  ```

### `POST /api/v1/ingest/batch` (Not Implemented)

Uploads and ingests a batch of documents.

- **Request Form Data**:
  - `files`: Multiple document files.
  - `brand_id`: The ID of the brand.
- **Success Response (202 Accepted)**:
  ```json
  {
    "job_id": "batch_ingest_job_xyz",
    "message": "Batch document ingestion started for 5 files."
  }
  ```

### `GET /api/v1/ingest/status/{job_id}`

Retrieves the status of a document ingestion job.

- **Path Parameters**:
  - `job_id` (string): The ID of the ingestion job.
- **Success Response (200 OK)**:
  ```json
  {
    "job_id": "ingest_job_abc",
    "status": "completed", // or "pending", "processing", "failed"
    "details": "Successfully ingested and indexed 25 chunks from document.pdf.",
    "error": null
  }
  ```

---

## 5. Admin Endpoints

Endpoints for managing brands, agents, and documents. Require `admin` role.

### Brands

- **`GET /api/v1/admin/brands`**: List all brands.
- **`POST /api/v1/admin/brands`**: Create a new brand.
  - **Body**: `{ "name": "New Brand", "config": { ... } }`
- **`GET /api/v1/admin/brands/{brand_id}`**: Get a specific brand.
- **`PUT /api/v1/admin/brands/{brand_id}`**: Update a brand.
- **`DELETE /api/v1/admin/brands/{brand_id}`**: Delete a brand.

### Agents

- **`GET /api/v1/admin/agents`**: List all agents for a brand.
  - **Query Params**: `brand_id` (required)
- **`POST /api/v1/admin/agents`**: Create a new agent.
  - **Body**: `{ "name": "Support Agent", "brand_id": "...", "config": { ... } }`
- **`GET /api/v1/admin/agents/{agent_id}`**: Get a specific agent.
- **`PUT /api/v1/admin/agents/{agent_id}`**: Update an agent.
- **`DELETE /api/v1/admin/agents/{agent_id}`**: Delete an agent.

### Documents

- **`GET /api/v1/admin/documents`**: List all documents for a brand.
  - **Query Params**: `brand_id` (required)
- **`DELETE /api/v1/admin/documents/{document_id}`**: Delete a document and its indexed chunks.

---

## 6. Health & Status Endpoints

Endpoints for monitoring the health of the API.

### `GET /health`

A simple liveness probe.

- **Success Response (200 OK)**:
  ```json
  {
    "status": "healthy",
    "timestamp": "2025-10-14T12:00:00Z"
  }
  ```

### `GET /api/v1/status`

A detailed readiness probe that checks dependencies (database, cache, LLM provider).

- **Success Response (200 OK)**:
  ```json
  {
    "status": "ready",
    "dependencies": {
      "mongodb": "connected",
      "redis": "connected",
      "llm_provider": "ok",
      "embeddings_provider": "ok"
    }
  }
  ```
- **Error Response (503 Service Unavailable)**: If a dependency is down.

---

## 7. Error Responses

Standard error responses follow this format.

- **Example (404 Not Found)**:
  ```json
  {
    "detail": "Agent with id 'agent_not_found' not found."
  }
  ```
- **Example (422 Unprocessable Entity)**:
  ```json
  {
    "detail": [
      {
        "loc": ["body", "message", "role"],
        "msg": "field required",
        "type": "value_error.missing"
      }
    ]
  }
  ```

---

## 8. Rate Limiting

- **Limit**: 60 requests per minute per user/API key.
- **Headers**:
  - `X-RateLimit-Limit`: The maximum number of requests.
  - `X-RateLimit-Remaining`: The number of requests remaining in the current window.
  - `X-RateLimit-Reset`: The UTC timestamp when the limit resets.
- **Response on Exceeding**: `429 Too Many Requests` with a `Retry-After` header.
