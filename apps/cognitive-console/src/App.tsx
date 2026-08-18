import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { OverviewPage } from './pages/Overview'
import { CapabilitiesPage } from './pages/Capabilities'
import { ExecutePage } from './pages/Execute'
import { ExecutionsPage } from './pages/Executions'
import { AuditPage } from './pages/Audit'
import { hasApiBaseUrl } from './config/env'

// CONSOLE-003: missing API config must fail loudly and visibly, never fall
// back to a guessed (or worse, hardcoded production) API target.
function ConfigErrorScreen() {
  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-lg rounded-xl border border-red-500/40 bg-red-500/10 p-6 text-red-100">
        <h1 className="text-lg font-semibold mb-2">Configuration Error</h1>
        <p className="text-sm">
          <code className="text-red-200">VITE_COGNITIVE_API_BASE_URL</code> is not set. The
          Console refuses to guess an API target (in particular it will never silently fall back
          to a production URL). Set this env var explicitly — see{' '}
          <code className="text-red-200">apps/cognitive-console/.env.example</code> — and
          rebuild/redeploy.
        </p>
      </div>
    </div>
  )
}

export default function App() {
  if (!hasApiBaseUrl()) {
    return <ConfigErrorScreen />
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="capabilities" element={<CapabilitiesPage />} />
          <Route path="execute" element={<ExecutePage />} />
          <Route path="executions" element={<ExecutionsPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
