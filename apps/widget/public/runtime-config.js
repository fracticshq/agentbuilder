// Runtime config template for local widget development.
//
// This file is intentionally inactive when committed. The widget loads
// /runtime-config.js if it exists, but the production Docker entrypoint writes
// the active config at container startup. For local dev, uncomment the block
// below only when you need to override VITE_API_BASE_URL without rebuilding.
//
window.__APP_CONFIG__ = {
  API_BASE_URL: 'http://localhost:8000'
};
