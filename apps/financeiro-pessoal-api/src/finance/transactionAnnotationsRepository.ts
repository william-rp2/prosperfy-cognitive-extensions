import type { FinanceDb } from './db.js'

const MAX_NOTE_LENGTH = 500

export interface TransactionAnnotationRow {
  pluggy_transaction_id: string
  note: string
  created_at: string
  updated_at: string
}

export class TransactionAnnotationsRepository {
  constructor(private readonly db: FinanceDb) {}

  get(pluggyTransactionId: string): TransactionAnnotationRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_transaction_annotations WHERE pluggy_transaction_id = ?')
      .get(pluggyTransactionId) as TransactionAnnotationRow | undefined
  }

  upsert(pluggyTransactionId: string, note: string): TransactionAnnotationRow {
    const trimmed = note.trim()
    if (!trimmed) throw new Error('note_required')
    if (trimmed.length > MAX_NOTE_LENGTH) throw new Error('note_too_long')

    const now = new Date().toISOString()
    const existing = this.get(pluggyTransactionId)

    this.db
      .prepare(
        `INSERT INTO financial_transaction_annotations (pluggy_transaction_id, note, created_at, updated_at)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(pluggy_transaction_id) DO UPDATE SET
           note = excluded.note,
           updated_at = excluded.updated_at`,
      )
      .run(pluggyTransactionId, trimmed, existing?.created_at ?? now, now)

    return this.get(pluggyTransactionId)!
  }

  delete(pluggyTransactionId: string): boolean {
    const result = this.db
      .prepare('DELETE FROM financial_transaction_annotations WHERE pluggy_transaction_id = ?')
      .run(pluggyTransactionId)
    return result.changes > 0
  }

  searchNoteContains(term: string): string[] {
    const pattern = `%${term.replace(/[%_]/g, '')}%`
    return (
      this.db
        .prepare(
          `SELECT pluggy_transaction_id FROM financial_transaction_annotations
           WHERE note LIKE ? COLLATE NOCASE`,
        )
        .all(pattern) as { pluggy_transaction_id: string }[]
    ).map(row => row.pluggy_transaction_id)
  }
}
