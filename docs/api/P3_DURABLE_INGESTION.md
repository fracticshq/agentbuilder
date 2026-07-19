# P3 durable document ingestion

`POST /api/v1/ingest/documents` is a submission endpoint. It no longer uses
FastAPI `BackgroundTasks` or retains request bytes after the HTTP response.

## Submission and retention

1. The dashboard route authorizes the requested agent and snapshots its
   `agent_id`, `brand_id`, `brand_slug`, and resolved chunk size/overlap.
2. Each source file (maximum `MAX_FILE_SIZE_MB` per file) is encrypted with a
   Fernet key derived from `SETTINGS_ENCRYPTION_KEY`, falling back to
   `PII_ENCRYPTION_KEY` and then `SECRET_KEY`.
3. Encrypted bytes are written to `system.ingestion_payloads` with a Mongo TTL
   index (`INGESTION_PAYLOAD_TTL_SECONDS`, default 24 hours). The queued job
   has only opaque payload IDs; it never contains uploaded bytes.
4. A v2 job is inserted in `system.ingestion_jobs` before the API returns
   `pending`. If the job write fails, the just-created payloads are deleted;
   TTL remains the bounded-retention backstop for interruption.
5. Clients may send an `Idempotency-Key` header (1–128 letters, digits,
   `.`, `_`, `:`, or `-`). Repeating that key for the same agent, brand, and
   source manifest returns the original job; reusing it for different source
   bytes returns `409 Conflict`.

Logs contain only job IDs, file counts, and exception types. They must not add
source bytes or parser/provider exception text.

## Worker protocol

`docker compose` starts `ingestion-worker` from the same `agentbuilder-api`
image with `INGESTION_WORKER=true`. It polls Mongo and atomically claims only
jobs with both `queue_version: 2` and `kind: document_ingestion`. Historical
job rows are readable for status but are never claimable by this worker.

The claim stores a random lease token and expiry. Lease renewal, progress,
publish transition, retries, terminal completion, and cancellation all use
Mongo filters containing that token. Redis cannot decide any of these actions.
An expired `running` or `publishing` lease can be reclaimed, so a process or
container restart does not strand work.

The worker stages extracted chunks and embeddings in
`system.ingestion_staged_chunks` before making anything visible in the brand
knowledge base. The stage has a TTL and uses deterministic IDs based on
`job_id:file_index:chunk_index`. At the publish fence the worker changes the
job to `publishing`; it then upserts the same deterministic IDs into the
snapshot's `brand_slug` database (and Qdrant, when enabled). Reclaiming a lease
therefore replays idempotent upserts rather than producing duplicate chunks.

An agent can be reassigned after submission without affecting where its queued
job publishes: the worker does not resolve current agent ownership.

## Cancellation and retries

- Cancellation atomically succeeds while a v2 job is `queued` or `running`
  before the publish fence. It prevents visible chunks and cleans staged/source
  artifacts.
- Once publishing has started, cancellation does not change the job to a
  partial terminal state; deterministic upserts finish and the job completes.
- Invalid/corrupt source input is terminal. Failures before the publish fence
  use `INGESTION_MAX_ATTEMPTS` and `INGESTION_RETRY_DELAY_SECONDS`. A failure
  during publish remains recoverable beyond that budget until the same
  deterministic upserts finish, so a visible partial batch can never be
  terminally reported as failed.
- Public status stays compatible: `queued` is returned as `pending`, and
  `running`/`publishing` as `processing`.

## Operational settings

| Setting | Default | Purpose |
| --- | ---: | --- |
| `INGESTION_JOB_TTL_SECONDS` | 86400 | Retention for job/staging state |
| `INGESTION_PAYLOAD_TTL_SECONDS` | 86400 | Maximum encrypted source retention |
| `INGESTION_LEASE_SECONDS` | 120 | Mongo worker lease duration |
| `INGESTION_MAX_ATTEMPTS` | 3 | Retry budget for transient failures |
| `INGESTION_RETRY_DELAY_SECONDS` | 10 | Delay before a retry claim |
| `INGESTION_WORKER_POLL_SECONDS` | 1.0 | Idle worker poll interval |
