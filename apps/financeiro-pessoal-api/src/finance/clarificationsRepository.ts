import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type ClarificationStatus = 'open' | 'resolved' | 'dismissed'
export type ClarificationPriority = 'low' | 'normal' | 'high'

export interface ClarificationRow {
  id: string
  pluggy_transaction_id: string
  question_type: string
  status: ClarificationStatus
  question_text: string | null
  created_at: string
  resolved_at: string | null
  resolved_by: string | null
  resolution: string | null
  source_message_id: string | null
  quoted_message_id: string | null
  priority: ClarificationPriority
  delivery_chat_id: string | null
  first_delivered_at: string | null
  last_delivered_at: string | null
  delivery_count: number
  snoozed_until: string | null
}

export interface ClarificationListFilters {
  status?: ClarificationStatus
  questionType?: string
  competenceMonth?: string
  pluggyItemId?: string
  pluggyAccountId?: string
  limit?: number
  offset?: number
}

export interface GetOrCreateClarificationInput {
  pluggyTransactionId: string
  questionType: string
  questionText: string
}

export class ClarificationsRepository {
  constructor(private readonly db: FinanceDb) {}

  getOpen(pluggyTransactionId: string, questionType: string): ClarificationRow | undefined {
    return this.db
      .prepare(
        `SELECT * FROM finance_clarifications
         WHERE pluggy_transaction_id = ? AND question_type = ? AND status = 'open'`,
      )
      .get(pluggyTransactionId, questionType) as ClarificationRow | undefined
  }

