import type { AccountsRepository } from './accountsRepository.js'
import type { CorrectionsRepository } from './correctionsRepository.js'
import type { FinanceDb } from './db.js'
import type {
  CycleAssignmentSource,
  StatementCycleRow,
  StatementCyclesRepository,
} from './statementCyclesRepository.js'
import {
  deriveCashflowMonth,
  deriveCompetenceMonth,
  derivePurchaseMonth,
  isCreditCardAccount,
  isMonthKey,
  monthKeyFromDate,
  type MonthKey,
  type TemporalTransactionRow,
} from './temporalSemantics.js'
import type { FinancialAccountRow, FinancialCreditCardBillRow } from './types.js'

/**
 * Cycle assignment + temporal field derivation.
 *
 * Assignment precedence (never collapsed, never silently downgraded):
 *
 *   USER
 *   > trusted statement reconciliation
 *   > explicit upstream bill identity
 *   > deterministic date/cycle rule
 *   > inference
 *
 * The last tier is deliberately empty: when no evidence exists the transaction keeps a NULL
 * cycle. Inventing a fatura from nothing is worse than admitting we do not know which one it is.
 *
 * The six temporal facts stay separate at all times:
 * `date` (source), `posted_date`, `purchase_month`, `competence_month`, `statement_cycle_id`,
 * `cashflow_month`. Nothing here writes a generic "month".
 */

export type CycleDecisionReason =
  | 'user_correction'
  | 'reconciled_statement'
  | 'upstream_bill'
  | 'bill_forecast'
  | 'cycle_window'
  | 'no_evidence'
  | 'not_credit_card'

export interface CycleDecision {
  cycleId: string | null
  source: CycleAssignmentSource | null
  confidence: number | null
  reason: CycleDecisionReason
}

export interface TemporalSyncResult {
  pluggyTransactionId: string
  postedDate: string | null
  purchaseMonth: MonthKey | null
  competenceMonth: MonthKey | null
  cashflowMonth: MonthKey | null
  statementCycleId: string | null
  decision: CycleDecision
  /** True when a weaker source tried to overwrite a stronger existing assignment. */
  assignmentRejected: boolean
  /** True when the assignment landed on an already-RECONCILED cycle; closure was NOT rewritten. */
  driftFlagged: boolean
}

export interface CycleAssignmentDeps {
  db: FinanceDb
  accounts: AccountsRepository
  cycles: StatementCyclesRepository
  corrections: CorrectionsRepository
}

/** Credit-card facts Pluggy exposes inside the immutable raw payload. Read-only, always. */
export interface RawCardMetadata {
  /** Original purchase date — distinct from the posting date the provider returns as `date`. */
  purchaseDate: string | null
  /** Explicit upstream bill identity. The strongest non-owner evidence we can get. */
  billId: string | null
  /** Forecast bill period ('YYYY-MM'), provided for pending/future Open Finance transactions. */
  billForecastMonth: MonthKey | null
}

const EMPTY_CARD_METADATA: RawCardMetadata = { purchaseDate: null, billId: null, billForecastMonth: null }

