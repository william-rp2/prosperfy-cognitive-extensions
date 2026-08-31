import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import type { PluggySyncClient } from '../pluggy.js'
import { createApp } from '../server.js'
import { AccountsRepository } from './accountsRepository.js'
import { ClarificationQueueService } from './clarificationQueueService.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { OnboardingRepository } from './onboardingRepository.js'
import { StatementImportRepository } from './statementImportRepository.js'
import { parseStatement } from './statementParser.js'
import { TransactionsRepository } from './transactionsRepository.js'

/**
 * F2B E2E acceptance matrix — E2E 10 through 16 (docs/finance-v2/f2b/08_TEST_AND_E2E_ACCEPTANCE_MATRIX.md).
 *
 * Mirrors e2eAcceptance.test.ts (E2E 1-9): boots the REAL app via `createApp`, drives it through
 * `app.inject()` HTTP wherever a route exists. Direct repository access is only used for fixture
 * setup with no HTTP surface (raw transactions, item/account rows) or read-only assertions with
 * no HTTP surface at all (statement line classification, onboarding mode).
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
let statementImports: StatementImportRepository
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
  statementImports = new StatementImportRepository(db)
})

afterAll(async () => {
  await app.close()
})

function seedItemAndCreditAccount(pluggyItemId: string, accountId: string) {
  items.upsertItem({ pluggyItemId, status: 'CREATED' })
  accounts.upsertAccount({
    pluggyAccountId: accountId,
    pluggyItemId,
    type: 'CREDIT',
    subtype: 'CREDIT_CARD',
    name: 'Cartão E2E',
    currencyCode: 'BRL',
    balanceCents: 0,
  })
}

interface Fixture {
  date: string
  description: string
  amountCents: number
}

const statementTotalOf = (fixtures: readonly Fixture[]) => fixtures.reduce((sum, f) => sum + f.amountCents, 0)
const toLines = (fixtures: readonly Fixture[]) =>
  fixtures.map(f => ({ date: f.date, description: f.description, amountCents: f.amountCents }))

async function importStatement(accountId: string, competenceMonth: string, fixtures: readonly Fixture[], overrides: Record<string, unknown> = {}) {
  const res = await app.inject({
    method: 'POST',
    url: '/api/finance/statements/import',
    headers: AUTH,
    payload: {
      accountId,
      source: 'MANUAL_UPLOAD',
      competenceMonth,
      statementCurrency: 'BRL',
      lines: toLines(fixtures),
      statementTotalCents: statementTotalOf(fixtures),
      ...overrides,
    },
  })
  return res
}

async function reconcile(statementId: string) {
  return app.inject({ method: 'POST', url: `/api/finance/statements/${statementId}/reconcile`, headers: AUTH })
}

// ---------------------------------------------------------------------------------------------
// E2E 10 — two statement cycles inside one Pluggy history.
// ---------------------------------------------------------------------------------------------

describe('E2E 10 — two statement cycles in one Pluggy history', () => {
  const pluggyItemId = 'e10-item'
  const accountId = 'e10-account'

  const julyFixtures: Fixture[] = [
    { date: '2026-07-04', description: 'MERCADO JULHO', amountCents: -5000 },
    { date: '2026-07-18', description: 'FARMACIA JULHO', amountCents: -1200 },
  ]
  const augustFixtures: Fixture[] = [
    { date: '2026-08-06', description: 'MERCADO AGOSTO', amountCents: -7000 },
    { date: '2026-08-21', description: 'POSTO AGOSTO', amountCents: -1500 },
  ]

  beforeAll(async () => {
    seedItemAndCreditAccount(pluggyItemId, accountId)

    // The whole Pluggy history for this credit account arrives together — both cycles at once.
    fakePluggySync.itemsById.set(pluggyItemId, { id: pluggyItemId, status: 'UPDATED', connector: { id: 10, name: 'Banco E10' } })
    fakePluggySync.accountsByItem.set(pluggyItemId, [
      { id: accountId, itemId: pluggyItemId, type: 'CREDIT', name: 'Cartão E10', currencyCode: 'BRL', balance: 0 },
    ])
    fakePluggySync.transactionsByAccount.set(accountId, [
      ...julyFixtures.map((f, i) => ({
        id: `e10-jul-${i}`,
        accountId,
        date: new Date(`${f.date}T12:00:00.000Z`),
        description: f.description,
        amount: f.amountCents / 100,
        currencyCode: 'BRL',
        type: 'DEBIT',
      })),
      ...augustFixtures.map((f, i) => ({
        id: `e10-aug-${i}`,
        accountId,
        date: new Date(`${f.date}T12:00:00.000Z`),
        description: f.description,
        amount: f.amountCents / 100,
        currencyCode: 'BRL',
        type: 'DEBIT',
      })),
    ])
  })

  it('one sync pulls both months, then two separate statement imports split them into two cycles', async () => {
    const sync = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
    expect(sync.statusCode).toBe(200)

    const julyImport = await importStatement(accountId, '2026-07', julyFixtures)
    expect(julyImport.statusCode).toBe(201)
    const augustImport = await importStatement(accountId, '2026-08', augustFixtures)
    expect(augustImport.statusCode).toBe(201)

    const julyReport = (await reconcile(julyImport.json().statementId)).json()
    const augustReport = (await reconcile(augustImport.json().statementId)).json()

    // Not all assigned to one cycle: two distinct cycle ids, one per month.
    expect(julyReport.cycleId).not.toBe(augustReport.cycleId)
    expect(julyReport.competenceMonth).toBe('2026-07')
    expect(augustReport.competenceMonth).toBe('2026-08')

    // Imported statement evidence splits correctly: each cycle only matched its own month's txs.
    expect(julyReport.matchedCount).toBe(julyFixtures.length)
    expect(julyReport.appOnlyCount).toBe(0)
    expect(augustReport.matchedCount).toBe(augustFixtures.length)
    expect(augustReport.appOnlyCount).toBe(0)

    // Cycle aggregates correct: effective total per cycle equals that month's own fixture total.
    const cyclesRes = await app.inject({ method: 'GET', url: `/api/finance/cycles?accountId=${accountId}`, headers: AUTH })
    const cyclesByMonth = new Map(cyclesRes.json().cycles.map((c: { competenceMonth: string; effectiveTotalCents: number }) => [c.competenceMonth, c]))
    expect((cyclesByMonth.get('2026-07') as { effectiveTotalCents: number }).effectiveTotalCents).toBe(statementTotalOf(julyFixtures))
    expect((cyclesByMonth.get('2026-08') as { effectiveTotalCents: number }).effectiveTotalCents).toBe(statementTotalOf(augustFixtures))
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 11 — closed statement import: exact matches linked, unmatched listed, ambiguity not
// auto-resolved, total discrepancy reported.
// ---------------------------------------------------------------------------------------------

describe('E2E 11 — closed statement PDF', () => {
  const pluggyItemId = 'e11-item'
  const accountId = 'e11-account'

  const exactFixture: Fixture = { date: '2026-07-05', description: 'LOJA UNICA E11', amountCents: -3000 }
  // Two identical charges, same day: matching them 1:1 against two identical app transactions is
  // ambiguous by construction — the parser must not collapse them and reconcile must not guess.
  const ambiguousFixture: Fixture = { date: '2026-07-09', description: 'ASSINATURA E11', amountCents: -990 }
  const statementOnlyFixture: Fixture = { date: '2026-07-14', description: 'SO NO EXTRATO E11', amountCents: -450 }

  beforeAll(() => {
    seedItemAndCreditAccount(pluggyItemId, accountId)
    transactions.upsertTransaction({
      pluggyTransactionId: 'e11-tx-exact',
      pluggyAccountId: accountId,
      description: exactFixture.description,
      amountCents: exactFixture.amountCents,
      currencyCode: 'BRL',
      date: exactFixture.date,
    })
    transactions.upsertTransaction({
      pluggyTransactionId: 'e11-tx-amb-1',
      pluggyAccountId: accountId,
      description: ambiguousFixture.description,
      amountCents: ambiguousFixture.amountCents,
      currencyCode: 'BRL',
      date: ambiguousFixture.date,
    })
    transactions.upsertTransaction({
      pluggyTransactionId: 'e11-tx-amb-2',
      pluggyAccountId: accountId,
      description: ambiguousFixture.description,
      amountCents: ambiguousFixture.amountCents,
      currencyCode: 'BRL',
      date: ambiguousFixture.date,
    })
    // App-only extra (never appears on the statement): drives appOnlyCount + APP_ONLY discrepancy.
    transactions.upsertTransaction({
      pluggyTransactionId: 'e11-tx-app-only',
      pluggyAccountId: accountId,
      description: 'SO NO APP E11',
      amountCents: -2000,
      currencyCode: 'BRL',
      date: '2026-07-16',
    })
  })

  it('statement parsed, cycle draft created, exact linked, unmatched listed, ambiguous untouched, total discrepancy reported', async () => {
    // Statement carries exactFixture + a single ambiguousFixture line (only one of the two
    // identical app transactions has a statement counterpart) + statementOnlyFixture.
    const importRes = await importStatement(accountId, '2026-07', [exactFixture, ambiguousFixture, statementOnlyFixture])
    expect(importRes.statusCode).toBe(201)
    const imported = importRes.json()
    expect(imported.lineCount).toBe(3) // statement parsed
    expect(imported.cycleId).toBeTruthy() // cycle draft created

    const report = (await reconcile(imported.statementId)).json()

    const exactLine = report.lines.find((l: { descriptionRaw: string }) => l.descriptionRaw === exactFixture.description)
    expect(exactLine.status).toBe('EXACT')
    expect(exactLine.transactionId).toBe('e11-tx-exact') // exact matches linked

    const ambiguousLine = report.lines.find((l: { descriptionRaw: string }) => l.descriptionRaw === ambiguousFixture.description)
    expect(ambiguousLine.status).toBe('AMBIGUOUS')
    expect(ambiguousLine.transactionId).toBeNull() // ambiguous not auto-resolved

    expect(report.statementOnly.some((l: { descriptionRaw: string }) => l.descriptionRaw === statementOnlyFixture.description)).toBe(true) // unmatched listed
    expect(report.appOnly.some((r: { transactionId: string }) => r.transactionId === 'e11-tx-app-only')).toBe(true) // unmatched listed (app side)

    expect(report.differenceCents).not.toBeNull() // total discrepancy reported
    expect(report.discrepancies.some((d: { kind: string }) => d.kind === 'TOTAL_MISMATCH')).toBe(true)
    expect(report.discrepancies.some((d: { kind: string }) => d.kind === 'AMBIGUOUS')).toBe(true)
    expect(report.discrepancies.some((d: { kind: string }) => d.kind === 'STATEMENT_ONLY')).toBe(true)
    expect(report.discrepancies.some((d: { kind: string }) => d.kind === 'APP_ONLY')).toBe(true)
    expect(report.cycleStatus).toBe('DISCREPANT')
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 12 — reconciliation close, then a late transaction flags the closed cycle dirty.
// ---------------------------------------------------------------------------------------------

describe('E2E 12 — reconciliation close', () => {
  const pluggyItemId = 'e12-item'
  const accountId = 'e12-account'
  const fixtures: Fixture[] = [
    { date: '2026-07-03', description: 'A E12', amountCents: -1000 },
    { date: '2026-07-08', description: 'B E12', amountCents: -2000 },
  ]

  beforeAll(() => {
    seedItemAndCreditAccount(pluggyItemId, accountId)
    for (const [i, f] of fixtures.entries()) {
      transactions.upsertTransaction({
        pluggyTransactionId: `e12-tx-${i}`,
        pluggyAccountId: accountId,
        description: f.description,
        amountCents: f.amountCents,
        currencyCode: 'BRL',
        date: f.date,
      })
    }
  })

  it('exact statement -> RECONCILED with matching total, then a late transaction flags DISCREPANT without silently rewriting the exact matches', async () => {
    const importRes = await importStatement(accountId, '2026-07', fixtures)
    const statementId = importRes.json().statementId

    const first = (await reconcile(statementId)).json()
    expect(first.cycleStatus).toBe('RECONCILED')
    expect(first.reconciliationStatus).toBe('MATCHED')
    expect(first.statementTotalCents).toBe(first.matchedTotalCents) // statement total == effective reconciled total
    const exactStatuses = first.lines.map((l: { status: string }) => l.status)
    expect(exactStatuses.every((s: string) => s === 'EXACT')).toBe(true)

    // Late transaction lands in the app on the same account/period, after the cycle closed.
    transactions.upsertTransaction({
      pluggyTransactionId: 'e12-tx-late',
      pluggyAccountId: accountId,
      description: 'LATE E12',
      amountCents: -500,
      currencyCode: 'BRL',
      date: '2026-07-10',
    })

    const second = (await reconcile(statementId)).json()
    expect(second.cycleStatus).toBe('DISCREPANT') // cycle flagged dirty/discrepant
    expect(second.appOnlyCount).toBeGreaterThan(0)
    expect(second.appOnly.some((r: { transactionId: string }) => r.transactionId === 'e12-tx-late')).toBe(true)

    // No silent rewrite: the two original exact matches are still exactly matched, not dropped
    // or reclassified because of the newcomer.
    const stillExact = second.lines.filter((l: { status: string }) => l.status === 'EXACT')
    expect(stillExact).toHaveLength(fixtures.length)
    expect(second.matchedCount).toBe(fixtures.length)
    expect(second.matchedTotalCents).toBe(first.matchedTotalCents)
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 13 — duplicate statement import: idempotent, no duplicate cycle/lines.
// ---------------------------------------------------------------------------------------------

describe('E2E 13 — duplicate statement', () => {
  const pluggyItemId = 'e13-item'
  const accountId = 'e13-account'
  const fixtures: Fixture[] = [{ date: '2026-07-12', description: 'UNICA E13', amountCents: -800 }]

  beforeAll(() => {
    seedItemAndCreditAccount(pluggyItemId, accountId)
  })

  it('importing the exact same statement twice never duplicates the cycle or the lines', async () => {
    const first = await importStatement(accountId, '2026-07', fixtures)
    expect(first.statusCode).toBe(201)
    const firstBody = first.json()

    const second = await importStatement(accountId, '2026-07', fixtures)
    expect(second.statusCode).toBe(200) // not created again
    const secondBody = second.json()

    expect(secondBody.statementId).toBe(firstBody.statementId)
    expect(secondBody.cycleId).toBe(firstBody.cycleId)
    expect(secondBody.lineCount).toBe(firstBody.lineCount)

    const cyclesRes = await app.inject({ method: 'GET', url: `/api/finance/cycles?accountId=${accountId}&competenceMonth=2026-07`, headers: AUTH })
    expect(cyclesRes.json().cycles).toHaveLength(1) // no duplicate cycle

    // Re-reconciling twice stays idempotent: no inflated match/discrepancy counts.
    const r1 = (await reconcile(firstBody.statementId)).json()
    const r2 = (await reconcile(firstBody.statementId)).json()
    expect(r2.discrepancies.length).toBe(r1.discrepancies.length)
    expect(r2.matchedCount).toBe(r1.matchedCount)
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 14 — IOF only from explicit statement vocabulary, never inferred from proximity to an
// international purchase.
// ---------------------------------------------------------------------------------------------

describe('E2E 14 — IOF explicit', () => {
  const pluggyItemId = 'e14-item'
  const accountId = 'e14-account'

  it('a line explicitly naming IOF is classified IOF', () => {
    const parsed = parseStatement({
      lines: [{ date: '2026-07-10', description: 'IOF COMPRA INTERNACIONAL', amountCents: -350 }],
      currencyCode: 'BRL',
    })
    expect(parsed.lines[0].lineType).toBe('IOF')
  })

  it('an international purchase with no explicit IOF wording is never auto-classified IOF, even sitting right next to one', () => {
    const parsed = parseStatement({
      lines: [
        { date: '2026-07-10', description: 'COMPRA INTERNACIONAL USD LOJA X', amountCents: -10000 },
        { date: '2026-07-10', description: 'IOF COMPRA INTERNACIONAL', amountCents: -350 },
      ],
      currencyCode: 'BRL',
    })
    expect(parsed.lines[0].lineType).not.toBe('IOF')
    expect(parsed.lines[0].lineType).toBe('PURCHASE')
    expect(parsed.lines[1].lineType).toBe('IOF')
  })

  it('an explicit IOF line flows through the real import pipeline untouched', async () => {
    seedItemAndCreditAccount(pluggyItemId, accountId)
    const fixtures: Fixture[] = [
      { date: '2026-07-10', description: 'COMPRA INTERNACIONAL USD LOJA X', amountCents: -10000 },
      { date: '2026-07-10', description: 'IOF COMPRA INTERNACIONAL', amountCents: -350 },
    ]
    const importRes = await importStatement(accountId, '2026-07', fixtures)
    expect(importRes.statusCode).toBe(201)
    const { statementId, cycleId } = importRes.json()

    const lines = statementImports.listLines(statementId)
    const iofLine = lines.find(l => l.description_raw === 'IOF COMPRA INTERNACIONAL')
    const purchaseLine = lines.find(l => l.description_raw === 'COMPRA INTERNACIONAL USD LOJA X')
    expect(iofLine?.line_type).toBe('IOF')
    expect(purchaseLine?.line_type).toBe('PURCHASE')
    expect(iofLine?.statement_cycle_id).toBe(cycleId)
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 15 — new bank onboarding: historical import backlog, no proactive flood, filterable,
// explicit cutover to ongoing.
// ---------------------------------------------------------------------------------------------

describe('E2E 15 — new bank onboarding', () => {
  const pluggyItemId = 'e15-item'
  const accountId = 'e15-account'
  const BACKLOG_SIZE = 24

  beforeAll(() => {
    seedItemAndCreditAccount(pluggyItemId, accountId)
    onboarding.getOrCreate(pluggyItemId) // starts HISTORICAL_IMPORT

    for (let i = 0; i < BACKLOG_SIZE; i += 1) {
      const isJuly = i % 2 === 0
      const date = isJuly ? '2026-07-10' : '2026-06-10'
      const txId = `e15-tx-${i}`
      transactions.upsertTransaction({
        pluggyTransactionId: txId,
        pluggyAccountId: accountId,
        description: `HIST E15 ${i}`,
        amountCents: -1000 - i,
        currencyCode: 'BRL',
        date,
      })
      db.prepare(
        `UPDATE financial_transactions SET purchase_month = substr(date,1,7), competence_month = ? WHERE pluggy_transaction_id = ?`,
      ).run(isJuly ? '2026-07' : '2026-06', txId)
      clarifications.getOrCreateOpen({ pluggyTransactionId: txId, questionType: 'category', questionText: `${txId}?` })
    }
  })

  it('historical records imported and counted', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/finance/clarifications?pluggyItemId=${pluggyItemId}&status=open`,
      headers: AUTH,
    })
    expect(res.json().total).toBe(BACKLOG_SIZE) // backlog count increases
  })

  it('no WhatsApp flood while still onboarding', () => {
    const queueService = new ClarificationQueueService(clarifications, onboarding)
    expect(queueService.selectForOngoingDelivery({ pluggyItemId })).toEqual([])
  })

  it('owner can filter only that bank and only that month', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/finance/transactions?accountId=${accountId}&startDate=2026-07-01&endDate=2026-07-31`,
      headers: AUTH,
    })
    expect(res.statusCode).toBe(200)
    const rows = res.json().transactions as Array<{ id: string; date: string }>
    expect(rows.length).toBe(Math.ceil(BACKLOG_SIZE / 2))
    for (const row of rows) expect(row.date.startsWith('2026-07')).toBe(true)
  })

  it('explicit owner cutover moves the item to ONGOING and unblocks proactive delivery', () => {
    onboarding.completeOnboarding(pluggyItemId, new Date().toISOString())
    expect(onboarding.getByItem(pluggyItemId)?.mode).toBe('ONGOING')

    const queueService = new ClarificationQueueService(clarifications, onboarding)
    const delivered = queueService.selectForOngoingDelivery({ pluggyItemId })
    expect(delivered.length).toBeGreaterThan(0) // ongoing cutover works
  })
})

// ---------------------------------------------------------------------------------------------
// E2E 16 — C6 consolidated card: one upstream account, no fabricated extra cards, owner can still
// assign responsibility manually per transaction.
// ---------------------------------------------------------------------------------------------

describe('E2E 16 — C6 consolidated card', () => {
  const pluggyItemId = 'e16-item'
  const accountId = 'e16-c6-account'
  const cardLast4 = '4242'

  beforeAll(() => {
    items.upsertItem({ pluggyItemId, status: 'CREATED' })
    fakePluggySync.itemsById.set(pluggyItemId, { id: pluggyItemId, status: 'UPDATED', connector: { id: 16, name: 'C6 Bank' } })
    // C6-style consolidated card: ONE upstream account even though the statement mixes multiple
    // family-member charges under the same card metadata.
    fakePluggySync.accountsByItem.set(pluggyItemId, [
      {
        id: accountId,
        itemId: pluggyItemId,
        type: 'CREDIT',
        subtype: 'CREDIT_CARD',
        name: 'C6 Consolidado',
        currencyCode: 'BRL',
        balance: 0,
        creditData: { cardNumber: `**** **** **** ${cardLast4}` },
      },
    ])
    fakePluggySync.transactionsByAccount.set(accountId, [
      {
        id: 'e16-tx-owner',
        accountId,
        date: new Date('2026-07-05T12:00:00.000Z'),
        description: 'COMPRA TITULAR',
        amount: -100,
        currencyCode: 'BRL',
        type: 'DEBIT',
      },
      {
        id: 'e16-tx-dependent',
        accountId,
        date: new Date('2026-07-06T12:00:00.000Z'),
        description: 'COMPRA DEPENDENTE',
        amount: -50,
        currencyCode: 'BRL',
        type: 'DEBIT',
      },
    ])
  })

  it('sync produces exactly one card account for this item, no fabricated extras', async () => {
    const sync = await app.inject({ method: 'POST', url: '/api/finance/sync', headers: AUTH })
    expect(sync.statusCode).toBe(200)

    const accountsRes = await app.inject({ method: 'GET', url: '/api/finance/accounts', headers: AUTH })
    const rows = accountsRes.json().accounts as Array<{ id: string; itemId: string }>
    const forItem = rows.filter(r => r.itemId === pluggyItemId)
    expect(forItem).toHaveLength(1)
    expect(forItem[0].id).toBe(accountId)
  })

  it('owner can still assign transaction responsibility manually, per transaction', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'e16-tx-dependent', field: 'economic_owner', value: 'dependente-1', source: 'USER', actorId: 'owner-1' },
    })
    expect(res.statusCode).toBe(201)
    expect(res.json().effective.effective.economicOwner.value).toBe('dependente-1')

    // The other transaction on the same consolidated card keeps its own, independent assignment.
    const ownerRes = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'e16-tx-owner', field: 'economic_owner', value: 'titular', source: 'USER', actorId: 'owner-1' },
    })
    expect(ownerRes.statusCode).toBe(201)
    expect(ownerRes.json().effective.effective.economicOwner.value).toBe('titular')
  })
})
