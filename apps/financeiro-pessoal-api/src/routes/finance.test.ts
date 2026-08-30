import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import type { Item } from 'pluggy-sdk'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { ItemsRepository } from '../finance/itemsRepository.js'
import { openFinanceDb } from '../finance/db.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'
import { TransactionAnnotationsRepository } from '../finance/transactionAnnotationsRepository.js'
import { createApp, type CreateAppOptions } from '../server.js'
import type { PluggySyncClient } from '../pluggy.js'

let config: AppConfig
let openApps: ReturnType<typeof createApp>[]
let dir: string

const AUTH = { authorization: 'Bearer test-finance-token' }
const TEST_ITEM_UUID = '22222222-2222-4222-8222-222222222222'

const fakePluggySync: PluggySyncClient = {
  async fetchItem(itemId: string) {
    return { id: itemId, status: 'UPDATED', connector: { id: 201, name: 'Bradesco' } } as Item
  },
  async fetchAccounts() {
    return []
  },
  async fetchAllTransactions() {
    return []
  },
  async fetchCreditCardBills() {
    return []
  },
  async fetchInvestments() {
    return []
  },
}

function buildApp(overrides: Partial<AppConfig> = {}) {
  const app = createApp({
    config: { ...config, ...overrides },
    disableScheduler: true,
    pluggySync: fakePluggySync,
  } satisfies CreateAppOptions)
  openApps.push(app)
  return app
}

beforeEach(async () => {
  openApps = []
  dir = await mkdtemp(join(tmpdir(), 'finance-routes-test-'))
  config = {
    HOST: '127.0.0.1',
    PORT: 0,
    CORS_ORIGIN: 'http://127.0.0.1:5175',
    PLUGGY_CLIENT_ID: undefined,
    PLUGGY_CLIENT_SECRET: undefined,
    PLUGGY_WEBHOOK_SECRET: 'test-secret',
    PLUGGY_WEBHOOK_HEADER: 'x-pluggy-webhook-secret',
    PLUGGY_ALLOW_UNSIGNED_WEBHOOKS: false,
    PLUGGY_CLIENT_USER_ID: 'poc-william',
    PLUGGY_ENV: 'sandbox',
    PLUGGY_STORE_PATH: join(dir, 'store.json'),
    PUBLIC_BASE_URL: undefined,
    FINANCE_DB_PATH: ':memory:',
    FINANCE_API_TOKEN: 'test-finance-token',
    PLUGGY_SYNC_ENABLED: false,
    PLUGGY_SYNC_INTERVAL_MINUTES: undefined,
    PLUGGY_SYNC_INTERVAL_HOURS: 6,
    PLUGGY_SYNC_SAFETY_WINDOW_HOURS: 24,
    PLUGGY_SYNC_MAX_CONCURRENT_ITEMS: 3,
    PLUGGY_SYNC_STALE_LOCK_MINUTES: 30,
  }
})

afterEach(async () => {
  await Promise.all(openApps.map(app => app.close()))
  await rm(dir, { recursive: true, force: true })
})

describe('routes/finance — API_AUTH', () => {
  it('rejects every /api/finance/* GET without a bearer token (fail-closed even if FINANCE_API_TOKEN is unset)', async () => {
    const app = buildApp({ FINANCE_API_TOKEN: undefined })
    const response = await app.inject({ method: 'GET', url: '/api/finance/summary' })
    expect(response.statusCode).toBe(401)
  })

  it('rejects a request with the wrong token', async () => {
    const app = buildApp()
    const response = await app.inject({ method: 'GET', url: '/api/finance/summary', headers: { authorization: 'Bearer wrong-token' } })
    expect(response.statusCode).toBe(401)
  })

  it('accepts the configured service token', async () => {
    const app = buildApp()
    const response = await app.inject({ method: 'GET', url: '/api/finance/summary', headers: AUTH })
    expect(response.statusCode).toBe(200)
  })

  it('does not leak the auth hook onto /health (unrelated route stays open)', async () => {
    const app = buildApp()
    const response = await app.inject({ method: 'GET', url: '/health' })
    expect(response.statusCode).toBe(200)
  })
})

describe('routes/finance — MANUAL_CREATE', () => {
  it('persists a manual expense and it is immediately visible in summary', async () => {
    const app = buildApp()
    const today = new Date().toISOString().slice(0, 10)

    const createResponse = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 89, direction: 'expense', description: 'Combustível', category: 'Combustível', date: today },
    })
    expect(createResponse.statusCode).toBe(201)
    const created = createResponse.json()
    expect(created.transaction.amount).toBe(89)
    expect(created.transaction.category.id).toBe('cat_combustivel')
    expect(created.message).toContain('89,00')

    const summaryResponse = await app.inject({ method: 'GET', url: '/api/finance/summary', headers: AUTH })
    expect(summaryResponse.json().monthExpense).toBeGreaterThanOrEqual(89)
  })

  it('rejects a non-positive amount', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 0, direction: 'expense', description: 'x' },
    })
    expect(response.statusCode).toBe(400)
  })
})

