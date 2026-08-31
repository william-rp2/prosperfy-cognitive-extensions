/**
 * CSV transport for the onboarding/clarification batch workflow (03 + 06 docs).
 * Decision D9 (PLAN.md): CSV, not XLSX — no spreadsheet library is present in this repo's
 * dependency tree, and a pure-JS XLSX writer is materially harder to get right (zip container,
 * shared-strings table, escaping) than a CSV writer/parser is. CSV round-trips cleanly through
 * every spreadsheet tool the owner already uses.
 *
 * Hard rule: this module NEVER emits a secret, token, credential, or full/integral account
 * number. Only an account's display name/alias is emitted — never number_masked, never any
 * raw provider field. See spreadsheetExport.test.ts for the enforcement test.
 */

export const ONBOARDING_EXPORT_COLUMNS = [
  'transaction_id',
  'export_version',
  'updated_at',
  'date',
  'competence_month',
  'institution',
  'account_alias',
  'merchant',
  'original_description',
  'amount',
  'currency',
  'category',
  'economic_owner',
  'responsible',
  'reimbursement',
  'statement_cycle',
  'needs_confirmation',
  'notes',
  'action',
] as const

export type OnboardingExportColumn = (typeof ONBOARDING_EXPORT_COLUMNS)[number]

export interface OnboardingExportRowData {
  transactionId: string
  exportVersion: number
  updatedAt: string
  date: string
  competenceMonth: string | null
  institution: string | null
  accountAlias: string | null
  merchant: string | null
  originalDescription: string | null
  amountCents: number
  currency: string | null
  category: string | null
  economicOwner: string | null
  responsible: string | null
  reimbursement: string | null
  statementCycle: string | null
  needsConfirmation: boolean
  notes: string | null
}

/** Cents -> decimal string, e.g. -12345 -> "-123.45". Never a float — string, exact. */
function centsToDecimalString(cents: number): string {
  const negative = cents < 0
  const abs = Math.abs(cents)
  const whole = Math.floor(abs / 100)
  const frac = String(abs % 100).padStart(2, '0')
  return `${negative ? '-' : ''}${whole}.${frac}`
}

function escapeCsvField(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

function rowToFields(row: OnboardingExportRowData): Record<OnboardingExportColumn, string> {
  return {
    transaction_id: row.transactionId,
    export_version: String(row.exportVersion),
    updated_at: row.updatedAt,
    date: row.date,
    competence_month: row.competenceMonth ?? '',
    institution: row.institution ?? '',
    account_alias: row.accountAlias ?? '',
    merchant: row.merchant ?? '',
    original_description: row.originalDescription ?? '',
    amount: centsToDecimalString(row.amountCents),
    currency: row.currency ?? '',
    category: row.category ?? '',
    economic_owner: row.economicOwner ?? '',
    responsible: row.responsible ?? '',
    reimbursement: row.reimbursement ?? '',
    statement_cycle: row.statementCycle ?? '',
    needs_confirmation: row.needsConfirmation ? 'yes' : 'no',
    notes: row.notes ?? '',
    action: '',
  }
}

export function buildOnboardingCsv(rows: OnboardingExportRowData[]): string {
  const lines = [ONBOARDING_EXPORT_COLUMNS.join(',')]
  for (const row of rows) {
    const fields = rowToFields(row)
    lines.push(ONBOARDING_EXPORT_COLUMNS.map(col => escapeCsvField(fields[col])).join(','))
  }
  return `${lines.join('\r\n')}\r\n`
}
