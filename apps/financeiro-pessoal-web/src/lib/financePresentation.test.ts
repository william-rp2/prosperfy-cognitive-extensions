import { describe, expect, it } from 'vitest'

import {
  formatAssetType,
  formatClassificationStatus,
  formatItemStatus,
  formatSyncStatus,
  formatTransactionType,
  isRawEnumVisible,
  onboardingMessage,
} from '../lib/financePresentation'

describe('financePresentation pt-BR', () => {
  it('traduz enums principais', () => {
    expect(formatItemStatus('UPDATED')).toBe('Atualizado')
    expect(formatSyncStatus('success')).toBe('Sincronizado')
    expect(formatAssetType('CREDIT_CARD')).toBe('Cartão de crédito')
    expect(formatAssetType('CHECKING_ACCOUNT')).toBe('Conta corrente')
    expect(formatTransactionType('PIX_IN')).toBe('PIX recebido')
    expect(formatClassificationStatus('needs_clarification')).toBe('Precisa de confirmação')
  })

  it('detecta enum raw que não deve aparecer na UI', () => {
    expect(isRawEnumVisible('needs_clarification')).toBe(true)
    expect(isRawEnumVisible('CREDIT_CARD')).toBe(true)
    expect(isRawEnumVisible('Cartão de crédito')).toBe(false)
    expect(isRawEnumVisible('Precisa de confirmação')).toBe(false)
  })

  it('mensagens de onboarding em português', () => {
    expect(onboardingMessage('invalid_id')).toBe('ID inválido')
    expect(onboardingMessage('already_registered')).toBe('Conexão já cadastrada')
  })
})
