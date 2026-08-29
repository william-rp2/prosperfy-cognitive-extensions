import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let clarifications: ClarificationsRepository
let transactions: TransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  clarifications = new ClarificationsRepository(db)
  transactions = new TransactionsRepository(db)
  const items = new ItemsRepository(db)
  const accounts = new AccountsRepository(db)
  items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
  accounts.upsertAccount({ pluggyAccountId: 'acc-1', pluggyItemId: 'item-1', type: 'BANK', balanceCents: 0 })
  transactions.upsertTransaction({
    pluggyTransactionId: 'tx-1',
    pluggyAccountId: 'acc-1',
    amountCents: 5000,
    date: '2026-08-01T12:00:00.000Z',
    description: 'Compra desconhecida',
  })
})

afterEach(() => {
  db.close()
})

describe('ClarificationsRepository', () => {
  it('cria OPEN na primeira ambiguidade e deduplica nas próximas', () => {
    const input = { pluggyTransactionId: 'tx-1', questionType: 'category', questionText: 'Como classificar?' }

    const first = clarifications.getOrCreateOpen(input)
    expect(first.created).toBe(true)
    expect(first.row.status).toBe('open')

    const second = clarifications.getOrCreateOpen(input)
    expect(second.created).toBe(false)
    expect(second.row.id).toBe(first.row.id)

    const third = clarifications.getOrCreateOpen(input)
    expect(third.created).toBe(false)
    expect(clarifications.countOpenForTransaction('tx-1')).toBe(1)
  })
})
