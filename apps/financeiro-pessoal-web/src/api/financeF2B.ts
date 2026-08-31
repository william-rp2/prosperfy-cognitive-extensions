import { apiRequest } from '../lib/api'

/**
 * F2B surface client: clarifications, corrections, learned rules, statement cycles,
 * reconciliation and historical onboarding.
 *
 * Same-origin `/api/finance/*` only — the dev-server proxy injects the bearer token
 * server-side (`vite.config.ts`). This module never reads a token client-side.
 */

// ---------------------------------------------------------------------------
// Clarifications
// ---------------------------------------------------------------------------

export type ClarificationStatus = 'open' | 'resolved' | 'dismissed'

export interface Clarification {
  id: string
  transactionId: string
  questionType: string
  status: ClarificationStatus
  priority: number
  questionText: string
  createdAt: string
  resolvedAt: string | null
  resolvedBy: string | null
  resolution: string | null
  deliveryMessageId: string | null
  deliveryChatId: string | null
  firstDeliveredAt: string | null
  lastDeliveredAt: string | null
  deliveryCount: number
  replyMessageId: string | null
  snoozedUntil: string | null
}

export async function fetchClarifications(
  params: { status?: ClarificationStatus; questionType?: string; competenceMonth?: string; limit?: number } = {},
) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value))
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest<{ clarifications: Clarification[]; total: number }>(`/api/finance/clarifications${suffix}`)
}

