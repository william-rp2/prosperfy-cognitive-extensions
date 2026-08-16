import { mkdtemp, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AppConfig } from './config.js'
import { PluggyPort } from './pluggy.js'
import { createApp, CreateAppOptions } from './server.js'
import { JsonPocStore } from './store.js'

let dir: string
let config: AppConfig
let store: JsonPocStore
let openApps: ReturnType<typeof createApp>[]

/**
 * Every test now opens a real (in-memory) better-sqlite3 handle via createApp. Leaving
 * those unclosed crashes the Windows vitest worker on teardown (native Statement
 * destructor racing V8 isolate cleanup), so route every createApp() call through here
 * and close them all in afterEach.
 */
function buildApp(options: CreateAppOptions) {
  const app = createApp(options)
  openApps.push(app)
  return app
}

/**
 * Webhook processing is fire-and-forget (`void processWebhookEvent(...)`) so tests must
 * wait for it. A fixed sleep is flaky under load (extra SQLite init per test made a
 * previously-marginal 10ms budget start missing real disk I/O) — poll instead.
 *
 * JsonPocStore.write() isn't atomic (plain writeFile, no temp+rename — a Windows
 * rename-over-open-file can EPERM under concurrent access, so it's deliberately left
 * as-is), so a poll can catch the file mid-write and JSON.parse throws. That's
 * expected here — swallow it and keep polling instead of treating it as fatal.
 */
async function waitFor(predicate: () => Promise<boolean>, timeoutMs = 2000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      if (await predicate()) return
    } catch {
      // mid-write read of the JSON store — retry
    }
    if (Date.now() >= deadline) throw new Error(`waitFor: condição não satisfeita em ${timeoutMs}ms`)
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

const fakePluggy: PluggyPort = {
  async createConnectToken() {
    return { accessToken: 'pluggy-connect-token-test' }
  },
  async fetchSnapshot(itemId) {
    return {
      item: { id: itemId, status: 'UPDATED' },
      accounts: [{ id: 'account-1', balance: 1000, type: 'BANK' }],
      accountSnapshots: [
        {
          account: { id: 'account-1', balance: 1000 },
          transactions: { ok: true, data: [{ id: 'transaction-1', amount: 20 }] },
          bills: { ok: false, error: 'not a credit card' },
        },
      ],
      fetchedAt: '2026-08-02T00:00:00.000Z',
      filters: { dateFrom: '2026-08-01' },
    }
  },
}

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'pluggy-poc-test-'))
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
    FINANCE_API_TOKEN: undefined,
    PLUGGY_SYNC_ENABLED: false,
    PLUGGY_SYNC_INTERVAL_HOURS: 6,
    PLUGGY_SYNC_SAFETY_WINDOW_HOURS: 24,
    PLUGGY_SYNC_MAX_CONCURRENT_ITEMS: 3,
    PLUGGY_SYNC_STALE_LOCK_MINUTES: 30,
  }
  store = new JsonPocStore(config.PLUGGY_STORE_PATH)
  openApps = []
})

afterEach(async () => {
  await Promise.all(openApps.map(app => app.close()))
  await rm(dir, { recursive: true, force: true })
})