describe('routes/finance — READ_MONTH / READ_CATEGORY (SQL control match)', () => {
  it('summary.monthExpense matches a direct sum over both ledgers for the given month', async () => {
    const app = buildApp()

    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 50, direction: 'expense', description: 'Farmácia', date: '2026-08-20' },
    })
    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 30, direction: 'income', description: 'Reembolso', date: '2026-08-20' },
    })

    const summary = await app.inject({ method: 'GET', url: '/api/finance/summary?month=2026-08', headers: AUTH })
    const body = summary.json()
    // Control: exactly what was just inserted via the API, summed by hand.
    expect(body.monthExpense).toBe(50)
    expect(body.monthIncome).toBe(30)
  })

  it('category filter (free-text name) returns only that category, matching a hand-computed control sum', async () => {
    const app = buildApp()
    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 40, direction: 'expense', description: 'Mercado', category: 'Alimentação', date: '2026-08-05' },
    })
    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 15, direction: 'expense', description: 'Uber', category: 'Transporte', date: '2026-08-06' },
    })

    const response = await app.inject({ method: 'GET', url: '/api/finance/summary?month=2026-08&category=Alimenta%C3%A7%C3%A3o', headers: AUTH })
    const body = response.json()
    expect(body.monthExpense).toBe(40) // control: only the Alimentação entry, not the 15 from Transporte
    expect(body.category.id).toBe('cat_alimentacao')
  })

  it('unknown category name returns 404, not a silently empty/zeroed summary', async () => {
    const app = buildApp()
    const response = await app.inject({ method: 'GET', url: '/api/finance/summary?category=categoria-inexistente-xyz', headers: AUTH })
    expect(response.statusCode).toBe(404)
  })
})

describe('routes/finance — CATEGORY_OVERRIDE', () => {
  it('reclassifies a transaction by explicit id/source', async () => {
    const app = buildApp()
    // Seed a Pluggy transaction the same way sync would: create the account/item rows, then insert directly.
    const create = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 54.9, direction: 'expense', description: 'Compra no X', date: '2026-08-11' },
    })
    const manualId = create.json().transaction.id

    const patch = await app.inject({
      method: 'PATCH',
      url: '/api/finance/transactions/category',
      headers: AUTH,
      payload: { transactionId: manualId, source: 'manual', category: 'Alimentação' },
    })
    expect(patch.statusCode).toBe(200)
    expect(patch.json().updated.category.id).toBe('cat_alimentacao')
  })

  it('resolves by description+amount when no id is given, and applies when exactly one match', async () => {
    const app = buildApp()
    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 54.9, direction: 'expense', description: 'Compra no X', date: '2026-08-11' },
    })

    const patch = await app.inject({
      method: 'PATCH',
      url: '/api/finance/transactions/category',
      headers: AUTH,
      payload: { description: 'Compra no X', amount: 54.9, category: 'Alimentação' },
    })
    expect(patch.statusCode).toBe(200)
    expect(patch.json().updated.category.id).toBe('cat_alimentacao')
  })

  it('unknown category name returns 404 and applies nothing', async () => {
    const app = buildApp()
    const create = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 10, direction: 'expense', description: 'Teste', date: '2026-08-11' },
    })
    const response = await app.inject({
      method: 'PATCH',
      url: '/api/finance/transactions/category',
      headers: AUTH,
      payload: { transactionId: create.json().transaction.id, source: 'manual', category: 'categoria-que-nao-existe' },
    })
    expect(response.statusCode).toBe(404)
  })
})

