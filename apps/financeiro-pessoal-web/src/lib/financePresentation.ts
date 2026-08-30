/** User-facing pt-BR labels for Finance enums — internal codes stay in English. */

const ITEM_STATUS: Record<string, string> = {
  UPDATED: 'Atualizado',
  CREATED: 'Criado',
  LOGIN_ERROR: 'Erro de login',
  OUTDATED: 'Desatualizado',
  WAITING_USER_INPUT: 'Aguardando sua ação',
  WAITING_USER_ACTION: 'Aguardando sua ação',
  SUCCESS: 'Sincronizado',
  ERROR: 'Erro',
  FAILED: 'Falha',
  PARTIAL: 'Parcial',
  RUNNING: 'Sincronizando',
  PENDING: 'Pendente',
}

const SYNC_STATUS: Record<string, string> = {
  success: 'Sincronizado',
  partial: 'Parcial',
  failed: 'Erro',
  running: 'Sincronizando',
  deferred: 'Aguardando sincronização',
}

const ASSET_TYPES: Record<string, string> = {
  CHECKING_ACCOUNT: 'Conta corrente',
  PAYMENT_ACCOUNT: 'Conta pagamento',
  SAVINGS_ACCOUNT: 'Poupança',
  CREDIT_CARD: 'Cartão de crédito',
  INVESTMENT: 'Investimento',
  RESERVE: 'Reserva',
  OTHER: 'Outro',
}

const TRANSACTION_TYPES: Record<string, string> = {
  PIX_IN: 'PIX recebido',
  PIX_OUT: 'PIX enviado',
  CREDIT_PURCHASE: 'Compra no cartão de crédito',
  DEBIT_PURCHASE: 'Compra no débito',
  TRANSFER_IN: 'Transferência recebida',
  TRANSFER_OUT: 'Transferência enviada',
  INCOME: 'Receita',
  EXPENSE: 'Despesa',
  CARD_PAYMENT: 'Pagamento de cartão',
  REFUND: 'Estorno',
  FEE: 'Taxa',
  TAX: 'Taxa',
  OTHER: 'Outro',
  CREDIT: 'Entrada',
  DEBIT: 'Saída',
}

const CLASSIFICATION_STATUS: Record<string, string> = {
  classified: 'Classificado',
  needs_clarification: 'Precisa de confirmação',
  unknown: 'Desconhecido',
}

const BUDGET_STATUS: Record<string, string> = {
  under: 'Dentro do orçamento',
  near: 'Próximo do limite',
  over: 'Acima do orçamento',
  on_track: 'No planejado',
}

const TECHNICAL_PRODUCT_NAMES = new Set(['BANDEIRADO', 'BRANDED', 'CREDIT_CARD', 'DEBIT_CARD'])

const INFRASTRUCTURE_CONNECTOR_NAMES = new Set(['MEUPLUGGY', 'MEU PLUGGY', 'PLUGGY', 'OPEN FINANCE', 'OPENFINANCE'])

const RAW_ENUM_PATTERN =
  /^(SUCCESS|UPDATED|FAILED|needs_clarification|CHECKING_ACCOUNT|CREDIT_CARD|INVESTMENT|INCOME|EXPENSE|CREDIT|DEBIT|IN|OUT|PARTIAL|RUNNING|PENDING|unknown|classified|BANDEIRADO|BRANDED|UNKNOWN|REFUND|FEE|TAX|PIX_IN|PIX_OUT|TRANSFER_IN|TRANSFER_OUT|DEBIT_PURCHASE|CREDIT_PURCHASE|CARD_PAYMENT|OTHER)$/i

function translate(map: Record<string, string>, value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  return map[value] ?? map[value.toUpperCase()] ?? fallback
}

function inferDirection(rawType: string | null | undefined, direction: string | null | undefined): 'IN' | 'OUT' | null {
  if (direction === 'IN' || direction === 'OUT') return direction
  if (rawType?.toUpperCase() === 'CREDIT') return 'IN'
  if (rawType?.toUpperCase() === 'DEBIT') return 'OUT'
  return null
}

function isExplicitIof(description: string | null | undefined): boolean {
  if (!description?.trim()) return false
  const upper = description.toUpperCase()
  return /\bIOF\b/.test(upper) || upper.includes('IMPOSTO SOBRE OPERACOES FINANCEIRAS')
}

export interface TransactionDisplayInput {
  canonicalType?: string | null
  paymentMethod?: string | null
  direction?: string | null
}

export interface TransactionAccountContextInput {
  displayName?: string | null
  name?: string | null
  marketingName?: string | null
  institutionName?: string | null
  canonicalType?: string | null
  last4?: string | null
  cardBrand?: string | null
}

export function isInfrastructureConnectorName(value: string | null | undefined): boolean {
  if (!value?.trim()) return false
  const normalized = value.trim().toUpperCase().replace(/\s+/g, ' ')
  return INFRASTRUCTURE_CONNECTOR_NAMES.has(normalized.replace(/\s/g, '')) ||
    INFRASTRUCTURE_CONNECTOR_NAMES.has(normalized)
}

