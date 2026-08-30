import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { CategoriesRepository } from './categoriesRepository.js'
import { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { ClassificationService } from './classificationService.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { EnrichmentRepository } from './enrichmentRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { TransactionReprocessService } from './transactionReprocessService.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let items: ItemsRepository
let accounts: AccountsRepository
let transactions: TransactionsRepository
let enrichment: EnrichmentRepository
let clarifications: ClarificationsRepository
let classification: ClassificationService
let service: TransactionReprocessService

function seedCreditCardAccount(accountId = 'card-1') {
  items.upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
  accounts.upsertAccount({
    pluggyAccountId: accountId,
    pluggyItemId: 'item-1',
    type: 'CREDIT',
    subtype: 'CREDIT_CARD',
    name: 'BANDEIRADO',
    balanceCents: -5000,
  })
}

function seedDebitTx(txId = 'tx-cc-debit', accountId = 'card-1') {
  transactions.upsertTransaction({
    pluggyTransactionId: txId,
    pluggyAccountId: accountId,
    amountCents: -5000,
    type: 'DEBIT',
    description: 'Compra mercado',
    date: '2026-08-01T12:00:00.000Z',
    status: 'POSTED',
  })
}

function buildService() {
  return new TransactionReprocessService(
    db,
    transactions,
    accounts,
    enrichment,
    clarifications,
    classification,
  )
}

beforeEach(() => {
  db = openFinanceDb(':memory:')
  items = new ItemsRepository(db)
  accounts = new AccountsRepository(db)
  transactions = new TransactionsRepository(db)
  enrichment = new EnrichmentRepository(db)
  clarifications = new ClarificationsRepository(db)
  classification = new ClassificationService(
    enrichment,
    clarifications,
    new CategoriesRepository(db),
    new CategoryOverridesRepository(db),
    accounts,
  )
  service = buildService()
})

afterEach(() => db.close())

describe('TransactionReprocessService — F2A.1 historical reprocess', () => {
  it('A. CREDIT_CARD + raw DEBIT histórico → CREDIT_CARD payment + CREDIT_PURCHASE', () => {
    seedCreditCardAccount()
    seedDebitTx()
    enrichment.upsert({
      pluggyTransactionId: 'tx-cc-debit',
      paymentMethod: 'DEBIT_CARD',
      canonicalType: 'DEBIT_PURCHASE',
      direction: 'OUT',
      rawType: 'DEBIT',
      classificationStatus: 'classified',
      classificationSource: 'unknown',
      classificationConfidence: 0.2,
    })

    const first = service.run({})
    expect(first.updated).toBe(1)

    const row = enrichment.getByTransactionId('tx-cc-debit')
    expect(row?.payment_method).toBe('CREDIT_CARD')
    expect(row?.canonical_type).toBe('CREDIT_PURCHASE')
    expect(row?.direction).toBe('OUT')
  })

  it('B. segunda execução idempotente', () => {
    seedCreditCardAccount()
    seedDebitTx()
    service.run({})
    const second = service.run({})
    expect(second.updated).toBe(0)
    expect(second.unchanged).toBe(1)
  })

  it('C. não duplica clarification', () => {
    seedCreditCardAccount()
    seedDebitTx()
    const first = service.run({})
    expect(first.clarificationsCreated).toBe(1)
    expect(clarifications.countOpenForTransaction('tx-cc-debit')).toBe(1)

    const second = service.run({})
    expect(second.clarificationsCreated).toBe(0)
    expect(clarifications.countOpenForTransaction('tx-cc-debit')).toBe(1)
  })

  it('D. não altera source transaction', () => {
    seedCreditCardAccount()
    seedDebitTx()
    const before = transactions.getByPluggyId('tx-cc-debit')!
    const snapshot = JSON.stringify({
      description: before.description,
      amount_cents: before.amount_cents,
      type: before.type,
      last_synced_at: before.last_synced_at,
      raw_data: before.raw_data,
    })

    service.run({})

    const after = transactions.getByPluggyId('tx-cc-debit')!
    expect(JSON.stringify({
      description: after.description,
      amount_cents: after.amount_cents,
      type: after.type,
      last_synced_at: after.last_synced_at,
      raw_data: after.raw_data,
    })).toBe(snapshot)
  })

  it('E. missing account context fail-safe', () => {
    seedCreditCardAccount('card-1')
    seedDebitTx('tx-orphan', 'card-1')
    db.pragma('foreign_keys = OFF')
    db.prepare('UPDATE financial_transactions SET pluggy_account_id = ? WHERE pluggy_transaction_id = ?').run(
      'missing-account',
      'tx-orphan',
    )
    db.pragma('foreign_keys = ON')

    const metrics = service.run({})
    expect(metrics.accountContextMissing).toBe(1)
    expect(metrics.updated).toBe(0)
    expect(enrichment.getByTransactionId('tx-orphan')).toBeUndefined()
  })

  it('F. dry-run não escreve', () => {
    seedCreditCardAccount()
    seedDebitTx()
    enrichment.upsert({
      pluggyTransactionId: 'tx-cc-debit',
      paymentMethod: 'DEBIT_CARD',
      canonicalType: 'DEBIT_PURCHASE',
      direction: 'OUT',
      rawType: 'DEBIT',
      classificationStatus: 'classified',
      classificationSource: 'unknown',
      classificationConfidence: 0.2,
    })

    const dry = service.run({ dryRun: true })
    expect(dry.updated).toBe(1)
    expect(dry.dryRun).toBe(true)

    const row = enrichment.getByTransactionId('tx-cc-debit')
    expect(row?.payment_method).toBe('DEBIT_CARD')
    expect(clarifications.countOpenForTransaction('tx-cc-debit')).toBe(0)
  })

  it('G. uma falha não aborta demais registros', () => {
    seedCreditCardAccount()
    seedDebitTx('tx-bad', 'card-1')
    seedDebitTx('tx-good', 'card-1')

    db.prepare('UPDATE financial_transactions SET raw_data = ? WHERE pluggy_transaction_id = ?').run(
      '{invalid-json',
      'tx-bad',
    )

    const metrics = service.run({})
    expect(metrics.processed).toBe(2)
    expect(metrics.failed).toBe(1)
    expect(enrichment.getByTransactionId('tx-good')).toBeDefined()
  })
})
