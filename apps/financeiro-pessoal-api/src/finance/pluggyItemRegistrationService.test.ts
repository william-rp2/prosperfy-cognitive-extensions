import type { Item } from 'pluggy-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PluggySyncClient } from '../pluggy.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { PluggyItemRegistrationService } from './pluggyItemRegistrationService.js'
import type { PluggySyncService } from './pluggySyncService.js'

class FakePluggy implements PluggySyncClient {
  items = new Map<string, Item>()
  deny = new Set<string>()

  async fetchItem(itemId: string) {
    if (this.deny.has(itemId)) throw new Error('403 forbidden')
    const item = this.items.get(itemId)
    if (!item) throw new Error('404 not found')
    return item
  }

  async fetchAccounts() {
    return []
  }
  async fetchAllTransactions() {
    return []
  }
  async fetchCreditCardBills() {
    return []
  }
  async fetchInvestments() {
    return []
  }
}

function makeItem(id: string): Item {
  return { id, status: 'UPDATED', connector: { id: 200, name: 'Bradesco' } } as Item
}

let db: FinanceDb
let items: ItemsRepository
let fake: FakePluggy
let syncOne: ReturnType<typeof vi.fn>

function buildService() {
  syncOne = vi.fn().mockResolvedValue({ status: 'success' })
  return new PluggyItemRegistrationService({
    pluggy: fake,
    items,
    syncService: { syncOne } as unknown as PluggySyncService,
    clientUserId: 'poc-william',
  })
}

beforeEach(() => {
  db = openFinanceDb(':memory:')
  items = new ItemsRepository(db)
  fake = new FakePluggy()
})

afterEach(() => {
  db.close()
})

describe('PluggyItemRegistrationService', () => {
  const validId = '11111111-1111-4111-8111-111111111111'

  it('rejeita Item ID inválido', async () => {
    const result = await buildService().registerItem('not-a-uuid')
    expect(result.outcome).toBe('invalid_id')
  })

  it('registra Item válido e dispara syncOne', async () => {
    fake.items.set(validId, makeItem(validId))
    const result = await buildService().registerItem(validId)
    expect(result.outcome).toBe('created')
    expect(syncOne).toHaveBeenCalledWith(validId, 'initial')
    expect(items.getByPluggyId(validId)).toBeDefined()
  })

  it('detecta Item já cadastrado', async () => {
    fake.items.set(validId, makeItem(validId))
    const service = buildService()
    await service.registerItem(validId)
    const second = await service.registerItem(validId)
    expect(second.outcome).toBe('already_registered')
  })

  it('trata Item inacessível', async () => {
    fake.deny.add(validId)
    fake.items.set(validId, makeItem(validId))
    const result = await buildService().registerItem(validId)
    expect(result.outcome).toBe('not_accessible')
  })
})
