import { describe, expect, it } from 'vitest'

import type { CandidateTransactionRow, StatementLineRow } from './statementImportRepository.js'
import { matchStatementLines } from './statementMatchingService.js'

/**
 * LIVE finding (homolog): card purchases arrive with POSITIVE raw.amount;
 * bill payments arrive NEGATIVE. Sign alone must not decide matching direction.
 */

function line(overrides: Partial<StatementLineRow> & Pick<StatementLineRow, 'id' | 'line_type' | 'amount_cents'>): StatementLineRow {
  return {
    statement_import_id: 'imp-1',
    statement_cycle_id: null,
    line_index: 0,
    line_hash: overrides.id,
    date: '2026-08-10',
    description_raw: 'COMPRA LOJA',
    currency_code: 'BRL',
    card_hint: null,
    source_page: null,
    created_at: '2026-08-10T00:00:00.000Z',
    ...overrides,
  }
}

function tx(
  overrides: Partial<CandidateTransactionRow> & Pick<CandidateTransactionRow, 'pluggy_transaction_id' | 'amount_cents'>,
): CandidateTransactionRow {
  return {
    pluggy_account_id: 'acc-card',
    description: 'COMPRA LOJA',
    description_raw: 'COMPRA LOJA',
    currency_code: 'BRL',
    date: '2026-08-10',
    statement_cycle_id: null,
    cycle_assignment_source: null,
    enrichment_direction: null,
    enrichment_canonical_type: null,
    enrichment_payment_method: null,
    ...overrides,
  }
}

describe('card statement direction (LIVE homolog contract)', () => {
  it('RED→GREEN: positive upstream card purchase with enrichment OUT matches PURCHASE line', () => {
    // LIVE: amount_cents=+5900, enrichment.direction=OUT, canonical=CREDIT_PURCHASE
    const purchase = tx({
      pluggy_transaction_id: 'live-purchase',
      amount_cents: 5900,
      enrichment_direction: 'OUT',
      enrichment_canonical_type: 'CREDIT_PURCHASE',
      enrichment_payment_method: 'CREDIT_CARD',
    })
    const purchaseLine = line({
      id: 'line-purchase',
      line_type: 'PURCHASE',
      amount_cents: 5900,
      description_raw: 'COMPRA LOJA',
    })

    const { results } = matchStatementLines([purchaseLine], [purchase])
    expect(results).toHaveLength(1)
    expect(['EXACT', 'HIGH']).toContain(results[0].status)
    expect(results[0].chosen?.transactionId).toBe('live-purchase')
  })

  it('positive amount without enrichment must NOT invent CREDIT and must not match PURCHASE', () => {
    const orphan = tx({
      pluggy_transaction_id: 'no-enrichment',
      amount_cents: 5900,
      enrichment_direction: null,
      enrichment_canonical_type: null,
    })
    const purchaseLine = line({
      id: 'line-purchase',
      line_type: 'PURCHASE',
      amount_cents: 5900,
    })

    const { results } = matchStatementLines([purchaseLine], [orphan])
    expect(results[0].status).toBe('STATEMENT_ONLY')
    expect(results[0].chosen).toBeNull()
  })

  it('negative bill payment with enrichment IN matches PAYMENT line; purchase does not', () => {
    const purchase = tx({
      pluggy_transaction_id: 'live-purchase',
      amount_cents: 5900,
      description: 'MERCADO',
      description_raw: 'MERCADO',
      enrichment_direction: 'OUT',
      enrichment_canonical_type: 'CREDIT_PURCHASE',
      enrichment_payment_method: 'CREDIT_CARD',
    })
    const payment = tx({
      pluggy_transaction_id: 'live-payment',
      amount_cents: -5900,
      description: 'PAGAMENTO FATURA',
      description_raw: 'PAGAMENTO FATURA',
      date: '2026-08-15',
      enrichment_direction: 'IN',
      enrichment_canonical_type: 'CARD_PAYMENT',
      enrichment_payment_method: 'CREDIT_CARD',
    })

    const purchaseLine = line({
      id: 'line-purchase',
      line_type: 'PURCHASE',
      amount_cents: 5900,
      description_raw: 'MERCADO',
      date: '2026-08-10',
    })
    const paymentLine = line({
      id: 'line-payment',
      line_index: 1,
      line_type: 'PAYMENT',
      amount_cents: -5900,
      description_raw: 'PAGAMENTO FATURA',
      date: '2026-08-15',
    })

    const { results } = matchStatementLines([purchaseLine, paymentLine], [purchase, payment])
    const purchaseResult = results.find(r => r.lineId === 'line-purchase')!
    const paymentResult = results.find(r => r.lineId === 'line-payment')!

    expect(purchaseResult.chosen?.transactionId).toBe('live-purchase')
    expect(paymentResult.chosen?.transactionId).toBe('live-payment')
    // Same magnitude must never cross-match purchase ↔ payment.
    expect(purchaseResult.chosen?.transactionId).not.toBe('live-payment')
    expect(paymentResult.chosen?.transactionId).not.toBe('live-purchase')
  })

  it('purchase and refund at same magnitude match only their semantic counterparts', () => {
    const purchase = tx({
      pluggy_transaction_id: 'purchase-tx',
      amount_cents: 5900,
      description: 'LOJA X',
      description_raw: 'LOJA X',
      enrichment_direction: 'OUT',
      enrichment_canonical_type: 'CREDIT_PURCHASE',
    })
    const refund = tx({
      pluggy_transaction_id: 'refund-tx',
      amount_cents: 5900, // LIVE-like: refund may also arrive positive upstream
      description: 'ESTORNO LOJA X',
      description_raw: 'ESTORNO LOJA X',
      enrichment_direction: 'IN',
      enrichment_canonical_type: 'REFUND',
    })

    const purchaseLine = line({
      id: 'line-purchase',
      line_type: 'PURCHASE',
      amount_cents: 5900,
      description_raw: 'LOJA X',
    })
    const refundLine = line({
      id: 'line-refund',
      line_index: 1,
      line_type: 'REFUND',
      amount_cents: 5900,
      description_raw: 'ESTORNO LOJA X',
    })

    const { results } = matchStatementLines([purchaseLine, refundLine], [purchase, refund])
    expect(results.find(r => r.lineId === 'line-purchase')?.chosen?.transactionId).toBe('purchase-tx')
    expect(results.find(r => r.lineId === 'line-refund')?.chosen?.transactionId).toBe('refund-tx')
  })

  it('canonical_type alone can resolve direction when enrichment.direction is missing', () => {
    const fee = tx({
      pluggy_transaction_id: 'fee-tx',
      amount_cents: 1200,
      description: 'IOF',
      description_raw: 'IOF',
      enrichment_direction: null,
      enrichment_canonical_type: 'FEE',
    })
    const feeLine = line({
      id: 'line-iof',
      line_type: 'IOF',
      amount_cents: 1200,
      description_raw: 'IOF',
    })

    const { results } = matchStatementLines([feeLine], [fee])
    expect(['EXACT', 'HIGH']).toContain(results[0].status)
    expect(results[0].chosen?.transactionId).toBe('fee-tx')
  })
})
