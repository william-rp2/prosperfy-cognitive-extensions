import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import type { PluggySyncClient } from '../pluggy.js'
import { createApp } from '../server.js'
import { AccountsRepository } from './accountsRepository.js'
import { ClarificationQueueService, MAX_DELIVERY_BATCH } from './clarificationQueueService.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { OnboardingRepository } from './onboardingRepository.js'
import { ONBOARDING_EXPORT_COLUMNS } from './spreadsheetExport.js'
import { TransactionsRepository } from './transactionsRepository.js'

/**
 * F2B E2E acceptance matrix (docs/finance-v2/f2b/08_TEST_AND_E2E_ACCEPTANCE_MATRIX.md).
 *
 * Boots the REAL app (`createApp`) against an in-memory sqlite db and drives it exclusively
 * through `app.inject()` HTTP calls wherever a route exists — a test that builds its own
 * Fastify instance proves nothing about the real wiring (F2B lesson). Only fixture setup that
 * has no HTTP surface (raw transaction/item rows, competence_month backfill) goes through the
 * repositories directly, on the SAME underlying sqlite connection the app uses.
 *
 * E2E 3 (third-party deny) and E2E 4 (explicit owner DM allow) are NOT re-implemented here:
 * that ACL lives entirely in core/cognitive/cognitive/policy/finance_acl.py (the TS API has no
 * owner/third-party concept, only a single bearer token) and is already covered end-to-end by
 * core/cognitive/tests/security/test_finance_acl.py and test_finance_acl_wiring.py.
 */

const FINANCE_API_TOKEN = 'e2e-test-token'
const AUTH = { authorization: `Bearer ${FINANCE_API_TOKEN}` }

function buildConfig(): AppConfig {
  return {
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
    PLUGGY_STORE_PATH: './data/pluggy-poc-store.json',
    PUBLIC_BASE_URL: undefined,
    FINANCE_DB_PATH: ':memory:',
    FINANCE_API_TOKEN,
    PLUGGY_SYNC_ENABLED: false,
    PLUGGY_SYNC_INTERVAL_HOURS: 6,
    PLUGGY_SYNC_SAFETY_WINDOW_HOURS: 24,
    PLUGGY_SYNC_MAX_CONCURRENT_ITEMS: 3,
    PLUGGY_SYNC_STALE_LOCK_MINUTES: 30,
  }
}

/** Minimal fake — only what PluggySyncService actually calls for these fixtures. */
function makeFakePluggySync(): PluggySyncClient & {
  itemsById: Map<string, unknown>
  accountsByItem: Map<string, unknown[]>
  transactionsByAccount: Map<string, unknown[]>
} {
  const itemsById = new Map<string, unknown>()
  const accountsByItem = new Map<string, unknown[]>()
  const transactionsByAccount = new Map<string, unknown[]>()
  return {
    itemsById,
    accountsByItem,
    transactionsByAccount,
    async fetchItem(itemId: string) {
      const item = itemsById.get(itemId)
      if (!item) throw new Error(`fake: unknown item ${itemId}`)
      return item as never
    },
    async fetchAccounts(itemId: string) {
      return (accountsByItem.get(itemId) ?? []) as never
    },
    async fetchAllTransactions(accountId: string) {
      return (transactionsByAccount.get(accountId) ?? []) as never
    },
    async fetchCreditCardBills() {
      return [] as never
    },
    async fetchInvestments() {
      return [] as never
    },
  }
}

let db: FinanceDb
let app: ReturnType<typeof createApp>
let items: ItemsRepository
let accounts: AccountsRepository
let transactions: TransactionsRepository
let clarifications: ClarificationsRepository
let onboarding: OnboardingRepository
let fakePluggySync: ReturnType<typeof makeFakePluggySync>

beforeAll(() => {
  db = openFinanceDb(':memory:')
  fakePluggySync = makeFakePluggySync()
  app = createApp({
    config: buildConfig(),
    financeDb: db,
    pluggySync: fakePluggySync,
    disableScheduler: true,
  })
  items = new ItemsRepository(db)
  accounts = new AccountsRepository(db)
  transactions = new TransactionsRepository(db)
  clarifications = new ClarificationsRepository(db)
  onboarding = new OnboardingRepository(db)
})

afterAll(async () => {
  await app.close()
})

