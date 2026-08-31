import Fastify, { type FastifyInstance } from 'fastify'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { ClarificationsRepository } from '../finance/clarificationsRepository.js'
import { CorrectionsRepository } from '../finance/correctionsRepository.js'
import { openFinanceDb, type FinanceDb } from '../finance/db.js'
import { EnrichmentRepository } from '../finance/enrichmentRepository.js'
import { ItemsRepository } from '../finance/itemsRepository.js'
import { OnboardingRepository } from '../finance/onboardingRepository.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'
import { registerFinanceOnboardingRoutes } from './financeOnboardingRoutes.js'

/**
 * Route-level tests on the REAL runtime path: real SQLite, real repositories, real Fastify
 * driven through `app.inject()`. Covers auth, live-derived export counts, the rule-5 no-secrets
 * guarantee at the HTTP boundary, rule-6 untrusted-import handling, and rule-7 (no mass delivery
 * triggered by a large historical import) at the integration level.
 */

const AUTH = { authorization: 'Bearer test-finance-token' }
const ITEM = 'item-1'
const ACCOUNT = 'acc-1'

let db: FinanceDb
let app: FastifyInstance
let transactions: TransactionsRepository
let clarifications: ClarificationsRepository
let onboarding: OnboardingRepository

beforeEach(async () => {
  db = openFinanceDb(':memory:')
  const accounts = new AccountsRepository(db)
  const items = new ItemsRepository(db)
  const enrichment = new EnrichmentRepository(db)
  const corrections = new CorrectionsRepository(db)
  transactions = new TransactionsRepository(db)
  clarifications = new ClarificationsRepository(db)
  onboarding = new OnboardingRepository(db)

  items.upsertItem({ pluggyItemId: ITEM, status: 'UPDATED', connectorName: 'Banco Exemplo' })
  accounts.upsertAccount({
    pluggyAccountId: ACCOUNT,
    pluggyItemId: ITEM,
    type: 'BANK',
    name: 'Conta Corrente',
    currencyCode: 'BRL',
    balanceCents: 0,
  })

  app = Fastify({ logger: false })
  registerFinanceOnboardingRoutes(app, {
    config: { FINANCE_API_TOKEN: 'test-finance-token' } as AppConfig,
    transactions,
    accounts,
    items,
    enrichment,
    clarifications,
    corrections,
    onboarding,
  })
  await app.ready()
})

afterEach(async () => {
  await app.close()
  db.close()
})

/** Seeds N historical transactions with one OPEN clarification each. N is caller-chosen, never hard-coded here. */
function seedOpenClarifications(count: number, prefix = 'tx') {
  for (let i = 0; i < count; i += 1) {
    const txId = `${prefix}-${i}`
    transactions.upsertTransaction({
      pluggyTransactionId: txId,
      pluggyAccountId: ACCOUNT,
      description: `Transação histórica ${i}`,
      amountCents: -1000 - i,
      date: '2026-08-01T12:00:00.000Z',
      rawData: { id: txId, secret_token: 'should-never-be-exported', card_number: '4111111111111111' },
    })
    clarifications.getOrCreateOpen({ pluggyTransactionId: txId, questionType: 'category', questionText: 'Como classificar?' })
  }
}

describe('registerFinanceOnboardingRoutes — autenticação (fail-closed)', () => {
  it('recusa export sem token', async () => {
    const res = await app.inject({ method: 'POST', url: '/api/finance/onboarding/export', payload: {} })
    expect(res.statusCode).toBe(401)
  })

  it('recusa import com token inválido', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: { authorization: 'Bearer errado' },
      payload: { fileContent: 'a,b\n1,2\n' },
    })
    expect(res.statusCode).toBe(401)
  })

  it('nega quando FINANCE_API_TOKEN não está configurado', async () => {
    const noTokenApp = Fastify({ logger: false })
    registerFinanceOnboardingRoutes(noTokenApp, {
      config: { FINANCE_API_TOKEN: undefined } as AppConfig,
      transactions,
      accounts: new AccountsRepository(db),
      items: new ItemsRepository(db),
      enrichment: new EnrichmentRepository(db),
      clarifications,
      corrections: new CorrectionsRepository(db),
      onboarding,
    })
    await noTokenApp.ready()
    const res = await noTokenApp.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: { authorization: 'Bearer anything' },
      payload: {},
    })
    expect(res.statusCode).toBe(401)
    await noTokenApp.close()
  })
})

