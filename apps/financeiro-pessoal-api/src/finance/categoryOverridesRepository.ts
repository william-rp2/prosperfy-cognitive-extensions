import type { FinanceDb } from './db.js'

export interface FinancialCategoryOverrideRow {
  pluggy_transaction_id: string
  category_id: string
  previous_category_original: string | null
  overridden_by: string
  created_at: string
  updated_at: string
}

/**
 * Per-transaction reclassification, keyed by pluggy_transaction_id. Deliberately
 * separate from financial_transactions — a future Pluggy sync upserts that row
 * again (category_original may change) but never touches this table, so the
 * user's override survives.
 */
export class CategoryOverridesRepository {
  constructor(private readonly db: FinanceDb) {}

  get(pluggyTransactionId: string): FinancialCategoryOverrideRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_category_overrides WHERE pluggy_transaction_id = ?')
      .get(pluggyTransactionId) as FinancialCategoryOverrideRow | undefined
  }

  set(
    pluggyTransactionId: string,
    categoryId: string,
    previousCategoryOriginal: string | null,
    overriddenBy = 'cognitive',
  ): FinancialCategoryOverrideRow {
    const now = new Date().toISOString()
    this.db
      .prepare(
        `INSERT INTO financial_category_overrides (pluggy_transaction_id, category_id, previous_category_original, overridden_by, created_at, updated_at)
         VALUES (@id, @categoryId, @previous, @by, @now, @now)
         ON CONFLICT(pluggy_transaction_id) DO UPDATE SET
           category_id = excluded.category_id,
           overridden_by = excluded.overridden_by,
           updated_at = excluded.updated_at`,
      )
      .run({ id: pluggyTransactionId, categoryId, previous: previousCategoryOriginal, by: overriddenBy, now })
    return this.get(pluggyTransactionId)!
  }
}