/** Directly seeds a transaction row (bypasses Pluggy sync — no HTTP surface writes raw rows ad hoc). */
function seedTransaction(input: {
  pluggyTransactionId: string
  pluggyAccountId: string
  amountCents: number
  date: string
  currencyCode?: string | null
  accountCurrencyCode?: string | null
  categoryOriginal?: string | null
  merchantOriginal?: string | null
  description?: string | null
}) {
  transactions.upsertTransaction({
    pluggyTransactionId: input.pluggyTransactionId,
    pluggyAccountId: input.pluggyAccountId,
    description: input.description ?? null,
    amountCents: input.amountCents,
    currencyCode: input.currencyCode ?? 'BRL',
    accountCurrencyCode: input.accountCurrencyCode ?? 'BRL',
    date: input.date,
    categoryOriginal: input.categoryOriginal ?? null,
    merchantOriginal: input.merchantOriginal ?? null,
  })
}

function setCompetenceMonth(pluggyTransactionId: string, month: string) {
  db.prepare(
    `UPDATE financial_transactions SET purchase_month = substr(date,1,7), competence_month = ? WHERE pluggy_transaction_id = ?`,
  ).run(month, pluggyTransactionId)
}

// ---------------------------------------------------------------------------------------------
// E2E 1 + E2E 2 — new ambiguous transaction, then a quoted reply after a delay resolves it.
// ---------------------------------------------------------------------------------------------

