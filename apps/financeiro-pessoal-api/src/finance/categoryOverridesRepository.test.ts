import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let overrides: CategoryOverridesRepository
let transactions: TransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  overrides = new CategoryOverridesRepository(db)
  transactions = new TransactionsRepository(db)
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

describe('CategoryOverridesRepository', () => {
  it('sets and reads back an override with the previous Pluggy category preserved for audit', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'account-1',
      amountCents: 5490,
      date: '2026-08-10T12:00:00.000Z',
      type: 'DEBIT',
      categoryOriginal: 'Supermercado',
    })

    overrides.set('tx-1', 'cat_alimentacao', 'Supermercado')
    const row = overrides.get('tx-1')
    expect(row?.category_id).toBe('cat_alimentacao')
    expect(row?.previous_category_original).toBe('Supermercado')
  })

  it('survives a future Pluggy sync that re-upserts the same transaction (category_original never overwritten by the override)', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'account-1',
      amountCents: 5490,
      date: '2026-08-10T12:00:00.000Z',
      type: 'DEBIT',
      categoryOriginal: 'Supermercado',
    })
    overrides.set('tx-1', 'cat_alimentacao', 'Supermercado')

    // Simulates PluggySyncService re-upserting the same transaction on a later sync run.
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'account-1',
      amountCents: 5490,
      date: '2026-08-10T12:00:00.000Z',
      type: 'DEBIT',
      categoryOriginal: 'Supermercado', // Pluggy's own text is untouched by the override
    })

    expect(overrides.get('tx-1')?.category_id).toBe('cat_alimentacao')
    expect(transactions.getByPluggyId('tx-1')?.category_original).toBe('Supermercado')
  })

  it('set() is idempotent per transaction (upsert, not insert-only)', () => {
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'account-1',
      amountCents: 5490,
      date: '2026-08-10T12:00:00.000Z',
      type: 'DEBIT',
    })
    overrides.set('tx-1', 'cat_alimentacao', null)
    overrides.set('tx-1', 'cat_lazer', null)
    expect(overrides.get('tx-1')?.category_id).toBe('cat_lazer')
  })
})
