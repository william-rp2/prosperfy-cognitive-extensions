import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import { assertMonthKey, type MonthKey } from './temporalSemantics.js'

/**
 * Statement cycles — our domain truth about which fatura a purchase landed on.
 *
 * Deliberately separate from `financial_credit_card_bills`, which stays a read-only mirror of
 * upstream Pluggy bills (PLAN.md D3). A cycle may originate from a bill, from an imported
 * statement, from a closing-date rule, or from the owner.
 *
 * Assignment precedence: USER > STATEMENT_IMPORT > PLUGGY_BILL > RULE > INFERRED.
 * A weaker source never silently overwrites a stronger one during sync.
 */

export const CYCLE_STATUSES = [
  'OPEN',
  'CLOSED_SOURCE',
  'RECONCILING',
  'RECONCILED',
  'DISCREPANT',
  'ARCHIVED',
] as const
export type CycleStatus = (typeof CYCLE_STATUSES)[number]

export const RECONCILIATION_STATUSES = ['PENDING', 'IN_PROGRESS', 'MATCHED', 'DRIFT', 'DISCREPANT'] as const
export type ReconciliationStatus = (typeof RECONCILIATION_STATUSES)[number]

export const ASSIGNMENT_SOURCES = ['USER', 'STATEMENT_IMPORT', 'PLUGGY_BILL', 'RULE', 'INFERRED'] as const
export type CycleAssignmentSource = (typeof ASSIGNMENT_SOURCES)[number]

/** Higher wins. Ranks are explicit so precedence is auditable rather than array-order folklore. */
const ASSIGNMENT_RANK: Record<CycleAssignmentSource, number> = {
  USER: 50,
  STATEMENT_IMPORT: 40,
  PLUGGY_BILL: 30,
  RULE: 20,
  INFERRED: 10,
}

export function assignmentRank(source: string | null | undefined): number {
  if (!source) return 0
  return ASSIGNMENT_RANK[source as CycleAssignmentSource] ?? 0
}

export interface StatementCycleRow {
  id: string
  financial_account_id: string
  source: CycleAssignmentSource
  source_external_id: string | null
  cycle_label: string
  period_start: string | null
  period_end: string | null
  closing_date: string | null
  due_date: string | null
  competence_month: MonthKey
  statement_currency: string
  statement_total_cents: number | null
  effective_total_cents: number | null
  status: CycleStatus
  reconciliation_status: ReconciliationStatus
  imported_at: string
  closed_at: string | null
  metadata_json: string | null
}

export interface UpsertCycleInput {
  financialAccountId: string
  source: CycleAssignmentSource
  sourceExternalId?: string | null
  cycleLabel?: string
  periodStart?: string | null
  periodEnd?: string | null
  closingDate?: string | null
  dueDate?: string | null
  competenceMonth: MonthKey
  statementCurrency: string
  statementTotalCents?: number | null
  effectiveTotalCents?: number | null
  status?: CycleStatus
  reconciliationStatus?: ReconciliationStatus
  closedAt?: string | null
  metadata?: unknown
}

export interface AssignTransactionInput {
  pluggyTransactionId: string
  statementCycleId: string
  source: CycleAssignmentSource
  confidence?: number | null
}

export interface AssignmentResult {
  applied: boolean
  /** Set when a weaker source tried to overwrite a stronger existing assignment. */
  rejectedReason?: 'weaker_source' | 'cycle_not_found'
  previousSource: CycleAssignmentSource | null
  previousCycleId: string | null
  /**
   * True when this assignment touched a RECONCILED cycle. The cycle's closure is NOT rewritten;
   * reconciliation_status becomes DRIFT so the divergence is surfaced instead of hidden.
   */
  driftFlagged: boolean
}

const INSERT_CYCLE = [
  'INSERT INTO financial_statement_cycles',
  '  (id, financial_account_id, source, source_external_id, cycle_label, period_start, period_end,',
  '   closing_date, due_date, competence_month, statement_currency, statement_total_cents,',
  '   effective_total_cents, status, reconciliation_status, imported_at, closed_at, metadata_json)',
  'VALUES (@id, @accountId, @source, @sourceExternalId, @cycleLabel, @periodStart, @periodEnd,',
  '        @closingDate, @dueDate, @competenceMonth, @statementCurrency, @statementTotalCents,',
  '        @effectiveTotalCents, @status, @reconciliationStatus, @importedAt, @closedAt, @metadataJson)',
].join('\n')

export class StatementCyclesRepository {
  constructor(private readonly db: FinanceDb) {}

