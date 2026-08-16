import { Account, CreditCardBills, Investment, Item, PageFilters, PluggyClient, Transaction } from 'pluggy-sdk'

import { AppConfig } from './config.js'

export interface PluggySnapshotFilters {
  dateFrom?: string
  dateTo?: string
}

export interface PluggyPort {
  createConnectToken(): Promise<{ accessToken: string }>
  fetchSnapshot(itemId: string, filters: PluggySnapshotFilters): Promise<unknown>
}

/**
 * Granular, sync-oriented surface of the Pluggy client (one Item/Account/Transactions
 * call at a time instead of the POC's all-in-one snapshot). Kept as a separate
 * interface so PluggySyncService can be tested with a fake without touching the
 * existing PluggyPort/server.test.ts contract.
 */
export interface PluggySyncClient {
  fetchItem(itemId: string): Promise<Item>
  fetchAccounts(itemId: string): Promise<Account[]>
  fetchAllTransactions(accountId: string, filters: { dateFrom?: string; dateTo?: string }): Promise<Transaction[]>
  fetchCreditCardBills(accountId: string, options?: PageFilters): Promise<CreditCardBills[]>
  fetchInvestments(itemId: string): Promise<Investment[]>
}

export class MissingPluggySecretsError extends Error {
  constructor() {
    super('PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET precisam estar configurados no backend.')
  }
}

/**
 * Single centralized wrapper around the Pluggy SDK client. Construction never throws —
 * the `PLUGGY_CLIENT_ID`/`PLUGGY_CLIENT_SECRET` check is deferred to first actual use
 * (`ensureClient`), so one instance can be built once at app boot (createApp) and
 * shared by every route/service, instead of `new SdkPluggyPort(config)` being
 * repeated (and re-validated) in each route handler.
 */
export class SdkPluggyPort implements PluggyPort, PluggySyncClient {
  private client: PluggyClient | null = null
  private readonly config: AppConfig

  constructor(config: AppConfig) {
    this.config = config
  }

  private ensureClient(): PluggyClient {
    if (this.client) return this.client
    if (!this.config.PLUGGY_CLIENT_ID || !this.config.PLUGGY_CLIENT_SECRET) throw new MissingPluggySecretsError()
    this.client = new PluggyClient({
      clientId: this.config.PLUGGY_CLIENT_ID,
      clientSecret: this.config.PLUGGY_CLIENT_SECRET,
    })
    return this.client
  }

  async fetchItem(itemId: string): Promise<Item> {
    return this.ensureClient().fetchItem(itemId)
  }

  async fetchAccounts(itemId: string): Promise<Account[]> {
    const response = await this.ensureClient().fetchAccounts(itemId)
    return response.results
  }

  /** Uses GET /v2/transactions (cursor pagination) via the SDK's fetchAllTransactions helper. */
  async fetchAllTransactions(accountId: string, filters: { dateFrom?: string; dateTo?: string }): Promise<Transaction[]> {
    return this.ensureClient().fetchAllTransactions(accountId, filters)
  }

  /** Credit card bills — only meaningful for CREDIT accounts; returns [] otherwise/if unsupported by the connector. */
  async fetchCreditCardBills(accountId: string, options?: PageFilters): Promise<CreditCardBills[]> {
    const pageSize = options?.pageSize ?? 100
    const results: CreditCardBills[] = []
    let page = 1
    for (;;) {
      const response = await this.ensureClient().fetchCreditCardBills(accountId, { page, pageSize })
      results.push(...response.results)
      if (page >= response.totalPages || response.results.length === 0) break
      page += 1
    }
    return results
  }

  /** Investments for an Item — returns [] if the connector doesn't expose the product. */
  async fetchInvestments(itemId: string): Promise<Investment[]> {
    const pageSize = 100
    const results: Investment[] = []
    let page = 1
    for (;;) {
      const response = await this.ensureClient().fetchInvestments(itemId, undefined, { page, pageSize })
      results.push(...response.results)
      if (page >= response.totalPages || response.results.length === 0) break
      page += 1
    }
    return results
  }

  async createConnectToken() {
    const webhookUrl = this.config.PUBLIC_BASE_URL
      ? `${this.config.PUBLIC_BASE_URL.replace(/\/$/, '')}/api/webhooks/pluggy`
      : undefined

    return this.ensureClient().createConnectToken(undefined, {
      clientUserId: this.config.PLUGGY_CLIENT_USER_ID,
      avoidDuplicates: true,
      webhookUrl,
    })
  }

  async fetchSnapshot(itemId: string, filters: PluggySnapshotFilters) {
    const client = this.ensureClient()
    const item = await client.fetchItem(itemId)
    const accounts = await client.fetchAccounts(itemId)
    const accountResults = accounts.results || []
    const accountSnapshots = []

    for (const account of accountResults) {
      const accountId = account.id
      const transactions = await this.safeFetch(() =>
        client.fetchAllTransactions(accountId, {
          dateFrom: filters.dateFrom,
          dateTo: filters.dateTo,
        }),
      )
      const bills = await this.safeFetch(() => client.fetchCreditCardBills(accountId))
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
