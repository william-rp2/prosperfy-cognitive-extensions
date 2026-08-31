import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import type { AccountsRepository } from '../finance/accountsRepository.js'
import type { ClarificationsRepository } from '../finance/clarificationsRepository.js'
import type { CorrectionsRepository } from '../finance/correctionsRepository.js'
import type { EnrichmentRepository } from '../finance/enrichmentRepository.js'
import type { ItemsRepository } from '../finance/itemsRepository.js'
import type { OnboardingRepository } from '../finance/onboardingRepository.js'
import { applyImportPlan, planImport, type ImportPlanContext } from '../finance/spreadsheetImport.js'
import { buildOnboardingCsv, type OnboardingExportRowData } from '../finance/spreadsheetExport.js'
import type { TransactionsRepository } from '../finance/transactionsRepository.js'
import { safeCompare } from '../safe.js'

/**
 * Onboarding export/import surface (F2B, SUBAGENT_B).
 *
 * Registered as its own encapsulated Fastify scope (PLAN.md route ownership). Only the
 * orchestrator wires this into `routes/finance.ts`.
 *
 * Export builds a batch of pending items from live data — never a hard-coded count or list
 * (rule 8 of the brief). Import treats the uploaded text as untrusted data end to end: it is
 * parsed and validated against a fixed schema, never evaluated or executed (rule 6).
 */

export interface FinanceOnboardingRouteDeps {
  config: AppConfig
  transactions: TransactionsRepository
  accounts: AccountsRepository
  items: ItemsRepository
  enrichment: EnrichmentRepository
  clarifications: ClarificationsRepository
  corrections: CorrectionsRepository
  onboarding: OnboardingRepository
}

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

export function registerFinanceOnboardingRoutes(app: FastifyInstance, deps: FinanceOnboardingRouteDeps): void {
  const { config, transactions, accounts, items, enrichment, clarifications, corrections, onboarding } = deps

  const revisionOf = (pluggyTransactionId: string): string | null => {
    const tx = transactions.getByPluggyId(pluggyTransactionId)
    if (!tx) return null
    let latest = tx.updated_at
    for (const correction of corrections.listActive(pluggyTransactionId).values()) {
      if (correction.created_at > latest) latest = correction.created_at
    }
    return latest
  }

  void app.register(async onboardingApp => {
    onboardingApp.addHook('preHandler', async (request, reply) => {
      if (!requireFinanceToken(request, config)) {
        return reply.code(401).send({
          error: 'unauthorized',
          message: 'FINANCE_API_TOKEN ausente ou inválido no header Authorization: Bearer <token>.',
        })
      }
    })

    /**
     * Filter pending -> export batch. The batch is whatever OPEN clarifications currently
     * match the filters — never a fixed/hard-coded slice. The owner explicitly chooses what
     * to process by supplying filters; there is no "export everything by default" firehose.
     */
    onboardingApp.post('/api/finance/onboarding/export', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>
      const pluggyItemId = typeof body.pluggyItemId === 'string' ? body.pluggyItemId : undefined
      const competenceMonth = typeof body.competenceMonth === 'string' ? body.competenceMonth : undefined
      const pluggyAccountId = typeof body.pluggyAccountId === 'string' ? body.pluggyAccountId : undefined
      const limit = typeof body.limit === 'number' ? body.limit : undefined

      const openClarifications = clarifications.list({
        status: 'open',
        pluggyItemId,
        competenceMonth,
        pluggyAccountId,
        limit,
      })

      // One export row per distinct transaction (a transaction may carry more than one open
      // question, but the spreadsheet edits the transaction, not the question).
      const seen = new Set<string>()
      const rows: OnboardingExportRowData[] = []

      for (const clarification of openClarifications) {
        const txId = clarification.pluggy_transaction_id
        if (seen.has(txId)) continue
        seen.add(txId)

        const tx = transactions.getByPluggyId(txId)
        if (!tx) continue
        const account = accounts.getByPluggyId(tx.pluggy_account_id)
        const item = account ? items.getByPluggyId(account.pluggy_item_id) : undefined
        const enr = enrichment.getByTransactionId(txId)

        rows.push({
          transactionId: txId,
          exportVersion: 0,
          updatedAt: revisionOf(txId) ?? tx.updated_at,
          date: tx.date,
          competenceMonth: (tx as unknown as { competence_month?: string | null }).competence_month ?? null,
          institution: item?.connector_name ?? null,
          // Display alias only — never number_masked, never a raw provider field.
          accountAlias: account?.marketing_name ?? account?.name ?? null,
          merchant: enr?.merchant_normalized ?? tx.merchant_original ?? null,
          originalDescription: tx.description ?? tx.description_raw ?? null,
          amountCents: tx.amount_cents,
          currency: tx.currency_code ?? account?.currency_code ?? null,
          category: enr?.category_name ?? tx.category_original ?? null,
          economicOwner: (enr as unknown as { economic_owner?: string | null } | undefined)?.economic_owner ?? null,
          responsible: null,
          reimbursement: null,
          statementCycle: (tx as unknown as { statement_cycle_id?: string | null }).statement_cycle_id ?? null,
          needsConfirmation: true,
          notes: enr?.notes ?? null,
        })
      }

      const exportRow = onboarding.recordExport({
        pluggyItemId: pluggyItemId ?? null,
        filters: { pluggyItemId, competenceMonth, pluggyAccountId },
        rowCount: rows.length,
      })

      const versionedRows = rows.map(row => ({ ...row, exportVersion: exportRow.export_version }))

      return reply.code(201).send({
        exportId: exportRow.id,
        exportVersion: exportRow.export_version,
        rowCount: versionedRows.length,
        csv: buildOnboardingCsv(versionedRows),
      })
    })

    /**
     * Upload -> parse -> dry-run|apply. `fileContent` is DATA, never instruction: parsing is a
     * fixed-schema pass, validation rejects anything that doesn't match, and applying only ever
     * writes through CorrectionsRepository/ClarificationsRepository — nothing derived from the
     * file content is ever executed as code.
     */
    onboardingApp.post('/api/finance/onboarding/import', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>

      if (typeof body.fileContent !== 'string' || !body.fileContent.trim()) {
        return reply.code(400).send({ error: 'invalid_file_content', message: 'Informe fileContent (CSV).' })
      }
      const dryRun = body.dryRun !== false // default true: apply requires an explicit dryRun:false

      const ctx: ImportPlanContext = {
        transactionExists: txId => Boolean(transactions.getByPluggyId(txId)),
        currentRevision: revisionOf,
        alreadyApplied: (contentKey, txId) => Boolean(onboarding.getImportRow(contentKey, txId)),
      }

      const { plan, parseError } = planImport(body.fileContent, ctx)
      if (parseError) {
        return reply.code(400).send({ error: 'parse_error', message: `Falha ao ler CSV: ${parseError}.` })
      }

      if (dryRun) {
        return { dryRun: true, rows: plan }
      }

      const results = applyImportPlan(plan, {
        corrections,
        clarifications,
        onboarding,
        actorId: typeof body.actorId === 'string' ? body.actorId : null,
        reason: 'onboarding_spreadsheet_import',
      })

      return { dryRun: false, rows: results }
    })
  })
}
