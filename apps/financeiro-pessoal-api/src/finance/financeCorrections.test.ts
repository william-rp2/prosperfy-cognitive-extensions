import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { CorrectionsRepository } from './correctionsRepository.js'
import { CycleAssignmentService } from './cycleAssignmentService.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { EffectiveTransactionService } from './effectiveTransaction.js'
import { EnrichmentRepository } from './enrichmentRepository.js'
import { ItemsRepository } from './itemsRepository.js'
import { MerchantRulesRepository } from './merchantRulesRepository.js'
import { ProductsRepository } from './productsRepository.js'
import { StatementCyclesRepository } from './statementCyclesRepository.js'
import type { TemporalTransactionRow } from './temporalSemantics.js'
import { TransactionsRepository } from './transactionsRepository.js'
import type { FinancialAccountRow } from './types.js'

/**
 * F2B domain layer: corrections, learned rules, statement cycles and temporal semantics.
 *
 * These exercise the real runtime path — actual SQLite, real migrations, real repositories — not
 * mocks, because every invariant here (append-only ledger, raw immutability, assignment
 * precedence) is enforced partly by SQL constraints that a stubbed repository would not have.
 */

const CARD_ACCOUNT = 'acc-card'
const CASH_ACCOUNT = 'acc-cash'

let db: FinanceDb
let accounts: AccountsRepository
let transactions: TransactionsRepository
let products: ProductsRepository
let corrections: CorrectionsRepository
let cycles: StatementCyclesRepository
let merchantRules: MerchantRulesRepository
let enrichment: EnrichmentRepository
let cycleAssignment: CycleAssignmentService
let effective: EffectiveTransactionService

beforeEach(() => {
  db = openFinanceDb(':memory:')
  accounts = new AccountsRepository(db)
  transactions = new TransactionsRepository(db)
  products = new ProductsRepository(db)
  corrections = new CorrectionsRepository(db)
  cycles = new StatementCyclesRepository(db)
  merchantRules = new MerchantRulesRepository(db)
  enrichment = new EnrichmentRepository(db)
  cycleAssignment = new CycleAssignmentService({ db, accounts, cycles, corrections })
  effective = new EffectiveTransactionService({ corrections, merchantRules, cycles, enrichment })

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
  accounts.upsertAccount({
    pluggyAccountId: CASH_ACCOUNT,
    pluggyItemId: 'item-1',
    type: 'BANK',
    subtype: 'CHECKING_ACCOUNT',
    name: 'Conta',
    currencyCode: 'BRL',
    balanceCents: 0,
  })
})

afterEach(() => db.close())

interface SeedTransactionInput {
  id: string
  accountId?: string
  /** Date the provider reports — for a card this is the POSTING date, not the purchase date. */
  date: string
  amountCents?: number
  currencyCode?: string | null
  merchant?: string | null
  category?: string | null
  /** Written into raw_data.creditCardMetadata, exactly as Pluggy would send it. */
  cardMetadata?: Record<string, unknown>
}

function seedTransaction(input: SeedTransactionInput): TemporalTransactionRow {
  const accountId = input.accountId ?? CARD_ACCOUNT
  const raw: Record<string, unknown> = {
    id: input.id,
    description: `Compra ${input.id}`,
    amount: (input.amountCents ?? -5000) / 100,
    date: input.date,
  }
  if (input.cardMetadata) raw.creditCardMetadata = input.cardMetadata

  const { row } = transactions.upsertTransaction({
    pluggyTransactionId: input.id,
    pluggyAccountId: accountId,
    description: `Compra ${input.id}`,
    amountCents: input.amountCents ?? -5000,
    currencyCode: input.currencyCode === undefined ? 'BRL' : input.currencyCode,
    accountCurrencyCode: 'BRL',
    date: input.date,
    type: 'DEBIT',
    status: 'POSTED',
    categoryOriginal: input.category ?? null,
    merchantOriginal: input.merchant ?? null,
    rawData: raw,
  })
  return row as TemporalTransactionRow
}

function reload(id: string): TemporalTransactionRow {
  return transactions.getByPluggyId(id) as TemporalTransactionRow
}

function cardAccount(): FinancialAccountRow {
  return accounts.getByPluggyId(CARD_ACCOUNT)!
}

