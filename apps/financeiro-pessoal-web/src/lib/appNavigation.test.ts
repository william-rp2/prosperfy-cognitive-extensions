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

  it('não exibe card técnico Finance V2 na sidebar', () => {
    expect(appSource).not.toContain('Dados reais via Open Finance (Pluggy)')
    expect(appSource).not.toContain('Sincronização automática a cada 15 min')
  })
})
