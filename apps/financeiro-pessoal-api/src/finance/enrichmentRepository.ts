import type { FinanceDb } from './db.js'
import type { CanonicalDirection, CanonicalTransactionType } from './transactionNormalizer.js'

export type ClassificationStatus = 'classified' | 'needs_clarification' | 'unknown'
export type ClassificationSource =
  | 'manual'
  | 'merchant_rule'
  | 'historical_confirmed'
  | 'deterministic_rule'
  | 'unknown'

export interface EnrichmentUpsertInput {
  pluggyTransactionId: string
  categoryId?: string | null
  categoryName?: string | null
  merchantNormalized?: string | null
  canonicalType?: CanonicalTransactionType | null
  direction?: CanonicalDirection | null
  rawType?: string | null
  paymentMethod?: string | null
  classificationStatus: ClassificationStatus
  classificationConfidence?: number | null
  classificationSource: ClassificationSource
  notes?: string | null
}

export interface EnrichmentRow {
  pluggy_transaction_id: string
  category_id: string | null
  category_name: string | null
  merchant_normalized: string | null
  canonical_type: string | null
  direction: string | null
  raw_type: string | null
  payment_method: string | null
  classification_status: string
  classification_confidence: number | null
  classification_source: string | null
  notes: string | null
  updated_at: string
}

export class EnrichmentRepository {
  constructor(private readonly db: FinanceDb) {}

  getByTransactionId(pluggyTransactionId: string): EnrichmentRow | undefined {
    return this.db
      .prepare('SELECT * FROM financial_transaction_enrichment WHERE pluggy_transaction_id = ?')
      .get(pluggyTransactionId) as EnrichmentRow | undefined
  }

  upsert(input: EnrichmentUpsertInput): EnrichmentRow {
    const now = new Date().toISOString()
    const existing = this.getByTransactionId(input.pluggyTransactionId)

    this.db
      .prepare(
        `INSERT INTO financial_transaction_enrichment (
           pluggy_transaction_id, category_id, category_name, merchant_normalized,
           canonical_type, direction, raw_type, payment_method,
           classification_status, classification_confidence, classification_source,
           notes, updated_at
         ) VALUES (
           @pluggyTransactionId, @categoryId, @categoryName, @merchantNormalized,
           @canonicalType, @direction, @rawType, @paymentMethod,
           @classificationStatus, @classificationConfidence, @classificationSource,
           @notes, @updatedAt
         )
         ON CONFLICT(pluggy_transaction_id) DO UPDATE SET
           category_id = excluded.category_id,
           category_name = excluded.category_name,
           merchant_normalized = excluded.merchant_normalized,
           canonical_type = excluded.canonical_type,
           direction = excluded.direction,
           raw_type = excluded.raw_type,
           payment_method = excluded.payment_method,
           classification_status = excluded.classification_status,
           classification_confidence = excluded.classification_confidence,
           classification_source = excluded.classification_source,
           notes = excluded.notes,
           updated_at = excluded.updated_at`,
      )
      .run({
        pluggyTransactionId: input.pluggyTransactionId,
        categoryId: input.categoryId ?? existing?.category_id ?? null,
        categoryName: input.categoryName ?? existing?.category_name ?? null,
        merchantNormalized: input.merchantNormalized ?? existing?.merchant_normalized ?? null,
        canonicalType: input.canonicalType ?? existing?.canonical_type ?? null,
        direction: input.direction ?? existing?.direction ?? null,
        rawType: input.rawType ?? existing?.raw_type ?? null,
        paymentMethod: input.paymentMethod ?? existing?.payment_method ?? null,
        classificationStatus: input.classificationStatus,
        classificationConfidence: input.classificationConfidence ?? null,
        classificationSource: input.classificationSource,
        notes: input.notes ?? existing?.notes ?? null,
        updatedAt: now,
      })

    return this.getByTransactionId(input.pluggyTransactionId)!
  }

  findHistoricalByMerchant(merchantNormalized: string): EnrichmentRow | undefined {
    return this.db
      .prepare(
        `SELECT * FROM financial_transaction_enrichment
         WHERE merchant_normalized = ?
           AND classification_status = 'classified'
           AND category_id IS NOT NULL
         ORDER BY updated_at DESC
         LIMIT 1`,
      )
      .get(merchantNormalized) as EnrichmentRow | undefined
  }
}
