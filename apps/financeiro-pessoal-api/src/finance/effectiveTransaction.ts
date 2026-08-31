import type { CorrectionField, CorrectionsRepository, FinancialCorrectionRow } from './correctionsRepository.js'
import { extractCardMetadata } from './cycleAssignmentService.js'
import type { EnrichmentRepository, EnrichmentRow } from './enrichmentRepository.js'
import type {
  MerchantRuleType,
  MerchantRulesRepository,
  MerchantMatchCandidate,
  ResolvedRule,
  RuleConflict,
} from './merchantRulesRepository.js'
import type { StatementCycleRow, StatementCyclesRepository } from './statementCyclesRepository.js'
import {
  deriveCashflowMonth,
  derivePurchaseMonth,
  isCreditCardAccount,
  isMonthKey,
  type MonthKey,
  type TemporalTransactionRow,
} from './temporalSemantics.js'
import { effectiveAccountAmountCents, isCurrencyConversionMissing } from './transactionAmount.js'
import type { FinancialAccountRow } from './types.js'

/**
 * The effective view of a transaction, derived at READ TIME.
 *
 *   RAW -> NORMALIZED -> CORRECTION / RULE -> EFFECTIVE
 *
 * Nothing in this module writes. `financial_transactions.raw_data` is what the provider sent and
 * stays that way forever: an upstream error is corrected in the ledger and shown as a correction,
 * never rewritten to pretend the provider got it right.
 *
 * Field precedence:
 *
 *   explicit transaction correction
 *   > owner TRUSTED scoped rule
 *   > deterministic source metadata
 *   > SUGGEST rule (surfaced, never applied)
 *   > classifier/LLM inference
 */

export type EffectiveSource =
  /** Explicit correction from the append-only ledger. */
  | 'CORRECTION'
  /** Owner-promoted merchant rule. */
  | 'TRUSTED_RULE'
  /** Owner statement recorded as manual enrichment before the ledger existed. */
  | 'OWNER_ENRICHMENT'
  /** Deterministic fact from the provider payload. */
  | 'SOURCE_METADATA'
  /** Domain truth about which fatura the purchase landed on. */
  | 'STATEMENT_CYCLE'
  /** Classifier / LLM guess. */
  | 'INFERENCE'
  /** Untouched raw value. */
  | 'RAW'
  /** Documented default policy, not evidence. */
  | 'DEFAULT'
  | 'NONE'

export interface Resolved<T> {
  value: T
  source: EffectiveSource
  correctionId?: string
  ruleId?: string
  /** Where the value came from, in words, for audit surfaces. */
  detail?: string
}

/** A learned rule that matched but was NOT applied. Surfaced to the owner, never auto-applied. */
export interface EffectiveSuggestion {
  ruleType: MerchantRuleType
  value: string
  ruleId: string
  matchedField: string
  matchedValue: string
  reason: 'suggest_mode' | 'outranked_by_correction' | 'currency_conflicts_with_source'
}

/** A TRUSTED rule disagreeing with a reliable upstream fact. Reported, never silently resolved. */
export interface EffectiveDiscrepancy {
  field: CorrectionField
  sourceValue: string | null
  ruleValue: string
  ruleId: string
  message: string
}

export interface EffectiveReimbursement {
  paidBy: string | null
  receivableFrom: string | null
  receivableStatus: string | null
}

export interface EffectiveTemporal {
  /** Source transaction date exactly as stored. Never corrected away. */
  transactionDate: string
  /** Original purchase date when the source distinguishes it from the posting date. */
  purchaseDate: string | null
  postedDate: string | null
  purchaseMonth: MonthKey | null
  competenceMonth: Resolved<MonthKey | null>
  cashflowMonth: MonthKey | null
  statementCycleId: string | null
  cycleAssignmentSource: string | null
  cycleAssignmentConfidence: number | null
  cycleCompetenceMonth: MonthKey | null
  cycleLabel: string | null
}

