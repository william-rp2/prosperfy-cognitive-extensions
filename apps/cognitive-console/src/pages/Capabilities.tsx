import { useEffect, useState } from 'react'
import { cognitiveApi, type CapabilitySummary } from '../api/client'
import { hasTestContext } from '../config/env'

export function CapabilitiesPage() {
  const [caps, setCaps] = useState<CapabilitySummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasTestContext()) {
      setError('Configure VITE_COGNITIVE_TEST_* to load capabilities')
      return
    }
    cognitiveApi.listCapabilities().then(setCaps).catch((e: Error) => setError(e.message))
  }, [])

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Capabilities</h2>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <div className="overflow-hidden rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-slate-400">
            <tr>
              <th className="p-3">ID</th>
              <th className="p-3">Version</th>
              <th className="p-3">Policy</th>
              <th className="p-3">Domain</th>
            </tr>
          </thead>
          <tbody>
            {caps.map((c) => (
              <tr key={c.id} className="border-t border-slate-800">
                <td className="p-3 font-mono text-emerald-300">{c.id}</td>
                <td className="p-3">{c.version}</td>
                <td className="p-3">{c.default_policy}</td>
                <td className="p-3 text-slate-400">{c.domain}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
