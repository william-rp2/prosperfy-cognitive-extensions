import { describe, expect, it } from 'vitest'

import { defaultAccountLabel, isTechnicalProductName, sortAccountsByPreference } from './accountPresentation.js'

describe('accountPresentation', () => {
  it('BANDEIRADO é nome técnico, não user-facing', () => {
    expect(isTechnicalProductName('BANDEIRADO')).toBe(true)
    expect(
      defaultAccountLabel({ name: 'BANDEIRADO', marketing_name: null }, 'Santander', 'CREDIT_CARD'),
    ).toBe('Santander — Cartão de crédito')
  })

  it('favoritos aparecem primeiro', () => {
    const sorted = sortAccountsByPreference([
      { isFavorite: false, displayName: 'Conta B' },
      { isFavorite: true, displayName: 'Conta A' },
      { isFavorite: false, displayName: 'Conta A' },
    ])
    expect(sorted[0].displayName).toBe('Conta A')
    expect(sorted[0].isFavorite).toBe(true)
  })
})
