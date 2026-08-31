import Fastify, { type FastifyInstance } from 'fastify'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { CorrectionsRepository } from '../finance/correctionsRepository.js'
import { CycleAssignmentService } from '../finance/cycleAssignmentService.js'
import { openFinanceDb, type FinanceDb } from '../finance/db.js'
import { EffectiveTransactionService } from '../finance/effectiveTransaction.js'
import { EnrichmentRepository } from '../finance/enrichmentRepository.js'
import { ItemsRepository } from '../finance/itemsRepository.js'
import { MerchantRulesRepository } from '../finance/merchantRulesRepository.js'
import { ProductsRepository } from '../finance/productsRepository.js'
import { StatementCyclesRepository } from '../finance/statementCyclesRepository.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'
import { registerFinanceCorrectionRoutes } from './financeCorrectionRoutes.js'

/**
 * Route-level tests on the REAL runtime path: real SQLite, real migrations, real repositories,
 * a real Fastify instance driven through `app.inject()`. Nothing is stubbed, so a break anywhere
 * between HTTP and the database surfaces here.
 */

const AUTH = { authorization: 'Bearer test-finance-token' }
const CARD_ACCOUNT = 'acc-card'

let db: FinanceDb
let app: FastifyInstance
let transactions: TransactionsRepository
let products: ProductsRepository
let cycles: StatementCyclesRepository
let cycleAssignment: CycleAssignmentService

beforeEach(async () => {
  db = openFinanceDb(':memory:')

  const accounts = new AccountsRepository(db)
  const corrections = new CorrectionsRepository(db)
  const merchantRules = new MerchantRulesRepository(db)
  const enrichment = new EnrichmentRepository(db)
  transactions = new TransactionsRepository(db)
  products = new ProductsRepository(db)
  cycles = new StatementCyclesRepository(db)
  cycleAssignment = new CycleAssignmentService({ db, accounts, cycles, corrections })
  const effective = new EffectiveTransactionService({ corrections, merchantRules, cycles, enrichment })

  new ItemsRepository(db).upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
  accounts.upsertAccount({
    pluggyAccountId: CARD_ACCOUNT,
    pluggyItemId: 'item-1',
    type: 'CREDIT',
    subtype: 'CREDIT_CARD',
    name: 'Cartão',
    currencyCode: 'BRL',
    balanceCents: 0,
  })

  app = Fastify({ logger: false })
  registerFinanceCorrectionRoutes(app, {
    config: { FINANCE_API_TOKEN: 'test-finance-token' } as AppConfig,
    transactions,
    accounts,
    corrections,
    merchantRules,
    cycles,
    cycleAssignment,
    effective,
  })
  await app.ready()
})

/** Fastify first, so no route still holds the connection when the database handle is released. */
afterEach(async () => {
  await app.close()
  db.close()
})

function seedTransaction(id: string, overrides: { date?: string; cardMetadata?: unknown } = {}) {
  const date = overrides.date ?? '2026-08-10T12:00:00.000Z'
  transactions.upsertTransaction({
    pluggyTransactionId: id,
    pluggyAccountId: CARD_ACCOUNT,
    description: 'PADARIA CENTRAL LTDA',
    amountCents: -4599,
    currencyCode: 'BRL',
    accountCurrencyCode: 'BRL',
    date,
    type: 'DEBIT',
    status: 'POSTED',
    categoryOriginal: 'Food',
    merchantOriginal: 'PADARIA CENTRAL',
    rawData: { id, description: 'PADARIA CENTRAL LTDA', creditCardMetadata: overrides.cardMetadata },
  })
}

describe('registerFinanceCorrectionRoutes — autenticação', () => {
  it('recusa requisição sem token', async () => {
    const response = await app.inject({ method: 'GET', url: '/api/finance/rules' })
    expect(response.statusCode).toBe(401)
    expect(response.json()).toMatchObject({ error: 'unauthorized' })
  })

  it('recusa token inválido', async () => {
    const response = await app.inject({
      method: 'GET',
      url: '/api/finance/rules',
      headers: { authorization: 'Bearer errado' },
    })
    expect(response.statusCode).toBe(401)
  })
})