  /** Idempotent: returns existing OPEN or creates a new one. Never duplicates OPEN rows. */
  getOrCreateOpen(input: GetOrCreateClarificationInput): { row: ClarificationRow; created: boolean } {
    const existing = this.getOpen(input.pluggyTransactionId, input.questionType)
    if (existing) return { row: existing, created: false }

    const now = new Date().toISOString()
    const id = randomUUID()

    try {
      this.db
        .prepare(
          `INSERT INTO finance_clarifications (
             id, pluggy_transaction_id, question_type, status, question_text, created_at
           ) VALUES (?, ?, ?, 'open', ?, ?)`,
        )
        .run(id, input.pluggyTransactionId, input.questionType, input.questionText, now)
      const row = this.db.prepare('SELECT * FROM finance_clarifications WHERE id = ?').get(id) as ClarificationRow
      return { row, created: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (message.includes('UNIQUE') || message.includes('constraint')) {
        const raced = this.getOpen(input.pluggyTransactionId, input.questionType)
        if (raced) return { row: raced, created: false }
      }
      throw error
    }
  }

  countOpenForTransaction(pluggyTransactionId: string): number {
    const row = this.db
      .prepare(
        `SELECT COUNT(*) as count FROM finance_clarifications
         WHERE pluggy_transaction_id = ? AND status = 'open'`,
      )
      .get(pluggyTransactionId) as { count: number }
    return row.count
  }

  listOpenForTransaction(pluggyTransactionId: string): ClarificationRow[] {
    return this.db
      .prepare(
        `SELECT * FROM finance_clarifications
         WHERE pluggy_transaction_id = ? AND status = 'open'
         ORDER BY created_at ASC`,
      )
      .all(pluggyTransactionId) as ClarificationRow[]
  }

  getById(id: string): ClarificationRow | undefined {
    return this.db.prepare('SELECT * FROM finance_clarifications WHERE id = ?').get(id) as
      | ClarificationRow
      | undefined
  }

  /**
   * Dynamic, never cached: every call re-derives from live rows (03 doc §Historical count
   * behavior — "não cachear número histórico"). Filtering by competence_month uses the
   * effective period column on financial_transactions; a transaction with unknown competence
   * is excluded from a month filter rather than guessed.
   */
  list(filters: ClarificationListFilters = {}): ClarificationRow[] {
    const conditions: string[] = []
    const params: Record<string, unknown> = {}

    if (filters.status) {
      conditions.push('c.status = @status')
      params.status = filters.status
    }
    if (filters.questionType) {
      conditions.push('c.question_type = @questionType')
      params.questionType = filters.questionType
    }
    if (filters.competenceMonth) {
      conditions.push('t.competence_month = @competenceMonth')
      params.competenceMonth = filters.competenceMonth
    }
    if (filters.pluggyAccountId) {
      conditions.push('t.pluggy_account_id = @pluggyAccountId')
      params.pluggyAccountId = filters.pluggyAccountId
    }
    if (filters.pluggyItemId) {
      conditions.push('a.pluggy_item_id = @pluggyItemId')
      params.pluggyItemId = filters.pluggyItemId
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
    const limit = Math.min(filters.limit ?? 200, 1000)
    const offset = filters.offset ?? 0

    return this.db
      .prepare(
        `SELECT c.* FROM finance_clarifications c
         JOIN financial_transactions t ON t.pluggy_transaction_id = c.pluggy_transaction_id
         LEFT JOIN financial_accounts a ON a.pluggy_account_id = t.pluggy_account_id
         ${where}
         ORDER BY c.created_at DESC
         LIMIT @limit OFFSET @offset`,
      )
      .all({ ...params, limit, offset }) as ClarificationRow[]
  }

  count(filters: ClarificationListFilters = {}): number {
    const conditions: string[] = []
    const params: Record<string, unknown> = {}

    if (filters.status) {
      conditions.push('c.status = @status')
      params.status = filters.status
    }
    if (filters.questionType) {
      conditions.push('c.question_type = @questionType')
      params.questionType = filters.questionType
    }
    if (filters.competenceMonth) {
      conditions.push('t.competence_month = @competenceMonth')
      params.competenceMonth = filters.competenceMonth
    }
    if (filters.pluggyAccountId) {
      conditions.push('t.pluggy_account_id = @pluggyAccountId')
      params.pluggyAccountId = filters.pluggyAccountId
    }
    if (filters.pluggyItemId) {
      conditions.push('a.pluggy_item_id = @pluggyItemId')
      params.pluggyItemId = filters.pluggyItemId
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
    const row = this.db
      .prepare(
        `SELECT COUNT(*) as count FROM finance_clarifications c
         JOIN financial_transactions t ON t.pluggy_transaction_id = c.pluggy_transaction_id
         LEFT JOIN financial_accounts a ON a.pluggy_account_id = t.pluggy_account_id
         ${where}`,
      )
      .get(params) as { count: number }
    return row.count
  }

  /**
   * Binds an outbound WhatsApp message to a clarification for exact reply resolution
   * (03 doc §Reply binding). Only affects OPEN clarifications — a resolved/dismissed one is
   * not silently reopened by a delivery call.
   */
  recordDelivery(
    id: string,
    input: { deliveryMessageId: string; deliveryChatId?: string | null },
  ): ClarificationRow | undefined {
    const existing = this.getById(id)
    if (!existing || existing.status !== 'open') return undefined

    const now = new Date().toISOString()
    this.db
      .prepare(
        `UPDATE finance_clarifications
            SET source_message_id = ?,
                delivery_chat_id = COALESCE(?, delivery_chat_id),
                first_delivered_at = COALESCE(first_delivered_at, ?),
                last_delivered_at = ?,
                delivery_count = delivery_count + 1,
                snoozed_until = NULL
          WHERE id = ?`,
      )
      .run(input.deliveryMessageId, input.deliveryChatId ?? null, now, now, id)
    return this.getById(id)
  }

  /**
   * Resolves by explicit clarification id (already bound via quoted_message_id at the
   * caller). Late-reply safe: resolving an already-resolved clarification is a no-op that
   * returns the existing row with `alreadyResolved: true` instead of mutating again
   * (03 doc §Late reply — never duplicate the mutation).
   */
  resolve(
    id: string,
    input: { replyMessageId: string; resolvedBy: string | null; resolution: string | null },
  ): { row: ClarificationRow; alreadyResolved: boolean } | undefined {
    const existing = this.getById(id)
    if (!existing) return undefined

    if (existing.status !== 'open') {
      return { row: existing, alreadyResolved: true }
    }

    const now = new Date().toISOString()
    this.db
      .prepare(
        `UPDATE finance_clarifications
            SET status = 'resolved',
                resolved_at = ?,
                resolved_by = ?,
                resolution = ?,
                quoted_message_id = ?
          WHERE id = ?`,
      )
      .run(now, input.resolvedBy, input.resolution, input.replyMessageId, id)
    return { row: this.getById(id)!, alreadyResolved: false }
  }

  /** Owner said "later" — stays open/unresolved but delivery does not repeat until `until`. */
  snooze(id: string, until: string): ClarificationRow | undefined {
    const existing = this.getById(id)
    if (!existing || existing.status !== 'open') return undefined
    this.db.prepare('UPDATE finance_clarifications SET snoozed_until = ? WHERE id = ?').run(until, id)
    return this.getById(id)
  }
}
