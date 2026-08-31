import type { StatementCyclesRepository } from './statementCyclesRepository.js'
import { matchStatementLines, type LineMatchResult, type MatchingOptions } from './statementMatchingService.js'
import {
  type CandidateTransactionRow,
  type StatementImportRepository,
  type StatementImportRow,
  type StatementLineRow,
  type StatementSource,
} from './statementImportRepository.js'
import { parseStatement, parseStatementDate, statementContentHash, type ParsedStatement } from './statementParser.js'
import { assertMonthKey, monthKeyFromDate, type MonthKey } from './temporalSemantics.js'

/**
 * Closed-statement import + reconciliation (F2B, SUBAGENT_D).
 *
 * Contract this service is built to keep:
 *
 *  1. RAW IS IMMUTABLE. Nothing here writes `financial_transactions.raw_data` or deletes a
 *     provider row. The statement is an independent evidence layer; corrections travel through
 *     the corrections ledger / effective layer owned by SUBAGENT_A.
 *  2. THE STATEMENT IS DATA. Its text is normalized and compared, never interpreted as a command
 *     and never used to derive a path or an authorization decision.
 *  3. ASSIGNMENT PRECEDENCE IS INVIOLABLE: USER > trusted statement reconciliation >
 *     upstream bill identity > deterministic date rule > inference. This service always writes
 *     with source `STATEMENT_IMPORT`, so `StatementCyclesRepository.assignTransaction` rejects it
 *     whenever a USER correction already owns the transaction. A rejection is recorded, not retried.
 *  4. A DIVERGENCE IS RECORDED, NEVER SILENTLY REPAIRED. Statement-only lines, app-only
 *     transactions, ambiguity and a total mismatch all persist as discrepancies and mark the
 *     cycle DISCREPANT instead of deleting the inconvenient side.
 *  5. NO PAYMENT INITIATION. Reconciliation is read-and-match accounting. There is no transfer,
 *     PIX or bill-payment path anywhere in this module.
 */

interface AccountLookup {
  getByPluggyId(pluggyAccountId: string): { currency_code?: string | null } | undefined
}

export interface ImportStatementInput {
  financialAccountId: string
  source: StatementSource
  competenceMonth: MonthKey
  statementCurrency?: string | null
  /** Untrusted extracted text. Opaque. */
  rawText?: string | null
  /** Untrusted structured lines. Opaque. */
  lines?: unknown
  fileName?: string | null
  institutionHint?: string | null
  cardLast4?: string | null
  periodStart?: string | null
  periodEnd?: string | null
  closingDate?: string | null
  dueDate?: string | null
  statementTotalCents?: number | null
  metadata?: unknown
}

export interface ImportStatementResult {
  statementId: string
  cycleId: string
  created: boolean
  competenceMonth: MonthKey
  statementCurrency: string
  lineCount: number
  skippedLineCount: number
  parsedTotalCents: number
  statementTotalCents: number | null
  status: StatementImportRow['status']
}

export interface ReconciliationLineReport {
  lineId: string
  lineIndex: number
  date: string | null
  descriptionRaw: string
  amountCents: number
  status: LineMatchResult['status']
  transactionId: string | null
  confidence: number
  assignmentApplied: boolean
  assignmentRejected: string | null
}

export interface ReconciliationReport {
  statementId: string
  cycleId: string
  competenceMonth: MonthKey
  statementCurrency: string
  statementTotalCents: number | null
  matchedTotalCents: number
  parsedTotalCents: number
  differenceCents: number | null
  matchedCount: number
  statementOnlyCount: number
  appOnlyCount: number
  ambiguousCount: number
  lines: ReconciliationLineReport[]
  statementOnly: ReconciliationLineReport[]
  appOnly: { transactionId: string; date: string; amountCents: number; description: string | null }[]
  discrepancies: { kind: string; subjectKey: string; deltaCents: number | null }[]
  cycleStatus: string
  reconciliationStatus: string
}

export interface ReconciliationServiceDeps {
  statementImports: StatementImportRepository
  cycles: StatementCyclesRepository
  accounts: AccountLookup
  matching?: MatchingOptions
}

export class StatementNotFoundError extends Error {}
export class AccountNotFoundError extends Error {}

