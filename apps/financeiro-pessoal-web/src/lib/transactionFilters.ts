import type { FinanceAccount, FinanceTransaction } from '../api/finance'
import { formatTransactionDisplay, isInfrastructureConnectorName } from './financePresentation'

export interface TransactionFilterState {
  q: string
  institution: string
  accountId: string
  movementType: string
  category: string
  direction: '' | 'IN' | 'OUT'
  dateFrom: string
  dateTo: string
  minAmount: string
  maxAmount: string
}

export function filterTransactions(
  rows: FinanceTransaction[],
  filters: TransactionFilterState,
  accountById: Map<string, FinanceAccount>,
): FinanceTransaction[] {
  const q = filters.q.trim().toLowerCase()

  return rows.filter(tx => {
    const account = tx.accountId ? accountById.get(tx.accountId) : undefined
    const institution = account?.institutionName ?? ''
    const alias = account?.displayName ?? ''
    const typeLabel = formatTransactionDisplay(tx.enrichment, tx.type, {
      description: tx.description,
      accountCanonicalType: account?.canonicalType,
    })

    if (filters.institution && institution !== filters.institution) return false
    if (filters.accountId && tx.accountId !== filters.accountId) return false
    if (filters.movementType && typeLabel !== filters.movementType) return false
    if (filters.category) {
      const cat = tx.category?.name ?? tx.enrichment?.categoryName ?? ''
      if (cat !== filters.category) return false
    }
    if (filters.direction === 'IN' && tx.type !== 'CREDIT') return false
    if (filters.direction === 'OUT' && tx.type !== 'DEBIT') return false
    if (filters.dateFrom && tx.date.slice(0, 10) < filters.dateFrom) return false
    if (filters.dateTo && tx.date.slice(0, 10) > filters.dateTo) return false
    const amount = Math.abs(tx.amount ?? 0)
    if (filters.minAmount && amount < Number(filters.minAmount)) return false
    if (filters.maxAmount && amount > Number(filters.maxAmount)) return false

    if (q) {
      const haystack = [
        tx.description,
        tx.merchant,
        tx.enrichment?.merchantNormalized,
        tx.note,
        alias,
        institution,
        typeLabel,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(q)) return false
    }

    return true
  })
}

export function uniqueInstitutions(accounts: FinanceAccount[]): string[] {
  const set = new Set<string>()
  for (const account of accounts) {
    const name = account.institutionName?.trim()
    if (!name || isInfrastructureConnectorName(name)) continue
    set.add(name)
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'pt-BR'))
}

export function accountFilterLabel(account: FinanceAccount): string {
  const inst = account.institutionName && !isInfrastructureConnectorName(account.institutionName)
    ? account.institutionName
    : ''
  const name = account.displayName ?? account.name ?? 'Conta'
  const last4 = account.last4 ? ` · •••• ${account.last4}` : ''
  return inst ? `${inst} — ${name}${last4}` : `${name}${last4}`
}

export function filterAccounts(accounts: FinanceAccount[], q: string): FinanceAccount[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return accounts
  return accounts.filter(account => {
    const haystack = [
      account.displayName,
      account.name,
      account.marketingName,
      account.institutionName,
      account.canonicalType,
      account.last4,
      account.cardBrand,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(needle)
  })
}
