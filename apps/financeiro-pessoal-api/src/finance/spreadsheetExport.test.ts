import { describe, expect, it } from 'vitest'

import { buildOnboardingCsv, ONBOARDING_EXPORT_COLUMNS, type OnboardingExportRowData } from './spreadsheetExport.js'

function row(overrides: Partial<OnboardingExportRowData> = {}): OnboardingExportRowData {
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
    category: 'Alimentação',
    economicOwner: 'william',
    responsible: 'william',
    reimbursement: null,
    statementCycle: null,
    needsConfirmation: true,
    notes: null,
    ...overrides,
  }
}

describe('spreadsheetExport — regra 5: nunca vaza segredo/credencial/número integral', () => {
  const FORBIDDEN_PATTERNS = [/secret/i, /token/i, /password/i, /credential/i, /apikey/i, /api_key/i]

  it('CSV não contém colunas nem valores de segredo/credencial', () => {
    const csv = buildOnboardingCsv([row()])
    for (const pattern of FORBIDDEN_PATTERNS) {
      expect(csv).not.toMatch(pattern)
    }
  })

  it('header nunca inclui número de conta/cartão — apenas alias de exibição', () => {
    expect(ONBOARDING_EXPORT_COLUMNS).not.toContain('account_number')
    expect(ONBOARDING_EXPORT_COLUMNS).not.toContain('number_masked')
    expect(ONBOARDING_EXPORT_COLUMNS).toContain('account_alias')
  })

  it('mesmo se um alias malicioso tentar carregar um número de cartão, a exportação não adiciona colunas extras', () => {
    // Attacker-controlled *display* value cannot smuggle in a real secret: it is emitted as a
    // plain CSV field like any other string, never parsed as a template or structured payload.
    const maliciousAlias = 'Cartão 4111 1111 1111 1111 secret=abc token=xyz'
    const csv = buildOnboardingCsv([row({ accountAlias: maliciousAlias })])
    const lines = csv.trim().split('\r\n')
    expect(lines).toHaveLength(2) // header + one data row, nothing injected
    expect(lines[0].split(',')).toHaveLength(ONBOARDING_EXPORT_COLUMNS.length)
  })
})

describe('spreadsheetExport — formato', () => {
  it('gera cabeçalho fixo e converte centavos em decimal exato', () => {
    const csv = buildOnboardingCsv([row({ amountCents: -4599 })])
    const [header, data] = csv.trim().split('\r\n')
    expect(header).toBe(ONBOARDING_EXPORT_COLUMNS.join(','))
    expect(data).toContain('-45.99')
  })

  it('escapa campos com vírgula, aspas ou quebra de linha', () => {
    const csv = buildOnboardingCsv([row({ notes: 'Nota, com vírgula e "aspas"' })])
    expect(csv).toContain('"Nota, com vírgula e ""aspas"""')
  })

  it('action sai sempre em branco — é a coluna que o dono edita', () => {
    const csv = buildOnboardingCsv([row()])
    const dataLine = csv.trim().split('\r\n')[1]
    expect(dataLine.endsWith(',')).toBe(true)
  })
})
