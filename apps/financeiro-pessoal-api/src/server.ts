import cors from '@fastify/cors'
import Fastify, { FastifyRequest } from 'fastify'
import { z } from 'zod'

import { AppConfig, getConfigStatus, loadConfig, resolveSyncIntervalMinutes } from './config.js'
import { AccountsRepository } from './finance/accountsRepository.js'
import { BudgetsRepository } from './finance/budgetsRepository.js'
import { CategoriesRepository } from './finance/categoriesRepository.js'
import { CategoryOverridesRepository } from './finance/categoryOverridesRepository.js'
import { ClarificationsRepository } from './finance/clarificationsRepository.js'
import { ClassificationService } from './finance/classificationService.js'
import { openFinanceDb, type FinanceDb } from './finance/db.js'
import { EnrichmentRepository } from './finance/enrichmentRepository.js'
import { ItemsRepository } from './finance/itemsRepository.js'
import { ManualTransactionsRepository } from './finance/manualTransactionsRepository.js'
import { PluggySyncService } from './finance/pluggySyncService.js'
import { ProductsRepository } from './finance/productsRepository.js'
import { PluggySyncScheduler } from './finance/scheduler.js'
import { SyncRunsRepository, SyncAlreadyRunningError } from './finance/syncRunsRepository.js'
import { TransactionsRepository } from './finance/transactionsRepository.js'
import { MissingPluggySecretsError, PluggyPort, PluggySyncClient, SdkPluggyPort } from './pluggy.js'
import { registerFinanceRoutes } from './routes/finance.js'
import { maskSensitive, parseDate, safeCompare } from './safe.js'
import { JsonPocStore } from './store.js'

const itemSchema = z.object({ itemId: z.string().min(4).max(160) })
const webhookSchema = z
  .object({
    eventId: z.string().min(1).optional(),
    id: z.string().min(1).optional(),
    event: z.string().min(1),
    itemId: z.string().optional(),
    item: z.object({ id: z.string().optional() }).passthrough().optional(),
    data: z.unknown().optional(),
    createdTransactionsLink: z.string().optional(),
    transactionIds: z.array(z.string()).optional(),
    transactions: z.array(z.object({ id: z.string() }).passthrough()).optional(),
  })
  .passthrough()
  .transform((payload, context) => {
    const eventId = payload.eventId || payload.id
    if (!eventId) {
      context.addIssue({ code: 'custom', message: 'eventId is required' })
      return z.NEVER
    }

    return {
      ...payload,
      eventId,
      itemId: payload.itemId || payload.item?.id,
    }
  })

function getHeader(request: FastifyRequest, name: string) {
  const value = request.headers[name.toLowerCase()]
  if (Array.isArray(value)) return value[0] || ''
  return value || ''
}

function requireHttpsIfPublished(request: FastifyRequest, config: AppConfig) {
  if (!config.PUBLIC_BASE_URL) return true
  if (!config.PUBLIC_BASE_URL.startsWith('https://')) return false
  const proto = getHeader(request, 'x-forwarded-proto')
  return proto === '' || proto === 'https'
}

function extractDeletedTransactionIds(payload: z.infer<typeof webhookSchema>) {
  const explicit = payload.transactionIds || []
  const fromTransactions = (payload.transactions || []).map(transaction => transaction.id)
  const data = payload.data as { transactionIds?: string[]; transactions?: Array<{ id: string }> } | undefined
  return [...new Set([...explicit, ...fromTransactions, ...(data?.transactionIds || []), ...(data?.transactions || []).map((transaction: { id: string }) => transaction.id)])]
}

export interface CreateAppOptions {
  config?: AppConfig
  store?: JsonPocStore
  pluggy?: PluggyPort
  /** Granular Pluggy surface used by the sync service. Defaults to the same centralized SdkPluggyPort instance as `pluggy`. */
  pluggySync?: PluggySyncClient
  /** Injectable SQLite connection for tests (e.g. openFinanceDb(':memory:')). Defaults to config.FINANCE_DB_PATH. */
  financeDb?: FinanceDb
  /** Skip starting the in-process cron timer (tests never want a background timer running). */
  disableScheduler?: boolean
}