  /** Create or update the cycle identified by (account, competence, source). */
  upsertCycle(input: UpsertCycleInput): StatementCycleRow {
    const competenceMonth = assertMonthKey(input.competenceMonth, 'Mês de competência')
    const now = new Date().toISOString()
    const existing = this.findByIdentity(input.financialAccountId, competenceMonth, input.source)

    if (existing) {
      this.db
        .prepare(
          [
            'UPDATE financial_statement_cycles SET',
            '  source_external_id = COALESCE(?, source_external_id),',
            '  cycle_label = COALESCE(?, cycle_label),',
            '  period_start = COALESCE(?, period_start),',
            '  period_end = COALESCE(?, period_end),',
            '  closing_date = COALESCE(?, closing_date),',
            '  due_date = COALESCE(?, due_date),',
            '  statement_currency = COALESCE(?, statement_currency),',
            '  statement_total_cents = COALESCE(?, statement_total_cents),',
            '  effective_total_cents = COALESCE(?, effective_total_cents),',
            '  status = COALESCE(?, status),',
            '  reconciliation_status = COALESCE(?, reconciliation_status),',
            '  closed_at = COALESCE(?, closed_at),',
            '  metadata_json = COALESCE(?, metadata_json)',
            'WHERE id = ?',
          ].join('\n'),
        )
        .run(
          input.sourceExternalId ?? null,
          input.cycleLabel ?? null,
          input.periodStart ?? null,
          input.periodEnd ?? null,
          input.closingDate ?? null,
          input.dueDate ?? null,
          input.statementCurrency ?? null,
          input.statementTotalCents ?? null,
          input.effectiveTotalCents ?? null,
          input.status ?? null,
          input.reconciliationStatus ?? null,
          input.closedAt ?? null,
          input.metadata === undefined ? null : JSON.stringify(input.metadata),
          existing.id,
        )
      return this.getById(existing.id)!
    }

    const id = randomUUID()
    this.db.prepare(INSERT_CYCLE).run({
      id,
      accountId: input.financialAccountId,
      source: input.source,
      sourceExternalId: input.sourceExternalId ?? null,
      cycleLabel: input.cycleLabel ?? `Fatura ${competenceMonth}`,
      periodStart: input.periodStart ?? null,
      periodEnd: input.periodEnd ?? null,
      closingDate: input.closingDate ?? null,
      dueDate: input.dueDate ?? null,
      competenceMonth,
      statementCurrency: input.statementCurrency,
      statementTotalCents: input.statementTotalCents ?? null,
      effectiveTotalCents: input.effectiveTotalCents ?? null,
      status: input.status ?? 'OPEN',
      reconciliationStatus: input.reconciliationStatus ?? 'PENDING',
      importedAt: now,
      closedAt: input.closedAt ?? null,
      metadataJson: input.metadata === undefined ? null : JSON.stringify(input.metadata),
    })
    return this.getById(id)!
  }

  getById(id: string): StatementCycleRow | undefined {
    return this.db.prepare('SELECT * FROM financial_statement_cycles WHERE id = ?').get(id) as
      | StatementCycleRow
      | undefined
  }

  findByIdentity(
    financialAccountId: string,
    competenceMonth: MonthKey,
    source: CycleAssignmentSource,
  ): StatementCycleRow | undefined {
    return this.db
      .prepare(
        'SELECT * FROM financial_statement_cycles WHERE financial_account_id = ? AND competence_month = ? AND source = ?',
      )
      .get(financialAccountId, competenceMonth, source) as StatementCycleRow | undefined
  }

  listByAccount(financialAccountId: string): StatementCycleRow[] {
    return this.db
      .prepare(
        'SELECT * FROM financial_statement_cycles WHERE financial_account_id = ? ORDER BY competence_month DESC, imported_at DESC',
      )
      .all(financialAccountId) as StatementCycleRow[]
  }

  listByCompetence(competenceMonth: MonthKey, financialAccountId?: string): StatementCycleRow[] {
    if (financialAccountId) {
      return this.db
        .prepare(
          'SELECT * FROM financial_statement_cycles WHERE competence_month = ? AND financial_account_id = ? ORDER BY imported_at DESC',
        )
        .all(competenceMonth, financialAccountId) as StatementCycleRow[]
    }
    return this.db
      .prepare('SELECT * FROM financial_statement_cycles WHERE competence_month = ? ORDER BY imported_at DESC')
      .all(competenceMonth) as StatementCycleRow[]
  }

  /**
   * Best cycle for an account + competence, preferring the most trustworthy origin.
   * Used when several sources produced a cycle for the same month.
   */
  findBestForCompetence(financialAccountId: string, competenceMonth: MonthKey): StatementCycleRow | undefined {
    const candidates = this.listByCompetence(competenceMonth, financialAccountId)
    if (candidates.length === 0) return undefined
    return [...candidates].sort((a, b) => assignmentRank(b.source) - assignmentRank(a.source))[0]
  }

