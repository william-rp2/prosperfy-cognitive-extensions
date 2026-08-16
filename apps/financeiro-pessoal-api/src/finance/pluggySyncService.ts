import type { CreditCardBills, Investment } from 'pluggy-sdk'

import type { PluggySyncClient } from '../pluggy.js'
import type { AccountsRepository } from './accountsRepository.js'
import { mapWithConcurrency } from './concurrency.js'
import type { ItemsRepository } from './itemsRepository.js'
import type { ProductsRepository } from './productsRepository.js'
import { withRetry } from './retry.js'
import type { SyncRunsRepository } from './syncRunsRepository.js'
import type { TransactionsRepository } from './transactionsRepository.js'
import { toCents, type FinancialSyncRunRow, type SyncStatus, type SyncTrigger } from './types.js'

export interface SyncLogger {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- pino's LogFn has overloaded signatures; keep this loose so app.log is assignable as-is.
  info?: (...args: any[]) => void
  warn?: (...args: any[]) => void
  error?: (...args: any[]) => void
}

export interface PluggySyncServiceOptions {
  pluggy: PluggySyncClient
  items: ItemsRepository
  accounts: AccountsRepository
  transactions: TransactionsRepository
  products: ProductsRepository
  syncRuns: SyncRunsRepository
  /** Overlap window subtracted from the last known transaction date, to catch retroactive edits. */
  safetyWindowHours: number
  maxConcurrentItems: number
  logger?: SyncLogger
}

interface ItemSyncResult {
  itemId: string
  accountsProcessed: number
  transactionsCreated: number
  transactionsUpdated: number
  error?: string
}

/**
 * Only items that can't produce any data right now are skipped before hitting the
 * Accounts/Transactions endpoints. WAITING_USER_INPUT/ACTION still expose whatever
 * was collected on a previous successful run, so those are synced normally.
 */
const UNSYNCABLE_STATUSES = new Set(['LOGIN_ERROR'])

export class PluggySyncService {
  constructor(private readonly opts: PluggySyncServiceOptions) {}

  /** Iterates every Item we already know about (persisted at Connect-Widget time) — Pluggy has no "list items" endpoint. */
  async syncAll(trigger: SyncTrigger): Promise<FinancialSyncRunRow> {
    const run = this.opts.syncRuns.startRun(trigger)
    const startedAt = Date.now()
    const items = this.opts.items.listAll()

    const results = await mapWithConcurrency(items, this.opts.maxConcurrentItems, item => this.syncItemSafe(item.pluggy_item_id))

    this.finishRun(run.id, items.length, results, startedAt)
    return this.opts.syncRuns.getById(run.id)!
  }

  /** Convenience wrapper for a single Item — e.g. right after Connect Widget success. Shares the same run-lock as syncAll. */
  async syncOne(pluggyItemId: string, trigger: SyncTrigger = 'manual'): Promise<FinancialSyncRunRow> {
    const run = this.opts.syncRuns.startRun(trigger)
    const startedAt = Date.now()
    const result = await this.syncItemSafe(pluggyItemId)
    this.finishRun(run.id, 1, [result], startedAt)
    return this.opts.syncRuns.getById(run.id)!
  }

  private finishRun(runId: string, itemsProcessed: number, results: ItemSyncResult[], startedAt: number) {
    const accountsProcessed = results.reduce((sum, r) => sum + r.accountsProcessed, 0)
    const transactionsCreated = results.reduce((sum, r) => sum + r.transactionsCreated, 0)
    const transactionsUpdated = results.reduce((sum, r) => sum + r.transactionsUpdated, 0)
    const errors = results.filter(r => r.error)

    let status: SyncStatus = 'success'
    if (errors.length > 0) status = errors.length === results.length ? 'failed' : 'partial'

    this.opts.syncRuns.finishRun(runId, {
      status,
      itemsProcessed,
      accountsProcessed,
      transactionsCreated,
      transactionsUpdated,
      errorCount: errors.length,
      errorSummary: errors.length ? errors.map(e => ({ itemId: e.itemId, message: e.error })) : undefined,
      metadata: { durationMs: Date.now() - startedAt },
    })
  }

