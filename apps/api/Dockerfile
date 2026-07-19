# ── Agent Builder API ─────────────────────────────────────────────────────────
# Build context: repository root
# Usage:
#   docker build -f apps/api/Dockerfile -t agentbuilder-api .
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.14@sha256:311ea5bb79f1a238ee9e38f8d5f09cb3b4b244575cf49e27cf365ea7e60f11d4

WORKDIR /app

# ── Copy local packages ───────────────────────────────────────────────────────
COPY packages/commons    /app/packages/commons
COPY packages/llm        /app/packages/llm
COPY packages/memory     /app/packages/memory
COPY packages/retrieval  /app/packages/retrieval
COPY packages/tools      /app/packages/tools
COPY packages/agent_runtime /app/packages/agent_runtime

# ── Install API dependencies ───────────────────────────────────────────────────
COPY apps/api/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock \
    && pip install --no-cache-dir --no-deps --no-build-isolation \
        /app/packages/commons \
        /app/packages/llm \
        /app/packages/memory \
        /app/packages/retrieval \
        /app/packages/tools \
        /app/packages/agent_runtime \
    && pip check

# ── Copy API source ────────────────────────────────────────────────────────────
COPY apps/api/app /app/api/app
COPY apps/api/run.py apps/api/docker-entrypoint.sh /app/api/
# The protected staging-evaluation API validates reports against the checked-in
# contract fixtures.  They are runtime artifacts, not test-only source.
COPY evals /app/evals

# The application runs from /app/api while the repository-owned evaluation
# package lives at /app/evals in the image.
ENV PYTHONPATH=/app

WORKDIR /app/api

EXPOSE 8000

RUN chmod +x /app/api/docker-entrypoint.sh \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && chown -R app:app /app

USER app

# Fail fast with a clear config error before importing the app.
ENTRYPOINT ["/app/api/docker-entrypoint.sh"]