describe('registerFinanceCorrectionRoutes — correções', () => {
  it('registra correção, devolve o efetivo e mantém o raw intacto', async () => {
    seedTransaction('tx-1')

    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'tx-1', field: 'category', value: 'Presentes', reason: 'compra para terceiro', actorId: 'owner' },
    })
    expect(response.statusCode).toBe(201)
    const body = response.json()
    expect(body.correction).toMatchObject({ field: 'category', newValue: 'Presentes', active: true })
    // The pre-correction effective value is captured for audit.
    expect(body.correction.oldValue).toBe('Food')
    expect(body.effective.effective.category).toMatchObject({ value: 'Presentes', source: 'CORRECTION' })
    expect(body.effective.raw.categoryOriginal).toBe('Food')

    const row = transactions.getByPluggyId('tx-1')!
    expect(row.category_original).toBe('Food')
    expect(JSON.parse(row.raw_data!).description).toBe('PADARIA CENTRAL LTDA')
  })

  it('histórico expõe entradas superseded e a correção ativa', async () => {
    seedTransaction('tx-2')
    for (const value of ['Primeiro', 'Segundo', 'Terceiro']) {
      await app.inject({
        method: 'POST',
        url: '/api/finance/corrections',
        headers: AUTH,
        payload: { transactionId: 'tx-2', field: 'merchant', value },
      })
    }

    const response = await app.inject({
      method: 'GET',
      url: '/api/finance/corrections/tx-2',
      headers: AUTH,
    })
    expect(response.statusCode).toBe(200)
    const body = response.json()
    expect(body.history).toHaveLength(3)
    expect(body.history.filter((entry: { active: boolean }) => entry.active)).toHaveLength(1)
    expect(body.active).toHaveLength(1)
    expect(body.active[0].newValue).toBe('Terceiro')
  })

  it('remover correção supersede sem apagar e devolve o efetivo ao raw', async () => {
    seedTransaction('tx-3')
    await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'tx-3', field: 'category', value: 'Presentes' },
    })

    const removed = await app.inject({
      method: 'DELETE',
      url: '/api/finance/corrections/tx-3/category',
      headers: AUTH,
    })
    expect(removed.statusCode).toBe(200)
    expect(removed.json().effective.effective.category).toMatchObject({ value: 'Food', source: 'SOURCE_METADATA' })

    const history = await app.inject({
      method: 'GET',
      url: '/api/finance/corrections/tx-3',
      headers: AUTH,
    })
    expect(history.json().history).toHaveLength(1)
    expect(history.json().active).toHaveLength(0)

    const again = await app.inject({
      method: 'DELETE',
      url: '/api/finance/corrections/tx-3/category',
      headers: AUTH,
    })
    expect(again.statusCode).toBe(404)
  })

  it('rejeita campo desconhecido, mês malformado e valor monetário não inteiro', async () => {
    seedTransaction('tx-4')
    const cases: { payload: Record<string, unknown>; error: string }[] = [
      { payload: { field: 'inventado', value: 'x' }, error: 'invalid_field' },
      { payload: { field: 'competence_month', value: '2026/08' }, error: 'invalid_month' },
      { payload: { field: 'amount', value: 45.99 }, error: 'invalid_amount' },
      { payload: { field: 'statement_cycle', value: 'ciclo-inexistente' }, error: 'cycle_not_found' },
    ]
    for (const testCase of cases) {
      const response = await app.inject({
        method: 'POST',
        url: '/api/finance/corrections',
        headers: AUTH,
        payload: { transactionId: 'tx-4', ...testCase.payload },
      })
      expect(response.statusCode).toBe(400)
      expect(response.json().error).toBe(testCase.error)
    }
  })

  it('aceita valor monetário em centavos inteiros', async () => {
    seedTransaction('tx-5')
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'tx-5', field: 'amount', value: -4500 },
    })
    expect(response.statusCode).toBe(201)
    expect(response.json().effective.effective.amountCents).toMatchObject({ value: -4500, source: 'CORRECTION' })
    // Raw stays exactly what the institution sent.
    expect(transactions.getByPluggyId('tx-5')!.amount_cents).toBe(-4599)
  })

  it('404 para transação inexistente', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'nao-existe', field: 'category', value: 'x' },
    })
    expect(response.statusCode).toBe(404)
  })

  it('correção de ciclo reatribui a fatura e recalcula competência e caixa', async () => {
    products.upsertCreditCardBill({
      pluggyBillId: 'bill-ago',
      pluggyAccountId: CARD_ACCOUNT,
      billClosingDate: '2026-08-05T00:00:00.000Z',
      dueDate: '2026-08-15T00:00:00.000Z',
      currencyCode: 'BRL',
      rawData: { id: 'bill-ago' },
    })
    products.upsertCreditCardBill({
      pluggyBillId: 'bill-set',
      pluggyAccountId: CARD_ACCOUNT,
      billClosingDate: '2026-09-05T00:00:00.000Z',
      dueDate: '2026-09-15T00:00:00.000Z',
      currencyCode: 'BRL',
      rawData: { id: 'bill-set' },
    })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)
    seedTransaction('tx-6', { date: '2026-09-01T12:00:00.000Z' })
    cycleAssignment.syncTemporal(transactions.getByPluggyId('tx-6')!)

    const target = cycles.findBestForCompetence(CARD_ACCOUNT, '2026-08')!
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'tx-6', field: 'statement_cycle', value: target.id, source: 'USER' },
    })
    expect(response.statusCode).toBe(201)

    const temporal = response.json().effective.temporal
    expect(temporal.statementCycleId).toBe(target.id)
    expect(temporal.competenceMonth.value).toBe('2026-08')
    expect(temporal.cashflowMonth).toBe('2026-08')
    // The purchase month is a source fact and survives the reassignment untouched.
    expect(temporal.purchaseMonth).toBe('2026-09')
  })

  it('correção de atribuição é projetada nas colunas consultáveis', async () => {
    seedTransaction('tx-7')
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/corrections',
      headers: AUTH,
      payload: { transactionId: 'tx-7',
        field: 'reimbursement',
        value: { paidBy: 'cartao-titular', receivableFrom: 'terceiro', status: 'PENDING' },
      },
    })
    expect(response.statusCode).toBe(201)
    expect(response.json().effective.effective.reimbursement.value).toMatchObject({
      paidBy: 'cartao-titular',
      receivableFrom: 'terceiro',
      receivableStatus: 'PENDING',
    })

    const projected = db
      .prepare('SELECT paid_by, receivable_status FROM financial_transaction_enrichment WHERE pluggy_transaction_id = ?')
      .get('tx-7') as { paid_by: string; receivable_status: string }
    expect(projected).toEqual({ paid_by: 'cartao-titular', receivable_status: 'PENDING' })
  })

  it('GET /effective devolve raw e efetivo lado a lado', async () => {
    seedTransaction('tx-8')
    const response = await app.inject({
      method: 'GET',
      url: '/api/finance/transactions/tx-8/effective',
      headers: AUTH,
    })
    expect(response.statusCode).toBe(200)
    const body = response.json()
    expect(body.raw).toMatchObject({ amountCents: -4599, categoryOriginal: 'Food' })
    expect(body.effective.category).toMatchObject({ value: 'Food', source: 'SOURCE_METADATA' })
  })
})

