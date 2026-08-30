import type { Account, Item, Transaction } from 'pluggy-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resolveSyncIntervalMinutes, type AppConfig } from '../config.js'
import type { PluggySyncClient } from '../pluggy.js'
import { createApp } from '../server.js'
import { AccountsRepository } from './accountsRepository.js'
import { CategoriesRepository } from './categoriesRepository.js'
import { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { ClassificationService } from './classificationService.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { EnrichmentRepository } from './enrichmentRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { PluggySyncService } from './pluggySyncService.js'
import { ProductsRepository } from './productsRepository.js'
import { PluggySyncScheduler } from './scheduler.js'
import { SyncAlreadyRunningError, SyncRunsRepository } from './syncRunsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

function baseConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    HOST: '127.0.0.1',
    PORT: 0,
    CORS_ORIGIN: 'http://127.0.0.1:5175',
    PLUGGY_CLIENT_ID: undefined,
    PLUGGY_CLIENT_SECRET: undefined,
    PLUGGY_WEBHOOK_SECRET: 'secret',
    PLUGGY_WEBHOOK_HEADER: 'x-pluggy-webhook-secret',
    PLUGGY_ALLOW_UNSIGNED_WEBHOOKS: false,
    PLUGGY_CLIENT_USER_ID: 'poc-william',
    PLUGGY_ENV: 'sandbox',
    PLUGGY_STORE_PATH: ':memory:',
    PUBLIC_BASE_URL: undefined,
    FINANCE_DB_PATH: ':memory:',
    FINANCE_API_TOKEN: 'test-token',
    PLUGGY_SYNC_ENABLED: true,
    PLUGGY_SYNC_INTERVAL_MINUTES: 15,
    PLUGGY_SYNC_INTERVAL_HOURS: undefined,
    PLUGGY_SYNC_SAFETY_WINDOW_HOURS: 24,
    PLUGGY_SYNC_MAX_CONCURRENT_ITEMS: 3,
    PLUGGY_SYNC_STALE_LOCK_MINUTES: 30,
    ...overrides,
  }
}

class FakePluggy implements PluggySyncClient {
  constructor(
    private readonly itemMap: Map<string, Item>,
    private readonly accountMap: Map<string, Account[]>,
    private readonly txMap: Map<string, Transaction[]>,
    private readonly failItems = new Set<string>(),
  ) {}

  async fetchItem(itemId: string) {
    if (this.failItems.has(itemId)) throw new Error(`item ${itemId} failed`)
    const item = this.itemMap.get(itemId)
    if (!item) throw new Error('missing item')
    return item
  }

  async fetchAccounts(itemId: string) {
    return this.accountMap.get(itemId) ?? []
  }

  async fetchAllTransactions(accountId: string) {
    return this.txMap.get(accountId) ?? []
  }

  async fetchCreditCardBills() {
    return []
  }

  async fetchInvestments() {
    return []
  }
}

function makeItem(id: string): Item {
  return { id, status: 'UPDATED', connector: { id: 200, name: 'Meu Pluggy' } } as Item
}

function makeAccount(id: string, itemId: string): Account {
  return { id, itemId, type: 'BANK', balance: 100, name: 'Conta', currencyCode: 'BRL' } as Account
}

function makeTx(id: string, accountId: string, overrides: Partial<Transaction> = {}): Transaction {
  return {
    id,
    accountId,
    date: new Date('2026-08-10T12:00:00.000Z'),
    description: 'Loja X',
    amount: 50,
    type: 'DEBIT',
    currencyCode: 'BRL',
    ...overrides,
  } as Transaction
}

describe('F1 — config & scheduler', () => {
  it('resolve intervalo em minutos (default 15, MINUTES canônico, HOURS legado)', () => {
    expect(resolveSyncIntervalMinutes(baseConfig({ PLUGGY_SYNC_INTERVAL_MINUTES: 15 }))).toBe(15)
    expect(resolveSyncIntervalMinutes(baseConfig({ PLUGGY_SYNC_INTERVAL_MINUTES: undefined, PLUGGY_SYNC_INTERVAL_HOURS: 0.25 }))).toBe(15)
    expect(resolveSyncIntervalMinutes(baseConfig({ PLUGGY_SYNC_INTERVAL_MINUTES: undefined, PLUGGY_SYNC_INTERVAL_HOURS: undefined }))).toBe(15)
  })

  it('scheduler expõe intervalo de 15 minutos', () => {
    const scheduler = new PluggySyncScheduler({
      enabled: false,
      intervalMinutes: 15,
      syncService: { syncAll: vi.fn() } as unknown as PluggySyncService,
    })
    expect(scheduler.getIntervalMinutes()).toBe(15)
  })
})

