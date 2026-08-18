import { useState } from 'react'
import { clearSessionCredential, getSessionCredential, setSessionCredential } from '../config/session'

// CONSOLE-001: runtime entry point for the Homolog test bearer credential.
// The value is kept only in this tab's sessionStorage (see config/session.ts)
// — it is never read from a build-time env var and never embedded in the
// production JS bundle. Reloading the page re-evaluates hasTestContext() /
// authHeaders() against the freshly stored value.
export function TestSessionPanel() {
  const [value, setValue] = useState('')
  const [configured, setConfigured] = useState(() => Boolean(getSessionCredential()))

  function save() {
    if (!value.trim()) return
    setSessionCredential(value)
    setValue('')
    setConfigured(true)
    window.location.reload()
  }

  function clear() {
    clearSessionCredential()
    setConfigured(false)
    window.location.reload()
  }

  return (
    <div className="mb-6 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100 space-y-2">
      <p>
        HOMOLOG TEST CONTEXT — tenant/actor come from{' '}
        <code className="text-amber-200">VITE_COGNITIVE_TEST_*</code> env vars. The bearer
        credential is entered here at runtime and kept only in this browser tab&apos;s
        sessionStorage — it is never built into the app bundle.
      </p>
      <p className="text-xs text-amber-200/80">
        Credential status: {configured ? 'configured (this tab only)' : 'not configured'}
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="password"
          autoComplete="off"
          placeholder="Paste Homolog bearer token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="min-w-[16rem] flex-1 rounded-md border border-amber-500/40 bg-slate-900 px-2 py-1 text-xs text-amber-50"
        />
        <button
          type="button"
          onClick={save}
          disabled={!value.trim()}
          className="rounded-md bg-amber-500/20 px-3 py-1 text-xs hover:bg-amber-500/30 disabled:opacity-40"
        >
          Save
        </button>
        <button
          type="button"
          onClick={clear}
          disabled={!configured}
          className="rounded-md bg-slate-800 px-3 py-1 text-xs hover:bg-slate-700 disabled:opacity-40"
        >
          Clear
        </button>
      </div>
    </div>
  )
}