function seedBill(input: {
  billId: string
  closingDate: string | null
  dueDate: string | null
  totalCents?: number | null
}) {
  return products.upsertCreditCardBill({
    pluggyBillId: input.billId,
    pluggyAccountId: CARD_ACCOUNT,
    dueDate: input.dueDate,
    billClosingDate: input.closingDate,
    totalAmountCents: input.totalCents ?? null,
    currencyCode: 'BRL',
    rawData: { id: input.billId },
  })
}

describe('camada efetiva: precedência de correção', () => {
  it('correção explícita do dono vence regra TRUSTED do mesmo campo', () => {
    const row = seedTransaction({
      id: 'tx-1',
      date: '2026-08-10T12:00:00.000Z',
      merchant: 'PADARIA CENTRAL',
      category: 'Food',
    })

    const rule = merchantRules.upsertRule({
      merchantPattern: 'PADARIA CENTRAL',
      ruleType: 'CATEGORY',
      targetValue: 'Alimentação',
    })
    merchantRules.promoteToTrusted(rule.id)

    const beforeCorrection = effective.build(reload('tx-1'), cardAccount())
    expect(beforeCorrection.category.value).toBe('Alimentação')
    expect(beforeCorrection.category.source).toBe('TRUSTED_RULE')

    corrections.applyCorrection({
      pluggyTransactionId: row.pluggy_transaction_id,
      field: 'category',
      newValue: 'Presentes',
      source: 'USER',
    })

    const afterCorrection = effective.build(reload('tx-1'), cardAccount())
    expect(afterCorrection.category.value).toBe('Presentes')
    expect(afterCorrection.category.source).toBe('CORRECTION')
    // The rule is not deleted or silently ignored: it is surfaced as outranked.
    expect(afterCorrection.suggestions).toContainEqual(
      expect.objectContaining({ ruleId: rule.id, reason: 'outranked_by_correction' }),
    )
  })

  it('regra TRUSTED vence metadado da fonte, que por sua vez vence inferência do classificador', () => {
    seedTransaction({
      id: 'tx-2',
      date: '2026-08-10T12:00:00.000Z',
      merchant: 'MERCADO XYZ',
      category: 'Supermercado (fonte)',
    })
    enrichment.upsert({
      pluggyTransactionId: 'tx-2',
      categoryName: 'Palpite do classificador',
      classificationStatus: 'classified',
      classificationSource: 'deterministic_rule',
    })

    // Source metadata beats the classifier guess.
    const withoutRule = effective.build(reload('tx-2'), cardAccount())
    expect(withoutRule.category.value).toBe('Supermercado (fonte)')
    expect(withoutRule.category.source).toBe('SOURCE_METADATA')

    const rule = merchantRules.upsertRule({
      merchantPattern: 'MERCADO XYZ',
      ruleType: 'CATEGORY',
      targetValue: 'Mercado',
    })
    merchantRules.promoteToTrusted(rule.id)

    const withRule = effective.build(reload('tx-2'), cardAccount())
    expect(withRule.category.value).toBe('Mercado')
    expect(withRule.category.source).toBe('TRUSTED_RULE')
  })

  it('moeda informada pela instituição não é sobrescrita por regra aprendida: divergência é reportada', () => {
    seedTransaction({
      id: 'tx-3',
      date: '2026-08-10T12:00:00.000Z',
      merchant: 'STEAM GAMES',
      currencyCode: 'BRL',
    })
    const rule = merchantRules.upsertRule({
      merchantPattern: 'STEAM GAMES',
      ruleType: 'CURRENCY_HINT',
      targetValue: 'USD',
    })
    merchantRules.promoteToTrusted(rule.id)

    const built = effective.build(reload('tx-3'), cardAccount())
    expect(built.currencyCode.value).toBe('BRL')
    expect(built.currencyCode.source).toBe('SOURCE_METADATA')
    expect(built.discrepancies).toContainEqual(
      expect.objectContaining({ field: 'currency', sourceValue: 'BRL', ruleValue: 'USD' }),
    )
  })
})

