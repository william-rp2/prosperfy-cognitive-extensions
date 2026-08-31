/**
 * F2B temporal semantics — pure functions, no DB access.
 *
 * A transaction date does not answer every financial question. Four distinct months exist:
 *  - purchase_month   : "em que mês eu fiz essa compra?"
 *  - competence_month : month the owner wants the expense analysed in
 *  - cashflow_month   : month cash actually left/entered the cash account
 *  - statement cycle  : which fatura the purchase landed on
 *
 * Every aggregate here declares its basis in its name. A generic `sumByMonth()` is forbidden:
 * an unnamed month is an ambiguous month.
 */

import type { FinancialTransactionRow } from './types.js'

export type MonthKey = string // 'YYYY-MM'

/**
 * Columns added by migration 009. Declared here as an additive extension instead of widening
 * `FinancialTransactionRow`: that type is shared by every finance module and F2B runs several
 * agents in parallel, so the shared file stays untouched.
 *
 * Every field is a separate fact. Collapsing any of them into a generic "month" is the exact
 * bug this module exists to prevent.
 */
export interface TemporalTransactionColumns {
  /** When the institution posted/settled it — only when the source actually distinguishes it. */
  posted_date?: string | null
  purchase_month?: MonthKey | null
  competence_month?: MonthKey | null
  cashflow_month?: MonthKey | null
  statement_cycle_id?: string | null
  cycle_assignment_source?: string | null
  cycle_assignment_confidence?: number | null
  cycle_assignment_updated_at?: string | null
}

export type TemporalTransactionRow = FinancialTransactionRow & TemporalTransactionColumns

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/

export function isMonthKey(value: unknown): value is MonthKey {
  return typeof value === 'string' && MONTH_PATTERN.test(value)
}

export function assertMonthKey(value: unknown, label = 'mês'): MonthKey {
  if (!isMonthKey(value)) {
    throw new Error(`${label} inválido: use o formato AAAA-MM.`)
  }
  return value
}

/** 'YYYY-MM' from a full ISO instant or a date-only string. Returns null for unusable input. */
export function monthKeyFromDate(date: string | null | undefined): MonthKey | null {
  if (!date) return null
  const candidate = date.slice(0, 7)
  return isMonthKey(candidate) ? candidate : null
}

/** The month the purchase happened, straight from the source transaction date. Never corrected away. */
export function derivePurchaseMonth(transactionDate: string | null | undefined): MonthKey | null {
  return monthKeyFromDate(transactionDate)
}

export interface CompetenceInput {
  /** Source transaction/purchase date (ISO). */
  transactionDate: string | null | undefined
  /** True when the underlying account is a credit card. */
  isCreditCard: boolean
  /** Competence of the statement cycle this transaction is assigned to, when a cycle is known. */
  assignedCycleCompetenceMonth?: MonthKey | null
  /** Explicit owner correction — always wins. */
  userCorrectedCompetenceMonth?: MonthKey | null
}

export type CompetenceBasis = 'USER_CORRECTION' | 'STATEMENT_CYCLE' | 'PURCHASE_MONTH'

export interface CompetenceResult {
  competenceMonth: MonthKey | null
  basis: CompetenceBasis
}

/**
 * Default competence policy:
 *  - explicit owner correction wins outright;
 *  - credit card prefers the assigned cycle's competence when a cycle is actually known;
 *  - everything else (and a card with no cycle evidence) falls back to the purchase month.
 *
 * competence_month is NOT assumed equal to purchase_month — it merely defaults to it.
 */
export function deriveCompetenceMonth(input: CompetenceInput): CompetenceResult {
  if (isMonthKey(input.userCorrectedCompetenceMonth)) {
    return { competenceMonth: input.userCorrectedCompetenceMonth, basis: 'USER_CORRECTION' }
  }
  if (input.isCreditCard && isMonthKey(input.assignedCycleCompetenceMonth)) {
    return { competenceMonth: input.assignedCycleCompetenceMonth, basis: 'STATEMENT_CYCLE' }
  }
  return { competenceMonth: derivePurchaseMonth(input.transactionDate), basis: 'PURCHASE_MONTH' }
}

export interface CashflowInput {
  transactionDate: string | null | undefined
  isCreditCard: boolean
  /** Due date of the assigned cycle (ISO) — when the card statement is actually paid. */
  assignedCycleDueDate?: string | null
  userCorrectedCashflowMonth?: MonthKey | null
}

