import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'

import { emptyStore, PluggyItemAssociation, PluggyPocStoreData, WebhookAuditEvent } from './types.js'

export class JsonPocStore {
  private readonly path: string
  private queue: Promise<unknown> = Promise.resolve()

  constructor(path: string) {
    this.path = resolve(path)
  }

  async read(): Promise<PluggyPocStoreData> {
    try {
      const raw = await readFile(this.path, 'utf8')
      return { ...structuredClone(emptyStore), ...JSON.parse(raw) }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return structuredClone(emptyStore)
      throw error
    }
  }

  async write(data: PluggyPocStoreData) {
    await mkdir(dirname(this.path), { recursive: true })
    await writeFile(this.path, `${JSON.stringify(data, null, 2)}\n`, 'utf8')
  }

  async upsertItem(itemId: string, clientUserId: string): Promise<PluggyItemAssociation> {
    return this.atomic(async () => {
    const data = await this.read()
    const now = new Date().toISOString()
    const existing = data.items[itemId]
    const item = {
      itemId,
      clientUserId,
      createdAt: existing?.createdAt || now,
      updatedAt: now,
      status: existing?.status || 'connected',
      lastSyncAt: existing?.lastSyncAt,
      error: existing?.error,
    }
    data.items[itemId] = item
    await this.write(data)
    return item
    })
  }

  async updateItem(itemId: string, patch: Partial<PluggyItemAssociation>) {
    return this.atomic(async () => {
    const data = await this.read()
    const current = data.items[itemId]
    if (!current) return null
    data.items[itemId] = { ...current, ...patch, updatedAt: new Date().toISOString() }
    await this.write(data)
    return data.items[itemId]
    })
  }

  async recordWebhook(event: WebhookAuditEvent): Promise<{ inserted: boolean; event: WebhookAuditEvent }> {
    return this.atomic(async () => {
    const data = await this.read()
    const existing = data.webhookEvents[event.eventId]
    if (existing) return { inserted: false, event: existing }
    data.webhookEvents[event.eventId] = event
    data.webhookHistory = [event.eventId, ...data.webhookHistory.filter(id => id !== event.eventId)].slice(0, 50)
    await this.write(data)
    return { inserted: true, event }
    })
  }

  async updateWebhook(eventId: string, patch: Partial<WebhookAuditEvent>) {
    return this.atomic(async () => {
    const data = await this.read()
    const current = data.webhookEvents[eventId]
    if (!current) return null
    data.webhookEvents[eventId] = { ...current, ...patch }
    await this.write(data)
    return data.webhookEvents[eventId]
    })
  }

  async tombstoneTransactions(eventId: string, ids: string[]) {
    return this.atomic(async () => {
    const data = await this.read()
    const deletedAt = new Date().toISOString()
    for (const transactionId of ids) {
      data.transactionTombstones[transactionId] = { transactionId, eventId, deletedAt }
    }
    await this.write(data)
    })
  }

  private async atomic<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.queue.then(operation, operation)
    this.queue = next.catch(() => undefined)
    return next
  }
}
