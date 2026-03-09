# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Monorepo Structure

```
apps/
  admin/   — React + Tailwind admin UI (Create React App, port 3000)
  widget/  — React chat widget (Vite, port 5174)
  api/     — FastAPI backend (Python, port 8000)
packages/
  agent_runtime/  — Python agent/LLM orchestration
  tools/          — Shared Python utilities
```

## Common Commands

```bash
# Start all services
./start-all.sh

# Widget dev server (port 5174 — Strapi owns 5173)
cd apps/widget && npm run dev

# Admin dev server
cd apps/admin && npm start

# API dev server
cd apps/api && uvicorn main:app --reload --port 8000

# Install all JS deps from root
npm install

# Install Python deps
pip install -e packages/agent_runtime packages/tools
```

## Architecture

### Admin (`apps/admin`)
- React + TypeScript + Tailwind + React Query + Headless UI
- Brand → Agent hierarchy: each Agent belongs to a Brand
- `src/api/client.ts` — all API calls + TypeScript types (`Brand`, `Agent`, `BrandIdentity`)
- `BrandIdentity` is stored in `Brand.colors` (typed `any` on the backend, typed `BrandIdentity` in TS)
- Routes: `/brands`, `/brands/:id` (BrandDetail with widget preview), `/agents`, `/agents/new`, `/agents/:id`

### Widget (`apps/widget`)
- React + TypeScript + Vite + Zustand store
- Two visual states: **landing** (no messages → hero panel with chips) and **chat** (messages → chat view)
- Brand theme is fetched at runtime: agent → brand → `brand.colors` → `buildBrandTheme()` → tokens
- `src/utils/brandTheme.ts` — derives `BrandThemeTokens` from `primaryColor` + `mode` (no user toggle; mode is admin-configured)
- `src/stores/widgetStore.ts` — Zustand store; holds `brandTheme`, `messages`, `conversationId`
- `src/components/ChatWindow.tsx` — main panel; renders landing hero OR chat messages depending on `messages.length`
- `src/components/WidgetButton.tsx` — circular bubble; uses `chatLogoDarkUrl` / `chatLogoLightUrl` based on brand mode
- NOVA wordmark always shown in the chat panel topbar (text-based; swap for SVG asset later)

### API (`apps/api`)
- FastAPI + MongoDB
- Streaming chat: `POST /api/v1/messages/stream` (SSE)
- Brand CRUD: `GET/POST/PUT/DELETE /api/v1/admin/brands/`
- Agent CRUD: `GET/POST/PUT/DELETE /api/v1/admin/agents/`
- Widget resolves agent ID from: URL `?agent_id=` → `config.agentId` → `data-agent-id` script attr → first agent in DB

## Brand Identity System

Brand widget identity is stored in `Brand.colors` as a `BrandIdentity` object:
- `primary_color` — hex accent color (drives button, chips, bubble ring, send button)
- `default_mode` — `'dark' | 'light'` (admin sets; no user toggle in widget)
- `chat_logo_dark_url` / `chat_logo_light_url` — separate logos for each mode
- `hero_title`, `hero_subtitle` — landing panel copy
- `suggestion_chips` — comma-separated chip strings
- `dark_bg_gradient` / `light_bg_gradient` — optional CSS gradient overrides for panel background

The `buildBrandTheme()` utility in `apps/widget/src/utils/brandTheme.ts` derives all CSS tokens from `primary_color` and `mode` automatically, so only `primary_color` + `default_mode` are required.

## Key Patterns

- Widget fetches brand via: `GET /api/v1/admin/agents/{id}` → extract `brand_id` → `GET /api/v1/admin/brands/{brand_id}`
- MessageBubble accepts `userMsgBg`, `userMsgColor`, `assistantMsgBg`, `assistantMsgColor` props for brand theming
- `BrandDetail.tsx` in admin renders a `WidgetPreview` component — an inline mini-render of the widget at the configured mode, no external deps needed
- CSS design system lives in `apps/widget/src/App.css`; keyframes: `bubblePop`, `panelOpen`, `ringPulse`, `orbPulse`, `floatOrb`, `typing`
- Fonts: DM Sans (UI text, weights 300/400/500/600), Kumbh Sans (titles/wordmarks, weights 300/400/600/700) loaded from Google Fonts in App.css
