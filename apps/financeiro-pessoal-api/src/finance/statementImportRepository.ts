import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import type { StatementCycleRow } from './statementCyclesRepository.js'
import type { MonthKey } from './temporalSemantics.js'
import type { ParsedStatementLine, StatementLineType } from './statementParser.js'

/**
 * Persistence for the imported-statement evidence layer (F2B, SUBAGENT_D).
 *
 * This repository writes ONLY to the `financial_statement_*` tables. It never writes
 * `financial_transactions.raw_data` and never deletes a provider row: the statement is a second,
 * parallel body of evidence, and any disagreement between the two is recorded as a discrepancy
 * rather than resolved by overwriting one of them.
 *
 * Every write is keyed on a natural identity (content hash / line hash / pair key), so replaying
 * the same statement converges instead of accumulating.
 */

export const STATEMENT_SOURCES = [
  'HERMES_ATTACHMENT',
  'FINANCE_EMAIL_ATTACHMENT',
  'MANUAL_UPLOAD',
  'PLUGGY_BILL',
] as const
export type StatementSource = (typeof STATEMENT_SOURCES)[number]

export function isStatementSource(value: unknown): value is StatementSource {
  return typeof value === 'string' && (STATEMENT_SOURCES as readonly string[]).includes(value)
}

export const IMPORT_STATUSES = ['PARSED', 'RECONCILING', 'RECONCILED', 'DISCREPANT'] as const
export type StatementImportStatus = (typeof IMPORT_STATUSES)[number]

export const MATCH_STATUSES = ['EXACT', 'HIGH', 'AMBIGUOUS', 'CONFLICT', 'STATEMENT_ONLY', 'APP_ONLY'] as const
export type MatchStatus = (typeof MATCH_STATUSES)[number]

export const DISCREPANCY_KINDS = ['TOTAL_MISMATCH', 'STATEMENT_ONLY', 'APP_ONLY', 'AMOUNT_MISMATCH', 'AMBIGUOUS'] as const
export type DiscrepancyKind = (typeof DISCREPANCY_KINDS)[number]

export interface StatementImportRow {
  id: string
  financial_account_id: string
  statement_cycle_id: string | null
  source: StatementSource
  content_hash: string
  file_name: string | null
  institution_hint: string | null
  card_last4: string | null
  competence_month: MonthKey
  statement_currency: string
  period_start: string | null
  period_end: string | null
  closing_date: string | null
  due_date: string | null
  statement_total_cents: number | null
  parsed_total_cents: number | null
  status: StatementImportStatus
  raw_text: string | null
  metadata_json: string | null
  imported_at: string
  reconciled_at: string | null
}

export interface StatementLineRow {
  id: string
  statement_import_id: string
  statement_cycle_id: string | null
  line_index: number
  line_hash: string
  date: string | null
  description_raw: string
  amount_cents: number
  currency_code: string
  line_type: StatementLineType
  card_hint: string | null
  source_page: number | null
  created_at: string
}

export interface ReconciliationRow {
  id: string
  statement_import_id: string
  statement_cycle_id: string | null
  statement_line_id: string | null
  pluggy_transaction_id: string | null
  match_status: MatchStatus
  confidence: number
  amount_delta_cents: number
  assignment_applied: number
  assignment_rejected: string | null
  evidence_json: string | null
  created_at: string
  updated_at: string
}

export interface DiscrepancyRow {
  id: string
  statement_import_id: string
  statement_cycle_id: string | null
  kind: DiscrepancyKind
  subject_key: string
  delta_cents: number | null
  detail_json: string | null
  created_at: string
  updated_at: string
  resolved_at: string | null
}

export interface UpsertStatementImportInput {
  financialAccountId: string
  source: StatementSource
  contentHash: string
  competenceMonth: MonthKey
  statementCurrency: string
  statementCycleId?: string | null
  fileName?: string | null
  institutionHint?: string | null
  cardLast4?: string | null
  periodStart?: string | null
  periodEnd?: string | null
  closingDate?: string | null
  dueDate?: string | null
  statementTotalCents?: number | null
  parsedTotalCents?: number | null
  rawText?: string | null
  metadata?: unknown
}

export interface UpsertStatementImportResult {
  row: StatementImportRow
  created: boolean
}

export interface CandidateTransactionRow {
  pluggy_transaction_id: string
  pluggy_account_id: string
  description: string | null
  description_raw: string | null
  amount_cents: number
  currency_code: string | null
  date: string
  statement_cycle_id: string | null
  cycle_assignment_source: string | null
}

