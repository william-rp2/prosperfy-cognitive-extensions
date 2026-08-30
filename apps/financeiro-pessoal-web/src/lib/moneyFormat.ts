import type { FinanceTransaction } from '../api/finance'

export function formatMoney(value: number | null | undefined, currencyCode = 'BRL'): string {
  if (value == null || Number.isNaN(value)) return '—'
  const code = currencyCode?.trim().toUpperCase() || 'BRL'
  try {
    return value.toLocaleString('pt-BR', { currency: code, style: 'currency' })
  } catch {
    return `${code} ${value.toFixed(2)}`
  }
}

export function formatTransactionAmount(
  tx: Pick<
    FinanceTransaction,
    'amount' | 'currencyCode' | 'amountInAccountCurrency' | 'accountCurrencyCode' | 'currencyConversionMissing'
  >,
): { primary: string; secondary: string | null } {
  const originalCurrency = tx.currencyCode?.trim().toUpperCase() || 'BRL'
  const accountCurrency = tx.accountCurrencyCode?.trim().toUpperCase() || originalCurrency
  const primary = formatMoney(tx.amount, originalCurrency)

  if (
    tx.amountInAccountCurrency != null &&
    accountCurrency &&
    originalCurrency !== accountCurrency
  ) {
    return {
      primary,
      secondary: `≈ ${formatMoney(tx.amountInAccountCurrency, accountCurrency)}`,
    }
  }

  if (tx.currencyConversionMissing) {
    return { primary, secondary: 'conversão indisponível' }
  }

  return { primary, secondary: null }
}

export function formatTransactionAmountInline(
  tx: Pick<
    FinanceTransaction,
    'amount' | 'currencyCode' | 'amountInAccountCurrency' | 'accountCurrencyCode' | 'currencyConversionMissing'
  >,
): string {
  const { primary, secondary } = formatTransactionAmount(tx)
  return secondary ? `${primary} ${secondary}` : primary
}
