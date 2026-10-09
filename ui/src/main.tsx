/**
 * Entry point.
 *
 * The router is chosen here rather than in App, because it has to be decided
 * before any Route exists: on `file://` a BrowserRouter pushState throws, so
 * the standalone build has to route through the hash instead.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { ReportProvider } from './state/report'
import { pickRouter, routerProps, STANDALONE } from './router'
import './styles/base.css'

const Router = pickRouter(STANDALONE)
const props = routerProps(STANDALONE)

const container = document.getElementById('root')
if (!container) {
  throw new Error('no #root element — index.html is missing its mount point')
}

createRoot(container).render(
  <StrictMode>
    <Router {...props}>
      <ReportProvider>
        <App />
      </ReportProvider>
    </Router>
  </StrictMode>,
)