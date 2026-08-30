import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { openFinanceDb, type FinanceDb } from './db.js'
import { TransactionAnnotationsRepository } from './transactionAnnotationsRepository.js'
import { TransactionReprocessService } from './transactionReprocessService.js'
import { AccountsRepository } from './accountsRepository.js'
import { CategoriesRepository } from './categoriesRepository.js'
import { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { ClassificationService } from './classificationService.js'
import { EnrichmentRepository } from './enrichmentRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let annotations: TransactionAnnotationsRepository
let transactions: TransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  annotations = new TransactionAnnotationsRepository(db)
  transactions = new TransactionsRepository(db)
})

afterEach(() => db.close())

describe('TransactionAnnotationsRepository', () => {
  function seedTransaction(txId = 'tx-1') {
    const items = new ItemsRepository(db)
    const accounts = new AccountsRepository(db)
    items.upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
    accounts.upsertAccount({
      pluggyAccountId: 'acc-1',
      pluggyItemId: 'item-1',
      type: 'BANK',
      subtype: 'CHECKING_ACCOUNT',
      name: 'Conta',
      balanceCents: 0,
    })
    transactions.upsertTransaction({
      pluggyTransactionId: txId,
      pluggyAccountId: 'acc-1',
      amountCents: -100,
      type: 'DEBIT',
      description: 'Teste',
      date: '2026-08-01T12:00:00.000Z',
      status: 'POSTED',
    })
  }

  it('K. create/update/delete annotation', () => {
    seedTransaction('tx-1')
    annotations.upsert('tx-1', 'Compra para cliente X')
    expect(annotations.get('tx-1')?.note).toBe('Compra para cliente X')

    annotations.upsert('tx-1', 'Reembolsável pela igreja')
    expect(annotations.get('tx-1')?.note).toBe('Reembolsável pela igreja')

    expect(annotations.delete('tx-1')).toBe(true)
    expect(annotations.get('tx-1')).toBeUndefined()
  })

  it('L. note sobrevive reprocess (tabela separada)', () => {
    const items = new ItemsRepository(db)
    const accounts = new AccountsRepository(db)
    const enrichment = new EnrichmentRepository(db)
    const clarifications = new ClarificationsRepository(db)
    const classification = new ClassificationService(
      enrichment,
      clarifications,
      new CategoriesRepository(db),
      new CategoryOverridesRepository(db),
      accounts,
    )

    items.upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
    accounts.upsertAccount({
      pluggyAccountId: 'card-1',
      pluggyItemId: 'item-1',
      type: 'CREDIT',
      subtype: 'CREDIT_CARD',
      name: 'BANDEIRADO',
      balanceCents: -1000,
    })
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-note',
      pluggyAccountId: 'card-1',
      amountCents: -1000,
      type: 'DEBIT',
      description: 'Compra mercado',
      date: '2026-08-01T12:00:00.000Z',
      status: 'POSTED',
    })
    annotations.upsert('tx-note', 'Presente aniversário')

    const service = new TransactionReprocessService(
      db,
      transactions,
      accounts,
      enrichment,
      clarifications,
      classification,
    )
    service.run({ dryRun: false })

    expect(annotations.get('tx-note')?.note).toBe('Presente aniversário')
  })

  it('M. busca encontra transaction por note', () => {
    seedTransaction('tx-a')
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-b',
      pluggyAccountId: 'acc-1',
      amountCents: -200,
      type: 'DEBIT',
      description: 'Outro',
      date: '2026-08-02T12:00:00.000Z',
      status: 'POSTED',
    })
    annotations.upsert('tx-a', 'Despesa da Prosperfy')
    annotations.upsert('tx-b', 'Outro contexto')
    const ids = annotations.searchNoteContains('Prosperfy')
    expect(ids).toEqual(['tx-a'])
  })
})
