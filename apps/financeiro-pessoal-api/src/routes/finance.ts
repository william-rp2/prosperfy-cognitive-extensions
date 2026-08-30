import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import { resolveSyncIntervalMinutes } from '../config.js'
import { aggregateFinancialAssets, resolveAccountCanonicalType } from '../finance/accountAggregation.js'
import type { AccountsRepository } from '../finance/accountsRepository.js'
import { CASH_ASSET_TYPES, type CanonicalFinancialAssetType } from '../finance/financialAssetNormalizer.js'
import type { BudgetWithStatus } from '../finance/budgetsRepository.js'
import { assertValidMonth, BudgetsRepository, monthRange } from '../finance/budgetsRepository.js'
import type { FinancialCategoryRow } from '../finance/categoriesRepository.js'
import { CategoriesRepository } from '../finance/categoriesRepository.js'
import type { CategoryOverridesRepository } from '../finance/categoryOverridesRepository.js'
import type { ClarificationsRepository } from '../finance/clarificationsRepository.js'
import type { EnrichmentRepository, EnrichmentRow } from '../finance/enrichmentRepository.js'
import type { ItemsRepository } from '../finance/itemsRepository.js'
import type { ManualDirection } from '../finance/manualTransactionsRepository.js'
import { ManualTransactionsRepository } from '../finance/manualTransactionsRepository.js'
import type { ProductsRepository } from '../finance/productsRepository.js'
import type { PluggySyncScheduler } from '../finance/scheduler.js'
import { SyncAlreadyRunningError } from '../finance/syncRunsRepository.js'
import type { SyncRunsRepository } from '../finance/syncRunsRepository.js'
import type { PluggySyncService } from '../finance/pluggySyncService.js'
import type { PluggyItemRegistrationService } from '../finance/pluggyItemRegistrationService.js'
import { fromCents, toCents } from '../finance/types.js'
import type { FinancialAccountRow, FinancialInvestmentRow, FinancialTransactionRow } from '../finance/types.js'
import type { TransactionsRepository } from '../finance/transactionsRepository.js'
import { parseDate, safeCompare } from '../safe.js'

export interface FinanceRouteDeps {
  config: AppConfig
  items: ItemsRepository
  accounts: AccountsRepository
  transactions: TransactionsRepository
  syncRuns: SyncRunsRepository
  syncService: PluggySyncService
  scheduler: PluggySyncScheduler
  categories: CategoriesRepository
  manualTransactions: ManualTransactionsRepository
  categoryOverrides: CategoryOverridesRepository
  budgets: BudgetsRepository
  products: ProductsRepository
  enrichment: EnrichmentRepository
  clarifications: ClarificationsRepository
  itemRegistration: PluggyItemRegistrationService
}

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7)
}

/** Accepts a date-only string ("2026-08-27") or full ISO datetime; always returns a full ISO instant so lexicographic range comparisons against Pluggy's `date` column (also full ISO) never miss the first/last day of a range. Falls back to "now" when omitted. */
function resolveOccurredAt(input: string | undefined): string | null {
  if (input === undefined || input === null || input === '') return new Date().toISOString()
  const dateOnly = parseDate(input)
  if (!dateOnly) return null
  return new Date(`${dateOnly}T12:00:00.000Z`).toISOString()
}

function serializeCategory(category: FinancialCategoryRow | undefined | null) {
  if (!category) return null
  return { id: category.id, name: category.name, kind: category.kind }
}

function serializeEnrichment(row: EnrichmentRow | undefined) {
  if (!row) return null
  return {
    merchantNormalized: row.merchant_normalized,
    categoryId: row.category_id,
    categoryName: row.category_name,
    canonicalType: row.canonical_type,
    direction: row.direction,
    rawType: row.raw_type,
    paymentMethod: row.payment_method,
    classificationStatus: row.classification_status,
    classificationConfidence: row.classification_confidence,
    classificationSource: row.classification_source,
    notes: row.notes,
    updatedAt: row.updated_at,
  }
}

function serializePluggyTransaction(
  row: FinancialTransactionRow,
  effectiveCategory: FinancialCategoryRow | null,
  enrichment?: EnrichmentRow,
) {
  return {
    id: row.pluggy_transaction_id,
    source: 'pluggy' as const,
    accountId: row.pluggy_account_id,
    description: row.description,
    amount: fromCents(row.amount_cents),
    currencyCode: row.currency_code,
    date: row.date,
    type: row.type,
    status: row.status,
    categoryOriginal: row.category_original,
    category: serializeCategory(effectiveCategory),
    merchant: row.merchant_original,
    enrichment: serializeEnrichment(enrichment),
  }
}

