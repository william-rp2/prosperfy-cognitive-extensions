import { NavLink, Outlet } from 'react-router-dom'
import { consoleConfig, isHomologTestContext } from '../config/env'
import { TestSessionPanel } from './TestSessionPanel'

const nav = [
  ['/', 'Overview'],
  ['/capabilities', 'Capabilities'],
  ['/execute', 'Execute'],
  ['/executions', 'Executions'],
  ['/audit', 'Audit'],
] as const

export function Layout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-64 border-r border-slate-800 bg-slate-900/80 p-6">
        <div className="mb-8">
          <p className="text-xs uppercase tracking-widest text-emerald-400">Prosperfy</p>
          <h1 className="text-xl font-semibold">Cognitive Console</h1>
          <p className="text-xs text-slate-400 mt-1">{consoleConfig.environment}</p>
        </div>
        <nav className="space-y-2">
          {nav.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-emerald-500/15 text-emerald-300' : 'text-slate-300 hover:bg-slate-800'}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">
        {isHomologTestContext() && <TestSessionPanel />}
        <Outlet />
      </main>
    </div>
  )
}