export class StatementImportRepository {
  constructor(private readonly db: FinanceDb) {}

  /** Create or converge the import identified by (account, content hash). */
  upsertImport(input: UpsertStatementImportInput): UpsertStatementImportResult {
    const now = new Date().toISOString()
    const existing = this.findByContentHash(input.financialAccountId, input.contentHash)
    const metadataJson = input.metadata === undefined ? null : JSON.stringify(input.metadata)

    if (existing) {
      this.db
        .prepare(
          `UPDATE financial_statement_imports SET
             statement_cycle_id = COALESCE(@statementCycleId, statement_cycle_id),
             source = @source,
             file_name = COALESCE(@fileName, file_name),
             institution_hint = COALESCE(@institutionHint, institution_hint),
             card_last4 = COALESCE(@cardLast4, card_last4),
             competence_month = @competenceMonth,
             statement_currency = @statementCurrency,
             period_start = COALESCE(@periodStart, period_start),
             period_end = COALESCE(@periodEnd, period_end),
             closing_date = COALESCE(@closingDate, closing_date),
             due_date = COALESCE(@dueDate, due_date),
             statement_total_cents = COALESCE(@statementTotalCents, statement_total_cents),
             parsed_total_cents = COALESCE(@parsedTotalCents, parsed_total_cents),
             raw_text = COALESCE(@rawText, raw_text),
             metadata_json = COALESCE(@metadataJson, metadata_json)
           WHERE id = @id`,
        )
        .run({
          id: existing.id,
          statementCycleId: input.statementCycleId ?? null,
          source: input.source,
          fileName: input.fileName ?? null,
          institutionHint: input.institutionHint ?? null,
          cardLast4: input.cardLast4 ?? null,
          competenceMonth: input.competenceMonth,
          statementCurrency: input.statementCurrency,
          periodStart: input.periodStart ?? null,
          periodEnd: input.periodEnd ?? null,
          closingDate: input.closingDate ?? null,
          dueDate: input.dueDate ?? null,
          statementTotalCents: input.statementTotalCents ?? null,
          parsedTotalCents: input.parsedTotalCents ?? null,
          rawText: input.rawText ?? null,
          metadataJson,
        })
      return { row: this.getImport(existing.id)!, created: false }
    }

    const id = randomUUID()
    this.db
      .prepare(
        `INSERT INTO financial_statement_imports
           (id, financial_account_id, statement_cycle_id, source, content_hash, file_name,
            institution_hint, card_last4, competence_month, statement_currency, period_start,
            period_end, closing_date, due_date, statement_total_cents, parsed_total_cents,
            status, raw_text, metadata_json, imported_at, reconciled_at)
         VALUES (@id, @accountId, @statementCycleId, @source, @contentHash, @fileName,
                 @institutionHint, @cardLast4, @competenceMonth, @statementCurrency, @periodStart,
                 @periodEnd, @closingDate, @dueDate, @statementTotalCents, @parsedTotalCents,
                 'PARSED', @rawText, @metadataJson, @importedAt, NULL)`,
      )
      .run({
        id,
        accountId: input.financialAccountId,
        statementCycleId: input.statementCycleId ?? null,
        source: input.source,
        contentHash: input.contentHash,
        fileName: input.fileName ?? null,
        institutionHint: input.institutionHint ?? null,
        cardLast4: input.cardLast4 ?? null,
        competenceMonth: input.competenceMonth,
        statementCurrency: input.statementCurrency,
        periodStart: input.periodStart ?? null,
        periodEnd: input.periodEnd ?? null,
        closingDate: input.closingDate ?? null,
        dueDate: input.dueDate ?? null,
        statementTotalCents: input.statementTotalCents ?? null,
        parsedTotalCents: input.parsedTotalCents ?? null,
        rawText: input.rawText ?? null,
        metadataJson,
        importedAt: now,
      })
    return { row: this.getImport(id)!, created: true }
  }

  getImport(id: string): StatementImportRow | undefined {
    return this.db.prepare('SELECT * FROM financial_statement_imports WHERE id = ?').get(id) as
      | StatementImportRow
      | undefined
  }

