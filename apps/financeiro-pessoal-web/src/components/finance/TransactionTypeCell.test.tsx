import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { FinanceAccount, FinanceTransaction } from '../../api/finance'
import { diagnoseTransactionDisplay } from '../../lib/financePresentation'
import { TransactionTypeCell } from './TransactionTypeCell'

/** Live-shaped fixture: TX prefix 1b8e14d2 — canonical PIX_OUT */
const LIVE_PIX_OUT: FinanceTransaction = {
  id: '1b8e14d2-0000-4000-8000-000000000001',
  source: 'pluggy',
  accountId: 'c6-checking',
  date: '2026-08-10T12:00:00.000Z',
  description: 'PIX ENVIADO - DES ...',
  descriptionRaw: 'PIX ENVIADO - DES ...',
  merchant: null,
  amount: -120,
  currencyCode: 'BRL',
  type: 'DEBIT',
  status: 'POSTED',
  categoryOriginal: null,
  category: null,
  enrichment: {
    canonicalType: 'PIX_OUT',
    paymentMethod: 'PIX',
    direction: 'OUT',
    classificationStatus: 'classified',
    classificationSource: 'rules',
    categoryName: null,
  },
}

/** Live-shaped fixture: TX prefix 7fad9739 — canonical FEE, IOF in description_raw only */
const LIVE_IOF: FinanceTransaction = {
  id: '7fad9739-0000-4000-8000-000000000002',
  source: 'pluggy',
  accountId: 'c6-credit',
  date: '2026-08-11T12:00:00.000Z',
  description: 'LIMITE CONTA',
  descriptionRaw: 'IOF LIMITE CONTA',
  merchant: null,
  amount: -3.5,
  currencyCode: 'BRL',
  type: 'DEBIT',
  status: 'POSTED',
  categoryOriginal: null,
  category: null,
  enrichment: {
    canonicalType: 'FEE',
    paymentMethod: 'UNKNOWN',
    direction: 'OUT',
    classificationStatus: 'classified',
    classificationSource: 'rules',
    categoryName: null,
  },
}

const creditCard: FinanceAccount = {
  id: 'c6-credit',
  itemId: 'item-c6',
  institutionName: 'C6 Bank',
  sourceType: 'CREDIT',
  sourceSubtype: 'CREDIT_CARD',
  canonicalType: 'CREDIT_CARD',
  name: 'BANDEIRADO',
  displayAlias: 'C6 — William físico',
  displayName: 'C6 — William físico',
  cardBrand: 'MASTERCARD',
  last4: '5619',
  balance: -500,
  creditLimit: 10000,
  availableCreditLimit: 9500,
  lastSyncedAt: null,
}

function renderCell(
  transaction: FinanceTransaction,
  account: FinanceAccount | null = creditCard,
): { label: string; context: string | null; html: string } {
  const html = renderToStaticMarkup(
    <TransactionTypeCell account={account} transaction={transaction} />,
  )
  const labelMatch = html.match(/data-testid="transaction-type-label"[^>]*>([^<]+)</)
  const contextMatch = html.match(/data-testid="transaction-account-context"[^>]*>([^<]+)</)
  return {
    html,
    label: labelMatch?.[1] ?? '',
    context: contextMatch?.[1] ?? null,
  }
}

