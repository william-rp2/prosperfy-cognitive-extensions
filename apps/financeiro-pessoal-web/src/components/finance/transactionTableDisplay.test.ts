import { describe, expect, it } from 'vitest'

import type { FinanceAccount, FinanceTransaction } from '../../api/finance'
import { transactionTypeLabel } from './TransactionTypeCell'
import { formatTransactionAccountContext } from '../../lib/financePresentation'

/** Real API-shaped fixtures consumed by ConnectedTransactionsScreen. */
function pluggyTx(overrides: Partial<FinanceTransaction> = {}): FinanceTransaction {
  return {
    id: 'tx-1',
    source: 'pluggy',
    accountId: 'card-c6',
    date: '2026-08-15T12:00:00.000Z',
    description: '',
    merchant: null,
    amount: -50,
    currencyCode: 'BRL',
    type: 'DEBIT',
    status: 'POSTED',
    categoryOriginal: null,
    category: null,
    enrichment: null,
    ...overrides,
  }
}

const c6Card: FinanceAccount = {
  id: 'card-c6',
  itemId: 'item-1',
  institutionName: 'C6 Bank',
  sourceType: 'CREDIT',
  sourceSubtype: 'CREDIT_CARD',
  canonicalType: 'CREDIT_CARD',
  name: 'BANDEIRADO',
  displayName: 'C6 — William físico',
  last4: '5619',
  cardBrand: 'Visa',
  balance: -500,
  creditLimit: 10000,
  availableCreditLimit: 9500,
  lastSyncedAt: null,
}

describe('ConnectedTransactionsScreen table semantics (real API shape)', () => {
  it('A. IOF → IOF mesmo com enrichment histórico incompleto', () => {
    const tx = pluggyTx({
      description: 'IOF OPERACOES DE CREDITO',
      enrichment: { canonicalType: 'EXPENSE', direction: 'OUT', paymentMethod: null, classificationStatus: 'classified', classificationSource: 'rules', categoryName: null },
    })
    expect(transactionTypeLabel(tx, c6Card)).toBe('IOF')
  })

  it('B. PIX OUT → PIX enviado sem payment_method persistido', () => {
    const tx = pluggyTx({
      description: 'PIX ENVIADO PARA MARIA',
      type: 'DEBIT',
      enrichment: { canonicalType: 'EXPENSE', direction: 'OUT', paymentMethod: null, classificationStatus: 'classified', classificationSource: 'rules', categoryName: null },
    })
    expect(transactionTypeLabel(tx, c6Card)).toBe('PIX enviado')
  })

  it('C. PIX IN → PIX recebido', () => {
    const tx = pluggyTx({
      description: 'PIX RECEBIDO',
      type: 'CREDIT',
      amount: 100,
      enrichment: { canonicalType: 'INCOME', direction: 'IN', paymentMethod: null, classificationStatus: 'classified', classificationSource: 'rules', categoryName: null },
    })
    expect(transactionTypeLabel(tx, c6Card)).toBe('PIX recebido')
  })

  it('D. REFUND → Estorno', () => {
    const tx = pluggyTx({
      description: 'ESTORNO COMPRA',
      type: 'CREDIT',
      amount: 50,
      enrichment: { canonicalType: 'REFUND', direction: 'IN', paymentMethod: 'CREDIT_CARD', classificationStatus: 'classified', classificationSource: 'rules', categoryName: null },
    })
    expect(transactionTypeLabel(tx, c6Card)).toBe('Estorno')
  })

  it('contexto de conta não usa MeuPluggy', () => {
    const ctx = formatTransactionAccountContext({
      displayName: 'C6 — William físico',
      institutionName: 'MeuPluggy',
      canonicalType: 'CREDIT_CARD',
      last4: '5619',
      cardBrand: 'Visa',
    })
    expect(ctx).toBe('C6 — William físico · Visa · •••• 5619')
    expect(ctx).not.toMatch(/pluggy/i)
  })
})
