import type { Account, CreditCardBills, Investment, Item, Transaction } from 'pluggy-sdk'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { PluggySyncClient } from '../pluggy.js'
import { AccountsRepository } from './accountsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { PluggySyncService } from './pluggySyncService.js'
import { ProductsRepository } from './productsRepository.js'
import { SyncAlreadyRunningError, SyncRunsRepository } from './syncRunsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

function makeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: 'item-1',
    connector: { id: 200, name: 'Meu Pluggy' },
    status: 'UPDATED',
    statusDetail: null,
    error: null,
    executionStatus: 'SUCCESS',
    createdAt: new Date('2026-01-01T00:00:00.000Z'),
    updatedAt: new Date('2026-01-01T00:00:00.000Z'),
    lastUpdatedAt: new Date('2026-01-01T00:00:00.000Z'),
    parameter: null,
    webhookUrl: null,
    clientUserId: 'poc-william',
    userAction: null,
    consecutiveFailedLoginAttempts: 0,
    nextAutoSyncAt: null,
    consentExpiresAt: null,
    ...overrides,
  } as unknown as Item
}

function makeAccount(overrides: Partial<Account> = {}): Account {
  return {
    id: 'account-1',
    itemId: 'item-1',
    type: 'BANK',
    subtype: 'CHECKING_ACCOUNT',
    number: '00001234',
    balance: 1000.5,
    name: 'Conta corrente',
    marketingName: null,
    owner: 'William',
    taxNumber: null,
    currencyCode: 'BRL',
    bankData: null,
    creditData: null,
    ...overrides,
  } as unknown as Account
}

function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: 'tx-1',
    accountId: 'account-1',
    date: new Date('2026-08-01T12:00:00.000Z'),
    description: 'Mercado',
    descriptionRaw: 'MERCADO LTDA',
    type: 'DEBIT',
    amount: 123.45,
    amountInAccountCurrency: null,
    balance: 900,
    currencyCode: 'BRL',
    category: 'Mercado',
    status: undefined,
    providerCode: undefined,
    paymentData: undefined,
    creditCardMetadata: null,
    merchant: undefined,
    categoryId: null,
    operationType: null,
    operationTypeAdditionalInfo: null,
    providerId: null,
    createdAt: new Date('2026-08-01T12:00:00.000Z'),
    updatedAt: new Date('2026-08-01T12:00:00.000Z'),
    ...overrides,
  } as unknown as Transaction
}

class FakePluggySyncClient implements PluggySyncClient {
  items = new Map<string, Item>()
  accounts = new Map<string, Account[]>()
  transactions = new Map<string, Transaction[]>()
  bills = new Map<string, CreditCardBills[]>()
  investments = new Map<string, Investment[]>()
  failingItemIds = new Set<string>()
  fetchAllTransactionsCalls: Array<{ accountId: string; dateFrom?: string }> = []

  async fetchItem(itemId: string): Promise<Item> {
    if (this.failingItemIds.has(itemId)) throw new Error(`falha simulada ao buscar item ${itemId}`)
    const item = this.items.get(itemId)
    if (!item) throw new Error(`item desconhecido no fake: ${itemId}`)
    return item
  }

  async fetchAccounts(itemId: string): Promise<Account[]> {
    return this.accounts.get(itemId) ?? []
  }

  async fetchAllTransactions(accountId: string, filters: { dateFrom?: string; dateTo?: string }): Promise<Transaction[]> {
    this.fetchAllTransactionsCalls.push({ accountId, dateFrom: filters.dateFrom })
    return this.transactions.get(accountId) ?? []
  }

  async fetchCreditCardBills(accountId: string): Promise<CreditCardBills[]> {
    return this.bills.get(accountId) ?? []
  }

  async fetchInvestments(itemId: string): Promise<Investment[]> {
    return this.investments.get(itemId) ?? []
  }
}

let db: FinanceDb
let items: ItemsRepository
let accounts: AccountsRepository
let transactions: TransactionsRepository
let products: ProductsRepository
let syncRuns: SyncRunsRepository
let fake: FakePluggySyncClient

function buildService(overrides: Partial<{ safetyWindowHours: number; maxConcurrentItems: number }> = {}) {
  return new PluggySyncService({
    pluggy: fake,
    items,
    accounts,
    transactions,
    products,
    syncRuns,
    safetyWindowHours: overrides.safetyWindowHours ?? 24,
    maxConcurrentItems: overrides.maxConcurrentItems ?? 3,
  })
}

