import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AccountsRepository } from './accountsRepository.js'
import { ClarificationsRepository } from './clarificationsRepository.js'
import { openFinanceDb, type FinanceDb } from './db.js'
import { ItemsRepository } from './itemsRepository.js'
import { TransactionsRepository } from './transactionsRepository.js'

let db: FinanceDb
let clarifications: ClarificationsRepository
let transactions: TransactionsRepository

beforeEach(() => {
  db = openFinanceDb(':memory:')
  clarifications = new ClarificationsRepository(db)
  transactions = new TransactionsRepository(db)
  const items = new ItemsRepository(db)
  const accounts = new AccountsRepository(db)
  items.upsertItem({ pluggyItemId: 'item-1', status: 'CREATED' })
  accounts.upsertAccount({ pluggyAccountId: 'acc-1', pluggyItemId: 'item-1', type: 'BANK', balanceCents: 0 })
  transactions.upsertTransaction({
    pluggyTransactionId: 'tx-1',
    pluggyAccountId: 'acc-1',
    amountCents: 5000,
    date: '2026-08-01T12:00:00.000Z',
    description: 'Compra desconhecida',
  })
  // competence_month is only backfilled by migration 009 for pre-existing rows; a freshly
  // upserted row only gets it via temporal sync (SUBAGENT_A's service) or a correction, neither
  // of which is this test's concern — set it directly so the competence_month filter has data.
  db.prepare('UPDATE financial_transactions SET competence_month = ? WHERE pluggy_transaction_id = ?').run(
    '2026-08',
    'tx-1',
  )
})

afterEach(() => {
  db.close()
})

describe('ClarificationsRepository', () => {
  it('cria OPEN na primeira ambiguidade e deduplica nas próximas', () => {
    const input = { pluggyTransactionId: 'tx-1', questionType: 'category', questionText: 'Como classificar?' }

    const first = clarifications.getOrCreateOpen(input)
    expect(first.created).toBe(true)
    expect(first.row.status).toBe('open')

    const second = clarifications.getOrCreateOpen(input)
    expect(second.created).toBe(false)
    expect(second.row.id).toBe(first.row.id)

    const third = clarifications.getOrCreateOpen(input)
    expect(third.created).toBe(false)
    expect(clarifications.countOpenForTransaction('tx-1')).toBe(1)
  })
})

describe('ClarificationsRepository — entrega e resolução (F2B)', () => {
  it('registra entrega ligando source_message_id à clarificação, uma vez por chamada', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Como classificar?',
    })

    const delivered = clarifications.recordDelivery(row.id, {
      deliveryMessageId: 'wa-msg-1',
      deliveryChatId: 'chat-finance',
    })
    expect(delivered?.source_message_id).toBe('wa-msg-1')
    expect(delivered?.delivery_chat_id).toBe('chat-finance')
    expect(delivered?.first_delivered_at).not.toBeNull()
    expect(delivered?.delivery_count).toBe(1)

    const deliveredAgain = clarifications.recordDelivery(row.id, { deliveryMessageId: 'wa-msg-2' })
    expect(deliveredAgain?.source_message_id).toBe('wa-msg-2')
    expect(deliveredAgain?.first_delivered_at).toBe(delivered?.first_delivered_at) // unchanged
    expect(deliveredAgain?.delivery_count).toBe(2)
  })

  it('resolve por id explícito ligando quoted_message_id à resposta', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Como classificar?',
    })
    clarifications.recordDelivery(row.id, { deliveryMessageId: 'wa-msg-1' })

    const result = clarifications.resolve(row.id, {
      replyMessageId: 'wa-reply-1',
      resolvedBy: 'owner-1',
      resolution: 'Mercado',
    })
    expect(result?.alreadyResolved).toBe(false)
    expect(result?.row.status).toBe('resolved')
    expect(result?.row.quoted_message_id).toBe('wa-reply-1')
    expect(result?.row.resolved_by).toBe('owner-1')
  })

  it('resposta tardia em clarificação já resolvida nunca duplica a mutação', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Como classificar?',
    })
    const firstResolve = clarifications.resolve(row.id, {
      replyMessageId: 'wa-reply-1',
      resolvedBy: 'owner-1',
      resolution: 'Mercado',
    })

    const secondResolve = clarifications.resolve(row.id, {
      replyMessageId: 'wa-reply-2',
      resolvedBy: 'owner-1',
      resolution: 'Restaurante',
    })

    expect(secondResolve?.alreadyResolved).toBe(true)
    // Nothing changed: resolution/quoted_message_id from the FIRST resolve still stand.
    expect(secondResolve?.row).toEqual(firstResolve?.row)
  })

  it('snooze mantém aberto mas evita reentrega imediata; delivery limpa o snooze', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Como classificar?',
    })
    const snoozed = clarifications.snooze(row.id, '2099-01-01T00:00:00.000Z')
    expect(snoozed?.status).toBe('open')
    expect(snoozed?.snoozed_until).toBe('2099-01-01T00:00:00.000Z')

    const delivered = clarifications.recordDelivery(row.id, { deliveryMessageId: 'wa-msg-1' })
    expect(delivered?.snoozed_until).toBeNull()
  })

  it('list/count filtram por status e mês de competência, sempre derivados ao vivo', () => {
    clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'Como classificar?',
    })
    expect(clarifications.count({ status: 'open' })).toBe(1)
    expect(clarifications.list({ status: 'open', competenceMonth: '2026-08' })).toHaveLength(1)
    expect(clarifications.list({ status: 'open', competenceMonth: '2099-01' })).toHaveLength(0)
    expect(clarifications.count({ status: 'resolved' })).toBe(0)
  })
})

