import { describe, expect, it, vi } from 'vitest'

import {
  applyImportPlan,
  computeRowContentKey,
  parseOnboardingCsv,
  planImport,
  type ImportPlanContext,
} from './spreadsheetImport.js'
import { buildOnboardingCsv, ONBOARDING_EXPORT_COLUMNS, type OnboardingExportRowData } from './spreadsheetExport.js'

function baseRow(overrides: Partial<OnboardingExportRowData> = {}): OnboardingExportRowData {
  return {
    transactionId: 'tx-1',
    exportVersion: 1,
    updatedAt: '2026-08-01T00:00:00.000Z',
    date: '2026-08-01',
    competenceMonth: '2026-08',
    institution: 'Banco Exemplo',
    accountAlias: 'Conta Corrente',
    merchant: 'Padaria Central',
    originalDescription: 'PADARIA CENTRAL LTDA',
    amountCents: -4599,
    currency: 'BRL',
    category: null,
    economicOwner: null,
    responsible: null,
    reimbursement: null,
    statementCycle: null,
    needsConfirmation: true,
    notes: null,
    ...overrides,
  }
}

function contextAllowing(txIds: string[], overrides: Partial<ImportPlanContext> = {}): ImportPlanContext {
  const known = new Set(txIds)
  return {
    transactionExists: id => known.has(id),
    currentRevision: () => null,
    alreadyApplied: () => false,
    ...overrides,
  }
}

/** Replaces one CSV cell by column name on the (single) data line — test helper only. */
function editCell(csv: string, column: (typeof ONBOARDING_EXPORT_COLUMNS)[number], value: string): string {
  const idx = ONBOARDING_EXPORT_COLUMNS.indexOf(column)
  const [header, data, ...rest] = csv.trim().split('\r\n')
  const cells = data.split(',')
  cells[idx] = value
  return [header, cells.join(','), ...rest].join('\r\n')
}

describe('spreadsheetImport — parsing (dado não confiável)', () => {
  it('rejeita arquivo cujo cabeçalho não bate com o schema conhecido', () => {
    const result = parseOnboardingCsv('a,b,c\n1,2,3\n')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toBe('schema_mismatch')
  })

  it('faz round-trip export -> parse preservando os valores', () => {
    const csv = buildOnboardingCsv([baseRow({ category: 'Mercado' })])
    const parsed = parseOnboardingCsv(csv)
    expect(parsed.ok).toBe(true)
    if (parsed.ok) {
      expect(parsed.rows).toHaveLength(1)
      expect(parsed.rows[0].fields.transaction_id).toBe('tx-1')
      expect(parsed.rows[0].fields.category).toBe('Mercado')
    }
  })
})

describe('spreadsheetImport — regra 6: conteúdo do arquivo é dado, nunca instrução', () => {
  it('rejeita transaction_id desconhecido/obsoleto em vez de aceitar cegamente', () => {
    const csv = buildOnboardingCsv([baseRow({ transactionId: 'tx-stale' })])
    const { plan } = planImport(csv, contextAllowing([])) // nothing known
    expect(plan[0].outcome).toBe('rejected')
    expect(plan[0].reason).toBe('unknown_transaction_id')
  })

  it('rejeita valor de action fora da lista fechada — nunca interpretado como comando', () => {
    const csv = editCell(buildOnboardingCsv([baseRow()]), 'action', 'DROP TABLE finance_clarifications')
    const { plan } = planImport(csv, contextAllowing(['tx-1']))
    expect(plan[0].outcome).toBe('rejected')
    expect(plan[0].reason).toBe('invalid_action')
  })

  it('rejeita reimbursement que não é um objeto JSON válido, mesmo parecendo código', () => {
    const csv = editCell(buildOnboardingCsv([baseRow()]), 'reimbursement', 'require(child_process)')
    const { plan } = planImport(csv, contextAllowing(['tx-1']))
    expect(plan[0].outcome).toBe('rejected')
    expect(plan[0].reason).toBe('invalid_reimbursement')
  })

  it('rejeita competence_month fora do formato AAAA-MM', () => {
    const csv = editCell(buildOnboardingCsv([baseRow()]), 'competence_month', 'not-a-month')
    const { plan } = planImport(csv, contextAllowing(['tx-1']))
    expect(plan[0].outcome).toBe('rejected')
    expect(plan[0].reason).toBe('invalid_competence_month')
  })

  it('célula em branco significa "sem mudança", nunca limpa um campo por acidente', () => {
    // All EDITABLE_FIELDS blank — including competence_month, which baseRow() sets by default.
    const csv = buildOnboardingCsv([baseRow({ competenceMonth: null })])
    const { plan } = planImport(csv, contextAllowing(['tx-1']))
    expect(plan[0].outcome).toBe('skipped')
    expect(plan[0].reason).toBe('no_op')
    expect(plan[0].changes).toHaveLength(0)
  })
})