function toIsoInstant(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

/** Parses `raw_data` without ever writing it back. Raw stays exactly as the provider sent it. */
export function extractCardMetadata(rawDataJson: string | null | undefined): RawCardMetadata {
  if (!rawDataJson) return EMPTY_CARD_METADATA
  let parsed: unknown
  try {
    parsed = JSON.parse(rawDataJson)
  } catch {
    return EMPTY_CARD_METADATA
  }
  if (!parsed || typeof parsed !== 'object') return EMPTY_CARD_METADATA
  const metadata = (parsed as Record<string, unknown>).creditCardMetadata
  if (!metadata || typeof metadata !== 'object') return EMPTY_CARD_METADATA
  const card = metadata as Record<string, unknown>
  const forecast = typeof card.billForecastDate === 'string' ? card.billForecastDate.slice(0, 7) : null
  return {
    purchaseDate: toIsoInstant(card.purchaseDate),
    billId: typeof card.billId === 'string' && card.billId.trim() ? card.billId.trim() : null,
    billForecastMonth: isMonthKey(forecast) ? forecast : null,
  }
}

export class CycleAssignmentService {
  constructor(private readonly deps: CycleAssignmentDeps) {}

  /**
   * Mirror an upstream bill into a domain cycle.
   *
   * competence is the CLOSING month, not the due month: a purchase posted in August that lands on
   * the statement closing in August and is paid in September belongs to the August statement.
   * With no closing date the due month is the only evidence left, and is used as documented fallback.
   */
  ensureCycleFromBill(bill: FinancialCreditCardBillRow): StatementCycleRow | null {
    const competenceMonth = monthKeyFromDate(bill.bill_closing_date) ?? monthKeyFromDate(bill.due_date)
    if (!competenceMonth) return null

    const account = this.deps.accounts.getByPluggyId(bill.pluggy_account_id)
    const statementCurrency = bill.currency_code ?? account?.currency_code ?? null
    // No currency evidence at all: refuse to invent one. A cycle with a guessed currency would
    // silently corrupt every total computed against it.
    if (!statementCurrency) return null

    return this.deps.cycles.upsertCycle({
      financialAccountId: bill.pluggy_account_id,
      source: 'PLUGGY_BILL',
      sourceExternalId: bill.pluggy_bill_id,
      cycleLabel: `Fatura ${competenceMonth}`,
      closingDate: bill.bill_closing_date,
      dueDate: bill.due_date,
      competenceMonth,
      statementCurrency,
      statementTotalCents: bill.total_amount_cents,
      status: bill.bill_closing_date ? 'CLOSED_SOURCE' : 'OPEN',
      metadata: { pluggyBillId: bill.pluggy_bill_id },
    })
  }

  /** Mirror every known bill of an account into cycles. Idempotent. */
  ensureCyclesForAccount(pluggyAccountId: string): StatementCycleRow[] {
    const bills = this.deps.db
      .prepare('SELECT * FROM financial_credit_card_bills WHERE pluggy_account_id = ? ORDER BY due_date ASC')
      .all(pluggyAccountId) as FinancialCreditCardBillRow[]
    const created: StatementCycleRow[] = []
    for (const bill of bills) {
      const cycle = this.ensureCycleFromBill(bill)
      if (cycle) created.push(cycle)
    }
    return created
  }

  /**
   * Which fatura does this transaction belong to?
   *
   * Returns the evidence tier that answered, so a caller can tell "we know" from "we guessed"
   * from "we have no idea". Nothing is applied here — this is a pure decision.
   */
  decideCycle(row: TemporalTransactionRow, account: FinancialAccountRow | null | undefined): CycleDecision {
    if (!isCreditCardAccount(account)) {
      return { cycleId: null, source: null, confidence: null, reason: 'not_credit_card' }
    }
    const accountId = row.pluggy_account_id

    // 1. USER — an explicit owner decision is final and outranks every provider fact.
    const userCorrection = this.deps.corrections.getActive(row.pluggy_transaction_id, 'statement_cycle')
    const userCycleId = userCorrection?.new_effective_value ?? null
    if (userCycleId && this.deps.cycles.getById(userCycleId)) {
      return { cycleId: userCycleId, source: 'USER', confidence: 1, reason: 'user_correction' }
    }

    const metadata = extractCardMetadata(row.raw_data)
    const postingDate = row.date
    const purchaseDate = metadata.purchaseDate ?? row.date

    // 2. Trusted statement reconciliation — an imported statement that already matched its source
    //    is stronger evidence than anything the provider says about a single transaction.
    const reconciled = this.findReconciledStatementCycle(accountId, postingDate, purchaseDate)
    if (reconciled) {
      return { cycleId: reconciled.id, source: 'STATEMENT_IMPORT', confidence: 0.95, reason: 'reconciled_statement' }
    }

    // 3. Explicit upstream bill identity — the provider naming the exact bill.
    if (metadata.billId) {
      const bill = this.deps.db
        .prepare('SELECT * FROM financial_credit_card_bills WHERE pluggy_bill_id = ?')
        .get(metadata.billId) as FinancialCreditCardBillRow | undefined
      if (bill) {
        const cycle = this.ensureCycleFromBill(bill)
        if (cycle) return { cycleId: cycle.id, source: 'PLUGGY_BILL', confidence: 0.9, reason: 'upstream_bill' }
      }
    }

    // 4. Deterministic date/cycle rules. A forecast period is upstream but explicitly a forecast,
    //    so it never gets bill-identity rank.
    if (metadata.billForecastMonth) {
      const forecastCycle = this.deps.cycles.findBestForCompetence(accountId, metadata.billForecastMonth)
      if (forecastCycle) {
        return { cycleId: forecastCycle.id, source: 'RULE', confidence: 0.6, reason: 'bill_forecast' }
      }
    }

    const windowed = this.findCycleByDateWindow(accountId, postingDate)
    if (windowed) return { cycleId: windowed.id, source: 'RULE', confidence: 0.5, reason: 'cycle_window' }

    // 5. Inference tier is intentionally empty. No evidence means no cycle.
    return { cycleId: null, source: null, confidence: null, reason: 'no_evidence' }
  }

  /**
   * Derive and persist the temporal facts, then apply the cycle decision.
   *
   * Writes ONLY the derived columns. `date`, `amount_cents`, `currency_code` and above all
   * `raw_data` are never touched: upstream truth is immutable, corrections live in the ledger.
   */
  syncTemporal(
    row: TemporalTransactionRow,
    account?: FinancialAccountRow | null,
  ): TemporalSyncResult {
    const resolvedAccount = account ?? this.deps.accounts.getByPluggyId(row.pluggy_account_id) ?? null
    const metadata = extractCardMetadata(row.raw_data)
    const isCreditCard = isCreditCardAccount(resolvedAccount)

    const purchaseDate = metadata.purchaseDate ?? row.date
    const purchaseMonth = derivePurchaseMonth(purchaseDate)

    // posted_date is only asserted when the source proves the two dates differ. Claiming that a
    // transaction date is also a posting date, when the provider never said so, is fabrication.
    const postedDate =
      metadata.purchaseDate && metadata.purchaseDate.slice(0, 10) !== row.date.slice(0, 10)
        ? row.date
        : (row.posted_date ?? null)

    const decision = this.decideCycle(row, resolvedAccount)
    let assignmentRejected = false
    let driftFlagged = false

    if (decision.cycleId && decision.source) {
      const result = this.deps.cycles.assignTransaction({
        pluggyTransactionId: row.pluggy_transaction_id,
        statementCycleId: decision.cycleId,
        source: decision.source,
        confidence: decision.confidence,
      })
      assignmentRejected = !result.applied
      driftFlagged = result.driftFlagged
    }

    // Re-read the durable assignment: a weaker source may have been rejected, in which case the
    // stronger existing cycle — not the one we just decided — drives competence and cashflow.
    const persisted = this.deps.db
      .prepare('SELECT statement_cycle_id FROM financial_transactions WHERE pluggy_transaction_id = ?')
      .get(row.pluggy_transaction_id) as { statement_cycle_id: string | null } | undefined
    const statementCycleId = persisted?.statement_cycle_id ?? null
    const cycle = statementCycleId ? this.deps.cycles.getById(statementCycleId) : undefined

    const userCompetence = this.deps.corrections.getActive(row.pluggy_transaction_id, 'competence_month')
      ?.new_effective_value

    const competence = deriveCompetenceMonth({
      transactionDate: purchaseDate,
      isCreditCard,
      assignedCycleCompetenceMonth: cycle?.competence_month ?? null,
      userCorrectedCompetenceMonth: isMonthKey(userCompetence) ? userCompetence : null,
    })

    // Cash leaves on the posting date for a cash account, and on the statement due date for a
    // card. With no due date the honest answer is NULL, never the purchase month.
    const cashflowMonth = deriveCashflowMonth({
      transactionDate: row.date,
      isCreditCard,
      assignedCycleDueDate: cycle?.due_date ?? null,
    })

    this.deps.db
      .prepare(
        [
          'UPDATE financial_transactions SET',
          '  posted_date = ?,',
          '  purchase_month = ?,',
          '  competence_month = ?,',
          '  cashflow_month = ?',
          'WHERE pluggy_transaction_id = ?',
        ].join('\n'),
      )
      .run(postedDate, purchaseMonth, competence.competenceMonth, cashflowMonth, row.pluggy_transaction_id)

    return {
      pluggyTransactionId: row.pluggy_transaction_id,
      postedDate,
      purchaseMonth,
      competenceMonth: competence.competenceMonth,
      cashflowMonth,
      statementCycleId,
      decision,
      assignmentRejected,
      driftFlagged,
    }
  }

  /**
   * A statement import that already reconciled against its source is trusted evidence.
   * The window must actually contain the transaction — a reconciled cycle never absorbs
   * transactions merely because it is the newest one around.
   */
  private findReconciledStatementCycle(
    pluggyAccountId: string,
    postingDate: string,
    purchaseDate: string,
  ): StatementCycleRow | undefined {
    return this.deps.db
      .prepare(
        [
          'SELECT * FROM financial_statement_cycles',
          " WHERE financial_account_id = ? AND source = 'STATEMENT_IMPORT'",
          "   AND reconciliation_status IN ('MATCHED', 'RECONCILED')",
          '   AND period_start IS NOT NULL AND period_end IS NOT NULL',
          '   AND ((? >= period_start AND ? <= period_end) OR (? >= period_start AND ? <= period_end))',
          ' ORDER BY period_end ASC',
          ' LIMIT 1',
        ].join('\n'),
      )
      .get(pluggyAccountId, postingDate, postingDate, purchaseDate, purchaseDate) as StatementCycleRow | undefined
  }

  /**
   * Deterministic date rule: the statement that closes first on/after the posting date.
   *
   * Guarded so old history is not swept into the oldest cycle we happen to know about: either the
   * candidate declares a period that contains the date, or a previous closed cycle proves the date
   * falls in a real gap between two known statements.
   */
  private findCycleByDateWindow(pluggyAccountId: string, postingDate: string): StatementCycleRow | undefined {
    const byPeriod = this.deps.db
      .prepare(
        [
          'SELECT * FROM financial_statement_cycles',
          ' WHERE financial_account_id = ?',
          '   AND period_start IS NOT NULL AND period_end IS NOT NULL',
          '   AND ? >= period_start AND ? <= period_end',
          ' ORDER BY period_end ASC LIMIT 1',
        ].join('\n'),
      )
      .get(pluggyAccountId, postingDate, postingDate) as StatementCycleRow | undefined
    if (byPeriod) return byPeriod

    const candidate = this.deps.db
      .prepare(
        [
          'SELECT * FROM financial_statement_cycles',
          ' WHERE financial_account_id = ? AND closing_date IS NOT NULL AND closing_date >= ?',
          ' ORDER BY closing_date ASC LIMIT 1',
        ].join('\n'),
      )
      .get(pluggyAccountId, postingDate) as StatementCycleRow | undefined
    if (!candidate) return undefined

    const previous = this.deps.db
      .prepare(
        [
          'SELECT closing_date FROM financial_statement_cycles',
          ' WHERE financial_account_id = ? AND closing_date IS NOT NULL AND closing_date < ?',
          ' ORDER BY closing_date DESC LIMIT 1',
        ].join('\n'),
      )
      .get(pluggyAccountId, postingDate) as { closing_date: string } | undefined

    if (previous) return candidate
    if (candidate.period_start && postingDate >= candidate.period_start) return candidate
    return undefined
  }
}
