import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

/**
 * Append-only correction ledger.
 *
 * Nothing here ever mutates `financial_transactions.raw_data`. A correction is superseded,
 * never edited, so "what did we believe, when, and who said so" stays answerable forever.
 */

export const CORRECTION_FIELDS = [
  'amount',
  'currency',
  'amount_in_account_currency',
  'category',
  'merchant',
  'economic_owner',
  'responsible',
  'reimbursement',
  'competence_month',
  'statement_cycle',
  'notes',
] as const

export type CorrectionField = (typeof CORRECTION_FIELDS)[number]

export const CORRECTION_SOURCES = ['USER', 'RULE', 'STATEMENT_IMPORT', 'SYSTEM'] as const
export type CorrectionSource = (typeof CORRECTION_SOURCES)[number]

export interface FinancialCorrectionRow {
  id: string
  pluggy_transaction_id: string
  field: CorrectionField
  /** Monotonic insertion order. The audit trail is ordered by this, never by created_at. */
  seq: number
  old_effective_value: string | null
  new_effective_value: string | null
  reason: string | null
  source: CorrectionSource
  actor_id: string | null
  created_at: string
  superseded_at: string | null
}

export interface ApplyCorrectionInput {
  pluggyTransactionId: string
  field: CorrectionField
  /** Canonical string form of the corrected value. `amount` is integer cents as a string. */
  newValue: string | null
  /** Effective value before this correction, captured for audit. */
  oldValue?: string | null
  reason?: string | null
  source?: CorrectionSource
  actorId?: string | null
}

export function isCorrectionField(value: unknown): value is CorrectionField {
  return typeof value === 'string' && (CORRECTION_FIELDS as readonly string[]).includes(value)
}

interface ReimbursementValue {
  paidBy: string | null
  receivableFrom: string | null
  receivableStatus: string | null
}

/**
 * A `reimbursement` correction carries a small JSON object, because settling a receivable is not
 * the same fact as who paid: `{"paidBy": "...", "receivableFrom": "...", "status": "PENDING"}`.
 * Anything else is kept in the ledger but not projected onto the queryable columns.
 */
function parseReimbursementJson(value: string | null | undefined): ReimbursementValue | null {
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
  return { paidBy: str('paidBy'), receivableFrom: str('receivableFrom'), receivableStatus: str('status') ?? str('receivableStatus') }
}

export class CorrectionsRepository {
  constructor(private readonly db: FinanceDb) {}

  /**
   * Supersede the active correction for this (transaction, field) and append the new one.
   * Done in a single transaction so the partial unique index can never see two active rows.
   */
  applyCorrection(input: ApplyCorrectionInput): FinancialCorrectionRow {
    if (!isCorrectionField(input.field)) {
      throw new Error(`Campo de correção não suportado: ${String(input.field)}.`)
    }
    const now = new Date().toISOString()
    const source: CorrectionSource = input.source ?? 'USER'

    const apply = this.db.transaction(() => {
      const previous = this.getActive(input.pluggyTransactionId, input.field)
      if (previous) {
        this.db
          .prepare('UPDATE financial_corrections SET superseded_at = ? WHERE id = ?')
          .run(now, previous.id)
      }
      const id = randomUUID()
      this.db
        .prepare(
          `INSERT INTO financial_corrections
             (id, pluggy_transaction_id, field, old_effective_value, new_effective_value, reason, source, actor_id, created_at, superseded_at)
           VALUES (@id, @pluggyTransactionId, @field, @oldValue, @newValue, @reason, @source, @actorId, @createdAt, NULL)`,
        )
        .run({
          id,
          pluggyTransactionId: input.pluggyTransactionId,
          field: input.field,
          oldValue: input.oldValue ?? previous?.new_effective_value ?? null,
          newValue: input.newValue,
          reason: input.reason ?? null,
          source,
          actorId: input.actorId ?? null,
          createdAt: now,
        })
      return id
    })

    const id = apply()
    return this.getById(id)!
  }

  /** Withdraw a correction without asserting a new value: the effective view falls back to raw. */
  revertCorrection(pluggyTransactionId: string, field: CorrectionField): boolean {
    const active = this.getActive(pluggyTransactionId, field)
    if (!active) return false
    this.db
      .prepare('UPDATE financial_corrections SET superseded_at = ? WHERE id = ?')
      .run(new Date().toISOString(), active.id)
    return true
  }

