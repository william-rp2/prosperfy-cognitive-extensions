import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import type { FinancialItemRow } from './types.js'

export interface UpsertItemInput {
  pluggyItemId: string
  connectorId?: number | null
  connectorName?: string | null
  status: string
  executionStatus?: string | null
  lastSuccessfulUpdate?: string | null
  rawMetadata?: unknown
}

export class ItemsRepository {
  constructor(private readonly db: FinanceDb) {}

  upsertItem(input: UpsertItemInput): FinancialItemRow {
    const now = new Date().toISOString()
    const existing = this.getByPluggyId(input.pluggyItemId)

    this.db
      .prepare(
        `INSERT INTO financial_items (id, pluggy_item_id, connector_id, connector_name, status, execution_status, last_successful_update, created_at, updated_at, raw_metadata)
         VALUES (@id, @pluggyItemId, @connectorId, @connectorName, @status, @executionStatus, @lastSuccessfulUpdate, @createdAt, @updatedAt, @rawMetadata)
         ON CONFLICT(pluggy_item_id) DO UPDATE SET
           connector_id = excluded.connector_id,
           connector_name = excluded.connector_name,
           status = excluded.status,
           execution_status = excluded.execution_status,
           last_successful_update = excluded.last_successful_update,
           updated_at = excluded.updated_at,
           raw_metadata = excluded.raw_metadata`,
      )
      .run({
        id: existing?.id ?? randomUUID(),
        pluggyItemId: input.pluggyItemId,
        connectorId: input.connectorId ?? null,
        connectorName: input.connectorName ?? null,
        status: input.status,
        executionStatus: input.executionStatus ?? null,
        lastSuccessfulUpdate: input.lastSuccessfulUpdate ?? null,
        createdAt: existing?.created_at ?? now,
        updatedAt: now,
        rawMetadata: input.rawMetadata !== undefined ? JSON.stringify(input.rawMetadata) : null,
      })

    return this.getByPluggyId(input.pluggyItemId)!
  }

  touchSynced(pluggyItemId: string) {
    this.db
      .prepare('UPDATE financial_items SET last_synced_at = ?, updated_at = ? WHERE pluggy_item_id = ?')
      .run(new Date().toISOString(), new Date().toISOString(), pluggyItemId)
  }

  setErrorSummary(pluggyItemId: string, errorSummary: string | null) {
    this.db
      .prepare('UPDATE financial_items SET error_summary = ?, updated_at = ? WHERE pluggy_item_id = ?')
      .run(errorSummary, new Date().toISOString(), pluggyItemId)
  }

  getByPluggyId(pluggyItemId: string): FinancialItemRow | undefined {
    return this.db.prepare('SELECT * FROM financial_items WHERE pluggy_item_id = ?').get(pluggyItemId) as
      | FinancialItemRow
      | undefined
  }

  listAll(): FinancialItemRow[] {
    return this.db.prepare('SELECT * FROM financial_items ORDER BY created_at ASC').all() as FinancialItemRow[]
  }
}
