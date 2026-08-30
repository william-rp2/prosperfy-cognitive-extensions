import { describe, expect, it } from 'vitest'

import {
  formatAccountDisplayName,
  formatPaymentMethod,
  formatTransactionDisplay,
  formatTransactionType,
  isRawEnumVisible,
  isTechnicalProductName,
} from '../lib/financePresentation'

describe('financePresentation pt-BR', () => {
  it('traduz enums principais', () => {
    expect(formatTransactionType('CREDIT_PURCHASE')).toBe('Compra no cartão de crédito')
    expect(formatPaymentMethod('CREDIT_CARD')).toBe('Compra no cartão de crédito')
    expect(formatPaymentMethod('UNKNOWN')).toBe('Não identificado')
  })

  it('usa payment method na exibição de transação', () => {
    expect(formatTransactionDisplay({ canonicalType: 'DEBIT_PURCHASE', paymentMethod: 'CREDIT_CARD' }, 'DEBIT')).toBe(
      'Compra no cartão de crédito',
    )
    expect(formatTransactionDisplay({ canonicalType: 'EXPENSE', paymentMethod: 'UNKNOWN' }, 'DEBIT')).toBe('Não identificado')
  })

  it('BANDEIRADO não aparece como nome amigável', () => {
    expect(isTechnicalProductName('BANDEIRADO')).toBe(true)
    expect(
      formatAccountDisplayName({
        name: 'BANDEIRADO',
        institutionName: 'Bradesco',
        canonicalType: 'CREDIT_CARD',
      }),
    ).toBe('Bradesco — Cartão de crédito')
    expect(isRawEnumVisible('BANDEIRADO')).toBe(true)
  })

  it('alias tem prioridade sobre nome técnico', () => {
    expect(
      formatAccountDisplayName({
        displayName: 'Cartão C6 Black',
        name: 'BANDEIRADO',
        institutionName: 'C6 Bank',
        canonicalType: 'CREDIT_CARD',
      }),
    ).toBe('Cartão C6 Black')
  })
})
