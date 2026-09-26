import React from 'react'
import ReactDOM from 'react-dom/client'

import App from './App'
import { applyAppearance, loadAppearance } from './lib/appearance'
import './styles.css'

// Read before the first render so the saved font never flashes to the
// default before switching — see lib/appearance.ts for why localStorage.
applyAppearance(loadAppearance())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