describe('TransactionTypeCell — live render path', () => {
  it('REAL_UI_PIX_BEFORE: snake_case enrichment renderizava Despesa', () => {
    const broken: FinanceTransaction = {
      ...LIVE_PIX_OUT,
      enrichment: {
        canonical_type: 'PIX_OUT',
        payment_method: 'PIX',
        direction: 'OUT',
      } as unknown as FinanceTransaction['enrichment'],
    }
    const before = renderCell(broken)
    expect(before.label).toBe('PIX enviado')
    expect(before.label).not.toBe('Despesa')
  })

  it('A. PIX_OUT → renderiza "PIX enviado" (live TX 1b8e14d2 shape)', () => {
    const { label } = renderCell(LIVE_PIX_OUT)
    expect(label).toBe('PIX enviado')
  })

  it('B. PIX_IN → renderiza "PIX recebido"', () => {
    const tx: FinanceTransaction = {
      ...LIVE_PIX_OUT,
      id: '28224451-0000-4000-8000-000000000003',
      type: 'CREDIT',
      amount: 50,
      description: 'PIX RECEBIDO - REM ...',
      descriptionRaw: 'PIX RECEBIDO - REM ...',
      enrichment: {
        canonicalType: 'PIX_IN',
        paymentMethod: 'PIX',
        direction: 'IN',
        classificationStatus: 'classified',
        classificationSource: 'rules',
        categoryName: null,
      },
    }
    expect(renderCell(tx).label).toBe('PIX recebido')
  })

  it('REAL_UI_IOF_BEFORE: FEE + IOF só em descriptionRaw renderizava Taxa', () => {
    const { label } = renderCell(LIVE_IOF)
    expect(label).toBe('IOF')
    expect(label).not.toBe('Taxa')
    expect(label).not.toBe('Despesa')
  })

  it('C. FEE/IOF → renderiza "IOF"', () => {
    expect(renderCell(LIVE_IOF).label).toBe('IOF')
  })

  it('D. canonical específico nunca cai em Despesa', () => {
    expect(renderCell(LIVE_PIX_OUT).label).not.toBe('Despesa')
    expect(renderCell(LIVE_IOF).label).not.toBe('Despesa')
  })

  it('E–H. alias exato sem owner/brand/last4', () => {
    const { context } = renderCell(LIVE_IOF, creditCard)
    expect(context).toBe('C6 — William físico')
    expect(context).not.toMatch(/WILLIAM RODRIGO/i)
    expect(context).not.toMatch(/MASTERCARD/i)
    expect(context).not.toMatch(/5619/)
  })

  it('I. sem alias → fallback curto instituição + tipo', () => {
    const account: FinanceAccount = {
      ...creditCard,
      displayAlias: null,
      displayName: 'C6 Bank — Cartão de crédito',
    }
    expect(renderCell(LIVE_IOF, account).context).toBe('C6 Bank · Cartão de crédito · •••• 5619')
  })

  it('J. credit purchase continua PASS', () => {
    const tx: FinanceTransaction = {
      ...LIVE_IOF,
      description: 'MERCADO XYZ',
      descriptionRaw: 'MERCADO XYZ',
      enrichment: {
        canonicalType: 'CREDIT_PURCHASE',
        paymentMethod: 'CREDIT_CARD',
        direction: 'OUT',
        classificationStatus: 'classified',
        classificationSource: 'rules',
        categoryName: null,
      },
    }
    expect(renderCell(tx).label).toBe('Compra no cartão de crédito')
  })

  it('K. REFUND → Estorno', () => {
    const tx: FinanceTransaction = {
      ...LIVE_IOF,
      type: 'CREDIT',
      amount: 10,
      enrichment: {
        canonicalType: 'REFUND',
        paymentMethod: 'CREDIT_CARD',
        direction: 'IN',
        classificationStatus: 'classified',
        classificationSource: 'rules',
        categoryName: null,
      },
    }
    expect(renderCell(tx).label).toBe('Estorno')
  })

  it('L. transferência real continua correta', () => {
    const tx: FinanceTransaction = {
      ...LIVE_PIX_OUT,
      description: 'TED PARA CONTA',
      descriptionRaw: 'TED PARA CONTA',
      enrichment: {
        canonicalType: 'TRANSFER_OUT',
        paymentMethod: 'TRANSFER',
        direction: 'OUT',
        classificationStatus: 'classified',
        classificationSource: 'rules',
        categoryName: null,
      },
    }
    expect(renderCell(tx).label).toBe('Transferência enviada')
  })

  it('diagnoseTransactionDisplay para OpenCode', () => {
    const diag = diagnoseTransactionDisplay({
      enrichment: LIVE_PIX_OUT.enrichment,
      type: LIVE_PIX_OUT.type,
      description: LIVE_PIX_OUT.description,
      descriptionRaw: LIVE_PIX_OUT.descriptionRaw,
    })
    expect(diag.apiCanonical).toBe('PIX_OUT')
    expect(diag.apiPayment).toBe('PIX')
    expect(diag.apiDirection).toBe('OUT')
    expect(diag.uiResolvedLabel).toBe('PIX enviado')
  })
})