describe('ledger de correções append-only', () => {
  it('corrigir duas vezes supersede a anterior e mantém histórico completo', () => {
    seedTransaction({ id: 'tx-4', date: '2026-08-10T12:00:00.000Z' })

    const first = corrections.applyCorrection({
      pluggyTransactionId: 'tx-4',
      field: 'merchant',
      newValue: 'Padaria da esquina',
      actorId: 'owner',
    })
    const second = corrections.applyCorrection({
      pluggyTransactionId: 'tx-4',
      field: 'merchant',
      newValue: 'Padaria Central',
      actorId: 'owner',
    })

    const history = corrections.listHistory('tx-4')
    expect(history).toHaveLength(2)
    expect(history[0]!.id).toBe(first.id)
    expect(history[0]!.superseded_at).not.toBeNull()
    expect(history[1]!.id).toBe(second.id)
    expect(history[1]!.superseded_at).toBeNull()
    // The new entry records what it replaced, so the chain stays auditable.
    expect(history[1]!.old_effective_value).toBe('Padaria da esquina')

    expect(corrections.getActive('tx-4', 'merchant')?.id).toBe(second.id)
    expect(effective.build(reload('tx-4'), cardAccount()).merchant.value).toBe('Padaria Central')
  })

  it('apenas uma correção ativa por (transação, campo) — garantido pelo índice parcial', () => {
    seedTransaction({ id: 'tx-5', date: '2026-08-10T12:00:00.000Z' })
    corrections.applyCorrection({ pluggyTransactionId: 'tx-5', field: 'notes', newValue: 'a' })
    corrections.applyCorrection({ pluggyTransactionId: 'tx-5', field: 'notes', newValue: 'b' })
    corrections.applyCorrection({ pluggyTransactionId: 'tx-5', field: 'notes', newValue: 'c' })

    const activeCount = db
      .prepare(
        'SELECT COUNT(*) AS total FROM financial_corrections WHERE pluggy_transaction_id = ? AND field = ? AND superseded_at IS NULL',
      )
      .get('tx-5', 'notes') as { total: number }
    expect(activeCount.total).toBe(1)
    expect(corrections.listHistory('tx-5')).toHaveLength(3)
  })

  it('reverter supersede sem apagar: histórico intacto e efetivo volta para o raw', () => {
    seedTransaction({ id: 'tx-6', date: '2026-08-10T12:00:00.000Z', category: 'Lazer' })
    corrections.applyCorrection({ pluggyTransactionId: 'tx-6', field: 'category', newValue: 'Educação' })

    expect(effective.build(reload('tx-6'), cardAccount()).category.value).toBe('Educação')

    expect(corrections.revertCorrection('tx-6', 'category')).toBe(true)
    expect(corrections.revertCorrection('tx-6', 'category')).toBe(false)

    expect(corrections.listHistory('tx-6')).toHaveLength(1)
    const back = effective.build(reload('tx-6'), cardAccount())
    expect(back.category.value).toBe('Lazer')
    expect(back.category.source).toBe('SOURCE_METADATA')
  })

  it('atribuição corrigida é projetada nas colunas consultáveis e limpa ao reverter', () => {
    seedTransaction({ id: 'tx-7', date: '2026-08-10T12:00:00.000Z' })

    corrections.applyCorrection({
      pluggyTransactionId: 'tx-7',
      field: 'reimbursement',
      newValue: JSON.stringify({ paidBy: 'conta-conjunta', receivableFrom: 'terceiro', status: 'PENDING' }),
    })
    corrections.projectAttribution('tx-7')

    const projected = db
      .prepare('SELECT paid_by, receivable_from, receivable_status FROM financial_transaction_enrichment WHERE pluggy_transaction_id = ?')
      .get('tx-7') as { paid_by: string | null; receivable_from: string | null; receivable_status: string | null }
    expect(projected).toEqual({ paid_by: 'conta-conjunta', receivable_from: 'terceiro', receivable_status: 'PENDING' })

    corrections.revertCorrection('tx-7', 'reimbursement')
    corrections.projectAttribution('tx-7')
    const cleared = db
      .prepare('SELECT paid_by, receivable_from, receivable_status FROM financial_transaction_enrichment WHERE pluggy_transaction_id = ?')
      .get('tx-7') as { paid_by: string | null; receivable_from: string | null; receivable_status: string | null }
    expect(cleared).toEqual({ paid_by: null, receivable_from: null, receivable_status: null })
  })
})

