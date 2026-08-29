import type { CategoryOverridesRepository } from './categoryOverridesRepository.js'
import type { CategoriesRepository } from './categoriesRepository.js'
import type { ClarificationsRepository } from './clarificationsRepository.js'
import type { EnrichmentRepository } from './enrichmentRepository.js'
import type { FinancialTransactionRow } from './types.js'
import { normalizePluggyTransaction } from './transactionNormalizer.js'

export interface ClassificationResult {
  enrichmentWritten: boolean
  clarificationCreated: boolean
  classificationStatus: string
}

export class ClassificationService {
  constructor(
    private readonly enrichment: EnrichmentRepository,
    private readonly clarifications: ClarificationsRepository,
    private readonly categories: CategoriesRepository,
    private readonly overrides: CategoryOverridesRepository,
  ) {}

  /** Skips re-classification when enrichment is already confirmed (manual/historical/rules). */
  classifyIfNeeded(row: FinancialTransactionRow): ClassificationResult {
    const existing = this.enrichment.getByTransactionId(row.pluggy_transaction_id)
    if (
      existing?.classification_status === 'classified' &&
      existing.classification_source &&
      existing.classification_source !== 'unknown'
    ) {
      return {
        enrichmentWritten: false,
        clarificationCreated: false,
        classificationStatus: existing.classification_status,
      }
    }
    return this.classifyPluggyTransaction(row)
  }

  classifyPluggyTransaction(row: FinancialTransactionRow): ClassificationResult {
    const normalized = normalizePluggyTransaction({
      pluggyType: row.type,
      amountCents: row.amount_cents,
      description: row.description,
      descriptionRaw: row.description_raw,
      merchantOriginal: row.merchant_original,
      rawData: row.raw_data ? JSON.parse(row.raw_data) : undefined,
    })

    const override = this.overrides.get(row.pluggy_transaction_id)
    if (override) {
      const category = this.categories.getById(override.category_id)
      this.enrichment.upsert({
        pluggyTransactionId: row.pluggy_transaction_id,
        categoryId: override.category_id,
        categoryName: category?.name ?? null,
        merchantNormalized: normalized.merchantNormalized,
        canonicalType: normalized.canonicalType,
        direction: normalized.direction,
        rawType: normalized.rawType,
        paymentMethod: normalized.paymentMethod,
        classificationStatus: 'classified',
        classificationConfidence: 1,
        classificationSource: 'manual',
      })
      return { enrichmentWritten: true, clarificationCreated: false, classificationStatus: 'classified' }
    }

    if (normalized.merchantNormalized) {
      const historical = this.enrichment.findHistoricalByMerchant(normalized.merchantNormalized)
      if (historical?.category_id) {
        this.enrichment.upsert({
          pluggyTransactionId: row.pluggy_transaction_id,
          categoryId: historical.category_id,
          categoryName: historical.category_name,
          merchantNormalized: normalized.merchantNormalized,
          canonicalType: normalized.canonicalType,
          direction: normalized.direction,
          rawType: normalized.rawType,
          paymentMethod: normalized.paymentMethod,
          classificationStatus: 'classified',
          classificationConfidence: 0.9,
          classificationSource: 'historical_confirmed',
        })
        return { enrichmentWritten: true, clarificationCreated: false, classificationStatus: 'classified' }
      }
    }

    const pluggyCategory = row.category_original?.trim()
    if (pluggyCategory) {
      const matches = this.categories.findByName(pluggyCategory)
      const exact = matches.find(c => c.name.toLowerCase() === pluggyCategory.toLowerCase()) ?? matches[0]
      if (exact && matches.length === 1) {
        this.enrichment.upsert({
          pluggyTransactionId: row.pluggy_transaction_id,
          categoryId: exact.id,
          categoryName: exact.name,
          merchantNormalized: normalized.merchantNormalized,
          canonicalType: normalized.canonicalType,
          direction: normalized.direction,
          rawType: normalized.rawType,
          paymentMethod: normalized.paymentMethod,
          classificationStatus: 'classified',
          classificationConfidence: 0.75,
          classificationSource: 'deterministic_rule',
        })
        return { enrichmentWritten: true, clarificationCreated: false, classificationStatus: 'classified' }
      }
    }

    this.enrichment.upsert({
      pluggyTransactionId: row.pluggy_transaction_id,
      merchantNormalized: normalized.merchantNormalized,
      canonicalType: normalized.canonicalType,
      direction: normalized.direction,
      rawType: normalized.rawType,
      paymentMethod: normalized.paymentMethod,
      classificationStatus: 'needs_clarification',
      classificationConfidence: 0.2,
      classificationSource: 'unknown',
      notes: 'Aguardando classificação do owner (F2 WhatsApp).',
    })

    const label = row.description || row.merchant_original || 'transação desconhecida'
    const amount = (Math.abs(row.amount_cents) / 100).toFixed(2)
    const { created } = this.clarifications.getOrCreateOpen({
      pluggyTransactionId: row.pluggy_transaction_id,
      questionType: 'category',
      questionText: `Como classificar "${label}" (R$ ${amount})?`,
    })

    return {
      enrichmentWritten: true,
      clarificationCreated: created,
      classificationStatus: 'needs_clarification',
    }
  }
}
