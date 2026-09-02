import Fastify, { type FastifyInstance } from 'fastify'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { AppConfig } from '../config.js'
import { AccountsRepository } from '../finance/accountsRepository.js'
import { ClarificationsRepository } from '../finance/clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from '../finance/db.js'
import { ItemsRepository } from '../finance/itemsRepository.js'
import { TransactionsRepository } from '../finance/transactionsRepository.js'
import { registerFinanceClarificationRoutes } from './financeClarificationRoutes.js'

const AUTH = { authorization: 'Bearer test-finance-token' }

let db: FinanceDb
let app: FastifyInstance
let clarifications: ClarificationsRepository
let transactions: TransactionsRepository

beforeEach(async () => {
  db = openFinanceDb(':memory:')
  clarifications = new ClarificationsRepository(db)
  transactions = new TransactionsRepository(db)

  new ItemsRepository(db).upsertItem({ pluggyItemId: 'item-1', status: 'UPDATED' })
  new AccountsRepository(db).upsertAccount({ pluggyAccountId: 'acc-1', pluggyItemId: 'item-1', type: 'BANK', balanceCents: 0 })
  transactions.upsertTransaction({
    pluggyTransactionId: 'tx-1',
    pluggyAccountId: 'acc-1',
    amountCents: -1000,
    date: '2026-08-01T12:00:00.000Z',
    description: 'Compra desconhecida',
  })

  app = Fastify({ logger: false })
  registerFinanceClarificationRoutes(app, {
    config: { FINANCE_API_TOKEN: 'test-finance-token' } as AppConfig,
    clarifications,
  })
  await app.ready()
})

afterEach(async () => {
  await app.close()
  db.close()
})

describe('registerFinanceClarificationRoutes — autenticação (fail-closed)', () => {
  it('recusa sem token', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/finance/clarifications' })
    expect(res.statusCode).toBe(401)
    expect(res.json()).toMatchObject({ error: 'unauthorized' })
  })

  it('recusa token inválido', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/finance/clarifications',
      headers: { authorization: 'Bearer errado' },
    })
    expect(res.statusCode).toBe(401)
  })

  it('nega quando FINANCE_API_TOKEN não está configurado, mesmo com header presente', async () => {
    const noTokenApp = Fastify({ logger: false })
    registerFinanceClarificationRoutes(noTokenApp, {
      config: { FINANCE_API_TOKEN: undefined } as AppConfig,
      clarifications,
    })
    await noTokenApp.ready()
    const res = await noTokenApp.inject({
      method: 'GET',
      url: '/api/finance/clarifications',
      headers: { authorization: 'Bearer anything' },
    })
    expect(res.statusCode).toBe(401)
    await noTokenApp.close()
  })
})

