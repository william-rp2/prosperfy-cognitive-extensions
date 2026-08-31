import type { FastifyInstance, FastifyRequest } from 'fastify'

import type { AppConfig } from '../config.js'
import {
  AccountNotFoundError,
  StatementNotFoundError,
  type ReconciliationService,
} from '../finance/reconciliationService.js'
import { isStatementSource, type StatementImportRepository } from '../finance/statementImportRepository.js'
import type { StatementCyclesRepository, StatementCycleRow } from '../finance/statementCyclesRepository.js'
import { isMonthKey } from '../finance/temporalSemantics.js'
import { safeCompare } from '../safe.js'
import multipart from '@fastify/multipart'
import { extractPdfText, PdfExtractionError, MAX_PDF_BYTES } from '../finance/pdfTextExtractor.js'

/**
 * Closed-statement import, reconciliation and cycle listing (F2B, SUBAGENT_D).
 *
 * Registered as its own encapsulated Fastify scope, mirroring `financeCorrectionRoutes.ts`, so it
 * can be wired next to `registerFinanceRoutes` without either module editing the other.
 *
 * Edge invariants:
 *  1. Fail-closed auth. No `FINANCE_API_TOKEN` configured => every request is denied.
 *  2. The uploaded statement is DATA. Its text is stored and compared, never interpreted as an
 *     instruction, never used to pick a path, and never able to influence authorization.
 *  3. Read-and-match only. There is no payment, transfer or PIX surface here.
 *  4. A path parameter is never repeated in the body, and no `mode` field is accepted.
 */

export interface FinanceStatementRouteDeps {
  config: AppConfig
  statementImports: StatementImportRepository
  cycles: StatementCyclesRepository
  reconciliation: ReconciliationService
}

function requireFinanceToken(request: FastifyRequest, config: AppConfig): boolean {
  if (!config.FINANCE_API_TOKEN) return false
  const header = request.headers.authorization || ''
  const [scheme, token] = header.split(' ')
  if (scheme !== 'Bearer' || !token) return false
  return safeCompare(config.FINANCE_API_TOKEN, token)
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function optionalCents(value: unknown): number | null | undefined {
  if (value === undefined || value === null) return null
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) return undefined
  return value
}

/**
 * Multipart carries every field as text, so the JSON `optionalCents` (which demands a real
 * `number`) would reject a perfectly valid `statementTotalCents=12345` as malformed. Parsing is
 * strict on purpose: only an optionally-signed run of digits is accepted, so "12.5", "1e3" and
 * "12345; DROP" are rejected rather than silently coerced into the wrong amount.
 */
function multipartCents(value: unknown): number | null | undefined {
  if (value === undefined || value === null) return null
  if (typeof value === 'number') return optionalCents(value)
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!/^[-+]?\d+$/.test(trimmed)) return undefined
  const parsed = Number(trimmed)
  return Number.isSafeInteger(parsed) ? parsed : undefined
}

function serializeCycle(row: StatementCycleRow) {
  return {
    id: row.id,
    accountId: row.financial_account_id,
    source: row.source,
    sourceExternalId: row.source_external_id,
    label: row.cycle_label,
    periodStart: row.period_start,
    periodEnd: row.period_end,
    closingDate: row.closing_date,
    dueDate: row.due_date,
    competenceMonth: row.competence_month,
    statementCurrency: row.statement_currency,
    statementTotalCents: row.statement_total_cents,
    effectiveTotalCents: row.effective_total_cents,
    status: row.status,
    reconciliationStatus: row.reconciliation_status,
    importedAt: row.imported_at,
    closedAt: row.closed_at,
  }
}

