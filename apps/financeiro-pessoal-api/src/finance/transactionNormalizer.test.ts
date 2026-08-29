import { describe, expect, it } from 'vitest'

import { normalizePluggyTransaction } from './transactionNormalizer.js'

describe('transactionNormalizer', () => {
  it('classifica PIX de entrada e saída', () => {
    const pixIn = normalizePluggyTransaction({
      pluggyType: 'CREDIT',
      amountCents: 10000,
      description: 'PIX recebido de João',
    })
    expect(pixIn.canonicalType).toBe('PIX_IN')
    expect(pixIn.direction).toBe('IN')

    const pixOut = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -5000,
      description: 'PIX enviado mercado',
    })
    expect(pixOut.canonicalType).toBe('PIX_OUT')
    expect(pixOut.direction).toBe('OUT')
  })

  it('classifica débito, crédito e transferência', () => {
    const debit = normalizePluggyTransaction({ pluggyType: 'DEBIT', amountCents: -2000, description: 'Compra débito' })
    expect(debit.canonicalType).toBe('DEBIT_PURCHASE')

    const credit = normalizePluggyTransaction({
      pluggyType: 'CREDIT',
      amountCents: 3000,
      description: 'Compra cartão',
      rawData: { paymentData: { paymentMethod: 'CREDIT' } },
    })
    expect(credit.canonicalType).toBe('CREDIT_PURCHASE')

    const transfer = normalizePluggyTransaction({ pluggyType: 'DEBIT', amountCents: -1000, description: 'TED transferência' })
    expect(transfer.canonicalType).toBe('TRANSFER_OUT')
  })

  it('preserva OTHER quando não há evidência suficiente', () => {
    const unknown = normalizePluggyTransaction({ pluggyType: 'DEBIT', amountCents: -100, description: 'Lançamento' })
    expect(unknown.canonicalType).toBe('DEBIT_PURCHASE')
    expect(unknown.rawType).toBe('DEBIT')
  })
})