/** Widen a date window by whole days without touching the source dates themselves. */
function shiftDays(isoDate: string, days: number): string {
  const base = Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`)
  return new Date(base + days * 86_400_000).toISOString().slice(0, 10)
}

function monthBounds(competenceMonth: MonthKey): { start: string; end: string } {
  const [year, month] = competenceMonth.split('-').map(Number)
  const start = `${competenceMonth}-01`
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return { start, end: `${competenceMonth}-${String(lastDay).padStart(2, '0')}` }
}

export class ReconciliationService {
  private readonly statementImports: StatementImportRepository
  private readonly cycles: StatementCyclesRepository
  private readonly accounts: AccountLookup
  private readonly matching: MatchingOptions

  constructor(deps: ReconciliationServiceDeps) {
    this.statementImports = deps.statementImports
    this.cycles = deps.cycles
    this.accounts = deps.accounts
    this.matching = deps.matching ?? {}
  }

  /**
   * Parse and persist a closed statement.
   *
   * Idempotent: identity is the content hash of the payload, so re-importing the same statement
   * converges on the same import row, the same lines and the same cycle.
   */
  importStatement(input: ImportStatementInput): ImportStatementResult {
    const account = this.accounts.getByPluggyId(input.financialAccountId)
    if (!account) throw new AccountNotFoundError('Conta financeira não encontrada.')

    const competenceMonth = assertMonthKey(input.competenceMonth, 'Mês de competência')
    const statementCurrency = (input.statementCurrency || account.currency_code || 'BRL').toUpperCase()

    const parsed: ParsedStatement = parseStatement({
      rawText: input.rawText ?? null,
      lines: input.lines,
      currencyCode: statementCurrency,
    })

    const contentHash = statementContentHash([
      input.financialAccountId,
      competenceMonth,
      statementCurrency,
      input.rawText ?? '',
      ...parsed.lines.map(line => line.lineHash),
    ])

    const cycle = this.cycles.upsertCycle({
      financialAccountId: input.financialAccountId,
      source: 'STATEMENT_IMPORT',
      competenceMonth,
      statementCurrency,
      cycleLabel: `Fatura ${competenceMonth}`,
      periodStart: parseStatementDate(input.periodStart) ?? null,
      periodEnd: parseStatementDate(input.periodEnd) ?? null,
      closingDate: parseStatementDate(input.closingDate) ?? null,
      dueDate: parseStatementDate(input.dueDate) ?? null,
      statementTotalCents: input.statementTotalCents ?? null,
      status: 'CLOSED_SOURCE',
      reconciliationStatus: 'PENDING',
    })

    const upserted = this.statementImports.upsertImport({
      financialAccountId: input.financialAccountId,
      source: input.source,
      contentHash,
      competenceMonth,
      statementCurrency,
      statementCycleId: cycle.id,
      fileName: input.fileName ?? null,
      institutionHint: input.institutionHint ?? null,
      cardLast4: input.cardLast4 ?? null,
      periodStart: parseStatementDate(input.periodStart) ?? null,
      periodEnd: parseStatementDate(input.periodEnd) ?? null,
      closingDate: parseStatementDate(input.closingDate) ?? null,
      dueDate: parseStatementDate(input.dueDate) ?? null,
      statementTotalCents: input.statementTotalCents ?? null,
      parsedTotalCents: parsed.parsedTotalCents,
      rawText: input.rawText ?? null,
      metadata: input.metadata,
    })

    const lines = this.statementImports.upsertLines(upserted.row.id, cycle.id, parsed.lines)

    return {
      statementId: upserted.row.id,
      cycleId: cycle.id,
      created: upserted.created,
      competenceMonth,
      statementCurrency,
      lineCount: lines.length,
      skippedLineCount: parsed.skippedLineCount,
      parsedTotalCents: parsed.parsedTotalCents,
      statementTotalCents: upserted.row.statement_total_cents,
      status: upserted.row.status,
    }
  }

  /** Date window used to pull app-side candidates. Derived from the data, never a fixed guess. */
  private candidateWindow(statement: StatementImportRow, lines: readonly StatementLineRow[]): { start: string; end: string } {
    const tolerance = this.matching.dateToleranceDays ?? 3
    const dates = lines.map(line => line.date).filter((date): date is string => typeof date === 'string' && date !== '')
    if (dates.length > 0) {
      const sorted = [...dates].sort()
      return { start: shiftDays(sorted[0], -tolerance), end: shiftDays(sorted[sorted.length - 1], tolerance) }
    }
    if (statement.period_start && statement.period_end) {
      return { start: shiftDays(statement.period_start, -tolerance), end: shiftDays(statement.period_end, tolerance) }
    }
    const bounds = monthBounds(statement.competence_month)
    return { start: shiftDays(bounds.start, -tolerance), end: shiftDays(bounds.end, tolerance) }
  }

  /**
   * Reconcile a persisted statement against the app's transactions.
   *
   * Re-running is idempotent: every persisted row is keyed on a natural identity, so a second run
   * over unchanged data rewrites the same rows and never inflates a divergence count.
   */
  reconcile(statementId: string): ReconciliationReport {
    const statement = this.statementImports.getImport(statementId)
    if (!statement) throw new StatementNotFoundError('Extrato não encontrado.')

    const lines = this.statementImports.listLines(statement.id)
    const window = this.candidateWindow(statement, lines)
    const candidates = this.statementImports.listCandidateTransactions(
      statement.financial_account_id,
      window.start,
      window.end,
    )
    const byTransactionId = new Map<string, CandidateTransactionRow>(
      candidates.map(candidate => [candidate.pluggy_transaction_id, candidate]),
    )
    const lineById = new Map(lines.map(line => [line.id, line]))

    const cycleId = statement.statement_cycle_id
    this.statementImports.setImportStatus(statement.id, 'RECONCILING')
    if (cycleId) this.cycles.setReconciliationStatus(cycleId, 'IN_PROGRESS')

    // A re-run recomputes the whole picture. The previous run's derived match rows are dropped and
    // its divergences are closed; whatever is still divergent below re-opens immediately. Nothing
    // that counts as evidence — the statement, its lines, the provider transactions — is touched.
    this.statementImports.clearReconciliations(statement.id)
    this.statementImports.resolveOpenDiscrepancies(statement.id)

    const { results, unmatchedTransactionIds } = matchStatementLines(lines, candidates, this.matching)

    const lineReports: ReconciliationLineReport[] = []
    let matchedTotalCents = 0
    let matchedCount = 0
    let ambiguousCount = 0
    let statementOnlyCount = 0

    for (const result of results) {
      const line = lineById.get(result.lineId)!
      let assignmentApplied = false
      let assignmentRejected: string | null = null

      if (result.chosen && cycleId) {
        // Always writes as STATEMENT_IMPORT. A USER assignment outranks it and the repository
        // rejects the write — a statement can never demote the owner's own correction.
        const assignment = this.cycles.assignTransaction({
          pluggyTransactionId: result.chosen.transactionId,
          statementCycleId: cycleId,
          source: 'STATEMENT_IMPORT',
          confidence: result.chosen.score,
        })
        assignmentApplied = assignment.applied
        assignmentRejected = assignment.applied ? null : (assignment.rejectedReason ?? 'not_applied')
      }

      if (result.chosen) {
        matchedCount += 1
        matchedTotalCents += line.amount_cents
      } else if (result.status === 'AMBIGUOUS') {
        ambiguousCount += 1
      } else {
        statementOnlyCount += 1
      }

      this.statementImports.upsertReconciliation({
        statementImportId: statement.id,
        statementCycleId: cycleId,
        statementLineId: line.id,
        pluggyTransactionId: result.chosen?.transactionId ?? null,
        matchStatus: result.status,
        confidence: result.chosen?.score ?? 0,
        amountDeltaCents: result.chosen
          ? Math.abs(line.amount_cents) - Math.abs(byTransactionId.get(result.chosen.transactionId)?.amount_cents ?? line.amount_cents)
          : 0,
        assignmentApplied,
        assignmentRejected,
        evidence: { candidates: result.candidates },
      })

      if (result.status === 'STATEMENT_ONLY') {
        this.statementImports.upsertDiscrepancy({
          statementImportId: statement.id,
          statementCycleId: cycleId,
          kind: 'STATEMENT_ONLY',
          subjectKey: line.line_hash,
          deltaCents: line.amount_cents,
          detail: { lineId: line.id, date: line.date, descriptionRaw: line.description_raw },
        })
      } else if (result.status === 'AMBIGUOUS') {
        this.statementImports.upsertDiscrepancy({
          statementImportId: statement.id,
          statementCycleId: cycleId,
          kind: 'AMBIGUOUS',
          subjectKey: line.line_hash,
          deltaCents: line.amount_cents,
          detail: { lineId: line.id, candidates: result.candidates.map(candidate => candidate.transactionId) },
        })
      }

      lineReports.push({
        lineId: line.id,
        lineIndex: line.line_index,
        date: line.date,
        descriptionRaw: line.description_raw,
        amountCents: line.amount_cents,
        status: result.status,
        transactionId: result.chosen?.transactionId ?? null,
        confidence: result.chosen?.score ?? 0,
        assignmentApplied,
        assignmentRejected,
      })
    }

    const appOnly = unmatchedTransactionIds
      .map(id => byTransactionId.get(id))
      .filter((row): row is CandidateTransactionRow => row !== undefined)
      .map(row => ({
        transactionId: row.pluggy_transaction_id,
        date: row.date,
        amountCents: row.amount_cents,
        description: row.description_raw || row.description,
      }))

    for (const row of appOnly) {
      this.statementImports.upsertReconciliation({
        statementImportId: statement.id,
        statementCycleId: cycleId,
        statementLineId: null,
        pluggyTransactionId: row.transactionId,
        matchStatus: 'APP_ONLY',
        confidence: 0,
        amountDeltaCents: row.amountCents,
        assignmentApplied: false,
        evidence: { window },
      })
      this.statementImports.upsertDiscrepancy({
        statementImportId: statement.id,
        statementCycleId: cycleId,
        kind: 'APP_ONLY',
        subjectKey: row.transactionId,
        deltaCents: row.amountCents,
        detail: { date: row.date, description: row.description },
      })
    }

    const statementTotalCents = statement.statement_total_cents
    const differenceCents = statementTotalCents == null ? null : statementTotalCents - matchedTotalCents
    if (statementTotalCents != null && differenceCents !== 0) {
      this.statementImports.upsertDiscrepancy({
        statementImportId: statement.id,
        statementCycleId: cycleId,
        kind: 'TOTAL_MISMATCH',
        subjectKey: statement.id,
        deltaCents: differenceCents,
        detail: { statementTotalCents, matchedTotalCents },
      })
    }

    const clean =
      statementOnlyCount === 0 &&
      appOnly.length === 0 &&
      ambiguousCount === 0 &&
      (statementTotalCents == null || differenceCents === 0)

    const cycleStatus = clean ? 'RECONCILED' : 'DISCREPANT'
    const reconciliationStatus = clean ? 'MATCHED' : 'DISCREPANT'
    const now = new Date().toISOString()

    this.statementImports.setImportStatus(statement.id, clean ? 'RECONCILED' : 'DISCREPANT', now)
    if (cycleId) {
      this.cycles.setEffectiveTotal(cycleId, matchedTotalCents)
      this.cycles.setStatus(cycleId, cycleStatus, clean ? now : null)
      this.cycles.setReconciliationStatus(cycleId, reconciliationStatus)
    }

    const discrepancies = this.statementImports
      .listDiscrepancies(statement.id)
      .map(row => ({ kind: row.kind, subjectKey: row.subject_key, deltaCents: row.delta_cents }))

    return {
      statementId: statement.id,
      cycleId: cycleId ?? '',
      competenceMonth: statement.competence_month,
      statementCurrency: statement.statement_currency,
      statementTotalCents,
      matchedTotalCents,
      parsedTotalCents: statement.parsed_total_cents ?? lines.reduce((sum, line) => sum + line.amount_cents, 0),
      differenceCents,
      matchedCount,
      statementOnlyCount,
      appOnlyCount: appOnly.length,
      ambiguousCount,
      lines: lineReports,
      statementOnly: lineReports.filter(report => report.status === 'STATEMENT_ONLY'),
      appOnly,
      discrepancies,
      cycleStatus,
      reconciliationStatus,
    }
  }
}

export { monthKeyFromDate }
