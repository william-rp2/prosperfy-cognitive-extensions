import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { OnboardingRepository } from './onboardingRepository.js'

let db: FinanceDb
let onboarding: OnboardingRepository
let items: ItemsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  onboarding = new OnboardingRepository(db)
  items = new ItemsRepository(db)
  items.upsertItem({ pluggyItemId: 'item-a', status: 'UPDATED' })
  items.upsertItem({ pluggyItemId: 'item-b', status: 'UPDATED' })
})

afterEach(() => {
  db.close()
})

describe('OnboardingRepository — estado incremental', () => {
  it('cria estado HISTORICAL_IMPORT na primeira vez e é idempotente', () => {
    const first = onboarding.getOrCreate('item-a')
    expect(first.mode).toBe('HISTORICAL_IMPORT')
    expect(first.onboarding_completed_at).toBeNull()

    const second = onboarding.getOrCreate('item-a')
    expect(second.id).toBe(first.id)
    expect(onboarding.listAll().filter(row => row.pluggy_item_id === 'item-a')).toHaveLength(1)
  })

  it('cutover explícito move para ONGOING sem exigir 100% de classificação', () => {
    onboarding.getOrCreate('item-a')
    const completed = onboarding.completeOnboarding('item-a', '2026-08-15T00:00:00.000Z')
    expect(completed?.mode).toBe('ONGOING')
    expect(completed?.historical_cutoff_at).toBe('2026-08-15T00:00:00.000Z')
    expect(completed?.onboarding_completed_at).not.toBeNull()
  })

  it('regra 9: adicionar um segundo banco não corrompe nem duplica o estado do primeiro', () => {
    const a = onboarding.getOrCreate('item-a')
    onboarding.completeOnboarding('item-a', '2026-08-01T00:00:00.000Z')
    const aAfterCutover = onboarding.getByItem('item-a')!

    // Second bank arrives independently, after the first is already ONGOING.
    const b = onboarding.getOrCreate('item-b')
    expect(b.mode).toBe('HISTORICAL_IMPORT')
    expect(b.id).not.toBe(a.id)

    // First bank's row is byte-for-byte unchanged by the second bank's onboarding.
    const aAfterSecondBank = onboarding.getByItem('item-a')!
    expect(aAfterSecondBank).toEqual(aAfterCutover)
    expect(onboarding.listAll()).toHaveLength(2)

    // Progressing item-b does not touch item-a either.
    onboarding.completeOnboarding('item-b', '2026-08-20T00:00:00.000Z')
    expect(onboarding.getByItem('item-a')).toEqual(aAfterCutover)
  })

  it('export version incrementa por item e é isolada entre itens', () => {
    const exportA1 = onboarding.recordExport({ pluggyItemId: 'item-a', filters: {}, rowCount: 3 })
    const exportA2 = onboarding.recordExport({ pluggyItemId: 'item-a', filters: {}, rowCount: 5 })
    const exportB1 = onboarding.recordExport({ pluggyItemId: 'item-b', filters: {}, rowCount: 1 })

    expect(exportA1.export_version).toBe(1)
    expect(exportA2.export_version).toBe(2)
    expect(exportB1.export_version).toBe(1)
  })

  it('recordImportRow é idempotente para a mesma chave (batch, transação)', () => {
    const first = onboarding.recordImportRow({
      importBatchId: 'batch-1',
      pluggyTransactionId: 'tx-1',
      action: 'update',
      status: 'applied',
      appliedAt: '2026-08-01T00:00:00.000Z',
    })
    const second = onboarding.recordImportRow({
      importBatchId: 'batch-1',
      pluggyTransactionId: 'tx-1',
      action: 'update',
      status: 'applied',
      appliedAt: '2026-08-02T00:00:00.000Z', // ignored: row already exists
    })
    expect(second.id).toBe(first.id)
    expect(second.applied_at).toBe(first.applied_at)
    expect(onboarding.listImportRows('batch-1')).toHaveLength(1)
  })
})