function serializeManualTransaction(
  row: {
    id: string
    amount_cents: number
    direction: ManualDirection
    occurred_at: string
    description: string
    category_id: string | null
    account_id: string | null
    notes: string | null
    reconciliation_status: string
  },
  category: FinancialCategoryRow | undefined | null,
) {
  return {
    id: row.id,
    source: 'manual' as const,
    accountId: row.account_id,
    description: row.description,
    amount: fromCents(row.amount_cents),
    currencyCode: 'BRL',
    date: row.occurred_at,
    type: row.direction === 'income' ? 'CREDIT' : 'DEBIT',
    status: row.reconciliation_status,
    categoryOriginal: null,
    category: serializeCategory(category ?? null),
    merchant: null,
    notes: row.notes,
  }
}

/**
 * Resolves a free-text category name or an explicit categoryId into exactly
 * one category row. Returns a discriminated result instead of throwing so
 * routes can turn "not found"/"ambiguous" into the right HTTP status without
 * a try/catch per call site.
 */
function resolveCategory(
  categories: CategoriesRepository,
  input: { categoryId?: string; category?: string },
): { kind: 'none' } | { kind: 'found'; category: FinancialCategoryRow } | { kind: 'not_found' } | { kind: 'ambiguous'; matches: FinancialCategoryRow[] } {
  if (input.categoryId) {
    const category = categories.getById(input.categoryId)
    return category ? { kind: 'found', category } : { kind: 'not_found' }
  }
  if (input.category) {
    const matches = categories.findByName(input.category)
    if (matches.length === 0) return { kind: 'not_found' }
    if (matches.length > 1) return { kind: 'ambiguous', matches }
    return { kind: 'found', category: matches[0] }
  }
  return { kind: 'none' }
}

function serializeAccountAsset(account: FinancialAccountRow) {
  const canonicalType = resolveAccountCanonicalType(account)
  return {
    id: account.pluggy_account_id,
    itemId: account.pluggy_item_id,
    sourceType: account.type,
    sourceSubtype: account.subtype,
    canonicalType,
    name: account.name,
    marketingName: account.marketing_name,
    currencyCode: account.currency_code,
    balance: fromCents(account.balance_cents),
    numberMasked: account.number_masked,
    creditLimit: fromCents(account.credit_limit_cents),
    availableCreditLimit: fromCents(account.available_credit_limit_cents),
    lastSyncedAt: account.last_synced_at,
    classificationUncertain: Boolean(account.asset_classification_uncertain),
  }
}

function serializeInvestmentAsset(investment: FinancialInvestmentRow) {
  return {
    id: investment.pluggy_investment_id,
    itemId: investment.pluggy_item_id,
    canonicalType: (investment.canonical_type ?? 'INVESTMENT') as CanonicalFinancialAssetType,
    name: investment.name,
    code: investment.code,
    balance: fromCents(investment.balance_cents),
    lastSyncedAt: investment.last_synced_at,
  }
}

function groupItemAssets(
  itemId: string,
  allAccounts: FinancialAccountRow[],
  allInvestments: FinancialInvestmentRow[],
) {
  const itemAccounts = allAccounts.filter(account => account.pluggy_item_id === itemId)
  const itemInvestments = allInvestments.filter(investment => investment.pluggy_item_id === itemId)

  const cashAccounts = itemAccounts.filter(account => CASH_ASSET_TYPES.has(resolveAccountCanonicalType(account)))
  const creditCards = itemAccounts.filter(account => resolveAccountCanonicalType(account) === 'CREDIT_CARD')
  const investmentAccounts = itemAccounts.filter(account => resolveAccountCanonicalType(account) === 'INVESTMENT')
  const otherAccounts = itemAccounts.filter(account => {
    const type = resolveAccountCanonicalType(account)
    return !CASH_ASSET_TYPES.has(type) && type !== 'CREDIT_CARD' && type !== 'INVESTMENT'
  })

  return {
    cashAccounts: cashAccounts.map(serializeAccountAsset),
    creditCards: creditCards.map(serializeAccountAsset),
    investments: [...itemInvestments.map(serializeInvestmentAsset), ...investmentAccounts.map(serializeAccountAsset)],
    other: otherAccounts.map(serializeAccountAsset),
  }
}

