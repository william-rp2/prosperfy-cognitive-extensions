import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountPreferencesRepository } from './accountPreferencesRepository.js'
import { AccountsRepository } from './accountsRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'

let db: FinanceDb
let preferences: AccountPreferencesRepository
let accounts: AccountsRepository
let items: ItemsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  preferences = new AccountPreferencesRepository(db)
  accounts = new AccountsRepository(db)
  items = new ItemsRepository(db)
  items.upsertItem({
    pluggyItemId: 'item-1',
    connectorId: 200,
    connectorName: 'Bradesco',
    status: 'UPDATED',
    executionStatus: null,
    lastSuccessfulUpdate: null,
    rawMetadata: null,
  })
})

afterEach(() => {
  db.close()
})

describe('AccountPreferencesRepository', () => {
  const accountId = 'acc-123'

  it('persiste alias e favorito', () => {
    preferences.upsert(accountId, { displayAlias: 'Cartão C6 Black', isFavorite: true })
    const row = preferences.get(accountId)
    expect(row?.display_alias).toBe('Cartão C6 Black')
    expect(row?.is_favorite).toBe(1)
  })

  it('sync de conta não apaga preferências', () => {
    preferences.upsert(accountId, { displayAlias: 'Conta principal', isFavorite: true })
    accounts.upsertAccount({
      pluggyAccountId: accountId,
      pluggyItemId: 'item-1',
      name: 'BANDEIRADO',
      type: 'CREDIT',
      subtype: 'CREDIT_CARD',
      balanceCents: -10000,
    })
    accounts.upsertAccount({
      pluggyAccountId: accountId,
      pluggyItemId: 'item-1',
      name: 'Outro nome Pluggy',
      type: 'CREDIT',
      subtype: 'CREDIT_CARD',
      balanceCents: -20000,
    })
    const pref = preferences.get(accountId)
    expect(pref?.display_alias).toBe('Conta principal')
    expect(pref?.is_favorite).toBe(1)
  })

  it('permite remover alias', () => {
    preferences.upsert(accountId, { displayAlias: 'Apelido', isFavorite: false })
    preferences.clearAlias(accountId)
    expect(preferences.get(accountId)?.display_alias).toBeNull()
  })
})