  getById(id: string): FinancialCorrectionRow | undefined {
    return this.db.prepare('SELECT * FROM financial_corrections WHERE id = ?').get(id) as
      | FinancialCorrectionRow
      | undefined
  }

  getActive(pluggyTransactionId: string, field: CorrectionField): FinancialCorrectionRow | undefined {
    return this.db
      .prepare(
        'SELECT * FROM financial_corrections WHERE pluggy_transaction_id = ? AND field = ? AND superseded_at IS NULL',
      )
      .get(pluggyTransactionId, field) as FinancialCorrectionRow | undefined
  }

  /** All currently-effective corrections for a transaction, keyed by field. */
  listActive(pluggyTransactionId: string): Map<CorrectionField, FinancialCorrectionRow> {
    const rows = this.db
      .prepare(
        'SELECT * FROM financial_corrections WHERE pluggy_transaction_id = ? AND superseded_at IS NULL',
      )
      .all(pluggyTransactionId) as FinancialCorrectionRow[]
    return new Map(rows.map(row => [row.field, row]))
  }

  /** Full auditable history, oldest first, superseded rows included. */
  listHistory(pluggyTransactionId: string): FinancialCorrectionRow[] {
    return this.db
      .prepare(
        'SELECT * FROM financial_corrections WHERE pluggy_transaction_id = ? ORDER BY seq ASC',
      )
      .all(pluggyTransactionId) as FinancialCorrectionRow[]
  }

  /**
   * Project owner-attribution corrections onto the queryable enrichment columns.
   *
   * The ledger stays the source of truth; these columns exist so aggregates and filters ("quem
   * deve o quê") can be answered in SQL. A column is only written when the ledger has something to
   * say about it: an untouched field is left exactly as another module wrote it, and a withdrawn
   * correction (history exists, nothing active) clears the column back to NULL.
   */
  projectAttribution(pluggyTransactionId: string): void {
    const active = this.listActive(pluggyTransactionId)
    const assignments: string[] = []
    const params: unknown[] = []

    const project = (column: string, field: CorrectionField, value: string | null) => {
      if (active.has(field)) {
        assignments.push(`${column} = ?`)
        params.push(value)
        return
      }
      if (this.hasHistory(pluggyTransactionId, field)) {
        assignments.push(`${column} = NULL`)
      }
    }

    project('economic_owner', 'economic_owner', active.get('economic_owner')?.new_effective_value ?? null)
    project('responsible', 'responsible', active.get('responsible')?.new_effective_value ?? null)

    const reimbursement = parseReimbursementJson(active.get('reimbursement')?.new_effective_value)
    project('paid_by', 'reimbursement', reimbursement?.paidBy ?? null)
    project('receivable_from', 'reimbursement', reimbursement?.receivableFrom ?? null)
    project('receivable_status', 'reimbursement', reimbursement?.receivableStatus ?? null)

    if (assignments.length === 0) return

    const now = new Date().toISOString()
    this.db
      .prepare(
        'INSERT INTO financial_transaction_enrichment (pluggy_transaction_id, updated_at) VALUES (?, ?) ON CONFLICT(pluggy_transaction_id) DO NOTHING',
      )
      .run(pluggyTransactionId, now)
    this.db
      .prepare(
        `UPDATE financial_transaction_enrichment SET ${assignments.join(', ')}, updated_at = ? WHERE pluggy_transaction_id = ?`,
      )
      .run(...params, now, pluggyTransactionId)
  }

  private hasHistory(pluggyTransactionId: string, field: CorrectionField): boolean {
    const row = this.db
      .prepare('SELECT 1 AS present FROM financial_corrections WHERE pluggy_transaction_id = ? AND field = ? LIMIT 1')
      .get(pluggyTransactionId, field) as { present: number } | undefined
    return Boolean(row)
  }

  listActiveByField(field: CorrectionField): FinancialCorrectionRow[] {
    return this.db
      .prepare(
        'SELECT * FROM financial_corrections WHERE field = ? AND superseded_at IS NULL ORDER BY seq DESC',
      )
      .all(field) as FinancialCorrectionRow[]
  }
}