describe('registerFinanceCorrectionRoutes — regras de merchant', () => {
  it('regra nasce SUGGEST e não altera o efetivo', async () => {
    seedTransaction('tx-9')
    const created = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'PADARIA CENTRAL', ruleType: 'CATEGORY', targetValue: 'Alimentação' },
    })
    expect(created.statusCode).toBe(201)
    expect(created.json().rule.mode).toBe('SUGGEST')

    const effective = await app.inject({
      method: 'GET',
      url: '/api/finance/transactions/tx-9/effective',
      headers: AUTH,
    })
    const body = effective.json()
    expect(body.effective.category.value).toBe('Food')
    expect(body.suggestions).toContainEqual(
      expect.objectContaining({ value: 'Alimentação', reason: 'suggest_mode' }),
    )
  })

  it('recusa criar regra já TRUSTED: promoção exige ação explícita', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: {
        merchantPattern: 'PADARIA CENTRAL',
        ruleType: 'CATEGORY',
        targetValue: 'Alimentação',
        mode: 'TRUSTED',
      },
    })
    expect(response.statusCode).toBe(400)
    expect(response.json().error).toBe('trusted_requires_promotion')
  })

  it('promoção explícita torna a regra TRUSTED e passa a valer no efetivo', async () => {
    seedTransaction('tx-10')
    const created = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'PADARIA CENTRAL', ruleType: 'CATEGORY', targetValue: 'Alimentação' },
    })
    const ruleId = created.json().rule.id

    const promoted = await app.inject({
      method: 'POST',
      url: `/api/finance/rules/${ruleId}/promote`,
      headers: AUTH,
      payload: { actorId: 'owner' },
    })
    expect(promoted.statusCode).toBe(200)
    expect(promoted.json().rule.mode).toBe('TRUSTED')

    const effective = await app.inject({
      method: 'GET',
      url: '/api/finance/transactions/tx-10/effective',
      headers: AUTH,
    })
    expect(effective.json().effective.category).toMatchObject({ value: 'Alimentação', source: 'TRUSTED_RULE' })
  })

  it('valida payload da regra e escopo de conta inexistente', async () => {
    const invalidType = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'X', ruleType: 'INVENTADO', targetValue: 'y' },
    })
    expect(invalidType.statusCode).toBe(400)
    expect(invalidType.json().error).toBe('invalid_rule_type')

    const unknownAccount = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: {
        merchantPattern: 'X',
        ruleType: 'CATEGORY',
        targetValue: 'y',
        scopeAccountId: 'conta-que-nao-existe',
      },
    })
    expect(unknownAccount.statusCode).toBe(404)
    expect(unknownAccount.json().error).toBe('account_not_found')
  })

  it('lista regras ativas e desativa uma regra', async () => {
    const created = await app.inject({
      method: 'POST',
      url: '/api/finance/rules',
      headers: AUTH,
      payload: { merchantPattern: 'PADARIA CENTRAL', ruleType: 'CATEGORY', targetValue: 'Alimentação' },
    })
    const ruleId = created.json().rule.id

    const listed = await app.inject({ method: 'GET', url: '/api/finance/rules', headers: AUTH })
    expect(listed.json().rules.map((rule: { id: string }) => rule.id)).toContain(ruleId)

    const removed = await app.inject({
      method: 'DELETE',
      url: `/api/finance/rules/${ruleId}`,
      headers: AUTH,
    })
    expect(removed.statusCode).toBe(200)

    const after = await app.inject({ method: 'GET', url: '/api/finance/rules', headers: AUTH })
    expect(after.json().rules).toHaveLength(0)

    const promoteGone = await app.inject({
      method: 'POST',
      url: `/api/finance/rules/${ruleId}/promote`,
      headers: AUTH,
    })
    expect(promoteGone.statusCode).toBe(404)
  })
})
