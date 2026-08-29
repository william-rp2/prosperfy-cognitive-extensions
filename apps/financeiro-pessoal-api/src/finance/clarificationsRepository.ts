import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'

export type ClarificationStatus = 'open' | 'resolved' | 'dismissed'

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
}