describe('imutabilidade do raw', () => {
  it('correções e derivação temporal nunca reescrevem raw_data, date, amount_cents ou currency_code', () => {
    seedTransaction({
      id: 'tx-8',
      date: '2026-08-10T12:00:00.000Z',
      amountCents: -12345,
      currencyCode: 'USD',
      cardMetadata: { purchaseDate: '2026-07-28T00:00:00.000Z', billId: 'bill-imut' },
    })
    const before = reload('tx-8')
    const upstream = {
      raw_data: before.raw_data,
      date: before.date,
      amount_cents: before.amount_cents,
      currency_code: before.currency_code,
      amount_in_account_currency_cents: before.amount_in_account_currency_cents,
    }

    seedBill({ billId: 'bill-imut', closingDate: '2026-08-12T00:00:00.000Z', dueDate: '2026-08-20T00:00:00.000Z' })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)

    corrections.applyCorrection({ pluggyTransactionId: 'tx-8', field: 'amount', newValue: '-9900' })
    corrections.applyCorrection({ pluggyTransactionId: 'tx-8', field: 'currency', newValue: 'BRL' })
    cycleAssignment.syncTemporal(reload('tx-8'), cardAccount())

    const after = reload('tx-8')
    expect({
      raw_data: after.raw_data,
      date: after.date,
      amount_cents: after.amount_cents,
      currency_code: after.currency_code,
      amount_in_account_currency_cents: after.amount_in_account_currency_cents,
    }).toEqual(upstream)

    // The effective layer is where the correction shows up — beside the untouched raw value.
    const built = effective.build(after, cardAccount())
    expect(built.amountCents.value).toBe(-9900)
    expect(built.amountCents.source).toBe('CORRECTION')
    expect(built.raw.amountCents).toBe(-12345)
    expect(built.raw.currencyCode).toBe('USD')
  })

  it('erro upstream é corrigido no ledger, não escondido no raw', () => {
    seedTransaction({ id: 'tx-9', date: '2026-08-10T12:00:00.000Z', merchant: 'NOME ERRADO DA FONTE' })
    corrections.applyCorrection({
      pluggyTransactionId: 'tx-9',
      field: 'merchant',
      newValue: 'Nome correto',
      reason: 'instituição enviou o descritivo trocado',
    })

    const row = reload('tx-9')
    expect(row.merchant_original).toBe('NOME ERRADO DA FONTE')
    expect(JSON.parse(row.raw_data!)).toMatchObject({ id: 'tx-9' })
    expect(effective.build(row, cardAccount()).merchant.value).toBe('Nome correto')
  })
})

