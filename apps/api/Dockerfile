# ── Agent Builder API ─────────────────────────────────────────────────────────
# Build context must be the repo root so packages/ is accessible.
# Usage (from repo root):
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
COPY apps/api /app/api

WORKDIR /app/api

EXPOSE 8000

# Run without --reload in Docker (source isn't hot-reloaded anyway in a container)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
