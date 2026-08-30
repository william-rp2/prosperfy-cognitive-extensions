import { describe, expect, it } from 'vitest'

import type { FinanceAccount, FinanceTransaction } from '../api/finance'
import { accountFilterLabel, filterAccounts, filterTransactions, uniqueInstitutions } from './transactionFilters'

const accounts: FinanceAccount[] = [
  {
    id: 'c6-a',
    itemId: 'i1',
    institutionName: 'C6 Bank',
    sourceType: 'CREDIT',
    sourceSubtype: 'CREDIT_CARD',
    canonicalType: 'CREDIT_CARD',
    name: 'BANDEIRADO',
    displayName: 'C6 — William físico',
    last4: '5619',
    balance: -100,
    creditLimit: 5000,
    availableCreditLimit: 4900,
    lastSyncedAt: null,
  },
  {
    id: 'c6-b',
    itemId: 'i1',
    institutionName: 'C6 Bank',
    sourceType: 'CREDIT',
    sourceSubtype: 'CREDIT_CARD',
    canonicalType: 'CREDIT_CARD',
    name: 'BANDEIRADO',
    displayName: 'C6 — Virtual',
    last4: '1234',
    balance: -50,
    creditLimit: 3000,
    availableCreditLimit: 2950,
    lastSyncedAt: null,
  },
]

describe('transactionFilters', () => {
  it('H/P. dois cartões C6 permanecem separados no autocomplete', () => {
    const labels = accounts.map(accountFilterLabel)
    expect(labels).toContain('C6 Bank — C6 — William físico · •••• 5619')
    expect(labels).toContain('C6 Bank — C6 — Virtual · •••• 1234')
    expect(new Set(labels).size).toBe(2)
  })

  it('N. autocomplete instituição lista C6 Bank', () => {
    expect(uniqueInstitutions(accounts)).toEqual(['C6 Bank'])
  })

  it('M. busca encontra transaction por note', () => {
    const accountById = new Map(accounts.map(a => [a.id, a]))
    const rows: FinanceTransaction[] = [
      {
        id: 'tx-1',
        source: 'pluggy',
        accountId: 'c6-a',
        date: '2026-08-01',
        description: 'Mercado',
        amount: -20,
        currencyCode: 'BRL',
        type: 'DEBIT',
        status: 'POSTED',
        categoryOriginal: null,
        category: null,
        merchant: null,
        note: 'Compra Prosperfy',
        enrichment: { canonicalType: 'EXPENSE', direction: 'OUT', classificationStatus: 'classified', classificationSource: 'rules', categoryName: null },
      },
    ]
    const filtered = filterTransactions(rows, { ...emptyFilters(), q: 'Prosperfy' }, accountById)
    expect(filtered).toHaveLength(1)
  })

  it('P. filtro por conta não agrega cartões distintos', () => {
    const filtered = filterAccounts(accounts, '5619')
    expect(filtered).toHaveLength(1)
    expect(filtered[0]?.id).toBe('c6-a')
  })
})

function emptyFilters() {
  return {
    q: '',
    institution: '',
    accountId: '',
    movementType: '',
    category: '',
    direction: '' as const,
    dateFrom: '',
    dateTo: '',
    minAmount: '',
    maxAmount: '',
  }
}