describe('Pluggy POC API', () => {
  it('gera connect token sem aceitar clientUserId arbitrário do frontend', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const response = await app.inject({
      method: 'POST',
      url: '/api/connect-token',
      payload: { clientUserId: 'attacker-user' },
    })

    expect(response.statusCode).toBe(200)
    expect(response.json()).toEqual({ accessToken: 'pluggy-connect-token-test' })
  })

  it('persiste associação de item de forma idempotente por itemId', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    for (let i = 0; i < 2; i += 1) {
      const response = await app.inject({ method: 'POST', url: '/api/pluggy/items', payload: { itemId: 'item-1' } })
      expect(response.statusCode).toBe(200)
    }

    const state = await store.read()
    expect(Object.keys(state.items)).toEqual(['item-1'])
    expect(state.items['item-1'].clientUserId).toBe('poc-william')
  })

  it('recupera snapshot de contas, saldo e movimentações com filtro por período', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    await store.upsertItem('item-1', 'poc-william')

    const response = await app.inject({ method: 'GET', url: '/api/pluggy/snapshot?itemId=item-1&dateFrom=2026-08-01' })

    expect(response.statusCode).toBe(200)
    expect(response.json().snapshot.accounts[0].balance).toBe(1000)
    expect(response.json().snapshot.accountSnapshots[0].transactions.data[0].id).toBe('transaction-1')
  })

  it('registra webhook válido, processa item/updated e preserva auditoria', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    await store.upsertItem('item-1', 'poc-william')

    const response = await app.inject({
      method: 'POST',
      url: '/api/webhooks/pluggy',
      headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' },
      payload: { eventId: 'event-1', event: 'item/updated', itemId: 'item-1', data: { status: 'PARTIAL_SUCCESS' } },
    })

    expect(response.statusCode).toBe(202)
    await waitFor(async () => (await store.read()).webhookEvents['event-1']?.status === 'processed')
    const state = await store.read()
    expect(state.webhookEvents['event-1'].status).toBe('processed')
    expect(state.items['item-1'].status).toBe('PARTIAL_SUCCESS')
  })

  it('deduplica reenvio do mesmo eventId', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const payload = { eventId: 'event-dup', event: 'item/created', itemId: 'item-1' }

    await app.inject({ method: 'POST', url: '/api/webhooks/pluggy', headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' }, payload })
    const response = await app.inject({ method: 'POST', url: '/api/webhooks/pluggy', headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' }, payload })

    expect(response.statusCode).toBe(202)
    expect(response.json().duplicate).toBe(true)
    await waitFor(async () => (await store.read()).webhookEvents['event-dup']?.status === 'processed')
    expect(Object.keys((await store.read()).webhookEvents)).toEqual(['event-dup'])
  })

  it('rejeita webhook com segredo inválido', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const response = await app.inject({
      method: 'POST',
      url: '/api/webhooks/pluggy',
      headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'wrong' },
      payload: { eventId: 'event-invalid-secret', event: 'item/created' },
    })

    expect(response.statusCode).toBe(401)
  })

  it('responde 2xx para validação GET/HEAD/OPTIONS do cadastro de webhook', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })

    const getResponse = await app.inject({ method: 'GET', url: '/api/webhooks/pluggy' })
    const headResponse = await app.inject({ method: 'HEAD', url: '/api/webhooks/pluggy' })
    const optionsResponse = await app.inject({ method: 'OPTIONS', url: '/api/webhooks/pluggy' })

    expect(getResponse.statusCode).toBe(200)
    expect(getResponse.json()).toMatchObject({ ok: true, endpoint: 'pluggy-webhook' })
    expect(headResponse.statusCode).toBeGreaterThanOrEqual(200)
    expect(headResponse.statusCode).toBeLessThan(300)
    expect(optionsResponse.statusCode).toBeGreaterThanOrEqual(200)
    expect(optionsResponse.statusCode).toBeLessThan(300)
  })

  it('aceita webhook sem header apenas quando modo temporário unsigned está habilitado', async () => {
    config.PLUGGY_ALLOW_UNSIGNED_WEBHOOKS = true
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const response = await app.inject({
      method: 'POST',
      url: '/api/webhooks/pluggy',
      headers: { 'content-type': 'application/json' },
      payload: { eventId: 'event-unsigned-poc', event: 'item/created', itemId: 'item-unsigned' },
    })

    expect(response.statusCode).toBe(202)
    await waitFor(async () => (await store.read()).webhookEvents['event-unsigned-poc']?.status === 'processed')
    const state = await store.read()
    expect(state.webhookEvents['event-unsigned-poc'].rawPayload).toMatchObject({ signature: 'unsigned-poc' })
  })

  it('rejeita webhook com payload inválido', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const response = await app.inject({
      method: 'POST',
      url: '/api/webhooks/pluggy',
      headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' },
      payload: { event: 'item/created' },
    })

    expect(response.statusCode).toBe(400)
  })

  it('registra item/error e waiting_user_action como estados tratáveis', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    await store.upsertItem('item-1', 'poc-william')

    await app.inject({ method: 'POST', url: '/api/webhooks/pluggy', headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' }, payload: { eventId: 'event-error', event: 'item/error', itemId: 'item-1', data: { code: 'SAFE_ERROR' } } })
    // Each webhook's processing is its own fire-and-forget chain — two in flight at once
    // race on the shared item's status update in whatever order their internal steps
    // happen to interleave. Wait for event-error to fully finish before firing
    // event-action so the final item status is deterministic (matches real-world
    // webhooks too: they essentially never land in the same millisecond).
    await waitFor(async () => (await store.read()).webhookEvents['event-error']?.status === 'processed')
    await app.inject({ method: 'POST', url: '/api/webhooks/pluggy', headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' }, payload: { eventId: 'event-action', event: 'item/waiting_user_action', itemId: 'item-1' } })
    await waitFor(async () => (await store.read()).webhookEvents['event-action']?.status === 'processed')

    const state = await store.read()
    expect(state.webhookEvents['event-error'].status).toBe('processed')
    expect(state.items['item-1'].status).toBe('waiting_user_action')
  })

  it('usa tombstone para transactions/deleted', async () => {
    const app = buildApp({ config, store, pluggy: fakePluggy })
    const response = await app.inject({
      method: 'POST',
      url: '/api/webhooks/pluggy',
      headers: { 'content-type': 'application/json', 'x-pluggy-webhook-secret': 'test-secret' },
      payload: { eventId: 'event-delete', event: 'transactions/deleted', transactionIds: ['tx-1'] },
    })

    expect(response.statusCode).toBe(202)
    await waitFor(async () => (await store.read()).webhookEvents['event-delete']?.status === 'processed')
    expect((await store.read()).transactionTombstones['tx-1']).toMatchObject({ transactionId: 'tx-1', eventId: 'event-delete' })
  })
})