export async function resolveClarification(
  clarificationId: string,
  body: { replyMessageId: string; actorId?: string; resolution?: string },
) {
  return apiRequest<{ clarification: Clarification; alreadyResolved: boolean }>(
    `/api/finance/clarifications/${encodeURIComponent(clarificationId)}/resolve`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

// ---------------------------------------------------------------------------
// Corrections + effective view
// ---------------------------------------------------------------------------

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

export interface Correction {
  id: string
  transactionId: string
  field: CorrectionField
  oldValue: string | null
  newValue: string | null
  reason: string | null
  source: string
  actorId: string | null
  createdAt: string
  supersededAt: string | null
  active: boolean
}

/** Mirrors `serializeEffective` in `financeCorrectionRoutes.ts`. Amounts are integer cents. */
export interface EffectiveTransaction {
  id: string
  accountId: string
  raw: unknown
  effective: {
    amountCents: { value: number; source: string } | Record<string, unknown>
    currencyCode: { value: string } | Record<string, unknown>
    amountInAccountCurrencyCents: { value: number | null } | Record<string, unknown>
    accountCurrencyCode: unknown
    accountAmountCents: unknown
    currencyConversionMissing: unknown
    category: { value: string | null } | Record<string, unknown>
    merchant: { value: string | null } | Record<string, unknown>
    economicOwner: unknown
    responsible: unknown
    reimbursement: unknown
    notes: { value: string | null } | Record<string, unknown>
  }
  temporal: unknown
  suggestions: unknown
  conflicts: unknown
  discrepancies: unknown
}

export async function fetchEffectiveTransaction(transactionId: string) {
  return apiRequest<EffectiveTransaction>(`/api/finance/transactions/${encodeURIComponent(transactionId)}/effective`)
}

export async function fetchCorrectionHistory(transactionId: string) {
  return apiRequest<{ transactionId: string; history: Correction[]; active: Correction[]; effective: EffectiveTransaction }>(
    `/api/finance/corrections/${encodeURIComponent(transactionId)}`,
  )
}

export async function applyCorrection(body: {
  transactionId: string
  field: CorrectionField
  value: string | number | null
  reason?: string
  source?: 'USER' | 'RULE' | 'STATEMENT_IMPORT' | 'SYSTEM'
  actorId?: string
}) {
  return apiRequest<{ correction: Correction; effective: EffectiveTransaction }>('/api/finance/corrections', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function removeCorrection(transactionId: string, field: CorrectionField) {
  return apiRequest<{ reverted: boolean; effective: EffectiveTransaction }>(
    `/api/finance/corrections/${encodeURIComponent(transactionId)}/${encodeURIComponent(field)}`,
    { method: 'DELETE' },
  )
}

// ---------------------------------------------------------------------------
// Learned merchant rules
// ---------------------------------------------------------------------------

export const RULE_TYPES = ['CURRENCY_HINT', 'CATEGORY', 'ECONOMIC_OWNER', 'RESPONSIBLE', 'REIMBURSEMENT', 'COMPETENCE'] as const
export type MerchantRuleType = (typeof RULE_TYPES)[number]

export const MATCH_KINDS = ['exact', 'normalized', 'anchored'] as const
export type MerchantMatchKind = (typeof MATCH_KINDS)[number]

export interface MerchantRule {
  id: string
  merchantPattern: string
  matchKind: MerchantMatchKind
  scopeAccountId: string | null
  ruleType: MerchantRuleType
  targetValue: string
  mode: 'SUGGEST' | 'TRUSTED'
  active: boolean
  createdBy: string | null
  createdAt: string
  updatedAt: string
  evidence: unknown
}

export async function fetchRules(ruleType?: MerchantRuleType) {
  const suffix = ruleType ? `?ruleType=${encodeURIComponent(ruleType)}` : ''
  const data = await apiRequest<{ rules: MerchantRule[] }>(`/api/finance/rules${suffix}`)
  return data.rules
}

export async function createRule(body: {
  merchantPattern: string
  matchKind?: MerchantMatchKind
  scopeAccountId?: string | null
  ruleType: MerchantRuleType
  targetValue: string
  createdBy?: string
}) {
  return apiRequest<{ rule: MerchantRule }>('/api/finance/rules', { method: 'POST', body: JSON.stringify(body) })
}

export async function promoteRule(ruleId: string, body: { actorId?: string } = {}) {
  return apiRequest<{ rule: MerchantRule }>(`/api/finance/rules/${encodeURIComponent(ruleId)}/promote`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function deleteRule(ruleId: string) {
  return apiRequest<{ deactivated: boolean }>(`/api/finance/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Statement cycles
// ---------------------------------------------------------------------------

export interface StatementCycle {
  id: string
  accountId: string
  source: string
  sourceExternalId: string | null
  label: string | null
  periodStart: string | null
  periodEnd: string | null
  closingDate: string | null
  dueDate: string | null
  competenceMonth: string
  statementCurrency: string
  statementTotalCents: number | null
  effectiveTotalCents: number | null
  status: string
  reconciliationStatus: string
  importedAt: string
  closedAt: string | null
}

export async function fetchCycles(params: { accountId?: string; competenceMonth?: string } = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value)
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const data = await apiRequest<{ cycles: StatementCycle[] }>(`/api/finance/cycles${suffix}`)
  return data.cycles
}

// ---------------------------------------------------------------------------
// Statement import + reconciliation
// ---------------------------------------------------------------------------

export const STATEMENT_SOURCES = ['HERMES_ATTACHMENT', 'FINANCE_EMAIL_ATTACHMENT', 'MANUAL_UPLOAD', 'PLUGGY_BILL'] as const
export type StatementSource = (typeof STATEMENT_SOURCES)[number]

export interface StatementImportResult {
  statementId: string
  cycleId: string
  created: boolean
  competenceMonth: string
  statementCurrency: string
  lineCount: number
  skippedLineCount: number
  parsedTotalCents: number
  statementTotalCents: number | null
  status: string
}

export async function importStatement(body: {
  accountId: string
  source: StatementSource
  competenceMonth: string
  statementTotalCents: number
  rawText?: string
  lines?: unknown[]
  statementCurrency?: string
  fileName?: string
  institutionHint?: string
  cardLast4?: string
  periodStart?: string
  periodEnd?: string
  closingDate?: string
  dueDate?: string
}) {
  return apiRequest<StatementImportResult>('/api/finance/statements/import', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export interface ReconciliationLineReport {
  lineId: string
  lineIndex: number
  date: string | null
  descriptionRaw: string
  amountCents: number
  status: string
  transactionId: string | null
  confidence: number
  assignmentApplied: boolean
  assignmentRejected: string | null
}

export interface ReconciliationReport {
  statementId: string
  cycleId: string
  competenceMonth: string
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
}

export async function reconcileStatement(statementId: string) {
  return apiRequest<ReconciliationReport>(`/api/finance/statements/${encodeURIComponent(statementId)}/reconcile`, {
    method: 'POST',
  })
}

// ---------------------------------------------------------------------------
// Historical onboarding export/import
// ---------------------------------------------------------------------------

export interface OnboardingExportResult {
  exportId: string
  exportVersion: number
  rowCount: number
  csv: string
}

export async function exportOnboardingBatch(
  body: { pluggyItemId?: string; competenceMonth?: string; pluggyAccountId?: string; limit?: number } = {},
) {
  return apiRequest<OnboardingExportResult>('/api/finance/onboarding/export', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export interface OnboardingPlanRow {
  lineNumber: number
  transactionId: string
  outcome?: string
  action?: string
  reason?: string
  exportedUpdatedAt?: string
  changes?: { field: string; newValue: string }[]
}

export type OnboardingImportResponse =
  | { dryRun: true; rows: OnboardingPlanRow[] }
  | { dryRun: false; rows: OnboardingPlanRow[] }

export async function importOnboardingBatch(body: { fileContent: string; dryRun?: boolean; actorId?: string }) {
  return apiRequest<OnboardingImportResponse>('/api/finance/onboarding/import', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
