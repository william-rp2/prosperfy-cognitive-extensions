import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import type { AccountsRepository } from '../finance/accountsRepository.js'
import {
  isCorrectionField,
  type CorrectionField,
  type CorrectionSource,
  type CorrectionsRepository,
  type FinancialCorrectionRow,
} from '../finance/correctionsRepository.js'
import type { CycleAssignmentService } from '../finance/cycleAssignmentService.js'
import type { EffectiveTransaction, EffectiveTransactionService } from '../finance/effectiveTransaction.js'
import {
  MATCH_KINDS,
  RULE_TYPES,
  type MerchantMatchKind,
  type MerchantRuleRow,
  type MerchantRuleType,
  type MerchantRulesRepository,
} from '../finance/merchantRulesRepository.js'
import type { StatementCyclesRepository } from '../finance/statementCyclesRepository.js'
import { isMonthKey, type TemporalTransactionRow } from '../finance/temporalSemantics.js'
import type { TransactionsRepository } from '../finance/transactionsRepository.js'
import { safeCompare } from '../safe.js'

/**
 * Correction + learned-rule surface (F2B, SUBAGENT_A).
 *
 * Registered as its own encapsulated Fastify scope so it can be wired next to
 * `registerFinanceRoutes` without either module editing the other.
 *
 * Two invariants this module enforces at the edge:
 *  1. Nothing here writes `raw_data`. A correction is an append-only ledger entry; the raw
 *     provider payload is never rewritten to hide an upstream error.
 *  2. A merchant rule is born SUGGEST. It becomes TRUSTED only through the explicit
 *     promote endpoint — never as a side effect of creating or updating it.
 */

export interface FinanceCorrectionRouteDeps {
  config: AppConfig
  transactions: TransactionsRepository
  accounts: AccountsRepository
  corrections: CorrectionsRepository
  merchantRules: MerchantRulesRepository
  cycles: StatementCyclesRepository
  cycleAssignment: CycleAssignmentService
  effective: EffectiveTransactionService
}

const AMOUNT_FIELDS = new Set<CorrectionField>(['amount', 'amount_in_account_currency'])
const ATTRIBUTION_FIELDS = new Set<CorrectionField>(['economic_owner', 'responsible', 'reimbursement'])
const TEMPORAL_FIELDS = new Set<CorrectionField>(['competence_month', 'statement_cycle'])
const CORRECTION_SOURCE_VALUES: readonly CorrectionSource[] = ['USER', 'RULE', 'STATEMENT_IMPORT', 'SYSTEM']

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

function serializeCorrection(row: FinancialCorrectionRow) {
  return {
    id: row.id,
    transactionId: row.pluggy_transaction_id,
    field: row.field,
    oldValue: row.old_effective_value,
    newValue: row.new_effective_value,
    reason: row.reason,
    source: row.source,
    actorId: row.actor_id,
    createdAt: row.created_at,
    supersededAt: row.superseded_at,
    active: row.superseded_at === null,
  }
}

function serializeRule(row: MerchantRuleRow) {
  return {
    id: row.id,
    merchantPattern: row.merchant_pattern,
    matchKind: row.match_kind,
    scopeAccountId: row.scope_account_id,
    ruleType: row.rule_type,
    targetValue: row.target_value,
    mode: row.mode,
    active: row.active === 1,
    createdBy: row.created_by,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    evidence: row.evidence_json ? (JSON.parse(row.evidence_json) as unknown) : null,
  }
}

function serializeEffective(effective: EffectiveTransaction) {
  return {
    id: effective.pluggyTransactionId,
    accountId: effective.pluggyAccountId,
    raw: effective.raw,
    effective: {
      amountCents: effective.amountCents,
      currencyCode: effective.currencyCode,
      amountInAccountCurrencyCents: effective.amountInAccountCurrencyCents,
      accountCurrencyCode: effective.accountCurrencyCode,
      accountAmountCents: effective.accountAmountCents,
      currencyConversionMissing: effective.currencyConversionMissing,
      category: effective.category,
      merchant: effective.merchant,
      economicOwner: effective.economicOwner,
      responsible: effective.responsible,
      reimbursement: effective.reimbursement,
      notes: effective.notes,
    },
    temporal: effective.temporal,
    suggestions: effective.suggestions,
    conflicts: effective.conflicts,
    discrepancies: effective.discrepancies,
  }
}

