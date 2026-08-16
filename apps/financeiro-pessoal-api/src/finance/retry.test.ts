import { afterEach, describe, expect, it, vi } from 'vitest'

import { classifyError, withRetry } from './retry.js'

function httpError(statusCode: number, headers: Record<string, string> = {}) {
  const error = new Error(`http ${statusCode}`) as Error & { response: { statusCode: number; headers: Record<string, string> } }
  error.response = { statusCode, headers }
  return error
}

function networkError(code: string) {
  const error = new Error(code) as Error & { code: string }
  error.code = code
  return error
}

afterEach(() => {
  vi.useRealTimers()
})

describe('classifyError', () => {
  it('classifica 429 como retryable e lê retry-after em segundos', () => {
    const result = classifyError(httpError(429, { 'retry-after': '2' }))
    expect(result).toEqual({ statusCode: 429, retryAfterMs: 2000 })
  })

  it('classifica 5xx como retryable', () => {
    expect(classifyError(httpError(503))).toMatchObject({ statusCode: 503 })
  })

  it('classifica timeout/erro de rede como retryable', () => {
    expect(classifyError(networkError('ETIMEDOUT'))).toEqual({})
  })

  it('não classifica 400 como retryable', () => {
    expect(classifyError(httpError(400))).toBeNull()
  })

  it('não classifica erro genérico sem response/code como retryable', () => {
    expect(classifyError(new Error('boom'))).toBeNull()
  })
})

describe('withRetry', () => {
  it('retenta erro transitório e sucede na segunda tentativa', async () => {
    vi.useFakeTimers()
    let attempts = 0
    const operation = vi.fn(async () => {
      attempts += 1
      if (attempts < 2) throw httpError(503)
      return 'ok'
    })

    const promise = withRetry(operation)
    await vi.advanceTimersByTimeAsync(5_000)

    await expect(promise).resolves.toBe('ok')
    expect(operation).toHaveBeenCalledTimes(2)
  })

  it('desiste após esgotar o schedule (4 tentativas) e propaga o erro original', async () => {
    vi.useFakeTimers()
    const error = httpError(500)
    const operation = vi.fn(async () => {
      throw error
    })

    const promise = withRetry(operation)
    promise.catch(() => {}) // avoid unhandled-rejection warning while timers advance
    await vi.advanceTimersByTimeAsync(200_000)

    await expect(promise).rejects.toBe(error)
    expect(operation).toHaveBeenCalledTimes(4)
  })

  it('não retenta erro não-transitório (ex: 400) — falha na primeira tentativa', async () => {
    const error = httpError(400)
    const operation = vi.fn(async () => {
      throw error
    })

    await expect(withRetry(operation)).rejects.toBe(error)
    expect(operation).toHaveBeenCalledTimes(1)
  })
})