describe('precedência de atribuição de ciclo', () => {
  it('USER > reconciliação de fatura > identidade de fatura upstream > regra de data', () => {
    seedBill({ billId: 'bill-ago', closingDate: '2026-08-05T00:00:00.000Z', dueDate: '2026-08-15T00:00:00.000Z' })
    seedBill({ billId: 'bill-set', closingDate: '2026-09-05T00:00:00.000Z', dueDate: '2026-09-15T00:00:00.000Z' })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)

    // 4. Deterministic date rule: no bill identity in the payload, only the posting date.
    seedTransaction({ id: 'tx-rule', date: '2026-09-01T12:00:00.000Z' })
    const ruleDecision = cycleAssignment.decideCycle(reload('tx-rule'), cardAccount())
    expect(ruleDecision.source).toBe('RULE')
    expect(ruleDecision.reason).toBe('cycle_window')

    // 3. Explicit upstream bill identity outranks the date rule.
    seedTransaction({
      id: 'tx-bill',
      date: '2026-09-01T12:00:00.000Z',
      cardMetadata: { billId: 'bill-ago' },
    })
    const billDecision = cycleAssignment.decideCycle(reload('tx-bill'), cardAccount())
    expect(billDecision.source).toBe('PLUGGY_BILL')
    expect(billDecision.reason).toBe('upstream_bill')

    // 2. A reconciled imported statement outranks the provider's own bill identity.
    const reconciled = cycles.upsertCycle({
      financialAccountId: CARD_ACCOUNT,
      source: 'STATEMENT_IMPORT',
      competenceMonth: '2026-09',
      statementCurrency: 'BRL',
      periodStart: '2026-08-06T00:00:00.000Z',
      periodEnd: '2026-09-05T23:59:59.000Z',
      closingDate: '2026-09-05T00:00:00.000Z',
      dueDate: '2026-09-15T00:00:00.000Z',
      status: 'RECONCILED',
      reconciliationStatus: 'MATCHED',
    })
    const statementDecision = cycleAssignment.decideCycle(reload('tx-bill'), cardAccount())
    expect(statementDecision.source).toBe('STATEMENT_IMPORT')
    expect(statementDecision.cycleId).toBe(reconciled.id)

    // 1. An explicit owner correction is final.
    const target = cycles.findBestForCompetence(CARD_ACCOUNT, '2026-08')!
    corrections.applyCorrection({
      pluggyTransactionId: 'tx-bill',
      field: 'statement_cycle',
      newValue: target.id,
      source: 'USER',
    })
    const userDecision = cycleAssignment.decideCycle(reload('tx-bill'), cardAccount())
    expect(userDecision.source).toBe('USER')
    expect(userDecision.cycleId).toBe(target.id)
  })

  it('fonte mais fraca não sobrescreve atribuição mais forte já registrada', () => {
    seedBill({ billId: 'bill-a', closingDate: '2026-08-05T00:00:00.000Z', dueDate: '2026-08-15T00:00:00.000Z' })
    seedBill({ billId: 'bill-b', closingDate: '2026-09-05T00:00:00.000Z', dueDate: '2026-09-15T00:00:00.000Z' })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)
    seedTransaction({ id: 'tx-weak', date: '2026-09-01T12:00:00.000Z' })

    const strong = cycles.findBestForCompetence(CARD_ACCOUNT, '2026-08')!
    const weakTarget = cycles.findBestForCompetence(CARD_ACCOUNT, '2026-09')!

    cycles.assignTransaction({
      pluggyTransactionId: 'tx-weak',
      statementCycleId: strong.id,
      source: 'USER',
      confidence: 1,
    })

    const rejected = cycles.assignTransaction({
      pluggyTransactionId: 'tx-weak',
      statementCycleId: weakTarget.id,
      source: 'RULE',
      confidence: 0.5,
    })
    expect(rejected.applied).toBe(false)
    expect(rejected.rejectedReason).toBe('weaker_source')
    expect(reload('tx-weak').statement_cycle_id).toBe(strong.id)

    // The full derivation pass must respect the same guard.
    const synced = cycleAssignment.syncTemporal(reload('tx-weak'), cardAccount())
    expect(synced.statementCycleId).toBe(strong.id)
  })

  it('transação atrasada em ciclo já reconciliado sinaliza DRIFT em vez de reescrever o fechamento', () => {
    const cycle = cycles.upsertCycle({
      financialAccountId: CARD_ACCOUNT,
      source: 'STATEMENT_IMPORT',
      competenceMonth: '2026-07',
      statementCurrency: 'BRL',
      periodStart: '2026-06-06T00:00:00.000Z',
      periodEnd: '2026-07-05T23:59:59.000Z',
      closingDate: '2026-07-05T00:00:00.000Z',
      dueDate: '2026-07-15T00:00:00.000Z',
      status: 'RECONCILED',
      reconciliationStatus: 'MATCHED',
      statementTotalCents: 100000,
    })
    seedTransaction({ id: 'tx-late', date: '2026-07-02T12:00:00.000Z' })

    const result = cycles.assignTransaction({
      pluggyTransactionId: 'tx-late',
      statementCycleId: cycle.id,
      source: 'STATEMENT_IMPORT',
    })
    expect(result.applied).toBe(true)
    expect(result.driftFlagged).toBe(true)

    const after = cycles.getById(cycle.id)!
    expect(after.reconciliation_status).toBe('DRIFT')
    // Closure itself is untouched: the divergence is surfaced, not absorbed.
    expect(after.statement_total_cents).toBe(100000)
    expect(after.status).toBe('RECONCILED')
  })
})

