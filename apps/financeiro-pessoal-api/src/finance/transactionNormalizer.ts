/**
 * Pluggy/raw → canonical Finance domain types (deterministic, no LLM).
 */

export type CanonicalDirection = 'IN' | 'OUT'

export type CanonicalTransactionType =
  | 'PIX_IN'
  | 'PIX_OUT'
  | 'CREDIT_PURCHASE'
  | 'DEBIT_PURCHASE'
  | 'TRANSFER_IN'
  | 'TRANSFER_OUT'
  | 'INCOME'
  | 'EXPENSE'
  | 'CARD_PAYMENT'
  | 'REFUND'
  | 'OTHER'

export interface NormalizedTransaction {
  direction: CanonicalDirection
  canonicalType: CanonicalTransactionType
  rawType: string | null
  paymentMethod: string | null
  merchantNormalized: string | null
}

export interface NormalizerInput {
  pluggyType: string | null | undefined
  amountCents: number
  description?: string | null
  descriptionRaw?: string | null
  merchantOriginal?: string | null
  rawData?: unknown
}

function normalizeMerchant(value: string | null | undefined): string | null {
  if (!value) return null
  return value.trim().toUpperCase().replace(/\s+/g, ' ')
}

function extractPaymentMethod(rawData: unknown): string | null {
  if (!rawData || typeof rawData !== 'object') return null
  const data = rawData as Record<string, unknown>
  const paymentData = data.paymentData as Record<string, unknown> | undefined
  if (!paymentData) return null
  const method = paymentData.paymentMethod ?? paymentData.type
  return typeof method === 'string' ? method : null
}

function textHints(description: string): { pix: boolean; transfer: boolean; card: boolean } {
  const upper = description.toUpperCase()
  return {
    pix: upper.includes('PIX'),
    transfer: upper.includes('TRANSFER') || upper.includes('TRANSF') || upper.includes('TED') || upper.includes('DOC'),
    card: upper.includes('CART') || upper.includes('CARD'),
  }
}

export function normalizePluggyTransaction(input: NormalizerInput): NormalizedTransaction {
  const rawType = input.pluggyType?.trim() || null
  const description = `${input.description || ''} ${input.descriptionRaw || ''}`.trim()
  const hints = textHints(description)
  const paymentMethod = extractPaymentMethod(input.rawData)
  const merchantNormalized = normalizeMerchant(input.merchantOriginal || input.descriptionRaw || input.description)

  const pluggyCredit = rawType?.toUpperCase() === 'CREDIT'
  const direction: CanonicalDirection = pluggyCredit ? 'IN' : 'OUT'

  let canonicalType: CanonicalTransactionType = 'OTHER'

  if (hints.pix) {
    canonicalType = direction === 'IN' ? 'PIX_IN' : 'PIX_OUT'
  } else if (hints.transfer) {
    canonicalType = direction === 'IN' ? 'TRANSFER_IN' : 'TRANSFER_OUT'
  } else if (rawType?.toUpperCase() === 'CREDIT' && (hints.card || paymentMethod?.toLowerCase().includes('credit'))) {
    canonicalType = 'CREDIT_PURCHASE'
  } else if (rawType?.toUpperCase() === 'DEBIT' && hints.card) {
    canonicalType = 'CARD_PAYMENT'
  } else if (rawType?.toUpperCase() === 'DEBIT') {
    canonicalType = 'DEBIT_PURCHASE'
  } else if (direction === 'IN') {
    canonicalType = description.toLowerCase().includes('estorno') || description.toLowerCase().includes('refund') ? 'REFUND' : 'INCOME'
  } else if (direction === 'OUT') {
    canonicalType = 'EXPENSE'
  }

  return {
    direction,
    canonicalType,
    rawType,
    paymentMethod,
    merchantNormalized,
  }
}
