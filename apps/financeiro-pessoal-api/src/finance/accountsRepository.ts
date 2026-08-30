import { randomUUID } from 'node:crypto'

import type { FinanceDb } from './db.js'
import { normalizeFinancialAccount } from './financialAssetNormalizer.js'
import type { FinancialAccountRow } from './types.js'

export interface UpsertAccountInput {
  pluggyAccountId: string
  pluggyItemId: string
  type?: string | null
  subtype?: string | null
  name?: string | null
  marketingName?: string | null
  currencyCode?: string | null
  balanceCents?: number | null
  numberMasked?: string | null
  owner?: string | null
  creditLimitCents?: number | null
  availableCreditLimitCents?: number | null
  rawData?: unknown
  canonicalType?: string | null
  assetClassificationConfidence?: number | null
  assetClassificationUncertain?: boolean | null
}

export class AccountsRepository {
  constructor(private readonly db: FinanceDb) {}

  upsertAccount(input: UpsertAccountInput): FinancialAccountRow {
    const now = new Date().toISOString()
    const existing = this.getByPluggyId(input.pluggyAccountId)
    const asset = normalizeFinancialAccount({
      pluggyType: input.type,
      pluggySubtype: input.subtype,
      name: input.name,
      marketingName: input.marketingName,
      creditLimitCents: input.creditLimitCents,
      rawData: input.rawData,
    })
    const canonicalType = input.canonicalType ?? asset.canonicalType
    const confidence = input.assetClassificationConfidence ?? asset.confidence
    const uncertain = input.assetClassificationUncertain ?? asset.classificationUncertain

    this.db
      .prepare(
        `INSERT INTO financial_accounts (id, pluggy_account_id, pluggy_item_id, type, subtype, name, marketing_name, currency_code, balance_cents, number_masked, owner, credit_limit_cents, available_credit_limit_cents, canonical_type, asset_classification_confidence, asset_classification_uncertain, created_at, updated_at, last_synced_at, raw_data)
         VALUES (@id, @pluggyAccountId, @pluggyItemId, @type, @subtype, @name, @marketingName, @currencyCode, @balanceCents, @numberMasked, @owner, @creditLimitCents, @availableCreditLimitCents, @canonicalType, @assetClassificationConfidence, @assetClassificationUncertain, @createdAt, @updatedAt, @lastSyncedAt, @rawData)
         ON CONFLICT(pluggy_account_id) DO UPDATE SET
           type = excluded.type,
           subtype = excluded.subtype,
           name = excluded.name,
           marketing_name = excluded.marketing_name,
           currency_code = excluded.currency_code,
           balance_cents = excluded.balance_cents,
           number_masked = excluded.number_masked,
           owner = excluded.owner,
           credit_limit_cents = excluded.credit_limit_cents,
           available_credit_limit_cents = excluded.available_credit_limit_cents,
           canonical_type = excluded.canonical_type,
           asset_classification_confidence = excluded.asset_classification_confidence,
           asset_classification_uncertain = excluded.asset_classification_uncertain,
           updated_at = excluded.updated_at,
           last_synced_at = excluded.last_synced_at,
           raw_data = excluded.raw_data`,
      )
      .run({
        id: existing?.id ?? randomUUID(),
        pluggyAccountId: input.pluggyAccountId,
        pluggyItemId: input.pluggyItemId,
        type: input.type ?? null,
        subtype: input.subtype ?? null,
        name: input.name ?? null,
        marketingName: input.marketingName ?? null,
        currencyCode: input.currencyCode ?? null,
        balanceCents: input.balanceCents ?? null,
        numberMasked: input.numberMasked ?? null,
        owner: input.owner ?? null,
        creditLimitCents: input.creditLimitCents ?? null,
        availableCreditLimitCents: input.availableCreditLimitCents ?? null,
        canonicalType,
        assetClassificationConfidence: confidence,
        assetClassificationUncertain: uncertain ? 1 : 0,
        createdAt: existing?.created_at ?? now,
        updatedAt: now,
        lastSyncedAt: now,
        rawData: input.rawData !== undefined ? JSON.stringify(input.rawData) : null,
      })

    return this.getByPluggyId(input.pluggyAccountId)!
  }

  getByPluggyId(pluggyAccountId: string): FinancialAccountRow | undefined {
    return this.db.prepare('SELECT * FROM financial_accounts WHERE pluggy_account_id = ?').get(pluggyAccountId) as
      | FinancialAccountRow
      | undefined
  }

  listByItem(pluggyItemId: string): FinancialAccountRow[] {
    return this.db
      .prepare('SELECT * FROM financial_accounts WHERE pluggy_item_id = ? ORDER BY name ASC')
      .all(pluggyItemId) as FinancialAccountRow[]
  }

  listAll(): FinancialAccountRow[] {
    return this.db.prepare('SELECT * FROM financial_accounts ORDER BY name ASC').all() as FinancialAccountRow[]
  }
}
