import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { ClarificationQueueService, MAX_DELIVERY_BATCH } from './clarificationQueueService.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { OnboardingRepository } from './onboardingRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let clarifications: ClarificationsRepository
let onboarding: OnboardingRepository
let queue: ClarificationQueueService
let transactions: TransactionsRepository

const ITEM = 'item-1'
const ACCOUNT = 'acc-1'

beforeEach(() => {
  db = openFinanceDb(':memory:')
  clarifications = new ClarificationsRepository(db)
  onboarding = new OnboardingRepository(db)
  queue = new ClarificationQueueService(clarifications, onboarding)
  transactions = new TransactionsRepository(db)

  new ItemsRepository(db).upsertItem({ pluggyItemId: ITEM, status: 'UPDATED' })
  new AccountsRepository(db).upsertAccount({ pluggyAccountId: ACCOUNT, pluggyItemId: ITEM, type: 'BANK', balanceCents: 0 })
})

afterEach(() => {
  db.close()
})

/** Seeds N historical transactions, each with one OPEN clarification. N is derived, never fixed. */
function seedOpenClarifications(count: number) {
  for (let i = 0; i < count; i += 1) {
    const txId = `tx-${i}`
    transactions.upsertTransaction({
      pluggyTransactionId: txId,
      pluggyAccountId: ACCOUNT,
      amountCents: -1000 - i,
      date: '2026-08-01T12:00:00.000Z',
      description: `Transação histórica ${i}`,
    })
    clarifications.getOrCreateOpen({ pluggyTransactionId: txId, questionType: 'category', questionText: 'Como classificar?' })
  }
}

describe('ClarificationQueueService — regra 7: sem disparo em massa histórico', () => {
  it('backlog histórico grande nunca produz entrega proativa (item ainda em HISTORICAL_IMPORT)', () => {
    onboarding.getOrCreate(ITEM) // starts HISTORICAL_IMPORT
    const backlogSize = 137 // arbitrary large N, not a magic contract number — just "large"
    seedOpenClarifications(backlogSize)

    expect(queue.countPending({ pluggyItemId: ITEM })).toBe(backlogSize)
    expect(queue.selectForOngoingDelivery({ pluggyItemId: ITEM })).toHaveLength(0)
  })

  it('lote sob demanda é sempre limitado a MAX_DELIVERY_BATCH, mesmo com backlog muito maior', () => {
    onboarding.getOrCreate(ITEM)
    const backlogSize = MAX_DELIVERY_BATCH * 10
    seedOpenClarifications(backlogSize)

    const batch = queue.selectHistoricalOnDemand(ITEM)
    expect(batch.length).toBeLessThanOrEqual(MAX_DELIVERY_BATCH)
    expect(batch.length).toBeLessThan(backlogSize)

    // Asking for more than the ceiling still yields at most the ceiling.
    const batchOverAsk = queue.selectHistoricalOnDemand(ITEM, { limit: backlogSize })
    expect(batchOverAsk.length).toBeLessThanOrEqual(MAX_DELIVERY_BATCH)

    // The full backlog is still there — selecting a batch does not resolve or hide anything.
    expect(queue.countPending({ pluggyItemId: ITEM })).toBe(backlogSize)
  })

  it('após cutover para ONGOING, entrega proativa passa a ser possível e continua limitada', () => {
    onboarding.getOrCreate(ITEM)
    seedOpenClarifications(50)
    onboarding.completeOnboarding(ITEM, '2026-08-15T00:00:00.000Z')

    const delivered = queue.selectForOngoingDelivery({ pluggyItemId: ITEM, limit: 3 })
    expect(delivered).toHaveLength(3)

    const uncapped = queue.selectForOngoingDelivery({ pluggyItemId: ITEM, limit: 999 })
    expect(uncapped.length).toBeLessThanOrEqual(MAX_DELIVERY_BATCH)
  })
})

describe('ClarificationQueueService — anti-spam', () => {
  it('sync repetido não infla a fila: OPEN_QUESTION_COUNT permanece 1 sem duplicar entregas', () => {
    onboarding.getOrCreate(ITEM)
    onboarding.completeOnboarding(ITEM, '2026-01-01T00:00:00.000Z')

    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-x',
      pluggyAccountId: ACCOUNT,
      amountCents: -500,
      date: '2026-08-01T12:00:00.000Z',
      description: 'Ambígua',
    })

    for (let i = 0; i < 10; i += 1) {
      clarifications.getOrCreateOpen({ pluggyTransactionId: 'tx-x', questionType: 'category', questionText: 'Como classificar?' })
    }

    expect(queue.countPending({ pluggyItemId: ITEM })).toBe(1)
    expect(queue.selectForOngoingDelivery({ pluggyItemId: ITEM })).toHaveLength(1)
  })
})
