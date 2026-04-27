# ── Agent Builder Admin Dashboard ────────────────────────────────────────────
# Build context: apps/admin
# Usage:
#   cd apps/admin && docker build -t agentbuilder-admin .
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (cached unless package.json changes)
COPY package.json package-lock.json* ./
RUN npm ci --legacy-peer-deps

# Copy source and build
COPY . .

# Runtime config is preferred for deployed environments; build args remain for local builds
ARG REACT_APP_API_URL=http://localhost:8000
ENV REACT_APP_API_URL=$REACT_APP_API_URL

ENV GENERATE_SOURCEMAP=false

RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Copy built assets
COPY --from=builder /app/build /usr/share/nginx/html

# nginx config: handle React Router (all paths → index.html)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/40-runtime-config.sh

ENV API_BASE_URL=http://localhost:8000

RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