describe('semântica temporal: cada fato é um campo distinto', () => {
  it('compra, postagem, competência e caixa são meses diferentes para um cartão', () => {
    seedBill({ billId: 'bill-comp', closingDate: '2026-08-05T00:00:00.000Z', dueDate: '2026-09-10T00:00:00.000Z' })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)

    // Purchase in July, posted in August, statement closes in August, paid in September.
    seedTransaction({
      id: 'tx-temporal',
      date: '2026-08-02T12:00:00.000Z',
      cardMetadata: { purchaseDate: '2026-07-29T00:00:00.000Z', billId: 'bill-comp' },
    })
    cycleAssignment.syncTemporal(reload('tx-temporal'), cardAccount())

    const row = reload('tx-temporal')
    expect(row.date).toBe('2026-08-02T12:00:00.000Z')
    expect(row.posted_date).toBe('2026-08-02T12:00:00.000Z')
    expect(row.purchase_month).toBe('2026-07')
    expect(row.competence_month).toBe('2026-08')
    expect(row.cashflow_month).toBe('2026-09')
    expect(row.statement_cycle_id).not.toBeNull()

    // Four distinct answers to four distinct questions.
    expect(new Set([row.purchase_month, row.competence_month, row.cashflow_month]).size).toBe(3)
  })

  it('conta corrente: caixa sai na data da transação e não há ciclo', () => {
    seedTransaction({ id: 'tx-cash', accountId: CASH_ACCOUNT, date: '2026-08-20T12:00:00.000Z' })
    const account = accounts.getByPluggyId(CASH_ACCOUNT)!
    const result = cycleAssignment.syncTemporal(reload('tx-cash'), account)

    expect(result.decision.reason).toBe('not_credit_card')
    const row = reload('tx-cash')
    expect(row.purchase_month).toBe('2026-08')
    expect(row.competence_month).toBe('2026-08')
    expect(row.cashflow_month).toBe('2026-08')
    expect(row.statement_cycle_id).toBeNull()
  })

  it('cartão sem ciclo conhecido deixa cashflow_month NULL em vez de chutar o mês da compra', () => {
    seedTransaction({ id: 'tx-nocycle', date: '2026-08-20T12:00:00.000Z' })
    cycleAssignment.syncTemporal(reload('tx-nocycle'), cardAccount())

    const row = reload('tx-nocycle')
    expect(row.purchase_month).toBe('2026-08')
    expect(row.cashflow_month).toBeNull()
    expect(row.statement_cycle_id).toBeNull()
  })

  it('posted_date só é afirmado quando a fonte prova que difere da data da compra', () => {
    seedTransaction({ id: 'tx-samedate', date: '2026-08-20T12:00:00.000Z' })
    cycleAssignment.syncTemporal(reload('tx-samedate'), cardAccount())
    expect(reload('tx-samedate').posted_date).toBeNull()
  })

  it('correção de competência do dono vence o ciclo atribuído', () => {
    seedBill({ billId: 'bill-user', closingDate: '2026-08-05T00:00:00.000Z', dueDate: '2026-09-10T00:00:00.000Z' })
    cycleAssignment.ensureCyclesForAccount(CARD_ACCOUNT)
    seedTransaction({ id: 'tx-comp', date: '2026-08-02T12:00:00.000Z', cardMetadata: { billId: 'bill-user' } })
    cycleAssignment.syncTemporal(reload('tx-comp'), cardAccount())
    expect(reload('tx-comp').competence_month).toBe('2026-08')

    corrections.applyCorrection({
      pluggyTransactionId: 'tx-comp',
      field: 'competence_month',
      newValue: '2026-06',
      source: 'USER',
    })
    cycleAssignment.syncTemporal(reload('tx-comp'), cardAccount())

    const row = reload('tx-comp')
    expect(row.competence_month).toBe('2026-06')
    // The purchase month is a fact, not a preference: it is never rewritten by a competence correction.
    expect(row.purchase_month).toBe('2026-08')
    expect(effective.build(row, cardAccount()).temporal.competenceMonth.source).toBe('CORRECTION')
  })
})