describe('E2E 1 — new ambiguous transaction', () => {
  const pluggyItemId = 'e1-item'
  const accountId = 'e1-account'
  const txId = 'e1-tx-1'
  let clarificationId: string

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    fakePluggySync.itemsById.set(pluggyItemId, {
      id: pluggyItemId,
      status: 'UPDATED',
      connector: { id: 200, name: 'Banco E2E' },
    })
    fakePluggySync.accountsByItem.set(pluggyItemId, [
      { id: accountId, itemId: pluggyItemId, type: 'BANK', name: 'Conta corrente', currencyCode: 'BRL', balance: 500 },
    ])
    fakePluggySync.transactionsByAccount.set(accountId, [
      {
        id: txId,
        accountId,
        date: new Date('2026-08-05T12:00:00.000Z'),
        description: 'Loja Desconhecida XPTO',
        amount: -73.4,
        currencyCode: 'BRL',
        type: 'DEBIT',
        // No category from Pluggy and no categories seeded in this DB -> deterministic
        // normalization cannot classify it -> classificationService must ask.
        category: null,
      },
    ])
  })

  it('sync creates exactly one clarification and one repeated sync never duplicates it', async () => {
    const first = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
    expect(first.statusCode).toBe(200)
    expect(first.json().status).not.toBe('failed')

    const afterFirst = await app.inject({
      method: 'GET',
      url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}&status=open`,
      headers: AUTH,
    })
    expect(afterFirst.statusCode).toBe(200)
    const bodyFirst = afterFirst.json()
    expect(bodyFirst.total).toBe(1)
    expect(bodyFirst.clarifications).toHaveLength(1)
    expect(bodyFirst.clarifications[0].transactionId).toBe(txId)
    expect(bodyFirst.clarifications[0].status).toBe('open')
    clarificationId = bodyFirst.clarifications[0].id

    // Repeated sync, same upstream data (idempotent — transaction delta is 'unchanged').
    const second = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
    expect(second.statusCode).toBe(200)

    const afterSecond = await app.inject({
      method: 'GET',
      url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}&status=open`,
      headers: AUTH,
    })
    const bodySecond = afterSecond.json()
    expect(bodySecond.total).toBe(1)
    expect(bodySecond.clarifications[0].id).toBe(clarificationId)
  })

  describe('E2E 2 — quoted reply after delay resolves the exact clarification', () => {
    it('delivery id persists, a late quoted reply resolves it exactly once, and it survives another sync', async () => {
      // question sent -> persist delivery message id
      const delivery = await app.inject({
        method: 'POST',
        url: `/api/finance/clarifications/${clarificationId}/delivery`,
        headers: AUTH,
        payload: { deliveryMessageId: 'wamid-outbound-1', deliveryChatId: 'chat-financas' },
      })
      expect(delivery.statusCode).toBe(200)
      expect(delivery.json().clarification.deliveryMessageId).toBe('wamid-outbound-1')

      // simulate late quoted owner reply (delay is not modeled in wall-clock, only in call order)
      const resolve = await app.inject({
        method: 'POST',
        url: `/api/finance/clarifications/${clarificationId}/resolve`,
        headers: AUTH,
        payload: { replyMessageId: 'wamid-reply-1', actorId: 'owner-1', resolution: 'Mercado' },
      })
      expect(resolve.statusCode).toBe(200)
      expect(resolve.json().alreadyResolved).toBe(false)
      expect(resolve.json().clarification.status).toBe('resolved')
      const resolvedAt = resolve.json().clarification.resolvedAt as string
      expect(resolvedAt).toBeTruthy()

      // correction/category saved as part of resolving the ambiguity
      const correction = await app.inject({
        method: 'POST',
        url: '/api/finance/corrections',
        headers: AUTH,
        payload: { transactionId: txId, field: 'category', value: 'Mercado', source: 'USER', actorId: 'owner-1' },
      })
      expect(correction.statusCode).toBe(201)
      expect(correction.json().effective.effective.category.value).toBe('Mercado')

      // late duplicate reply on the same clarification id: resolved once, never mutated twice
      const resolveAgain = await app.inject({
        method: 'POST',
        url: `/api/finance/clarifications/${clarificationId}/resolve`,
        headers: AUTH,
        payload: { replyMessageId: 'wamid-reply-2-duplicate', actorId: 'owner-1', resolution: 'Mercado (dup)' },
      })
      expect(resolveAgain.statusCode).toBe(200)
      expect(resolveAgain.json().alreadyResolved).toBe(true)
      expect(resolveAgain.json().clarification.resolvedAt).toBe(resolvedAt)

      // next sync -> remains resolved (unchanged transaction is not re-classified)
      const thirdSync = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
      expect(thirdSync.statusCode).toBe(200)

      const finalState = await app.inject({
        method: 'GET',
        url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}`,
        headers: AUTH,
      })
      const finalClarification = finalState.json().clarifications.find((c: { id: string }) => c.id === clarificationId)
      expect(finalClarification.status).toBe('resolved')
    })
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 5 — historical backlog suppression: no mass proactive flood, dynamic count, period filter.
// ---------------------------------------------------------------------------------------------

describe('E2E 5 — historical backlog suppression', () => {
  const pluggyItemId = 'e5-item'
  const accountId = 'e5-account'
  const BACKLOG_SIZE = 25 // > MAX_DELIVERY_BATCH, on purpose — proves the cap actually bites.
  const augustTxIds: string[] = []
  const januaryTxIds: string[] = []

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    accounts.upsertAccount({ pluggyAccountId: accountId, pluggyItemId, type: 'BANK', currencyCode: 'BRL' })
    onboarding.getOrCreate(pluggyItemId) // still HISTORICAL_IMPORT by default

    for (let i = 0; i < BACKLOG_SIZE; i += 1) {
      const txId = `e5-tx-${i}`
      const isAugust = i % 3 === 0
      const date = isAugust ? '2026-08-10' : '2026-01-10'
      seedTransaction({ pluggyTransactionId: txId, pluggyAccountId: accountId, amountCents: -1000 - i, date })
      setCompetenceMonth(txId, isAugust ? '2026-08' : '2026-01')
      clarifications.getOrCreateOpen({ pluggyTransactionId: txId, questionType: 'category', questionText: `tx ${i}?` })
      if (isAugust) augustTxIds.push(txId)
      else januaryTxIds.push(txId)
    }
  })

  it('zero proactive delivery while onboarding is HISTORICAL_IMPORT, even across a restart', () => {
    const queueService = new ClarificationQueueService(clarifications, onboarding)
    expect(queueService.selectForOngoingDelivery({ pluggyItemId })).toEqual([])

    // "restart": brand new service instance over the same persisted state, same guarantee.
    const afterRestart = new ClarificationQueueService(clarifications, onboarding)
    expect(afterRestart.selectForOngoingDelivery({ pluggyItemId })).toEqual([])
  })

  it('an explicit historical pull is still capped at MAX_DELIVERY_BATCH no matter the backlog size', () => {
    const queueService = new ClarificationQueueService(clarifications, onboarding)
    const pulled = queueService.selectHistoricalOnDemand(pluggyItemId, { limit: 1000 })
    expect(BACKLOG_SIZE).toBeGreaterThan(MAX_DELIVERY_BATCH)
    expect(pulled.length).toBe(MAX_DELIVERY_BATCH)
  })

  it('owner asks the count -> real-time dynamic count, not a cached/hardcoded number', async () => {
    const response = await app.inject({
      method: 'GET',
      url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}&status=open`,
      headers: AUTH,
    })
    expect(response.json().total).toBe(BACKLOG_SIZE)
  })

  it('owner asks for August -> correct period filter, no January rows leak in', async () => {
    const response = await app.inject({
      method: 'GET',
      url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}&competenceMonth=2026-08&status=open`,
      headers: AUTH,
    })
    const body = response.json()
    expect(body.total).toBe(augustTxIds.length)
    const returnedTxIds = new Set(body.clarifications.map((c: { transactionId: string }) => c.transactionId))
    for (const id of augustTxIds) expect(returnedTxIds.has(id)).toBe(true)
    for (const id of januaryTxIds) expect(returnedTxIds.has(id)).toBe(false)
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 6 — spreadsheet export/import round trip.
// ---------------------------------------------------------------------------------------------

describe('E2E 6 — spreadsheet export/import', () => {
  const pluggyItemId = 'e6-item'
  const accountId = 'e6-account'
  const txIds = ['e6-tx-1', 'e6-tx-2', 'e6-tx-3']
  let firstExportCsv: string

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    accounts.upsertAccount({ pluggyAccountId: accountId, pluggyItemId, type: 'BANK', currencyCode: 'BRL' })
    for (const txId of txIds) {
      seedTransaction({ pluggyTransactionId: txId, pluggyAccountId: accountId, amountCents: -2500, date: '2026-08-12' })
      setCompetenceMonth(txId, '2026-08')
      clarifications.getOrCreateOpen({ pluggyTransactionId: txId, questionType: 'category', questionText: `${txId}?` })
    }
  })

  function editNotesColumn(csv: string, newValue: string): string {
    const noteIdx = ONBOARDING_EXPORT_COLUMNS.indexOf('notes')
    const [header, ...dataLines] = csv.trim().split('\r\n')
    const edited = dataLines.map(line => {
      const cells = line.split(',')
      cells[noteIdx] = newValue
      return cells.join(',')
    })
    return [header, ...edited].join('\r\n')
  }

  it('filter August -> export -> modify 3 rows -> dry-run -> apply -> 3 accepted', async () => {
    const exportRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId, competenceMonth: '2026-08' },
    })
    expect(exportRes.statusCode).toBe(201)
    const exportBody = exportRes.json()
    expect(exportBody.rowCount).toBe(txIds.length)
    firstExportCsv = exportBody.csv as string

    const editedCsv = editNotesColumn(firstExportCsv, 'Confirmado pelo dono')

    const dryRun = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: editedCsv, dryRun: true },
    })
    expect(dryRun.statusCode).toBe(200)
    expect(dryRun.json().dryRun).toBe(true)
    expect(dryRun.json().rows).toHaveLength(txIds.length)
    for (const row of dryRun.json().rows) expect(row.outcome).toBe('applied')

    const apply = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: editedCsv, dryRun: false, actorId: 'owner-1' },
    })
    expect(apply.statusCode).toBe(200)
    const applied = apply.json().rows.filter((r: { outcome: string }) => r.outcome === 'applied')
    expect(applied).toHaveLength(3)

    const effective = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${txIds[0]}/effective`,
      headers: AUTH,
    })
    expect(effective.json().effective.notes.value).toBe('Confirmado pelo dono')
  })

  it('reimport the same file -> 0 duplicate mutations', async () => {
    const editedCsv = editNotesColumn(firstExportCsv, 'Confirmado pelo dono')
    const reimport = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: editedCsv, dryRun: false, actorId: 'owner-1' },
    })
    expect(reimport.statusCode).toBe(200)
    for (const row of reimport.json().rows) expect(row.outcome).not.toBe('applied')

    // The correction ledger has exactly one active 'notes' entry per transaction, not two.
    const history = await app.inject({
      method: 'GET',
      url: `/api/finance/corrections/${txIds[0]}`,
      headers: AUTH,
    })
    const notesEntries = history.json().history.filter((c: { field: string }) => c.field === 'notes')
    expect(notesEntries).toHaveLength(1)
  })

  it('a stale row (real revision moved past the exported snapshot) is a conflict, not a silent overwrite', async () => {
    // firstExportCsv still carries the ORIGINAL updated_at, taken before the edits above landed.
    const staleEdit = editNotesColumn(firstExportCsv, 'Edição atrasada do dono')
    const dryRun = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: staleEdit, dryRun: true },
    })
    expect(dryRun.statusCode).toBe(200)
    for (const row of dryRun.json().rows) {
      expect(row.outcome).toBe('conflict')
      expect(row.reason).toBe('stale_export')
    }
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 7 — currency correction: raw untouched, effective foreign amount, account amount in BRL.
// ---------------------------------------------------------------------------------------------