export interface EffectiveTransaction {
  pluggyTransactionId: string
  pluggyAccountId: string
  /** Exactly what upstream said. Present so a UI can show raw beside effective. */
  raw: {
    amountCents: number
    currencyCode: string | null
    amountInAccountCurrencyCents: number | null
    accountCurrencyCode: string | null
    date: string
    categoryOriginal: string | null
    merchantOriginal: string | null
  }
  amountCents: Resolved<number>
  currencyCode: Resolved<string | null>
  amountInAccountCurrencyCents: Resolved<number | null>
  accountCurrencyCode: string | null
  /**
   * Absolute amount in the account's base currency, for aggregation. NULL when a foreign-currency
   * transaction has no conversion: fail-closed, an unknown amount is excluded, never zeroed.
   */
  accountAmountCents: number | null
  currencyConversionMissing: boolean
  category: Resolved<string | null>
  merchant: Resolved<string | null>
  economicOwner: Resolved<string | null>
  responsible: Resolved<string | null>
  reimbursement: Resolved<EffectiveReimbursement | null>
  notes: Resolved<string | null>
  temporal: EffectiveTemporal
  suggestions: EffectiveSuggestion[]
  conflicts: RuleConflict[]
  discrepancies: EffectiveDiscrepancy[]
}

/** Columns added by migration 010 to `financial_transaction_enrichment`. */
export interface AttributionEnrichmentColumns {
  /** Present since migration 001 but absent from `EnrichmentRow`, which never surfaced it. */
  responsible?: string | null
  economic_owner?: string | null
  paid_by?: string | null
  receivable_from?: string | null
  receivable_status?: string | null
}

export type AttributionEnrichmentRow = EnrichmentRow & AttributionEnrichmentColumns

export interface EffectiveTransactionDeps {
  corrections: CorrectionsRepository
  merchantRules: MerchantRulesRepository
  cycles: StatementCyclesRepository
  enrichment: EnrichmentRepository
}

/** Enrichment written by an explicit human decision, as opposed to a classifier guess. */
function isOwnerAuthoredEnrichment(row: AttributionEnrichmentRow | undefined): boolean {
  return row?.classification_source === 'manual'
}

function parseIntegerCents(value: string | null | undefined): number | null {
  if (value == null || value.trim() === '') return null
  const parsed = Number(value)
  return Number.isInteger(parsed) ? parsed : null
}

export function parseReimbursementValue(value: string | null | undefined): EffectiveReimbursement | null {
  if (!value?.trim()) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  const data = parsed as Record<string, unknown>
  const str = (key: string): string | null => (typeof data[key] === 'string' && data[key] ? (data[key] as string) : null)
  return {
    paidBy: str('paidBy'),
    receivableFrom: str('receivableFrom'),
    receivableStatus: str('status') ?? str('receivableStatus'),
  }
}

function none<T>(value: T): Resolved<T> {
  return { value, source: 'NONE' }
}

export class EffectiveTransactionService {
  constructor(private readonly deps: EffectiveTransactionDeps) {}

  buildMany(
    rows: readonly TemporalTransactionRow[],
    account?: FinancialAccountRow | null,
  ): EffectiveTransaction[] {
    return rows.map(row => this.build(row, account))
  }

