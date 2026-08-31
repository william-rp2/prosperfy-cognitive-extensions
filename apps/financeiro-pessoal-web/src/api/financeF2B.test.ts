import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import * as f2b from './financeF2B'

describe('finance F2B api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetchClarifications monta querystring same-origin com status', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ clarifications: [], total: 0 }), { status: 200 }))
    await f2b.fetchClarifications({ status: 'open', limit: 5 })
    const url = String(vi.mocked(fetch).mock.calls[0][0])
    expect(url).toContain('/api/finance/clarifications')
    expect(url).toContain('status=open')
    expect(url).toContain('limit=5')
  })

  it('resolveClarification usa o id no path, não repete no corpo', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ clarification: {}, alreadyResolved: false }), { status: 200 }))
    await f2b.resolveClarification('clr-1', { replyMessageId: 'msg-9' })
    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toBe('/api/finance/clarifications/clr-1/resolve')
    expect(JSON.parse(String((options as RequestInit).body))).toEqual({ replyMessageId: 'msg-9' })
  })

  it('applyCorrection envia transactionId no corpo, não como path param extra', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ correction: {}, effective: {} }), { status: 201 }))
    await f2b.applyCorrection({ transactionId: 'tx-1', field: 'category', value: 'Tecnologia' })
    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toBe('/api/finance/corrections')
    const body = JSON.parse(String((options as RequestInit).body))
    expect(body).toEqual({ transactionId: 'tx-1', field: 'category', value: 'Tecnologia' })
  })

  it('propaga mensagem de erro HTTP do backend', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ message: 'rule_not_found' }), { status: 404 }))
    await expect(f2b.deleteRule('missing')).rejects.toThrow('rule_not_found')
  })

  it('createRule nunca envia mode TRUSTED — regra nasce sugestão (invariante do servidor)', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ rule: {} }), { status: 201 }))
    await f2b.createRule({ merchantPattern: 'OPENAI', ruleType: 'CURRENCY_HINT', targetValue: 'USD' })
    const [, options] = vi.mocked(fetch).mock.calls[0]
    const body = JSON.parse(String((options as RequestInit).body))
    expect(body.mode).toBeUndefined()
  })
})