  findByContentHash(financialAccountId: string, contentHash: string): StatementImportRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_statement_imports WHERE financial_account_id = ? AND content_hash = ?')
      .get(financialAccountId, contentHash) as StatementImportRow | undefined
  }

  setImportCycle(id: string, statementCycleId: string): void {
    this.db.prepare('UPDATE financial_statement_imports SET statement_cycle_id = ? WHERE id = ?').run(statementCycleId, id)
  }

  setImportStatus(id: string, status: StatementImportStatus, reconciledAt?: string | null): void {
    this.db
      .prepare('UPDATE financial_statement_imports SET status = ?, reconciled_at = COALESCE(?, reconciled_at) WHERE id = ?')
      .run(status, reconciledAt ?? null, id)
  }

  /** Idempotent by (import, line_hash): replaying the same statement converges on the same rows. */
  upsertLines(statementImportId: string, statementCycleId: string | null, lines: readonly ParsedStatementLine[]): StatementLineRow[] {
    const now = new Date().toISOString()
    const insert = this.db.prepare(
      `INSERT INTO financial_statement_lines
         (id, statement_import_id, statement_cycle_id, line_index, line_hash, date, description_raw,
          amount_cents, currency_code, line_type, card_hint, source_page, created_at)
       VALUES (@id, @importId, @cycleId, @lineIndex, @lineHash, @date, @descriptionRaw,
               @amountCents, @currencyCode, @lineType, @cardHint, @sourcePage, @createdAt)
       ON CONFLICT(statement_import_id, line_hash) DO UPDATE SET
         statement_cycle_id = COALESCE(excluded.statement_cycle_id, financial_statement_lines.statement_cycle_id),
         line_index = excluded.line_index,
         line_type = excluded.line_type,
         card_hint = excluded.card_hint,
         source_page = excluded.source_page`,
    )

    const run = this.db.transaction(() => {
      for (const line of lines) {
        insert.run({
          id: randomUUID(),
          importId: statementImportId,
          cycleId: statementCycleId,
          lineIndex: line.lineIndex,
          lineHash: line.lineHash,
          date: line.date,
          descriptionRaw: line.descriptionRaw,
          amountCents: line.amountCents,
          currencyCode: line.currencyCode,
          lineType: line.lineType,
          cardHint: line.cardHint,
          sourcePage: line.sourcePage,
          createdAt: now,
        })
      }
    })
    run()
    return this.listLines(statementImportId)
  }

  listLines(statementImportId: string): StatementLineRow[] {
    return this.db
      .prepare('SELECT * FROM financial_statement_lines WHERE statement_import_id = ? ORDER BY line_index ASC')
      .all(statementImportId) as StatementLineRow[]
  }

  /** Idempotent by the coalesced (import, line, transaction) pair key. */
  upsertReconciliation(input: {
    statementImportId: string
    statementCycleId: string | null
    statementLineId: string | null
    pluggyTransactionId: string | null
    matchStatus: MatchStatus
    confidence: number
    amountDeltaCents: number
    assignmentApplied: boolean
    assignmentRejected?: string | null
    evidence?: unknown
  }): void {
    const now = new Date().toISOString()
    this.db
      .prepare(
        `INSERT INTO financial_statement_reconciliations
           (id, statement_import_id, statement_cycle_id, statement_line_id, pluggy_transaction_id,
            match_status, confidence, amount_delta_cents, assignment_applied, assignment_rejected,
            evidence_json, created_at, updated_at)
         VALUES (@id, @importId, @cycleId, @lineId, @transactionId, @matchStatus, @confidence,
                 @amountDeltaCents, @assignmentApplied, @assignmentRejected, @evidenceJson, @now, @now)
         ON CONFLICT(statement_import_id, COALESCE(statement_line_id, ''), COALESCE(pluggy_transaction_id, ''))
         DO UPDATE SET
           statement_cycle_id = excluded.statement_cycle_id,
           match_status = excluded.match_status,
           confidence = excluded.confidence,
           amount_delta_cents = excluded.amount_delta_cents,
           assignment_applied = excluded.assignment_applied,
           assignment_rejected = excluded.assignment_rejected,
           evidence_json = excluded.evidence_json,
           updated_at = excluded.updated_at`,
      )
      .run({
        id: randomUUID(),
        importId: input.statementImportId,
        cycleId: input.statementCycleId,
        lineId: input.statementLineId,
        transactionId: input.pluggyTransactionId,
        matchStatus: input.matchStatus,
        confidence: input.confidence,
        amountDeltaCents: input.amountDeltaCents,
        assignmentApplied: input.assignmentApplied ? 1 : 0,
        assignmentRejected: input.assignmentRejected ?? null,
        evidenceJson: input.evidence === undefined ? null : JSON.stringify(input.evidence),
        now,
      })
  }

  /**
   * Close every open divergence of this import. Rows are kept (a divergence is recorded, never
   * deleted); `upsertDiscrepancy` re-opens the ones the next pass finds again.
   */
  resolveOpenDiscrepancies(statementImportId: string): void {
    this.db
      .prepare(
        'UPDATE financial_statement_discrepancies SET resolved_at = ?, updated_at = ? WHERE statement_import_id = ? AND resolved_at IS NULL',
      )
      .run(new Date().toISOString(), new Date().toISOString(), statementImportId)
  }

  /**
   * Drop the derived match rows of this import so a re-run recomputes them from scratch.
   *
   * These rows are output, not evidence: the statement, its lines and the provider transactions
   * are untouched. Without this a line matched to one transaction and later re-matched to another
   * would leave both links standing, and a transaction that stopped being app-only would keep its
   * stale APP_ONLY row forever.
   */
  clearReconciliations(statementImportId: string): void {
    this.db.prepare('DELETE FROM financial_statement_reconciliations WHERE statement_import_id = ?').run(statementImportId)
  }

  listReconciliations(statementImportId: string): ReconciliationRow[] {
    return this.db
      .prepare('SELECT * FROM financial_statement_reconciliations WHERE statement_import_id = ? ORDER BY created_at ASC, id ASC')
      .all(statementImportId) as ReconciliationRow[]
  }

  /** A divergence is recorded, never resolved by deleting data. */
  upsertDiscrepancy(input: {
    statementImportId: string
    statementCycleId: string | null
    kind: DiscrepancyKind
    subjectKey: string
    deltaCents?: number | null
    detail?: unknown
  }): void {
    const now = new Date().toISOString()
    this.db
      .prepare(
        `INSERT INTO financial_statement_discrepancies
           (id, statement_import_id, statement_cycle_id, kind, subject_key, delta_cents, detail_json,
            created_at, updated_at, resolved_at)
         VALUES (@id, @importId, @cycleId, @kind, @subjectKey, @deltaCents, @detailJson, @now, @now, NULL)
         ON CONFLICT(statement_import_id, kind, subject_key) DO UPDATE SET
           statement_cycle_id = excluded.statement_cycle_id,
           delta_cents = excluded.delta_cents,
           detail_json = excluded.detail_json,
           updated_at = excluded.updated_at,
           resolved_at = NULL`,
      )
      .run({
        id: randomUUID(),
        importId: input.statementImportId,
        cycleId: input.statementCycleId,
        kind: input.kind,
        subjectKey: input.subjectKey,
        deltaCents: input.deltaCents ?? null,
        detailJson: input.detail === undefined ? null : JSON.stringify(input.detail),
        now,
      })
  }

  /**
   * Only the divergences still open. A run that starts by closing the previous run's findings and
   * re-opens the ones that survive would otherwise report a divergence that no longer exists —
   * the normal case here, because a transaction that was missing at import time arrives later.
   */
  listDiscrepancies(statementImportId: string): DiscrepancyRow[] {
    return this.db
      .prepare('SELECT * FROM financial_statement_discrepancies WHERE statement_import_id = ? AND resolved_at IS NULL ORDER BY kind ASC, subject_key ASC')
      .all(statementImportId) as DiscrepancyRow[]
  }

  /**
   * Read-only listing of every cycle, for the unfiltered `GET /api/finance/cycles`.
   * Lives here rather than in `StatementCyclesRepository` (owned by SUBAGENT_A) to keep file
   * ownership clean; it only reads.
   */
  listAllCycles(): StatementCycleRow[] {
    return this.db
      .prepare('SELECT * FROM financial_statement_cycles ORDER BY competence_month DESC, imported_at DESC')
      .all() as StatementCycleRow[]
  }

  /**
   * Candidate app-side transactions for an account within a date window.
   * Read-only: matching never mutates `financial_transactions` from here.
   */
  listCandidateTransactions(financialAccountId: string, startDate: string, endDate: string): CandidateTransactionRow[] {
    return this.db
      .prepare(
        `SELECT pluggy_transaction_id, pluggy_account_id, description, description_raw, amount_cents,
                currency_code, date, statement_cycle_id, cycle_assignment_source
           FROM financial_transactions
          WHERE pluggy_account_id = ? AND deleted_at IS NULL AND date(date) BETWEEN date(?) AND date(?)
          ORDER BY date ASC, pluggy_transaction_id ASC`,
      )
      .all(financialAccountId, startDate, endDate) as CandidateTransactionRow[]
  }
}
