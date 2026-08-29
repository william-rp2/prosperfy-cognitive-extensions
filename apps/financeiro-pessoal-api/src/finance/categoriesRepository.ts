import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type CategoryKind = 'expense' | 'income' | 'both'

export interface FinancialCategoryRow {
  id: string
  name: string
  kind: CategoryKind
  created_at: string
}

export class CategoriesRepository {
  constructor(private readonly db: FinanceDb) {}

  listAll(): FinancialCategoryRow[] {
    return this.db.prepare('SELECT * FROM financial_categories ORDER BY name').all() as FinancialCategoryRow[]
  }

  getById(id: string): FinancialCategoryRow | undefined {
    return this.db.prepare('SELECT * FROM financial_categories WHERE id = ?').get(id) as FinancialCategoryRow | undefined
  }

  /**
   * Resolves free text (WhatsApp message fragments) against category names.
   * Returns exact (case-insensitive) matches first; falls back to substring
   * matches so callers can detect ambiguity (2+ results -> ask, don't guess).
   */
  findByName(name: string): FinancialCategoryRow[] {
    const normalized = name.trim().toLowerCase()
    if (!normalized) return []

    const exact = this.db
      .prepare('SELECT * FROM financial_categories WHERE lower(name) = ?')
      .all(normalized) as FinancialCategoryRow[]
    if (exact.length > 0) return exact

    return this.db
      .prepare('SELECT * FROM financial_categories WHERE lower(name) LIKE ? ORDER BY name')
      .all(`%${normalized}%`) as FinancialCategoryRow[]
  }

  create(name: string, kind: CategoryKind = 'expense'): FinancialCategoryRow {
    const id = `cat_${randomUUID().slice(0, 8)}`
    const now = new Date().toISOString()
    this.db.prepare('INSERT INTO financial_categories (id, name, kind, created_at) VALUES (?, ?, ?, ?)').run(id, name, kind, now)
    return this.getById(id)!
  }
}