  setStatus(id: string, status: CycleStatus, closedAt?: string | null): void {
    this.db
      .prepare('UPDATE financial_statement_cycles SET status = ?, closed_at = COALESCE(?, closed_at) WHERE id = ?')
      .run(status, closedAt ?? null, id)
  }

  setReconciliationStatus(id: string, status: ReconciliationStatus): void {
    this.db.prepare('UPDATE financial_statement_cycles SET reconciliation_status = ? WHERE id = ?').run(status, id)
  }

  setEffectiveTotal(id: string, effectiveTotalCents: number | null): void {
    this.db
      .prepare('UPDATE financial_statement_cycles SET effective_total_cents = ? WHERE id = ?')
      .run(effectiveTotalCents, id)
  }

  /**
   * Durably attach a transaction to a cycle, honouring source precedence.
   *
   * A weaker source is rejected outright rather than applied-then-warned: silent downgrade during
   * a routine sync is exactly the failure mode this table exists to prevent. Equal rank is allowed
   * (a newer statement import supersedes an older one from the same authority).
   */
  assignTransaction(input: AssignTransactionInput): AssignmentResult {
    const cycle = this.getById(input.statementCycleId)
    if (!cycle) {
      return {
        applied: false,
        rejectedReason: 'cycle_not_found',
        previousSource: null,
        previousCycleId: null,
        driftFlagged: false,
      }
    }

    const current = this.db
      .prepare(
        'SELECT statement_cycle_id, cycle_assignment_source FROM financial_transactions WHERE pluggy_transaction_id = ?',
      )
      .get(input.pluggyTransactionId) as
      | { statement_cycle_id: string | null; cycle_assignment_source: CycleAssignmentSource | null }
      | undefined

    const previousSource = current?.cycle_assignment_source ?? null
    const previousCycleId = current?.statement_cycle_id ?? null

    if (assignmentRank(previousSource) > assignmentRank(input.source)) {
      return { applied: false, rejectedReason: 'weaker_source', previousSource, previousCycleId, driftFlagged: false }
    }

    const now = new Date().toISOString()
    const changesCycle = previousCycleId !== input.statementCycleId

    const apply = this.db.transaction(() => {
      this.db
        .prepare(
          [
            'UPDATE financial_transactions SET',
            '  statement_cycle_id = ?,',
            '  cycle_assignment_source = ?,',
            '  cycle_assignment_confidence = ?,',
            '  cycle_assignment_updated_at = ?',
            'WHERE pluggy_transaction_id = ?',
          ].join('\n'),
        )
        .run(
          input.statementCycleId,
          input.source,
          input.confidence ?? null,
          now,
          input.pluggyTransactionId,
        )

      // Late arrival into an already-reconciled cycle: never rewrite the closure, flag the drift.
      let drift = false
      if (changesCycle && cycle.status === 'RECONCILED') {
        this.db
          .prepare("UPDATE financial_statement_cycles SET reconciliation_status = 'DRIFT' WHERE id = ?")
          .run(cycle.id)
        drift = true
      } else if (changesCycle && cycle.status === 'CLOSED_SOURCE' && cycle.reconciliation_status !== 'DRIFT') {
        // Closed but not yet reconciled: mark it dirty so reconciliation runs again.
        this.db
          .prepare("UPDATE financial_statement_cycles SET reconciliation_status = 'IN_PROGRESS' WHERE id = ?")
          .run(cycle.id)
      }
      return drift
    })

    const driftFlagged = apply()
    return { applied: true, previousSource, previousCycleId, driftFlagged }
  }

  /** Detach a transaction from its cycle. Only a source of equal or greater rank may do so. */
  clearAssignment(pluggyTransactionId: string, source: CycleAssignmentSource): boolean {
    const current = this.db
      .prepare('SELECT cycle_assignment_source FROM financial_transactions WHERE pluggy_transaction_id = ?')
      .get(pluggyTransactionId) as { cycle_assignment_source: CycleAssignmentSource | null } | undefined
    if (assignmentRank(current?.cycle_assignment_source) > assignmentRank(source)) return false
    this.db
      .prepare(
        'UPDATE financial_transactions SET statement_cycle_id = NULL, cycle_assignment_source = NULL, cycle_assignment_confidence = NULL, cycle_assignment_updated_at = ? WHERE pluggy_transaction_id = ?',
      )
      .run(new Date().toISOString(), pluggyTransactionId)
    return true
  }

  listTransactionIdsForCycle(statementCycleId: string): string[] {
    const rows = this.db
      .prepare(
        'SELECT pluggy_transaction_id FROM financial_transactions WHERE statement_cycle_id = ? AND deleted_at IS NULL ORDER BY date ASC',
      )
      .all(statementCycleId) as { pluggy_transaction_id: string }[]
    return rows.map(row => row.pluggy_transaction_id)
  }
}
