# NOVA Database Setup

NOVA uses MongoDB as the source of truth for users, brands, agents, runtime settings, conversations, memory, and knowledge documents. Vector retrieval can run in two supported modes:

- `VECTOR_BACKEND=atlas` for MongoDB Atlas Vector Search.
- `VECTOR_BACKEND=qdrant` for local or self-hosted vector search.

## Local OSS Setup

The default Docker Compose stack includes MongoDB, Redis, and Qdrant.

```bash
cp .env.docker.example .env.docker
docker compose up --build
```

Use this local vector configuration:

```env
MONGODB_URI=mongodb://mongodb:27017
MONGO_SYSTEM_DB=system
VECTOR_BACKEND=qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION_PREFIX=nova
VECTOR_DIMENSIONS=1024
```

Run the bootstrap check:

```bash
docker compose run --rm api python -m app.bootstrap.check
```

The command creates MongoDB indexes and Qdrant collections for existing brands. New brand databases and knowledge collections are also created lazily as data is uploaded.

## MongoDB Atlas Setup

Use Atlas when you want managed MongoDB plus Atlas Vector Search:

```env
MONGODB_URI=mongodb+srv://...
MONGO_SYSTEM_DB=system
VECTOR_BACKEND=atlas
VECTOR_INDEX_NAME=vector_index
VECTOR_DIMENSIONS=1024
ATLAS_PROJECT_ID=...
ATLAS_CLUSTER_NAME=...
ATLAS_PUBLIC_KEY=...
ATLAS_PRIVATE_KEY=...
ATLAS_AUTO_CREATE_VECTOR_INDEXES=false
```

Run:

```bash
python -m app.bootstrap.check
```

The default bootstrap command is check-only. If Atlas Admin API credentials are configured, it reports whether each brand database needs an Atlas Vector Search index create/update. To let NOVA create or update the Atlas Vector Search indexes, run:

```bash
python -m app.bootstrap.check --apply
```

You can also set `ATLAS_AUTO_CREATE_VECTOR_INDEXES=true` in a controlled setup job. Keep it `false` for normal app runtime if you prefer infrastructure changes to happen only during deployment.

If you do not configure Atlas Admin API credentials, create an Atlas Search index named `vector_index` on each brand database's `knowledge_base` collection using [`ATLAS_VECTOR_INDEX.json`](./ATLAS_VECTOR_INDEX.json).

## What The App Creates

On startup and via the bootstrap command, NOVA creates:

- `system.brands` indexes
- `system.agents` indexes
- `system.users` indexes
- `system.password_reset_tokens` TTL index
- `system.runtime_settings` indexes
- `system.audit_logs` indexes
- `<brand>.knowledge_base` text and metadata indexes
- Qdrant collections when `VECTOR_BACKEND=qdrant`
- Atlas Vector Search indexes when `VECTOR_BACKEND=atlas` and bootstrap is run with `--apply` plus Atlas Admin API credentials

## Notes

- MongoDB collections are created automatically on first write.
- Qdrant stores vector points; MongoDB remains the source of truth for document content and metadata.
- Voyage embeddings currently use 1024 dimensions. If the embedding model changes, update `VECTOR_DIMENSIONS` and recreate the vector index/collection.
- Atlas Admin API keys should have the narrowest project access needed to manage search indexes and should be stored in Azure Key Vault or your deployment secret manager, not committed to git.