describe('F1 — multi-item sync & delta', () => {
  let db: FinanceDb
  let items: ItemsRepository
  let accounts: AccountsRepository
  let transactions: TransactionsRepository
  let syncRuns: SyncRunsRepository
  let enrichment: EnrichmentRepository
  let clarifications: ClarificationsRepository
  let classification: ClassificationService

  beforeEach(() => {
    db = openFinanceDb(':memory:')
    items = new ItemsRepository(db)
    accounts = new AccountsRepository(db)
    transactions = new TransactionsRepository(db)
    syncRuns = new SyncRunsRepository(db)
    enrichment = new EnrichmentRepository(db)
    clarifications = new ClarificationsRepository(db)
    classification = new ClassificationService(enrichment, clarifications, new CategoriesRepository(db), new CategoryOverridesRepository(db), new AccountsRepository(db))
  })

  afterEach(() => db.close())

  function buildService(fake: FakePluggy) {
    return new PluggySyncService({
      pluggy: fake,
      items,
      accounts,
      transactions,
      products: new ProductsRepository(db),
      syncRuns,
      safetyWindowHours: 24,
      maxConcurrentItems: 3,
      classification,
    })
  }

  it('sincroniza 2+ items; falha de um não aborta os demais', async () => {
    items.upsertItem({ pluggyItemId: 'item-a', status: 'CREATED' })
    items.upsertItem({ pluggyItemId: 'item-b', status: 'CREATED' })

    const fake = new FakePluggy(
      new Map([
        ['item-a', makeItem('item-a')],
        ['item-b', makeItem('item-b')],
      ]),
      new Map([
        ['item-a', [makeAccount('acc-a', 'item-a')]],
        ['item-b', [makeAccount('acc-b', 'item-b')]],
      ]),
      new Map([
        ['acc-a', [makeTx('tx-a', 'acc-a')]],
        ['acc-b', [makeTx('tx-b', 'acc-b')]],
      ]),
      new Set(['item-b']),
    )

    const run = await buildService(fake).syncAll('manual')
    expect(run.status).toBe('partial')
    expect(run.transactions_created).toBe(1)
    expect(run.error_count).toBe(1)
  })

  it('dedupe: mesma transação Pluggy duas vezes gera apenas uma row', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    const fake = new FakePluggy(
      new Map([['item-1', makeItem('item-1')]]),
      new Map([['item-1', [makeAccount('acc-1', 'item-1')]]]),
      new Map([['acc-1', [makeTx('tx-dup', 'acc-1')]]]),
    )
    const service = buildService(fake)
    await service.syncAll('initial')
    await service.syncAll('manual')
    expect(transactions.list()).toHaveLength(1)
  })

  it('delta NEW / UPDATED / UNCHANGED', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    const txMap = new Map([['acc-1', [makeTx('tx-1', 'acc-1')]]])
    const fake = new FakePluggy(new Map([['item-1', makeItem('item-1')]]), new Map([['item-1', [makeAccount('acc-1', 'item-1')]]]), txMap)
    const service = buildService(fake)

    const first = await service.syncAll('initial')
    expect(first.transactions_created).toBe(1)
    const firstMeta = JSON.parse(first.metadata ?? '{}')
    expect(firstMeta.transactionsSeen).toBe(1)

    const second = await service.syncAll('manual')
    expect(second.transactions_created).toBe(0)
    expect(second.transactions_updated).toBe(0)
    const secondMeta = JSON.parse(second.metadata ?? '{}')
    expect(secondMeta.transactionsUnchanged).toBe(1)

    txMap.set('acc-1', [makeTx('tx-1', 'acc-1', { description: 'Loja X alterada' })])
    const third = await service.syncAll('manual')
    expect(third.transactions_updated).toBe(1)
  })

  it('enrichment writer preserva raw e clarification dedupe', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    const fake = new FakePluggy(
      new Map([['item-1', makeItem('item-1')]]),
      new Map([['item-1', [makeAccount('acc-1', 'item-1')]]]),
      new Map([['acc-1', [makeTx('tx-ambig', 'acc-1', { description: 'Desconhecido', category: undefined })]]]),
    )
    const service = buildService(fake)
    await service.syncAll('initial')
    await service.syncAll('manual')

    const raw = transactions.getByPluggyId('tx-ambig')
    expect(raw?.description).toBe('Desconhecido')
    expect(enrichment.getByTransactionId('tx-ambig')?.classification_status).toBe('needs_clarification')
    expect(clarifications.countOpenForTransaction('tx-ambig')).toBe(1)
  })

  it('lock evita overlap de sync', async () => {
    items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
    const fake = new FakePluggy(
      new Map([['item-1', makeItem('item-1')]]),
      new Map([['item-1', [makeAccount('acc-1', 'item-1')]]]),
      new Map([['acc-1', [makeTx('tx-1', 'acc-1')]]]),
    )
    const service = buildService(fake)
    const first = service.syncAll('manual')
    await expect(service.syncAll('cron')).rejects.toThrow(SyncAlreadyRunningError)
    await first
  })
})

describe('F1 — auth', () => {
  it('nega GET financeiro sem token e aceita com token', async () => {
    const app = createApp({ config: baseConfig(), disableScheduler: true })
    const denied = await app.inject({ method: 'GET', url: '/api/finance/summary' })
    expect(denied.statusCode).toBe(401)

    const allowed = await app.inject({
      method: 'GET',
      url: '/api/finance/summary',
      headers: { authorization: 'Bearer test-token' },
    })
    expect(allowed.statusCode).toBe(200)
    await app.close()
  })
})