describe('routes/finance — AMBIGUITY', () => {
  it('2+ matching transactions -> 409 with a short list, and changes nothing', async () => {
    const app = buildApp()
    const first = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 20, direction: 'expense', description: 'Uber viagem', date: '2026-08-11' },
    })
    const second = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 20, direction: 'expense', description: 'Uber viagem', date: '2026-08-12' },
    })

    const patch = await app.inject({
      method: 'PATCH',
      url: '/api/finance/transactions/category',
      headers: AUTH,
      payload: { description: 'Uber', amount: 20, category: 'Transporte' },
    })
    expect(patch.statusCode).toBe(409)
    expect(patch.json().matches).toHaveLength(2)

    // Neither candidate was touched.
    const firstId = first.json().transaction.id
    const secondId = second.json().transaction.id
    const list = await app.inject({ method: 'GET', url: '/api/finance/transactions', headers: AUTH })
    const rows = list.json().transactions as Array<{ id: string; category: unknown }>
    expect(rows.find(row => row.id === firstId)?.category).toBeNull()
    expect(rows.find(row => row.id === secondId)?.category).toBeNull()
  })

  it('0 matches -> 404, not a silent no-op success', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'PATCH',
      url: '/api/finance/transactions/category',
      headers: AUTH,
      payload: { description: 'transacao-que-nao-existe-xyz', category: 'Transporte' },
    })
    expect(response.statusCode).toBe(404)
  })
})

describe('routes/finance — BUDGET', () => {
  it('write then read reports limit/spent/remaining/status computed from the ledger', async () => {
    const app = buildApp()
    await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 700, direction: 'expense', description: 'Mercado do mês', category: 'Alimentação', date: '2026-08-05' },
    })

    const write = await app.inject({
      method: 'POST',
      url: '/api/finance/budgets',
      headers: AUTH,
      payload: { month: '2026-08', category: 'Alimentação', limitAmount: 800 },
    })
    expect(write.statusCode).toBe(201)
    const written = write.json().budget
    expect(written.limitAmount).toBe(800)
    expect(written.spentAmount).toBe(700)
    expect(written.remainingAmount).toBe(100)
    expect(written.status).toBe('warning') // 700/800 = 87.5%

    const read = await app.inject({ method: 'GET', url: '/api/finance/budgets?month=2026-08', headers: AUTH })
    expect(read.statusCode).toBe(200)
    const budgetsList = read.json().budgets
    expect(budgetsList.find((b: { category: { id: string } | null }) => b.category?.id === 'cat_alimentacao').status).toBe('warning')
  })

  it('rejects an invalid month format', async () => {
    const app = buildApp()
    const response = await app.inject({ method: 'POST', url: '/api/finance/budgets', headers: AUTH, payload: { month: '2026-8', limitAmount: 100 } })
    expect(response.statusCode).toBe(400)
  })
})

describe('routes/finance — DELETE_GUARD', () => {
  it('deleting a manual transaction without confirm:true is blocked', async () => {
    const app = buildApp()
    const create = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 5, direction: 'expense', description: 'Teste E2E a remover', date: '2026-08-11' },
    })
    const id = create.json().transaction.id

    const blocked = await app.inject({ method: 'DELETE', url: `/api/finance/transactions/manual/${id}`, headers: AUTH, payload: {} })
    expect(blocked.statusCode).toBe(400)

    const stillThere = await app.inject({ method: 'GET', url: '/api/finance/transactions', headers: AUTH })
    expect((stillThere.json().transactions as Array<{ id: string }>).some(row => row.id === id)).toBe(true)
  })

  it('deleting with confirm:true removes it (soft delete) from subsequent reads', async () => {
    const app = buildApp()
    const create = await app.inject({
      method: 'POST',
      url: '/api/finance/transactions/manual',
      headers: AUTH,
      payload: { amount: 5, direction: 'expense', description: 'Teste E2E a remover', date: '2026-08-11' },
    })
    const id = create.json().transaction.id

    const confirmed = await app.inject({ method: 'DELETE', url: `/api/finance/transactions/manual/${id}`, headers: AUTH, payload: { confirm: true } })
    expect(confirmed.statusCode).toBe(200)

    const gone = await app.inject({ method: 'GET', url: '/api/finance/transactions', headers: AUTH })
    expect((gone.json().transactions as Array<{ id: string }>).some(row => row.id === id)).toBe(false)
  })
})

describe('routes/finance — ADD_EXISTING_ITEM', () => {
  it('rejeita Item ID inválido', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/integrations/add-existing',
      headers: AUTH,
      payload: { itemId: 'not-a-uuid' },
    })
    expect(response.statusCode).toBe(400)
    expect(response.json().message).toBe('ID inválido.')
  })

  it('registra Item válido e dispara syncOne', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/integrations/add-existing',
      headers: AUTH,
      payload: { itemId: TEST_ITEM_UUID },
    })
    expect(response.statusCode).toBe(201)
    expect(response.json().success).toBe(true)
    expect(response.json().outcome).toBe('created')
  })

  it('retorna 409 quando Item já cadastrado', async () => {
    const app = buildApp()
    await app.inject({
      method: 'POST',
      url: '/api/finance/integrations/add-existing',
      headers: AUTH,
      payload: { itemId: TEST_ITEM_UUID },
    })
    const second = await app.inject({
      method: 'POST',
      url: '/api/finance/integrations/add-existing',
      headers: AUTH,
      payload: { itemId: TEST_ITEM_UUID },
    })
    expect(second.statusCode).toBe(409)
    expect(second.json().message).toBe('Conexão já cadastrada.')
  })
})