  build(row: TemporalTransactionRow, account?: FinancialAccountRow | null): EffectiveTransaction {
    const corrections = this.deps.corrections.listActive(row.pluggy_transaction_id)
    const enrichment = this.deps.enrichment.getByTransactionId(row.pluggy_transaction_id) as
      | AttributionEnrichmentRow
      | undefined

    const candidate: MerchantMatchCandidate = {
      merchantOriginal: row.merchant_original,
      merchantNormalized: enrichment?.merchant_normalized ?? null,
      description: row.description ?? row.description_raw,
      pluggyAccountId: row.pluggy_account_id,
    }
    const resolution = this.deps.merchantRules.resolveRules(candidate)
    const trustedByType = new Map<MerchantRuleType, ResolvedRule>(
      resolution.trusted.map(rule => [rule.ruleType, rule]),
    )

    const suggestions: EffectiveSuggestion[] = resolution.suggested.map(rule => ({
      ruleType: rule.ruleType,
      value: rule.value,
      ruleId: rule.ruleId,
      matchedField: rule.evidence.matchedField,
      matchedValue: rule.evidence.matchedValue,
      reason: 'suggest_mode' as const,
    }))
    const discrepancies: EffectiveDiscrepancy[] = []

    const cycle = row.statement_cycle_id ? this.deps.cycles.getById(row.statement_cycle_id) : undefined
    const isCreditCard = isCreditCardAccount(account)

    const amountCents = this.resolveAmount(corrections, row)
    const currencyCode = this.resolveCurrency(corrections, row, trustedByType, suggestions, discrepancies)
    const amountInAccountCurrencyCents = this.resolveAccountAmount(corrections, row)

    const effectiveAmountFields = {
      amount_cents: amountCents.value,
      currency_code: currencyCode.value,
      amount_in_account_currency_cents: amountInAccountCurrencyCents.value,
      account_currency_code: row.account_currency_code,
    }

    return {
      pluggyTransactionId: row.pluggy_transaction_id,
      pluggyAccountId: row.pluggy_account_id,
      raw: {
        amountCents: row.amount_cents,
        currencyCode: row.currency_code,
        amountInAccountCurrencyCents: row.amount_in_account_currency_cents,
        accountCurrencyCode: row.account_currency_code,
        date: row.date,
        categoryOriginal: row.category_original,
        merchantOriginal: row.merchant_original,
      },
      amountCents,
      currencyCode,
      amountInAccountCurrencyCents,
      accountCurrencyCode: row.account_currency_code,
      accountAmountCents: effectiveAccountAmountCents(effectiveAmountFields),
      currencyConversionMissing: isCurrencyConversionMissing(effectiveAmountFields),
      category: this.resolveCategory(corrections, row, enrichment, trustedByType, suggestions),
      merchant: this.resolveMerchant(corrections, row, enrichment),
      economicOwner: this.resolveAttribution(
        corrections,
        'economic_owner',
        trustedByType.get('ECONOMIC_OWNER'),
        enrichment?.economic_owner ?? null,
        suggestions,
      ),
      responsible: this.resolveAttribution(
        corrections,
        'responsible',
        trustedByType.get('RESPONSIBLE'),
        enrichment?.responsible ?? null,
        suggestions,
      ),
      reimbursement: this.resolveReimbursement(corrections, enrichment, trustedByType, suggestions),
      notes: this.resolveNotes(corrections, enrichment),
      temporal: this.resolveTemporal(corrections, row, cycle, isCreditCard),
      suggestions,
      conflicts: resolution.conflicts,
      discrepancies,
    }
  }

  private resolveAmount(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
  ): Resolved<number> {
    const correction = corrections.get('amount')
    const corrected = parseIntegerCents(correction?.new_effective_value)
    if (correction && corrected != null) {
      return { value: corrected, source: 'CORRECTION', correctionId: correction.id, detail: 'correção do dono' }
    }
    return { value: row.amount_cents, source: 'RAW' }
  }

  private resolveAccountAmount(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
  ): Resolved<number | null> {
    const correction = corrections.get('amount_in_account_currency')
    const corrected = parseIntegerCents(correction?.new_effective_value)
    if (correction && corrected != null) {
      return { value: corrected, source: 'CORRECTION', correctionId: correction.id }
    }
    return { value: row.amount_in_account_currency_cents, source: 'RAW' }
  }

  /**
   * Currency is the one field where a TRUSTED rule does NOT override the provider.
   *
   * "This merchant is usually USD" is not proof that this charge is USD. When upstream states a
   * currency and a learned rule disagrees, the disagreement is reported and the source value is
   * kept — surfacing the discrepancy instead of blindly overriding money semantics. The rule still
   * applies when upstream said nothing at all.
   */
  private resolveCurrency(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
    trusted: Map<MerchantRuleType, ResolvedRule>,
    suggestions: EffectiveSuggestion[],
    discrepancies: EffectiveDiscrepancy[],
  ): Resolved<string | null> {
    const correction = corrections.get('currency')
    if (correction?.new_effective_value) {
      return { value: correction.new_effective_value, source: 'CORRECTION', correctionId: correction.id }
    }

    const rule = trusted.get('CURRENCY_HINT')
    const sourceCurrency = row.currency_code

    if (rule) {
      if (!sourceCurrency) {
        return { value: rule.value, source: 'TRUSTED_RULE', ruleId: rule.ruleId }
      }
      if (sourceCurrency.toUpperCase() !== rule.value.toUpperCase()) {
        discrepancies.push({
          field: 'currency',
          sourceValue: sourceCurrency,
          ruleValue: rule.value,
          ruleId: rule.ruleId,
          message: `A instituição informou ${sourceCurrency} e a regra aprendida diz ${rule.value}. Confirme qual vale.`,
        })
        suggestions.push({
          ruleType: 'CURRENCY_HINT',
          value: rule.value,
          ruleId: rule.ruleId,
          matchedField: rule.evidence.matchedField,
          matchedValue: rule.evidence.matchedValue,
          reason: 'currency_conflicts_with_source',
        })
      }
    }

    if (sourceCurrency) return { value: sourceCurrency, source: 'SOURCE_METADATA' }
    return none(null)
  }

