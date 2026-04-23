import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import type { WidgetConfig } from './types'
import { DEFAULT_API_BASE_URL } from './utils/apiClient'

// Default configuration - agentId will be auto-detected
const defaultConfig: WidgetConfig = {
  apiUrl: DEFAULT_API_BASE_URL,
  userId: 'anonymous',
  // agentId is auto-fetched from API if not specified
  position: 'bottom-right',
  autoOpen: false,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App config={defaultConfig} />
  </StrictMode>,
)
