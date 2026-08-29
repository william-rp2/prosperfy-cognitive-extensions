import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import type { FinancialTransactionRow } from './types.js'

export interface UpsertTransactionInput {
  pluggyTransactionId: string
  pluggyAccountId: string
  description?: string | null
  descriptionRaw?: string | null
  amountCents: number
  currencyCode?: string | null
  date: string
  status?: string | null
  type?: string | null
  categoryOriginal?: string | null
  merchantOriginal?: string | null
  balanceCents?: number | null
  rawData?: unknown
}

export interface TransactionFilters {
  accountId?: string
  startDate?: string
  endDate?: string
  category?: string
  minAmountCents?: number
  maxAmountCents?: number
  search?: string
  limit?: number
  offset?: number
}

export class TransactionsRepository {
  constructor(private readonly db: FinanceDb) {}

  /** Upserts a transaction. Returns whether it was newly created (for sync stats). */
  upsertTransaction(input: UpsertTransactionInput): { row: FinancialTransactionRow; created: boolean } {
    const now = new Date().toISOString()
    const existing = this.getByPluggyId(input.pluggyTransactionId)

    this.db
      .prepare(
        `INSERT INTO financial_transactions (id, pluggy_transaction_id, pluggy_account_id, description, description_raw, amount_cents, currency_code, date, status, type, category_original, merchant_original, balance_cents, created_at, updated_at, last_synced_at, raw_data)
         VALUES (@id, @pluggyTransactionId, @pluggyAccountId, @description, @descriptionRaw, @amountCents, @currencyCode, @date, @status, @type, @categoryOriginal, @merchantOriginal, @balanceCents, @createdAt, @updatedAt, @lastSyncedAt, @rawData)
         ON CONFLICT(pluggy_transaction_id) DO UPDATE SET
           description = excluded.description,
           description_raw = excluded.description_raw,
           amount_cents = excluded.amount_cents,
           currency_code = excluded.currency_code,
           date = excluded.date,
           status = excluded.status,
           type = excluded.type,
           category_original = excluded.category_original,
           merchant_original = excluded.merchant_original,
           balance_cents = excluded.balance_cents,
           updated_at = excluded.updated_at,
           last_synced_at = excluded.last_synced_at,
           raw_data = excluded.raw_data,
           deleted_at = NULL`,
      )
      .run({
        id: existing?.id ?? randomUUID(),
        pluggyTransactionId: input.pluggyTransactionId,
        pluggyAccountId: input.pluggyAccountId,
        description: input.description ?? null,
        descriptionRaw: input.descriptionRaw ?? null,
        amountCents: input.amountCents,
        currencyCode: input.currencyCode ?? null,
        date: input.date,
        status: input.status ?? null,
        type: input.type ?? null,
        categoryOriginal: input.categoryOriginal ?? null,
        merchantOriginal: input.merchantOriginal ?? null,
        balanceCents: input.balanceCents ?? null,
        createdAt: existing?.created_at ?? now,
        updatedAt: now,
        lastSyncedAt: now,
        rawData: input.rawData !== undefined ? JSON.stringify(input.rawData) : null,
      })

    return { row: this.getByPluggyId(input.pluggyTransactionId)!, created: !existing }
  }

  tombstone(pluggyTransactionId: string) {
    this.db
      .prepare('UPDATE financial_transactions SET deleted_at = ?, updated_at = ? WHERE pluggy_transaction_id = ?')
      .run(new Date().toISOString(), new Date().toISOString(), pluggyTransactionId)
  }

