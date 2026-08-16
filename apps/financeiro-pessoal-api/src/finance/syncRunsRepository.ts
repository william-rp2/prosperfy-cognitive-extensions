import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import type { FinancialSyncRunRow, SyncStatus, SyncTrigger } from './types.js'

export class SyncAlreadyRunningError extends Error {
  constructor() {
    super('Já existe uma sincronização em andamento (financial_sync_runs.status = running).')
  }
}

export interface FinishRunInput {
  status: SyncStatus
  itemsProcessed: number
  accountsProcessed: number
  transactionsCreated: number
  transactionsUpdated: number
  errorCount: number
  errorSummary?: unknown
  metadata?: unknown
}

export class SyncRunsRepository {
  constructor(private readonly db: FinanceDb) {}

  /** Starts a run. Throws SyncAlreadyRunningError if the DB-level lock (partial unique index) is held. */
  startRun(trigger: SyncTrigger, provider = 'pluggy'): FinancialSyncRunRow {
    const id = randomUUID()
    const now = new Date().toISOString()

    try {
      this.db
        .prepare(
          `INSERT INTO financial_sync_runs (id, provider, started_at, status, trigger)
           VALUES (?, ?, ?, 'running', ?)`,
        )
        .run(id, provider, now, trigger)
    } catch (error) {
      if (isUniqueConstraintError(error)) throw new SyncAlreadyRunningError()
      throw error
    }

    return this.getById(id)!
  }

  finishRun(id: string, input: FinishRunInput) {
    this.db
      .prepare(
        `UPDATE financial_sync_runs SET
           finished_at = @finishedAt,
           status = @status,
           items_processed = @itemsProcessed,
           accounts_processed = @accountsProcessed,
           transactions_created = @transactionsCreated,
           transactions_updated = @transactionsUpdated,
           error_count = @errorCount,
           error_summary = @errorSummary,
           metadata = @metadata
         WHERE id = @id`,
      )
      .run({
        id,
        finishedAt: new Date().toISOString(),
        status: input.status,
        itemsProcessed: input.itemsProcessed,
        accountsProcessed: input.accountsProcessed,
        transactionsCreated: input.transactionsCreated,
        transactionsUpdated: input.transactionsUpdated,
        errorCount: input.errorCount,
        errorSummary: input.errorSummary !== undefined ? JSON.stringify(input.errorSummary) : null,
        metadata: input.metadata !== undefined ? JSON.stringify(input.metadata) : null,
      })
  }

  /** Force-clears a stale 'running' row (e.g. process crashed mid-sync) so the lock doesn't wedge forever. */
  releaseStaleLocks(staleAfterMs: number, provider = 'pluggy') {
    const threshold = new Date(Date.now() - staleAfterMs).toISOString()
    this.db
      .prepare(
        `UPDATE financial_sync_runs
         SET status = 'failed', finished_at = ?, error_summary = ?
         WHERE provider = ? AND status = 'running' AND started_at < ?`,
      )
      .run(new Date().toISOString(), JSON.stringify({ reason: 'stale_lock_released' }), provider, threshold)
  }

  getById(id: string): FinancialSyncRunRow | undefined {
    return this.db.prepare('SELECT * FROM financial_sync_runs WHERE id = ?').get(id) as FinancialSyncRunRow | undefined
  }

  getLatest(provider = 'pluggy'): FinancialSyncRunRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_sync_runs WHERE provider = ? ORDER BY started_at DESC LIMIT 1')
      .get(provider) as FinancialSyncRunRow | undefined
  }

  listRecent(limit = 20, provider = 'pluggy'): FinancialSyncRunRow[] {
    return this.db
      .prepare('SELECT * FROM financial_sync_runs WHERE provider = ? ORDER BY started_at DESC LIMIT ?')
      .all(provider, limit) as FinancialSyncRunRow[]
  }
}

function isUniqueConstraintError(error: unknown): boolean {
  return error instanceof Error && 'code' in error && (error as { code?: string }).code === 'SQLITE_CONSTRAINT_UNIQUE'
}
