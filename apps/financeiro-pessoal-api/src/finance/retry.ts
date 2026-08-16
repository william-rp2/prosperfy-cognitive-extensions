/**
 * Backoff schedule for transient Pluggy API failures (429 / 5xx / network timeout).
 * "1ª tentativa, 5s, 30s, 2min" — 4 attempts total, no infinite retry.
 */
const BACKOFF_SCHEDULE_MS = [5_000, 30_000, 120_000]

export interface RetryableError {
  statusCode?: number
  retryAfterMs?: number
}

export function classifyError(error: unknown): RetryableError | null {
  const err = error as {
    response?: { statusCode?: number; headers?: Record<string, string | string[] | undefined> }
    code?: string
  }

  const statusCode = err?.response?.statusCode
  if (statusCode === 429 || (typeof statusCode === 'number' && statusCode >= 500)) {
    const retryAfterHeader = err.response?.headers?.['retry-after']
    const retryAfterMs = parseRetryAfter(Array.isArray(retryAfterHeader) ? retryAfterHeader[0] : retryAfterHeader)
    return { statusCode, retryAfterMs }
  }

  const networkTimeoutCodes = new Set(['ETIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'ENOTFOUND', 'EAI_AGAIN'])
  if (typeof err?.code === 'string' && networkTimeoutCodes.has(err.code)) {
    return {}
  }

  return null
}

function parseRetryAfter(value: string | undefined): number | undefined {
  if (!value) return undefined
  const seconds = Number(value)
  if (!Number.isNaN(seconds)) return seconds * 1000
  const date = Date.parse(value)
  if (!Number.isNaN(date)) return Math.max(0, date - Date.now())
  return undefined
}

export async function withRetry<T>(
  operation: () => Promise<T>,
  options: { onRetry?: (attempt: number, delayMs: number, error: unknown) => void } = {},
): Promise<T> {
  let lastError: unknown

  for (let attempt = 0; attempt <= BACKOFF_SCHEDULE_MS.length; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      const retryable = classifyError(error)
      const isLastAttempt = attempt === BACKOFF_SCHEDULE_MS.length
      if (!retryable || isLastAttempt) throw error

      const delayMs = retryable.retryAfterMs ?? BACKOFF_SCHEDULE_MS[attempt]
      options.onRetry?.(attempt + 1, delayMs, error)
      await sleep(delayMs)
    }
  }

  throw lastError
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}
