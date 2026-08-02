# ── Shopify MCP Server ────────────────────────────────────────────────────────
# Maps Shopify admin/storefront APIs to the Model Context Protocol
# Build context: apps/shopify-mcp
# Usage:
#   cd apps/shopify-mcp && docker build -t agentbuilder-shopify .
# ─────────────────────────────────────────────────────────────────────────────

FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4

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
