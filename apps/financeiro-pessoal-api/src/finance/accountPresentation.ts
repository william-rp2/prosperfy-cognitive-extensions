import type { FinancialAccountRow } from './types.js'
import { isInfrastructureConnectorName } from './institutionIdentity.js'

const TECHNICAL_PRODUCT_NAMES = new Set(['BANDEIRADO', 'BRANDED', 'CREDIT_CARD', 'DEBIT_CARD'])

const ASSET_TYPE_LABELS: Record<string, string> = {
  CHECKING_ACCOUNT: 'Conta corrente',
  PAYMENT_ACCOUNT: 'Conta pagamento',
  SAVINGS_ACCOUNT: 'Poupança',
  CREDIT_CARD: 'Cartão de crédito',
  INVESTMENT: 'Investimento',
  RESERVE: 'Reserva',
  OTHER: 'Outro',
}

export function isTechnicalProductName(value: string | null | undefined): boolean {
  if (!value) return false
  return TECHNICAL_PRODUCT_NAMES.has(value.trim().toUpperCase())
}

export function defaultAccountLabel(
  account: Pick<FinancialAccountRow, 'name' | 'marketing_name'>,
  institutionName: string | null | undefined,
  canonicalType: string,
): string {
  const marketing = account.marketing_name?.trim()
  if (marketing && !isTechnicalProductName(marketing)) return marketing

  const name = account.name?.trim()
  if (name && !isTechnicalProductName(name)) return name

  const typeLabel = ASSET_TYPE_LABELS[canonicalType] ?? 'Produto'
  if (institutionName && !isInfrastructureConnectorName(institutionName)) {
    return `${institutionName} — ${typeLabel}`
  }
  return typeLabel
}

export function sortAccountsByPreference<T extends { isFavorite: boolean; displayName: string | null }>(accounts: T[]): T[] {
  return [...accounts].sort((a, b) => {
    const favDiff = Number(b.isFavorite) - Number(a.isFavorite)
    if (favDiff !== 0) return favDiff
    return (a.displayName ?? '').localeCompare(b.displayName ?? '', 'pt-BR', { sensitivity: 'base' })
  })
}
