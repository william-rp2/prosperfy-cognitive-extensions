import { createRoot } from 'react-dom/client'

import { App } from './App'
import './index.css'

// No StrictMode: its dev-only double mount/unmount breaks the Pluggy Connect widget's
// iframe lifecycle (it fails with a generic "Erro no widget Pluggy." on first open).
createRoot(document.getElementById('root')!).render(<App />)
