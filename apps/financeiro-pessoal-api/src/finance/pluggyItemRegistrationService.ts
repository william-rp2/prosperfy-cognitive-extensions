import type { Item } from 'pluggy-sdk'

import type { PluggySyncClient } from '../pluggy.js'
import type { JsonPocStore } from '../store.js'
import type { ItemsRepository } from './itemsRepository.js'
import type { PluggySyncService } from './pluggySyncService.js'
import { SyncAlreadyRunningError } from './syncRunsRepository.js'

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export type RegisterItemOutcome = 'created' | 'already_registered' | 'invalid_id' | 'not_accessible' | 'sync_failed'

export interface RegisterItemResult {
  outcome: RegisterItemOutcome
  connectorName: string | null
  syncStatus?: 'success' | 'partial' | 'failed' | 'deferred'
  message?: string
}

export interface PluggyItemRegistrationDeps {
  pluggy: PluggySyncClient
  items: ItemsRepository
  syncService: PluggySyncService
  store?: JsonPocStore
  clientUserId: string
  logger?: { warn?: (...args: unknown[]) => void; error?: (...args: unknown[]) => void }
}

export class PluggyItemRegistrationService {
  constructor(private readonly deps: PluggyItemRegistrationDeps) {}

  validateItemId(itemId: string): boolean {
    return UUID_REGEX.test(itemId.trim())
  }

  maskItemId(itemId: string): string {
    const trimmed = itemId.trim()
    if (trimmed.length <= 8) return '••••'
    return `••••${trimmed.slice(-8)}`
  }

  async registerItem(itemId: string): Promise<RegisterItemResult> {
    const normalizedId = itemId.trim()
    if (!this.validateItemId(normalizedId)) {
      return { outcome: 'invalid_id', connectorName: null, message: 'ID inválido.' }
    }

    const existing = this.deps.items.getByPluggyId(normalizedId)
    if (existing) {
      return {
        outcome: 'already_registered',
        connectorName: existing.connector_name,
        message: 'Conexão já cadastrada.',
      }
    }

    let pluggyItem: Item
    try {
      pluggyItem = await this.deps.pluggy.fetchItem(normalizedId)
    } catch (error) {
      this.deps.logger?.warn?.({ err: error, itemIdSuffix: this.maskItemId(normalizedId) }, 'pluggy: item inacessível no registro')
      return {
        outcome: 'not_accessible',
        connectorName: null,
        message: 'Não foi possível acessar essa conexão.',
      }
    }

    if (this.deps.store) {
      await this.deps.store.upsertItem(normalizedId, this.deps.clientUserId)
    }

    this.deps.items.upsertItem({
      pluggyItemId: normalizedId,
      connectorId: pluggyItem.connector?.id ?? null,
      connectorName: pluggyItem.connector?.name ?? null,
      status: pluggyItem.status,
      executionStatus: pluggyItem.executionStatus,
      lastSuccessfulUpdate: pluggyItem.lastUpdatedAt ? new Date(pluggyItem.lastUpdatedAt).toISOString() : null,
      rawMetadata: { connector: pluggyItem.connector, statusDetail: pluggyItem.statusDetail },
    })

    try {
      const run = await this.deps.syncService.syncOne(normalizedId, 'initial')
      const syncStatus = run.status === 'failed' ? 'failed' : run.status === 'partial' ? 'partial' : 'success'
      return {
        outcome: 'created',
        connectorName: pluggyItem.connector?.name ?? null,
        syncStatus,
        message: 'Conexão adicionada.',
      }
    } catch (error) {
      if (error instanceof SyncAlreadyRunningError) {
        return {
          outcome: 'created',
          connectorName: pluggyItem.connector?.name ?? null,
          syncStatus: 'deferred',
          message: 'Conexão adicionada. Sincronização em andamento.',
        }
      }
      this.deps.logger?.error?.({ err: error, itemIdSuffix: this.maskItemId(normalizedId) }, 'pluggy: sync pós-registro falhou')
      return {
        outcome: 'sync_failed',
        connectorName: pluggyItem.connector?.name ?? null,
        message: 'Falha temporária ao sincronizar.',
      }
    }
  }
}
