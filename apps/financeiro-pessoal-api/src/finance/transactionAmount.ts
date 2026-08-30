import type { FinancialTransactionRow } from './types.js'
import { toCents } from './types.js'

export type TransactionAmountFields = Pick<
  FinancialTransactionRow,
  'amount_cents' | 'currency_code' | 'amount_in_account_currency_cents' | 'account_currency_code'
>

function normalizeCurrency(value: string | null | undefined): string | null {
  if (!value?.trim()) return null
  return value.trim().toUpperCase()
}

/** Same-currency or converted foreign → cents for account-base aggregation; null when excluded. */
export function effectiveAccountAmountCents(row: TransactionAmountFields): number | null {
  const txCurrency = normalizeCurrency(row.currency_code)
  const accountCurrency = normalizeCurrency(row.account_currency_code)

  if (!txCurrency || !accountCurrency || txCurrency === accountCurrency) {
    return Math.abs(row.amount_cents)
  }

  if (row.amount_in_account_currency_cents != null) {
    return Math.abs(row.amount_in_account_currency_cents)
  }

  return null
}

export function isCurrencyConversionMissing(row: TransactionAmountFields): boolean {
  const txCurrency = normalizeCurrency(row.currency_code)
  const accountCurrency = normalizeCurrency(row.account_currency_code)
  if (!txCurrency || !accountCurrency || txCurrency === accountCurrency) return false
  return row.amount_in_account_currency_cents == null
}

/** SQL fragment: effective absolute amount in account currency (NULL when fail-closed excluded). */
export const EFFECTIVE_ABS_AMOUNT_CENTS_SQL = `
  CASE
    WHEN t.currency_code IS NULL OR t.account_currency_code IS NULL OR UPPER(t.currency_code) = UPPER(t.account_currency_code)
      THEN ABS(t.amount_cents)
    WHEN t.amount_in_account_currency_cents IS NOT NULL
      THEN ABS(t.amount_in_account_currency_cents)
    ELSE NULL
  END
`

export function extractAmountInAccountCurrencyCents(rawData: unknown): number | null {
  if (!rawData || typeof rawData !== 'object') return null
  const data = rawData as Record<string, unknown>
  if (typeof data.amountInAccountCurrency === 'number' && Number.isFinite(data.amountInAccountCurrency)) {
    return toCents(data.amountInAccountCurrency)
  }
  return null
}

/** Recovery probe: whether persisted raw payloads contain converted account amounts. */
export function historicalRawHasAccountAmount(rawDataJson: string | null | undefined): boolean {
  if (!rawDataJson) return false
  try {
    const parsed = JSON.parse(rawDataJson) as unknown
    return extractAmountInAccountCurrencyCents(parsed) != null
  } catch {
    return false
  }
}
