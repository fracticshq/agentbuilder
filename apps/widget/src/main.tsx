import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import type { WidgetConfig } from './types'

// Default configuration - agentId will be auto-detected
const defaultConfig: WidgetConfig = {
  apiUrl: 'http://localhost:8000',
  userId: 'anonymous',
  // agentId is auto-fetched from API if not specified
  theme: 'light',
  position: 'bottom-right',
  autoOpen: false,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App config={defaultConfig} />
  </StrictMode>,
)
