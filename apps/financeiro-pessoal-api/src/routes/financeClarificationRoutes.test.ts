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
