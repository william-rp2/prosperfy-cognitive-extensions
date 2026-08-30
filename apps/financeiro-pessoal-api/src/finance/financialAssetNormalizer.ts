/**
 * Pluggy account/investment → canonical Finance asset types (deterministic, no LLM).
 */

export type CanonicalFinancialAssetType =
  | 'CHECKING_ACCOUNT'
  | 'PAYMENT_ACCOUNT'
  | 'SAVINGS_ACCOUNT'
  | 'CREDIT_CARD'
  | 'INVESTMENT'
  | 'RESERVE'
  | 'OTHER'

export interface NormalizedFinancialAsset {
  canonicalType: CanonicalFinancialAssetType
  sourceType: string | null
  sourceSubtype: string | null
  confidence: number
  classificationUncertain: boolean
}

export interface NormalizeAccountInput {
  pluggyType?: string | null
  pluggySubtype?: string | null
  name?: string | null
  marketingName?: string | null
  creditLimitCents?: number | null
  rawData?: unknown
}

export interface NormalizeInvestmentInput {
  pluggyType?: string | null
  pluggySubtype?: string | null
  name?: string | null
}

export const CASH_ASSET_TYPES = new Set<CanonicalFinancialAssetType>([
  'CHECKING_ACCOUNT',
  'PAYMENT_ACCOUNT',
  'SAVINGS_ACCOUNT',
])

function upper(value: string | null | undefined): string {
  return (value ?? '').trim().toUpperCase()
}

export function normalizeFinancialAccount(input: NormalizeAccountInput): NormalizedFinancialAsset {
  const sourceType = input.pluggyType?.trim() || null
  const sourceSubtype = input.pluggySubtype?.trim() || null
  const typeUpper = upper(sourceType)
  const subtypeUpper = upper(sourceSubtype)
  const nameUpper = `${input.name ?? ''} ${input.marketingName ?? ''}`.toUpperCase()

  if (typeUpper === 'CREDIT' || subtypeUpper.includes('CREDIT_CARD') || subtypeUpper.includes('CREDIT CARD')) {
    return {
      canonicalType: 'CREDIT_CARD',
      sourceType,
      sourceSubtype,
      confidence: 0.95,
      classificationUncertain: false,
    }
  }

  if (typeUpper === 'INVESTMENT' || subtypeUpper.includes('INVESTMENT') || subtypeUpper.includes('INVEST')) {
    return {
      canonicalType: 'INVESTMENT',
      sourceType,
      sourceSubtype,
      confidence: 0.9,
      classificationUncertain: false,
    }
  }

  if (subtypeUpper.includes('SAVINGS') || subtypeUpper.includes('POUPAN') || nameUpper.includes('POUPAN')) {
    return {
      canonicalType: 'SAVINGS_ACCOUNT',
      sourceType,
      sourceSubtype,
      confidence: nameUpper.includes('POUPAN') && !subtypeUpper.includes('SAVINGS') ? 0.75 : 0.9,
      classificationUncertain: nameUpper.includes('POUPAN') && !subtypeUpper.includes('SAVINGS'),
    }
  }

  if (subtypeUpper.includes('PAYMENT') || subtypeUpper.includes('PAGAMENTO') || nameUpper.includes('PAGAMENTO')) {
    return {
      canonicalType: 'PAYMENT_ACCOUNT',
      sourceType,
      sourceSubtype,
      confidence: 0.85,
      classificationUncertain: false,
    }
  }

  if (
    subtypeUpper.includes('RESERVE') ||
    subtypeUpper.includes('RESERVA') ||
    (nameUpper.includes('RESERVA') && subtypeUpper.includes('RESERV'))
  ) {
    return {
      canonicalType: 'RESERVE',
      sourceType,
      sourceSubtype,
      confidence: 0.65,
      classificationUncertain: true,
    }
  }

  if (subtypeUpper.includes('CHECKING') || subtypeUpper.includes('CORRENTE') || nameUpper.includes('CORRENTE')) {
    return {
      canonicalType: 'CHECKING_ACCOUNT',
      sourceType,
      sourceSubtype,
      confidence: 0.9,
      classificationUncertain: false,
    }
  }

  if (typeUpper === 'BANK') {
    return {
      canonicalType: 'CHECKING_ACCOUNT',
      sourceType,
      sourceSubtype,
      confidence: 0.7,
      classificationUncertain: false,
    }
  }

  return {
    canonicalType: 'OTHER',
    sourceType,
    sourceSubtype,
    confidence: 0.3,
    classificationUncertain: true,
  }
}

export function normalizeInvestmentAsset(input: NormalizeInvestmentInput): NormalizedFinancialAsset {
  const sourceType = input.pluggyType?.trim() || null
  const sourceSubtype = input.pluggySubtype?.trim() || null
  const nameUpper = upper(input.name)
  const subtypeUpper = upper(sourceSubtype)

  if (nameUpper.includes('RESERVA') && (subtypeUpper.includes('RESERV') || subtypeUpper.includes('RESERVE'))) {
    return {
      canonicalType: 'RESERVE',
      sourceType,
      sourceSubtype,
      confidence: 0.6,
      classificationUncertain: true,
    }
  }

  return {
    canonicalType: 'INVESTMENT',
    sourceType,
    sourceSubtype,
    confidence: 0.9,
    classificationUncertain: false,
  }
}
