import { apiRequest } from '../lib/api'

export interface FinanceSummary {
  month: string
  totalBalance: number | null
  cashBalance: number | null
  investmentBalance: number | null
  financialWealth: number | null
  monthIncome: number | null
  monthExpense: number | null
  monthResult: number | null
  openCardBalance: number | null
  creditCardLimitTotal: number | null
  lastSync: string | null
}

export interface FinanceTransaction {
  id: string
  source: 'pluggy' | 'manual'
  accountId: string | null
  description: string | null
  descriptionRaw?: string | null
  amount: number | null
  currencyCode: string | null
  amountInAccountCurrency?: number | null
  accountCurrencyCode?: string | null
  currencyConversionMissing?: boolean
  date: string
  type: string | null
  status: string | null
  categoryOriginal: string | null
  category: { id: string; name: string; kind: string } | null
  merchant: string | null
  enrichment?: {
    merchantNormalized?: string | null
    canonicalType: string | null
    direction: string | null
    paymentMethod?: string | null
    classificationStatus: string | null
    classificationSource: string | null
    categoryName: string | null
  } | null
  note?: string | null
}

export interface FinanceBill {
  id: string
  accountId: string
  dueDate: string | null
  closingDate: string | null
  totalAmount: number | null
  minimumPayment: number | null
  currencyCode: string | null
}

export interface FinanceAccount {
  id: string
  itemId: string
  institutionName?: string | null
  sourceType: string | null
  sourceSubtype: string | null
  canonicalType: string | null
  name: string | null
  marketingName?: string | null
  displayName?: string | null
  displayAlias?: string | null
  isFavorite?: boolean
  responsibleLabel?: string | null
  cardBrand?: string | null
  last4?: string | null
  balance: number | null
  creditLimit: number | null
  availableCreditLimit: number | null
  numberMasked?: string | null
  lastSyncedAt: string | null
}

export interface FinanceAsset {
  id: string
  itemId: string
  institutionName?: string | null
  canonicalType: string | null
  name: string | null
  marketingName?: string | null
  displayName?: string | null
  displayAlias?: string | null
  isFavorite?: boolean
  balance: number | null
  creditLimit?: number | null
  availableCreditLimit?: number | null
  numberMasked?: string | null
  lastSyncedAt: string | null
}

export interface FinanceIntegrationItem {
  id: string
  idMasked: string
  connectorName: string | null
  status: string
  lastSyncedAt: string | null
  errorSummary: string | null
  groups: {
    cashAccounts: FinanceAsset[]
    creditCards: FinanceAsset[]
    investments: FinanceAsset[]
    other: FinanceAsset[]
  }
}

export interface FinanceBudget {
  id: string
  month: string
  category: { id: string; name: string; kind: string } | null
  limitAmount: number | null
  spentAmount: number | null
  remainingAmount: number | null
  status: string
}

export interface FinanceIntegrationsResponse {
  items: FinanceIntegrationItem[]
  sync: {
    enabled: boolean
    intervalMinutes: number
    nextRunAt: string | null
    latestRun: { status: string; started_at: string } | null
  }
}

export interface FinanceSyncStatus {
  syncEnabled: boolean
  syncIntervalMinutes: number
  nextSync: string | null
  latest: { status: string; started_at: string } | null
}

export async function fetchSummary(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : ''
  return apiRequest<FinanceSummary>(`/api/finance/summary${query}`)
}

export async function fetchTransactions(params: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const data = await apiRequest<{ transactions: FinanceTransaction[] }>(`/api/finance/transactions${suffix}`)
  return data.transactions
}

export async function fetchBills() {
  const data = await apiRequest<{ bills: FinanceBill[] }>('/api/finance/bills')
  return data.bills
}

export async function fetchAccounts() {
  const data = await apiRequest<{ accounts: FinanceAccount[] }>('/api/finance/accounts')
  return data.accounts
}

export async function fetchBudgets(month: string) {
  const data = await apiRequest<{ month: string; budgets: FinanceBudget[] }>(`/api/finance/budgets?month=${encodeURIComponent(month)}`)
  return data.budgets
}

export async function fetchIntegrations() {
  return apiRequest<FinanceIntegrationsResponse>('/api/finance/integrations')
}

export async function fetchSyncStatus() {
  return apiRequest<FinanceSyncStatus>('/api/finance/sync/status')
}

export async function triggerSync() {
  return apiRequest<{ success: boolean; status: string }>('/api/finance/sync', { method: 'POST', body: JSON.stringify({}) })
}

export async function updateTransactionCategory(body: {
  transactionId: string
  source: 'pluggy' | 'manual'
  categoryId?: string
  category?: string
}) {
  return apiRequest('/api/finance/transactions/category', { method: 'PATCH', body: JSON.stringify(body) })
}

export async function addExistingConnection(itemId: string) {
  return apiRequest<{
    success: boolean
    outcome: string
    message: string
    connectorName: string | null
    syncStatus: string | null
  }>('/api/finance/integrations/add-existing', {
    method: 'POST',
    body: JSON.stringify({ itemId }),
  })
}

export async function updateAccountPreferences(
  accountId: string,
  body: { displayAlias?: string | null; isFavorite?: boolean; responsibleLabel?: string | null },
) {
  return apiRequest<{ account: FinanceAccount; preferences: { displayAlias: string | null; isFavorite: boolean; responsibleLabel?: string | null } }>(
    `/api/finance/accounts/${encodeURIComponent(accountId)}/preferences`,
    { method: 'PATCH', body: JSON.stringify(body) },
  )
}

export async function upsertTransactionAnnotation(transactionId: string, note: string) {
  return apiRequest<{ note: string; updatedAt: string }>(
    `/api/finance/transactions/${encodeURIComponent(transactionId)}/annotation`,
    { method: 'PUT', body: JSON.stringify({ note }) },
  )
}

export async function deleteTransactionAnnotation(transactionId: string) {
  return apiRequest<{ deleted: boolean }>(
    `/api/finance/transactions/${encodeURIComponent(transactionId)}/annotation`,
    { method: 'DELETE' },
  )
}

export async function createManualTransaction(body: {
  amount: number
  direction: 'income' | 'expense'
  description: string
  date?: string
  category?: string
}) {
  return apiRequest('/api/finance/transactions/manual', { method: 'POST', body: JSON.stringify(body) })
}