  /** One bank's failure (LOGIN_ERROR, timeout, whatever) must not sink the whole run — that's what makes status = PARTIAL possible. */
  private async syncItemSafe(pluggyItemId: string): Promise<ItemSyncResult> {
    try {
      const result = await this.syncItemInternal(pluggyItemId)
      this.opts.items.setErrorSummary(pluggyItemId, null)
      return result
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Erro desconhecido'
      this.opts.logger?.error?.({ err: error, pluggyItemId }, 'pluggy sync: item failed')
      this.opts.items.setErrorSummary(pluggyItemId, message)
      return { itemId: pluggyItemId, accountsProcessed: 0, transactionsCreated: 0, transactionsUpdated: 0, error: message }
    }
  }

  private async syncItemInternal(pluggyItemId: string): Promise<ItemSyncResult> {
    const item = await withRetry(() => this.opts.pluggy.fetchItem(pluggyItemId), { onRetry: this.logRetry(pluggyItemId, 'fetchItem') })

    this.opts.items.upsertItem({
      pluggyItemId,
      connectorId: item.connector?.id ?? null,
      connectorName: item.connector?.name ?? null,
      status: item.status,
      executionStatus: item.executionStatus,
      lastSuccessfulUpdate: item.lastUpdatedAt ? new Date(item.lastUpdatedAt).toISOString() : null,
      rawMetadata: { connector: item.connector, statusDetail: item.statusDetail },
    })

    if (UNSYNCABLE_STATUSES.has(item.status)) {
      this.opts.items.touchSynced(pluggyItemId)
      return { itemId: pluggyItemId, accountsProcessed: 0, transactionsCreated: 0, transactionsUpdated: 0 }
    }

    const accounts = await withRetry(() => this.opts.pluggy.fetchAccounts(pluggyItemId), {
      onRetry: this.logRetry(pluggyItemId, 'fetchAccounts'),
    })

    let transactionsCreated = 0
    let transactionsUpdated = 0

    for (const account of accounts) {
      this.opts.accounts.upsertAccount({
        pluggyAccountId: account.id,
        pluggyItemId,
        type: account.type,
        subtype: account.subtype,
        name: account.name,
        marketingName: account.marketingName,
        currencyCode: account.currencyCode,
        balanceCents: toCents(account.balance),
        numberMasked: maskAccountNumber(account.number),
        owner: account.owner,
        creditLimitCents: account.creditData?.creditLimit != null ? toCents(account.creditData.creditLimit) : null,
        availableCreditLimitCents:
          account.creditData?.availableCreditLimit != null ? toCents(account.creditData.availableCreditLimit) : null,
        rawData: account,
      })

      const dateFrom = this.incrementalDateFrom(account.id)
      const transactions = await withRetry(() => this.opts.pluggy.fetchAllTransactions(account.id, { dateFrom }), {
        onRetry: this.logRetry(pluggyItemId, `fetchAllTransactions:${account.id}`),
      })

      for (const transaction of transactions) {
        const { created } = this.opts.transactions.upsertTransaction({
          pluggyTransactionId: transaction.id,
          pluggyAccountId: account.id,
          description: transaction.description,
          descriptionRaw: transaction.descriptionRaw,
          amountCents: toCents(transaction.amount),
          currencyCode: transaction.currencyCode,
          date: new Date(transaction.date).toISOString(),
          status: transaction.status ?? null,
          type: transaction.type,
          categoryOriginal: transaction.category,
          merchantOriginal: transaction.merchant?.name ?? null,
          balanceCents: transaction.balance != null ? toCents(transaction.balance) : null,
          rawData: transaction,
        })
        if (created) transactionsCreated += 1
        else transactionsUpdated += 1
      }

      if (account.type === 'CREDIT') await this.syncCreditCardBills(pluggyItemId, account.id)
    }

    await this.syncInvestments(pluggyItemId)

    this.opts.items.touchSynced(pluggyItemId)
    return { itemId: pluggyItemId, accountsProcessed: accounts.length, transactionsCreated, transactionsUpdated }
  }

