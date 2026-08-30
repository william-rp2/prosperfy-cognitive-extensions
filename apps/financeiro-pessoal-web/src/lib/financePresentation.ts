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
  CREDIT_PURCHASE: 'Compra no crédito',
  DEBIT_PURCHASE: 'Compra no débito',
  TRANSFER_IN: 'Transferência recebida',
  TRANSFER_OUT: 'Transferência enviada',
  INCOME: 'Receita',
  EXPENSE: 'Despesa',
  CARD_PAYMENT: 'Pagamento de cartão',
  REFUND: 'Estorno',
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

const RAW_ENUM_PATTERN =
  /^(SUCCESS|UPDATED|FAILED|needs_clarification|CHECKING_ACCOUNT|CREDIT_CARD|INVESTMENT|INCOME|EXPENSE|CREDIT|DEBIT|IN|OUT|PARTIAL|RUNNING|PENDING|unknown|classified)$/i

function translate(map: Record<string, string>, value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  return map[value] ?? map[value.toUpperCase()] ?? fallback
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
  return translate(TRANSACTION_TYPES, value, 'Outro')
}

export function formatClassificationStatus(value: string | null | undefined): string {
  return translate(CLASSIFICATION_STATUS, value, 'Desconhecido')
}

export function formatBudgetStatus(value: string | null | undefined): string {
  return translate(BUDGET_STATUS, value, value ?? '—')
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