describe('E2E 7 — currency correction', () => {
  const pluggyItemId = 'e7-item'
  const accountId = 'e7-account'
  const txId = 'e7-tx-1'
  const rawAmountCents = -2819 // R$ 28,19 as Pluggy originally reported it, in BRL.

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    accounts.upsertAccount({ pluggyAccountId: accountId, pluggyItemId, type: 'BANK', currencyCode: 'BRL' })
    seedTransaction({
      pluggyTransactionId: txId,
      pluggyAccountId: accountId,
      amountCents: rawAmountCents,
      currencyCode: 'BRL',
      accountCurrencyCode: 'BRL',
      date: '2026-08-14',
      merchantOriginal: 'Compra internacional',
    })
  })

  it('owner correction: real charge was USD 5, account statement shows the R$28.19 conversion', async () => {
    const post = (field: string, value: unknown) =>
      app.inject({
        method: 'POST',
        url: '/api/finance/corrections',
        headers: AUTH,
        payload: { transactionId: txId, field, value, source: 'USER', actorId: 'owner-1', reason: 'Essa compra foi US$ 5; os R$ 28,19 são o valor da conta.' },
      })

    expect((await post('currency', 'USD')).statusCode).toBe(201)
    expect((await post('amount', 500)).statusCode).toBe(201)
    expect((await post('amount_in_account_currency', 2819)).statusCode).toBe(201)

    const effectiveRes = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${txId}/effective`,
      headers: AUTH,
    })
    const body = effectiveRes.json()

    // Raw provider payload is never rewritten.
    expect(body.raw.amountCents).toBe(rawAmountCents)
    expect(body.raw.currencyCode).toBe('BRL')

    // Effective view reflects the owner's correction.
    expect(body.effective.currencyCode.value).toBe('USD')
    expect(body.effective.amountCents.value).toBe(500)
    expect(body.effective.amountInAccountCurrencyCents.value).toBe(2819)
    expect(body.effective.accountCurrencyCode).toBe('BRL')

    // Aggregate uses the account-currency amount, in BRL, with no missing-conversion flag.
    expect(body.effective.accountAmountCents).toBe(2819)
    expect(body.effective.currencyConversionMissing).toBe(false)

    // Audit trail identifies the owner correction for all three fields.
    const history = await app.inject({ method: 'GET', url: `/api/finance/corrections/${txId}`, headers: AUTH })
    const fields = history.json().history.map((c: { field: string; source: string; actorId: string }) => c.field)
    expect(fields.sort()).toEqual(['amount', 'amount_in_account_currency', 'currency'])
    for (const entry of history.json().history) {
      expect(entry.source).toBe('USER')
      expect(entry.actorId).toBe('owner-1')
    }
  })

  it('sync/reprocess of the same upstream data does not erase the correction', async () => {
    // Re-upsert identical raw fields, exactly what a repeated Pluggy sync would send.
    const result = transactions.upsertTransaction({
      pluggyTransactionId: txId,
      pluggyAccountId: accountId,
      amountCents: rawAmountCents,
      currencyCode: 'BRL',
      accountCurrencyCode: 'BRL',
      date: '2026-08-14',
      merchantOriginal: 'Compra internacional',
    })
    expect(result.delta).toBe('unchanged')

    const effectiveRes = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${txId}/effective`,
      headers: AUTH,
    })
    const body = effectiveRes.json()
    expect(body.raw.amountCents).toBe(rawAmountCents)
    expect(body.effective.currencyCode.value).toBe('USD')
    expect(body.effective.amountCents.value).toBe(500)
    expect(body.effective.accountAmountCents).toBe(2819)
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 8 — learned merchant rule: SUGGEST is visible but never auto-applied; TRUSTED only via
// explicit promotion; an explicit correction always outranks a TRUSTED rule.
// ---------------------------------------------------------------------------------------------

