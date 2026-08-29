import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type BudgetStatus = 'ok' | 'warning' | 'exceeded'

export interface FinancialBudgetRow {
  id: string
  month: string
  category_id: string | null
  limit_amount_cents: number
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface BudgetWithStatus {
  id: string
  month: string
  categoryId: string | null
  limitAmountCents: number
  spentCents: number
  remainingCents: number
  status: BudgetStatus
}

const WARNING_THRESHOLD = 0.8
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/

export function assertValidMonth(month: string): void {
  if (!MONTH_RE.test(month)) throw new Error(`month inválido: "${month}" (esperado YYYY-MM)`)
}

export function monthRange(month: string): { start: string; end: string } {
  assertValidMonth(month)
  const [year, mon] = month.split('-').map(Number)
  const start = new Date(Date.UTC(year, mon - 1, 1)).toISOString()
  const end = new Date(Date.UTC(year, mon, 0, 23, 59, 59, 999)).toISOString()
  return { start, end }
}

/**
 * Budgets are declarative (limit only); spent/remaining/status are always
 * derived at read time from financial_transactions + financial_manual_transactions
 * — never stored, so they can't drift from the ledger.
 */
export class BudgetsRepository {
  constructor(private readonly db: FinanceDb) {}

  upsert(month: string, categoryId: string | null, limitAmountCents: number): BudgetWithStatus {
    assertValidMonth(month)
    if (!Number.isInteger(limitAmountCents) || limitAmountCents < 0) {
      throw new Error('limitAmountCents deve ser um inteiro >= 0 (centavos)')
    }
    const now = new Date().toISOString()
    const existing = this.findRaw(month, categoryId)
    let id: string
    if (existing) {
      this.db
        .prepare('UPDATE financial_budgets SET limit_amount_cents = ?, updated_at = ?, deleted_at = NULL WHERE id = ?')
        .run(limitAmountCents, now, existing.id)
      id = existing.id
    } else {
      id = randomUUID()
      this.db
        .prepare('INSERT INTO financial_budgets (id, month, category_id, limit_amount_cents, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)')
        .run(id, month, categoryId, limitAmountCents, now, now)
    }
    return this.withStatus(this.getById(id)!)
  }

  getById(id: string): FinancialBudgetRow | undefined {
    return this.db.prepare('SELECT * FROM financial_budgets WHERE id = ?').get(id) as FinancialBudgetRow | undefined
  }

  findRaw(month: string, categoryId: string | null): FinancialBudgetRow | undefined {
    if (categoryId === null) {
      return this.db
        .prepare('SELECT * FROM financial_budgets WHERE month = ? AND category_id IS NULL AND deleted_at IS NULL')
        .get(month) as FinancialBudgetRow | undefined
    }
    return this.db
      .prepare('SELECT * FROM financial_budgets WHERE month = ? AND category_id = ? AND deleted_at IS NULL')
      .get(month, categoryId) as FinancialBudgetRow | undefined
  }

  private spentForCategory(month: string, categoryId: string): number {
    const { start, end } = monthRange(month)
    // Effective category = override if present, else a best-effort name match
    // against Pluggy's own category_original text. Unmatched Pluggy rows are
    // excluded here (they still count in the general/no-category budget).
    const pluggy = this.db
      .prepare(
        `SELECT COALESCE(SUM(ABS(t.amount_cents)),0) as spent
         FROM financial_transactions t
         LEFT JOIN financial_category_overrides o ON o.pluggy_transaction_id = t.pluggy_transaction_id
         LEFT JOIN financial_categories c ON lower(c.name) = lower(t.category_original)
         WHERE t.deleted_at IS NULL AND t.type = 'DEBIT' AND t.date >= ? AND t.date <= ?
           AND COALESCE(o.category_id, c.id) = ?`,
      )
      .get(start, end, categoryId) as { spent: number }

    const manual = this.db
      .prepare(
        `SELECT COALESCE(SUM(amount_cents),0) as spent FROM financial_manual_transactions
         WHERE deleted_at IS NULL AND direction = 'expense' AND occurred_at >= ? AND occurred_at <= ? AND category_id = ?`,
      )
      .get(start, end, categoryId) as { spent: number }

    return pluggy.spent + manual.spent
  }

  private spentGeneral(month: string): number {
    const { start, end } = monthRange(month)
    const pluggy = this.db
      .prepare(
        `SELECT COALESCE(SUM(ABS(amount_cents)),0) as spent FROM financial_transactions
         WHERE deleted_at IS NULL AND type = 'DEBIT' AND date >= ? AND date <= ?`,
      )
      .get(start, end) as { spent: number }
    const manual = this.db
      .prepare(
        `SELECT COALESCE(SUM(amount_cents),0) as spent FROM financial_manual_transactions
         WHERE deleted_at IS NULL AND direction = 'expense' AND occurred_at >= ? AND occurred_at <= ?`,
      )
      .get(start, end) as { spent: number }
    return pluggy.spent + manual.spent
  }

  private toStatus(spent: number, limit: number): BudgetStatus {
    if (limit <= 0) return spent > 0 ? 'exceeded' : 'ok'
    if (spent > limit) return 'exceeded'
    if (spent >= limit * WARNING_THRESHOLD) return 'warning'
    return 'ok'
  }

  private withStatus(row: FinancialBudgetRow): BudgetWithStatus {
    const spent = row.category_id ? this.spentForCategory(row.month, row.category_id) : this.spentGeneral(row.month)
    return {
      id: row.id,
      month: row.month,
      categoryId: row.category_id,
      limitAmountCents: row.limit_amount_cents,
      spentCents: spent,
      remainingCents: row.limit_amount_cents - spent,
      status: this.toStatus(spent, row.limit_amount_cents),
    }
  }

  listForMonth(month: string): BudgetWithStatus[] {
    assertValidMonth(month)
    const rows = this.db
      .prepare('SELECT * FROM financial_budgets WHERE month = ? AND deleted_at IS NULL ORDER BY category_id IS NULL DESC, category_id')
      .all(month) as FinancialBudgetRow[]
    return rows.map(row => this.withStatus(row))
  }

  getWithStatus(month: string, categoryId: string | null): BudgetWithStatus | undefined {
    const row = this.findRaw(month, categoryId)
    return row ? this.withStatus(row) : undefined
  }
}
