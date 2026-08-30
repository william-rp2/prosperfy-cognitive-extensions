import { describe, expect, it } from 'vitest'

import { normalizePluggyTransaction } from './transactionNormalizer.js'

describe('transactionNormalizer — payment semantics', () => {
  it('CREDIT_CARD asset + raw DEBIT → compra no crédito, não débito', () => {
    const purchase = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -5000,
      description: 'Compra mercado',
      accountCanonicalType: 'CREDIT_CARD',
    })
    expect(purchase.canonicalType).toBe('CREDIT_PURCHASE')
    expect(purchase.paymentMethod).toBe('CREDIT_CARD')
    expect(purchase.direction).toBe('OUT')
  })

  it('checking account + debit-card evidence → débito', () => {
    const debit = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -2000,
      description: 'Compra débito',
      accountCanonicalType: 'CHECKING_ACCOUNT',
      rawData: { paymentData: { paymentMethod: 'DEBIT_CARD' } },
    })
    expect(debit.canonicalType).toBe('DEBIT_PURCHASE')
    expect(debit.paymentMethod).toBe('DEBIT_CARD')
  })

  it('OUT sem evidência de pagamento → fail-safe, não inventa débito', () => {
    const unknown = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -100,
      description: 'Lançamento',
      accountCanonicalType: 'CHECKING_ACCOUNT',
    })
    expect(unknown.canonicalType).toBe('EXPENSE')
    expect(unknown.paymentMethod).toBe('UNKNOWN')
    expect(unknown.rawType).toBe('DEBIT')
  })

  it('PIX out → PIX', () => {
    const pixOut = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -5000,
      description: 'PIX enviado mercado',
      accountCanonicalType: 'CHECKING_ACCOUNT',
    })
    expect(pixOut.canonicalType).toBe('PIX_OUT')
    expect(pixOut.paymentMethod).toBe('PIX')
  })

  it('transfer out → transferência', () => {
    const transfer = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -1000,
      description: 'TED transferência',
      accountCanonicalType: 'CHECKING_ACCOUNT',
    })
    expect(transfer.canonicalType).toBe('TRANSFER_OUT')
    expect(transfer.paymentMethod).toBe('TRANSFER')
  })

  it('direction OUT não determina payment_method sozinho', () => {
    const row = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -3000,
      description: 'Serviço',
      accountCanonicalType: 'PAYMENT_ACCOUNT',
    })
    expect(row.direction).toBe('OUT')
    expect(row.paymentMethod).toBe('UNKNOWN')
    expect(row.canonicalType).not.toBe('DEBIT_PURCHASE')
  })
})

describe('transactionNormalizer — legacy cases', () => {
  it('classifica PIX de entrada e saída', () => {
    const pixIn = normalizePluggyTransaction({
      pluggyType: 'CREDIT',
      amountCents: 10000,
      description: 'PIX recebido de João',
    })
    expect(pixIn.canonicalType).toBe('PIX_IN')
    expect(pixIn.direction).toBe('IN')
  })

  it('classifica crédito com paymentMethod explícito em conta cartão', () => {
    const credit = normalizePluggyTransaction({
      pluggyType: 'DEBIT',
      amountCents: -3000,
      description: 'Compra cartão',
      rawData: { paymentData: { paymentMethod: 'CREDIT' } },
      accountCanonicalType: 'CREDIT_CARD',
    })
    expect(credit.canonicalType).toBe('CREDIT_PURCHASE')
    expect(credit.paymentMethod).toBe('CREDIT_CARD')
  })
})
