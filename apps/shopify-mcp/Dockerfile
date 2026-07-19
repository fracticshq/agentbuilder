# ── Shopify MCP Server ────────────────────────────────────────────────────────
# Maps Shopify admin/storefront APIs to the Model Context Protocol
# Build context: apps/shopify-mcp
# Usage:
#   cd apps/shopify-mcp && docker build -t agentbuilder-shopify .
# ─────────────────────────────────────────────────────────────────────────────

FROM node:26-alpine@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66

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