  /** Not all connectors/plans expose bills — a failure here is logged and swallowed, never fails the whole item. */
  private async syncCreditCardBills(pluggyItemId: string, accountId: string) {
    let bills: CreditCardBills[]
    try {
      bills = await withRetry(() => this.opts.pluggy.fetchCreditCardBills(accountId), {
        onRetry: this.logRetry(pluggyItemId, `fetchCreditCardBills:${accountId}`),
      })
    } catch (error) {
      this.opts.logger?.warn?.({ err: error, accountId }, 'pluggy sync: credit card bills indisponível (verificar se é recurso Pro/NÃO DISPONÍVEL NO MODO PESSOAL)')
      return
    }

    for (const bill of bills) {
      this.opts.products.upsertCreditCardBill({
        pluggyBillId: bill.id,
        pluggyAccountId: accountId,
        dueDate: bill.dueDate ? new Date(bill.dueDate).toISOString() : null,
        billClosingDate: bill.billClosingDate ? new Date(bill.billClosingDate).toISOString() : null,
        totalAmountCents: bill.totalAmount != null ? toCents(bill.totalAmount) : null,
        minimumPaymentCents: bill.minimumPaymentAmount != null ? toCents(bill.minimumPaymentAmount) : null,
        currencyCode: bill.totalAmountCurrencyCode,
        rawData: bill,
      })
    }
  }

  /** Same swallow-and-log rule as bills — investments may not be enabled for this connector. */
  private async syncInvestments(pluggyItemId: string) {
    let investments: Investment[]
    try {
      investments = await withRetry(() => this.opts.pluggy.fetchInvestments(pluggyItemId), {
        onRetry: this.logRetry(pluggyItemId, 'fetchInvestments'),
      })
    } catch (error) {
      this.opts.logger?.warn?.({ err: error, pluggyItemId }, 'pluggy sync: investments indisponível (verificar se é recurso Pro/NÃO DISPONÍVEL NO MODO PESSOAL)')
      return
    }

    for (const investment of investments) {
      this.opts.products.upsertInvestment({
        pluggyInvestmentId: investment.id,
        pluggyItemId,
        type: investment.type,
        subtype: investment.subtype,
        name: investment.name,
        code: investment.code,
        balanceCents: investment.balance != null ? toCents(investment.balance) : null,
        quantity: investment.quantity != null ? String(investment.quantity) : null,
        rate: investment.rate ?? null,
        rateType: investment.rateType ?? null,
        referenceDate: investment.date ? new Date(investment.date).toISOString() : null,
        rawData: investment,
      })
    }
  }

  private incrementalDateFrom(pluggyAccountId: string): string | undefined {
    const latest = this.opts.transactions.latestDateForAccount(pluggyAccountId)
    if (!latest) return undefined
    const safetyWindowMs = this.opts.safetyWindowHours * 60 * 60 * 1000
    return new Date(new Date(latest).getTime() - safetyWindowMs).toISOString().slice(0, 10)
  }

  private logRetry(pluggyItemId: string, op: string) {
    return (attempt: number, delayMs: number, error: unknown) => {
      this.opts.logger?.warn?.({ pluggyItemId, op, attempt, delayMs, err: error }, 'pluggy sync: retry after transient error')
    }
  }
}

function maskAccountNumber(number: string | null | undefined): string | null {
  if (!number) return null
  if (number.length <= 4) return number
  return `••••${number.slice(-4)}`
}
