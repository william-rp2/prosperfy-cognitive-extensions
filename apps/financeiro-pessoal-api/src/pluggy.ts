import { PluggyClient } from 'pluggy-sdk'

import { AppConfig } from './config.js'

export interface PluggySnapshotFilters {
  dateFrom?: string
  dateTo?: string
}

export interface PluggyPort {
  createConnectToken(): Promise<{ accessToken: string }>
  fetchSnapshot(itemId: string, filters: PluggySnapshotFilters): Promise<unknown>
}

export class MissingPluggySecretsError extends Error {
  constructor() {
    super('PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET precisam estar configurados no backend.')
  }
}

export class SdkPluggyPort implements PluggyPort {
  private readonly client: PluggyClient
  private readonly clientUserId: string
  private readonly publicBaseUrl?: string

  constructor(config: AppConfig) {
    if (!config.PLUGGY_CLIENT_ID || !config.PLUGGY_CLIENT_SECRET) throw new MissingPluggySecretsError()
    this.client = new PluggyClient({
      clientId: config.PLUGGY_CLIENT_ID,
      clientSecret: config.PLUGGY_CLIENT_SECRET,
    })
    this.clientUserId = config.PLUGGY_CLIENT_USER_ID
    this.publicBaseUrl = config.PUBLIC_BASE_URL
  }

  async createConnectToken() {
    const webhookUrl = this.publicBaseUrl
      ? `${this.publicBaseUrl.replace(/\/$/, '')}/api/webhooks/pluggy`
      : undefined

    return this.client.createConnectToken(undefined, {
      clientUserId: this.clientUserId,
      avoidDuplicates: true,
      webhookUrl,
    })
  }

  async fetchSnapshot(itemId: string, filters: PluggySnapshotFilters) {
    const item = await this.client.fetchItem(itemId)
    const accounts = await this.client.fetchAccounts(itemId)
    const accountResults = accounts.results || []
    const accountSnapshots = []

    for (const account of accountResults) {
      const accountId = account.id
      const transactions = await this.safeFetch(() =>
        this.client.fetchAllTransactions(accountId, {
          dateFrom: filters.dateFrom,
          dateTo: filters.dateTo,
        }),
      )
      const bills = await this.safeFetch(() => this.client.fetchCreditCardBills(accountId))
      accountSnapshots.push({ account, transactions, bills })
    }

    return {
      item,
      accounts: accountResults,
      accountSnapshots,
      fetchedAt: new Date().toISOString(),
      filters,
    }
  }

  private async safeFetch<T>(operation: () => Promise<T>): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
    try {
      return { ok: true, data: await operation() }
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : 'Erro desconhecido na Pluggy.' }
    }
  }
}
