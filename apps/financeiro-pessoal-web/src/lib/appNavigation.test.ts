import { describe, expect, it } from 'vitest'

import appSource from '../App.tsx?raw'

describe('navegação principal', () => {
  it('não expõe POC Pluggy no menu lateral', () => {
    expect(appSource).not.toContain('POC Pluggy')
    expect(appSource).not.toMatch(/href="\/poc\/pluggy"/)
  })

  it('restringe rota POC a flag admin', () => {
    expect(appSource).toContain("VITE_FINANCE_ADMIN_POC === 'true'")
  })
})