beforeEach(() => {
  db = openFinanceDb(':memory:')
  items = new ItemsRepository(db)
  accounts = new AccountsRepository(db)
  transactions = new TransactionsRepository(db)
  products = new ProductsRepository(db)
  syncRuns = new SyncRunsRepository(db)
  fake = new FakePluggySyncClient()
})

afterEach(() => {
  db.close()
})

describe('PluggySyncService', () => {
  it('sincronização inicial cria item, conta e transação (sem duplicar ao rodar de novo)', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    fake.items.set('item-1', makeItem())
    fake.accounts.set('item-1', [makeAccount()])
    fake.transactions.set('account-1', [makeTransaction()])

    const service = buildService()
    const firstRun = await service.syncAll('initial')

    expect(firstRun.status).toBe('success')
    expect(firstRun.accounts_processed).toBe(1)
    expect(firstRun.transactions_created).toBe(1)
    expect(firstRun.transactions_updated).toBe(0)
    expect(transactions.list()).toHaveLength(1)
    expect(accounts.getByPluggyId('account-1')?.balance_cents).toBe(100050)

    // Second run, same upstream data: unchanged (idempotent upsert, no duplicate).
    const secondRun = await service.syncAll('manual')
    expect(secondRun.transactions_created).toBe(0)
    expect(secondRun.transactions_updated).toBe(0)
    const secondMeta = JSON.parse(secondRun.metadata ?? '{}')
    expect(secondMeta.transactionsUnchanged).toBe(1)
    expect(transactions.list()).toHaveLength(1)
  })

  it('usa a data da última transação conhecida (menos a janela de segurança) na segunda sincronização', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    fake.items.set('item-1', makeItem())
    fake.accounts.set('item-1', [makeAccount()])
    fake.transactions.set('account-1', [makeTransaction()])

    const service = buildService({ safetyWindowHours: 24 })
    await service.syncAll('initial')
    expect(fake.fetchAllTransactionsCalls[0].dateFrom).toBeUndefined() // primeira vez: sem cursor, puxa tudo

    await service.syncAll('manual')
    // segunda vez: dateFrom = última data conhecida (2026-08-01) - 24h = 2026-07-31
    expect(fake.fetchAllTransactionsCalls[1].dateFrom).toBe('2026-07-31')
  })

  it('isola falha de um Item (ex: LOGIN_ERROR) sem derrubar os demais — status PARTIAL', async () => {
    items.upsertItem({ pluggyItemId: 'item-ok', status: 'CREATED' })
    items.upsertItem({ pluggyItemId: 'item-broken', status: 'CREATED' })

    fake.items.set('item-ok', makeItem({ id: 'item-ok' }))
    fake.accounts.set('item-ok', [makeAccount({ id: 'account-ok', itemId: 'item-ok' })])
    fake.transactions.set('account-ok', [makeTransaction({ id: 'tx-ok', accountId: 'account-ok' })])
    fake.failingItemIds.add('item-broken')

    const service = buildService()
    const run = await service.syncAll('manual')

    expect(run.status).toBe('partial')
    expect(run.error_count).toBe(1)
    expect(run.transactions_created).toBe(1)
    expect(JSON.parse(run.error_summary ?? '[]')).toEqual([{ itemId: 'item-broken', message: expect.stringContaining('falha simulada') }])

    expect(items.getByPluggyId('item-ok')?.error_summary).toBeNull()
    expect(items.getByPluggyId('item-broken')?.error_summary).toContain('falha simulada')
  })

  it('marca status FAILED quando todos os Items falham', async () => {
    items.upsertItem({ pluggyItemId: 'item-broken', status: 'CREATED' })
    fake.failingItemIds.add('item-broken')

    const run = await buildService().syncAll('manual')
    expect(run.status).toBe('failed')
    expect(run.error_count).toBe(1)
  })

  it('bloqueia uma segunda sincronização concorrente (lock) e libera após a primeira terminar', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    fake.items.set('item-1', makeItem())
    fake.accounts.set('item-1', [makeAccount()])
    fake.transactions.set('account-1', [makeTransaction()])

    const service = buildService()
    const first = service.syncAll('manual')
    await expect(service.syncAll('cron')).rejects.toThrow(SyncAlreadyRunningError)
    await expect(first).resolves.toMatchObject({ status: 'success' })

    // Lock released: a third call now succeeds instead of throwing.
    await expect(service.syncAll('manual')).resolves.toMatchObject({ status: 'success' })
  })
})
