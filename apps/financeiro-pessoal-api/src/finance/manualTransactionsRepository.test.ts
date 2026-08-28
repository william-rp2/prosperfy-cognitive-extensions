import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { openFinanceDb, type FinanceDb } from './db.js'
import { ManualTransactionsRepository } from './manualTransactionsRepository.js'

let db: FinanceDb
let repo: ManualTransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  repo = new ManualTransactionsRepository(db)
})

afterEach(() => {
  db.close()
})

describe('ManualTransactionsRepository', () => {
  it('creates an expense and makes it immediately readable', () => {
    const row = repo.create({
      amountCents: 8900,
      direction: 'expense',
      occurredAt: '2026-08-15T12:00:00.000Z',
      description: 'Combustível',
      categoryId: 'cat_combustivel',
    })
    expect(row.source).toBe('manual')
    expect(row.reconciliation_status).toBe('unreconciled')
    expect(repo.getById(row.id)).toMatchObject({ amount_cents: 8900, direction: 'expense' })
  })

  it('rejects non-positive amounts', () => {
    expect(() => repo.create({ amountCents: 0, direction: 'expense', occurredAt: '2026-08-15T12:00:00.000Z', description: 'x' })).toThrow()
    expect(() => repo.create({ amountCents: -100, direction: 'expense', occurredAt: '2026-08-15T12:00:00.000Z', description: 'x' })).toThrow()
  })

  it('sumByDateRange buckets income and expense separately, scoped by date', () => {
    repo.create({ amountCents: 10000, direction: 'income', occurredAt: '2026-08-05T12:00:00.000Z', description: 'Freelance' })
    repo.create({ amountCents: 3000, direction: 'expense', occurredAt: '2026-08-06T12:00:00.000Z', description: 'Mercado' })
    repo.create({ amountCents: 5000, direction: 'expense', occurredAt: '2026-07-06T12:00:00.000Z', description: 'Fora do período' })

    const sum = repo.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z')
    expect(sum).toEqual({ income: 10000, expense: 3000 })
  })

  it('includes a manual entry dated exactly on the first day of the month (no off-by-one from date-only vs full-ISO string comparison)', () => {
    repo.create({ amountCents: 4200, direction: 'expense', occurredAt: '2026-08-01T12:00:00.000Z', description: 'Dia 1' })
    const sum = repo.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z')
    expect(sum.expense).toBe(4200)
  })

  it('sumByDateRange can be scoped to one categoryId', () => {
    repo.create({ amountCents: 3000, direction: 'expense', occurredAt: '2026-08-06T12:00:00.000Z', description: 'Mercado', categoryId: 'cat_alimentacao' })
    repo.create({ amountCents: 7000, direction: 'expense', occurredAt: '2026-08-07T12:00:00.000Z', description: 'Uber', categoryId: 'cat_transporte' })
    const sum = repo.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z', 'cat_alimentacao')
    expect(sum.expense).toBe(3000)
  })

  it('updateCategory reclassifies an existing manual entry', () => {
    const row = repo.create({ amountCents: 3000, direction: 'expense', occurredAt: '2026-08-06T12:00:00.000Z', description: 'Mercado' })
    const updated = repo.updateCategory(row.id, 'cat_alimentacao')
    expect(updated?.category_id).toBe('cat_alimentacao')
  })

  it('softDelete excludes the row from list() and sumByDateRange() without a hard delete', () => {
    const row = repo.create({ amountCents: 3000, direction: 'expense', occurredAt: '2026-08-06T12:00:00.000Z', description: 'Mercado' })
    repo.softDelete(row.id)
    expect(repo.list({ startDate: '2026-08-01', endDate: '2026-08-31' })).toHaveLength(0)
    expect(repo.sumByDateRange('2026-08-01T00:00:00.000Z', '2026-08-31T23:59:59.999Z').expense).toBe(0)
    // Row still physically exists (soft delete, not hard delete).
    const raw = db.prepare('SELECT deleted_at FROM financial_manual_transactions WHERE id = ?').get(row.id) as { deleted_at: string | null }
    expect(raw.deleted_at).not.toBeNull()
  })
})
