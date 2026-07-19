# ── Agent Builder Admin Dashboard ────────────────────────────────────────────
# Build context: apps/admin
# Usage:
#   cd apps/admin && docker build -t agentbuilder-admin .
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder

WORKDIR /app

# Install dependencies first (cached unless package.json changes)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source and build
COPY . .

RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

# Copy built assets
COPY --from=builder /app/build /usr/share/nginx/html

# nginx config: handle React Router (all paths → index.html)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/40-runtime-config.sh

ENV API_BASE_URL=http://localhost:8000
ENV WIDGET_BASE_URL=http://localhost:5174

RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run /etc/nginx/conf.d /docker-entrypoint.d \
    && sed -i \
        -e 's|^user .*;|# worker user is the unprivileged container user|' \
        -e 's|^pid .*;|pid /tmp/nginx.pid;|' \
        /etc/nginx/nginx.conf

USER nginx

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
