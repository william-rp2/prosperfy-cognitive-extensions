import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import * as financeApi from '../api/finance'

describe('finance api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetchSummary retorna dados do backend', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ month: '2026-08', monthIncome: 1000, monthExpense: 200, monthResult: 800, totalBalance: 5000, openCardBalance: 300, lastSync: null }), { status: 200 }),
    )
    const summary = await financeApi.fetchSummary('2026-08')
    expect(summary.monthIncome).toBe(1000)
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/api/finance/summary')
  })

  it('propaga erro HTTP', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ message: 'unauthorized' }), { status: 401 }))
    await expect(financeApi.fetchSummary()).rejects.toThrow('unauthorized')
  })
})
