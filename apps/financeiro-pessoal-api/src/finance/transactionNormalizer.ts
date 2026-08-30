/**
 * Pluggy/raw → canonical Finance domain types (deterministic, no LLM).
 */

export type CanonicalDirection = 'IN' | 'OUT'

export type CanonicalPaymentMethod = 'CREDIT_CARD' | 'DEBIT_CARD' | 'PIX' | 'TRANSFER' | 'BOLETO' | 'UNKNOWN'

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
  /** Resolved payment method for presentation — not the same as Pluggy raw DEBIT/CREDIT. */
  paymentMethod: CanonicalPaymentMethod
  merchantNormalized: string | null
}

export interface NormalizerInput {
  pluggyType: string | null | undefined
  amountCents: number
  description?: string | null
  descriptionRaw?: string | null
  merchantOriginal?: string | null
  rawData?: unknown
  /** Financial asset canonical type of the originating account (from Finance, not Pluggy raw). */
  accountCanonicalType?: string | null
}

function normalizeMerchant(value: string | null | undefined): string | null {
  if (!value) return null
  return value.trim().toUpperCase().replace(/\s+/g, ' ')
}

function extractRawPaymentMethod(rawData: unknown): string | null {
  if (!rawData || typeof rawData !== 'object') return null
  const data = rawData as Record<string, unknown>
  const paymentData = data.paymentData as Record<string, unknown> | undefined
  if (!paymentData) return null
  const method = paymentData.paymentMethod ?? paymentData.type
  return typeof method === 'string' ? method : null
}

function textHints(description: string): { pix: boolean; transfer: boolean; card: boolean; boleto: boolean; billPayment: boolean } {
  const upper = description.toUpperCase()
  return {
    pix: upper.includes('PIX'),
    transfer: upper.includes('TRANSFER') || upper.includes('TRANSF') || upper.includes('TED') || upper.includes('DOC'),
    card: upper.includes('CART') || upper.includes('CARD'),
    boleto: upper.includes('BOLETO') || upper.includes('BOLETO'),
    billPayment:
      (upper.includes('PAG') && upper.includes('FAT')) ||
      upper.includes('PAGAMENTO FATURA') ||
      upper.includes('PAG FAT') ||
      upper.includes('LIQUIDACAO FATURA'),
  }
}

function isCreditCardAsset(accountCanonicalType: string | null | undefined): boolean {
  return accountCanonicalType === 'CREDIT_CARD'
}

function hasDebitCardEvidence(rawPaymentMethod: string | null, hints: ReturnType<typeof textHints>): boolean {
  const method = rawPaymentMethod?.toLowerCase() ?? ''
  return method.includes('debit') || (method.includes('card') && !method.includes('credit') && hints.card)
}

function hasCreditCardEvidence(
  rawPaymentMethod: string | null,
  hints: ReturnType<typeof textHints>,
  accountCanonicalType: string | null | undefined,
): boolean {
  if (isCreditCardAsset(accountCanonicalType)) return true
  const method = rawPaymentMethod?.toLowerCase() ?? ''
  return method.includes('credit') || (hints.card && method.includes('credit'))
}

export function normalizePluggyTransaction(input: NormalizerInput): NormalizedTransaction {
  const rawType = input.pluggyType?.trim() || null
  const description = `${input.description || ''} ${input.descriptionRaw || ''}`.trim()
  const hints = textHints(description)
  const rawPaymentMethod = extractRawPaymentMethod(input.rawData)
  const merchantNormalized = normalizeMerchant(input.merchantOriginal || input.descriptionRaw || input.description)
  const accountType = input.accountCanonicalType ?? null

  const pluggyCredit = rawType?.toUpperCase() === 'CREDIT'
  const direction: CanonicalDirection = pluggyCredit ? 'IN' : 'OUT'

  let paymentMethod: CanonicalPaymentMethod = 'UNKNOWN'
  if (hints.pix) paymentMethod = 'PIX'
  else if (hints.transfer) paymentMethod = 'TRANSFER'
  else if (hints.boleto) paymentMethod = 'BOLETO'
  else if (hasCreditCardEvidence(rawPaymentMethod, hints, accountType)) paymentMethod = 'CREDIT_CARD'
  else if (hasDebitCardEvidence(rawPaymentMethod, hints)) paymentMethod = 'DEBIT_CARD'

  let canonicalType: CanonicalTransactionType = 'OTHER'

  if (hints.pix) {
    canonicalType = direction === 'IN' ? 'PIX_IN' : 'PIX_OUT'
  } else if (hints.transfer) {
    canonicalType = direction === 'IN' ? 'TRANSFER_IN' : 'TRANSFER_OUT'
  } else if (isCreditCardAsset(accountType) && direction === 'OUT' && hints.billPayment) {
    canonicalType = 'CARD_PAYMENT'
    paymentMethod = 'CREDIT_CARD'
  } else if (isCreditCardAsset(accountType) && direction === 'OUT') {
    canonicalType = 'CREDIT_PURCHASE'
    paymentMethod = 'CREDIT_CARD'
  } else if (isCreditCardAsset(accountType) && direction === 'IN') {
    canonicalType =
      hints.billPayment || description.toLowerCase().includes('pagamento')
        ? 'CARD_PAYMENT'
        : description.toLowerCase().includes('estorno') || description.toLowerCase().includes('refund')
          ? 'REFUND'
          : 'INCOME'
    paymentMethod = 'CREDIT_CARD'
  } else if (paymentMethod === 'DEBIT_CARD' && direction === 'OUT') {
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