export function createApp(options: CreateAppOptions = {}) {
  const config = options.config || loadConfig()
  const store = options.store || new JsonPocStore(config.PLUGGY_STORE_PATH)

  // Single centralized Pluggy client instance, shared by every route and by the sync service —
  // construction never throws (secrets are only required on first actual call).
  const sdkPluggyPort = new SdkPluggyPort(config)
  const pluggy = options.pluggy || sdkPluggyPort
  const pluggySync = options.pluggySync || sdkPluggyPort

  const financeDb = options.financeDb || openFinanceDb(config.FINANCE_DB_PATH)
  const itemsRepository = new ItemsRepository(financeDb)
  const accountsRepository = new AccountsRepository(financeDb)
  const transactionsRepository = new TransactionsRepository(financeDb)
  const productsRepository = new ProductsRepository(financeDb)
  const syncRunsRepository = new SyncRunsRepository(financeDb)
  const categoriesRepository = new CategoriesRepository(financeDb)
  const manualTransactionsRepository = new ManualTransactionsRepository(financeDb)
  const categoryOverridesRepository = new CategoryOverridesRepository(financeDb)
  const budgetsRepository = new BudgetsRepository(financeDb)
  const enrichmentRepository = new EnrichmentRepository(financeDb)
  const clarificationsRepository = new ClarificationsRepository(financeDb)
  const classificationService = new ClassificationService(
    enrichmentRepository,
    clarificationsRepository,
    categoriesRepository,
    categoryOverridesRepository,
  )

  const app = Fastify({
    logger: {
      redact: ['req.headers.authorization', `req.headers.${config.PLUGGY_WEBHOOK_HEADER}`, '*.accessToken', '*.clientSecret'],
    },
    bodyLimit: 512 * 1024,
  })

  syncRunsRepository.releaseStaleLocks(config.PLUGGY_SYNC_STALE_LOCK_MINUTES * 60 * 1000)

  const syncService = new PluggySyncService({
    pluggy: pluggySync,
    items: itemsRepository,
    accounts: accountsRepository,
    transactions: transactionsRepository,
    products: productsRepository,
    syncRuns: syncRunsRepository,
    safetyWindowHours: config.PLUGGY_SYNC_SAFETY_WINDOW_HOURS,
    maxConcurrentItems: config.PLUGGY_SYNC_MAX_CONCURRENT_ITEMS,
    logger: app.log,
    classification: classificationService,
  })

  const scheduler = new PluggySyncScheduler({
    enabled: config.PLUGGY_SYNC_ENABLED,
    intervalMinutes: resolveSyncIntervalMinutes(config),
    syncService,
    logger: app.log,
  })
  if (!options.disableScheduler) scheduler.start()
  app.addHook('onClose', async () => {
    scheduler.stop()
    if (!options.financeDb) financeDb.close()
  })

  void app.register(cors, { origin: config.CORS_ORIGIN, strictPreflight: false })

  registerFinanceRoutes(app, {
    config,
    items: itemsRepository,
    accounts: accountsRepository,
    transactions: transactionsRepository,
    syncRuns: syncRunsRepository,
    syncService,
    scheduler,
    categories: categoriesRepository,
    manualTransactions: manualTransactionsRepository,
    categoryOverrides: categoryOverridesRepository,
    budgets: budgetsRepository,
    products: productsRepository,
    enrichment: enrichmentRepository,
    clarifications: clarificationsRepository,
  })

  app.get('/health', async () => ({ ok: true, app: 'financeiro-pessoal-api' }))

  app.get('/api/pluggy/config-status', async () => {
    const data = await store.read()
    return {
      ...getConfigStatus(config),
      itemCount: Object.keys(data.items).length,
      webhookEventCount: Object.keys(data.webhookEvents).length,
    }
  })

  app.post('/api/connect-token', async (_request, reply) => {
    try {
      const token = await pluggy.createConnectToken()
      return reply.send({ accessToken: token.accessToken })
    } catch (error) {
      if (error instanceof MissingPluggySecretsError) {
        return reply.code(424).send({ error: 'missing_pluggy_secrets', message: error.message })
      }
      app.log.error({ err: error }, 'connect token failed')
      return reply.code(502).send({ error: 'pluggy_connect_token_failed', message: 'Não foi possível gerar o Connect Token.' })
    }
  })

  // Item discovery: Pluggy has no "list items" endpoint (by design, for security), so
  // this Connect-Widget callback is the only place a new itemId is ever learned.
  app.post('/api/pluggy/items', async (request, reply) => {
    const parsed = itemSchema.safeParse(request.body)
    if (!parsed.success) return reply.code(400).send({ error: 'invalid_item_payload' })
    const { itemId } = parsed.data

    const item = await store.upsertItem(itemId, config.PLUGGY_CLIENT_USER_ID)

    try {
      const pluggyItem = await pluggySync.fetchItem(itemId)
      itemsRepository.upsertItem({
        pluggyItemId: itemId,
        connectorId: pluggyItem.connector?.id ?? null,
        connectorName: pluggyItem.connector?.name ?? null,
        status: pluggyItem.status,
        executionStatus: pluggyItem.executionStatus,
        lastSuccessfulUpdate: pluggyItem.lastUpdatedAt ? new Date(pluggyItem.lastUpdatedAt).toISOString() : null,
        rawMetadata: { connector: pluggyItem.connector, statusDetail: pluggyItem.statusDetail },
      })
    } catch (error) {
      app.log.warn({ err: error, itemId }, 'pluggy: não foi possível enriquecer item com dados do connector no registro; persistindo com dados mínimos')
      itemsRepository.upsertItem({ pluggyItemId: itemId, status: 'CREATED' })
    }

    try {
      await syncService.syncOne(itemId, 'initial')
    } catch (error) {
      if (error instanceof SyncAlreadyRunningError) {
        app.log.warn({ itemId }, 'pluggy: sync imediato pós-connect adiado — outro sync em andamento')
      } else {
        app.log.error({ err: error, itemId }, 'pluggy: sync imediato pós-connect falhou')
      }
    }

    return reply.send({ item })
  })

  app.get('/api/pluggy/snapshot', async (request, reply) => {
    const query = request.query as Record<string, unknown>
    const itemId = typeof query.itemId === 'string' ? query.itemId : undefined
    if (!itemId) return reply.code(400).send({ error: 'missing_item_id' })

    try {
      const snapshot = await pluggy.fetchSnapshot(itemId, {
        dateFrom: parseDate(query.dateFrom),
        dateTo: parseDate(query.dateTo),
      })
      await store.updateItem(itemId, { status: 'snapshot_fetched', lastSyncAt: new Date().toISOString() })
      return reply.send({ snapshot: maskSensitive(snapshot) })
    } catch (error) {
      if (error instanceof MissingPluggySecretsError) {
        return reply.code(424).send({ error: 'missing_pluggy_secrets', message: error.message })
      }
      await store.updateItem(itemId, { status: 'error', error: maskSensitive({ message: error instanceof Error ? error.message : 'Erro desconhecido' }) })
      return reply.code(502).send({ error: 'pluggy_snapshot_failed', message: 'Não foi possível consultar dados na Pluggy.' })
    }
  })

  app.get('/api/pluggy/poc-state', async () => {
    const data = await store.read()
    return maskSensitive({
      ...data,
      config: getConfigStatus(config),
    })
  })

  app.get('/api/webhooks/pluggy', async () => ({ ok: true, endpoint: 'pluggy-webhook', method: 'GET' }))
  app.options('/api/webhooks/pluggy', async (_request, reply) => reply.code(204).send())

  app.post('/api/webhooks/pluggy', async (request, reply) => {
    if (!requireHttpsIfPublished(request, config)) return reply.code(400).send({ error: 'https_required' })

    const contentType = getHeader(request, 'content-type')
    if (!contentType.includes('application/json')) return reply.code(415).send({ error: 'invalid_content_type' })

    if (!config.PLUGGY_WEBHOOK_SECRET) return reply.code(424).send({ error: 'missing_webhook_secret' })

    const receivedSecret = getHeader(request, config.PLUGGY_WEBHOOK_HEADER)
    const isSigned = Boolean(receivedSecret && safeCompare(config.PLUGGY_WEBHOOK_SECRET, receivedSecret))
    const canAcceptUnsigned = !receivedSecret && config.PLUGGY_ALLOW_UNSIGNED_WEBHOOKS
    if (!isSigned && !canAcceptUnsigned) {
      return reply.code(401).send({ error: 'invalid_webhook_secret' })
    }

    const parsed = webhookSchema.safeParse(request.body)
    if (!parsed.success) return reply.code(400).send({ error: 'invalid_webhook_payload' })

    const event = parsed.data
    const record = await store.recordWebhook({
      eventId: event.eventId,
      event: event.event,
      itemId: event.itemId,
      status: 'received',
      receivedAt: new Date().toISOString(),
      rawPayload: maskSensitive({ ...event, signature: isSigned ? 'signed' : 'unsigned-poc' }),
    })

    if (!record.inserted) return reply.code(202).send({ ok: true, duplicate: true, eventId: record.event.eventId })

    void processWebhookEvent(event, store).catch(async error => {
      await store.updateWebhook(event.eventId, {
        status: 'error',
        error: error instanceof Error ? error.message : 'Erro desconhecido',
      })
    })

    return reply.code(202).send({ ok: true, eventId: event.eventId, status: 'received' })
  })

  return app
}