  getByPluggyId(pluggyTransactionId: string): FinancialTransactionRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_transactions WHERE pluggy_transaction_id = ?')
      .get(pluggyTransactionId) as FinancialTransactionRow | undefined
  }

  list(filters: TransactionFilters = {}): FinancialTransactionRow[] {
    const conditions: string[] = ['deleted_at IS NULL']
    const params: Record<string, unknown> = {}

    if (filters.accountId) {
      conditions.push('pluggy_account_id = @accountId')
      params.accountId = filters.accountId
    }
    if (filters.startDate) {
      conditions.push('date >= @startDate')
      params.startDate = filters.startDate
    }
    if (filters.endDate) {
      conditions.push('date <= @endDate')
      params.endDate = filters.endDate
    }
    if (filters.category) {
      conditions.push('category_original = @category')
      params.category = filters.category
    }
    if (filters.minAmountCents !== undefined) {
      conditions.push('amount_cents >= @minAmountCents')
      params.minAmountCents = filters.minAmountCents
    }
    if (filters.maxAmountCents !== undefined) {
      conditions.push('amount_cents <= @maxAmountCents')
      params.maxAmountCents = filters.maxAmountCents
    }
    if (filters.search) {
      conditions.push('(description LIKE @search OR description_raw LIKE @search)')
      params.search = `%${filters.search}%`
    }

    const limit = Math.min(filters.limit ?? 200, 1000)
    const offset = filters.offset ?? 0

    return this.db
      .prepare(
        `SELECT * FROM financial_transactions WHERE ${conditions.join(' AND ')} ORDER BY date DESC, id DESC LIMIT @limit OFFSET @offset`,
      )
      .all({ ...params, limit, offset }) as FinancialTransactionRow[]
  }

  /** Latest transaction createdAt/date for an account — used as the incremental sync cursor. */
  latestDateForAccount(pluggyAccountId: string): string | null {
    const row = this.db
      .prepare('SELECT MAX(date) as maxDate FROM financial_transactions WHERE pluggy_account_id = ?')
      .get(pluggyAccountId) as { maxDate: string | null } | undefined
    return row?.maxDate ?? null
  }

  /**
   * Buckets by the SDK's documented `type` field (CREDIT = money in, DEBIT = money
   * out), not by amount sign — sign convention flips for credit-card accounts.
   */
  sumByDateRange(startDate: string, endDate: string): { income: number; expense: number } {
    const row = this.db
      .prepare(
        `SELECT
           COALESCE(SUM(CASE WHEN type = 'CREDIT' THEN ABS(amount_cents) ELSE 0 END), 0) as income,
           COALESCE(SUM(CASE WHEN type = 'DEBIT' THEN ABS(amount_cents) ELSE 0 END), 0) as expense
         FROM financial_transactions
         WHERE deleted_at IS NULL AND date >= ? AND date <= ?`,
      )
      .get(startDate, endDate) as { income: number; expense: number }
    return row
  }

  /**
   * Same as sumByDateRange but scoped to one internal category — "effective"
   * category is the override (financial_category_overrides) when present,
   * else a case-insensitive name match against Pluggy's own category_original.
   * Unmatched rows (no override, no name match) are excluded — they still
   * count in the unscoped sumByDateRange/general budget.
   */
  sumByEffectiveCategoryAndDateRange(categoryId: string, startDate: string, endDate: string): { income: number; expense: number } {
    const row = this.db
      .prepare(
        `SELECT
           COALESCE(SUM(CASE WHEN t.type = 'CREDIT' THEN ABS(t.amount_cents) ELSE 0 END), 0) as income,
           COALESCE(SUM(CASE WHEN t.type = 'DEBIT' THEN ABS(t.amount_cents) ELSE 0 END), 0) as expense
         FROM financial_transactions t
         LEFT JOIN financial_category_overrides o ON o.pluggy_transaction_id = t.pluggy_transaction_id
         LEFT JOIN financial_categories c ON lower(c.name) = lower(t.category_original)
         WHERE t.deleted_at IS NULL AND t.date >= ? AND t.date <= ? AND COALESCE(o.category_id, c.id) = ?`,
      )
      .get(startDate, endDate, categoryId) as { income: number; expense: number }
    return row
  }

  /** Same effective-category resolution as sumByEffectiveCategoryAndDateRange, for listing instead of summing. */
  listByEffectiveCategory(
    categoryId: string,
    filters: { startDate?: string; endDate?: string; limit?: number; offset?: number } = {},
  ): FinancialTransactionRow[] {
    const conditions: string[] = ['t.deleted_at IS NULL', 'COALESCE(o.category_id, c.id) = @categoryId']
    const params: Record<string, unknown> = { categoryId }

    if (filters.startDate) {
      conditions.push('t.date >= @startDate')
      params.startDate = filters.startDate
    }
    if (filters.endDate) {
      conditions.push('t.date <= @endDate')
      params.endDate = filters.endDate
    }

    const limit = Math.min(filters.limit ?? 200, 1000)
    const offset = filters.offset ?? 0

    return this.db
      .prepare(
        `SELECT t.* FROM financial_transactions t
         LEFT JOIN financial_category_overrides o ON o.pluggy_transaction_id = t.pluggy_transaction_id
         LEFT JOIN financial_categories c ON lower(c.name) = lower(t.category_original)
         WHERE ${conditions.join(' AND ')}
         ORDER BY t.date DESC, t.id DESC LIMIT @limit OFFSET @offset`,
      )
      .all({ ...params, limit, offset }) as FinancialTransactionRow[]
  }
}