/** Current effective value of a field, in the canonical string form the ledger stores. */
function effectiveValueAsString(effective: EffectiveTransaction, field: CorrectionField): string | null {
  switch (field) {
    case 'amount':
      return String(effective.amountCents.value)
    case 'amount_in_account_currency':
      return effective.amountInAccountCurrencyCents.value == null
        ? null
        : String(effective.amountInAccountCurrencyCents.value)
    case 'currency':
      return effective.currencyCode.value
    case 'category':
      return effective.category.value
    case 'merchant':
      return effective.merchant.value
    case 'economic_owner':
      return effective.economicOwner.value
    case 'responsible':
      return effective.responsible.value
    case 'reimbursement':
      return effective.reimbursement.value ? JSON.stringify(effective.reimbursement.value) : null
    case 'competence_month':
      return effective.temporal.competenceMonth.value
    case 'statement_cycle':
      return effective.temporal.statementCycleId
    case 'notes':
      return effective.notes.value
    default:
      return null
  }
}

interface ValueValidation {
  ok: boolean
  value?: string | null
  error?: string
  message?: string
}

/** Money is INTEGER cents, months are 'YYYY-MM', a cycle must exist. No silent coercion. */
function normalizeCorrectionValue(
  field: CorrectionField,
  raw: unknown,
  cycles: StatementCyclesRepository,
): ValueValidation {
  if (raw === null) return { ok: true, value: null }

  if (AMOUNT_FIELDS.has(field)) {
    const numeric = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN
    if (!Number.isInteger(numeric)) {
      return {
        ok: false,
        error: 'invalid_amount',
        message: 'Informe o valor em centavos inteiros (ex.: 500 para R$ 5,00).',
      }
    }
    return { ok: true, value: String(numeric) }
  }

  if (field === 'competence_month') {
    if (!isMonthKey(raw)) {
      return { ok: false, error: 'invalid_month', message: 'Mês de competência inválido: use o formato AAAA-MM.' }
    }
    return { ok: true, value: raw }
  }

  if (field === 'statement_cycle') {
    if (typeof raw !== 'string' || !raw.trim()) {
      return { ok: false, error: 'invalid_cycle', message: 'Informe o identificador da fatura.' }
    }
    if (!cycles.getById(raw.trim())) {
      return { ok: false, error: 'cycle_not_found', message: 'Fatura não encontrada.' }
    }
    return { ok: true, value: raw.trim() }
  }

  if (field === 'reimbursement') {
    if (typeof raw === 'object') return { ok: true, value: JSON.stringify(raw) }
    if (typeof raw === 'string' && raw.trim()) return { ok: true, value: raw.trim() }
    return {
      ok: false,
      error: 'invalid_reimbursement',
      message: 'Informe um objeto com paidBy, receivableFrom e status.',
    }
  }

  if (typeof raw !== 'string' || !raw.trim()) {
    return { ok: false, error: 'invalid_value', message: 'Informe um valor de texto não vazio.' }
  }
  return { ok: true, value: raw.trim() }
}

