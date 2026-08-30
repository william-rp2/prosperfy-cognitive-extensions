import { describe, expect, it } from 'vitest'

import {
  formatAccountDisplayName,
  formatTransactionAccountContext,
  formatTransactionDisplay,
  formatTransactionType,
  isInfrastructureConnectorName,
  isRawEnumVisible,
  isTechnicalProductName,
  resolveTransactionDisplayInput,
} from '../lib/financePresentation'

describe('financePresentation pt-BR', () => {
  it('traduz enums principais', () => {
    expect(formatTransactionType('CREDIT_PURCHASE')).toBe('Compra no cartão de crédito')
    expect(formatTransactionType('REFUND')).toBe('Estorno')
  })

  it('A. PIX + OUT → PIX enviado', () => {
    expect(
      formatTransactionDisplay({ canonicalType: 'PIX_OUT', paymentMethod: 'PIX', direction: 'OUT' }, 'DEBIT'),
    ).toBe('PIX enviado')
    expect(formatTransactionDisplay({ paymentMethod: 'PIX', direction: 'OUT' }, 'DEBIT')).toBe('PIX enviado')
  })

  it('B. PIX + IN → PIX recebido', () => {
    expect(
      formatTransactionDisplay({ canonicalType: 'PIX_IN', paymentMethod: 'PIX', direction: 'IN' }, 'CREDIT'),
    ).toBe('PIX recebido')
  })

  it('C. PIX OUT não aparece apenas como Despesa', () => {
    const label = formatTransactionDisplay(
      { canonicalType: 'EXPENSE', paymentMethod: 'PIX', direction: 'OUT' },
      'DEBIT',
    )
    expect(label).toBe('PIX enviado')
    expect(label).not.toBe('Despesa')
  })

  it('D. IOF explícito → IOF, nunca Transferência enviada', () => {
    expect(
      formatTransactionDisplay(
        { canonicalType: 'TRANSFER_OUT', paymentMethod: 'TRANSFER', direction: 'OUT' },
        'DEBIT',
        { description: 'IOF OPERACOES DE CREDITO' },
      ),
    ).toBe('IOF')
    expect(
      formatTransactionDisplay({ canonicalType: 'FEE', direction: 'OUT' }, 'DEBIT', { description: 'TARIFA IOF' }),
    ).toBe('IOF')
  })

  it('E. REFUND → Estorno; raw REFUND não visível', () => {
    expect(formatTransactionDisplay({ canonicalType: 'REFUND', paymentMethod: 'CREDIT_CARD', direction: 'IN' }, 'CREDIT')).toBe(
      'Estorno',
    )
    expect(isRawEnumVisible('REFUND')).toBe(true)
    expect(formatTransactionDisplay({ canonicalType: 'REFUND' }, 'CREDIT')).not.toBe('REFUND')
  })

  it('F. alias tem precedência no contexto da movimentação', () => {
    const ctx = formatTransactionAccountContext({
      displayName: 'Cartão C6',
      institutionName: 'C6 Bank',
      canonicalType: 'CREDIT_CARD',
      last4: '5619',
    })
    expect(ctx).toBe('Cartão C6 · •••• 5619')
  })

  it('E. MeuPluggy não aparece como instituição user-facing', () => {
    expect(isInfrastructureConnectorName('MeuPluggy')).toBe(true)
    expect(
      formatAccountDisplayName({
        name: 'BANDEIRADO',
        institutionName: 'MeuPluggy',
        canonicalType: 'CREDIT_CARD',
      }),
    ).toBe('Cartão de crédito')
  })

  it('PIX inferido quando enrichment histórico incompleto', () => {
    const resolved = resolveTransactionDisplayInput(
      { canonicalType: 'EXPENSE', paymentMethod: null, direction: 'OUT' },
      'DEBIT',
      { description: 'PIX ENVIADO JOAO' },
    )
    expect(resolved.canonicalType).toBe('PIX_OUT')
    expect(formatTransactionDisplay(resolved, 'DEBIT', { description: 'PIX ENVIADO JOAO' })).toBe('PIX enviado')
  })

  it('G. alias tem prioridade sobre nome técnico', () => {
    expect(
      formatAccountDisplayName({
        displayName: 'Cartão C6 Black',
        name: 'BANDEIRADO',
        institutionName: 'C6 Bank',
        canonicalType: 'CREDIT_CARD',
      }),
    ).toBe('Cartão C6 Black')
  })

  it('H. transferência comum continua transferência', () => {
    expect(
      formatTransactionDisplay(
        { canonicalType: 'TRANSFER_OUT', paymentMethod: 'TRANSFER', direction: 'OUT' },
        'DEBIT',
        { description: 'TED PARA CONTA POUPANCA' },
      ),
    ).toBe('Transferência enviada')
  })

  it('I. credit purchase continua crédito', () => {
    expect(
      formatTransactionDisplay({ canonicalType: 'DEBIT_PURCHASE', paymentMethod: 'CREDIT_CARD', direction: 'OUT' }, 'DEBIT'),
    ).toBe('Compra no cartão de crédito')
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
})
