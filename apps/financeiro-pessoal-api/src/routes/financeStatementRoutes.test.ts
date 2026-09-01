import Fastify, { type FastifyInstance } from 'fastify'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { openFinanceDb, type FinanceDb } from '../finance/db.js'
import { EnrichmentRepository } from '../finance/enrichmentRepository.js'
import { ItemsRepository } from '../finance/itemsRepository.js'
import { ReconciliationService } from '../finance/reconciliationService.js'
import { StatementCyclesRepository } from '../finance/statementCyclesRepository.js'
import { StatementImportRepository } from '../finance/statementImportRepository.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'
import { registerFinanceStatementRoutes } from './financeStatementRoutes.js'

/**
 * Route-level tests on the real runtime path: real SQLite, real migrations, real repositories,
 * a real Fastify instance driven through `app.inject()`.
 */

const AUTH = { authorization: 'Bearer test-finance-token' }
const CARD_ACCOUNT = 'acc-card-routes'

const STATEMENT_FIXTURES = [
  { date: '2026-07-04', description: 'PADARIA CENTRAL', amountCents: -1550 },
  { date: '2026-07-11', description: 'POSTO IPIRANGA', amountCents: -21090 },
]

const totalOf = (rows: readonly { amountCents: number }[]) => rows.reduce((sum, row) => sum + row.amountCents, 0)

let db: FinanceDb
let app: FastifyInstance
let statementImports: StatementImportRepository

function buildApp(config: Partial<AppConfig>): FastifyInstance {
  const accounts = new AccountsRepository(db)
  const cycles = new StatementCyclesRepository(db)
  statementImports = new StatementImportRepository(db)
  const reconciliation = new ReconciliationService({ statementImports, cycles, accounts })

  const instance = Fastify({ logger: false })
  registerFinanceStatementRoutes(instance, {
    config: config as AppConfig,
    statementImports,
    cycles,
    reconciliation,
  })
  return instance
}

const importBody = (overrides: Record<string, unknown> = {}) => ({
  accountId: CARD_ACCOUNT,
  source: 'MANUAL_UPLOAD',
  competenceMonth: '2026-07',
  statementCurrency: 'BRL',
  lines: STATEMENT_FIXTURES,
  statementTotalCents: totalOf(STATEMENT_FIXTURES),
  ...overrides,
})

beforeEach(async () => {
  db = openFinanceDb(':memory:')
  const accounts = new AccountsRepository(db)
  const transactions = new TransactionsRepository(db)

  new ItemsRepository(db).upsertItem({ pluggyItemId: 'item-routes', status: 'UPDATED' })
  accounts.upsertAccount({
    pluggyAccountId: CARD_ACCOUNT,
    pluggyItemId: 'item-routes',
    type: 'CREDIT',
    subtype: 'CREDIT_CARD',
    name: 'Cartão',
    currencyCode: 'BRL',
    balanceCents: 0,
  })
  STATEMENT_FIXTURES.forEach((fixture, index) => {
    const id = `rtx-${index}`
    transactions.upsertTransaction({
      pluggyTransactionId: id,
      pluggyAccountId: CARD_ACCOUNT,
      description: fixture.description,
      descriptionRaw: fixture.description,
      amountCents: fixture.amountCents,
      currencyCode: 'BRL',
      date: fixture.date,
      rawData: { provider: 'pluggy' },
    })
    new EnrichmentRepository(db).upsert({
      pluggyTransactionId: id,
      direction: 'OUT',
      canonicalType: 'CREDIT_PURCHASE',
      paymentMethod: 'CREDIT_CARD',
      classificationStatus: 'classified',
      classificationSource: 'deterministic_rule',
    })
  })

  app = buildApp({ FINANCE_API_TOKEN: 'test-finance-token' })
  await app.ready()
})

afterEach(async () => {
  await app.close()
  db.close()
})

describe('auth (fail-closed)', () => {
  const routes = [
    { method: 'POST' as const, url: '/api/finance/statements/import' },
    { method: 'POST' as const, url: '/api/finance/statements/any/reconcile' },
    { method: 'GET' as const, url: '/api/finance/cycles' },
  ]

  it('denies every route without an Authorization header', async () => {
    for (const route of routes) {
      const response = await app.inject({ method: route.method, url: route.url, payload: {} })
      expect(response.statusCode).toBe(401)
      expect(response.json().error).toBe('unauthorized')
    }
  })

  it('denies every route with a wrong token', async () => {
    for (const route of routes) {
      const response = await app.inject({
        method: route.method,
        url: route.url,
        headers: { authorization: 'Bearer wrong-token' },
        payload: {},
      })
      expect(response.statusCode).toBe(401)
    }
  })

  it('denies every route when FINANCE_API_TOKEN is not configured', async () => {
    const unconfigured = buildApp({})
    await unconfigured.ready()
    for (const route of routes) {
      const response = await unconfigured.inject({ method: route.method, url: route.url, headers: AUTH, payload: {} })
      expect(response.statusCode).toBe(401)
    }
    await unconfigured.close()
  })
})