  private resolveCategory(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
    enrichment: AttributionEnrichmentRow | undefined,
    trusted: Map<MerchantRuleType, ResolvedRule>,
    suggestions: EffectiveSuggestion[],
  ): Resolved<string | null> {
    const correction = corrections.get('category')
    if (correction?.new_effective_value) {
      const rule = trusted.get('CATEGORY')
      if (rule && rule.value !== correction.new_effective_value) {
        suggestions.push({
          ruleType: 'CATEGORY',
          value: rule.value,
          ruleId: rule.ruleId,
          matchedField: rule.evidence.matchedField,
          matchedValue: rule.evidence.matchedValue,
          reason: 'outranked_by_correction',
        })
      }
      return { value: correction.new_effective_value, source: 'CORRECTION', correctionId: correction.id }
    }

    const rule = trusted.get('CATEGORY')
    if (rule) return { value: rule.value, source: 'TRUSTED_RULE', ruleId: rule.ruleId }

    if (isOwnerAuthoredEnrichment(enrichment) && enrichment?.category_name) {
      return { value: enrichment.category_name, source: 'OWNER_ENRICHMENT' }
    }
    if (row.category_original) return { value: row.category_original, source: 'SOURCE_METADATA' }
    if (enrichment?.category_name) return { value: enrichment.category_name, source: 'INFERENCE' }
    return none(null)
  }

  private resolveMerchant(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
    enrichment: AttributionEnrichmentRow | undefined,
  ): Resolved<string | null> {
    const correction = corrections.get('merchant')
    if (correction?.new_effective_value) {
      return { value: correction.new_effective_value, source: 'CORRECTION', correctionId: correction.id }
    }
    if (row.merchant_original) return { value: row.merchant_original, source: 'SOURCE_METADATA' }
    if (enrichment?.merchant_normalized) return { value: enrichment.merchant_normalized, source: 'INFERENCE' }
    return none(null)
  }

  /**
   * Owner / responsible attribution.
   *
   * There is deliberately no fallback to the account holder's name: card-level upstream identity
   * is absent for consolidated accounts, and inferring who made a purchase from who owns the
   * account fabricates attribution.
   */
  private resolveAttribution(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    field: Extract<CorrectionField, 'economic_owner' | 'responsible'>,
    trustedRule: ResolvedRule | undefined,
    enrichmentValue: string | null,
    suggestions: EffectiveSuggestion[],
  ): Resolved<string | null> {
    const correction = corrections.get(field)
    if (correction?.new_effective_value) {
      if (trustedRule && trustedRule.value !== correction.new_effective_value) {
        suggestions.push({
          ruleType: trustedRule.ruleType,
          value: trustedRule.value,
          ruleId: trustedRule.ruleId,
          matchedField: trustedRule.evidence.matchedField,
          matchedValue: trustedRule.evidence.matchedValue,
          reason: 'outranked_by_correction',
        })
      }
      return { value: correction.new_effective_value, source: 'CORRECTION', correctionId: correction.id }
    }
    if (trustedRule) return { value: trustedRule.value, source: 'TRUSTED_RULE', ruleId: trustedRule.ruleId }
    if (enrichmentValue) return { value: enrichmentValue, source: 'OWNER_ENRICHMENT' }
    return none(null)
  }

