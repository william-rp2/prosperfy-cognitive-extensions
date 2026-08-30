import { describe, expect, it } from 'vitest'

import {
  discoverAccountIdentityCapabilities,
  extractLast4,
  isInfrastructureConnectorName,
  resolveInstitutionName,
} from './institutionIdentity.js'
import type { FinancialAccountRow, FinancialItemRow } from './types.js'

function account(overrides: Partial<FinancialAccountRow> = {}): FinancialAccountRow {
  return {
    pluggy_account_id: 'acc-1',
    pluggy_item_id: 'item-1',
    name: null,
    marketing_name: null,
    owner: null,
    type: 'CREDIT',
    subtype: 'CREDIT_CARD',
    balance_cents: 0,
    currency_code: 'BRL',
    number_masked: '****5619',
    credit_limit_cents: null,
    available_credit_limit_cents: null,
    raw_data: null,
    last_synced_at: null,
    asset_classification_uncertain: 0,
    ...overrides,
  }
}

describe('institutionIdentity', () => {
  it('E. MeuPluggy nunca é instituição user-facing', () => {
    expect(isInfrastructureConnectorName('MeuPluggy')).toBe(true)
    expect(isInfrastructureConnectorName('PLUGGY')).toBe(true)
    const item: FinancialItemRow = {
      pluggy_item_id: 'item-1',
      connector_id: 200,
      connector_name: 'MeuPluggy',
      status: 'UPDATED',
      execution_status: null,
      last_synced_at: null,
      last_successful_update: null,
      error_summary: null,
      raw_metadata: null,
    }
    const resolved = resolveInstitutionName(
      account({
        raw_data: JSON.stringify({ bankData: { bankName: 'C6 Bank' } }),
      }),
      item,
    )
    expect(resolved).toBe('C6 Bank')
    expect(resolved).not.toMatch(/pluggy/i)
  })

  it('F. instituição real aparece quando disponível via marketing_name', () => {
    expect(
      resolveInstitutionName(
        account({ marketing_name: 'Bradesco', name: 'BANDEIRADO' }),
        { pluggy_item_id: 'item-1', connector_name: 'MeuPluggy' } as FinancialItemRow,
      ),
    ).toBe('Bradesco')
  })

  it('I. last4 extraído de number_masked', () => {
    expect(extractLast4('****5619')).toBe('5619')
  })

  it('discovery report capabilities sem dados sensíveis', () => {
    const caps = discoverAccountIdentityCapabilities(
      account({
        owner: null,
        raw_data: JSON.stringify({ creditData: { brand: 'Visa' } }),
        number_masked: '****1234',
      }),
      { pluggy_item_id: 'item-1', connector_name: 'MeuPluggy' } as FinancialItemRow,
      JSON.stringify({ creditCardMetadata: { cardNumber: '1234' } }),
    )
    expect(caps.bankAvailable).toBe(false)
    expect(caps.cardLast4Available).toBe(true)
    expect(caps.cardBrandAvailable).toBe(true)
    expect(caps.cardholderAvailable).toBe(false)
    expect(caps.transactionCardIdentifierAvailable).toBe(true)
  })
})
