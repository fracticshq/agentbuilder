# ── Shopify MCP Server ────────────────────────────────────────────────────────
# Maps Shopify admin/storefront APIs to the Model Context Protocol
# Build context: apps/shopify-mcp
# Usage:
#   cd apps/shopify-mcp && docker build -t agentbuilder-shopify .
# ─────────────────────────────────────────────────────────────────────────────

FROM node:20-alpine

WORKDIR /app

# Copy package files first to leverage Docker layer caching
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm ci

# Copy the source code
COPY src ./src

# Expose the port the app runs on
EXPOSE 3005

# Start the server
CMD ["npm", "start"]
