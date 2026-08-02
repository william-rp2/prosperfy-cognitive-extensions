export interface PluggyItemAssociation {
  itemId: string
  clientUserId: string
  createdAt: string
  updatedAt: string
  status: string
  lastSyncAt?: string
  error?: unknown
}

export interface WebhookAuditEvent {
  eventId: string
  event: string
  itemId?: string
  status: 'received' | 'processing' | 'processed' | 'error'
  receivedAt: string
  processedAt?: string
  rawPayload: unknown
  error?: string
}

export interface TransactionTombstone {
  transactionId: string
  eventId: string
  deletedAt: string
}

export interface PluggyPocStoreData {
  items: Record<string, PluggyItemAssociation>
  webhookEvents: Record<string, WebhookAuditEvent>
  webhookHistory: string[]
  transactionTombstones: Record<string, TransactionTombstone>
}

export const emptyStore: PluggyPocStoreData = {
  items: {},
  webhookEvents: {},
  webhookHistory: [],
  transactionTombstones: {},
}