async function processWebhookEvent(event: z.infer<typeof webhookSchema>, store: JsonPocStore) {
  await store.updateWebhook(event.eventId, { status: 'processing' })

  if (event.itemId) {
    const normalizedStatus = normalizeItemStatus(event)
    await store.updateItem(event.itemId, {
      status: normalizedStatus,
      lastSyncAt: ['item/updated', 'item.updated'].includes(event.event) ? new Date().toISOString() : undefined,
      error: event.event.includes('error') ? maskSensitive(event.data || event) : undefined,
    })
  }

  if (['transactions/deleted', 'transactions.deleted'].includes(event.event)) {
    await store.tombstoneTransactions(event.eventId, extractDeletedTransactionIds(event))
  }

  await store.updateWebhook(event.eventId, { status: 'processed', processedAt: new Date().toISOString() })
}

function normalizeItemStatus(event: z.infer<typeof webhookSchema>) {
  const data = event.data as { status?: string; executionStatus?: string } | undefined
  if (event.event.includes('waiting_user_input')) return 'waiting_user_input'
  if (event.event.includes('waiting_user_action')) return 'waiting_user_action'
  if (event.event.includes('error')) return 'error'
  if (event.event.includes('updated')) return data?.status || data?.executionStatus || 'updated'
  if (event.event.includes('created')) return 'created'
  return event.event
}
