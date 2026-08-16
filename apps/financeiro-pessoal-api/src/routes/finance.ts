import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import type { AccountsRepository } from '../finance/accountsRepository.js'
import type { ItemsRepository } from '../finance/itemsRepository.js'
import type { PluggySyncScheduler } from '../finance/scheduler.js'
import { SyncAlreadyRunningError } from '../finance/syncRunsRepository.js'
import type { SyncRunsRepository } from '../finance/syncRunsRepository.js'
import type { PluggySyncService } from '../finance/pluggySyncService.js'
import { fromCents } from '../finance/types.js'
import type { TransactionsRepository } from '../finance/transactionsRepository.js'
import { safeCompare } from '../safe.js'

export interface FinanceRouteDeps {
  config: AppConfig
  items: ItemsRepository
  accounts: AccountsRepository
  transactions: TransactionsRepository
  syncRuns: SyncRunsRepository
  syncService: PluggySyncService
  scheduler: PluggySyncScheduler
}

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

export function registerFinanceRoutes(app: FastifyInstance, deps: FinanceRouteDeps) {
  const { config, items, accounts, transactions, syncRuns, syncService, scheduler } = deps

  app.get('/api/finance/status', async () => {
    const allItems = items.listAll()
    const latestRun = syncRuns.getLatest()
    return {
      pluggy: config.PLUGGY_CLIENT_ID && config.PLUGGY_CLIENT_SECRET ? 'connected' : 'not_configured',
      mode: 'meu_pluggy_connector_200',
      webhooks: 'unavailable_in_free_tier',
      items: allItems.length,
      itemsWithError: allItems.filter(item => item.error_summary).length,
      accounts: accounts.listAll().length,
      lastSync: latestRun?.started_at ?? null,
      lastSyncStatus: latestRun?.status ?? null,
      nextSync: scheduler.getNextRunAt(),
      syncEnabled: config.PLUGGY_SYNC_ENABLED,
    }
  })

  app.get('/api/finance/accounts', async () => {
    return {
      accounts: accounts.listAll().map(account => ({
        id: account.pluggy_account_id,
        itemId: account.pluggy_item_id,
        type: account.type,
        subtype: account.subtype,
        name: account.name,
        marketingName: account.marketing_name,
        currencyCode: account.currency_code,
        balance: fromCents(account.balance_cents),
        numberMasked: account.number_masked,
        creditLimit: fromCents(account.credit_limit_cents),
        availableCreditLimit: fromCents(account.available_credit_limit_cents),
        lastSyncedAt: account.last_synced_at,
      })),
    }
  })

  app.get('/api/finance/transactions', async request => {
    const query = request.query as Record<string, string | undefined>
    const rows = transactions.list({
      accountId: query.account,
      startDate: query.startDate,
      endDate: query.endDate,
      category: query.category,
      minAmountCents: query.minAmount ? Math.round(Number(query.minAmount) * 100) : undefined,
      maxAmountCents: query.maxAmount ? Math.round(Number(query.maxAmount) * 100) : undefined,
      search: query.search,
      limit: query.limit ? Number(query.limit) : undefined,
      offset: query.offset ? Number(query.offset) : undefined,
    })

    return {
      transactions: rows.map(row => ({
        id: row.pluggy_transaction_id,
        accountId: row.pluggy_account_id,
        description: row.description,
        amount: fromCents(row.amount_cents),
        currencyCode: row.currency_code,
        date: row.date,
        type: row.type,
        status: row.status,
        category: row.category_original,
        merchant: row.merchant_original,
      })),
    }
  })

  app.get('/api/finance/summary', async () => {
    const now = new Date()
    const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString()
    const monthEnd = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0, 23, 59, 59)).toISOString()
    const { income, expense } = transactions.sumByDateRange(monthStart, monthEnd)

    const allAccounts = accounts.listAll()
    const totalBalance = allAccounts
      .filter(account => account.type !== 'CREDIT')
      .reduce((sum, account) => sum + (account.balance_cents ?? 0), 0)
    const openCardBalance = allAccounts
      .filter(account => account.type === 'CREDIT')
      .reduce((sum, account) => sum + Math.abs(account.balance_cents ?? 0), 0)

    const latestRun = syncRuns.getLatest()

    return {
      totalBalance: fromCents(totalBalance),
      monthIncome: fromCents(income),
      monthExpense: fromCents(expense),
      monthResult: fromCents(income - expense),
      openCardBalance: fromCents(openCardBalance),
      lastSync: latestRun?.started_at ?? null,
    }
  })

  app.get('/api/finance/sync/status', async () => {
    const latest = syncRuns.getLatest()
    return {
      latest,
      recent: syncRuns.listRecent(10),
      nextSync: scheduler.getNextRunAt(),
      syncEnabled: config.PLUGGY_SYNC_ENABLED,
    }
  })

  app.post('/api/finance/sync', async (request, reply) => {
    if (!requireFinanceToken(request, config)) {
      return reply.code(401).send({ error: 'unauthorized', message: 'FINANCE_API_TOKEN ausente/inválido no header Authorization: Bearer <token>.' })
    }

    const startedAt = Date.now()
    try {
      const run = await syncService.syncAll('manual')
      return reply.send({
        success: run.status !== 'failed',
        status: run.status,
        items: run.items_processed,
        accounts: run.accounts_processed,
        transactionsCreated: run.transactions_created,
        transactionsUpdated: run.transactions_updated,
        errorCount: run.error_count,
        durationMs: Date.now() - startedAt,
      })
    } catch (error) {
      if (error instanceof SyncAlreadyRunningError) {
        return reply.code(409).send({ error: 'sync_already_running', message: error.message })
      }
      app.log.error({ err: error }, 'finance sync failed')
      return reply.code(500).send({ error: 'sync_failed', message: error instanceof Error ? error.message : 'Erro desconhecido' })
    }
  })
}
