# ── Agent Builder API ─────────────────────────────────────────────────────────
# Build context: repository root
# Usage:
#   docker build -f apps/api/Dockerfile -t agentbuilder-api .
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12

WORKDIR /app

# ── Install local packages first (better layer caching) ───────────────────────
COPY packages/commons    /app/packages/commons
COPY packages/llm        /app/packages/llm
COPY packages/memory     /app/packages/memory
COPY packages/retrieval  /app/packages/retrieval
COPY packages/tools      /app/packages/tools
COPY packages/agent_runtime /app/packages/agent_runtime

RUN pip install --no-cache-dir \
    /app/packages/commons \
    /app/packages/llm \
    /app/packages/memory \
    /app/packages/retrieval \
    /app/packages/tools \
    /app/packages/agent_runtime

# ── Install API dependencies ───────────────────────────────────────────────────
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ── Copy API source ────────────────────────────────────────────────────────────
COPY apps/api/app /app/api/app
COPY apps/api/run.py apps/api/docker-entrypoint.sh /app/api/

WORKDIR /app/api

EXPOSE 8000

RUN chmod +x /app/api/docker-entrypoint.sh

# Fail fast with a clear config error before importing the app.
ENTRYPOINT ["/app/api/docker-entrypoint.sh"]
