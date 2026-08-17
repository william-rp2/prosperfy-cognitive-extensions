import { useState } from 'react'
import { cognitiveApi, type ExecuteResponse } from '../api/client'
import { hasTestContext } from '../config/env'

export function ExecutePage() {
  const [capabilityId, setCapabilityId] = useState('infra.inspect')
  const [paramsJson, setParamsJson] = useState('{"resource": "prosperfy-main"}')
  const [result, setResult] = useState<ExecuteResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function run() {
    if (!hasTestContext()) {
      setError('Configure VITE_COGNITIVE_TEST_* before executing')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const params = JSON.parse(paramsJson) as Record<string, unknown>
      const res = await cognitiveApi.executeCapability(capabilityId, params)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Execution failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h2 className="text-2xl font-semibold">Execute</h2>
      <label className="block text-sm text-slate-400">Capability ID</label>
      <input
        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm"
        value={capabilityId}
        onChange={(e) => setCapabilityId(e.target.value)}
      />
      <label className="block text-sm text-slate-400">Params JSON</label>
      <textarea
        className="w-full h-40 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm"
        value={paramsJson}
        onChange={(e) => setParamsJson(e.target.value)}
      />
      <button
        type="button"
        onClick={run}
        disabled={loading}
        className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
      >
        {loading ? 'Running…' : 'Execute'}
      </button>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {result && (
        <pre className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-xs overflow-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  )
}