export function registerFinanceCorrectionRoutes(app: FastifyInstance, deps: FinanceCorrectionRouteDeps): void {
  const { config, transactions, accounts, corrections, merchantRules, cycles, cycleAssignment, effective } = deps

  const loadRow = (transactionId: string): TemporalTransactionRow | undefined =>
    transactions.getByPluggyId(transactionId) as TemporalTransactionRow | undefined

  const buildEffective = (row: TemporalTransactionRow): EffectiveTransaction =>
    effective.build(row, accounts.getByPluggyId(row.pluggy_account_id) ?? null)

  void app.register(async correctionApp => {
    correctionApp.addHook('preHandler', async (request, reply) => {
      if (!requireFinanceToken(request, config)) {
        return reply.code(401).send({
          error: 'unauthorized',
          message: 'FINANCE_API_TOKEN ausente ou inválido no header Authorization: Bearer <token>.',
        })
      }
    })

    /** Effective view: raw beside the corrections and rules that produced it. */
    correctionApp.get('/api/finance/transactions/:transactionId/effective', async (request, reply) => {
      const { transactionId } = request.params as { transactionId: string }
      const row = loadRow(transactionId)
      if (!row) {
        return reply.code(404).send({ error: 'transaction_not_found', message: 'Transação não encontrada.' })
      }
      return serializeEffective(buildEffective(row))
    })

    /** Full auditable ledger for a transaction — superseded entries included, oldest first. */
    correctionApp.get('/api/finance/corrections/:transactionId', async (request, reply) => {
      const { transactionId } = request.params as { transactionId: string }
      const row = loadRow(transactionId)
      if (!row) {
        return reply.code(404).send({ error: 'transaction_not_found', message: 'Transação não encontrada.' })
      }
      const history = corrections.listHistory(transactionId)
      return {
        transactionId,
        history: history.map(serializeCorrection),
        active: [...corrections.listActive(transactionId).values()].map(serializeCorrection),
        effective: serializeEffective(buildEffective(row)),
      }
    })

    correctionApp.post('/api/finance/corrections', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>
      // The apply route has no path param (adapters/finance_api/client.py routes
      // finance.correction.apply to POST /api/finance/corrections), so the target
      // transaction is named in the body.
      const transactionId = typeof body.transactionId === 'string' ? body.transactionId : ''
      if (!transactionId) {
        return reply
          .code(400)
          .send({ error: 'invalid_transaction_id', message: 'transactionId é obrigatório no corpo.' })
      }

      const row = loadRow(transactionId)
      if (!row) {
        return reply.code(404).send({ error: 'transaction_not_found', message: 'Transação não encontrada.' })
      }
      if (!isCorrectionField(body.field)) {
        return reply
          .code(400)
          .send({ error: 'invalid_field', message: 'Campo de correção não suportado.' })
      }
      const field = body.field

      const source = body.source === undefined ? 'USER' : (body.source as CorrectionSource)
      if (!CORRECTION_SOURCE_VALUES.includes(source)) {
        return reply.code(400).send({ error: 'invalid_source', message: 'Origem de correção não suportada.' })
      }

      const validated = normalizeCorrectionValue(field, body.value ?? null, cycles)
      if (!validated.ok) {
        return reply.code(400).send({ error: validated.error, message: validated.message })
      }

      // Old effective value is captured BEFORE the write, so the ledger records what the owner
      // was actually looking at when they decided to correct it.
      const oldValue = effectiveValueAsString(buildEffective(row), field)

      const correction = corrections.applyCorrection({
        pluggyTransactionId: transactionId,
        field,
        newValue: validated.value ?? null,
        oldValue,
        reason: typeof body.reason === 'string' ? body.reason : null,
        source,
        actorId: typeof body.actorId === 'string' ? body.actorId : null,
      })

      if (ATTRIBUTION_FIELDS.has(field)) corrections.projectAttribution(transactionId)
      if (TEMPORAL_FIELDS.has(field)) cycleAssignment.syncTemporal(loadRow(transactionId)!)

      return reply.code(201).send({
        correction: serializeCorrection(correction),
        effective: serializeEffective(buildEffective(loadRow(transactionId)!)),
      })
    })

    /**
     * Withdraw a correction. The ledger row is superseded, never deleted, and the effective view
     * falls back to the layer underneath it.
     */
    correctionApp.delete('/api/finance/corrections/:transactionId/:field', async (request, reply) => {
      const { transactionId, field } = request.params as { transactionId: string; field: string }
      const row = loadRow(transactionId)
      if (!row) {
        return reply.code(404).send({ error: 'transaction_not_found', message: 'Transação não encontrada.' })
      }
      if (!isCorrectionField(field)) {
        return reply.code(400).send({ error: 'invalid_field', message: 'Campo de correção não suportado.' })
      }
      const reverted = corrections.revertCorrection(transactionId, field)
      if (!reverted) {
        return reply
          .code(404)
          .send({ error: 'correction_not_found', message: 'Não há correção ativa para esse campo.' })
      }

      if (ATTRIBUTION_FIELDS.has(field)) corrections.projectAttribution(transactionId)
      if (TEMPORAL_FIELDS.has(field)) cycleAssignment.syncTemporal(loadRow(transactionId)!)

      return {
        reverted: true,
        effective: serializeEffective(buildEffective(loadRow(transactionId)!)),
      }
    })

    correctionApp.get('/api/finance/rules', async request => {
      const query = (request.query ?? {}) as Record<string, unknown>
      const ruleType =
        typeof query.ruleType === 'string' && (RULE_TYPES as readonly string[]).includes(query.ruleType)
          ? (query.ruleType as MerchantRuleType)
          : undefined
      return { rules: merchantRules.listActive(ruleType).map(serializeRule) }
    })

    /**
     * Create or update a learned rule. Always SUGGEST: a rule that starts deterministic would let
     * one guess silently rewrite every future transaction of a merchant.
     */
    correctionApp.post('/api/finance/rules', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>

      if (body.mode === 'TRUSTED') {
        return reply.code(400).send({
          error: 'trusted_requires_promotion',
          message: 'Uma regra nasce como sugestão. Promova a confiável em POST /api/finance/rules/:id/promote.',
        })
      }

      const merchantPattern = typeof body.merchantPattern === 'string' ? body.merchantPattern.trim() : ''
      if (!merchantPattern) {
        return reply
          .code(400)
          .send({ error: 'invalid_pattern', message: 'Informe o padrão do estabelecimento.' })
      }
      if (typeof body.ruleType !== 'string' || !(RULE_TYPES as readonly string[]).includes(body.ruleType)) {
        return reply.code(400).send({ error: 'invalid_rule_type', message: 'Tipo de regra não suportado.' })
      }
      const targetValue = typeof body.targetValue === 'string' ? body.targetValue.trim() : ''
      if (!targetValue) {
        return reply.code(400).send({ error: 'invalid_target', message: 'Informe o valor alvo da regra.' })
      }
      if (body.matchKind !== undefined && !(MATCH_KINDS as readonly string[]).includes(String(body.matchKind))) {
        return reply.code(400).send({ error: 'invalid_match_kind', message: 'Tipo de correspondência não suportado.' })
      }
      const scopeAccountId = typeof body.scopeAccountId === 'string' ? body.scopeAccountId.trim() : null
      if (scopeAccountId && !accounts.getByPluggyId(scopeAccountId)) {
        return reply.code(404).send({ error: 'account_not_found', message: 'Conta do escopo não encontrada.' })
      }

      const rule = merchantRules.upsertRule({
        merchantPattern,
        matchKind: body.matchKind as MerchantMatchKind | undefined,
        scopeAccountId,
        ruleType: body.ruleType as MerchantRuleType,
        targetValue,
        mode: 'SUGGEST',
        createdBy: typeof body.createdBy === 'string' ? body.createdBy : null,
        evidence: body.evidence,
      })
      return reply.code(201).send({ rule: serializeRule(rule) })
    })

    /** Explicit owner promotion — the only path from SUGGEST to TRUSTED. */
    correctionApp.post('/api/finance/rules/:ruleId/promote', async (request, reply) => {
      const { ruleId } = request.params as { ruleId: string }
      const body = (request.body ?? {}) as Record<string, unknown>
      const existing = merchantRules.getById(ruleId)
      if (!existing || existing.active !== 1) {
        return reply.code(404).send({ error: 'rule_not_found', message: 'Regra não encontrada.' })
      }
      const promoted = merchantRules.promoteToTrusted(ruleId, {
        promotedBy: typeof body.actorId === 'string' ? body.actorId : null,
        promotedAt: new Date().toISOString(),
        evidence: body.evidence ?? null,
      })
      return { rule: serializeRule(promoted!) }
    })

    correctionApp.delete('/api/finance/rules/:ruleId', async (request, reply) => {
      const { ruleId } = request.params as { ruleId: string }
      if (!merchantRules.deactivate(ruleId)) {
        return reply.code(404).send({ error: 'rule_not_found', message: 'Regra não encontrada.' })
      }
      return { deactivated: true }
    })
  })
}