describe('POST /api/finance/statements/import', () => {
  it('imports a statement and returns the created cycle', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/statements/import',
      headers: AUTH,
      payload: importBody(),
    })
    expect(response.statusCode).toBe(201)
    const body = response.json()
    expect(body.lineCount).toBe(STATEMENT_FIXTURES.length)
    expect(body.parsedTotalCents).toBe(totalOf(STATEMENT_FIXTURES))
    expect(body.cycleId).toBeTruthy()
  })

  it('rejects an unknown account, an unsupported source and a malformed competence month', async () => {
    const cases: [Record<string, unknown>, string][] = [
      [{ accountId: 'nao-existe' }, 'account_not_found'],
      [{ source: 'ANYTHING' }, 'invalid_source'],
      [{ competenceMonth: '2026/07' }, 'invalid_competence_month'],
      [{ lines: [], rawText: '' }, 'empty_statement'],
    ]
    for (const [override, expectedError] of cases) {
      const response = await app.inject({
        method: 'POST',
        url: '/api/finance/statements/import',
        headers: AUTH,
        payload: importBody(override),
      })
      expect(response.json().error).toBe(expectedError)
    }
  })

  it('is idempotent: re-importing the same statement returns the same ids without duplicating', async () => {
    const first = await app.inject({
      method: 'POST',
      url: '/api/finance/statements/import',
      headers: AUTH,
      payload: importBody(),
    })
    const second = await app.inject({
      method: 'POST',
      url: '/api/finance/statements/import',
      headers: AUTH,
      payload: importBody(),
    })
    expect(first.statusCode).toBe(201)
    expect(second.statusCode).toBe(200)
    expect(second.json().statementId).toBe(first.json().statementId)
    expect(statementImports.listLines(first.json().statementId)).toHaveLength(STATEMENT_FIXTURES.length)
  })
})

describe('POST /api/finance/statements/:statementId/reconcile', () => {
  async function importOnce(): Promise<string> {
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/statements/import',
      headers: AUTH,
      payload: importBody(),
    })
    return response.json().statementId as string
  }

  it('reconciles the statement it was given in the path', async () => {
    const statementId = await importOnce()
    const response = await app.inject({
      method: 'POST',
      url: `/api/finance/statements/${statementId}/reconcile`,
      headers: AUTH,
      payload: {},
    })
    expect(response.statusCode).toBe(200)
    const body = response.json()
    expect(body.statementId).toBe(statementId)
    expect(body.matchedCount).toBe(STATEMENT_FIXTURES.length)
    expect(body.cycleStatus).toBe('RECONCILED')
  })

  it('refuses a body that repeats the path parameter', async () => {
    const statementId = await importOnce()
    const response = await app.inject({
      method: 'POST',
      url: `/api/finance/statements/${statementId}/reconcile`,
      headers: AUTH,
      payload: { statementId },
    })
    expect(response.statusCode).toBe(400)
    expect(response.json().error).toBe('duplicated_path_param')
  })

  it('404s an unknown statement', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/statements/nao-existe/reconcile',
      headers: AUTH,
      payload: {},
    })
    expect(response.statusCode).toBe(404)
    expect(response.json().error).toBe('statement_not_found')
  })

  it('never accepts a mode field: the payload shape has no such switch', async () => {
    const statementId = await importOnce()
    const response = await app.inject({
      method: 'POST',
      url: `/api/finance/statements/${statementId}/reconcile`,
      headers: AUTH,
      payload: { mode: 'auto-approve-everything' },
    })
    // `mode` is simply not part of the contract — it is ignored, never honoured.
    expect(response.statusCode).toBe(200)
    expect(Object.keys(response.json())).not.toContain('mode')
  })
})

describe('GET /api/finance/cycles', () => {
  it('lists cycles and honours the account and competence filters', async () => {
    await app.inject({ method: 'POST', url: '/api/finance/statements/import', headers: AUTH, payload: importBody() })

    const all = await app.inject({ method: 'GET', url: '/api/finance/cycles', headers: AUTH })
    expect(all.statusCode).toBe(200)
    const cycles = all.json().cycles as { accountId: string; competenceMonth: string }[]
    expect(cycles.length).toBeGreaterThan(0)
    expect(cycles.every(cycle => cycle.accountId === CARD_ACCOUNT)).toBe(true)

    const filtered = await app.inject({
      method: 'GET',
      url: `/api/finance/cycles?accountId=${CARD_ACCOUNT}&competenceMonth=2026-07`,
      headers: AUTH,
    })
    expect(filtered.json().cycles).toHaveLength(cycles.filter(cycle => cycle.competenceMonth === '2026-07').length)

    const otherMonth = await app.inject({
      method: 'GET',
      url: '/api/finance/cycles?competenceMonth=2026-01',
      headers: AUTH,
    })
    expect(otherMonth.json().cycles).toHaveLength(0)
  })

  it('rejects a malformed competence month', async () => {
    const response = await app.inject({ method: 'GET', url: '/api/finance/cycles?competenceMonth=julho', headers: AUTH })
    expect(response.statusCode).toBe(400)
    expect(response.json().error).toBe('invalid_competence_month')
  })
})