/**
 * Cash leaves a checking account on the transaction date. For a card purchase cash leaves when
 * the statement is paid, so with no cycle due date the honest answer is null — not the purchase
 * month. Fail-open guessing here would silently corrupt cashflow reports.
 */
export function deriveCashflowMonth(input: CashflowInput): MonthKey | null {
  if (isMonthKey(input.userCorrectedCashflowMonth)) return input.userCorrectedCashflowMonth
  if (!input.isCreditCard) return monthKeyFromDate(input.transactionDate)
  return monthKeyFromDate(input.assignedCycleDueDate)
}

/** Credit-card detection from account type/subtype/canonical type, tolerant of nulls. */
export function isCreditCardAccount(account: {
  type?: string | null
  subtype?: string | null
  canonical_type?: string | null
} | null | undefined): boolean {
  if (!account) return false
  const type = account.type?.trim().toUpperCase() ?? ''
  const subtype = account.subtype?.trim().toUpperCase() ?? ''
  const canonical = account.canonical_type?.trim().toUpperCase() ?? ''
  return type === 'CREDIT' || subtype === 'CREDIT_CARD' || canonical === 'CREDIT_CARD'
}

// ---------------------------------------------------------------------------
// Aggregates. Each one names the month basis it groups by. There is deliberately
// no generic sumByMonth(): the caller must state which month it means.
// ---------------------------------------------------------------------------

export interface MonthlyTotal {
  month: MonthKey
  totalCents: number
  count: number
}

interface MonthBasisRow {
  purchase_month?: MonthKey | null
  competence_month?: MonthKey | null
  cashflow_month?: MonthKey | null
}

function totalsByMonth<T extends MonthBasisRow>(
  rows: readonly T[],
  monthOf: (row: T) => MonthKey | null | undefined,
  amountOf: (row: T) => number | null,
): MonthlyTotal[] {
  const buckets = new Map<MonthKey, MonthlyTotal>()
  for (const row of rows) {
    const month = monthOf(row)
    if (!isMonthKey(month)) continue
    const amount = amountOf(row)
    // Fail-closed: an amount we cannot express in the base currency is excluded, never zeroed.
    if (amount == null) continue
    const bucket = buckets.get(month) ?? { month, totalCents: 0, count: 0 }
    bucket.totalCents += amount
    bucket.count += 1
    buckets.set(month, bucket)
  }
  return [...buckets.values()].sort((a, b) => a.month.localeCompare(b.month))
}

/** Spend analysis basis: the month the owner assigns the expense to. */
export function spendByCompetenceMonth<T extends MonthBasisRow>(
  rows: readonly T[],
  amountOf: (row: T) => number | null,
): MonthlyTotal[] {
  return totalsByMonth(rows, row => row.competence_month, amountOf)
}

/** Cashflow analysis basis: the month money actually moved. */
export function cashflowByCashflowMonth<T extends MonthBasisRow>(
  rows: readonly T[],
  amountOf: (row: T) => number | null,
): MonthlyTotal[] {
  return totalsByMonth(rows, row => row.cashflow_month, amountOf)
}

/** Purchase history basis: when the purchase was made, regardless of statement or payment. */
export function purchasesByPurchaseMonth<T extends MonthBasisRow>(
  rows: readonly T[],
  amountOf: (row: T) => number | null,
): MonthlyTotal[] {
  return totalsByMonth(rows, row => row.purchase_month, amountOf)
}

/** Statement basis: totals grouped by the assigned cycle, for reconciliation against the source. */
export function statementTotalByCycle<T extends { statement_cycle_id?: string | null }>(
  rows: readonly T[],
  amountOf: (row: T) => number | null,
): { statementCycleId: string; totalCents: number; count: number }[] {
  const buckets = new Map<string, { statementCycleId: string; totalCents: number; count: number }>()
  for (const row of rows) {
    const cycleId = row.statement_cycle_id
    if (!cycleId) continue
    const amount = amountOf(row)
    if (amount == null) continue
    const bucket = buckets.get(cycleId) ?? { statementCycleId: cycleId, totalCents: 0, count: 0 }
    bucket.totalCents += amount
    bucket.count += 1
    buckets.set(cycleId, bucket)
  }
  return [...buckets.values()]
}
