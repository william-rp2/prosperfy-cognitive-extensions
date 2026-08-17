import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { OverviewPage } from './pages/Overview'
import { CapabilitiesPage } from './pages/Capabilities'
import { ExecutePage } from './pages/Execute'
import { ExecutionsPage } from './pages/Executions'
import { AuditPage } from './pages/Audit'

export default function App() {
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
