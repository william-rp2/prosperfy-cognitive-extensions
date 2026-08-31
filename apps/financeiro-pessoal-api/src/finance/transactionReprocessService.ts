import type { AccountsRepository } from './accountsRepository.js'
import type { ClassificationService } from './classificationService.js'
import type { ClarificationsRepository } from './clarificationsRepository.js'
import type { CycleAssignmentService } from './cycleAssignmentService.js'
import type { FinanceDb } from './db.js'
import type { EnrichmentRepository, EnrichmentRow } from './enrichmentRepository.js'
import type { TemporalTransactionRow } from './temporalSemantics.js'
import type { FinancialTransactionRow } from './types.js'
import type { TransactionsRepository } from './transactionsRepository.js'

export interface ReprocessMetrics {
  processed: number
  updated: number
  unchanged: number
  failed: number
  accountContextMissing: number
  clarificationsCreated: number
  clarificationsReused: number
  dryRun: boolean
}

export interface ReprocessOptions {
  dryRun?: boolean
  pluggyTransactionId?: string
}

function snapshotEnrichment(row: EnrichmentRow | undefined) {
  if (!row) return null
  return {
    category_id: row.category_id,
    category_name: row.category_name,
    merchant_normalized: row.merchant_normalized,
    canonical_type: row.canonical_type,
    direction: row.direction,
    raw_type: row.raw_type,
    payment_method: row.payment_method,
    classification_status: row.classification_status,
    classification_confidence: row.classification_confidence,
    classification_source: row.classification_source,
    notes: row.notes,
  }
}

function enrichmentSemanticallyEqual(
  before: ReturnType<typeof snapshotEnrichment>,
  after: ReturnType<typeof snapshotEnrichment>,
): boolean {
  if (before === null && after === null) return true
  if (before === null || after === null) return false
  return JSON.stringify(before) === JSON.stringify(after)
}

function snapshotTransaction(row: FinancialTransactionRow) {
  return {
    pluggy_transaction_id: row.pluggy_transaction_id,
    pluggy_account_id: row.pluggy_account_id,
    description: row.description,
    description_raw: row.description_raw,
    amount_cents: row.amount_cents,
    date: row.date,
    type: row.type,
    category_original: row.category_original,
    merchant_original: row.merchant_original,
    raw_data: row.raw_data,
    last_synced_at: row.last_synced_at,
  }
}

export class TransactionReprocessService {
  constructor(
    private readonly db: FinanceDb,
    private readonly transactions: TransactionsRepository,
    private readonly accounts: AccountsRepository,
    private readonly enrichment: EnrichmentRepository,
    private readonly clarifications: ClarificationsRepository,
    private readonly classification: ClassificationService,
    /**
     * F2B temporal/cycle layer. Optional and last so existing call sites keep compiling; when it
     * is absent the reprocess behaves exactly as before.
     */
    private readonly cycleAssignment?: CycleAssignmentService,
  ) {}

  run(options: ReprocessOptions = {}): ReprocessMetrics {
    const rows = options.pluggyTransactionId
      ? (() => {
          const row = this.transactions.getByPluggyId(options.pluggyTransactionId!)
          return row && !row.deleted_at ? [row] : []
        })()
      : this.transactions.listAll()

    const metrics: ReprocessMetrics = {
      processed: 0,
      updated: 0,
      unchanged: 0,
      failed: 0,
      accountContextMissing: 0,
      clarificationsCreated: 0,
      clarificationsReused: 0,
      dryRun: Boolean(options.dryRun),
    }

    // Bills are mirrored into cycles once per account, not once per transaction.
    const cyclesEnsured = new Set<string>()

    for (const row of rows) {
      metrics.processed += 1
      const openBefore = this.clarifications.countOpenForTransaction(row.pluggy_transaction_id)
      try {
        const account = this.accounts.getByPluggyId(row.pluggy_account_id)
        if (!account) {
          metrics.accountContextMissing += 1
          continue
        }

        if (!options.dryRun) {
          this.transactions.backfillCurrencyFromRaw(row.pluggy_transaction_id, account.currency_code)
          // F2B: re-derive the temporal facts and the statement cycle. Idempotent, and it refuses
          // to downgrade an assignment made by a stronger source (a USER correction, a reconciled
          // statement), so reprocessing never silently undoes an owner decision.
          if (this.cycleAssignment) {
            if (!cyclesEnsured.has(account.pluggy_account_id)) {
              this.cycleAssignment.ensureCyclesForAccount(account.pluggy_account_id)
              cyclesEnsured.add(account.pluggy_account_id)
            }
            this.cycleAssignment.syncTemporal(row as TemporalTransactionRow, account)
          }
        }

        const enrichBefore = snapshotEnrichment(this.enrichment.getByTransactionId(row.pluggy_transaction_id))
        let result: { clarificationCreated: boolean; classificationStatus: string }

        if (options.dryRun) {
          this.db.prepare('SAVEPOINT reprocess_dry').run()
          try {
            result = this.classification.classifyPluggyTransaction(row)
            const enrichAfter = snapshotEnrichment(this.enrichment.getByTransactionId(row.pluggy_transaction_id))
            this.db.prepare('ROLLBACK TO reprocess_dry').run()
            this.db.prepare('RELEASE reprocess_dry').run()
            if (enrichmentSemanticallyEqual(enrichBefore, enrichAfter)) metrics.unchanged += 1
            else metrics.updated += 1
            if (result.clarificationCreated) metrics.clarificationsCreated += 1
            else if (result.classificationStatus === 'needs_clarification') metrics.clarificationsReused += 1
          } catch (error) {
            this.db.prepare('ROLLBACK TO reprocess_dry').run()
            this.db.prepare('RELEASE reprocess_dry').run()
            throw error
          }
        } else {
          const txBefore = snapshotTransaction(row)
          result = this.classification.classifyPluggyTransaction(row)
          const txAfter = this.transactions.getByPluggyId(row.pluggy_transaction_id)
          if (!txAfter || JSON.stringify(snapshotTransaction(txAfter)) !== JSON.stringify(txBefore)) {
            throw new Error(`source transaction mutated: ${row.pluggy_transaction_id}`)
          }
          const enrichAfter = snapshotEnrichment(this.enrichment.getByTransactionId(row.pluggy_transaction_id))
          if (enrichmentSemanticallyEqual(enrichBefore, enrichAfter)) metrics.unchanged += 1
          else metrics.updated += 1
          if (result.clarificationCreated) metrics.clarificationsCreated += 1
          else if (
            result.classificationStatus === 'needs_clarification' &&
            this.clarifications.countOpenForTransaction(row.pluggy_transaction_id) >= openBefore &&
            openBefore > 0
          ) {
            metrics.clarificationsReused += 1
          }
        }
      } catch {
        metrics.failed += 1
      }
    }

    return metrics
  }
}