export function isTechnicalProductName(value: string | null | undefined): boolean {
  if (!value) return false
  return TECHNICAL_PRODUCT_NAMES.has(value.trim().toUpperCase())
}

export function formatItemStatus(value: string | null | undefined): string {
  return translate(ITEM_STATUS, value, 'Pendente')
}

export function formatSyncStatus(value: string | null | undefined): string {
  return translate(SYNC_STATUS, value, 'Pendente')
}

export function formatAssetType(value: string | null | undefined): string {
  return translate(ASSET_TYPES, value, 'Outro')
}

export function formatTransactionType(value: string | null | undefined): string {
  const translated = translate(TRANSACTION_TYPES, value, '')
  if (translated) return translated
  if (value && isRawEnumVisible(value)) return 'Não identificado'
  return value ?? 'Outro'
}

/**
 * Merges persisted enrichment with strong description/account signals
 * when historical rows lack payment_method/direction/canonical_type.
 */
export function resolveTransactionDisplayInput(
  enrichment: TransactionDisplayInput | null | undefined,
  rawType: string | null | undefined,
  options?: { description?: string | null; accountCanonicalType?: string | null },
): TransactionDisplayInput {
  const description = options?.description ?? ''
  const direction = inferDirection(rawType, enrichment?.direction ?? null)
  let canonicalType = enrichment?.canonicalType ?? null
  let paymentMethod = enrichment?.paymentMethod ?? null

  if (canonicalType === 'REFUND' || /\bestorno\b|\brefund\b/i.test(description)) {
    return { canonicalType: 'REFUND', paymentMethod, direction: direction ?? 'IN' }
  }

  if (isExplicitIof(description) || canonicalType === 'FEE') {
    return { canonicalType: 'FEE', paymentMethod, direction: direction ?? 'OUT' }
  }

  if (/\bPIX\b/i.test(description) || paymentMethod === 'PIX' || canonicalType === 'PIX_IN' || canonicalType === 'PIX_OUT') {
    const dir =
      direction ??
      (canonicalType === 'PIX_IN' ? 'IN' : canonicalType === 'PIX_OUT' ? 'OUT' : rawType === 'CREDIT' ? 'IN' : 'OUT')
    return { canonicalType: dir === 'IN' ? 'PIX_IN' : 'PIX_OUT', paymentMethod: 'PIX', direction: dir }
  }

  if (
    options?.accountCanonicalType === 'CREDIT_CARD' &&
    rawType?.toUpperCase() === 'DEBIT' &&
    (!paymentMethod || paymentMethod === 'UNKNOWN' || canonicalType === 'DEBIT_PURCHASE' || canonicalType === 'EXPENSE')
  ) {
    return { canonicalType: 'CREDIT_PURCHASE', paymentMethod: 'CREDIT_CARD', direction: 'OUT' }
  }

  return { canonicalType, paymentMethod, direction }
}

function formatTransactionDisplayFromResolved(resolved: TransactionDisplayInput, description?: string | null): string {
  const canonical = resolved.canonicalType ?? null
  const paymentMethod = resolved.paymentMethod ?? null
  const direction = resolved.direction ?? null

  if (canonical === 'REFUND') return 'Estorno'
  if (isExplicitIof(description) || (canonical === 'FEE' && isExplicitIof(description ?? ''))) return 'IOF'
  if (canonical === 'FEE' || canonical === 'TAX') return 'Taxa'

  if (paymentMethod === 'PIX' || canonical === 'PIX_IN' || canonical === 'PIX_OUT') {
    if (direction === 'IN' || canonical === 'PIX_IN') return 'PIX recebido'
    return 'PIX enviado'
  }

  if (canonical === 'CREDIT_PURCHASE' || (paymentMethod === 'CREDIT_CARD' && canonical !== 'CARD_PAYMENT')) {
    return 'Compra no cartão de crédito'
  }
  if (canonical === 'CARD_PAYMENT') return 'Pagamento de cartão'

  if (canonical === 'DEBIT_PURCHASE' || paymentMethod === 'DEBIT_CARD') return 'Compra no débito'

  if (paymentMethod === 'TRANSFER' || canonical === 'TRANSFER_IN' || canonical === 'TRANSFER_OUT') {
    return direction === 'IN' || canonical === 'TRANSFER_IN' ? 'Transferência recebida' : 'Transferência enviada'
  }

  if (paymentMethod === 'BOLETO') return 'Boleto'
  if (canonical === 'INCOME' || direction === 'IN') return 'Receita'
  if (canonical === 'EXPENSE' || direction === 'OUT') return 'Despesa'
  if (canonical === 'OTHER') return 'Outro'

  const fromCanonical = formatTransactionType(canonical)
  if (fromCanonical !== 'Outro' && fromCanonical !== 'Não identificado') return fromCanonical
  if (direction === 'IN') return 'Receita'
  if (direction === 'OUT') return 'Despesa'
  return 'Não identificado'
}

