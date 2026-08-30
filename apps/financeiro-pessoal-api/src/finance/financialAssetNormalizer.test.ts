import { describe, expect, it } from 'vitest'

import { aggregateFinancialAssets, resolveAccountCanonicalType } from './accountAggregation.js'
import { normalizeFinancialAccount, normalizeInvestmentAsset } from './financialAssetNormalizer.js'
import type { FinancialAccountRow, FinancialInvestmentRow } from './types.js'

function account(overrides: Partial<FinancialAccountRow>): FinancialAccountRow {
  return {
    id: '1',
    pluggy_account_id: overrides.pluggy_account_id ?? 'acc',
    pluggy_item_id: overrides.pluggy_item_id ?? 'item',
    type: overrides.type ?? 'BANK',
    subtype: overrides.subtype ?? 'CHECKING_ACCOUNT',
    name: overrides.name ?? 'Conta',
    marketing_name: null,
    currency_code: 'BRL',
    balance_cents: overrides.balance_cents ?? 100000,
    number_masked: null,
    owner: null,
    credit_limit_cents: overrides.credit_limit_cents ?? null,
    available_credit_limit_cents: null,
    canonical_type: overrides.canonical_type ?? null,
    asset_classification_confidence: null,
    asset_classification_uncertain: null,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
    last_synced_at: null,
    raw_data: null,
  }
}

describe('financialAssetNormalizer', () => {
  it('normaliza conta corrente, pagamento, poupança, cartão e investimento', () => {
    expect(normalizeFinancialAccount({ pluggyType: 'BANK', pluggySubtype: 'CHECKING_ACCOUNT' }).canonicalType).toBe(
      'CHECKING_ACCOUNT',
    )
    expect(normalizeFinancialAccount({ pluggyType: 'BANK', pluggySubtype: 'PAYMENT_ACCOUNT' }).canonicalType).toBe(
      'PAYMENT_ACCOUNT',
    )
    expect(normalizeFinancialAccount({ pluggyType: 'BANK', pluggySubtype: 'SAVINGS_ACCOUNT' }).canonicalType).toBe(
      'SAVINGS_ACCOUNT',
    )
    expect(normalizeFinancialAccount({ pluggyType: 'CREDIT' }).canonicalType).toBe('CREDIT_CARD')
    expect(normalizeFinancialAccount({ pluggyType: 'INVESTMENT' }).canonicalType).toBe('INVESTMENT')
  })

  it('desconhecido cai em OTHER com baixa confiança', () => {
    const unknown = normalizeFinancialAccount({ pluggyType: 'WEIRD', pluggySubtype: 'X' })
    expect(unknown.canonicalType).toBe('OTHER')
    expect(unknown.classificationUncertain).toBe(true)
  })

  it('investimento separado via normalizeInvestmentAsset', () => {
    expect(normalizeInvestmentAsset({ pluggyType: 'FIXED_INCOME', name: 'CDB' }).canonicalType).toBe('INVESTMENT')
  })
})

describe('accountAggregation', () => {
  it('cartão não entra no saldo de contas', () => {
    const agg = aggregateFinancialAssets(
      [
        account({ pluggy_account_id: 'checking', type: 'BANK', subtype: 'CHECKING_ACCOUNT', balance_cents: 500000 }),
        account({
          pluggy_account_id: 'card',
          type: 'CREDIT',
          subtype: 'CREDIT_CARD',
          balance_cents: -120000,
          credit_limit_cents: 1000000,
        }),
      ],
      [],
    )
    expect(agg.cashBalanceCents).toBe(500000)
    expect(agg.creditCardInvoiceCents).toBe(120000)
    expect(agg.creditCardLimitCents).toBe(1000000)
    expect(agg.financialWealthCents).toBe(500000)
  })

  it('limite não entra como patrimônio', () => {
    const agg = aggregateFinancialAssets(
      [account({ type: 'CREDIT', balance_cents: -50000, credit_limit_cents: 2000000 })],
      [],
    )
    expect(agg.financialWealthCents).toBe(0)
    expect(agg.creditCardLimitCents).toBe(2000000)
  })

  it('investimento separado de cash', () => {
    const agg = aggregateFinancialAssets(
      [account({ pluggy_account_id: 'checking', balance_cents: 100000 })],
      [{ pluggy_investment_id: 'inv1', pluggy_item_id: 'item', balance_cents: 250000 } as FinancialInvestmentRow],
    )
    expect(agg.cashBalanceCents).toBe(100000)
    expect(agg.investmentValueCents).toBe(250000)
    expect(agg.financialWealthCents).toBe(350000)
  })

  it('resolve canonical type from persisted column', () => {
    expect(resolveAccountCanonicalType(account({ canonical_type: 'CREDIT_CARD', type: 'BANK' }))).toBe('CREDIT_CARD')
  })
})