  private resolveReimbursement(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    enrichment: AttributionEnrichmentRow | undefined,
    trusted: Map<MerchantRuleType, ResolvedRule>,
    suggestions: EffectiveSuggestion[],
  ): Resolved<EffectiveReimbursement | null> {
    const correction = corrections.get('reimbursement')
    const parsed = parseReimbursementValue(correction?.new_effective_value)
    if (correction && parsed) {
      return { value: parsed, source: 'CORRECTION', correctionId: correction.id }
    }

    const rule = trusted.get('REIMBURSEMENT')
    if (rule) {
      const fromRule = parseReimbursementValue(rule.value)
      if (fromRule) return { value: fromRule, source: 'TRUSTED_RULE', ruleId: rule.ruleId }
      suggestions.push({
        ruleType: 'REIMBURSEMENT',
        value: rule.value,
        ruleId: rule.ruleId,
        matchedField: rule.evidence.matchedField,
        matchedValue: rule.evidence.matchedValue,
        reason: 'suggest_mode',
      })
    }

    if (enrichment?.receivable_from || enrichment?.receivable_status || enrichment?.paid_by) {
      return {
        value: {
          paidBy: enrichment.paid_by ?? null,
          receivableFrom: enrichment.receivable_from ?? null,
          receivableStatus: enrichment.receivable_status ?? null,
        },
        source: 'OWNER_ENRICHMENT',
      }
    }
    return none(null)
  }

  private resolveNotes(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    enrichment: AttributionEnrichmentRow | undefined,
  ): Resolved<string | null> {
    const correction = corrections.get('notes')
    if (correction?.new_effective_value) {
      return { value: correction.new_effective_value, source: 'CORRECTION', correctionId: correction.id }
    }
    if (enrichment?.notes) return { value: enrichment.notes, source: 'OWNER_ENRICHMENT' }
    return none(null)
  }

  /**
   * Six distinct temporal facts, never collapsed.
   *
   * competence precedence: owner correction > assigned statement cycle > purchase month default.
   * A COMPETENCE merchant rule is intentionally NOT applied here: a merchant-level rule cannot
   * assert an absolute month for every future transaction, so it stays a suggestion.
   */
  private resolveTemporal(
    corrections: Map<CorrectionField, FinancialCorrectionRow>,
    row: TemporalTransactionRow,
    cycle: StatementCycleRow | undefined,
    isCreditCard: boolean,
  ): EffectiveTemporal {
    // Read straight from the immutable raw payload — the purchase date is a source fact we expose,
    // never a column we overwrite `date` with.
    const purchaseDate = extractCardMetadata(row.raw_data).purchaseDate
    const purchaseMonth = row.purchase_month ?? derivePurchaseMonth(purchaseDate ?? row.date)

    let competenceMonth: Resolved<MonthKey | null>
    const correction = corrections.get('competence_month')
    if (correction && isMonthKey(correction.new_effective_value)) {
      competenceMonth = {
        value: correction.new_effective_value,
        source: 'CORRECTION',
        correctionId: correction.id,
      }
    } else if (isCreditCard && cycle && isMonthKey(cycle.competence_month)) {
      competenceMonth = { value: cycle.competence_month, source: 'STATEMENT_CYCLE', detail: cycle.cycle_label }
    } else {
      competenceMonth = { value: row.competence_month ?? purchaseMonth, source: 'DEFAULT', detail: 'mês da compra' }
    }

    return {
      transactionDate: row.date,
      // With a posted_date recorded, `date` is the posting instant and the purchase date is the
      // one the source gave separately; it is exposed from raw, never persisted over `date`.
      purchaseDate,
      postedDate: row.posted_date ?? null,
      purchaseMonth,
      competenceMonth,
      cashflowMonth:
        row.cashflow_month ??
        deriveCashflowMonth({
          transactionDate: row.date,
          isCreditCard,
          assignedCycleDueDate: cycle?.due_date ?? null,
        }),
      statementCycleId: row.statement_cycle_id ?? null,
      cycleAssignmentSource: row.cycle_assignment_source ?? null,
      cycleAssignmentConfidence: row.cycle_assignment_confidence ?? null,
      cycleCompetenceMonth: cycle?.competence_month ?? null,
      cycleLabel: cycle?.cycle_label ?? null,
    }
  }
}
