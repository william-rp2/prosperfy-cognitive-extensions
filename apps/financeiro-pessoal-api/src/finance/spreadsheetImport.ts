import { createHash, randomUUID } from 'node:crypto'

import type { ClarificationsRepository } from './clarificationsRepository.js'
import type { CorrectionField, CorrectionsRepository } from './correctionsRepository.js'
import type { OnboardingRepository } from './onboardingRepository.js'
import { ONBOARDING_EXPORT_COLUMNS, type OnboardingExportColumn } from './spreadsheetExport.js'
import { isMonthKey } from './temporalSemantics.js'

/**
 * Untrusted-input boundary for the onboarding spreadsheet round-trip (06 doc + rule 6 of the
 * F2B brief). Everything in this file treats spreadsheet text as DATA, never as instruction:
 * every cell is matched against a fixed schema and a closed set of allowed values. A cell that
 * does not match is a row-level rejection, never a code path, never something evaluated.
 */

export type EditableField =
  | 'category'
  | 'economic_owner'
  | 'responsible'
  | 'reimbursement'
  | 'competence_month'
  | 'notes'

export const EDITABLE_FIELDS: readonly EditableField[] = [
  'category',
  'economic_owner',
  'responsible',
  'reimbursement',
  'competence_month',
  'notes',
]

export const ACTION_VALUES = ['', 'resolve', 'skip'] as const
export type ImportAction = (typeof ACTION_VALUES)[number]

export interface RawCsvRow {
  lineNumber: number
  fields: Record<OnboardingExportColumn, string>
}

export type ParseResult = { ok: true; rows: RawCsvRow[] } | { ok: false; error: string }

/** Minimal RFC4180 line splitter: handles quoted fields, escaped quotes, CRLF/LF. */
function splitCsvLine(line: string): string[] {
  const fields: string[] = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    if (inQuotes) {
      if (char === '"') {
        if (line[i + 1] === '"') {
          current += '"'
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        current += char
      }
    } else if (char === '"') {
      inQuotes = true
    } else if (char === ',') {
      fields.push(current)
      current = ''
    } else {
      current += char
    }
  }
  fields.push(current)
  return fields
}

/**
 * Parses raw text into schema-checked rows. Rejects outright (no partial parse) if the header
 * does not match the known export columns exactly — a mismatched header means the file is not
 * our export, and guessing column meaning from arbitrary text is exactly the "content as
 * instruction" failure mode this module exists to prevent.
 */
export function parseOnboardingCsv(text: string): ParseResult {
  const lines = text.split(/\r\n|\n|\r/).filter((line, idx, arr) => !(idx === arr.length - 1 && line === ''))
  if (lines.length === 0) return { ok: false, error: 'empty_file' }

  const header = splitCsvLine(lines[0]).map(cell => cell.trim())
  const expected = ONBOARDING_EXPORT_COLUMNS as readonly string[]
  if (header.length !== expected.length || header.some((cell, idx) => cell !== expected[idx])) {
    return { ok: false, error: 'schema_mismatch' }
  }

  const rows: RawCsvRow[] = []
  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i]
    if (line === '') continue
    const cells = splitCsvLine(line)
    if (cells.length !== ONBOARDING_EXPORT_COLUMNS.length) {
      return { ok: false, error: `malformed_row_line_${i + 1}` }
    }
    const fields = {} as Record<OnboardingExportColumn, string>
    ONBOARDING_EXPORT_COLUMNS.forEach((col, idx) => {
      fields[col] = cells[idx]
    })
    rows.push({ lineNumber: i + 1, fields })
  }
  return { ok: true, rows }
}

export interface RowValidationError {
  lineNumber: number
  transactionId: string | null
  code: string
  message: string
}

export interface RowChange {
  field: EditableField
  newValue: string
}

export interface ValidatedRow {
  lineNumber: number
  transactionId: string
  action: ImportAction
  exportedUpdatedAt: string
  changes: RowChange[]
}

export type RowValidationResult = { ok: true; row: ValidatedRow } | { ok: false; error: RowValidationError }

export interface ValidationContext {
  /** True when this transaction id is known/still exists. Stale/unknown ids are rejected. */
  transactionExists(transactionId: string): boolean
}

