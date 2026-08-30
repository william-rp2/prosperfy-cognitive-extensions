import { describe, expect, it } from 'vitest'

import { formatMoney, formatTransactionAmount } from './moneyFormat'

describe('moneyFormat', () => {
  it('A. USD 20,00 original e R$ 109,54 convertido', () => {
    const formatted = formatTransactionAmount({
      amount: 20,
      currencyCode: 'USD',
      amountInAccountCurrency: 109.54,
      accountCurrencyCode: 'BRL',
    })
    expect(formatted.primary).toMatch(/US\$/)
    expect(formatted.primary).toContain('20')
    expect(formatted.secondary).toMatch(/R\$/)
    expect(formatted.secondary).toContain('109,54')
  })

  it('B. BRL permanece BRL', () => {
    expect(formatMoney(100, 'BRL')).toMatch(/R\$/)
    const formatted = formatTransactionAmount({
      amount: 100,
      currencyCode: 'BRL',
      accountCurrencyCode: 'BRL',
    })
    expect(formatted.secondary).toBeNull()
  })

  it('C. USD sem conversão indica indisponível', () => {
    const formatted = formatTransactionAmount({
      amount: 20,
      currencyCode: 'USD',
      accountCurrencyCode: 'BRL',
      currencyConversionMissing: true,
    })
    expect(formatted.secondary).toBe('conversão indisponível')
  })

  it('E. não hardcode BRL para USD', () => {
    expect(formatMoney(20, 'USD')).not.toMatch(/^R\$/)
  })
})
