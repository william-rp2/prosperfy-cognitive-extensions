import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type OnboardingMode = 'HISTORICAL_IMPORT' | 'ONGOING'

export interface OnboardingStateRow {
  id: string
  pluggy_item_id: string
  mode: OnboardingMode
  onboarding_started_at: string
  historical_cutoff_at: string | null
  onboarding_completed_at: string | null
  created_at: string
  updated_at: string
}

export interface OnboardingExportRow {
  id: string
  pluggy_item_id: string | null
  export_version: number
  filters_json: string | null
  row_count: number
  created_at: string
}

export type ImportRowStatus = 'applied' | 'rejected' | 'conflict' | 'skipped'

export interface OnboardingImportRowRecord {
  id: string
  import_batch_id: string
  pluggy_transaction_id: string
  action: string
  status: ImportRowStatus
  error_code: string | null
  applied_at: string | null
  created_at: string
}

/**
 * Incremental, per-institution onboarding state (06_ONBOARDING_HISTORICAL_BACKFILL.md).
 * One row per `pluggy_item_id`. A second bank never touches a first bank's row: every
 * write here is scoped by item id, so onboarding for item B cannot corrupt or duplicate
 * item A's state (rule 9).
 */
export class OnboardingRepository {
  constructor(private readonly db: FinanceDb) {}

  getByItem(pluggyItemId: string): OnboardingStateRow | undefined {
    return this.db
      .prepare('SELECT * FROM finance_onboarding_state WHERE pluggy_item_id = ?')
      .get(pluggyItemId) as OnboardingStateRow | undefined
  }

  listAll(): OnboardingStateRow[] {
    return this.db
      .prepare('SELECT * FROM finance_onboarding_state ORDER BY onboarding_started_at ASC')
      .all() as OnboardingStateRow[]
  }

  /** Idempotent: a bank already onboarding/onboarded keeps its existing row untouched. */
  getOrCreate(pluggyItemId: string): OnboardingStateRow {
    const existing = this.getByItem(pluggyItemId)
    if (existing) return existing

    const now = new Date().toISOString()
    try {
      this.db
        .prepare(
          `INSERT INTO finance_onboarding_state (
             id, pluggy_item_id, mode, onboarding_started_at, created_at, updated_at
           ) VALUES (?, ?, 'HISTORICAL_IMPORT', ?, ?, ?)`,
        )
        .run(randomUUID(), pluggyItemId, now, now, now)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (!message.includes('UNIQUE') && !message.includes('constraint')) throw error
    }
    return this.getByItem(pluggyItemId)!
  }

  /** Explicit owner cutover: HISTORICAL_IMPORT -> ONGOING. Never automatic, never 100%-gated. */
  completeOnboarding(pluggyItemId: string, cutoffAt: string): OnboardingStateRow | undefined {
    const now = new Date().toISOString()
    this.db
      .prepare(
        `UPDATE finance_onboarding_state
            SET mode = 'ONGOING', historical_cutoff_at = ?, onboarding_completed_at = ?, updated_at = ?
          WHERE pluggy_item_id = ?`,
      )
      .run(cutoffAt, now, now, pluggyItemId)
    return this.getByItem(pluggyItemId)
  }

  recordExport(input: { pluggyItemId: string | null; filters: unknown; rowCount: number }): OnboardingExportRow {
    const now = new Date().toISOString()
    const version = this.nextExportVersion(input.pluggyItemId)
    const id = randomUUID()
    this.db
      .prepare(
        `INSERT INTO finance_onboarding_exports (id, pluggy_item_id, export_version, filters_json, row_count, created_at)
         VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .run(id, input.pluggyItemId, version, JSON.stringify(input.filters ?? null), input.rowCount, now)
    return this.db.prepare('SELECT * FROM finance_onboarding_exports WHERE id = ?').get(id) as OnboardingExportRow
  }

  private nextExportVersion(pluggyItemId: string | null): number {
    const row = this.db
      .prepare(
        `SELECT COALESCE(MAX(export_version), 0) as maxVersion FROM finance_onboarding_exports
         WHERE pluggy_item_id IS ?`,
      )
      .get(pluggyItemId) as { maxVersion: number }
    return row.maxVersion + 1
  }

  getExportByVersion(pluggyItemId: string | null, version: number): OnboardingExportRow | undefined {
    return this.db
      .prepare('SELECT * FROM finance_onboarding_exports WHERE pluggy_item_id IS ? AND export_version = ?')
      .get(pluggyItemId, version) as OnboardingExportRow | undefined
  }

  /** Idempotency lookup: has this exact (batch, transaction) row already been processed? */
  getImportRow(importBatchId: string, pluggyTransactionId: string): OnboardingImportRowRecord | undefined {
    return this.db
      .prepare('SELECT * FROM finance_onboarding_import_rows WHERE import_batch_id = ? AND pluggy_transaction_id = ?')
      .get(importBatchId, pluggyTransactionId) as OnboardingImportRowRecord | undefined
  }

  recordImportRow(input: {
    importBatchId: string
    pluggyTransactionId: string
    action: string
    status: ImportRowStatus
    errorCode?: string | null
    appliedAt?: string | null
  }): OnboardingImportRowRecord {
    const existing = this.getImportRow(input.importBatchId, input.pluggyTransactionId)
    if (existing) return existing // idempotent: never re-record, never re-apply

    const now = new Date().toISOString()
    const id = randomUUID()
    this.db
      .prepare(
        `INSERT INTO finance_onboarding_import_rows (
           id, import_batch_id, pluggy_transaction_id, action, status, error_code, applied_at, created_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        input.importBatchId,
        input.pluggyTransactionId,
        input.action,
        input.status,
        input.errorCode ?? null,
        input.appliedAt ?? null,
        now,
      )
    return this.getImportRow(input.importBatchId, input.pluggyTransactionId)!
  }

  listImportRows(importBatchId: string): OnboardingImportRowRecord[] {
    return this.db
      .prepare('SELECT * FROM finance_onboarding_import_rows WHERE import_batch_id = ? ORDER BY created_at ASC')
      .all(importBatchId) as OnboardingImportRowRecord[]
  }
}
