import { createHmac, timingSafeEqual } from 'node:crypto'

export function maskSensitive(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(maskSensitive)
  if (!value || typeof value !== 'object') return value

  const redacted: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (/secret|token|password|authorization|clientsecret|apikey|api_key/i.test(key)) {
      redacted[key] = '[REDACTED]'
    } else {
      redacted[key] = maskSensitive(item)
    }
  }
  return redacted
}

export function safeCompare(expected: string, received: string): boolean {
  const expectedDigest = createHmac('sha256', expected).update(expected).digest()
  const receivedDigest = createHmac('sha256', expected).update(received).digest()
  return timingSafeEqual(expectedDigest, receivedDigest)
}

export function parseDate(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.trim() === '') return undefined
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return undefined
  return new Date(timestamp).toISOString().slice(0, 10)
}