export function registerFinanceStatementRoutes(app: FastifyInstance, deps: FinanceStatementRouteDeps): void {
  const { config, statementImports, cycles, reconciliation } = deps

  void app.register(async statementApp => {
    statementApp.addHook('preHandler', async (request, reply) => {
      if (!requireFinanceToken(request, config)) {
        return reply.code(401).send({
          error: 'unauthorized',
          message: 'FINANCE_API_TOKEN ausente ou inválido no header Authorization: Bearer <token>.',
        })
      }
    })

    /**
     * Import a closed statement. The payload carries already-extracted text and/or structured
     * lines; both are treated as opaque untrusted data by the parser.
     */
    statementApp.post('/api/finance/statements/import', async (request, reply) => {
      const body = (request.body ?? {}) as Record<string, unknown>

      const accountId = optionalString(body.accountId)
      if (!accountId) {
        return reply.code(400).send({ error: 'invalid_account_id', message: 'accountId é obrigatório no corpo.' })
      }
      if (!isStatementSource(body.source)) {
        return reply.code(400).send({ error: 'invalid_source', message: 'Origem de extrato não suportada.' })
      }
      if (!isMonthKey(body.competenceMonth)) {
        return reply
          .code(400)
          .send({ error: 'invalid_competence_month', message: 'competenceMonth deve estar no formato AAAA-MM.' })
      }
      const hasText = typeof body.rawText === 'string' && body.rawText.trim() !== ''
      const hasLines = Array.isArray(body.lines) && body.lines.length > 0
      if (!hasText && !hasLines) {
        return reply
          .code(400)
          .send({ error: 'empty_statement', message: 'Informe rawText ou lines com o conteúdo do extrato.' })
      }
      const statementTotalCents = optionalCents(body.statementTotalCents)
      if (statementTotalCents === undefined) {
        return reply
          .code(400)
          .send({ error: 'invalid_total', message: 'statementTotalCents deve ser um inteiro em centavos.' })
      }

      try {
        const result = reconciliation.importStatement({
          financialAccountId: accountId,
          source: body.source,
          competenceMonth: body.competenceMonth,
          statementCurrency: optionalString(body.statementCurrency),
          rawText: typeof body.rawText === 'string' ? body.rawText : null,
          lines: Array.isArray(body.lines) ? body.lines : undefined,
          fileName: optionalString(body.fileName),
          institutionHint: optionalString(body.institutionHint),
          cardLast4: optionalString(body.cardLast4),
          periodStart: optionalString(body.periodStart),
          periodEnd: optionalString(body.periodEnd),
          closingDate: optionalString(body.closingDate),
          dueDate: optionalString(body.dueDate),
          statementTotalCents,
          metadata: body.metadata,
        })
        return reply.code(result.created ? 201 : 200).send(result)
      } catch (error) {
        if (error instanceof AccountNotFoundError) {
          return reply.code(404).send({ error: 'account_not_found', message: 'Conta financeira não encontrada.' })
        }
        throw error
      }
    })

    void statementApp.register(multipart, {
      limits: { fileSize: MAX_PDF_BYTES, files: 1 },
      throwFileSizeLimit: false,
    })

    /**
     * Import a closed statement from an uploaded PDF file. The PDF's extracted text is
     * treated as opaque untrusted data — it is handed to the same importStatement()
     * pipeline as the JSON route, and never interpreted as instructions.
     */
    statementApp.post('/api/finance/statements/import/pdf', async (request, reply) => {
      const part = await request.file()
      if (!part) {
        return reply.code(400).send({ error: 'empty_statement', message: 'Nenhum arquivo enviado.' })
      }

      const fileBuffer = await part.toBuffer()
      if (part.file.truncated) {
        return reply.code(413).send({ error: 'pdf_too_large' })
      }

      const fields = part.fields as Record<string, { value?: unknown } | undefined>
      const fieldValue = (name: string): unknown => {
        const field = fields[name]
        if (!field || typeof field !== 'object' || !('value' in field)) return undefined
        return (field as { value?: unknown }).value
      }

      const accountId = optionalString(fieldValue('financialAccountId'))
      if (!accountId) {
        return reply.code(400).send({ error: 'invalid_account_id', message: 'financialAccountId é obrigatório.' })
      }
      const competenceMonth = fieldValue('competenceMonth')
      if (!isMonthKey(competenceMonth)) {
        return reply
          .code(400)
          .send({ error: 'invalid_competence_month', message: 'competenceMonth deve estar no formato AAAA-MM.' })
      }
      const statementTotalCents = multipartCents(fieldValue('statementTotalCents'))
      if (statementTotalCents === undefined) {
        return reply
          .code(400)
          .send({ error: 'invalid_total', message: 'statementTotalCents deve ser um inteiro em centavos.' })
      }

      const safeFileName = String(part.filename ?? '')
        .replace(/[^A-Za-z0-9._-]/g, '_')
        .slice(0, 120)

      let extracted: { text: string; pageCount: number }
      try {
        extracted = await extractPdfText(new Uint8Array(fileBuffer))
      } catch (error) {
        if (error instanceof PdfExtractionError) {
          const statusByCode: Record<string, number> = {
            not_a_pdf: 415,
            pdf_too_large: 413,
            pdf_without_text_layer: 422,
            pdf_unreadable: 422,
          }
          return reply.code(statusByCode[error.code] ?? 422).send({ error: error.code })
        }
        throw error
      }

      try {
        const result = reconciliation.importStatement({
          financialAccountId: accountId,
          source: 'PDF_UPLOAD',
          competenceMonth,
          statementCurrency: optionalString(fieldValue('statementCurrency')),
          rawText: extracted.text,
          lines: undefined,
          fileName: safeFileName,
          institutionHint: optionalString(fieldValue('institutionHint')),
          cardLast4: optionalString(fieldValue('cardLast4')),
          periodStart: optionalString(fieldValue('periodStart')),
          periodEnd: optionalString(fieldValue('periodEnd')),
          closingDate: optionalString(fieldValue('closingDate')),
          dueDate: optionalString(fieldValue('dueDate')),
          statementTotalCents,
        })
        return reply.code(result.created ? 201 : 200).send(result)
      } catch (error) {
        if (error instanceof AccountNotFoundError) {
          return reply.code(404).send({ error: 'account_not_found', message: 'Conta financeira não encontrada.' })
        }
        throw error
      }
    })

    /**
     * Reconcile an imported statement against the app's transactions.
     * `statementId` lives only in the path — it is never repeated in the body.
     */
    statementApp.post('/api/finance/statements/:statementId/reconcile', async (request, reply) => {
      const { statementId } = request.params as { statementId: string }
      const body = (request.body ?? {}) as Record<string, unknown>
      if ('statementId' in body) {
        return reply.code(400).send({
          error: 'duplicated_path_param',
          message: 'statementId pertence apenas ao caminho da URL; remova-o do corpo.',
        })
      }
      if (!statementImports.getImport(statementId)) {
        return reply.code(404).send({ error: 'statement_not_found', message: 'Extrato não encontrado.' })
      }
      try {
        return reconciliation.reconcile(statementId)
      } catch (error) {
        if (error instanceof StatementNotFoundError) {
          return reply.code(404).send({ error: 'statement_not_found', message: 'Extrato não encontrado.' })
        }
        throw error
      }
    })

    /** Cycles, optionally narrowed by account and/or competence month. */
    statementApp.get('/api/finance/cycles', async (request, reply) => {
      const query = (request.query ?? {}) as Record<string, unknown>
      const accountId = optionalString(query.accountId)
      const competenceMonth = optionalString(query.competenceMonth)
      if (competenceMonth && !isMonthKey(competenceMonth)) {
        return reply
          .code(400)
          .send({ error: 'invalid_competence_month', message: 'competenceMonth deve estar no formato AAAA-MM.' })
      }

      let rows: StatementCycleRow[]
      if (competenceMonth) rows = cycles.listByCompetence(competenceMonth, accountId ?? undefined)
      else if (accountId) rows = cycles.listByAccount(accountId)
      else rows = statementImports.listAllCycles()

      return { cycles: rows.map(serializeCycle) }
    })
  })
}