describe('routes/finance — ACCOUNT_PREFERENCES', () => {
  it('retorna 404 para conta inexistente', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'PATCH',
      url: '/api/finance/accounts/acc-inexistente/preferences',
      headers: AUTH,
      payload: { isFavorite: true },
    })
    expect(response.statusCode).toBe(404)
  })

  it('rejeita payload vazio', async () => {
    const app = buildApp()
    const response = await app.inject({
      method: 'PATCH',
      url: '/api/finance/accounts/acc-inexistente/preferences',
      headers: AUTH,
      payload: {},
    })
    expect(response.statusCode).toBe(404)
  })
})

describe('routes/finance — INSTITUTION_IDENTITY / ANNOTATIONS', () => {
  it('F. accounts API não expõe MeuPluggy como institutionName', async () => {
    const db = openFinanceDb(':memory:')
    const items = new ItemsRepository(db)
    const accounts = new AccountsRepository(db)
    items.upsertItem({
      pluggyItemId: 'item-c6',
      connectorId: 200,
      connectorName: 'MeuPluggy',
      status: 'UPDATED',
      executionStatus: null,
      lastSuccessfulUpdate: null,
      rawMetadata: null,
    })
    accounts.upsertAccount({
      pluggyAccountId: 'card-c6',
      pluggyItemId: 'item-c6',
      name: 'BANDEIRADO',
      marketingName: 'C6 Bank',
      type: 'CREDIT',
      subtype: 'CREDIT_CARD',
      balanceCents: -5000,
      numberMasked: '****5619',
      rawData: { creditData: { brand: 'Visa' }, bankData: { bankName: 'C6 Bank' } },
    })

    const app = createApp({
      config,
      financeDb: db,
      disableScheduler: true,
      pluggySync: fakePluggySync,
    } satisfies CreateAppOptions)
    openApps.push(app)

    const response = await app.inject({ method: 'GET', url: '/api/finance/accounts', headers: AUTH })
    expect(response.statusCode).toBe(200)
    const account = response.json().accounts[0]
    expect(account.institutionName).toBe('C6 Bank')
    expect(account.displayAlias).toBeNull()
    expect(account.last4).toBe('5619')
    expect(account.cardBrand).toBe('Visa')
    expect(String(account.institutionName)).not.toMatch(/pluggy/i)
  })

  it('K. annotation create/read/delete via API', async () => {
    const db = openFinanceDb(':memory:')
    const items = new ItemsRepository(db)
    const accounts = new AccountsRepository(db)
    const transactions = new TransactionsRepository(db)
    const annotations = new TransactionAnnotationsRepository(db)

    items.upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
    accounts.upsertAccount({
      pluggyAccountId: 'acc-1',
      pluggyItemId: 'item-1',
      type: 'BANK',
      subtype: 'CHECKING_ACCOUNT',
      name: 'Conta',
      balanceCents: 10000,
    })
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-pluggy-1',
      pluggyAccountId: 'acc-1',
      amountCents: -1000,
      type: 'DEBIT',
      description: 'Mercado',
      date: '2026-08-01T12:00:00.000Z',
      status: 'POSTED',
    })
    annotations.upsert('tx-pluggy-1', 'Compra Prosperfy')

    const app = createApp({
      config,
      financeDb: db,
      disableScheduler: true,
      pluggySync: fakePluggySync,
    } satisfies CreateAppOptions)
    openApps.push(app)

    const list = await app.inject({ method: 'GET', url: '/api/finance/transactions', headers: AUTH })
    expect(list.json().transactions[0].note).toBe('Compra Prosperfy')

    const put = await app.inject({
      method: 'PUT',
      url: '/api/finance/transactions/tx-pluggy-1/annotation',
      headers: AUTH,
      payload: { note: 'Reembolsável' },
    })
    expect(put.statusCode).toBe(200)

    const search = await app.inject({ method: 'GET', url: '/api/finance/transactions?q=Reembols', headers: AUTH })
    expect(search.json().transactions.some((row: { id: string }) => row.id === 'tx-pluggy-1')).toBe(true)

    const del = await app.inject({
      method: 'DELETE',
      url: '/api/finance/transactions/tx-pluggy-1/annotation',
      headers: AUTH,
    })
    expect(del.statusCode).toBe(200)
  })
})
