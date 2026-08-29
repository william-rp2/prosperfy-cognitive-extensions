import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { assertValidMonth, BudgetsRepository } from './budgetsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ManualTransactionsRepository } from './manualTransactionsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let budgets: BudgetsRepository
let transactions: TransactionsRepository
let manual: ManualTransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  budgets = new BudgetsRepository(db)
  transactions = new TransactionsRepository(db)
  manual = new ManualTransactionsRepository(db)
  db.prepare(
    `INSERT INTO financial_items (id, pluggy_item_id, status, created_at, updated_at) VALUES ('item-row-1', 'item-1', 'UPDATED', datetime('now'), datetime('now'))`,
  ).run()
  db.prepare(
    `INSERT INTO financial_accounts (id, pluggy_account_id, pluggy_item_id, type, created_at, updated_at)
     VALUES ('acc-row-1', 'account-1', 'item-1', 'BANK', datetime('now'), datetime('now'))`,
  ).run()
})

afterEach(() => {
  db.close()
})

describe('assertValidMonth', () => {
  it('accepts YYYY-MM and rejects anything else', () => {
    expect(() => assertValidMonth('2026-08')).not.toThrow()
    expect(() => assertValidMonth('2026-8')).toThrow()
    expect(() => assertValidMonth('08-2026')).toThrow()
    expect(() => assertValidMonth('2026-13')).toThrow()
  })
})

describe('BudgetsRepository', () => {
  function seedAugustSpend() {
    // Pluggy transaction matched by name (no explicit override) — 30,00 expense.
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'account-1',
      amountCents: 3000,
      date: '2026-08-10T12:00:00.000Z',
      type: 'DEBIT',
      categoryOriginal: 'Alimentação',
    })
    // Manual expense in the same category — 20,00.
    manual.create({ amountCents: 2000, direction: 'expense', occurredAt: '2026-08-12T12:00:00.000Z', description: 'Padaria', categoryId: 'cat_alimentacao' })
    // Unrelated category, must not leak into the alimentação budget.
    manual.create({ amountCents: 9999, direction: 'expense', occurredAt: '2026-08-13T12:00:00.000Z', description: 'Uber', categoryId: 'cat_transporte' })
  }

  it('upsert creates then updates the same (month, category) budget in place', () => {
    const created = budgets.upsert('2026-08', 'cat_alimentacao', 5000)
    const updated = budgets.upsert('2026-08', 'cat_alimentacao', 8000)
    expect(updated.id).toBe(created.id)
    expect(updated.limitAmountCents).toBe(8000)
  })

  it('enforces one general (category_id NULL) budget per month via upsert, not duplicate rows', () => {
    budgets.upsert('2026-08', null, 100000)
    budgets.upsert('2026-08', null, 150000)
    expect(budgets.listForMonth('2026-08').filter(b => b.categoryId === null)).toHaveLength(1)
  })

  it('spent combines Pluggy (name-matched) + manual within one category, excluding other categories', () => {
    seedAugustSpend()
    const budget = budgets.upsert('2026-08', 'cat_alimentacao', 6000)
    expect(budget.spentCents).toBe(5000) // 3000 (pluggy) + 2000 (manual), not the 9999 transporte entry
    expect(budget.remainingCents).toBe(1000)
  })

  it('status is ok below 80%, warning at/above 80%, exceeded over 100%', () => {
    seedAugustSpend() // 5000 cents spent in cat_alimentacao

    expect(budgets.upsert('2026-08', 'cat_alimentacao', 10000).status).toBe('ok') // 50%
    expect(budgets.upsert('2026-08', 'cat_alimentacao', 6000).status).toBe('warning') // 83.3%
    expect(budgets.upsert('2026-08', 'cat_alimentacao', 4000).status).toBe('exceeded') // 125%
  })

  it('general budget (category_id null) sums every expense in the month regardless of category', () => {
    seedAugustSpend() // 3000 + 2000 + 9999 = 14999 total expense
    const general = budgets.upsert('2026-08', null, 20000)
    expect(general.spentCents).toBe(14999)
  })

  it('a category override changes which budget a transaction counts against', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-override',
      pluggyAccountId: 'account-1',
      amountCents: 5000,
      date: '2026-08-15T12:00:00.000Z',
      type: 'DEBIT',
      categoryOriginal: 'Uncategorized Merchant', // no name match to any internal category
    })
    db.prepare(
      `INSERT INTO financial_category_overrides (pluggy_transaction_id, category_id, previous_category_original, overridden_by, created_at, updated_at)
       VALUES ('tx-override', 'cat_lazer', 'Uncategorized Merchant', 'test', datetime('now'), datetime('now'))`,
    ).run()

    const lazer = budgets.upsert('2026-08', 'cat_lazer', 100000)
    expect(lazer.spentCents).toBe(5000)
  })
})
