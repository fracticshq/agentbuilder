# RUNBOOK — Secrets, Embeddings & RAG

Operational notes for keeping the Lal Kitab agent (and any RAG agent) working
across container rebuilds and key rotations. Written 2026-06-23.

## TL;DR

- All stored secrets in Mongo (connector tokens, runtime settings) are encrypted
  with **`SETTINGS_ENCRYPTION_KEY`** from `.env.docker`. If that key doesn't match
  what encrypted the data, decryption fails and you get `InvalidToken` /
  `Master key must be 32 bytes` in the api logs.
- When a stored secret can't be decrypted, the code **falls back to env vars**
  (`runtime_setting_decrypt_failed_using_env`). So keeping the real keys in
  `.env.docker` / `.env` keeps things working even after a key mismatch.
- Data lives in a **real Atlas cluster** (`mongodb+srv://agent-builder-cluster…`),
  not the local `mongo:7` container. Vector search runs in Atlas.

## Keys and where they live

| Secret | Env var (fallback) | Also stored in Mongo | Notes |
|---|---|---|---|
| Voyage embeddings | `VOYAGE_API_KEY` | runtime_settings `voyage.api_key` | Must be a **native Voyage key (`pa-…`)** for `api.voyageai.com`. An Atlas Model API key (`al-…`) only works against `https://ai.mongodb.com/v1`. |
| Voyage endpoint | `VOYAGE_BASE_URL` | `voyage.base_url` | `https://api.voyageai.com/v1` for `pa-` keys. |
| Voyage model | `VOYAGE_MODEL` | `voyage.model` | `voyage-3-large` (1024-dim) — must match what the KB was embedded with. |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | runtime_settings `azure_openai.api_key` | LLM provider; env fallback already in place. |
| Vedika connector | — (no env hook) | agent doc `configuration.context_connectors[].auth` | Per-agent bearer token. Only survives via Mongo + a stable encryption key. |

## Go-live key rotation checklist

When swapping dev keys for production keys:

1. Update `.env.docker` (and `.env`) with the new values:
   `VOYAGE_API_KEY`, `VOYAGE_BASE_URL`, `VOYAGE_MODEL`, `AZURE_OPENAI_API_KEY`, etc.
2. If you also rotate `SETTINGS_ENCRYPTION_KEY`, **every** previously-stored Mongo
   secret stops decrypting. Re-enter each one via Admin (Settings + the agent's
   connector) so they re-encrypt under the new key — or rely on the env fallbacks
   above for the ones that have them (Voyage, Azure). The **Vedika token has no
   env fallback**, so it must be re-saved (see below).
3. `docker compose up -d --build api widget` to rebuild and restart.
4. Verify: `curl -s localhost:8000/api/v1/public/agents/<id>` returns, and send a
   test message in the widget (chart + retrieval should work).

## Re-applying the Vedika connector token (no env hook)

If Mongo is reseeded or the encryption key changes, re-save the bearer token so it
re-encrypts under the container's current key:

```bash
docker exec -e VK="<vk_live_token>" agentbuilder-api python - <<'PY'
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.dependencies import get_settings
from app.services.runtime_settings_service import RuntimeSettingsService
from app.services import tool_config_secrets as tcs
AID='<agent_id>'
async def main():
    cli=AsyncIOMotorClient(os.environ['MONGODB_URI']); db=cli['agent-builder']
    a=await db.agents.find_one({'id':AID}); ccs=a['configuration']['context_connectors']
    rss=RuntimeSettingsService(get_settings())
    auth=tcs._protect_secretish_mapping({'type':'bearer','token':os.environ['VK']}, existing=None, runtime_settings_service=rss)
    for c in ccs:
        if c.get('id')=='vedika_lal_kitab': c['auth']=auth
    await db.agents.update_one({'id':AID}, {'$set':{'configuration.context_connectors':ccs}})
    print('vedika token re-saved')
asyncio.run(main())
PY
```

## Re-embedding the knowledge base (if `embeddings` are empty)

Symptom: hybrid RAG only returns keyword (BM25) hits; `$vectorSearch` returns
nothing. Cause: chunks ingested without embeddings, or no Atlas vector index.

Check:
```bash
docker exec agentbuilder-api python -c "import os,asyncio;from motor.motor_asyncio import AsyncIOMotorClient;\
kb=AsyncIOMotorClient(os.environ['MONGODB_URI'])['lalkitab']['knowledge_base'];\
import asyncio;print(asyncio.run(kb.count_documents({'\$or':[{'embeddings':{'\$size':0}},{'embeddings':{'\$exists':False}}]})))"
```

Fix: embed each chunk's `content` with the configured model (batched
`VoyageClient.embed_documents`), write the `embeddings` field, then create the
Atlas vector index from `app.bootstrap.atlas_vector.atlas_vector_index_definition`
(path `embeddings`, 1024 dims, cosine) via the data-plane `create_search_index`
(`SearchIndexModel(type='vectorSearch')`). Wait for `queryable: true`. The full
one-off script used on 2026-06-23 is in this session's history.

## Widget activity timeline (per-agent)

`channels.widget.activity_mode` = `basic` (cycling indicator) or `advanced`
(live step timeline). Set per agent in Admin → Agent → Features → Activity Display.
Default `basic`. The timeline is general (any agent) — it maps standard streaming
events (`context_*`, `tool_*`, `connector_*`, `geocode_*`, `rag_context`, …).
