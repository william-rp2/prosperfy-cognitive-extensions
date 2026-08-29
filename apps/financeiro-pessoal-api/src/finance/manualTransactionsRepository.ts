import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type ManualDirection = 'income' | 'expense'

export interface FinancialManualTransactionRow {
  id: string
  source: string
  amount_cents: number
  direction: ManualDirection
  occurred_at: string
  description: string
  category_id: string | null
  account_id: string | null
  notes: string | null
  created_by: string
  reconciliation_status: string
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface CreateManualTransactionInput {
  amountCents: number
  direction: ManualDirection
  occurredAt: string
  description: string
  categoryId?: string | null
  accountId?: string | null
  notes?: string | null
  createdBy?: string
}

export interface ManualTransactionFilters {
  startDate?: string
  endDate?: string
  categoryId?: string
  search?: string
  limit?: number
  offset?: number
}

/** Money in/out entered directly by the user — never merged into financial_transactions (that table is Pluggy-only). */
export class ManualTransactionsRepository {
  constructor(private readonly db: FinanceDb) {}

  create(input: CreateManualTransactionInput): FinancialManualTransactionRow {
    if (!Number.isInteger(input.amountCents) || input.amountCents <= 0) {
      throw new Error('amountCents deve ser um inteiro positivo (centavos)')
    }
    const id = randomUUID()
    const now = new Date().toISOString()
    this.db
      .prepare(
        `INSERT INTO financial_manual_transactions
           (id, source, amount_cents, direction, occurred_at, description, category_id, account_id, notes, created_by, reconciliation_status, created_at, updated_at)
         VALUES (@id, 'manual', @amountCents, @direction, @occurredAt, @description, @categoryId, @accountId, @notes, @createdBy, 'unreconciled', @createdAt, @updatedAt)`,
      )
      .run({
        id,
        amountCents: input.amountCents,
        direction: input.direction,
        occurredAt: input.occurredAt,
        description: input.description,
        categoryId: input.categoryId ?? null,
        accountId: input.accountId ?? null,
        notes: input.notes ?? null,
        createdBy: input.createdBy ?? 'cognitive',
        createdAt: now,
        updatedAt: now,
      })
    return this.getById(id)!
  }

  getById(id: string): FinancialManualTransactionRow | undefined {
    return this.db.prepare('SELECT * FROM financial_manual_transactions WHERE id = ?').get(id) as
      | FinancialManualTransactionRow
      | undefined
  }

  list(filters: ManualTransactionFilters = {}): FinancialManualTransactionRow[] {
    const conditions: string[] = ['deleted_at IS NULL']
    const params: Record<string, unknown> = {}

    if (filters.startDate) {
      conditions.push('occurred_at >= @startDate')
      params.startDate = filters.startDate
    }
    if (filters.endDate) {
      conditions.push('occurred_at <= @endDate')
      params.endDate = filters.endDate
    }
    if (filters.categoryId) {
      conditions.push('category_id = @categoryId')
      params.categoryId = filters.categoryId
    }
    if (filters.search) {
      conditions.push('description LIKE @search')
      params.search = `%${filters.search}%`
    }

    const limit = Math.min(filters.limit ?? 200, 1000)
    const offset = filters.offset ?? 0

    return this.db
      .prepare(
        `SELECT * FROM financial_manual_transactions WHERE ${conditions.join(' AND ')} ORDER BY occurred_at DESC, id DESC LIMIT @limit OFFSET @offset`,
      )
      .all({ ...params, limit, offset }) as FinancialManualTransactionRow[]
  }

  /**
   * Same shape as TransactionsRepository.sumByDateRange so callers can add the
   * two together for a combined total. Pass categoryId to scope the sum to one
   * internal category (used when a budget/summary query is category-filtered).
   */
  sumByDateRange(startDate: string, endDate: string, categoryId?: string): { income: number; expense: number } {
    const categoryClause = categoryId ? 'AND category_id = @categoryId' : ''
    const row = this.db
      .prepare(
        `SELECT
           COALESCE(SUM(CASE WHEN direction = 'income' THEN amount_cents ELSE 0 END), 0) as income,
           COALESCE(SUM(CASE WHEN direction = 'expense' THEN amount_cents ELSE 0 END), 0) as expense
         FROM financial_manual_transactions
         WHERE deleted_at IS NULL AND occurred_at >= @startDate AND occurred_at <= @endDate ${categoryClause}`,
      )
      .get({ startDate, endDate, categoryId }) as { income: number; expense: number }
    return row
  }

  updateCategory(id: string, categoryId: string | null): FinancialManualTransactionRow | undefined {
    const now = new Date().toISOString()
    this.db
      .prepare('UPDATE financial_manual_transactions SET category_id = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL')
      .run(categoryId, now, id)
    return this.getById(id)
  }

  /** Soft delete only — CONFIRM-gated at the route layer, never a hard DELETE. */
  softDelete(id: string): void {
    const now = new Date().toISOString()
    this.db.prepare('UPDATE financial_manual_transactions SET deleted_at = ?, updated_at = ? WHERE id = ?').run(now, now, id)
  }
}