describe('E2E 8 — learned merchant rule', () => {
  const pluggyItemId = 'e8-item'
  const accountId = 'e8-account'
  const firstTxId = 'e8-tx-1'
  const secondTxId = 'e8-tx-2'
  let ruleId: string

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    accounts.upsertAccount({ pluggyAccountId: accountId, pluggyItemId, type: 'BANK', currencyCode: 'BRL' })
    seedTransaction({
      pluggyTransactionId: firstTxId,
      pluggyAccountId: accountId,
      amountCents: -4590,
      date: '2026-08-01',
      merchantOriginal: 'PADARIA CENTRAL',
    })
    seedTransaction({
      pluggyTransactionId: secondTxId,
      pluggyAccountId: accountId,
      amountCents: -3200,
      date: '2026-08-02',
      merchantOriginal: 'PADARIA CENTRAL FILIAL 2',
    })
  })

  it('a new SUGGEST rule is visible on a matching transaction but never auto-applied', async () => {
    const createRule = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'PADARIA', matchKind: 'anchored', ruleType: 'CATEGORY', targetValue: 'Alimentação', createdBy: 'owner-1' },
    })
    expect(createRule.statusCode).toBe(201)
    const rule = createRule.json().rule
    expect(rule.mode).toBe('SUGGEST')
    ruleId = rule.id

    const effective = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${firstTxId}/effective`,
      headers: AUTH,
    })
    const body = effective.json()
    expect(body.effective.category.value).not.toBe('Alimentação') // no unsafe auto-override
    const suggestion = body.suggestions.find((s: { ruleId: string }) => s.ruleId === ruleId)
    expect(suggestion).toBeTruthy()
    expect(suggestion.reason).toBe('suggest_mode')
    expect(suggestion.value).toBe('Alimentação')
  })

  it('creating a rule already TRUSTED is rejected — promotion is the only path', async () => {
    const attempt = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'OUTRA LOJA', ruleType: 'CATEGORY', targetValue: 'Lazer', mode: 'TRUSTED' },
    })
    expect(attempt.statusCode).toBe(400)
    expect(attempt.json().error).toBe('trusted_requires_promotion')
  })

  it('explicit owner promotion applies the rule to future matching transactions', async () => {
    const promote = await app.inject({
      method: 'POST',
      url: `/api/finance/rules/${ruleId}/promote`,
      headers: AUTH,
      payload: { actorId: 'owner-1' },
    })
    expect(promote.statusCode).toBe(200)
    expect(promote.json().rule.mode).toBe('TRUSTED')

    const effective = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${secondTxId}/effective`,
      headers: AUTH,
    })
    const body = effective.json()
    expect(body.effective.category.value).toBe('Alimentação')
  })

  it('conflict: an explicit correction always outranks the TRUSTED rule', async () => {
    const correction = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: secondTxId, field: 'category', value: 'Transporte', source: 'USER', actorId: 'owner-1' },
    })
    expect(correction.statusCode).toBe(201)

    const effective = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${secondTxId}/effective`,
      headers: AUTH,
    })
    const body = effective.json()
    expect(body.effective.category.value).toBe('Transporte')
    const outranked = body.suggestions.find((s: { ruleId: string }) => s.ruleId === ruleId)
    expect(outranked).toBeTruthy()
    expect(outranked.reason).toBe('outranked_by_correction')
    expect(outranked.value).toBe('Alimentação')
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 9 — competence correction: purchase_month stays put, competence_month moves, the August
// competence aggregate picks it up.
// ---------------------------------------------------------------------------------------------

describe('E2E 9 — competence correction', () => {
  const pluggyItemId = 'e9-item'
  const accountId = 'e9-account'
  const txId = 'e9-tx-1'
  const amountCents = -12000

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    accounts.upsertAccount({ pluggyAccountId: accountId, pluggyItemId, type: 'BANK', currencyCode: 'BRL' })
    seedTransaction({ pluggyTransactionId: txId, pluggyAccountId: accountId, amountCents, date: '2026-07-20' })
    setCompetenceMonth(txId, '2026-07') // documented default: competence = purchase month.
  })

  it('"Essa compra entra em agosto" moves competence without touching the purchase month', async () => {
    const correction = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: {
        transactionId: txId,
        field: 'competence_month',
        value: '2026-08',
        source: 'USER',
        actorId: 'owner-1',
        reason: 'Essa compra entra em agosto.',
      },
    })
    expect(correction.statusCode).toBe(201)

    const effective = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions/${txId}/effective`,
      headers: AUTH,
    })
    const body = effective.json()
    expect(body.temporal.purchaseMonth).toBe('2026-07') // purchase_month=July unchanged
    expect(body.temporal.competenceMonth.value).toBe('2026-08')
    expect(body.temporal.competenceMonth.source).toBe('CORRECTION')
    expect(body.raw.date.startsWith('2026-07')).toBe(true)
  })

  it('the August competence aggregate (real persisted column, projected by the correction) includes it', () => {
    // financeCorrectionRoutes projects TEMPORAL_FIELDS corrections onto the real column via
    // CycleAssignmentService.syncTemporal — verified directly against persisted state, since
    // there is no dedicated "aggregate by competence" HTTP endpoint yet.
    const row = db
      .prepare('SELECT competence_month, amount_cents FROM financial_transactions WHERE pluggy_transaction_id = ?')
      .get(txId) as { competence_month: string; amount_cents: number }
    expect(row.competence_month).toBe('2026-08')

    // Scoped to this describe's own account: the shared in-memory db also holds fixtures from
    // other E2E scenarios (some of which land in competence_month='2026-08' too), so an
    // unscoped SUM would assert against cross-test pollution rather than this correction.
    const augustSum = db
      .prepare(
        'SELECT COALESCE(SUM(amount_cents), 0) as total FROM financial_transactions WHERE competence_month = ? AND pluggy_account_id = ?',
      )
      .get('2026-08', accountId) as { total: number }
    expect(augustSum.total).toBe(amountCents)

    const julySum = db
      .prepare(
        'SELECT COALESCE(SUM(amount_cents), 0) as total FROM financial_transactions WHERE competence_month = ? AND pluggy_account_id = ?',
      )
      .get('2026-07', accountId) as { total: number }
    expect(julySum.total).toBe(0)
  })
})