describe('ClarificationsRepository — durable list filters (F2B contract)', () => {
  function seedTx(pluggyTransactionId: string, competenceMonth = '2026-08') {
    transactions.upsertTransaction({
      pluggyTransactionId,
      pluggyAccountId: 'acc-1',
      amountCents: 1000,
      date: '2026-08-02T12:00:00.000Z',
      description: pluggyTransactionId,
    })
    db.prepare('UPDATE financial_transactions SET competence_month = ? WHERE pluggy_transaction_id = ?').run(
      competenceMonth,
      pluggyTransactionId,
    )
  }

  function forceCreatedAt(id: string, iso: string) {
    db.prepare('UPDATE finance_clarifications SET created_at = ? WHERE id = ?').run(iso, id)
  }

  it('status matrix: open/resolved/any hit-miss + unknown delivery miss', () => {
    const { row: openRow } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'open?',
    })
    clarifications.recordDelivery(openRow.id, { deliveryMessageId: 'deliv-open' })

    seedTx('tx-resolved')
    const { row: resolvedRow } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-resolved',
      questionType: 'category',
      questionText: 'resolved?',
    })
    clarifications.recordDelivery(resolvedRow.id, { deliveryMessageId: 'deliv-resolved' })
    clarifications.resolve(resolvedRow.id, {
      replyMessageId: 'reply-1',
      resolvedBy: 'owner',
      resolution: 'Mercado',
    })

    expect(clarifications.list({ deliveryMessageId: 'deliv-open', status: 'open', limit: 1 })).toHaveLength(1)
    expect(clarifications.list({ deliveryMessageId: 'deliv-resolved', status: 'resolved', limit: 1 })).toHaveLength(1)
    expect(clarifications.list({ deliveryMessageId: 'deliv-open', status: 'resolved', limit: 1 })).toHaveLength(0)
    expect(clarifications.list({ deliveryMessageId: 'deliv-resolved', status: 'open', limit: 1 })).toHaveLength(0)
    expect(clarifications.list({ deliveryMessageId: 'deliv-open', status: 'any', limit: 1 })[0]?.id).toBe(openRow.id)
    expect(clarifications.list({ deliveryMessageId: 'deliv-resolved', status: 'any', limit: 1 })[0]?.id).toBe(
      resolvedRow.id,
    )
    expect(clarifications.list({ deliveryMessageId: 'unknown-deliv', status: 'any', limit: 1 })).toHaveLength(0)
  })

  it('deliveryMessageId exact: two open rows, B newer, limit=1 → A never B', () => {
    const { row: a } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'A',
    })
    clarifications.recordDelivery(a.id, { deliveryMessageId: 'deliv-A' })
    forceCreatedAt(a.id, '2026-08-01T10:00:00.000Z')

    seedTx('tx-B')
    const { row: b } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-B',
      questionType: 'category',
      questionText: 'B newer',
    })
    clarifications.recordDelivery(b.id, { deliveryMessageId: 'deliv-B' })
    forceCreatedAt(b.id, '2026-08-02T10:00:00.000Z')

    const hit = clarifications.list({ deliveryMessageId: 'deliv-A', status: 'open', limit: 1 })
    expect(hit).toHaveLength(1)
    expect(hit[0].id).toBe(a.id)
    expect(hit[0].id).not.toBe(b.id)
  })

  it('deliveryMessageId + any: resolved A beats newer open B', () => {
    const { row: a } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'A',
    })
    clarifications.recordDelivery(a.id, { deliveryMessageId: 'deliv-A' })
    clarifications.resolve(a.id, {
      replyMessageId: 'reply-a',
      resolvedBy: 'owner',
      resolution: 'Mercado',
    })
    forceCreatedAt(a.id, '2026-08-01T10:00:00.000Z')

    seedTx('tx-B')
    const { row: b } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-B',
      questionType: 'category',
      questionText: 'B newer open',
    })
    clarifications.recordDelivery(b.id, { deliveryMessageId: 'deliv-B' })
    forceCreatedAt(b.id, '2026-08-02T10:00:00.000Z')

    const hit = clarifications.list({ deliveryMessageId: 'deliv-A', status: 'any', limit: 1 })
    expect(hit).toHaveLength(1)
    expect(hit[0].id).toBe(a.id)
    expect(hit[0].status).toBe('resolved')
  })

  it('count com deliveryMessageId respeita filtro exato', () => {
    const { row: a } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'A',
    })
    clarifications.recordDelivery(a.id, { deliveryMessageId: 'deliv-A' })

    seedTx('tx-B')
    const { row: b } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-B',
      questionType: 'category',
      questionText: 'B',
    })
    clarifications.recordDelivery(b.id, { deliveryMessageId: 'deliv-B' })

    expect(clarifications.count({ deliveryMessageId: 'deliv-A', status: 'any' })).toBe(1)
    expect(clarifications.count({ status: 'open' })).toBe(2)
  })

  it('deliveryMessageId combina com competenceMonth', () => {
    const { row: a } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'A',
    })
    clarifications.recordDelivery(a.id, { deliveryMessageId: 'deliv-A' })

    expect(
      clarifications.list({
        deliveryMessageId: 'deliv-A',
        status: 'any',
        competenceMonth: '2099-01',
        limit: 1,
      }),
    ).toHaveLength(0)
    expect(
      clarifications.list({
        deliveryMessageId: 'deliv-A',
        status: 'any',
        competenceMonth: '2026-08',
        limit: 1,
      })[0]?.id,
    ).toBe(a.id)
  })

  it('status=snoozed mapeia open + snoozed_until futuro (não status DB)', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'snooze?',
    })
    clarifications.snooze(row.id, '2099-01-01T00:00:00.000Z')
    expect(clarifications.list({ status: 'snoozed' })).toHaveLength(1)
    expect(clarifications.list({ status: 'open' })[0]?.id).toBe(row.id)
  })

  it('list({}) sem status não aplica default open (boundary HTTP, não repo)', () => {
    const { row } = clarifications.getOrCreateOpen({
      pluggyTransactionId: 'tx-1',
      questionType: 'category',
      questionText: 'open',
    })
    clarifications.resolve(row.id, {
      replyMessageId: 'r1',
      resolvedBy: 'owner',
      resolution: 'x',
    })
    // Internal callers: no status → unfiltered (includes resolved).
    expect(clarifications.list({}).some((c) => c.status === 'resolved')).toBe(true)
  })
})
