import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import type { WidgetConfig } from './types'

// Default configuration with Essco agent ID
const defaultConfig: WidgetConfig = {
  apiUrl: 'http://localhost:8000',
  userId: 'anonymous',
  agentId: 'f168131d-7833-4f9c-ac8e-8a19b22c16f3',  // Essco AI agent
  theme: 'light',
  position: 'bottom-right',
  autoOpen: false,
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App config={defaultConfig} />
  </StrictMode>,
)