// ---------------------------------------------------------------------------------------------
// Composition-root regression: a REAL sync must derive the temporal facts.
// ---------------------------------------------------------------------------------------------

/**
 * `PluggySyncService` takes `cycleAssignment` as an OPTIONAL dependency and silently skips the
 * whole temporal pass when it is missing. The composition root did not pass it, so every real
 * sync left purchase_month / competence_month / statement_cycle_id null while every unit test
 * that wired the service by hand still passed. Only a sync driven through the real app catches
 * that, which is why this goes through POST /api/finance/sync instead of seeding rows.
 */
describe('composition root — a real sync derives the temporal columns', () => {
  const pluggyItemId = 'wiring-item'
  const accountId = 'wiring-account'
  const txId = 'wiring-tx-1'
  const txDate = '2026-05-14'

  beforeAll(() => {
    fakePluggySync.itemsById.set(pluggyItemId, {
      id: pluggyItemId,
      status: 'UPDATED',
      executionStatus: 'SUCCESS',
      connector: { id: 201, name: 'Fake Bank' },
    })
    fakePluggySync.accountsByItem.set(pluggyItemId, [
      { id: accountId, type: 'BANK', name: 'Conta Corrente', currencyCode: 'BRL', balance: 100 },
    ])
    fakePluggySync.transactionsByAccount.set(accountId, [
      { id: txId, description: 'PADARIA', amount: -12.5, currencyCode: 'BRL', date: `${txDate}T12:00:00.000Z` },
    ])
    items.upsertItem({ pluggyItemId, status: 'UPDATED' })
  })

  it('populates purchase_month from the real POST /api/finance/sync path', async () => {
    const response = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
    expect(response.statusCode).toBe(200)

    const row = db
      .prepare('SELECT purchase_month, date FROM financial_transactions WHERE pluggy_transaction_id = ?')
      .get(txId) as { purchase_month: string | null; date: string } | undefined

    // The transaction was ingested at all...
    expect(row).toBeDefined()
    // ...and the temporal pass ran: derived from the row's own date, not from a literal.
    expect(row?.purchase_month).toBe(row?.date.slice(0, 7))
    expect(row?.purchase_month).not.toBeNull()
  })
})
