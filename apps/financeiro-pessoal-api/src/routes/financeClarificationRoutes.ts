import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import type { ClarificationRow, ClarificationsRepository, ClarificationListStatusFilter } from '../finance/clarificationsRepository.js'
import { safeCompare } from '../safe.js'

/**
 * Clarification delivery + resolution surface (F2B, SUBAGENT_B).
 *
 * Registered as its own encapsulated Fastify scope so it can be wired next to
 * `registerFinanceRoutes` without either module editing the other (PLAN.md route ownership).
 *
 * Path param is the single source of the clarification id — it is never repeated in the body.
 * No request in this module accepts a `mode` field.
 */

export interface FinanceClarificationRouteDeps {
  config: AppConfig
  clarifications: ClarificationsRepository
}

/** HTTP contract statuses from finance.clarification.list.yaml (+ dismissed legacy). */
const QUERY_STATUS_VALUES: readonly ClarificationListStatusFilter[] = [
  'open',
  'resolved',
  'dismissed',
  'any',
  'snoozed',
]

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

function serializeClarification(row: ClarificationRow) {
  return {
    id: row.id,
    transactionId: row.pluggy_transaction_id,
    questionType: row.question_type,
    status: row.status,
    priority: row.priority,
    questionText: row.question_text,
    createdAt: row.created_at,
    resolvedAt: row.resolved_at,
    resolvedBy: row.resolved_by,
    resolution: row.resolution,
    deliveryMessageId: row.source_message_id,
    deliveryChatId: row.delivery_chat_id,
    firstDeliveredAt: row.first_delivered_at,
    lastDeliveredAt: row.last_delivered_at,
    deliveryCount: row.delivery_count,
    replyMessageId: row.quoted_message_id,
    snoozedUntil: row.snoozed_until,
  }
}

export function registerFinanceClarificationRoutes(app: FastifyInstance, deps: FinanceClarificationRouteDeps): void {
  const { config, clarifications } = deps

  void app.register(async clarificationApp => {
    clarificationApp.addHook('preHandler', async (request, reply) => {
      if (!requireFinanceToken(request, config)) {
        return reply.code(401).send({
          error: 'unauthorized',
          message: 'FINANCE_API_TOKEN ausente ou inválido no header Authorization: Bearer <token>.',
        })
      }
    })

    /** Real-time list/count. Never a cached historic number (03 doc §Historical count behavior). */
    clarificationApp.get('/api/finance/clarifications', async (request, reply) => {
      const query = (request.query ?? {}) as Record<string, unknown>

      // Capability contract: "Default do servidor: open." Applied at HTTP boundary only —
      // ClarificationsRepository.list({}) without status stays unfiltered for internal callers.
      let status: ClarificationListStatusFilter = 'open'
      if (typeof query.status === 'string') {
        if (!(QUERY_STATUS_VALUES as readonly string[]).includes(query.status)) {
          return reply.code(400).send({ error: 'invalid_status', message: 'Status não suportado.' })
        }
        status = query.status as ClarificationListStatusFilter
      }

      const filters = {
        status,
        deliveryMessageId:
          typeof query.deliveryMessageId === 'string' ? query.deliveryMessageId : undefined,
        questionType: typeof query.questionType === 'string' ? query.questionType : undefined,
        competenceMonth: typeof query.competenceMonth === 'string' ? query.competenceMonth : undefined,
        pluggyItemId: typeof query.pluggyItemId === 'string' ? query.pluggyItemId : undefined,
        pluggyAccountId: typeof query.pluggyAccountId === 'string' ? query.pluggyAccountId : undefined,
        limit: typeof query.limit === 'string' ? Number(query.limit) : undefined,
        offset: typeof query.offset === 'string' ? Number(query.offset) : undefined,
      }

      return {
        clarifications: clarifications.list(filters).map(serializeClarification),
        total: clarifications.count(filters),
      }
    })

    /**
     * Binds the outbound WhatsApp message to this clarification for exact reply resolution.
     * Path param carries the id; the body never repeats it.
     */
    clarificationApp.post('/api/finance/clarifications/:clarificationId/delivery', async (request, reply) => {
      const { clarificationId } = request.params as { clarificationId: string }
      const body = (request.body ?? {}) as Record<string, unknown>

      if (typeof body.deliveryMessageId !== 'string' || !body.deliveryMessageId.trim()) {
        return reply
          .code(400)
          .send({ error: 'invalid_delivery_message_id', message: 'Informe deliveryMessageId.' })
      }

      const existing = clarifications.getById(clarificationId)
      if (!existing) {
        return reply.code(404).send({ error: 'clarification_not_found', message: 'Clarificação não encontrada.' })
      }
      if (existing.status !== 'open') {
        return reply
          .code(409)
          .send({ error: 'clarification_not_open', message: 'Clarificação não está aberta.' })
      }

      const deliveryChatId = typeof body.deliveryChatId === 'string' ? body.deliveryChatId : null
      const updated = clarifications.recordDelivery(clarificationId, {
        deliveryMessageId: body.deliveryMessageId,
        deliveryChatId,
      })

      return { clarification: serializeClarification(updated!) }
    })

    /**
     * Resolves by explicit clarification id. Late-reply safe: an already-resolved clarification
     * responds 200 with `alreadyResolved: true` instead of mutating a second time.
     */
    clarificationApp.post('/api/finance/clarifications/:clarificationId/resolve', async (request, reply) => {
      const { clarificationId } = request.params as { clarificationId: string }
      const body = (request.body ?? {}) as Record<string, unknown>

      if (typeof body.replyMessageId !== 'string' || !body.replyMessageId.trim()) {
        return reply.code(400).send({ error: 'invalid_reply_message_id', message: 'Informe replyMessageId.' })
      }

      const result = clarifications.resolve(clarificationId, {
        replyMessageId: body.replyMessageId,
        resolvedBy: typeof body.actorId === 'string' ? body.actorId : null,
        resolution: typeof body.resolution === 'string' ? body.resolution : null,
      })

      if (!result) {
        return reply.code(404).send({ error: 'clarification_not_found', message: 'Clarificação não encontrada.' })
      }

      return reply.code(result.alreadyResolved ? 200 : 200).send({
        clarification: serializeClarification(result.row),
        alreadyResolved: result.alreadyResolved,
      })
    })
  })
}
