import { useEffect, useState } from 'react'
import { cognitiveApi, type HealthResponse, type StatusResponse } from '../api/client'
import { consoleConfig, hasTestContext } from '../config/env'

export function OverviewPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cognitiveApi.getHealth().then(setHealth).catch((e: Error) => setError(e.message))
    if (hasTestContext()) {
      cognitiveApi.getStatus().then(setStatus).catch((e: Error) => setError(e.message))
    }
  }, [])

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Overview</h2>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="API Health" body={health} />
        <Card title="Gateway Status" body={status ?? { note: hasTestContext() ? 'loading…' : 'Configure test context' }} />
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-300">
        <p><span className="text-slate-500">API base:</span> {consoleConfig.apiBaseUrl}</p>
      </div>
    </div>
  )
}

function Card({ title, body }: { title: string; body: unknown }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
      <h3 className="text-sm uppercase tracking-wide text-slate-400 mb-3">{title}</h3>
      <pre className="text-xs overflow-auto text-emerald-100/90">{JSON.stringify(body, null, 2)}</pre>
    </div>
  )
}
