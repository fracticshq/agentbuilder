# ── Shopify MCP Server ────────────────────────────────────────────────────────
# Maps Shopify admin/storefront APIs to the Model Context Protocol
# Build context: apps/shopify-mcp
# Usage:
#   cd apps/shopify-mcp && docker build -t agentbuilder-shopify .
# ─────────────────────────────────────────────────────────────────────────────

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

WORKDIR /app

# Copy package files first to leverage Docker layer caching
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm ci

# Copy the source code
COPY src ./src

# The MCP server does not require root privileges at runtime.
RUN chown -R node:node /app

USER node

# Expose the port the app runs on
EXPOSE 3005

# Start the server
CMD ["npm", "start"]