describe('regras de merchant: SUGGEST vs TRUSTED', () => {
  it('regra nasce SUGGEST e não altera o efetivo — apenas sugere', () => {
    seedTransaction({ id: 'tx-sug', date: '2026-08-10T12:00:00.000Z', merchant: 'UBER TRIP', category: 'Transport' })
    const rule = merchantRules.upsertRule({
      merchantPattern: 'UBER TRIP',
      ruleType: 'CATEGORY',
      targetValue: 'Transporte',
    })
    expect(rule.mode).toBe('SUGGEST')

    const built = effective.build(reload('tx-sug'), cardAccount())
    expect(built.category.value).toBe('Transport')
    expect(built.category.source).toBe('SOURCE_METADATA')
    expect(built.suggestions).toContainEqual(
      expect.objectContaining({ ruleId: rule.id, value: 'Transporte', reason: 'suggest_mode' }),
    )
  })

  it('promoção explícita a TRUSTED passa a aplicar a regra', () => {
    seedTransaction({ id: 'tx-prom', date: '2026-08-10T12:00:00.000Z', merchant: 'UBER TRIP', category: 'Transport' })
    const rule = merchantRules.upsertRule({
      merchantPattern: 'UBER TRIP',
      ruleType: 'CATEGORY',
      targetValue: 'Transporte',
    })

    const promoted = merchantRules.promoteToTrusted(rule.id, { promotedBy: 'owner' })
    expect(promoted?.mode).toBe('TRUSTED')

    const built = effective.build(reload('tx-prom'), cardAccount())
    expect(built.category.value).toBe('Transporte')
    expect(built.category.source).toBe('TRUSTED_RULE')
    expect(built.suggestions.some(s => s.ruleId === rule.id)).toBe(false)
  })

  it('regra com escopo de conta vence regra global e duas TRUSTED no mesmo escopo viram conflito', () => {
    seedTransaction({ id: 'tx-scope', date: '2026-08-10T12:00:00.000Z', merchant: 'FARMACIA BOA' })

    const global = merchantRules.upsertRule({
      merchantPattern: 'FARMACIA BOA',
      ruleType: 'CATEGORY',
      targetValue: 'Saúde global',
    })
    const scoped = merchantRules.upsertRule({
      merchantPattern: 'FARMACIA BOA',
      ruleType: 'CATEGORY',
      targetValue: 'Saúde do cartão',
      scopeAccountId: CARD_ACCOUNT,
    })
    merchantRules.promoteToTrusted(global.id)
    merchantRules.promoteToTrusted(scoped.id)

    const built = effective.build(reload('tx-scope'), cardAccount())
    expect(built.category.value).toBe('Saúde do cartão')

    // Two TRUSTED rules at the SAME scope disagreeing is a conflict, never a silent pick.
    const rival = merchantRules.upsertRule({
      merchantPattern: 'farmacia boa',
      ruleType: 'ECONOMIC_OWNER',
      targetValue: 'perfil-a',
      matchKind: 'normalized',
    })
    const rival2 = merchantRules.upsertRule({
      merchantPattern: 'FARMACIA BOA',
      ruleType: 'ECONOMIC_OWNER',
      targetValue: 'perfil-b',
      matchKind: 'exact',
    })
    merchantRules.promoteToTrusted(rival.id)
    merchantRules.promoteToTrusted(rival2.id)

    const conflicted = effective.build(reload('tx-scope'), cardAccount())
    expect(conflicted.conflicts.length).toBeGreaterThan(0)
    expect(conflicted.economicOwner.value).toBeNull()
  })

  it('desativar uma regra a remove do efetivo sem apagar histórico de correções', () => {
    seedTransaction({ id: 'tx-off', date: '2026-08-10T12:00:00.000Z', merchant: 'LIVRARIA', category: 'Books' })
    const rule = merchantRules.upsertRule({
      merchantPattern: 'LIVRARIA',
      ruleType: 'CATEGORY',
      targetValue: 'Livros',
    })
    merchantRules.promoteToTrusted(rule.id)
    expect(effective.build(reload('tx-off'), cardAccount()).category.value).toBe('Livros')

    expect(merchantRules.deactivate(rule.id)).toBe(true)
    expect(effective.build(reload('tx-off'), cardAccount()).category.value).toBe('Books')
    expect(merchantRules.listActive().some(r => r.id === rule.id)).toBe(false)
  })
})