/** Blank cell = "no change". A non-blank cell is an explicit owner-provided new value. */
export function validateImportRow(raw: RawCsvRow, ctx: ValidationContext): RowValidationResult {
  const transactionId = raw.fields.transaction_id.trim()
  const fail = (code: string, message: string): RowValidationResult => ({
    ok: false,
    error: { lineNumber: raw.lineNumber, transactionId: transactionId || null, code, message },
  })

  if (!transactionId) return fail('missing_transaction_id', 'transaction_id vazio.')
  if (!ctx.transactionExists(transactionId)) {
    return fail('unknown_transaction_id', 'transaction_id desconhecido ou obsoleto.')
  }

  const action = raw.fields.action.trim() as ImportAction
  if (!(ACTION_VALUES as readonly string[]).includes(action)) {
    return fail('invalid_action', `Ação não reconhecida: "${raw.fields.action}".`)
  }

  const competenceMonth = raw.fields.competence_month.trim()
  if (competenceMonth && !isMonthKey(competenceMonth)) {
    return fail('invalid_competence_month', 'competence_month inválido: use AAAA-MM.')
  }

  const reimbursement = raw.fields.reimbursement.trim()
  if (reimbursement) {
    try {
      const parsed = JSON.parse(reimbursement)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not_object')
    } catch {
      return fail('invalid_reimbursement', 'reimbursement deve ser um objeto JSON válido ou vazio.')
    }
  }

  const changes: RowChange[] = []
  for (const field of EDITABLE_FIELDS) {
    const value = raw.fields[field as OnboardingExportColumn].trim()
    if (value !== '') changes.push({ field, newValue: value })
  }

  return {
    ok: true,
    row: {
      lineNumber: raw.lineNumber,
      transactionId,
      action,
      exportedUpdatedAt: raw.fields.updated_at.trim(),
      changes,
    },
  }
}

export type ImportRowOutcome = 'applied' | 'rejected' | 'conflict' | 'skipped'

export interface ImportPlanEntry {
  lineNumber: number
  transactionId: string
  outcome: ImportRowOutcome
  reason?: string
  changes: RowChange[]
  action: ImportAction
}

export interface ImportPlanContext extends ValidationContext {
  /** Current live revision timestamp for staleness comparison (06 doc: stale spreadsheet protection). */
  currentRevision(transactionId: string): string | null
  /**
   * True if this exact row content (same transaction + same edits + same action) was already
   * applied by any prior import run — see computeRowContentKey.
   */
  alreadyApplied(contentKey: string, transactionId: string): boolean
}

/**
 * Pure planning pass: parses + validates + resolves conflict/idempotency, but performs no
 * writes. Used for both dry-run and as the first phase of a real apply, so "dry run" and
 * "what will actually happen" can never drift apart.
 */
export function planImport(text: string, ctx: ImportPlanContext): { plan: ImportPlanEntry[]; parseError?: string } {
  const parsed = parseOnboardingCsv(text)
  if (!parsed.ok) return { plan: [], parseError: parsed.error }

  const plan: ImportPlanEntry[] = []
  for (const raw of parsed.rows) {
    const validated = validateImportRow(raw, ctx)
    if (!validated.ok) {
      plan.push({
        lineNumber: raw.lineNumber,
        transactionId: validated.error.transactionId ?? '',
        outcome: 'rejected',
        reason: validated.error.code,
        changes: [],
        action: '',
      })
      continue
    }

    const row = validated.row
    const contentKey = computeRowContentKey(row.transactionId, row.changes, row.action)

    if (ctx.alreadyApplied(contentKey, row.transactionId)) {
      plan.push({
        lineNumber: row.lineNumber,
        transactionId: row.transactionId,
        outcome: 'skipped',
        reason: 'already_applied',
        changes: row.changes,
        action: row.action,
      })
      continue
    }

    if (row.action === 'skip') {
      plan.push({
        lineNumber: row.lineNumber,
        transactionId: row.transactionId,
        outcome: 'skipped',
        reason: 'owner_skip',
        changes: [],
        action: row.action,
      })
      continue
    }

    if (row.changes.length === 0 && row.action === '') {
      plan.push({
        lineNumber: row.lineNumber,
        transactionId: row.transactionId,
        outcome: 'skipped',
        reason: 'no_op',
        changes: [],
        action: row.action,
      })
      continue
    }

    const revision = ctx.currentRevision(row.transactionId)
    if (row.exportedUpdatedAt && revision && revision > row.exportedUpdatedAt) {
      plan.push({
        lineNumber: row.lineNumber,
        transactionId: row.transactionId,
        outcome: 'conflict',
        reason: 'stale_export',
        changes: row.changes,
        action: row.action,
      })
      continue
    }

    plan.push({
      lineNumber: row.lineNumber,
      transactionId: row.transactionId,
      outcome: 'applied',
      changes: row.changes,
      action: row.action,
    })
  }

  return { plan }
}

