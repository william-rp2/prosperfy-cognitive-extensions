import type { FinanceDb } from './db.js'

export interface FinancialAccountPreferenceRow {
  pluggy_account_id: string
  display_alias: string | null
  is_favorite: number
  responsible_label: string | null
  created_at: string
  updated_at: string
}

/**
 * User-facing preferences for Pluggy accounts (alias, favorite).
 * Deliberately separate from financial_accounts — sync upserts account rows
 * but never touches this table.
 */
export class AccountPreferencesRepository {
  constructor(private readonly db: FinanceDb) {}

  get(pluggyAccountId: string): FinancialAccountPreferenceRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_account_preferences WHERE pluggy_account_id = ?')
      .get(pluggyAccountId) as FinancialAccountPreferenceRow | undefined
  }

  listAll(): FinancialAccountPreferenceRow[] {
    return this.db.prepare('SELECT * FROM financial_account_preferences').all() as FinancialAccountPreferenceRow[]
  }

  upsert(
    pluggyAccountId: string,
    input: { displayAlias?: string | null; isFavorite?: boolean; responsibleLabel?: string | null },
  ): FinancialAccountPreferenceRow {
    const now = new Date().toISOString()
    const existing = this.get(pluggyAccountId)
    const displayAlias =
      input.displayAlias !== undefined ? input.displayAlias?.trim() || null : (existing?.display_alias ?? null)
    const isFavorite =
      input.isFavorite !== undefined ? (input.isFavorite ? 1 : 0) : (existing?.is_favorite ?? 0)
    const responsibleLabel =
      input.responsibleLabel !== undefined
        ? input.responsibleLabel?.trim() || null
        : (existing?.responsible_label ?? null)

    this.db
      .prepare(
        `INSERT INTO financial_account_preferences (pluggy_account_id, display_alias, is_favorite, responsible_label, created_at, updated_at)
         VALUES (@pluggyAccountId, @displayAlias, @isFavorite, @responsibleLabel, @now, @now)
         ON CONFLICT(pluggy_account_id) DO UPDATE SET
           display_alias = excluded.display_alias,
           is_favorite = excluded.is_favorite,
           responsible_label = excluded.responsible_label,
           updated_at = excluded.updated_at`,
      )
      .run({ pluggyAccountId, displayAlias, isFavorite, responsibleLabel, now })

    return this.get(pluggyAccountId)!
  }

  clearAlias(pluggyAccountId: string): FinancialAccountPreferenceRow | undefined {
    const existing = this.get(pluggyAccountId)
    if (!existing) return undefined
    return this.upsert(pluggyAccountId, { displayAlias: null, isFavorite: Boolean(existing.is_favorite) })
  }
}
