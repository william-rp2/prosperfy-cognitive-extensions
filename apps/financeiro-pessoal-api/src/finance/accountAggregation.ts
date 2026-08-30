import {
  CASH_ASSET_TYPES,
  normalizeFinancialAccount,
  type CanonicalFinancialAssetType,
} from './financialAssetNormalizer.js'
import type { FinancialAccountRow, FinancialInvestmentRow } from './types.js'

export interface AccountAggregation {
  cashBalanceCents: number
  creditCardInvoiceCents: number
  creditCardLimitCents: number
  investmentValueCents: number
  /** Cash + investments — never includes credit limits or invoice debt as wealth. */
  financialWealthCents: number
}

export function resolveAccountCanonicalType(account: FinancialAccountRow): CanonicalFinancialAssetType {
  if (account.canonical_type) return account.canonical_type as CanonicalFinancialAssetType
  return normalizeFinancialAccount({
    pluggyType: account.type,
    pluggySubtype: account.subtype,
    name: account.name,
    marketingName: account.marketing_name,
    creditLimitCents: account.credit_limit_cents,
    rawData: account.raw_data ? JSON.parse(account.raw_data) : undefined,
  }).canonicalType
}

export function aggregateFinancialAssets(
  accounts: FinancialAccountRow[],
  investments: FinancialInvestmentRow[],
): AccountAggregation {
  let cashBalanceCents = 0
  let creditCardInvoiceCents = 0
  let creditCardLimitCents = 0
  let investmentValueCents = 0

  for (const account of accounts) {
    const canonical = resolveAccountCanonicalType(account)
    const balance = account.balance_cents ?? 0

    if (CASH_ASSET_TYPES.has(canonical)) {
      cashBalanceCents += balance
      continue
    }

    if (canonical === 'CREDIT_CARD') {
      creditCardInvoiceCents += Math.abs(balance)
      if (account.credit_limit_cents != null) creditCardLimitCents += account.credit_limit_cents
      continue
    }

    if (canonical === 'INVESTMENT') {
      investmentValueCents += balance
    }
  }

  for (const investment of investments) {
    investmentValueCents += investment.balance_cents ?? 0
  }

  return {
    cashBalanceCents,
    creditCardInvoiceCents,
    creditCardLimitCents,
    investmentValueCents,
    financialWealthCents: cashBalanceCents + investmentValueCents,
  }
}