const ATTRIBUTION_FIELDS = new Set<EditableField>(['economic_owner', 'responsible', 'reimbursement'])

/**
 * Idempotency key for one row's effect: same transaction + same edited values + same action
 * always hashes to the same key, so reimporting an unchanged row from any file (the same
 * export, a re-download of it, a second copy) never applies twice — even across different
 * import runs. This is stronger than a whole-file hash, which would treat "owner fixed one
 * unrelated row" as a reason to reapply every other unchanged row too.
 */
export function computeRowContentKey(transactionId: string, changes: RowChange[], action: ImportAction): string {
  const sorted = [...changes].sort((a, b) => a.field.localeCompare(b.field))
  const payload = JSON.stringify({ transactionId, action, sorted })
  return createHash('sha256').update(payload).digest('hex')
}

export interface ApplyDeps {
  corrections: CorrectionsRepository
  clarifications: ClarificationsRepository
  onboarding: OnboardingRepository
  actorId: string | null
  reason: string
}

export interface ApplyRowResult {
  lineNumber: number
  transactionId: string
  outcome: ImportRowOutcome
  reason?: string
}

/**
 * Executes an already-planned import. Never re-derives validation — a row's outcome was
 * decided by `planImport`; this function only performs (or idempotently skips) the write.
 */
export function applyImportPlan(plan: ImportPlanEntry[], deps: ApplyDeps): ApplyRowResult[] {
  const results: ApplyRowResult[] = []

  for (const entry of plan) {
    if (entry.outcome !== 'applied') {
      results.push({ lineNumber: entry.lineNumber, transactionId: entry.transactionId, outcome: entry.outcome, reason: entry.reason })
      continue
    }

    const contentKey = computeRowContentKey(entry.transactionId, entry.changes, entry.action)
    const existing = deps.onboarding.getImportRow(contentKey, entry.transactionId)
    if (existing) {
      results.push({
        lineNumber: entry.lineNumber,
        transactionId: entry.transactionId,
        outcome: existing.status,
        reason: 'already_applied',
      })
      continue
    }

    for (const change of entry.changes) {
      deps.corrections.applyCorrection({
        pluggyTransactionId: entry.transactionId,
        field: change.field as CorrectionField,
        newValue: change.newValue,
        reason: deps.reason,
        source: 'STATEMENT_IMPORT',
        actorId: deps.actorId,
      })
    }
    if (entry.changes.some(c => ATTRIBUTION_FIELDS.has(c.field))) {
      deps.corrections.projectAttribution(entry.transactionId)
    }

    if (entry.action === 'resolve') {
      const marker = `import:${contentKey}:${randomUUID()}`
      for (const open of deps.clarifications.listOpenForTransaction(entry.transactionId)) {
        deps.clarifications.resolve(open.id, {
          replyMessageId: marker,
          resolvedBy: deps.actorId,
          resolution: 'onboarding_spreadsheet_import',
        })
      }
    }

    deps.onboarding.recordImportRow({
      importBatchId: contentKey,
      pluggyTransactionId: entry.transactionId,
      action: entry.action || 'update',
      status: 'applied',
      appliedAt: new Date().toISOString(),
    })

    results.push({ lineNumber: entry.lineNumber, transactionId: entry.transactionId, outcome: 'applied' })
  }

  return results
}
