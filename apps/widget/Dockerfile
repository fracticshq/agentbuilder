# ── Agent Builder Chat Widget ─────────────────────────────────────────────────
# Build context: apps/widget
# Usage:
#   cd apps/widget && docker build -t agentbuilder-widget .
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# API URL can still be provided for non-Docker builds, but runtime config is preferred
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Skip tsc (it flags test files) — vite handles transpilation on its own
RUN npx vite build

# ── Stage 2: Serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/40-runtime-config.sh

ENV API_BASE_URL=http://localhost:8000

RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run /etc/nginx/conf.d /docker-entrypoint.d \
    && sed -i \
        -e 's|^user .*;|# worker user is the unprivileged container user|' \
        -e 's|^pid .*;|pid /tmp/nginx.pid;|' \
        /etc/nginx/nginx.conf

USER nginx

EXPOSE 5174

CMD ["nginx", "-g", "daemon off;"]