function registerItemUserMessage(outcome: string, fallback?: string): string {
  switch (outcome) {
    case 'created':
      return fallback ?? 'Conexão adicionada.'
    case 'already_registered':
      return 'Conexão já cadastrada.'
    case 'invalid_id':
      return 'ID inválido.'
    case 'not_accessible':
      return 'Não foi possível acessar essa conexão.'
    case 'sync_failed':
      return 'Falha temporária ao sincronizar.'
    default:
      return fallback ?? 'Operação concluída.'
  }
}

export function registerFinanceRoutes(app: FastifyInstance, deps: FinanceRouteDeps) {
  const {
    config,
    items,
    accounts,
    transactions,
    syncRuns,
    syncService,
    scheduler,
    categories,
    manualTransactions,
    categoryOverrides,
    budgets,
    products,
    enrichment,
    itemRegistration,
  } = deps

  // Everything under /api/finance/* requires the Cognitive service credential.
  // Encapsulated child scope so this preHandler never leaks onto /health,
  // /api/pluggy/*, or /api/webhooks/pluggy (each has its own auth model).
  void app.register(async financeApp => {
    financeApp.addHook('preHandler', async (request, reply) => {
      if (!requireFinanceToken(request, config)) {
        return reply
          .code(401)
          .send({ error: 'unauthorized', message: 'FINANCE_API_TOKEN ausente ou inválido no header Authorization: Bearer <token>.' })
      }
    })

    financeApp.get('/api/finance/status', async () => {
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
        syncIntervalMinutes: resolveSyncIntervalMinutes(config),
      }
    })

    financeApp.get('/api/finance/integrations', async () => {
      const allItems = items.listAll()
      const allAccounts = accounts.listAll()
      const allInvestments = products.listAllInvestments()
      const latestRun = syncRuns.getLatest()
      return {
        items: allItems.map(item => ({
          id: item.pluggy_item_id,
          idMasked: itemRegistration.maskItemId(item.pluggy_item_id),
          connectorId: item.connector_id,
          connectorName: item.connector_name,
          status: item.status,
          executionStatus: item.execution_status,
          lastSyncedAt: item.last_synced_at,
          lastSuccessfulUpdate: item.last_successful_update,
          errorSummary: item.error_summary,
          groups: groupItemAssets(item.pluggy_item_id, allAccounts, allInvestments),
        })),
        sync: {
          enabled: config.PLUGGY_SYNC_ENABLED,
          intervalMinutes: resolveSyncIntervalMinutes(config),
          nextRunAt: scheduler.getNextRunAt(),
          latestRun: latestRun ?? null,
        },
      }
    })

    financeApp.post('/api/finance/integrations/add-existing', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>
      const itemId = typeof body.itemId === 'string' ? body.itemId.trim() : ''
      if (!itemId) {
        return reply.code(400).send({ error: 'invalid_item_id', message: 'Informe o ID da conexão Pluggy.' })
      }

      const result = await itemRegistration.registerItem(itemId)
      const message = registerItemUserMessage(result.outcome, result.message)

      if (result.outcome === 'invalid_id') {
        return reply.code(400).send({ error: 'invalid_item_id', message })
      }
      if (result.outcome === 'not_accessible') {
        return reply.code(404).send({ error: 'item_not_accessible', message })
      }
      if (result.outcome === 'already_registered') {
        return reply.code(409).send({
          error: 'item_already_registered',
          message,
          connectorName: result.connectorName,
        })
      }

      const statusCode = result.outcome === 'sync_failed' ? 502 : 201
      return reply.code(statusCode).send({
        success: result.outcome === 'created',
        outcome: result.outcome,
        message,
        connectorName: result.connectorName,
        syncStatus: result.syncStatus ?? null,
      })
    })

    financeApp.get('/api/finance/accounts', async () => {
      return {
        accounts: accounts.listAll().map(serializeAccountAsset),
      }
    })

    // finance.transactions.read — merges Pluggy history with manual entries
    // (source tags each row) so "extrato"/"quanto gastei" reflect everything,
    // not just what the bank reported. `category` accepts either an internal
    // categoryId or free text resolved via CategoriesRepository.findByName.
    financeApp.get('/api/finance/transactions', async (request, reply) => {
      const query = request.query as Record<string, string | undefined>

      let effectiveCategoryId: string | undefined
      if (query.category || query.categoryId) {
        const resolved = resolveCategory(categories, { categoryId: query.categoryId, category: query.category })
        if (resolved.kind === 'not_found') return reply.code(404).send({ error: 'category_not_found' })
        if (resolved.kind === 'ambiguous') {
          return reply.code(409).send({
            error: 'category_ambiguous',
            message: 'Mais de uma categoria bate com esse nome. Escolha uma pelo id.',
            matches: resolved.matches.map(serializeCategory),
          })
        }
        if (resolved.kind === 'found') effectiveCategoryId = resolved.category.id
      }

      const limit = query.limit ? Number(query.limit) : undefined
      const offset = query.offset ? Number(query.offset) : undefined

      const pluggyRows = effectiveCategoryId
        ? transactions.listByEffectiveCategory(effectiveCategoryId, { startDate: query.startDate, endDate: query.endDate, limit, offset })
        : transactions.list({
            accountId: query.account,
            startDate: query.startDate,
            endDate: query.endDate,
            category: query.categoryOriginal,
            minAmountCents: query.minAmount ? Math.round(Number(query.minAmount) * 100) : undefined,
            maxAmountCents: query.maxAmount ? Math.round(Number(query.maxAmount) * 100) : undefined,
            search: query.search,
            limit,
            offset,
          })

      const manualRows = manualTransactions.list({
        startDate: query.startDate ? resolveOccurredAt(query.startDate) ?? undefined : undefined,
        endDate: query.endDate ? resolveOccurredAt(query.endDate) ?? undefined : undefined,
        categoryId: effectiveCategoryId,
        search: query.search,
        limit,
        offset,
      })

      const categoryCache = new Map<string, FinancialCategoryRow | null>()
      const lookupCategory = (id: string | null) => {
        if (!id) return null
        if (!categoryCache.has(id)) categoryCache.set(id, categories.getById(id) ?? null)
        return categoryCache.get(id) ?? null
      }

      const combined = [
        ...pluggyRows.map(row => {
          const override = categoryOverrides.get(row.pluggy_transaction_id)
          const effective = override
            ? lookupCategory(override.category_id)
            : row.category_original
              ? categories.findByName(row.category_original)[0] ?? null
              : null
          return serializePluggyTransaction(
            row,
            effective,
            enrichment.getByTransactionId(row.pluggy_transaction_id),
          )
        }),
        ...manualRows.map(row => serializeManualTransaction(row, lookupCategory(row.category_id))),
      ].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))

      return { transactions: combined }
    })

    // finance.summary.read — total income/expense/balance for a month
    // (default: current month), optionally scoped to one category. Pluggy +
    // manual are summed together so this is the same total a controle SQL
    // query over both tables would produce.
    financeApp.get('/api/finance/summary', async (request, reply) => {
      const query = request.query as Record<string, string | undefined>
      const month = query.month || currentMonth()
      try {
        assertValidMonth(month)
      } catch {
        return reply.code(400).send({ error: 'invalid_month', message: 'month deve ser YYYY-MM.' })
      }
      const { start: monthStart, end: monthEnd } = monthRange(month)

      let categoryId: string | undefined
      if (query.category || query.categoryId) {
        const resolved = resolveCategory(categories, { categoryId: query.categoryId, category: query.category })
        if (resolved.kind === 'not_found') return reply.code(404).send({ error: 'category_not_found' })
        if (resolved.kind === 'ambiguous') {
          return reply.code(409).send({ error: 'category_ambiguous', matches: resolved.matches.map(serializeCategory) })
        }
        if (resolved.kind === 'found') categoryId = resolved.category.id
      }

      const pluggySum = categoryId
        ? transactions.sumByEffectiveCategoryAndDateRange(categoryId, monthStart, monthEnd)
        : transactions.sumByDateRange(monthStart, monthEnd)
      const manualSum = manualTransactions.sumByDateRange(monthStart, monthEnd, categoryId)

      const income = pluggySum.income + manualSum.income
      const expense = pluggySum.expense + manualSum.expense

      const allAccounts = accounts.listAll()
      const allInvestments = products.listAllInvestments()
      const aggregation = aggregateFinancialAssets(allAccounts, allInvestments)

      const latestRun = syncRuns.getLatest()

      return {
        month,
        category: categoryId ? serializeCategory(categories.getById(categoryId)) : null,
        totalBalance: fromCents(aggregation.cashBalanceCents),
        cashBalance: fromCents(aggregation.cashBalanceCents),
        investmentBalance: fromCents(aggregation.investmentValueCents),
        financialWealth: fromCents(aggregation.financialWealthCents),
        monthIncome: fromCents(income),
        monthExpense: fromCents(expense),
        monthResult: fromCents(income - expense),
        openCardBalance: fromCents(aggregation.creditCardInvoiceCents),
        creditCardLimitTotal: fromCents(aggregation.creditCardLimitCents),
        lastSync: latestRun?.started_at ?? null,
      }
    })

    // finance.bills.read — upcoming credit-card bills. Empty result is a
    // valid answer (no bills synced yet / connector without card products),
    // never an error; the specialist phrases that as "não achei faturas".
    financeApp.get('/api/finance/bills', async request => {
      const query = request.query as Record<string, string | undefined>
      const fromDate = query.fromDate ? resolveOccurredAt(query.fromDate) ?? undefined : new Date().toISOString()
      const bills = products.listUpcoming(fromDate, query.limit ? Number(query.limit) : undefined)
      return {
        bills: bills.map(bill => ({
          id: bill.pluggy_bill_id,
          accountId: bill.pluggy_account_id,
          dueDate: bill.due_date,
          closingDate: bill.bill_closing_date,
          totalAmount: fromCents(bill.total_amount_cents),
          minimumPayment: fromCents(bill.minimum_payment_cents),
          currencyCode: bill.currency_code,
        })),
      }
    })

    financeApp.get('/api/finance/sync/status', async () => {
      const latest = syncRuns.getLatest()
      const latestMetadata = latest?.metadata ? JSON.parse(latest.metadata) : null
      return {
        latest,
        recent: syncRuns.listRecent(10),
        nextSync: scheduler.getNextRunAt(),
        syncEnabled: config.PLUGGY_SYNC_ENABLED,
        syncIntervalMinutes: resolveSyncIntervalMinutes(config),
        metrics: latest
          ? {
              transactionsSeen: latestMetadata?.transactionsSeen ?? null,
              transactionsCreated: latest.transactions_created,
              transactionsUpdated: latest.transactions_updated,
              transactionsUnchanged: latestMetadata?.transactionsUnchanged ?? null,
            }
          : null,
      }
    })

    financeApp.post('/api/finance/sync', async (_request, reply) => {
      const startedAt = Date.now()
      try {
        const run = await syncService.syncAll('manual')
        const metadata = run.metadata ? JSON.parse(run.metadata) : {}
        return reply.send({
          success: run.status !== 'failed',
          status: run.status,
          items: run.items_processed,
          accounts: run.accounts_processed,
          transactionsSeen: metadata.transactionsSeen ?? null,
          transactionsCreated: run.transactions_created,
          transactionsUpdated: run.transactions_updated,
          transactionsUnchanged: metadata.transactionsUnchanged ?? null,
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

    // finance.manual.create — ALLOW by design (doc 00 §8): explicit manual
    // entries never require confirmation, but the response always echoes back
    // exactly what was saved so the specialist can confirm it in text.
    financeApp.post('/api/finance/transactions/manual', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>
      const amount = Number(body.amount)
      const direction = body.direction as ManualDirection | undefined
      const description = typeof body.description === 'string' ? body.description.trim() : ''

      if (!Number.isFinite(amount) || amount <= 0) return reply.code(400).send({ error: 'invalid_amount', message: 'amount deve ser um número positivo.' })
      if (direction !== 'income' && direction !== 'expense') return reply.code(400).send({ error: 'invalid_direction', message: 'direction deve ser "income" ou "expense".' })
      if (!description) return reply.code(400).send({ error: 'invalid_description', message: 'description é obrigatória.' })

      const occurredAt = resolveOccurredAt(typeof body.date === 'string' ? body.date : undefined)
      if (!occurredAt) return reply.code(400).send({ error: 'invalid_date' })

      let categoryId: string | null = null
      if (body.categoryId || body.category) {
        const resolved = resolveCategory(categories, {
          categoryId: typeof body.categoryId === 'string' ? body.categoryId : undefined,
          category: typeof body.category === 'string' ? body.category : undefined,
        })
        if (resolved.kind === 'not_found') return reply.code(404).send({ error: 'category_not_found' })
        if (resolved.kind === 'ambiguous') {
          return reply.code(409).send({ error: 'category_ambiguous', matches: resolved.matches.map(serializeCategory) })
        }
        if (resolved.kind === 'found') categoryId = resolved.category.id
      }

      const row = manualTransactions.create({
        amountCents: toCents(amount),
        direction,
        occurredAt,
        description,
        categoryId,
        accountId: typeof body.accountId === 'string' ? body.accountId : null,
        notes: typeof body.notes === 'string' ? body.notes : null,
      })

      const category = categoryId ? categories.getById(categoryId) : null
      return reply.code(201).send({
        transaction: serializeManualTransaction(row, category),
        message: `Registrado: R$ ${amount.toFixed(2).replace('.', ',')} (${direction === 'expense' ? 'despesa' : 'receita'})${category ? ` em ${category.name}` : ''} em ${occurredAt.slice(0, 10)}.`,
      })
    })

    // Deleting a manual entry is CONFIRM-gated (doc 00 §8): the caller must
    // send an explicit {confirm:true}, otherwise this is a no-op 400 — used
    // by DELETE_GUARD and to safely remove the E2E test entry afterwards.
    // Soft delete only (deleted_at), never a hard DELETE FROM.
    financeApp.delete('/api/finance/transactions/manual/:id', async (request, reply) => {
      const { id } = request.params as { id: string }
      const body = (request.body ?? {}) as Record<string, unknown>
      if (body.confirm !== true) {
        return reply.code(400).send({ error: 'confirmation_required', message: 'Envie {"confirm": true} para excluir. Sem confirmação, nada é alterado.' })
      }
      const existing = manualTransactions.getById(id)
      if (!existing || existing.deleted_at) return reply.code(404).send({ error: 'transaction_not_found' })
      manualTransactions.softDelete(id)
      return reply.send({ deleted: true, id })
    })

    // finance.category.update — reclassifies one transaction (Pluggy override
    // or manual entry). Either pass {transactionId, source} for a known row,
    // or {description, amount?, startDate?, endDate?} to resolve by search:
    // 0 matches -> 404, 1 -> applies, 2+ -> 409 with a short numbered list and
    // NOTHING is changed (doc 00 §7.1 — never guess).
    financeApp.patch('/api/finance/transactions/category', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>

      const categoryResolution = resolveCategory(categories, {
        categoryId: typeof body.categoryId === 'string' ? body.categoryId : undefined,
        category: typeof body.category === 'string' ? body.category : undefined,
      })
      if (categoryResolution.kind === 'none') return reply.code(400).send({ error: 'category_required' })
      if (categoryResolution.kind === 'not_found') return reply.code(404).send({ error: 'category_not_found' })
      if (categoryResolution.kind === 'ambiguous') {
        return reply.code(409).send({ error: 'category_ambiguous', matches: categoryResolution.matches.map(serializeCategory) })
      }
      const targetCategory = categoryResolution.category

      const explicitId = typeof body.transactionId === 'string' ? body.transactionId : undefined
      const explicitSource = body.source === 'pluggy' || body.source === 'manual' ? body.source : undefined

      if (explicitId && explicitSource === 'manual') {
        const existing = manualTransactions.getById(explicitId)
        if (!existing) return reply.code(404).send({ error: 'transaction_not_found' })
        const updated = manualTransactions.updateCategory(explicitId, targetCategory.id)!
        return reply.send({ updated: serializeManualTransaction(updated, targetCategory), category: serializeCategory(targetCategory) })
      }
      if (explicitId && explicitSource === 'pluggy') {
        const existing = transactions.getByPluggyId(explicitId)
        if (!existing) return reply.code(404).send({ error: 'transaction_not_found' })
        categoryOverrides.set(explicitId, targetCategory.id, existing.category_original)
        return reply.send({ updated: serializePluggyTransaction(existing, targetCategory, enrichment.getByTransactionId(explicitId)), category: serializeCategory(targetCategory) })
      }

      // No explicit id: resolve by free-text search across both sources.
      const description = typeof body.description === 'string' ? body.description : undefined
      const amount = body.amount !== undefined ? Number(body.amount) : undefined
      const amountCents = amount !== undefined && Number.isFinite(amount) ? Math.round(amount * 100) : undefined
      const startDate = typeof body.startDate === 'string' ? body.startDate : undefined
      const endDate = typeof body.endDate === 'string' ? body.endDate : undefined

      if (!description && amountCents === undefined) {
        return reply.code(400).send({ error: 'search_criteria_required', message: 'Informe transactionId+source, ou description/amount para localizar a transação.' })
      }

      const pluggyCandidates = transactions
        .list({ search: description, startDate, endDate, limit: 10 })
        .filter(row => amountCents === undefined || Math.abs(row.amount_cents) === amountCents)
        .map(row => ({ source: 'pluggy' as const, id: row.pluggy_transaction_id, description: row.description, amount: fromCents(row.amount_cents), date: row.date }))

      const manualCandidates = manualTransactions
        .list({ search: description, startDate, endDate, limit: 10 })
        .filter(row => amountCents === undefined || row.amount_cents === amountCents)
        .map(row => ({ source: 'manual' as const, id: row.id, description: row.description, amount: fromCents(row.amount_cents), date: row.occurred_at }))

      const candidates = [...pluggyCandidates, ...manualCandidates]

      if (candidates.length === 0) return reply.code(404).send({ error: 'transaction_not_found' })
      if (candidates.length > 1) {
        return reply.code(409).send({
          error: 'transaction_ambiguous',
          message: 'Mais de uma transação bate com essa busca. Escolha uma pelo id antes de reclassificar.',
          matches: candidates,
        })
      }

      const [match] = candidates
      if (match.source === 'manual') {
        const updated = manualTransactions.updateCategory(match.id, targetCategory.id)!
        return reply.send({ updated: serializeManualTransaction(updated, targetCategory), category: serializeCategory(targetCategory) })
      }
      const existing = transactions.getByPluggyId(match.id)!
      categoryOverrides.set(match.id, targetCategory.id, existing.category_original)
      return reply.send({ updated: serializePluggyTransaction(existing, targetCategory, enrichment.getByTransactionId(match.id)), category: serializeCategory(targetCategory) })
    })

    // finance.budget.read
    financeApp.get('/api/finance/budgets', async (request, reply) => {
      const query = request.query as Record<string, string | undefined>
      const month = query.month || currentMonth()
      try {
        assertValidMonth(month)
      } catch {
        return reply.code(400).send({ error: 'invalid_month', message: 'month deve ser YYYY-MM.' })
      }
      const rows = budgets.listForMonth(month)
      return { month, budgets: rows.map(row => serializeBudget(row, categories)) }
    })

    // finance.budget.write — ALLOW by design (doc 00 §8): creating/editing a
    // budget the user explicitly asked for never requires confirmation.
    financeApp.post('/api/finance/budgets', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>
      const month = typeof body.month === 'string' ? body.month : undefined
      const limitAmount = Number(body.limitAmount)

      if (!month) return reply.code(400).send({ error: 'invalid_month', message: 'month (YYYY-MM) é obrigatório.' })
      try {
        assertValidMonth(month)
      } catch {
        return reply.code(400).send({ error: 'invalid_month', message: 'month deve ser YYYY-MM.' })
      }
      if (!Number.isFinite(limitAmount) || limitAmount < 0) return reply.code(400).send({ error: 'invalid_limit_amount' })

      let categoryId: string | null = null
      if (body.categoryId || body.category) {
        const resolved = resolveCategory(categories, {
          categoryId: typeof body.categoryId === 'string' ? body.categoryId : undefined,
          category: typeof body.category === 'string' ? body.category : undefined,
        })
        if (resolved.kind === 'not_found') return reply.code(404).send({ error: 'category_not_found' })
        if (resolved.kind === 'ambiguous') {
          return reply.code(409).send({ error: 'category_ambiguous', matches: resolved.matches.map(serializeCategory) })
        }
        if (resolved.kind === 'found') categoryId = resolved.category.id
      }

      const budget = budgets.upsert(month, categoryId, toCents(limitAmount))
      return reply.code(201).send({ budget: serializeBudget(budget, categories) })
    })
  })
}

function serializeBudget(budget: BudgetWithStatus, categories: CategoriesRepository) {
  const category = budget.categoryId ? categories.getById(budget.categoryId) : null
  return {
    id: budget.id,
    month: budget.month,
    category: serializeCategory(category),
    limitAmount: fromCents(budget.limitAmountCents),
    spentAmount: fromCents(budget.spentCents),
    remainingAmount: fromCents(budget.remainingCents),
    status: budget.status,
  }
}
