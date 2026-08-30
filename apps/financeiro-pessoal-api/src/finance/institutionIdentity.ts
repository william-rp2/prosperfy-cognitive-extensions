import type { FinancialAccountRow, FinancialItemRow } from './types.js'
import { isTechnicalProductName } from './accountPresentation.js'

/** Connector/proxy names — never user-facing as financial institution. */
const INFRASTRUCTURE_CONNECTOR_NAMES = new Set([
  'MEUPLUGGY',
  'MEU PLUGGY',
  'PLUGGY',
  'OPEN FINANCE',
  'OPENFINANCE',
])

export function isInfrastructureConnectorName(value: string | null | undefined): boolean {
  if (!value?.trim()) return false
  const normalized = value.trim().toUpperCase().replace(/\s+/g, ' ')
  return INFRASTRUCTURE_CONNECTOR_NAMES.has(normalized.replace(/\s/g, '')) ||
    INFRASTRUCTURE_CONNECTOR_NAMES.has(normalized)
}

function parseJson(value: string | null | undefined): Record<string, unknown> | null {
  if (!value) return null
  try {
    const parsed = JSON.parse(value) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function pickInstitutionCandidate(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed || isInfrastructureConnectorName(trimmed) || isTechnicalProductName(trimmed)) return null
  return trimmed
}

/**
 * Resolves user-facing institution/bank name from account + item metadata.
 * Never returns MeuPluggy/Pluggy connector names.
 */
export function resolveInstitutionName(
  account: Pick<
    FinancialAccountRow,
    'name' | 'marketing_name' | 'owner' | 'raw_data' | 'pluggy_item_id'
  >,
  item?: Pick<FinancialItemRow, 'connector_name' | 'raw_metadata'> | null,
): string | null {
  const raw = parseJson(account.raw_data)
  const bankData = raw?.bankData as Record<string, unknown> | undefined
  const creditData = raw?.creditData as Record<string, unknown> | undefined
  const itemMeta = item ? parseJson(item.raw_metadata) : null
  const connector = itemMeta?.connector as Record<string, unknown> | undefined

  const candidates: unknown[] = [
    bankData?.bankName,
    bankData?.name,
    creditData?.brand, // sometimes institution appears here incorrectly — filtered below if card brand only
    account.marketing_name,
    account.name,
    account.owner,
    connector?.institutionName,
    connector?.name,
    item?.connector_name,
  ]

  for (const candidate of candidates) {
    const picked = pickInstitutionCandidate(candidate)
    if (!picked) continue
    const upper = picked.toUpperCase()
    if (upper === 'VISA' || upper === 'MASTERCARD' || upper === 'ELO' || upper === 'AMEX') continue
    return picked
  }

  return null
}

export function extractCardBrand(rawDataJson: string | null | undefined): string | null {
  const raw = parseJson(rawDataJson)
  if (!raw) return null
  const credit = raw.creditData as Record<string, unknown> | undefined
  const brand = credit?.brand ?? credit?.level ?? raw.brand
  if (typeof brand !== 'string') return null
  const trimmed = brand.trim()
  return trimmed || null
}

export function extractLast4(numberMasked: string | null | undefined): string | null {
  if (!numberMasked?.trim()) return null
  const digits = numberMasked.replace(/\D/g, '')
  return digits.length >= 4 ? digits.slice(-4) : null
}

export interface AccountIdentityCapabilities {
  bankAvailable: boolean
  cardLast4Available: boolean
  cardBrandAvailable: boolean
  cardholderAvailable: boolean
  transactionCardIdentifierAvailable: boolean
  virtualCardSignalAvailable: boolean
  additionalCardSignalAvailable: boolean
}

export function discoverAccountIdentityCapabilities(
  account: FinancialAccountRow,
  item?: FinancialItemRow | null,
  sampleTransactionRaw?: string | null,
): AccountIdentityCapabilities {
  const raw = parseJson(account.raw_data)
  const credit = raw?.creditData as Record<string, unknown> | undefined
  const txRaw = parseJson(sampleTransactionRaw ?? null)
  const txCredit = txRaw?.creditCardMetadata as Record<string, unknown> | undefined

  const subtype = (account.subtype ?? '').toUpperCase()
  const name = `${account.name ?? ''} ${account.marketing_name ?? ''}`.toUpperCase()

  return {
    bankAvailable: resolveInstitutionName(account, item) !== null,
    cardLast4Available: extractLast4(account.number_masked) !== null,
    cardBrandAvailable: extractCardBrand(account.raw_data) !== null,
    cardholderAvailable: Boolean(account.owner?.trim()),
    transactionCardIdentifierAvailable: Boolean(
      txCredit?.cardNumber ?? txCredit?.cardId ?? txRaw?.paymentData,
    ),
    virtualCardSignalAvailable: subtype.includes('VIRTUAL') || name.includes('VIRTUAL'),
    additionalCardSignalAvailable: subtype.includes('ADDITIONAL') || name.includes('ADICIONAL'),
  }
}
