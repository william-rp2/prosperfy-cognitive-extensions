import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { openFinanceDb, type FinanceDb } from './db.js'
import { SyncAlreadyRunningError, SyncRunsRepository } from './syncRunsRepository.js'

let db: FinanceDb
let repo: SyncRunsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  repo = new SyncRunsRepository(db)
})

afterEach(() => {
  db.close()
})

describe('SyncRunsRepository lock', () => {
  it('impede duas execuções "running" simultâneas via índice único parcial', () => {
    const run = repo.startRun('manual')
    expect(() => repo.startRun('cron')).toThrow(SyncAlreadyRunningError)

    repo.finishRun(run.id, {
      status: 'success',
      itemsProcessed: 1,
      accountsProcessed: 1,
      transactionsCreated: 0,
      transactionsUpdated: 0,
      errorCount: 0,
    })

    // Lock released once the running row transitions to a finished status.
    expect(() => repo.startRun('manual')).not.toThrow()
  })

  it('libera lock travado (processo derrubado) após o timeout configurado', () => {
    repo.startRun('manual')
    // Backdate started_at (same ISO format the repo writes) to simulate a crashed run whose lock never got released.
    db.prepare('UPDATE financial_sync_runs SET started_at = ?').run(new Date(Date.now() - 60 * 60 * 1000).toISOString())

    repo.releaseStaleLocks(30 * 60 * 1000)

    expect(() => repo.startRun('manual')).not.toThrow()
    expect(repo.getLatest()?.status).toBe('running')
  })
})
