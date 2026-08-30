import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { ClassificationService } from './classificationService.js'
import { CategoriesRepository } from './categoriesRepository.js'
import { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { EnrichmentRepository } from './enrichmentRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb

beforeEach(() => {
  db = openFinanceDb(':memory:')
})

afterEach(() => {
  db.close()
})

describe('ClassificationService — payment semantics', () => {
  it('classifica compra em cartão de crédito mesmo com raw DEBIT', () => {
    const items = new ItemsRepository(db)
    items.upsertItem({
      pluggyItemId: 'item-1',
      connectorId: 200,
      connectorName: 'Bradesco',
      status: 'UPDATED',
      executionStatus: null,
      lastSuccessfulUpdate: null,
      rawMetadata: null,
    })
    const accounts = new AccountsRepository(db)
    accounts.upsertAccount({
      pluggyAccountId: 'card-1',
      pluggyItemId: 'item-1',
      type: 'CREDIT',
      subtype: 'CREDIT_CARD',
      name: 'BANDEIRADO',
      balanceCents: -5000,
    })

    const enrichment = new EnrichmentRepository(db)
    const transactions = new TransactionsRepository(db)
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-1',
      pluggyAccountId: 'card-1',
      amountCents: -5000,
      type: 'DEBIT',
      description: 'Compra mercado',
      date: '2026-08-01T12:00:00.000Z',
      status: 'POSTED',
    })

    const service = new ClassificationService(
      enrichment,
      new ClarificationsRepository(db),
      new CategoriesRepository(db),
      new CategoryOverridesRepository(db),
      accounts,
    )

    const txRow = transactions.getByPluggyId('tx-1')
    if (!txRow) throw new Error('missing tx')
    service.classifyPluggyTransaction(txRow)

    const enriched = enrichment.getByTransactionId('tx-1')
    expect(enriched?.canonical_type).toBe('CREDIT_PURCHASE')
    expect(enriched?.payment_method).toBe('CREDIT_CARD')
  })
})