describe('spreadsheetImport — conflito e dry-run', () => {
  it('detecta conflito quando o registro mudou depois do export (proteção contra planilha desatualizada)', () => {
    const csv = editCell(buildOnboardingCsv([baseRow({ updatedAt: '2026-08-01T00:00:00.000Z' })]), 'category', 'Mercado')
    const { plan } = planImport(csv, contextAllowing(['tx-1'], { currentRevision: () => '2026-08-05T00:00:00.000Z' }))
    expect(plan[0].outcome).toBe('conflict')
  })

  it('dry-run nunca escreve — apenas retorna o plano', () => {
    const csv = editCell(buildOnboardingCsv([baseRow()]), 'category', 'Mercado')
    const corrections = { applyCorrection: vi.fn(), projectAttribution: vi.fn(), listActive: vi.fn(() => new Map()) } as any
    const { plan } = planImport(csv, contextAllowing(['tx-1']))
    expect(plan[0].outcome).toBe('applied')
    expect(corrections.applyCorrection).not.toHaveBeenCalled()
  })
})

describe('spreadsheetImport — regra 7 (via idempotência de importação em lote)', () => {
  it('planImport marca como skipped uma linha cujo conteúdo já foi aplicado antes', () => {
    const csv = editCell(buildOnboardingCsv([baseRow({ competenceMonth: null })]), 'category', 'Mercado')
    const key = computeRowContentKey('tx-1', [{ field: 'category', newValue: 'Mercado' }], '')
    const ctx = contextAllowing(['tx-1'], { alreadyApplied: k => k === key })
    const { plan } = planImport(csv, ctx)
    expect(plan[0].outcome).toBe('skipped')
    expect(plan[0].reason).toBe('already_applied')
  })
})

describe('applyImportPlan — regra 7: reimportar não duplica', () => {
  function makeRepos() {
    const applied: Array<{ txId: string; field: string; value: string | null }> = []
    const importRows = new Map<string, { id: string; status: string; applied_at: string | null }>()

    const corrections = {
      applyCorrection: vi.fn((input: any) => {
        applied.push({ txId: input.pluggyTransactionId, field: input.field, value: input.newValue })
        return { id: 'corr-1' }
      }),
      projectAttribution: vi.fn(),
    } as any

    const clarifications = {
      listOpenForTransaction: vi.fn(() => []),
      resolve: vi.fn(),
    } as any

    const onboarding = {
      getImportRow: vi.fn((batchId: string, txId: string) => importRows.get(`${batchId}:${txId}`)),
      recordImportRow: vi.fn((input: any) => {
        const rec = { id: `${input.importBatchId}:${input.pluggyTransactionId}`, status: input.status, applied_at: input.appliedAt }
        importRows.set(`${input.importBatchId}:${input.pluggyTransactionId}`, rec)
        return rec
      }),
    } as any

    return { corrections, clarifications, onboarding, applied }
  }

  it('primeira aplicação escreve a correção; reimportar o mesmo conteúdo não duplica', () => {
    const { corrections, clarifications, onboarding, applied } = makeRepos()
    const csv = editCell(buildOnboardingCsv([baseRow({ competenceMonth: null })]), 'category', 'Mercado')

    const ctx1: ImportPlanContext = contextAllowing(['tx-1'], {
      alreadyApplied: (key, txId) => Boolean(onboarding.getImportRow(key, txId)),
    })
    const { plan: plan1 } = planImport(csv, ctx1)
    applyImportPlan(plan1, { corrections, clarifications, onboarding, actorId: 'owner', reason: 'test' })
    expect(applied).toHaveLength(1)

    // Reimport of the exact same file/content.
    const { plan: plan2 } = planImport(csv, ctx1)
    const results2 = applyImportPlan(plan2, { corrections, clarifications, onboarding, actorId: 'owner', reason: 'test' })

    expect(applied).toHaveLength(1) // still just one correction write
    expect(results2[0].outcome).not.toBe('applied')
  })
})