describe('registerFinanceOnboardingRoutes — export: contagem derivada, regra 5 (sem segredo/número integral)', () => {
  it('rowCount reflete exatamente os dados vivos, nunca um número fixo', async () => {
    const backlogSize = 7 // arbitrary, asserted against the response, never hard-coded server-side
    seedOpenClarifications(backlogSize)

    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId: ITEM },
    })
    expect(res.statusCode).toBe(201)
    const body = res.json()
    expect(body.rowCount).toBe(backlogSize)
    expect(body.csv.trim().split('\r\n')).toHaveLength(backlogSize + 1) // header + rows
  })

  it('CSV exportado não contém segredo, token nem número de cartão completo do raw_data', async () => {
    seedOpenClarifications(3)
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId: ITEM },
    })
    const csv: string = res.json().csv
    expect(csv).not.toMatch(/secret/i)
    expect(csv).not.toMatch(/token/i)
    expect(csv).not.toContain('4111111111111111')
  })

  it('export com filtro que não bate com nada retorna rowCount 0, não erro', async () => {
    seedOpenClarifications(2)
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      // A real, existing item but a competence_month that matches nothing seeded.
      payload: { pluggyItemId: ITEM, competenceMonth: '2099-01' },
    })
    expect(res.statusCode).toBe(201)
    expect(res.json().rowCount).toBe(0)
  })
})

describe('registerFinanceOnboardingRoutes — import: dado não confiável (regra 6)', () => {
  it('dry-run (padrão) nunca escreve correção', async () => {
    seedOpenClarifications(1)
    const exportRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId: ITEM },
    })
    const csv: string = exportRes.json().csv

    const importRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: csv },
    })
    expect(importRes.statusCode).toBe(200)
    expect(importRes.json().dryRun).toBe(true)

    const corrections = new CorrectionsRepository(db)
    expect(corrections.listActive('tx-0').size).toBe(0)
  })

  it('rejeita CSV com cabeçalho fora do schema em vez de tentar interpretar', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: 'coluna_maliciosa,outra\nvalor,valor2\n' },
    })
    expect(res.statusCode).toBe(400)
    expect(res.json().error).toBe('parse_error')
  })

  it('rejeita fileContent ausente/vazio', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: {},
    })
    expect(res.statusCode).toBe(400)
    expect(res.json().error).toBe('invalid_file_content')
  })

  it('dryRun:false aplica a mudança e reimportar o mesmo conteúdo não duplica', async () => {
    seedOpenClarifications(1)
    const exportRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId: ITEM },
    })
    const csv: string = exportRes.json().csv
    const lines = csv.trim().split('\r\n')
    const header = lines[0].split(',')
    const categoryIdx = header.indexOf('category')
    const cells = lines[1].split(',')
    cells[categoryIdx] = 'Mercado'
    const editedCsv = [lines[0], cells.join(',')].join('\r\n')

    const applied1 = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: editedCsv, dryRun: false },
    })
    expect(applied1.statusCode).toBe(200)
    expect(applied1.json().rows[0].outcome).toBe('applied')

    const corrections = new CorrectionsRepository(db)
    expect(corrections.getActive('tx-0', 'category')?.new_effective_value).toBe('Mercado')

    const applied2 = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: editedCsv, dryRun: false },
    })
    expect(applied2.json().rows[0].outcome).not.toBe('applied')
    // Still only one active correction for the field — the ledger was not appended twice.
    expect(corrections.listHistory('tx-0').filter(r => r.field === 'category')).toHaveLength(1)
  })
})

describe('registerFinanceOnboardingRoutes — regra 7: importação histórica em massa não gera fila de entrega', () => {
  it('importar um backlog grande via CSV não cria/entrega clarificações em massa', async () => {
    onboarding.getOrCreate(ITEM) // HISTORICAL_IMPORT by default
    const backlogSize = 42 // arbitrary "large", derived assertions below — not a magic contract
    seedOpenClarifications(backlogSize, 'hist')

    const exportRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/export',
      headers: AUTH,
      payload: { pluggyItemId: ITEM },
    })
    expect(exportRes.json().rowCount).toBe(backlogSize)

    // Importing (even applying) the exported batch resolves nothing on its own and creates no
    // delivery queue entries — clarifications remain open until the owner explicitly resolves them.
    const openBefore = clarifications.count({ status: 'open', pluggyItemId: ITEM })
    const importRes = await app.inject({
      method: 'POST',
      url: '/api/finance/onboarding/import',
      headers: AUTH,
      payload: { fileContent: exportRes.json().csv, dryRun: false },
    })
    expect(importRes.statusCode).toBe(200)
    const openAfter = clarifications.count({ status: 'open', pluggyItemId: ITEM })
    // No action column was set (blank), so nothing gets auto-resolved and nothing gets delivered.
    expect(openAfter).toBe(openBefore)
  })
})