describe('registerFinanceClarificationRoutes — GET list', () => {
  it('lista e conta dinamicamente, sem número fixo', async () => {
    clarifications.getOrCreateOpen({ pluggyTransactionId: 'tx-1', questionType: 'category', questionText: 'Qual categoria?' })

    const res = await app.inject({ method: 'GET', url: '/api/finance/clarifications', headers: AUTH })
    expect(res.statusCode).toBe(200)
    const body = res.json()
    expect(body.total).toBe(body.clarifications.length)
    expect(body.clarifications[0].transactionId).toBe('tx-1')
  })

  it('rejeita status inválido', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/finance/clarifications?status=bogus',
      headers: AUTH,
    })
    expect(res.statusCode).toBe(400)
  })

  it('status omitido → default open (contrato HTTP)', async () => {
    const { row: openRow } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'open',
    })
    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-2',
      pluggyAccountId: 'acc-1',
      amountCents: -500,
      date: '2026-08-02T12:00:00.000Z',
      description: 'outra',
    })
    const { row: resolvedRow } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-2',
      questionType: 'category',
      questionText: 'resolved',
    })
    clarifications.resolve(resolvedRow.id, {
      replyMessageId: 'r1',
      resolvedBy: 'owner',
      resolution: 'x',
    })

    const res = await app.inject({ method: 'GET', url: '/api/finance/clarifications', headers: AUTH })
    expect(res.statusCode).toBe(200)
    const ids = res.json().clarifications.map((c: { id: string }) => c.id)
    expect(ids).toContain(openRow.id)
    expect(ids).not.toContain(resolvedRow.id)
  })

  it('deliveryMessageId + status=any + limit=1 → exact A (HTTP)', async () => {
    const { row: a } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'A',
    })
    await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${a.id}/delivery`,
      headers: AUTH,
      payload: { deliveryMessageId: 'deliv-A' },
    })
    db.prepare('UPDATE finance_clarifications SET created_at = ? WHERE id = ?').run(
      '2026-08-01T10:00:00.000Z',
      a.id,
    )

    transactions.upsertTransaction({
      pluggyTransactionId: 'tx-B',
      pluggyAccountId: 'acc-1',
      amountCents: -200,
      date: '2026-08-03T12:00:00.000Z',
      description: 'B',
    })
    const { row: b } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-B',
      questionType: 'category',
      questionText: 'B newer',
    })
    await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${b.id}/delivery`,
      headers: AUTH,
      payload: { deliveryMessageId: 'deliv-B' },
    })
    db.prepare('UPDATE finance_clarifications SET created_at = ? WHERE id = ?').run(
      '2026-08-02T10:00:00.000Z',
      b.id,
    )

    // Resolve A — late-reply path must still find it via status=any.
    await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${a.id}/resolve`,
      headers: AUTH,
      payload: { replyMessageId: 'reply-a', resolution: 'Mercado' },
    })

    const anyRes = await app.inject({
      method: 'GET',
      url: '/api/finance/clarifications?deliveryMessageId=deliv-A&status=any&limit=1',
      headers: AUTH,
    })
    expect(anyRes.statusCode).toBe(200)
    expect(anyRes.json().clarifications).toHaveLength(1)
    expect(anyRes.json().clarifications[0].id).toBe(a.id)
    expect(anyRes.json().clarifications[0].status).toBe('resolved')
    expect(anyRes.json().total).toBe(1)

    const openMiss = await app.inject({
      method: 'GET',
      url: '/api/finance/clarifications?deliveryMessageId=deliv-A&status=open&limit=1',
      headers: AUTH,
    })
    expect(openMiss.json().clarifications).toHaveLength(0)

    const resolvedHit = await app.inject({
      method: 'GET',
      url: '/api/finance/clarifications?deliveryMessageId=deliv-A&status=resolved&limit=1',
      headers: AUTH,
    })
    expect(resolvedHit.json().clarifications[0].id).toBe(a.id)
  })
})

describe('registerFinanceClarificationRoutes — delivery/resolve, path param não se repete no corpo', () => {
  it('POST .../delivery liga deliveryMessageId a source_message_id via path param', async () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Qual categoria?',
    })

    const res = await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${row.id}/delivery`,
      headers: AUTH,
      payload: { deliveryMessageId: 'wa-msg-1', deliveryChatId: 'chat-1' },
    })
    expect(res.statusCode).toBe(200)
    expect(res.json().clarification.deliveryMessageId).toBe('wa-msg-1')

    // clarificationId is never expected in the body — only in the path.
    const persisted = clarifications.getById(row.id)
    expect(persisted?.source_message_id).toBe('wa-msg-1')
  })

  it('POST .../resolve liga replyMessageId a quoted_message_id via path param', async () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Qual categoria?',
    })

    const res = await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${row.id}/resolve`,
      headers: AUTH,
      payload: { replyMessageId: 'wa-reply-1', resolution: 'Mercado' },
    })
    expect(res.statusCode).toBe(200)
    const body = res.json()
    expect(body.clarification.replyMessageId).toBe('wa-reply-1')
    expect(body.clarification.status).toBe('resolved')
    expect(body.alreadyResolved).toBe(false)
  })

  it('POST .../resolve persiste resolution + actorId + replyMessageId (HTTP contract)', async () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Qual categoria?',
    })
    expect(row.resolution).toBeNull()
    expect(row.resolved_by).toBeNull()

    const res = await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${row.id}/resolve`,
      headers: AUTH,
      payload: {
        resolution: 'mercado',
        actorId: 'finance-owner-1',
        replyMessageId: 'reply-1',
      },
    })
    expect(res.statusCode).toBe(200)
    const body = res.json()
    expect(body.alreadyResolved).toBe(false)
    expect(body.clarification.status).toBe('resolved')
    expect(body.clarification.resolution).toBe('mercado')
    expect(body.clarification.resolvedBy).toBe('finance-owner-1')
    expect(body.clarification.replyMessageId).toBe('reply-1')
    expect(body.clarification.resolvedAt).toBeTruthy()

    const persisted = clarifications.getById(row.id)
    expect(persisted?.resolution).toBe('mercado')
    expect(persisted?.resolved_by).toBe('finance-owner-1')
    expect(persisted?.quoted_message_id).toBe('reply-1')
  })

  it('resolve idempotente: segunda chamada não duplica a mutação', async () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Qual categoria?',
    })
    await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${row.id}/resolve`,
      headers: AUTH,
      payload: { replyMessageId: 'wa-reply-1', resolution: 'Mercado' },
    })
    const second = await app.inject({
      method: 'POST',
      url: `/api/finance/clarifications/${row.id}/resolve`,
      headers: AUTH,
      payload: { replyMessageId: 'wa-reply-2', resolution: 'Restaurante' },
    })
    expect(second.statusCode).toBe(200)
    expect(second.json().alreadyResolved).toBe(true)
    expect(second.json().clarification.resolution).toBe('Mercado') // unchanged
  })

  it('404 para clarificationId desconhecido', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/finance/clarifications/does-not-exist/delivery',
      headers: AUTH,
      payload: { deliveryMessageId: 'wa-msg-1' },
    })
    expect(res.statusCode).toBe(404)
  })
})