/**
 * Central user-facing transaction label (pt-BR).
 * Structured enrichment fields first; description only for strong IOF tokens.
 */
export function formatTransactionDisplay(
  enrichment?: TransactionDisplayInput | null,
  rawType?: string | null,
  options?: { description?: string | null; accountCanonicalType?: string | null },
): string {
  const resolved = resolveTransactionDisplayInput(enrichment, rawType, options)
  return formatTransactionDisplayFromResolved(resolved, options?.description)
}

/** Institution + asset label for transaction list/detail (no UUIDs or raw enums). */
export function formatTransactionAccountContext(account?: TransactionAccountContextInput | null): string | null {
  if (!account) return null

  const institution = account.institutionName?.trim()
  const safeInstitution = institution && !isInfrastructureConnectorName(institution) ? institution : null

  let mainLabel: string
  if (account.displayName?.trim()) {
    mainLabel = account.displayName.trim()
  } else if (account.marketingName?.trim() && !isTechnicalProductName(account.marketingName)) {
    mainLabel = account.marketingName.trim()
  } else if (account.name?.trim() && !isTechnicalProductName(account.name)) {
    mainLabel = account.name.trim()
  } else if (safeInstitution) {
    mainLabel = `${safeInstitution} · ${formatAssetType(account.canonicalType)}`
  } else {
    mainLabel = formatAssetType(account.canonicalType)
  }

  const suffix: string[] = []
  if (account.cardBrand?.trim()) suffix.push(account.cardBrand.trim())
  if (account.last4?.trim()) suffix.push(`•••• ${account.last4.trim()}`)

  if (suffix.length === 0) return mainLabel
  return `${mainLabel} · ${suffix.join(' · ')}`
}

export function formatClassificationStatus(value: string | null | undefined): string {
  return translate(CLASSIFICATION_STATUS, value, 'Desconhecido')
}

export function formatBudgetStatus(value: string | null | undefined): string {
  return translate(BUDGET_STATUS, value, value ?? '—')
}

export function formatAccountDisplayName(input: {
  displayName?: string | null
  name?: string | null
  marketingName?: string | null
  institutionName?: string | null
  canonicalType?: string | null
}): string {
  if (input.displayName?.trim()) return input.displayName.trim()
  const marketing = input.marketingName?.trim()
  if (marketing && !isTechnicalProductName(marketing)) return marketing
  const name = input.name?.trim()
  if (name && !isTechnicalProductName(name)) return name
  const typeLabel = formatAssetType(input.canonicalType)
  if (input.institutionName && !isInfrastructureConnectorName(input.institutionName)) {
    return `${input.institutionName} — ${typeLabel}`
  }
  return typeLabel
}

export function formatMaskedNumber(value: string | null | undefined): string | null {
  if (!value?.trim()) return null
  const digits = value.replace(/\D/g, '')
  if (digits.length >= 4) return `•••• ${digits.slice(-4)}`
  return value
}

export function maskItemId(itemId: string): string {
  const trimmed = itemId.trim()
  if (trimmed.length <= 8) return '••••'
  return `••••${trimmed.slice(-8)}`
}

export function isRawEnumVisible(value: string | null | undefined): boolean {
  if (!value) return false
  return RAW_ENUM_PATTERN.test(value.trim())
}

export function onboardingMessage(outcome: string): string {
  switch (outcome) {
    case 'created':
      return 'Conexão adicionada'
    case 'already_registered':
      return 'Conexão já cadastrada'
    case 'invalid_id':
      return 'ID inválido'
    case 'not_accessible':
      return 'Não foi possível acessar essa conexão'
    case 'sync_failed':
      return 'Falha temporária ao sincronizar'
    default:
      return 'Operação concluída'
  }
}

export function onboardingStateLabel(state: 'idle' | 'validating' | 'syncing' | 'done' | 'error'): string {
  switch (state) {
    case 'validating':
      return 'Validando...'
    case 'syncing':
      return 'Sincronizando...'
    case 'done':
      return 'Conexão adicionada'
    case 'error':
      return 'Não foi possível concluir'
    default:
      return ''
  }
}

/** @deprecated Use formatTransactionDisplay — kept for legacy imports */
export function formatPaymentMethod(value: string | null | undefined): string {
  if (value === 'PIX') return 'PIX'
  if (value === 'CREDIT_CARD') return 'Compra no cartão de crédito'
  if (value === 'DEBIT_CARD') return 'Compra no débito'
  if (value === 'TRANSFER') return 'Transferência'
  if (value === 'BOLETO') return 'Boleto'
  if (!value || value === 'UNKNOWN') return 'Não identificado'
  return isRawEnumVisible(value) ? 'Não identificado' : value
}
